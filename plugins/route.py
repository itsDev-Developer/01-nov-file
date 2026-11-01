"""Web layer: the public landing page ("/") and the ad-verification Mini App
("/unlock/{token}" + its two API endpoints). Business rules live in
helper/ads_func.py, helper/delivery.py and helper/database.py; this file
only wires HTTP <-> them.
"""

import asyncio
from datetime import datetime

from aiohttp import web

from config import MIN_AD_STEP_SECONDS, POSTBACK_SECRET
from helper.delivery import deliver_payload
from helper.geo import client_ip_from_request, get_country_tier
from helper.webapp_auth import validate_init_data
from helper.webapp_templates import render_error_page, render_home_page, render_unlock_page

routes = web.RouteTableDef()

_background = set()  # keeps fire-and-forget tasks alive until they finish


def _html(text: str, status: int = 200, cache: str = "no-store") -> web.Response:
    """HTML response, gzip/deflate-compressed when the client allows it (the
    watch page is ~15 KB of markup, ~5 KB compressed — matters on mobile data).
    The unlock page is per-user and single-use, so it must never be cached."""
    resp = web.Response(text=text, content_type="text/html", status=status, headers={"Cache-Control": cache})
    try:
        resp.enable_compression()
    except Exception:  # compression is an optimisation, never a reason to fail the request
        pass
    return resp


