"""Public link-generation API: lets your other bots/scripts turn content into
monetized links served by this bot. Docs: /api/docs (HTML) and /api/docs.md.

Kept in its own RouteTableDef (registered in plugins/__init__.py) so the
Mini App routes in route.py stay focused on the unlock flow.
"""

import os
import tempfile
import time
import uuid
from collections import deque

from aiohttp import web

from config import API_ENABLED, API_MAX_BATCH, API_MAX_UPLOAD_MB, API_RATE_LIMIT_PER_MIN, WEBAPP_URL
from helper.api_docs import render_api_docs_markdown, render_api_docs_page
from helper.api_links import (
    MEDIA_TYPES, ApiError, build_link, guess_media_type, resolve_known_channel, schedule_share_buttons,
    store_batch, store_single, verify_messages_exist,
)

api_routes = web.RouteTableDef()

_UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "api_uploads")
_hits: dict = {}  # key id -> deque of request timestamps (sliding one-minute window)


# --- small helpers -----------------------------------------------------

def _error(status: int, code: str, message: str, headers: dict = None, **extra):
    return web.json_response({"ok": False, "error": code, "message": message, **extra}, status=status, headers=headers)


def _api_error(e: ApiError):
    return _error(e.status, e.code, e.message, **e.extra)


def _rate_limit_retry_after(key_id: str) -> int:
    """0 if the request is allowed (and counted), else seconds to wait."""
    now, window = time.monotonic(), 60
    hits = _hits.setdefault(key_id, deque())
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= API_RATE_LIMIT_PER_MIN:
        return max(1, int(window - (now - hits[0])) + 1)
    hits.append(now)
    return 0


def key_scopes(key: dict) -> list:
    """Keys created before scopes existed have no field: they keep their old
    behaviour (links only), never silently gaining new powers."""
    return key.get("scopes") or ["links"]


