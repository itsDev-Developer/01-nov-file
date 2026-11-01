"""Admin-only ad configuration: enable/disable, per-zone ids, unlock mode
(one/two/all ad units), and watch-stats broken down by tier and time range.

Mirrors the shortner.py panel pattern (listen-based text prompts + inline
buttons) so it feels consistent with the rest of the settings UI.
"""

from pyrogram import Client, filters
from pyrogram.errors.pyromod import ListenerTimeout
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import POSTBACK_SECRET, WEBAPP_URL

# zone_type -> (command name, human label)
ZONE_TYPES = {
    "interstitial": ("setinterstitial", "Interstitial"),
    "inapp_interstitial": ("setinappinterstitial", "In-App Interstitial"),
    "rewarded_interstitial": ("setrewardedinterstitial", "Rewarded Interstitial"),
    "rewarded_popup": ("setpopup", "Rewarded Popup"),
    "native_banner": ("setnativebanner", "Native Banner"),
}
COMMAND_TO_ZONE = {cmd: zone for zone, (cmd, _) in ZONE_TYPES.items()}
MODE_LABELS = {"one": "1 ad unit", "two": "2 ad units", "all": "All configured units"}
STATS_RANGES = {"today": 1, "week": 7, "month": 30, "lifetime": 0}
GEO_TIER_LABELS = {
    1: "Tier 1 (US/UK/CA/AU/W.Europe — top CPM)",
    2: "Tier 2 (S/E Europe, Gulf, HK/TW/KR/MY)",
    3: "Tier 3 (BR/MX/IN/RU/TR + other emerging)",
    4: "Tier 4 (rest of world)",
}
TEMPLATE_LABELS = {"violet": "🟣 Violet", "emerald": "🟢 Emerald", "sunset": "🟠 Sunset"}
BANNER_HEIGHTS = (200, 250, 300, 350, 400, 500)
BANNER_MIN, BANNER_MAX = 120, 700

#===============================================================#

def _is_admin(user_id: int, client: Client) -> bool:
    return user_id in client.admins

#===============================================================#

