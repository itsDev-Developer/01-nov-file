"""Everything users see about premium, in one place: the `?start=premium`
deep link, /myplan and /profile all build their text and buttons here, so the
perks list, dates and buy/contact links can never drift apart between screens.

All text is HTML: dynamic values (names, admin-written perks) are escaped, and
callers send with ParseMode.HTML so a stray `*` or `_` in a name can't break
formatting the way it could under the default Markdown+HTML mode.
"""

import html
import re
from datetime import datetime

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import DEFAULT_PREMIUM_URL, OWNER_ID

# Only perks the bot really enforces: ads and shortener are skipped for
# premium (ads_func.user_is_exempt / the shortener check in start.py) and
# /request is premium-only. Admins can replace this list with /setpremiumfeatures.
BUILTIN_FEATURES = [
    "No ads — skip the ad verification step",
    "No link shortener — files come straight to you",
    "Send file requests to the admin with /request",
]
MAX_FEATURES, MAX_FEATURE_LEN = 10, 100


# --- admin input -----------------------------------------------------------

def normalize_url(raw: str):
    """What an admin typed -> a URL Telegram will accept on a button, or None.
    Accepts https://…, http://…, tg://…, t.me/… and @username."""
    raw = (raw or "").strip()
    if not raw or len(raw) > 512 or any(c.isspace() for c in raw):
        return None
    if raw.startswith("@") and re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{3,31}", raw):
        return f"https://t.me/{raw[1:]}"
    if re.match(r"(?i)^(t\.me|telegram\.me)/", raw):
        raw = "https://" + raw
    return raw if re.match(r"(?i)^(https?|tg)://\S+$", raw) else None


