"""Encryption of saved connection secrets (passwords, tokens, API keys).

Secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using the key in
``INSIGHTSQL_SECRET_KEY``. Only the encrypted token is stored; plaintext secrets exist only in
memory while a connection is used. The key itself is never stored by the app, and its value is
redacted from logs (``logging_setup.SECRET_SETTINGS``).
"""

from cryptography.fernet import Fernet, InvalidToken

from src import config

KEY_HELP = ('Set INSIGHTSQL_SECRET_KEY in the .env file. Create a key with: python -c "from '
            'cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')


class SecretError(Exception):
    """Secrets cannot be encrypted or read. ``message`` is safe to show to users."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _fernet() -> Fernet:
    key = config.get_secret_key()
    if not key:
        raise SecretError("Saving passwords and tokens needs an encryption key. " + KEY_HELP)
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise SecretError("INSIGHTSQL_SECRET_KEY is not a valid key. " + KEY_HELP) from None


def available() -> bool:
    try:
        _fernet()
    except SecretError:
        return False
    return True


def encrypt(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode("utf-8"))


def decrypt(token: bytes) -> str:
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken:
        raise SecretError("A saved password or token cannot be read with the current INSIGHTSQL_SECRET_KEY "
                          "(was the key changed?). Enter the secret again.") from None