def _run_in_background(coro) -> None:
    task = asyncio.ensure_future(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _record_geo(bot, token: str, ip: str) -> None:
    """Geo lookup is a network call to a third party (up to ~3 s on a cache
    miss). It used to block the page from rendering; now it runs after the
    response is sent and the result is attached to the session, long before
    the user finishes watching ads."""
    try:
        country, tier = await get_country_tier(ip)
        await bot.mongodb.set_session_geo(token, country, tier)
    except Exception:
        pass  # stats only — never worth breaking anything


def _bot(request):
    return request.app.get("bot")


@routes.get("/", allow_head=True)
async def home(request):
    bot = _bot(request)
    username = getattr(bot, "username", "") if bot else ""
    theme = "violet"
    if bot:
        site_settings = await bot.mongodb.get_site_settings()
        theme = site_settings.get("template", "violet")
    return _html(render_home_page(username, theme), cache="public, max-age=60")


@routes.get("/unlock/{token}")
async def unlock_page(request):
    bot = _bot(request)
    if not bot:
        return _html(render_error_page("Starting up", "The bot is still starting, please try again in a few seconds."), 503)

    token = request.match_info["token"]
    # Three independent reads: run them together instead of one after another.
    session, site_settings, ads_settings = await asyncio.gather(
        bot.mongodb.get_verify_session(token),
        bot.mongodb.get_site_settings(),
        bot.mongodb.get_ads_settings(),
    )
    theme = site_settings.get("template", "violet")

    if not session:
        return _html(render_error_page("Link Expired", "This unlock link is invalid or has expired. Please request the file again in the bot.", theme), 404)
    if session["status"] != "pending":
        return _html(render_error_page("Already Used", "This link has already been used. Please request the file again in the bot.", theme), 409)
    if session["expires_at"] < datetime.now():
        return _html(render_error_page("Link Expired", "This unlock link has expired. Please request the file again in the bot.", theme), 410)

    _run_in_background(_record_geo(bot, token, client_ip_from_request(request)))

    html = render_unlock_page(
        token, session["steps"], ads_settings["zones"], getattr(bot, "username", ""), theme,
        banner_min_height=site_settings.get("banner_min_height", 300),
    )
    return _html(html)


async def _authenticate_session(request, token):
    """Shared guard for the two API endpoints below. Returns
    (bot, session, error_response) — error_response is None on success."""
    bot = _bot(request)
    if not bot:
        return None, None, web.json_response({"ok": False, "error": "server_starting"}, status=503)

    try:
        body = await request.json()
    except Exception:
        return None, None, web.json_response({"ok": False, "error": "bad_request"}, status=400)

    session = await bot.mongodb.get_verify_session(token)
    if not session or session["status"] != "pending" or session["expires_at"] < datetime.now():
        return None, None, web.json_response({"ok": False, "error": "session_invalid"}, status=410)

    user = validate_init_data(body.get("init_data", ""), bot.token)
    if not user or user.get("id") != session["user_id"]:
        return None, None, web.json_response({"ok": False, "error": "auth_failed"}, status=401)

    request["json_body"] = body  # avoid re-reading the (already consumed) request stream
    return bot, session, None


@routes.post("/api/unlock/{token}/step")
async def unlock_step(request):
    token = request.match_info["token"]
    bot, session, error = await _authenticate_session(request, token)
    if error:
        return error

    step = request["json_body"].get("step")
    if step not in session["steps"]:
        return web.json_response({"ok": False, "error": "unknown_step"}, status=400)

    await bot.mongodb.mark_step_complete(token, step)
    if request["json_body"].get("ad_shown") is False:
        await bot.mongodb.mark_step_skipped(token, step)
    remaining = len(session["steps"]) - len(set(session["completed_steps"]) | {step})
    return web.json_response({"ok": True, "remaining": max(remaining, 0)})


@routes.post("/api/unlock/{token}/complete")
async def unlock_complete(request):
    token = request.match_info["token"]
    bot, session, error = await _authenticate_session(request, token)
    if error:
        return error

    completed = set(session["completed_steps"])
    if not completed.issuperset(session["steps"]):
        return web.json_response({"ok": False, "error": "steps_incomplete"}, status=400)

    # Anti-bypass sanity check: a real ad sequence can't finish faster than
    # roughly MIN_AD_STEP_SECONDS per step. This won't stop a determined
    # scripted bypass, but it blocks the trivial "call the API directly" case.
    elapsed = (datetime.now() - session["created_at"]).total_seconds()
    required = MIN_AD_STEP_SECONDS * len(session["steps"])
    if elapsed < required:
        return web.json_response({"ok": False, "error": "too_fast"}, status=429)

    # Atomically claim this session before doing any delivery work: two
    # near-simultaneous /complete calls (double-tap, a retried fetch) must
    # not both pass this point, or the file gets sent twice.
    locked_session = await bot.mongodb.try_lock_verify_session(token)
    if not locked_session:
        return web.json_response({"ok": False, "error": "already_processed"}, status=409)

    # Deliver the file directly from the server — no more round-tripping
    # the user back through a `/start unlock_<token>` deep link, which was
    # fragile (double-fires, "Open Telegram" sometimes failing silently).
    delivered = await deliver_payload(bot, session["user_id"], session["payload"], transfer_link=session["payload"])
    if not delivered:
        await bot.mongodb.unlock_verify_session(token)
        return web.json_response({"ok": False, "error": "delivery_failed"}, status=502)

    await bot.mongodb.mark_verify_session_used(token)
    if session.get("skipped_steps"):
        await bot.mongodb.record_ad_skipped(user_id=session["user_id"])  # unlocked without a real ad: not a watched ad
    else:
        geo_tier = session.get("geo_tier")
        if geo_tier is None:  # background lookup hadn't finished (rare): do it now, it's cached per IP
            _, geo_tier = await get_country_tier(client_ip_from_request(request))
        await bot.mongodb.record_ad_completion(tier=geo_tier, user_id=session["user_id"])
    try:  # credit the API key whose link this was (no-op for normal links)
        await bot.mongodb.attribute_ad_to_api_key(session["payload"])
    except Exception:
        pass  # attribution is reporting only; it must never block a delivery

    return web.json_response({"ok": True})


@routes.get("/postback/monetag")
async def monetag_postback(request):
    """Server-to-server confirmation from Monetag that an ad was actually
    shown (Rewarded Interstitial / Rewarded Popup only — Monetag doesn't
    support postbacks for other formats). This is a *stronger* signal than
    the client-side JS callback, since it can't be spoofed by tampering
    with the page: https://docs.monetag.com/docs/postbacks/

    Always returns 200 on anything we can parse — Monetag retries with
    backoff on non-200 responses, and we don't want retry storms for
    "session already expired" style situations that will never resolve.
    """
    bot = _bot(request)
    if not bot:
        return web.Response(status=503, text="starting up")

    q = request.query
    if q.get("secret") != POSTBACK_SECRET:
        # Wrong/missing secret: don't leak *why* to whoever's poking the
        # endpoint, and don't log it as a real (failed) ad event.
        return web.Response(status=403, text="forbidden")

    ymid = q.get("ymid", "")
    token, _, step = ymid.partition(":")
    if not token or not step:
        return web.Response(status=200, text="ignored: bad ymid")

    await bot.mongodb.record_postback(
        token=token,
        step=step,
        event_type=q.get("event", ""),
        reward_event_type=q.get("value", ""),
        extra={
            "zone": q.get("zone", ""),
            "sub_zone": q.get("sub", ""),
            "estimated_price": q.get("price", ""),
            "telegram_id": q.get("telegram_id", ""),
        },
    )
    return web.Response(status=200, text="OK")