def parse_features(raw: str):
    """One perk per line -> cleaned list, or None if it breaks the limits."""
    lines = [re.sub(r"^[\s•\-*✅✔️▪️›»]+", "", ln).strip() for ln in (raw or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines or len(lines) > MAX_FEATURES or any(len(ln) > MAX_FEATURE_LEN for ln in lines):
        return None
    return lines


# --- formatting ------------------------------------------------------------

def fmt_date(dt: datetime) -> str:
    return dt.strftime("%d %b %Y")


def time_left(expires: datetime, now: datetime) -> str:
    seconds = int((expires - now).total_seconds())
    if seconds <= 0:
        return "expired"
    days, rem = divmod(seconds, 86400)
    if days >= 1:
        return f"{days} day{'s' if days != 1 else ''} left"
    hours = rem // 3600
    return f"{hours} hour{'s' if hours != 1 else ''} left" if hours else "less than an hour left"


def features_block(features: list) -> str:
    return "\n".join(f"✅ {html.escape(f)}" for f in features)


def plan_lines(info: dict, now: datetime, *, detailed: bool) -> str:
    """Expiry (+ purchase dates when `detailed`) for an active member."""
    lines = ["♾ <b>Lifetime</b> membership — it never expires"] if info["permanent"] else [
        f"⏳ <b>Expires:</b> {fmt_date(info['expires_at'])} ({time_left(info['expires_at'], now)})"
    ]
    if detailed:
        since, updated = info.get("since"), info.get("updated_at")
        lines.append(f"🗓 <b>Purchased:</b> {fmt_date(since)}" if since else "🗓 <b>Purchased:</b> not recorded")
        if since and updated and (updated - since).total_seconds() > 300:
            lines.append(f"🔄 <b>Last renewed:</b> {fmt_date(updated)}")
    return "\n".join(lines)


# --- settings --------------------------------------------------------------

async def get_links_and_features(client) -> tuple:
    """(buy_url, contact_url, features) with defaults applied."""
    s = await client.mongodb.get_premium_settings()
    return s.get("buy_url") or DEFAULT_PREMIUM_URL, s.get("contact_url") or "", s.get("features") or list(BUILTIN_FEATURES)


async def get_buy_url(client) -> str:
    """The one place every 'Buy Premium' button gets its link from."""
    return (await get_links_and_features(client))[0]


# --- keyboards ---------------------------------------------------------------

def keyboard(primary_label: str = None, buy_url: str = None, contact_url: str = "", *, contact: bool = False):
    rows = []
    top = []
    if primary_label:
        top.append(InlineKeyboardButton(primary_label, url=buy_url))
    if contact and contact_url:
        top.append(InlineKeyboardButton("📞 Contact", url=contact_url))
    if top:
        rows.append(top)
    rows.append([InlineKeyboardButton("Close", callback_data="close")])
    return InlineKeyboardMarkup(rows)


# --- screens -----------------------------------------------------------------

async def build_premium_screen(client, user_id: int, *, detailed: bool) -> tuple:
    """(text, keyboard) for `?start=premium` (detailed=False, Close only) and
    /myplan (detailed=True, adds purchase date and a Renew button)."""
    now = datetime.now()
    info = await client.mongodb.get_premium_info(user_id)
    buy_url, _, features = await get_links_and_features(client)

    if info["active"]:
        text = (
            "<b>💎 Premium Activated</b>\n\n"
            f"<blockquote>{plan_lines(info, now, detailed=detailed)}</blockquote>\n"
            f"<b>Your perks</b>\n{features_block(features)}"
        )
        return text, keyboard("🔄 Renew Premium", buy_url) if detailed else keyboard()

    text = (
        "<b>✨ Activate Premium</b>\n\n"
        "Upgrade once and enjoy:\n"
        f"{features_block(features)}\n\n"
        "<i>Tap the button below to get started.</i>"
    )
    return text, keyboard("✨ Activate Premium", buy_url)


def _switch(label_on: str, label_off: str, off_reason: str, applies: bool) -> str:
    return label_on if applies else f"{label_off}{off_reason}"


async def build_profile(client, user) -> tuple:
    """(text, keyboard) for /profile."""
    from helper.ads_func import get_required_ad_steps  # local import: ads_func pulls in pyrogram WebApp types

    now = datetime.now()
    uid = user.id
    info = await client.mongodb.get_premium_info(uid)
    premium = info["active"]
    is_owner, is_admin = uid == OWNER_ID, uid in client.admins
    buy_url, contact_url, _ = await get_links_and_features(client)

    # What each switch really does for THIS user (mirrors the checks in start.py / ads_func).
    ads_exempt = premium or is_admin
    short_exempt = premium or is_owner
    ads_active = bool(await get_required_ad_steps(client))
    short_active = bool(getattr(client, "shortner_enabled", True))
    why = lambda exempt: " — premium" if premium else (" — staff" if exempt else "")
    ads = "Off" + why(ads_exempt) if ads_exempt or not ads_active else "On"
    short = "Off" + why(short_exempt) if short_exempt or not short_active else "On"

    role = "👑 Owner" if is_owner else ("🛡 Admin" if is_admin else "👤 Member")
    name = html.escape(" ".join(p for p in (user.first_name, user.last_name) if p) or "Unknown")
    username = f"@{html.escape(user.username)}" if user.username else "—"

    if premium:
        plan = f"💎 <b>Premium</b>\n{plan_lines(info, now, detailed=True)}"
    else:
        plan = "🆓 <b>Free</b>\n<i>Go premium for no ads, no shortener and /request access.</i>"

    text = (
        "<b>👤 Your Profile</b>\n\n"
        f"<blockquote>🙍 <b>Name:</b> {name}\n"
        f"🔖 <b>Username:</b> {username}\n"
        f"🆔 <b>ID:</b> <code>{uid}</code>\n"
        f"🎭 <b>Role:</b> {role}</blockquote>\n"
        f"<b>Plan</b>\n{plan}\n\n"
        f"<b>What applies to you</b>\n"
        f"📺 Ads: {ads}\n"
        f"🔗 Link shortener: {short}\n"
        f"📩 Requests: {'Enabled' if premium else 'Premium only'}"
    )
    label = "🔄 Renew Premium" if premium else "💎 Buy Premium"
    return text, keyboard(label, buy_url, contact_url, contact=True)
