"""Management API: premium users, ban/unban, user lookup and bot stats.

Same authentication, rate limit and error format as the link API
(plugins/api_routes.py), but every endpoint here needs a key that was
explicitly given the matching scope:

    premium  -> /api/v1/premium...
    users    -> /api/v1/users..., /api/v1/stats

Keys default to the 'links' scope only, so a key leaked from a small bot can
never grant premium or ban people unless you chose to allow it.
"""

import math
from datetime import datetime, timedelta

from aiohttp import web

from config import OWNER_ID
from helper.api_links import ApiError
from plugins.api_routes import _api_error, _authenticate, _error, _json_body, _to_int

manage_routes = web.RouteTableDef()

MAX_DAYS = 3650          # 10 years — guards against typos like days=3650000
MAX_PAGE = 200
VALID_MODES = ("extend", "replace")


# --- pure helpers (unit-tested directly) ------------------------------

def plan_premium_change(info: dict, days, mode: str, now: datetime) -> tuple:
    """Decide what an "add premium" call should do.

    Returns (new_expiry, action). new_expiry None means *permanent*.
    `days=None` means "make permanent". Actions: activated, extended,
    replaced, made_permanent, unchanged.
    """
    target = now + timedelta(days=days) if days else None
    if not info["active"]:
        return target, "activated"
    if days is None:  # caller asked for a permanent plan
        return (None, "unchanged") if info["permanent"] else (None, "made_permanent")
    if mode == "replace":
        return target, "replaced"
    if info["permanent"]:
        return None, "unchanged"  # extending a permanent plan changes nothing
    return info["expires_at"] + timedelta(days=days), "extended"


def premium_payload(user_id: int, info: dict, now: datetime = None) -> dict:
    now = now or datetime.now()
    expires = info["expires_at"]
    active = info["active"]
    return {
        "user_id": user_id,
        "premium": active,
        "permanent": bool(active and info["permanent"]),
        "expires_at": expires.isoformat() if expires else None,
        "expires_at_unix": int(expires.timestamp()) if expires else None,
        "days_left": max(0, math.ceil((expires - now).total_seconds() / 86400)) if active and expires else None,
    }


# --- request parsing ---------------------------------------------------

def _user_id(value, field: str = "user_id") -> int:
    uid = _to_int(value)
    if uid is None or uid <= 0:
        raise ApiError(400, "invalid_request", f"'{field}' must be a positive integer (a Telegram user id).")
    return uid


def _flag(body: dict, name: str) -> bool:
    value = body.get(name, False)
    if not isinstance(value, bool):
        raise ApiError(400, "invalid_request", f"'{name}' must be true or false.")
    return value


def _days(body: dict):
    if body.get("days") is None:
        return None
    days = _to_int(body["days"])
    if days is None or not 1 <= days <= MAX_DAYS:
        raise ApiError(400, "invalid_request", f"'days' must be a whole number from 1 to {MAX_DAYS} (omit it for permanent).")
    return days


