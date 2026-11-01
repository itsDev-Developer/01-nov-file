"""Drop-in client for the file-store bot's Link Generation API.
Copy this ONE file into any bot you want to monetize through it.

Sync version needs nothing but the standard library. If your bot is already
async (most Pyrogram/aiogram/python-telegram-bot-v20+ bots are), use
MonetizeClientAsync instead, which reuses one aiohttp session.

    from monetize_client import MonetizeClient
    client = MonetizeClient("https://your-filestore-bot.example.com", "fsk_...")
    link = client.single(source_chat_id=-1001234567890, message_id=45)
    # send `link` to your user instead of the file

    # premium (key needs the 'premium' scope) — e.g. from your payment-confirmed handler:
    client.premium_add(user_id=123456789, days=30, request_id="order-8841")

    # or, inside an async bot:
    from monetize_client import MonetizeClientAsync
    client = MonetizeClientAsync("https://your-filestore-bot.example.com", "fsk_...")
    link = await client.single(source_chat_id=-1001234567890, message_id=45)
    await client.close()
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class MonetizeApiError(Exception):
    def __init__(self, status: int, code: str, message: str, payload: dict = None):
        super().__init__(f"[{status}] {code}: {message}")
        self.status, self.code, self.message, self.payload = status, code, message, payload or {}


def _premium_add_body(user_id, days, mode, notify, request_id):
    body = {"user_id": user_id, "mode": mode, "notify": notify}
    if days is not None:        # omit => permanent
        body["days"] = days
    if request_id:              # makes retries safe (applied once)
        body["request_id"] = request_id
    return body


class MonetizeClient:
    """Synchronous client — standard library only."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    def _request(self, method: str, path: str, json_body: dict = None):
        url = self.base_url + path
        data = json.dumps(json_body).encode() if json_body is not None else None
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if data is not None:
            headers["Content-Type"] = "application/json"

        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                body = e.read().decode()
                try:
                    payload = json.loads(body)
                except ValueError:
                    payload = {"error": "unknown", "message": body[:200]}
                if e.code == 429 and attempt < self.max_retries - 1:
                    time.sleep(int(e.headers.get("Retry-After", 2)))
                    continue
                raise MonetizeApiError(e.code, payload.get("error", "unknown"), payload.get("message", ""), payload)
            except urllib.error.URLError as e:
                if attempt < self.max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise MonetizeApiError(0, "network_error", str(e))

    def ping(self) -> dict:
        return self._request("GET", "/api/v1/ping")

    def usage(self) -> dict:
        return self._request("GET", "/api/v1/usage")

    def single(self, *, source_chat_id: int = None, message_id: int = None,
               url: str = None, type: str = "document", caption: str = None) -> str:
        """One of (source_chat_id + message_id) or url is required. Returns the share link."""
        body = {"caption": caption} if caption else {}
        if source_chat_id is not None and message_id is not None:
            body.update(source_chat_id=source_chat_id, message_id=message_id)
        elif url is not None:
            body.update(url=url, type=type)
        else:
            raise ValueError("Provide source_chat_id+message_id, or url.")
        return self._request("POST", "/api/v1/links/single", body)["link"]

    def batch(self, *, source_chat_id: int = None, message_ids: list = None, items: list = None) -> dict:
        """Either (source_chat_id + message_ids) or a pre-built `items` list.
        Returns the full response (has 'link', 'count', 'skipped', ...)."""
        if items is not None:
            body = {"items": items}
        elif source_chat_id is not None and message_ids:
            body = {"source_chat_id": source_chat_id, "message_ids": message_ids}
        else:
            raise ValueError("Provide items=[...], or source_chat_id + message_ids=[...].")
        return self._request("POST", "/api/v1/links/batch", body)

    # --- premium & users (need a key with the 'premium' / 'users' scope) ---

    def premium_add(self, user_id: int, days: int = None, *, mode: str = "extend",
                    notify: bool = False, request_id: str = None) -> dict:
        """days=None => permanent. Pass a unique request_id (your order id) so a retried webhook can't extend twice."""
        return self._request("POST", "/api/v1/premium/add", _premium_add_body(user_id, days, mode, notify, request_id))

    def premium_remove(self, user_id: int, *, notify: bool = False) -> dict:
        return self._request("POST", "/api/v1/premium/remove", {"user_id": user_id, "notify": notify})

    def premium_status(self, user_id: int) -> dict:
        return self._request("GET", f"/api/v1/premium/{int(user_id)}")

    def premium_list(self, limit: int = 50, offset: int = 0) -> dict:
        return self._request("GET", f"/api/v1/premium?limit={int(limit)}&offset={int(offset)}")

    def user_info(self, user_id: int) -> dict:
        return self._request("GET", f"/api/v1/users/{int(user_id)}")

    def ban(self, user_id: int) -> dict:
        return self._request("POST", "/api/v1/users/ban", {"user_id": user_id})

    def unban(self, user_id: int) -> dict:
        return self._request("POST", "/api/v1/users/unban", {"user_id": user_id})

    def stats(self) -> dict:
        return self._request("GET", "/api/v1/stats")