async def build_settings_panel(client: Client) -> tuple:
    s = await client.mongodb.get_ads_settings()
    site = await client.mongodb.get_site_settings()
    zones = s["zones"]

    def zline(zone_type):
        cmd, label = ZONE_TYPES[zone_type]
        raw = zones.get(zone_type) or ""
        if zone_type == "native_banner":
            value = "not set" if not raw else f"custom code set ({len(raw)} chars)"
        else:
            value = raw or "not set"
        return f"›› **{label}:** `{value}`"

    msg = f"""<blockquote>✦ ADS SETTINGS</blockquote>
›› **Status:** {"✓ Enabled" if s["enabled"] else "✗ Disabled"}
›› **Unlock mode:** {MODE_LABELS.get(s["mode"], s["mode"])}
›› **Site template:** {TEMPLATE_LABELS.get(site["template"], site["template"])}
›› **Banner height:** `{site["banner_min_height"]}px`

**Ad zones (Monetag, except Native Banner):**
{chr(10).join(zline(z) for z in ZONE_TYPES)}

<i>Free users complete the configured ad steps in a Telegram Mini App before a file unlocks. Admins and premium users always skip ads.</i>
"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(("✗ Disable Ads" if s["enabled"] else "✓ Enable Ads"), callback_data="toggle_ads")],
        [InlineKeyboardButton("⚙️ Unlock Mode", callback_data="adsmode_panel"),
         InlineKeyboardButton("📊 Ads Stats", callback_data="adsstats_panel")],
        [InlineKeyboardButton("🎨 Site Template", callback_data="template_panel"),
         InlineKeyboardButton("📐 Banner Height", callback_data="bannerh_panel")],
        [InlineKeyboardButton("Interstitial", callback_data="adszone_interstitial"),
         InlineKeyboardButton("In-App Interstitial", callback_data="adszone_inapp_interstitial")],
        [InlineKeyboardButton("Rewarded Interstitial", callback_data="adszone_rewarded_interstitial"),
         InlineKeyboardButton("Rewarded Popup", callback_data="adszone_rewarded_popup")],
        [InlineKeyboardButton("Native Banner (Adsterra code)", callback_data="adszone_native_banner")],
        [InlineKeyboardButton("◂ Back", callback_data="settings")],
    ])
    return msg, keyboard

#===============================================================#

@Client.on_message(filters.command("adssettings") & filters.private)
async def adssettings_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    msg, keyboard = await build_settings_panel(client)
    await message.reply(msg, reply_markup=keyboard)

@Client.on_callback_query(filters.regex("^adssettings$"))
async def adssettings_callback(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    await query.answer()
    msg, keyboard = await build_settings_panel(client)
    await query.message.edit_text(msg, reply_markup=keyboard)

#===============================================================#

@Client.on_message(filters.command(["adsenable", "adsdisable"]) & filters.private)
async def toggle_ads_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    enabled = message.command[0].lower() == "adsenable"
    await client.mongodb.update_ads_setting("enabled", enabled)
    await message.reply(f"✅ Ads {'enabled' if enabled else 'disabled'}.")

@Client.on_callback_query(filters.regex("^toggle_ads$"))
async def toggle_ads_callback(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    s = await client.mongodb.get_ads_settings()
    new_status = not s["enabled"]
    await client.mongodb.update_ads_setting("enabled", new_status)
    await query.answer(f"Ads {'enabled' if new_status else 'disabled'}!")
    msg, keyboard = await build_settings_panel(client)
    await query.message.edit_text(msg, reply_markup=keyboard)

#===============================================================#
# Unlock mode: how many configured ad units a free user must clear.

@Client.on_message(filters.command("adsmode") & filters.private)
async def adsmode_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    if len(message.command) >= 2 and message.command[1].lower() in MODE_LABELS:
        mode = message.command[1].lower()
        await client.mongodb.update_ads_setting("mode", mode)
        return await message.reply(f"✅ Unlock mode set to **{MODE_LABELS[mode]}**.")
    await message.reply(
        "**Usage:** `/adsmode one|two|all`\nOr use the buttons below:",
        reply_markup=_mode_keyboard(),
    )

def _mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"adsmode_set_{mode}") for mode, label in MODE_LABELS.items()],
        [InlineKeyboardButton("◂ Back", callback_data="adssettings")],
    ])

@Client.on_callback_query(filters.regex("^adsmode_panel$"))
async def adsmode_panel(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    await query.answer()
    s = await client.mongodb.get_ads_settings()
    await query.message.edit_text(
        f"<blockquote>✦ UNLOCK MODE</blockquote>\n**Current:** {MODE_LABELS.get(s['mode'], s['mode'])}\n\n"
        "Choose how many ad units a free user must complete to unlock a file:",
        reply_markup=_mode_keyboard(),
    )

@Client.on_callback_query(filters.regex(r"^adsmode_set_(one|two|all)$"))
async def adsmode_set(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    mode = query.data.rsplit("_", 1)[1]
    await client.mongodb.update_ads_setting("mode", mode)
    await query.answer(f"Mode set to {MODE_LABELS[mode]}!")
    msg, keyboard = await build_settings_panel(client)
    await query.message.edit_text(msg, reply_markup=keyboard)

#===============================================================#
# Per-zone id commands: one handler for all five /set... commands.

@Client.on_message(filters.command(list(COMMAND_TO_ZONE.keys())) & filters.private)
async def set_zone_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")

    zone_type = COMMAND_TO_ZONE[message.command[0].lower()]
    _, label = ZONE_TYPES[zone_type]

    if len(message.command) < 2:
        if zone_type == "native_banner":
            return await message.reply(
                f"**{label} — paste your Adsterra ad code** (the full `<script>` + container `<div>` snippet) "
                f"as your next message, or use the button in `/adssettings` since it's usually multi-line."
            )
        s = await client.mongodb.get_ads_settings()
        current = s["zones"].get(zone_type) or "not set"
        return await message.reply(
            f"**{label} zone — current:** `{current}`\n\n"
            f"**Usage:** `/{message.command[0]} <zone_id>` or `/{message.command[0]} off` to clear it."
        )

    value = message.text.split(" ", 1)[1].strip()
    value = "" if value.lower() in ("off", "none", "clear", "0") else value
    await client.mongodb.set_ads_zone(zone_type, value)
    await message.reply(f"✅ **{label}** {'cleared.' if not value else 'updated.'}")

@Client.on_callback_query(filters.regex(r"^adszone_(\w+)$"))
async def set_zone_callback(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)

    zone_type = query.data.split("_", 1)[1]
    if zone_type not in ZONE_TYPES:
        return await query.answer()
    cmd, label = ZONE_TYPES[zone_type]
    is_banner = zone_type == "native_banner"

    await query.answer()
    s = await client.mongodb.get_ads_settings()
    current = s["zones"].get(zone_type) or ""
    current_display = (f"custom code set ({len(current)} chars)" if is_banner else current) or "not set"
    prompt = (
        "Paste the full Adsterra native banner code (the `<script>` tag plus its container `<div>`) "
        "in the next 120 seconds, or send `off` to clear it."
        if is_banner else
        "Send the Monetag zone id in the next 60 seconds, or `off` to clear it."
    )
    await query.message.edit_text(
        f"<blockquote>**Set {label}**</blockquote>\n**Current:** `{current_display}`\n\n{prompt}"
    )
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=120 if is_banner else 60)
        value = res.text.strip()
        value = "" if value.lower() in ("off", "none", "clear", "0") else value
        await client.mongodb.set_ads_zone(zone_type, value)
        await res.reply(
            f"✅ **{label}** {'cleared.' if not value else 'updated.'}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◂ Back", callback_data="adssettings")]]),
        )
    except ListenerTimeout:
        await query.message.edit_text(
            "⏰ Timeout, try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◂ Back", callback_data="adssettings")]]),
        )

#===============================================================#
# Site color template — same page structure, different CSS variables.

@Client.on_message(filters.command("template") & filters.private)
async def template_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    if len(message.command) >= 2 and message.command[1].lower() in TEMPLATE_LABELS:
        template = message.command[1].lower()
        await client.mongodb.update_site_setting("template", template)
        return await message.reply(f"✅ Site template set to **{TEMPLATE_LABELS[template]}**.")
    await message.reply("**Usage:** `/template violet|emerald|sunset`\nOr use the buttons below:", reply_markup=_template_keyboard())

def _template_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"template_set_{key}") for key, label in TEMPLATE_LABELS.items()],
        [InlineKeyboardButton("◂ Back", callback_data="adssettings")],
    ])

@Client.on_callback_query(filters.regex("^template_panel$"))
async def template_panel(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    await query.answer()
    site = await client.mongodb.get_site_settings()
    await query.message.edit_text(
        f"<blockquote>✦ SITE TEMPLATE</blockquote>\n**Current:** {TEMPLATE_LABELS.get(site['template'], site['template'])}\n\n"
        "Applies to both the home page and the ad-unlock Mini App page — same layout, different colors:",
        reply_markup=_template_keyboard(),
    )

@Client.on_callback_query(filters.regex(r"^template_set_(violet|emerald|sunset)$"))
async def template_set(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    template = query.data.rsplit("_", 1)[1]
    await client.mongodb.update_site_setting("template", template)
    await query.answer(f"Template set to {TEMPLATE_LABELS[template]}!")
    msg, keyboard = await build_settings_panel(client)
    await query.message.edit_text(msg, reply_markup=keyboard)

#===============================================================#
# Native banner height: the space reserved for the Adsterra banner on the
# watch page (the banner still grows if the ad itself is taller).

def _bannerh_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{h}px", callback_data=f"bannerh_set_{h}") for h in BANNER_HEIGHTS[i:i + 3]]
            for i in range(0, len(BANNER_HEIGHTS), 3)]
    rows.append([InlineKeyboardButton("◂ Back", callback_data="adssettings")])
    return InlineKeyboardMarkup(rows)

@Client.on_message(filters.command("bannerheight") & filters.private)
async def bannerheight_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    if len(message.command) >= 2 and message.command[1].isdigit():
        px = int(message.command[1])
        if not BANNER_MIN <= px <= BANNER_MAX:
            return await message.reply(f"✗ Choose a height between {BANNER_MIN} and {BANNER_MAX} px.")
        await client.mongodb.update_site_setting("banner_min_height", px)
        return await message.reply(f"✅ Native banner height set to **{px}px**. It applies to the next page load.")
    site = await client.mongodb.get_site_settings()
    await message.reply(
        f"**Usage:** `/bannerheight <{BANNER_MIN}-{BANNER_MAX}>` — current: `{site['banner_min_height']}px`\n"
        "Or pick a preset:", reply_markup=_bannerh_keyboard())

@Client.on_callback_query(filters.regex("^bannerh_panel$"))
async def bannerh_panel(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    await query.answer()
    site = await client.mongodb.get_site_settings()
    await query.message.edit_text(
        f"<blockquote>✦ NATIVE BANNER HEIGHT</blockquote>\n**Current:** `{site['banner_min_height']}px`\n\n"
        "Space reserved for the banner on the watch page. The banner still grows if your Adsterra unit is taller; "
        "pick a smaller value if you see empty space under it.",
        reply_markup=_bannerh_keyboard())

@Client.on_callback_query(filters.regex(r"^bannerh_set_(\d+)$"))
async def bannerh_set(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    px = int(query.data.rsplit("_", 1)[1])
    if not BANNER_MIN <= px <= BANNER_MAX:
        return await query.answer("Out of range.", show_alert=True)
    await client.mongodb.update_site_setting("banner_min_height", px)
    await query.answer(f"Banner height set to {px}px!")
    msg, keyboard = await build_settings_panel(client)
    await query.message.edit_text(msg, reply_markup=keyboard)

#===============================================================#
# Monetag server-side postback URL — shown to the admin to paste into the
# Monetag SSP dashboard (per rewarded zone). Only Rewarded Interstitial and
# Rewarded Popup support postbacks; see plugins/route.py's /postback/monetag.

@Client.on_message(filters.command("postbackurl") & filters.private)
async def postback_url_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")

    url = (
        f"{WEBAPP_URL}/postback/monetag?secret={POSTBACK_SECRET}"
        "&ymid={ymid}&event={event_type}&value={reward_event_type}"
        "&zone={zone_id}&sub={sub_zone_id}&price={estimated_price}&telegram_id={telegram_id}"
    )
    await message.reply(
        "<blockquote>✦ MONETAG POSTBACK URL</blockquote>\n"
        "Paste this into the Monetag SSP dashboard for your **Rewarded Interstitial** and "
        "**Rewarded Popup** zones (postbacks aren't supported for other formats):\n\n"
        f"`{url}`\n\n"
        "<i>⚠️ Make sure POSTBACK_SECRET in .env is changed from the default before going live — "
        "it's the only thing stopping random requests from faking ad-watch events.</i>",
        disable_web_page_preview=True,
    )
# country grouped by ad-industry CPM tier — see helper/geo.py).

def _format_stats(stats: dict, title: str) -> str:
    tier_lines = "\n".join(
        f"›› {GEO_TIER_LABELS.get(int(k[4:]), f'Tier {k[4:]}')}: `{v}`"
        for k, v in sorted(stats.items()) if k.startswith("tier")
    ) or "_No data yet._"
    unique = stats.get("unique_users")
    unique_line = f"\n›› **Unique users:** `{unique}`" if unique is not None else ""
    return (
        f"<blockquote>✦ ADS STATS — {title}</blockquote>\n"
        f"›› **Total ads watched:** `{stats.get('total', 0)}`{unique_line}\n"
        f"›› **Unlocked without an ad (blocked / no fill):** `{stats.get('skipped', 0)}`\n\n"
        f"**By visitor GEO tier (from IP):**\n{tier_lines}"
    )

def _stats_keyboard(active: str) -> InlineKeyboardMarkup:
    labels = {"today": "Today", "week": "7 Days", "month": "30 Days", "lifetime": "Lifetime"}
    row = [
        InlineKeyboardButton(("• " + label if key == active else label), callback_data=f"adsstats_range_{key}")
        for key, label in labels.items()
    ]
    return InlineKeyboardMarkup([row[:2], row[2:], [InlineKeyboardButton("◂ Back", callback_data="adssettings")]])

@Client.on_message(filters.command("adsstats") & filters.private)
async def adsstats_command(client: Client, message: Message):
    if not _is_admin(message.from_user.id, client):
        return await message.reply("✗ Only admins can use this.")
    stats = await client.mongodb.get_ads_stats(STATS_RANGES["today"])
    await message.reply(_format_stats(stats, "Today"), reply_markup=_stats_keyboard("today"))

@Client.on_callback_query(filters.regex("^adsstats_panel$"))
async def adsstats_panel(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    await query.answer()
    stats = await client.mongodb.get_ads_stats(STATS_RANGES["today"])
    await query.message.edit_text(_format_stats(stats, "Today"), reply_markup=_stats_keyboard("today"))

@Client.on_callback_query(filters.regex(r"^adsstats_range_(today|week|month|lifetime)$"))
async def adsstats_range(client: Client, query: CallbackQuery):
    if not _is_admin(query.from_user.id, client):
        return await query.answer("✗ Only admins can use this!", show_alert=True)
    range_key = query.data.rsplit("_", 1)[1]
    await query.answer()
    stats = await client.mongodb.get_ads_stats(STATS_RANGES[range_key])
    title = {"today": "Today", "week": "Last 7 Days", "month": "Last 30 Days", "lifetime": "Lifetime"}[range_key]
    await query.message.edit_text(_format_stats(stats, title), reply_markup=_stats_keyboard(range_key))
