"""Server-side validation for Telegram Mini App `initData`.

Why this exists: the ad-unlock page runs inside a Telegram WebView and must
prove to our backend that a request really came from Telegram for a given
user — otherwise anyone could call the "unlock" API directly and skip the
ads entirely. Telegram signs `initData` with the bot token; we re-derive the
same signature and compare it. See:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl

MAX_INIT_DATA_AGE = 3600  # seconds; reject stale/replayed initData


def validate_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    """Return the parsed `user` dict if `init_data` is authentic and fresh, else None."""
    if not init_data or not bot_token:
        return None

    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date = int(pairs.get("auth_date", 0))
    if time.time() - auth_date > MAX_INIT_DATA_AGE:
        return None

    try:
        return json.loads(pairs.get("user", "{}"))
    except (json.JSONDecodeError, TypeError):
        return None