async def _authenticate(request, scope: str = None):
    """Returns (bot, key_doc, error_response); error_response is None on success."""
    bot = request.app.get("bot")
    if not API_ENABLED:
        return None, None, _error(503, "api_disabled", "The API is disabled on this bot.")
    if not bot or not getattr(bot, "username", None):
        return None, None, _error(503, "server_starting", "The bot is still starting. Retry in a few seconds.")

    raw = request.headers.get("X-API-Key", "").strip()
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        raw = auth[7:].strip()
    if not raw:
        return None, None, _error(401, "missing_api_key", "Send your key as 'Authorization: Bearer <key>'.")

    key = await bot.mongodb.get_api_key_by_raw(raw)
    if not key:
        return None, None, _error(401, "invalid_api_key", "This API key is invalid or has been revoked.")

    if scope and scope not in key_scopes(key):
        return None, None, _error(
            403, "insufficient_scope",
            f"This key doesn't have the '{scope}' permission. Grant it with /apikeyscopes in the bot.",
        )

    retry_after = _rate_limit_retry_after(key["_id"])
    if retry_after:
        return None, None, _error(
            429, "rate_limited", f"Rate limit is {API_RATE_LIMIT_PER_MIN} requests/minute. Retry in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    await bot.mongodb.touch_api_key(key["_id"])
    return bot, key, None


def _to_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _parse_item(obj, where: str) -> dict:
    """Validate one JSON item: either {url,...} or {source_chat_id,message_id,...}."""
    if not isinstance(obj, dict):
        raise ApiError(400, "invalid_request", f"{where} must be a JSON object.")

    caption = obj.get("caption")
    if caption is not None and (not isinstance(caption, str) or len(caption) > 1024):
        raise ApiError(400, "invalid_request", f"{where}: 'caption' must be a string of at most 1024 characters.")

    if "url" in obj:
        url = obj["url"]
        if not (isinstance(url, str) and url.startswith(("http://", "https://")) and len(url) <= 2048):
            raise ApiError(400, "invalid_request", f"{where}: 'url' must be a public http(s) link.")
        media_type = obj.get("type", "document")
        if media_type not in MEDIA_TYPES:
            raise ApiError(400, "invalid_request", f"{where}: 'type' must be one of {', '.join(MEDIA_TYPES)}.")
        return {"kind": "url", "url": url, "type": media_type, "caption": caption}

    if "source_chat_id" in obj and "message_id" in obj:
        chat_id, message_id = _to_int(obj["source_chat_id"]), _to_int(obj["message_id"])
        if chat_id is None or message_id is None or message_id <= 0:
            raise ApiError(400, "invalid_request", f"{where}: 'source_chat_id' and 'message_id' must be integers.")
        return {"kind": "copy", "source_chat_id": chat_id, "message_id": message_id, "caption": caption}

    raise ApiError(400, "invalid_request", f"{where}: provide either 'url' or 'source_chat_id' + 'message_id'.")


async def _read_multipart(request, max_files: int, files: list) -> dict:
    """Stream uploaded files to disk (never into memory). Appends each saved
    file to `files` immediately so the caller can always clean them up, even
    if we raise halfway. Returns the plain text fields."""
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    max_bytes = API_MAX_UPLOAD_MB * 1024 * 1024
    fields = {}
    reader = await request.multipart()
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file" and part.filename:
            if len(files) >= max_files:
                raise ApiError(400, "too_many_files", f"At most {max_files} files per request.")
            filename = os.path.basename(part.filename) or "file"
            entry = {"path": os.path.join(_UPLOAD_DIR, f"{uuid.uuid4().hex}_{filename}"), "filename": filename}
            files.append(entry)
            size = 0
            with open(entry["path"], "wb") as out:
                while True:
                    chunk = await part.read_chunk(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise ApiError(413, "file_too_large", f"'{filename}' is larger than {API_MAX_UPLOAD_MB} MB.")
                    out.write(chunk)
            if size == 0:
                raise ApiError(400, "empty_file", f"'{filename}' is empty.")
        elif part.name in ("type", "caption"):
            fields[part.name] = (await part.text())[:1100]
    return fields


def _file_items(files: list, fields: dict) -> list:
    caption = fields.get("caption") or None
    if caption and len(caption) > 1024:
        raise ApiError(400, "invalid_request", "'caption' must be at most 1024 characters.")
    forced = fields.get("type")
    if forced and forced not in MEDIA_TYPES:
        raise ApiError(400, "invalid_request", f"'type' must be one of {', '.join(MEDIA_TYPES)}.")
    return [
        {"kind": "file", "path": f["path"], "filename": f["filename"],
         "type": forced or guess_media_type(f["filename"]), "caption": caption}
        for f in files
    ]


async def _json_body(request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "invalid_json", "Request body must be valid JSON (or multipart/form-data with a 'file').")
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_request", "Request body must be a JSON object.")
    return body


def _cleanup(files: list) -> None:
    for f in files:
        try:
            os.remove(f["path"])
        except OSError:
            pass


# --- endpoints ---------------------------------------------------------

@api_routes.get("/api/v1/ping")
async def ping(request):
    bot, key, error = await _authenticate(request)
    if error:
        return error
    return web.json_response({
        "ok": True, "bot": bot.username, "key_label": key["label"], "scopes": key_scopes(key), "version": "v1",
    })


@api_routes.get("/api/v1/usage")
async def usage(request):
    bot, key, error = await _authenticate(request)
    if error:
        return error
    return web.json_response({
        "ok": True, "key_id": key["_id"], "label": key["label"],
        "links_created": key.get("links_created", 0), "ads_completed": key.get("ads_completed", 0),
        "scopes": key_scopes(key), "created_at": key["created_at"].isoformat(),
        "rate_limit_per_min": API_RATE_LIMIT_PER_MIN,
    })


@api_routes.post("/api/v1/links/single")
async def links_single(request):
    bot, key, error = await _authenticate(request, "links")
    if error:
        return error

    files = []
    try:
        if request.content_type.startswith("multipart/"):
            fields = await _read_multipart(request, 1, files)
            if len(files) != 1:
                raise ApiError(400, "invalid_request", "Send exactly one 'file' part.")
            item = _file_items(files, fields)[0]
        else:
            body = await _json_body(request)

            # Reference mode: the content is already in one of THIS bot's own
            # DB channels (typically because another bot of yours posted it
            # there directly) — just wrap the existing id into a link. No
            # copy, no download, no duplicate storage.
            if "url" not in body and "source_chat_id" in body and "message_id" in body:
                chat_id, message_id = _to_int(body.get("source_chat_id")), _to_int(body.get("message_id"))
                if chat_id is None or message_id is None or message_id <= 0:
                    raise ApiError(400, "invalid_request", "'source_chat_id' and 'message_id' must be integers.")
                known = resolve_known_channel(bot, chat_id)
                if known is not None:
                    missing = await verify_messages_exist(bot, known, [message_id])
                    if missing:
                        raise ApiError(404, "message_not_found", f"No message {message_id} in chat {chat_id}.")
                    link, payload = await build_link(bot, known, [message_id])
                    await bot.mongodb.record_api_link(key["_id"], payload, "single", 1)
                    return web.json_response({
                        "ok": True, "link": link, "message_id": message_id, "channel_id": known, "source": "reference",
                    })

            item = _parse_item(body, "body")  # not a known channel (or a url) -> falls through to copy/url below

        message = await store_single(bot, item)
        link, payload = await build_link(bot, bot.db, [message.id])
        await bot.mongodb.record_api_link(key["_id"], payload, "single", 1)
        schedule_share_buttons(bot, [message])
        return web.json_response({
            "ok": True, "link": link, "message_id": message.id, "channel_id": bot.db, "source": item["kind"],
        })
    except ApiError as e:
        return _api_error(e)
    except Exception as e:
        bot.LOGGER(__name__, bot.name).warning(f"API single-link error: {e}")
        return _error(500, "internal_error", "Unexpected error while creating the link.")
    finally:
        _cleanup(files)


@api_routes.post("/api/v1/links/batch")
async def links_batch(request):
    bot, key, error = await _authenticate(request, "links")
    if error:
        return error

    files = []
    try:
        if request.content_type.startswith("multipart/"):
            fields = await _read_multipart(request, API_MAX_BATCH, files)
            if not files:
                raise ApiError(400, "invalid_request", "Send at least one 'file' part.")
            items = _file_items(files, fields)
        else:
            body = await _json_body(request)

            if "message_ids" in body and "source_chat_id" in body:
                raw_ids = body["message_ids"]
                if not isinstance(raw_ids, list) or not raw_ids:
                    raise ApiError(400, "invalid_request", "'message_ids' must be a non-empty list.")
                if len(raw_ids) > API_MAX_BATCH:
                    raise ApiError(400, "too_many_items", f"At most {API_MAX_BATCH} items per batch.")
                chat_id = _to_int(body["source_chat_id"])
                int_ids = [_to_int(x) for x in raw_ids]
                if chat_id is None or any(i is None or i <= 0 for i in int_ids):
                    raise ApiError(400, "invalid_request", "'source_chat_id' and every 'message_ids' entry must be integers.")

                # Reference mode: same idea as single-link — if these ids are
                # already in a channel this bot treats as storage, just
                # encode the range directly. Nothing is copied or downloaded.
                known = resolve_known_channel(bot, chat_id)
                if known is not None:
                    sorted_ids = sorted(int_ids)
                    if sorted_ids[-1] - sorted_ids[0] + 1 != len(sorted_ids):
                        raise ApiError(
                            400, "not_contiguous",
                            "Reference-mode batch links can only cover a contiguous run of message ids in the "
                            "source channel — the link format can't list arbitrary/non-contiguous ids. If these "
                            "files aren't contiguous there, use 'items' instead: it copies your selection into "
                            "this bot's channel to build a clean batch link.",
                        )
                    missing = await verify_messages_exist(bot, known, [sorted_ids[0], sorted_ids[-1]])
                    if missing:
                        raise ApiError(404, "message_not_found", f"Missing message(s) {missing} in chat {chat_id}.")
                    link, payload = await build_link(bot, known, sorted_ids)
                    await bot.mongodb.record_api_link(
                        key["_id"], payload, "batch" if len(sorted_ids) > 1 else "single", len(sorted_ids)
                    )
                    return web.json_response({
                        "ok": True, "link": link, "count": len(sorted_ids), "first_message_id": sorted_ids[0],
                        "last_message_id": sorted_ids[-1], "message_ids": sorted_ids, "skipped": [], "source": "reference",
                    })

                items = [_parse_item({"source_chat_id": chat_id, "message_id": mid, "caption": body.get("caption")},
                                     f"message_ids[{i}]")
                         for i, mid in enumerate(int_ids)]

            elif "items" in body:
                raw_items = body["items"]
                if not isinstance(raw_items, list) or not raw_items:
                    raise ApiError(400, "invalid_request", "'items' must be a non-empty list.")
                if len(raw_items) > API_MAX_BATCH:
                    raise ApiError(400, "too_many_items", f"At most {API_MAX_BATCH} items per batch.")
                items = [_parse_item(obj, f"items[{i}]") for i, obj in enumerate(raw_items)]
            else:
                raise ApiError(400, "invalid_request",
                               "Provide 'items', or 'source_chat_id' + 'message_ids', or upload files.")

        messages, skipped = await store_batch(bot, items)
        ids = [m.id for m in messages]
        link, payload = await build_link(bot, bot.db, ids)
        await bot.mongodb.record_api_link(key["_id"], payload, "batch" if len(ids) > 1 else "single", len(ids))
        schedule_share_buttons(bot, messages)
        return web.json_response({
            "ok": True, "link": link, "count": len(ids), "first_message_id": ids[0], "last_message_id": ids[-1],
            "message_ids": ids, "skipped": skipped, "source": "copy",
        })
    except ApiError as e:
        return _api_error(e)
    except Exception as e:
        bot.LOGGER(__name__, bot.name).warning(f"API batch-link error: {e}")
        return _error(500, "internal_error", "Unexpected error while creating the batch link.")
    finally:
        _cleanup(files)


# --- docs (public: they contain no secrets) ------------------------------

def _public_base(request) -> str:
    if "example.com" not in WEBAPP_URL:
        return WEBAPP_URL.rstrip("/")
    return f"{request.scheme}://{request.host}"  # WEBAPP_URL still the placeholder


@api_routes.get("/api/docs")
async def docs_page(request):
    bot = request.app.get("bot")
    theme = "violet"
    if bot:
        theme = (await bot.mongodb.get_site_settings()).get("template", "violet")
    return web.Response(text=render_api_docs_page(_public_base(request), theme), content_type="text/html")


@api_routes.get("/api/docs.md")
async def docs_markdown(request):
    return web.Response(text=render_api_docs_markdown(_public_base(request)),
                        content_type="text/markdown", charset="utf-8")
