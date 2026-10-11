"""REST APIs: fetch JSON records from one endpoint, with authentication and pagination.

Safety:
- Requests go only to the profile's base address: the endpoint is a path below it, and "next
  page" links must stay on the same scheme, host and port. Every request's host is checked by
  ``network.check`` (SSRF protection), and redirects are never followed.
- https is required (plain http only for allow-listed hosts, checked in ``profiles``).
- The secret goes only in a header (never in the URL); proxy settings from the environment are
  ignored; TLS certificates are verified.
- Limits: timeout per request, response size, number of pages and records. Rate limits (429/503)
  are retried a few times, waiting as the server asks (capped).
- Responses must be JSON; records must be a list of objects.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit, urlunsplit

import httpx
import pandas as pd

from src import config
from src.connectors import network
from src.connectors.profiles import ConnectorError, Profile

logger = logging.getLogger(__name__)

PAGINATION = {"none": "One request", "page": "Page number", "offset": "Offset and limit",
              "next_link": "Link to the next page in the response"}
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_PAGES = 50
MAX_ATTEMPTS = 3
MAX_RETRY_WAIT = 10.0
PREVIEW_RECORDS = 100


@dataclass(frozen=True)
class Endpoint:
    path: str  # below the base address, e.g. "/orders"
    params: dict[str, str] = field(default_factory=dict)  # fixed query parameters (not secrets)
    records_path: str = ""  # where the list is in the JSON, e.g. "data.items" ("" = the whole body)
    pagination: str = "none"  # a key of PAGINATION
    page_param: str = "page"
    size_param: str = "per_page"
    page_size: int = 100
    first_page: int = 1
    offset_param: str = "offset"
    limit_param: str = "limit"
    next_path: str = "next"  # JSON path of the next-page URL (pagination "next_link")
    max_pages: int = MAX_PAGES

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Endpoint":
        return cls(**data)


@dataclass
class FetchResult:
    records: list[dict]
    pages: list[bytes]  # the raw JSON bodies, kept as the import's original
    truncated: bool = False


def validate_endpoint(endpoint: Endpoint) -> None:
    path = endpoint.path.strip()
    if not path.startswith("/") or path.startswith("//") or "://" in path or "@" in path or "\\" in path:
        raise ConnectorError("The endpoint must be a path starting with '/', e.g. /orders.")
    if any(part == ".." for part in path.split("?")[0].split("/")):
        raise ConnectorError("The endpoint path must not contain '..'.")
    if "?" in path or "#" in path:
        raise ConnectorError("Put query parameters in the parameters field, not in the path.")
    if endpoint.pagination not in PAGINATION:
        raise ConnectorError("Choose a pagination method.")
    if not 1 <= endpoint.page_size <= 1000 or not 1 <= endpoint.max_pages <= 500:
        raise ConnectorError("Page size must be 1–1000 and the page limit 1–500.")


def _origin(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    return parts.scheme, (parts.hostname or "").lower(), parts.port or (443 if parts.scheme == "https" else 80)


def _headers(profile: Profile, secret: str | None) -> tuple[dict, httpx.Auth | None]:
    headers = {"Accept": "application/json", "User-Agent": "InsightSQL"}
    auth = profile.settings.get("auth", "none")
    if auth == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif auth == "header":
        headers[profile.settings["auth_header"]] = secret
    if auth == "basic":
        return headers, httpx.BasicAuth(profile.settings["username"], secret or "")
    return headers, None


def _get(client: httpx.Client, url: str, params: dict, base: tuple) -> bytes:
    """One GET with checks, size limit and polite retries. Returns the body."""
    scheme, host, port = _origin(url)
    if (scheme, host, port) != base:
        raise ConnectorError("The API pointed to a different address; only the connection's own address is used.")
    try:
        network.check(host, port)
    except network.DestinationError as exc:
        raise ConnectorError(exc.message) from None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            # params=None keeps a next-page link's own query string (an empty dict would erase it).
            with client.stream("GET", url, params=params or None) as response:
                status = response.status_code
                if status in (429, 503) and attempt < MAX_ATTEMPTS:
                    wait = _retry_after(response.headers.get("Retry-After"), attempt)
                    logger.info("API rate limit (%s); retrying in %.1f s", status, wait)
                    time.sleep(wait)
                    continue
                _check_status(response)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ConnectorError(f"The API response is larger than {MAX_RESPONSE_BYTES // 1_048_576} MB.")
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type.lower():
                    raise ConnectorError(f"The API did not return JSON (it returned '{content_type or 'no type'}').")
                return bytes(body)
        except httpx.TimeoutException:
            raise ConnectorError("The API did not answer in time.", retryable=True) from None
        except httpx.HTTPError as exc:
            logger.warning("API request failed: %s", type(exc).__name__)
            raise ConnectorError("Could not reach the API. Check the address and your network.", retryable=True) from None
    raise ConnectorError("The API is rate limiting requests. Try again later.", retryable=True)


def _retry_after(value: str | None, attempt: int) -> float:
    try:
        wait = float(value) if value is not None else float(attempt)
    except ValueError:
        wait = float(attempt)
    return max(0.0, min(wait, MAX_RETRY_WAIT))


def _check_status(response: httpx.Response) -> None:
    status = response.status_code
    if 300 <= status < 400:
        raise ConnectorError("The API answered with a redirect. Redirects are not followed for security; use the "
                             "final address in the connection.")
    if status in (401, 403):
        raise ConnectorError("The API rejected the credentials (or they lack permission).")
    if status == 404:
        raise ConnectorError("The API endpoint was not found. Check the path.")
    if status == 429:
        raise ConnectorError("The API is rate limiting requests. Try again later.", retryable=True)
    if status >= 400:
        raise ConnectorError(f"The API returned an error (HTTP {status}).", retryable=status >= 500)


def _dig(data, path: str):
    for key in [k for k in path.split(".") if k]:
        if isinstance(data, dict) and key in data:
            data = data[key]
        elif isinstance(data, list) and key.isdigit() and int(key) < len(data):
            data = data[int(key)]
        else:
            return None
    return data


def _records(body: bytes, endpoint: Endpoint) -> tuple[list[dict], object]:
    try:
        document = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise ConnectorError("The API response is not valid JSON.") from None
    records = _dig(document, endpoint.records_path)
    if not isinstance(records, list):
        where = f"at '{endpoint.records_path}'" if endpoint.records_path else "at the top level"
        raise ConnectorError(f"No list of records was found {where} of the response. Set where the records are.")
    if not all(isinstance(r, dict) for r in records):
        raise ConnectorError("The records must be JSON objects (key: value), not plain values.")
    return records, document


def fetch(profile: Profile, secret: str | None, endpoint: Endpoint, max_records: int) -> FetchResult:
    """All records (every page). Raises ``ConnectorError`` if there are more than ``max_records``
    records or more pages than ``endpoint.max_pages`` (nothing is dropped silently)."""
    validate_endpoint(endpoint)
    base_url = profile.settings["base_url"]
    base = _origin(base_url)
    headers, auth = _headers(profile, secret)
    url = base_url + endpoint.path
    params = dict(endpoint.params)
    result = FetchResult([], [])
    page, offset = endpoint.first_page, 0
    with httpx.Client(headers=headers, auth=auth, timeout=config.get_connector_timeout(), follow_redirects=False,
                      trust_env=False, verify=True) as client:
        for number in range(1, endpoint.max_pages + 2):
            if number > endpoint.max_pages:
                raise ConnectorError(f"The API has more than {endpoint.max_pages} pages. Increase the page limit or "
                                     "narrow the request with parameters.")
            if endpoint.pagination == "page":
                params.update({endpoint.page_param: str(page), endpoint.size_param: str(endpoint.page_size)})
            elif endpoint.pagination == "offset":
                params.update({endpoint.offset_param: str(offset), endpoint.limit_param: str(endpoint.page_size)})
            body = _get(client, url, params, base)
            records, document = _records(body, endpoint)
            result.pages.append(body)
            result.records.extend(records)
            if len(result.records) > max_records:
                raise ConnectorError(f"The API returned more than {max_records:,} records, the import limit.")
            if endpoint.pagination == "none":
                break
            if endpoint.pagination == "next_link":
                link = _dig(document, endpoint.next_path)
                if not link:
                    break
                if not isinstance(link, str):
                    raise ConnectorError("The next-page link in the response is not text.")
                url, params = _absolute(link, base_url), {}
                continue
            if len(records) < endpoint.page_size:
                break
            page += 1
            offset += len(records)
    return result


def _absolute(link: str, base_url: str) -> str:
    """Resolve a next-page link; relative links are taken from the base address's origin."""
    if link.startswith("/") and not link.startswith("//"):
        scheme, netloc = urlsplit(base_url)[:2]
        return urlunsplit((scheme, netloc, *urlsplit(link)[2:]))
    return link


def preview(profile: Profile, secret: str | None, endpoint: Endpoint) -> pd.DataFrame:
    """The first page only (up to 100 records), flattened."""
    params = dict(endpoint.params)
    if endpoint.pagination == "page":
        params.update({endpoint.page_param: str(endpoint.first_page), endpoint.size_param: str(endpoint.page_size)})
    elif endpoint.pagination == "offset":
        params.update({endpoint.offset_param: "0", endpoint.limit_param: str(endpoint.page_size)})
    first = Endpoint(**{**endpoint.to_dict(), "params": params, "pagination": "none", "max_pages": 1})
    return to_frame(fetch(profile, secret, first, max_records=10**9).records[:PREVIEW_RECORDS])


def to_frame(records: list[dict]) -> pd.DataFrame:
    """Records as text columns. Nested objects become ``parent_child`` columns (one level);
    deeper values and lists are kept as JSON text, so nothing is dropped."""
    if not records:
        return pd.DataFrame(dtype=object)
    flat = pd.json_normalize(records, max_level=1, sep="_")
    return flat.apply(lambda column: column.map(_text)).astype(object)


def _text(value) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, float):
        return repr(value)
    return str(value)
