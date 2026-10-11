"""Where connections may go: protection against server-side request forgery (SSRF).

Every database or API connection first resolves its host name and checks **every** address
it resolves to. Addresses on loopback, private, link-local, shared, multicast, reserved or
unspecified networks are refused unless that exact ``host`` or ``host:port`` is listed in
``INSIGHTSQL_ALLOWED_PRIVATE_HOSTS``. Cloud metadata endpoints are refused always, even when
listed. Numeric tricks (``2130706433``, ``0x7f.1``, ``::ffff:127.0.0.1``) are normalised by
the resolver before checking, so they cannot slip through as "names".

Residual risk (documented): a name could resolve differently between this check and the
driver's own lookup (DNS rebinding). Database connections are made to the checked address;
API requests are re-checked on every request and never follow redirects.
"""

import ipaddress
import socket
from dataclasses import dataclass

from src import config

METADATA_ADDRESSES = frozenset({
    ipaddress.ip_address("169.254.169.254"),  # AWS, GCP, Azure, OpenStack, DigitalOcean
    ipaddress.ip_address("169.254.170.2"),  # AWS ECS task metadata
    ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud
    ipaddress.ip_address("fd00:ec2::254"),  # AWS IPv6
})
METADATA_NAMES = frozenset({"metadata.google.internal", "metadata", "metadata.azure.com"})


class DestinationError(Exception):
    """The destination is not allowed or cannot be found. ``message`` is user-safe."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Destination:
    host: str
    port: int
    addresses: tuple[str, ...]  # checked IP addresses, in resolver order


def _is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def check(host: str, port: int) -> Destination:
    """Resolve ``host`` and return the checked destination, or raise ``DestinationError``."""
    host = (host or "").strip().lower().rstrip(".")
    if not host or any(c in host for c in "/@?#\\ ") or not 0 < int(port) < 65536:
        raise DestinationError("Enter a valid host name and port.")
    if host.strip("[]") in METADATA_NAMES:
        raise DestinationError("Cloud metadata addresses can never be used.")
    try:
        infos = socket.getaddrinfo(host.strip("[]"), port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise DestinationError(f"The host '{host}' could not be found.") from None
    addresses = []
    for info in infos:
        text = info[4][0].split("%")[0]  # drop an IPv6 zone index
        if text not in addresses:
            addresses.append(text)
    if not addresses:
        raise DestinationError(f"The host '{host}' could not be found.")
    allowed = config.get_allowed_private_hosts()
    listed = host in allowed or f"{host}:{port}" in allowed
    for text in addresses:
        address = ipaddress.ip_address(text)
        mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
        if address in METADATA_ADDRESSES or mapped in METADATA_ADDRESSES:
            raise DestinationError("Cloud metadata addresses can never be used.")
        if not _is_public(address) and not listed:
            raise DestinationError(
                f"'{host}' is on a private or local network ({text}), which connections may not reach. "
                f"An administrator can allow it by adding {host}:{port} to INSIGHTSQL_ALLOWED_PRIVATE_HOSTS.")
    return Destination(host, int(port), tuple(addresses))