def _is_protected(bot, user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in getattr(bot, "admins", [])


async def _notify(bot, user_id: int, text: str) -> bool:
    """Best-effort DM. Never raises: the user may not have started the bot,
    and a failed notification must not fail the (already applied) change."""
    try:
        await bot.send_message(user_id, text)
        return True
    except Exception:
        return False


# --- premium -------------------------------------------------------------

@manage_routes.get("/api/v1/premium")
async def premium_list(request):
    bot, key, error = await _authenticate(request, "premium")
    if error:
        return error
    limit = _to_int(request.query.get("limit", "50"))
    offset = _to_int(request.query.get("offset", "0"))
    if limit is None or offset is None or not 1 <= limit <= MAX_PAGE or offset < 0:
        return _error(400, "invalid_request", f"'limit' must be 1-{MAX_PAGE} and 'offset' 0 or more.")

    docs = await bot.mongodb.get_pros_page(limit, offset)
    total = await bot.mongodb.count_pros()
    now = datetime.now()
    users = []
    for doc in docs:
        info = {"active": True, "permanent": doc.get("expiry_date") is None,
                "expires_at": doc.get("expiry_date")}
        users.append(premium_payload(doc["_id"], info, now))
    return web.json_response({"ok": True, "total": total, "limit": limit, "offset": offset, "users": users})


@manage_routes.get("/api/v1/premium/{user_id}")
async def premium_status(request):
    bot, key, error = await _authenticate(request, "premium")
    if error:
        return error
    try:
        uid = _user_id(request.match_info["user_id"])
    except ApiError as e:
        return _api_error(e)
    info = await bot.mongodb.get_premium_info(uid)
    return web.json_response({"ok": True, **premium_payload(uid, info)})


@manage_routes.post("/api/v1/premium/add")
async def premium_add(request):
    bot, key, error = await _authenticate(request, "premium")
    if error:
        return error
    try:
        body = await _json_body(request)
        uid, days = _user_id(body.get("user_id")), _days(body)
        mode = body.get("mode", "extend")
        if mode not in VALID_MODES:
            raise ApiError(400, "invalid_request", f"'mode' must be one of: {', '.join(VALID_MODES)}.")
        notify = _flag(body, "notify")
        request_id = body.get("request_id")
        if request_id is not None and not (isinstance(request_id, str) and 1 <= len(request_id) <= 100):
            raise ApiError(400, "invalid_request", "'request_id' must be a string of 1-100 characters.")

        # Replay of a request we already applied (e.g. a payment webhook
        # retry): report the current state instead of extending again.
        if request_id and not await bot.mongodb.claim_api_request(key["_id"], request_id):
            info = await bot.mongodb.get_premium_info(uid)
            return web.json_response({"ok": True, "duplicate": True, "action": "unchanged",
                                      **premium_payload(uid, info)})

        try:
            previous = await bot.mongodb.get_premium_info(uid)
            new_expiry, action = plan_premium_change(previous, days, mode, datetime.now())
            if action != "unchanged":
                await bot.mongodb.add_pro(uid, new_expiry, source=f"api:{key['_id']}")
                bot.LOGGER(__name__, bot.name).info(f"API key '{key['label']}': premium {action} for {uid} (expires {new_expiry})")
            current = await bot.mongodb.get_premium_info(uid)
        except Exception:
            if request_id:  # nothing was applied: let the caller's retry through
                await bot.mongodb.release_api_request(key["_id"], request_id)
            raise

        notified = None
        if notify and action != "unchanged":
            until = f" until {new_expiry.strftime('%Y-%m-%d %H:%M')}" if new_expiry else " permanently"
            notified = await _notify(bot, uid, f"<b>🎉 Your premium membership is active{until}!</b>")

        payload = {"ok": True, "duplicate": False, "action": action, **premium_payload(uid, current)}
        payload["previous_expires_at"] = previous["expires_at"].isoformat() if previous["expires_at"] else None
        if notified is not None:
            payload["notified"] = notified
        return web.json_response(payload)
    except ApiError as e:
        return _api_error(e)


@manage_routes.post("/api/v1/premium/remove")
async def premium_remove(request):
    bot, key, error = await _authenticate(request, "premium")
    if error:
        return error
    try:
        body = await _json_body(request)
        uid, notify = _user_id(body.get("user_id")), _flag(body, "notify")

        previous = await bot.mongodb.get_premium_info(uid)
        removed = previous["known"]
        if removed:
            await bot.mongodb.remove_pro(uid)
            bot.LOGGER(__name__, bot.name).info(f"API key '{key['label']}': premium removed for {uid}")

        notified = None
        if notify and previous["active"]:
            notified = await _notify(bot, uid, "<b>Your premium membership has ended.</b>")

        payload = {"ok": True, "removed": removed, "was_active": previous["active"],
                   **premium_payload(uid, {"active": False, "permanent": False, "expires_at": None})}
        if notified is not None:
            payload["notified"] = notified
        return web.json_response(payload)
    except ApiError as e:
        return _api_error(e)


# --- users ----------------------------------------------------------------

@manage_routes.get("/api/v1/users/{user_id}")
async def user_info(request):
    bot, key, error = await _authenticate(request, "users")
    if error:
        return error
    try:
        uid = _user_id(request.match_info["user_id"])
    except ApiError as e:
        return _api_error(e)
    known = await bot.mongodb.present_user(uid)
    banned = await bot.mongodb.is_banned(uid)
    info = await bot.mongodb.get_premium_info(uid)
    return web.json_response({"ok": True, "user_id": uid, "started_bot": known, "banned": banned,
                              "premium": premium_payload(uid, info)})


async def _set_ban(request, banned: bool):
    bot, key, error = await _authenticate(request, "users")
    if error:
        return error
    try:
        uid = _user_id((await _json_body(request)).get("user_id"))
        if banned and _is_protected(bot, uid):
            raise ApiError(400, "protected_user", "Admins and the owner can't be banned through the API.")
        was_banned = await bot.mongodb.is_banned(uid)
        await bot.mongodb.set_user_ban(uid, banned)
        bot.LOGGER(__name__, bot.name).info(f"API key '{key['label']}': {'ban' if banned else 'unban'} {uid}")
        return web.json_response({"ok": True, "user_id": uid, "banned": banned, "changed": was_banned != banned})
    except ApiError as e:
        return _api_error(e)


@manage_routes.post("/api/v1/users/ban")
async def user_ban(request):
    return await _set_ban(request, True)


@manage_routes.post("/api/v1/users/unban")
async def user_unban(request):
    return await _set_ban(request, False)


@manage_routes.get("/api/v1/stats")
async def stats(request):
    bot, key, error = await _authenticate(request, "users")
    if error:
        return error
    return web.json_response({
        "ok": True,
        "users": await bot.mongodb.count_users(),
        "banned": await bot.mongodb.count_banned(),
        "premium_active": await bot.mongodb.count_pros(),
    })
