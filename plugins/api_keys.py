"""Admin-only management of API keys for the public link API.

Commands: /apikeys (panel), /newapikey <label>, /revokeapikey <id>, /apidocs.
The plaintext key is shown exactly once, at creation — only a hash is stored.
"""

from pyrogram import Client, filters
from pyrogram.errors.pyromod import ListenerTimeout
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import API_SCOPES, WEBAPP_URL

BACK_TO_KEYS = InlineKeyboardMarkup([[InlineKeyboardButton("◂ Back", callback_data="apikeys_panel")]])


def parse_scopes(text: str):
    """'links,premium' / 'all' -> ['links','premium'] (None if any part is invalid)."""
    parts = [p.strip().lower() for p in text.split(",") if p.strip()]
    if not parts:
        return None
    if parts == ["all"]:
        return list(API_SCOPES)
    if any(p not in API_SCOPES for p in parts):
        return None
    return [s for s in API_SCOPES if s in parts]  # canonical order, no duplicates


def split_label_and_scopes(text: str):
    """'moviebot links,premium' -> ('moviebot', ['links','premium']);
    no trailing scope token -> (text, None) so the default (links) applies."""
    head, _, last = text.strip().rpartition(" ")
    if head and parse_scopes(last):
        return head.strip(), parse_scopes(last)
    return text.strip(), None


def _scope_warning(scopes: list) -> str:
    risky = [s for s in scopes if s != "links"]
    if not risky:
        return ""
    return ("\n\n⚠️ This key can <b>" + " & ".join(
        {"premium": "grant/remove premium", "users": "ban users and read stats"}[s] for s in risky
    ) + "</b>. Keep it on your server only.")


def _is_admin(user_id: int, client: Client) -> bool:
    return user_id in client.admins


def _docs_url() -> str:
    return f"{WEBAPP_URL.rstrip('/')}/api/docs"


def _key_created_text(raw: str, doc: dict) -> str:
    return (
        "<blockquote>✦ API KEY CREATED</blockquote>\n"
        f"›› **Label:** `{doc['label']}`  ·  **ID:** `{doc['_id']}`\n"
        f"›› **Scopes:** `{', '.join(doc.get('scopes', ['links']))}`\n\n"
        f"`{raw}`\n\n"
        "⚠️ <b>Copy it now — it is shown only once.</b> Put it in your other bot's environment variables "
        "(never in user-facing code).\n\n"
        f"Base URL: `{WEBAPP_URL.rstrip('/')}`\nDocs: {_docs_url()}"
        + _scope_warning(doc.get("scopes", ["links"]))
    )


async def build_keys_panel(client: Client) -> tuple:
    keys = await client.mongodb.list_api_keys()
    if keys:
        lines = []
        for k in keys:
            state = "🚫 revoked" if k["revoked"] else "✅ active"
            lines.append(
                f"{state} · **{k['label']}** (`{k['_id']}`)\n"
                f"   `{k['prefix']}…` · scopes: `{','.join(k.get('scopes') or ['links'])}`\n"
                f"   links: `{k.get('links_created', 0)}` · ad unlocks: `{k.get('ads_completed', 0)}`"
            )
        body = "\n\n".join(lines)
    else:
        body = "_No API keys yet. Create one for each bot you want to monetize._"

    text = (
        "<blockquote>✦ API KEYS</blockquote>\n"
        f"{body}\n\n"
        "<i>Each key = one of your bots. \"Ad unlocks\" counts users who finished the ads for links that key created.</i>"
    )
    rows = [[InlineKeyboardButton(f"🗑 Revoke: {k['label']}", callback_data=f"akrev:{k['_id']}")]
            for k in keys if not k["revoked"]][:8]
    rows += [
        [InlineKeyboardButton("➕ New Key", callback_data="apikey_new"),
         InlineKeyboardButton("📖 Docs", url=_docs_url())],
        [InlineKeyboardButton("◂ Back", callback_data="settings_page_2")],
    ]
    return text, InlineKeyboardMarkup(rows)


#===============================================================#

