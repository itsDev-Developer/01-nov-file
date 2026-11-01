"""Decides *whether* and *how* a user must watch ads before getting a file.

Kept separate from helper_func.py because it's a distinct concern (monetization
gating) with its own config reads, and importing it doesn't need to pull in
the force-sub / message-copy machinery.
"""

import random
import uuid

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config import VERIFY_SESSION_TTL, WEBAPP_URL

# Priority order used to pick zones when the admin's chosen mode ("one"/"two")
# needs fewer steps than there are configured zone types. native_banner is
# excluded here — it's a passive banner on the page, never a blocking step.
AD_STEP_PRIORITY = ("inapp_interstitial", "interstitial", "rewarded_interstitial", "rewarded_popup")
AD_STEP_LABELS = {
    "inapp_interstitial": "In-App Interstitial ad",
    "interstitial": "Interstitial ad",
    "rewarded_interstitial": "Rewarded Interstitial ad",
    "rewarded_popup": "Rewarded Popup ad",
}
MODE_LIMITS = {"one": 1, "two": 2, "all": len(AD_STEP_PRIORITY)}

# Small rotating set of lines for the pre-unlock message — purely cosmetic,
# edit freely.
UNLOCK_QUOTES = [
    "Good things come to those who tap one button. 😉",
    "30 seconds of patience, unlimited content unlocked. 🚀",
    "One quick ad away from what you came here for.",
    "Almost there — your file is just a tap away. ⚡",
]


async def get_required_ad_steps(client) -> list:
    """Return the ordered list of ad-zone types a user must clear, or [] if
    ads are off / nothing is configured (fails open so misconfiguration never
    blocks file delivery)."""
    settings = await client.mongodb.get_ads_settings()
    if not settings.get("enabled"):
        return []
    zones = settings.get("zones", {})
    configured = [zone for zone in AD_STEP_PRIORITY if zones.get(zone)]
    if not configured:
        return []
    limit = MODE_LIMITS.get(settings.get("mode", "two"), 2)
    return configured[:limit]


async def user_is_exempt(client, user_id: int, is_pro: bool = None) -> bool:
    """Admins and premium users never see ads. Pass `is_pro` when the caller
    has already looked it up, to avoid reading the same document twice."""
    if user_id in client.admins:
        return True
    return await client.mongodb.is_pro(user_id) if is_pro is None else is_pro


async def create_unlock_session(client, user_id: int, base64_string: str, steps: list) -> str:
    token = uuid.uuid4().hex
    await client.mongodb.create_verify_session(token, user_id, base64_string, steps, VERIFY_SESSION_TTL)
    return token


def unlock_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🎬 Unlock & Watch", web_app=WebAppInfo(url=f"{WEBAPP_URL}/unlock/{token}"))]]
    )


def unlock_caption(steps: list) -> str:
    step_lines = "\n".join(f"{i}. {AD_STEP_LABELS.get(s, s)}" for i, s in enumerate(steps, 1))
    quote = random.choice(UNLOCK_QUOTES)
    return (
        "<b>🔐 Your content is ready — just one step left!</b>\n\n"
        "Tap below to open the quick verification screen — watch the "
        f"short ad(s) and it unlocks automatically.\n\n<blockquote>{step_lines}</blockquote>"
        f"\n<i>💬 {quote}</i>"
    )
