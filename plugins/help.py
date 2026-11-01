"""A single source of truth for "what commands exist" — shown via /help.
Kept as plain data (COMMAND_GROUPS) so adding a new command elsewhere in the
bot just means adding one line here, not rewriting a big string each time.
"""

from pyrogram import Client, filters
from pyrogram.types import Message

USER_COMMANDS = [
    ("/start", "Open the bot, or a shared file link"),
    ("/profile", "Your details, plan and what applies to you"),
    ("/myplan", "Premium perks, purchase date, expiry and renew"),
    ("/request <text>", "Send a request to the owner (premium users)"),
]

ADMIN_FILE_COMMANDS = [
    ("/genlink", "Generate a share link for a single file"),
    ("/batch", "Generate a share link for a batch of files"),
    ("/nbatch <n>", "Generate a batch link for the next <n> files"),
    ("/adddb <id>", "Add a database channel (alias: /add_db)"),
    ("/removedb <id>", "Remove a database channel (alias: /rm_db)"),
    ("/db", "View configured database channel(s)"),
]

ADMIN_USER_COMMANDS = [
    ("/users", "Total user count"),
    ("/ban <id>", "Ban a user from the bot"),
    ("/unban <id>", "Unban a user"),
    ("/addpremium <id> [duration]", "Grant premium: 1 day, 2 weeks, 1 month, 1 year (omit = permanent)"),
    ("/delpremium <id>", "Remove premium access"),
    ("/premiumusers", "List all premium users"),
    ("/premiumsettings", "Set the premium buy link, contact and perks list"),
    ("/setpremiumurl <url|off>", "Where Buy / Activate / Renew buttons point"),
    ("/setcontact <url|@user|off>", "Contact button on /profile"),
    ("/setpremiumfeatures", "Perks list shown on premium screens (one per line)"),
]

ADMIN_BROADCAST_COMMANDS = [
    ("/broadcast", "Broadcast a message to every user (reply to a message)"),
    ("/pbroadcast", "Broadcast + pin the message in each chat"),
]

ADMIN_ADS_COMMANDS = [
    ("/adssettings", "Open the full ads settings panel"),
    ("/adsenable", "Turn the ad-unlock gate on"),
    ("/adsdisable", "Turn the ad-unlock gate off"),
    ("/adsmode <one|two|all>", "How many ad units a free user must clear"),
    ("/setinterstitial <zone|off>", "Set the Interstitial ad zone"),
    ("/setinappinterstitial <zone|off>", "Set the In-App Interstitial ad zone"),
    ("/setrewardedinterstitial <zone|off>", "Set the Rewarded Interstitial ad zone"),
    ("/setpopup <zone|off>", "Set the Rewarded Popup ad zone"),
    ("/setnativebanner <code|off>", "Set the Native Banner ad code (Adsterra)"),
    ("/adsstats", "Watch stats — today/7d/30d/lifetime, by visitor GEO tier"),
    ("/postbackurl", "Get the Monetag server-side postback URL to configure"),
    ("/bannerheight <px>", "Space reserved for the native banner on the watch page"),
    ("/template <violet|emerald|sunset>", "Set the home/unlock page color theme"),
]

ADMIN_API_COMMANDS = [
    ("/apikeys", "Manage API keys: create, revoke, per-bot usage"),
    ("/newapikey <label> [scopes]", "Create an API key (scopes: links, premium, users)"),
    ("/apikeyscopes <id> <scopes>", "Change what an API key is allowed to do"),
    ("/revokeapikey <id>", "Revoke an API key"),
    ("/apidocs", "Link to the API documentation"),
]

ADMIN_OTHER_COMMANDS = [
    ("/shortner", "Configure the link shortener"),
    ("/stats", "Bot uptime, storage and system stats"),
    ("/resources [1h|24h]", "RAM, CPU, loop lag and more — now, min, avg, max + daily history"),
]


ALL_ADMIN_COMMANDS = (
    ADMIN_FILE_COMMANDS + ADMIN_USER_COMMANDS + ADMIN_BROADCAST_COMMANDS
    + ADMIN_ADS_COMMANDS + ADMIN_API_COMMANDS + ADMIN_OTHER_COMMANDS
)


def _format_group(title: str, commands: list) -> str:
    lines = "\n".join(f"›› {cmd} — {desc}" for cmd, desc in commands)
    return f"<b>{title}</b>\n{lines}"


def _build_help_text(user_id: int, admins: list) -> str:
    sections = [_format_group("👤 For Everyone", USER_COMMANDS)]
    if user_id in admins:
        sections += [
            _format_group("📁 Files & Channels", ADMIN_FILE_COMMANDS),
            _format_group("🧑‍🤝‍🧑 Users", ADMIN_USER_COMMANDS),
            _format_group("📢 Broadcast", ADMIN_BROADCAST_COMMANDS),
            _format_group("💰 Ads (Monetag)", ADMIN_ADS_COMMANDS),
            _format_group("🔌 Link API", ADMIN_API_COMMANDS),
            _format_group("⚙️ Other", ADMIN_OTHER_COMMANDS),
        ]
    return "<blockquote>📖 <b>Command Reference</b></blockquote>\n\n" + "\n\n".join(sections)


@Client.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    await message.reply(_build_help_text(message.from_user.id, client.admins), disable_web_page_preview=True)