@Client.on_message(filters.command("apikeys") & filters.private)
async def apikeys_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    text, keyboard = await build_keys_panel(client)
    await message.reply(text, reply_markup=keyboard, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex("^apikeys_panel$"))
async def apikeys_panel(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    await query.answer()
    text, keyboard = await build_keys_panel(client)
    await query.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)


#===============================================================#

@Client.on_message(filters.command("newapikey") & filters.private)
async def newapikey_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    if len(message.command) < 2:
        return await message.reply(
            "**Usage:** `/newapikey <label> [scopes]`\n"
            "Scopes: `links` (default), `premium`, `users` or `all` — comma separated.\n"
            "e.g. `/newapikey moviebot` · `/newapikey shopbot links,premium`"
        )
    label, scopes = split_label_and_scopes(message.text.split(" ", 1)[1])
    raw, doc = await client.mongodb.create_api_key(label, scopes)
    await message.reply(_key_created_text(raw, doc), disable_web_page_preview=True)


@Client.on_callback_query(filters.regex("^apikey_new$"))
async def apikey_new_callback(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    await query.answer()
    await query.message.edit_text(
        "<blockquote>**New API key**</blockquote>\nSend a short label (e.g. the bot's name) in the next 60 seconds."
    )
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        raw, doc = await client.mongodb.create_api_key(res.text)
        await res.reply(_key_created_text(raw, doc), reply_markup=BACK_TO_KEYS, disable_web_page_preview=True)
    except ListenerTimeout:
        await query.message.edit_text("⏰ Timeout, try again.", reply_markup=BACK_TO_KEYS)


#===============================================================#
# Revoking is a two-step (confirm) action — a mis-tap would break a live bot.

@Client.on_callback_query(filters.regex(r"^akrev:([0-9a-f]{8})$"))
async def revoke_confirm(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    key_id = query.data.split(":", 1)[1]
    await query.answer()
    await query.message.edit_text(
        f"<blockquote>Revoke key `{key_id}`?</blockquote>\nAny bot using it will immediately get `401` errors. "
        "Links it already created keep working.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, revoke", callback_data=f"akrevy:{key_id}"),
             InlineKeyboardButton("Cancel", callback_data="apikeys_panel")],
        ]),
    )


@Client.on_callback_query(filters.regex(r"^akrevy:([0-9a-f]{8})$"))
async def revoke_do(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    done = await client.mongodb.revoke_api_key(query.data.split(":", 1)[1])
    await query.answer("Key revoked." if done else "Key not found / already revoked.")
    text, keyboard = await build_keys_panel(client)
    await query.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)


@Client.on_message(filters.command("revokeapikey") & filters.private)
async def revokeapikey_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/revokeapikey <id>` — ids are listed in /apikeys")
    done = await client.mongodb.revoke_api_key(message.command[1].strip())
    await message.reply("✅ Key revoked." if done else "✗ No active key with that id.")


@Client.on_message(filters.command("apikeyscopes") & filters.private)
async def apikeyscopes_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    parts = message.command
    scopes = parse_scopes(parts[2]) if len(parts) >= 3 else None
    if len(parts) < 3 or not scopes:
        return await message.reply(
            "**Usage:** `/apikeyscopes <id> <scopes>`\n"
            "Scopes: `links`, `premium`, `users` or `all` — comma separated, e.g. `/apikeyscopes a1b2c3d4 links,premium`\n"
            "Key ids are listed in /apikeys."
        )
    if not await client.mongodb.set_api_key_scopes(parts[1].strip(), scopes):
        return await message.reply("✗ No active key with that id.")
    await message.reply(f"✅ Scopes updated: `{', '.join(scopes)}`" + _scope_warning(scopes))


@Client.on_message(filters.command("apidocs") & filters.private)
async def apidocs_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    await message.reply(
        f"<blockquote>✦ API DOCS</blockquote>\n{_docs_url()}\n\nMarkdown: {_docs_url()}.md",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📖 Open docs", url=_docs_url())]]),
        disable_web_page_preview=True,
    )
