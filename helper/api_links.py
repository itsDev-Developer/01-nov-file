"""Storage + link building for the public link-generation API.

Two families of input:
  - REFERENCE (no copy, no download): the content is already sitting in a
    channel this bot treats as a DB channel — typically because another bot
    of yours posted it there directly. We just validate the message exists
    (a metadata-only call, no file transfer) and encode a link around its
    existing id. Nothing is re-uploaded or duplicated.
  - COPY / URL / FILE (this bot has to actually store something): the
    content lives somewhere this bot doesn't already track, so it's copied
    or uploaded into the primary DB channel, same as /genlink and /batch
    would end up storing it.

Either way the result is the same kind of `https://t.me/<bot>?start=<payload>`
link /genlink and /batch produce, so everything downstream (force-sub,
shortener, ads, delivery) is untouched.
"""

import asyncio
import os

from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from helper.helper_func import encode

MEDIA_TYPES = ("document", "video", "audio", "photo")
_VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
_AUDIO_EXT = {".mp3", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".wav"}

_write_lock = None
_background = set()  # keeps fire-and-forget tasks alive until they finish


class ApiError(Exception):
    """An error that maps 1:1 onto a JSON error response."""

    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def write_lock() -> asyncio.Lock:
    """One lock for every write into the DB channel. A COPY/URL/FILE batch is
    a *contiguous message-id range*, so nothing else may post into the
    channel while one is being stored. Reference mode never takes this —
    it doesn't write anything."""
    global _write_lock
    if _write_lock is None:
        _write_lock = asyncio.Lock()
    return _write_lock


def guess_media_type(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _AUDIO_EXT:
        return "audio"
    return "document"


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:160]}"


def resolve_known_channel(client, chat_id: int):
    """chat_id back, unchanged, if it's already one of this bot's DB
    channels (the primary one, or a secondary one from multi-channel setups)
    — meaning a link can reference an existing message there directly,
    with no copy. None if it's some other chat entirely."""
    if chat_id is None:
        return None
    if chat_id == client.db:
        return chat_id
    if str(chat_id) in getattr(client, "db_channels", {}):
        return chat_id
    return None


async def verify_messages_exist(client, channel_id: int, message_ids: list) -> list:
    """Metadata-only existence check (no file is downloaded) — returns the
    subset of `message_ids` that don't actually exist in `channel_id`, so
    a bad id produces a clear error instead of a link that fails later."""
    try:
        result = await client.get_messages(chat_id=channel_id, message_ids=message_ids)
    except Exception as e:
        raise ApiError(502, "source_unreachable", f"Could not read chat {channel_id} ({_short(e)}).")
    msgs = result if isinstance(result, list) else [result]
    return [mid for mid, msg in zip(message_ids, msgs) if msg is None or getattr(msg, "empty", False)]


async def build_link(client, channel_id: int, message_ids: list) -> tuple:
    """(link, payload) for consecutive message ids in `channel_id` — a
    single link for one id, a batch link (first..last) for several. Same
    encoding /genlink and /batch use."""
    mult = abs(channel_id)
    first, last = message_ids[0], message_ids[-1]
    string = f"get-{first * mult}" if first == last else f"get-{first * mult}-{last * mult}"
    payload = await encode(string)
    return f"https://t.me/{client.username}?start={payload}", payload


async def _retry_flood(factory):
    """Run a Telegram call, sleeping through one short FloodWait."""
    try:
        return await factory()
    except FloodWait as e:
        wait = getattr(e, "value", None) or getattr(e, "x", 5)
        if wait > 60:
            raise ApiError(429, "telegram_flood_wait", f"Telegram asked us to wait {wait}s. Retry later.")
        await asyncio.sleep(wait + 1)
        return await factory()


async def store_item(client, item: dict):
    """Post one COPY/URL/FILE item into the primary DB channel; returns its
    Message. Never called for reference-mode items — those skip storage
    entirely (see resolve_known_channel / build_link above)."""
    kind = item["kind"]
    try:
        if kind == "copy":
            kwargs = {"chat_id": client.db, "from_chat_id": item["source_chat_id"],
                      "message_id": item["message_id"], "disable_notification": True}
            if item.get("caption") is not None:
                kwargs["caption"] = item["caption"]
            return await _retry_flood(lambda: client.copy_message(**kwargs))

        media_type = item["type"]
        send = {"document": client.send_document, "video": client.send_video,
                "audio": client.send_audio, "photo": client.send_photo}[media_type]
        kwargs = {"chat_id": client.db, media_type: item["url"] if kind == "url" else item["path"],
                  "caption": item.get("caption") or "", "disable_notification": True}
        if kind == "file" and media_type == "document":
            kwargs["file_name"] = item["filename"]  # keep the uploader's file name
        if kind == "file" and media_type == "video":
            kwargs["supports_streaming"] = True
        return await _retry_flood(lambda: send(**kwargs))
    except ApiError:
        raise
    except Exception as e:
        if kind == "copy":
            raise ApiError(
                502, "source_unreachable",
                f"Could not copy message {item['message_id']} from chat {item['source_chat_id']} "
                f"({_short(e)}). Add this bot to that chat and check the message id.",
            )
        raise ApiError(502, "store_failed", f"Telegram rejected the content ({_short(e)}).")


async def store_single(client, item: dict):
    async with write_lock():
        return await store_item(client, item)


async def store_batch(client, items: list) -> tuple:
    """Store COPY/URL/FILE items back-to-back; returns (messages, skipped).
    Items that fail are skipped (reported), not fatal. If a foreign post
    lands in the middle (someone posting directly in the channel while this
    runs), the range would include it — so we delete our copies and retry
    once instead of returning a bad link."""
    for _ in range(2):
        stored, skipped = [], []
        async with write_lock():
            for index, item in enumerate(items):
                try:
                    stored.append(await store_item(client, item))
                except ApiError as e:
                    skipped.append({"index": index, "error": e.code, "message": e.message})

        if not stored:
            raise ApiError(502, "batch_empty", "None of the items could be stored.", skipped=skipped)

        ids = [m.id for m in stored]
        if ids == list(range(ids[0], ids[0] + len(ids))):
            return stored, skipped

        try:
            await client.delete_messages(client.db, ids)
        except Exception:
            pass
    raise ApiError(409, "not_contiguous", "The DB channel was busy while storing this batch. Please retry.")


def schedule_share_buttons(client, messages: list) -> None:
    """Match what manual uploads get: a 'Share URL' button on each newly
    stored post (unless the bot runs with buttons disabled). Only for
    COPY/URL/FILE items this bot just created — a reference-mode link must
    never edit a message it doesn't own. Done in the background so the API
    response isn't held up by N extra Telegram calls."""
    if getattr(client, "disable_btn", False):
        return

    async def worker():
        for msg in messages:
            try:
                link, _ = await build_link(client, client.db, [msg.id])
                await msg.edit_reply_markup(InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔁 Share URL", url=f"https://telegram.me/share/url?url={link}")]]
                ))
            except Exception:
                pass
            await asyncio.sleep(0.3)

    task = asyncio.ensure_future(worker())
    _background.add(task)
    task.add_done_callback(_background.discard)
