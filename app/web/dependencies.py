"""
initData validation for Telegram Mini App.

Flow:
1. Mini App opens → gets raw initData from window.Telegram.WebApp.initData
2. Frontend sends it as X-Init-Data header on every API call
3. Backend validates HMAC-SHA256 signature using bot token
4. On success: returns validated user data
5. On failure: raises HTTP 401

Reference: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, unquote

from fastapi import Header, HTTPException, status

from app.config import settings

# Maximum age of initData in seconds (24 hours)
_MAX_INIT_DATA_AGE = 86400


def _extract_init_data(init_data: str) -> dict[str, list[str]]:
    """Parse raw initData query string into a dict of key→[values]."""
    return parse_qs(init_data, keep_blank_values=True)


def _build_data_check_string(params: dict[str, list[str]]) -> str:
    """Build the data_check_string from all params except 'hash'.

    Sorted alphabetically by key, joined as key=value\\n.
    """
    items = []
    for key, values in params.items():
        if key == "hash":
            continue
        # decode_url for values
        value = unquote(values[0])
        items.append(f"{key}={value}")
    items.sort()
    return "\n".join(items)


def _compute_signature(data_check_string: str, bot_token: str) -> str:
    """Compute HMAC-SHA256 signature of data_check_string using bot token.

    1. Derive secret_key: HMAC-SHA256(b"WebAppData", bot_token)
    2. Compute signature: HMAC-SHA256(secret_key, data_check_string)
    """
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()
    signature = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return signature


def validate_init_data(
    x_init_data: str | None = Header(None),
    x_skip_auth: str | None = Header(None),
) -> dict:
    """Validate Telegram Mini App initData.

    Returns parsed initData dict (with 'user' key) on success.
    Raises 401 on invalid/missing/expired initData.

    If X-Skip-Auth header is set to any truthy value (for local dev/testing),
    returns a placeholder user dict. NEVER enable in production.
    """
    # Normalize: when called outside FastAPI request context,
    # Header(None) stays as a Header object (which is truthy).
    # Treat it the same as "header not present".
    if not isinstance(x_skip_auth, (str, type(None))):
        x_skip_auth = None

    # Skip auth for local development / testing
    if x_skip_auth:
        return {
            "user": {"id": 12345, "first_name": "Dev", "last_name": "User"},
            "auth_date": int(time.time()),
            "hash": "skip",
        }

    if not x_init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Init-Data header",
        )

    # Check that bot token is available (needed for signature validation)
    bot_token = settings.telegram_token
    if not bot_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="TELEGRAM_TOKEN not configured",
        )

    params = _extract_init_data(x_init_data)

    # Check hash presence
    if "hash" not in params:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing hash in initData",
        )

    provided_hash = params["hash"][0]

    # Build data_check_string and compute signature
    data_check_string = _build_data_check_string(params)
    computed_signature = _compute_signature(data_check_string, bot_token)

    # Compare signatures (constant-time comparison via hmac.compare_digest)
    if not hmac.compare_digest(computed_signature, provided_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid initData signature",
        )

    # Check auth_date freshness
    if "auth_date" in params:
        auth_date = int(params["auth_date"][0])
        if time.time() - auth_date > _MAX_INIT_DATA_AGE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="initData expired",
            )

    # Parse user field into a dict
    result = {}
    for key, values in params.items():
        val = values[0]
        if key == "user":
            try:
                val = json.loads(unquote(val))
            except (json.JSONDecodeError, ValueError):
                # If user can't be parsed, keep it as string
                pass
        result[key] = val

    return result