class MonetizeClientAsync:
    """Async client for aiohttp-based bots. Reuses one session; call close()
    when your bot shuts down (or use it as an async context manager)."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30, max_retries: int = 3):
        import aiohttp  # imported lazily so the sync class above needs no extra dependency
        self._aiohttp = aiohttp
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self._session = None

    def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = self._aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.api_key}"}, timeout=self.timeout
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def _request(self, method: str, path: str, json_body: dict = None):
        import asyncio
        session = self._get_session()
        for attempt in range(self.max_retries):
            try:
                async with session.request(method, self.base_url + path, json=json_body) as resp:
                    payload = await resp.json()
                    if resp.status >= 400:
                        if resp.status == 429 and attempt < self.max_retries - 1:
                            await asyncio.sleep(int(resp.headers.get("Retry-After", 2)))
                            continue
                        raise MonetizeApiError(resp.status, payload.get("error", "unknown"), payload.get("message", ""), payload)
                    return payload
            except self._aiohttp.ClientError as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise MonetizeApiError(0, "network_error", str(e))

    async def ping(self) -> dict:
        return await self._request("GET", "/api/v1/ping")

    async def usage(self) -> dict:
        return await self._request("GET", "/api/v1/usage")

    async def single(self, *, source_chat_id: int = None, message_id: int = None,
                     url: str = None, type: str = "document", caption: str = None) -> str:
        body = {"caption": caption} if caption else {}
        if source_chat_id is not None and message_id is not None:
            body.update(source_chat_id=source_chat_id, message_id=message_id)
        elif url is not None:
            body.update(url=url, type=type)
        else:
            raise ValueError("Provide source_chat_id+message_id, or url.")
        return (await self._request("POST", "/api/v1/links/single", body))["link"]

    async def batch(self, *, source_chat_id: int = None, message_ids: list = None, items: list = None) -> dict:
        if items is not None:
            body = {"items": items}
        elif source_chat_id is not None and message_ids:
            body = {"source_chat_id": source_chat_id, "message_ids": message_ids}
        else:
            raise ValueError("Provide items=[...], or source_chat_id + message_ids=[...].")
        return await self._request("POST", "/api/v1/links/batch", body)

    # --- premium & users (need a key with the 'premium' / 'users' scope) ---

    async def premium_add(self, user_id: int, days: int = None, *, mode: str = "extend",
                          notify: bool = False, request_id: str = None) -> dict:
        return await self._request("POST", "/api/v1/premium/add", _premium_add_body(user_id, days, mode, notify, request_id))

    async def premium_remove(self, user_id: int, *, notify: bool = False) -> dict:
        return await self._request("POST", "/api/v1/premium/remove", {"user_id": user_id, "notify": notify})

    async def premium_status(self, user_id: int) -> dict:
        return await self._request("GET", f"/api/v1/premium/{int(user_id)}")

    async def premium_list(self, limit: int = 50, offset: int = 0) -> dict:
        return await self._request("GET", f"/api/v1/premium?limit={int(limit)}&offset={int(offset)}")

    async def user_info(self, user_id: int) -> dict:
        return await self._request("GET", f"/api/v1/users/{int(user_id)}")

    async def ban(self, user_id: int) -> dict:
        return await self._request("POST", "/api/v1/users/ban", {"user_id": user_id})

    async def unban(self, user_id: int) -> dict:
        return await self._request("POST", "/api/v1/users/unban", {"user_id": user_id})

    async def stats(self) -> dict:
        return await self._request("GET", "/api/v1/stats")


if __name__ == "__main__":
    import os
    import sys

    base = os.environ.get("MONETIZE_BASE_URL")
    key = os.environ.get("MONETIZE_API_KEY")
    if not (base and key):
        sys.exit("Set MONETIZE_BASE_URL and MONETIZE_API_KEY env vars to smoke-test this client.")
    c = MonetizeClient(base, key)
    print(c.ping())
