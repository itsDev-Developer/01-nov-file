"""Admin-only: what users see on the premium screens.

    /premiumsettings            panel with buttons
    /setpremiumurl <url|off>    where Buy / Activate / Renew buttons point
    /setcontact <url|@user|off> the Contact button on /profile
    /setpremiumfeatures         perks list, one per line (or `reset`)

Every "Buy Premium" button in the bot (premium screens, /profile, /request and
the shortener message) reads the URL set here, so you change it in one place.
"""

import html

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors.pyromod import ListenerTimeout
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import DEFAULT_PREMIUM_URL
from helper.premium_ui import BUILTIN_FEATURES, MAX_FEATURE_LEN, MAX_FEATURES, normalize_url, parse_features

BACK = InlineKeyboardMarkup([[InlineKeyboardButton("◂ Back", callback_data="premiumsettings")]])
CLEAR_WORDS = ("off", "none", "clear", "reset")


def _is_admin(user_id: int, client: Client) -> bool:
    return user_id in client.admins


async def apply_setting(client: Client, key: str, raw: str) -> str:
    """Validate and store one setting; returns the message to show the admin.
    Shared by the commands and the panel buttons so they behave identically."""
    raw = (raw or "").strip()
    clearing = raw.lower() in CLEAR_WORDS

    if key == "features":
        if clearing:
            await client.mongodb.update_premium_setting("features", [])
            return "✅ Perks list reset to the built-in one."
        lines = parse_features(raw)
        if not lines:
            return (f"✗ Send 1-{MAX_FEATURES} perks, one per line, each up to {MAX_FEATURE_LEN} characters.")
        await client.mongodb.update_premium_setting("features", lines)
        return f"✅ Saved {len(lines)} perk(s)."

    field, label = {"buy_url": ("buy_url", "Premium link"), "contact_url": ("contact_url", "Contact link")}[key]
    if clearing:
        await client.mongodb.update_premium_setting(field, "")
        fallback = " Buttons now use the built-in default link." if key == "buy_url" else " The Contact button is hidden."
        return f"✅ {label} cleared." + fallback
    url = normalize_url(raw)
    if not url:
        return "✗ That doesn't look like a link. Use <code>https://…</code>, <code>t.me/…</code> or <code>@username</code>."
    await client.mongodb.update_premium_setting(field, url)
    return f"✅ {label} set to {html.escape(url)}"


async def build_panel(client: Client) -> tuple:
    s = await client.mongodb.get_premium_settings()
    buy = s["buy_url"] or f"{DEFAULT_PREMIUM_URL} (default — not set by you yet)"
    contact = s["contact_url"] or "not set (button hidden)"
    features = s["features"] or BUILTIN_FEATURES
    custom = "custom" if s["features"] else "built-in"
    text = (
        "<blockquote>✦ PREMIUM SETTINGS</blockquote>\n"
        f"›› <b>Buy / Activate / Renew link:</b>\n<code>{html.escape(buy)}</code>\n"
        f"›› <b>Contact link:</b> <code>{html.escape(contact)}</code>\n"
        f"›› <b>Perks list</b> ({custom}):\n" + "\n".join(f"   ✅ {html.escape(f)}" for f in features) +
        "\n\n<i>These appear on /myplan, /profile, the <code>?start=premium</code> link and every Buy Premium button.</i>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Set Buy Link", callback_data="pset_buy_url"),
         InlineKeyboardButton("📞 Set Contact", callback_data="pset_contact_url")],
        [InlineKeyboardButton("📝 Set Perks", callback_data="pset_features"),
         InlineKeyboardButton("↺ Reset Perks", callback_data="pset_reset_features")],
        [InlineKeyboardButton("◂ Back", callback_data="settings_page_2")],
    ])
    return text, keyboard


#===============================================================#

@Client.on_message(filters.command("premiumsettings") & filters.private)
async def premiumsettings_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    text, keyboard = await build_panel(client)
    await message.reply(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@Client.on_callback_query(filters.regex("^premiumsettings$"))
async def premiumsettings_callback(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    await query.answer()
    text, keyboard = await build_panel(client)
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


#===============================================================#

@Client.on_message(filters.command(["setpremiumurl", "setcontact"]) & filters.private)
async def set_link_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    cmd = message.command[0].lower()
    key = "buy_url" if cmd == "setpremiumurl" else "contact_url"
    if len(message.command) < 2:
        examples = "`/setpremiumurl https://t.me/yourname`" if key == "buy_url" else "`/setcontact @yourname`"
        return await message.reply(f"**Usage:** {examples}\nSend `off` to clear it.")
    await message.reply(await apply_setting(client, key, message.text.split(None, 1)[1]), parse_mode=ParseMode.HTML)


@Client.on_message(filters.command("setpremiumfeatures") & filters.private)
async def set_features_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        return await message.reply(
            "**Usage:** send the command followed by your perks, one per line:\n\n"
            "`/setpremiumfeatures`\n`No ads`\n`Faster downloads`\n`Priority support`\n\n"
            "Send `/setpremiumfeatures reset` to go back to the built-in list."
        )
    await message.reply(await apply_setting(client, "features", parts[1]), parse_mode=ParseMode.HTML)


#===============================================================#
# Panel buttons: ask for the value, then reuse apply_setting().

PROMPTS = {
    "buy_url": ("Premium link", "Send the link people should open to buy premium (<code>https://…</code>, <code>t.me/…</code> or <code>@username</code>), or <code>off</code> to use the default."),
    "contact_url": ("Contact link", "Send the contact link (<code>https://…</code>, <code>t.me/…</code> or <code>@username</code>), or <code>off</code> to hide the button."),
    "features": ("Perks list", f"Send your perks, one per line (up to {MAX_FEATURES}), or <code>reset</code> for the built-in list."),
}


@Client.on_callback_query(filters.regex(r"^pset_(buy_url|contact_url|features)$"))
async def pset_prompt(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    key = query.data[len("pset_"):]
    title, prompt = PROMPTS[key]
    await query.answer()
    await query.message.edit_text(f"<blockquote><b>Set {title}</b></blockquote>\n{prompt}\n\n<i>You have 2 minutes.</i>",
                                  parse_mode=ParseMode.HTML)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=120)
        await res.reply(await apply_setting(client, key, res.text), reply_markup=BACK, parse_mode=ParseMode.HTML)
    except ListenerTimeout:
        await query.message.edit_text("⏰ Timeout, try again.", reply_markup=BACK)


@Client.on_callback_query(filters.regex("^pset_reset_features$"))
async def pset_reset_features(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    await apply_setting(client, "features", "reset")
    await query.answer("Perks list reset.")
    text, keyboard = await build_panel(client)
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
