import hashlib
import secrets

from fastapi import Header

from src.config import get_settings
from src.exceptions import UnauthorizedError


async def verify_api_key(api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    if not api_key or not secrets.compare_digest(api_key, get_settings().api_key):
        raise UnauthorizedError(
            "Missing or invalid 'X-API-Key' header. Include the API key issued to your application."
        )
    return api_key


def caller_id(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
