"""All settings for the bot.

Where the values come from, highest priority first:
  1. real environment variables (Heroku config vars, `docker run -e`, systemd, ...)
  2. the `.env` file next to this file (or the path in ENV_FILE)
  3. the defaults below

So: fill in `.env` (copy `.env.example`) and you normally never edit this file. Long, editable
texts live in MESSAGES at the bottom; they can also be changed from inside the bot.
"""

import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


# --- .env loading ---------------------------------------------------------------------------
def _parse_dotenv(text: str) -> dict:
    """KEY=VALUE per line. Understands `#` comment lines, an optional `export `, single/double quotes
    around a value, and `=` inside values (MongoDB URLs). In an unquoted value a comment starts at
    whitespace followed by `#`, so `abc#def` is data. Lines that aren't KEY=VALUE are ignored."""
    values = {}
    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote, value = value[0], value[1:-1]
            if quote == '"':
                value = value.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        else:
            comment = re.search(r"\s+#", value)
            if comment:
                value = value[:comment.start()].rstrip()
        values[key] = value
    return values


def load_dotenv(path) -> str:
    """Fill os.environ from the file. A variable that is already set (and not empty) is left alone,
    so the real environment always wins. Returns the path used, or "" if there is no such file."""
    path = Path(path)
    if not path.is_file():
        return ""
    for key, value in _parse_dotenv(path.read_text(encoding="utf-8")).items():
        if not os.environ.get(key):
            os.environ[key] = value
    return str(path)


ENV_FILE_USED = load_dotenv(os.environ.get("ENV_FILE") or Path(__file__).with_name(".env"))

_ENV_PROBLEMS = []  # values that were set but unusable; reported at start-up (helper/preflight.py)


def _env(name, default=None, cast=str):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return cast(raw.strip())
    except Exception as e:
        _ENV_PROBLEMS.append(f"{name} is not valid ({type(e).__name__}); using the default")
        return default


def _bool(value: str) -> bool:
    return {"1": True, "true": True, "yes": True, "on": True,
            "0": False, "false": False, "no": False, "off": False}[value.lower()]


def _int_list(value: str) -> list:
    """`1,2,3`, `1 2 3` or a JSON list."""
    return [int(x) for x in re.split(r"[,\s]+", value.strip("[] ")) if x]


def _fsubs(value: str) -> list:
    """JSON: [[channel_id, request_to_join (true/false), invite_link_minutes], ...]"""
    parsed = json.loads(value)
    for item in parsed:
        channel, request, timer = item
        if not (isinstance(channel, int) and isinstance(request, bool) and isinstance(timer, int)):
            raise ValueError("each entry must be [int, true/false, int]")
    return parsed


# --- Telegram / database (required) -------------------------------------------------------------
TOKEN = _env("BOT_TOKEN", "")
API_ID = _env("API_ID", "")
API_HASH = _env("API_HASH", "")
OWNER_ID = _env("OWNER_ID", 0, int)
ADMINS = _env("ADMINS", [], _int_list)
if OWNER_ID and OWNER_ID not in ADMINS:
    ADMINS.append(OWNER_ID)  # the owner is always an admin
DB_URI = _env("DB_URI", "")
DB_NAME = _env("DB_NAME", "")
DB_CHANNEL = _env("DB_CHANNEL", 0, int)  # primary storage channel (more can be added with /adddb)

# --- Bot behaviour ---------------------------------------------------------------------------------
SESSION = _env("SESSION", "FileStoreBot")
WORKERS = _env("WORKERS", 4, int)
FSUBS = _env("FSUBS", [], _fsubs)  # force-subscribe channels
AUTO_DEL = _env("AUTO_DEL", 0, int)  # seconds before delivered files are deleted (0 = never)
PROTECT = _env("PROTECT", False, _bool)  # block forwarding/saving of delivered files
DISABLE_BTN = _env("DISABLE_BTN", False, _bool)  # hide the Share button on stored posts
MSG_EFFECT = _env("MSG_EFFECT", 5046509860389126442, int)

# --- Web server, ads, API --------------------------------------------------------------------------
PORT = _env("PORT", 5010, int)  # hosts that inject $PORT are followed automatically
# WEBAPP_URL MUST be the public HTTPS address of this server: Telegram only opens Mini Apps on HTTPS,
# and API / watch-page links are built from it.
WEBAPP_URL = _env("WEBAPP_URL", "https://your-app-domain.example.com").rstrip("/")
POSTBACK_SECRET = _env("POSTBACK_SECRET", "change-this-postback-secret")  # shared secret in the Monetag postback URL
MONETAG_SDK_SRC = _env("MONETAG_SDK_SRC", "//libtl.com/sdk.js")
DEFAULT_AD_ZONE = _env("DEFAULT_AD_ZONE", "10739699")  # only shown as an example in the admin panel
VERIFY_SESSION_TTL = _env("VERIFY_SESSION_TTL", 600, int)  # seconds an unlock link stays valid
MIN_AD_STEP_SECONDS = _env("MIN_AD_STEP_SECONDS", 2, int)  # anti-bypass: minimum plausible time per ad step
AD_FAIL_OPEN_AFTER = _env("AD_FAIL_OPEN_AFTER", 3, int)  # let a user through after N failed attempts at one ad (0 = never)
BANNER_MIN_HEIGHT = _env("BANNER_MIN_HEIGHT", 300, int)  # px; also changeable with /bannerheight

API_ENABLED = _env("API_ENABLED", True, _bool)
API_RATE_LIMIT_PER_MIN = _env("API_RATE_LIMIT_PER_MIN", 60, int)
API_MAX_BATCH = _env("API_MAX_BATCH", 100, int)
API_MAX_UPLOAD_MB = _env("API_MAX_UPLOAD_MB", 512, int)
API_SCOPES = ("links", "premium", "users")  # what an API key can be allowed to do (not configurable)

# --- Premium / contact -----------------------------------------------------------------------------------
DEFAULT_PREMIUM_URL = _env("DEFAULT_PREMIUM_URL", "https://t.me/Uchiha_Community")  # until you run /setpremiumurl
CONTACT_USERNAME = _env("CONTACT_USERNAME", "tojma")  # "Buy this bot / Hire me" on the landing page

# --- Link shortener (the admin panel can change these live) ---------------------------------------------------
SHORT_URL = _env("SHORT_URL", "uchihalinks.gt.tc")
SHORT_API = _env("SHORT_API", "")
SHORT_TUT = _env("SHORT_TUT", "https://t.me/hw2openlinks")

# --- Logging -----------------------------------------------------------------------------------------------------
LOG_FILE_NAME = _env("LOG_FILE_NAME", "bot.log")
LOG_MAX_MB = _env("LOG_MAX_MB", 50, int)  # per file; total disk use is about (LOG_BACKUPS + 1) x this
LOG_BACKUPS = _env("LOG_BACKUPS", 10, int)

# Messages Configuration
MESSAGES = {
    "START": "<b>›› ʜᴇʏ!!, {first} ~ <blockquote>ʟᴏᴠᴇ ᴘᴏʀɴʜᴡᴀ? ɪ ᴀᴍ ᴍᴀᴅᴇ ᴛᴏ ʜᴇʟᴘ ʏᴏᴜ ᴛᴏ ғɪɴᴅ ᴡʜᴀᴛ ʏᴏᴜ aʀᴇ ʟᴏᴏᴋɪɴɢ ꜰᴏʀ.</blockquote></b>",
    "FSUB": "<b><blockquote>›› ʜᴇʏ ×</blockquote>\n  ʏᴏᴜʀ ғɪʟᴇ ɪs ʀᴇᴀᴅʏ ‼️ ʟᴏᴏᴋs ʟɪᴋᴇ ʏᴏᴜ ʜᴀᴠᴇɴ'ᴛ sᴜʙsᴄʀɪʙᴇᴅ ᴛᴏ ᴏᴜʀ ᴄʜᴀɴɴᴇʟs ʏᴇᴛ, sᴜʙsᴄʀɪʙᴇ ɴᴏᴡ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ғɪʟᴇs</b>",
    "ABOUT": "<b>›› ғᴏʀ ᴍᴏʀᴇ: @Uchiha_Community \n <blockquote expandable>›› ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ: <a href='https://t.me/Uchiha_Developer'>Cʟɪᴄᴋ ʜᴇʀᴇ</a> \n›› ᴏᴡɴᴇʀ: @Tojma\n›› ʟᴀɴɢᴜᴀɢᴇ: <a href='https://docs.python.org/3/'>Pʏᴛʜᴏɴ 3</a> \n›› ʟɪʙʀᴀʀʏ: <a href='https://docs.pyrogram.org/'>Pʏʀᴏɢʀᴀᴍ ᴠ2</a> \n›› ᴅᴀᴛᴀʙᴀsᴇ: <a href='https://www.mongodb.com/docs/'>Mᴏɴɢᴏ ᴅʙ</a> \n›› ᴅᴇᴠᴇʟᴏᴘᴇʀ: @Its_Sasuke_Uchiha</b></blockquote>",
    "REPLY": "<b>For More Join - @Jav_xxx</b>",
    "SHORT_MSG": "<b>📊 ʜᴇʏ {first}, \n\n‼️ ɢᴇᴛ ᴀʟʟ ꜰɪʟᴇꜱ ɪɴ ᴀ ꜱɪɴɢʟᴇ ʟɪɴᴋ ‼️\n\n ⌯ ʏᴏᴜʀ ʟɪɴᴋ ɪꜱ ʀᴇᴀᴅʏ, ᴋɪɴᴅʟʏ ᴄʟɪᴄᴋ ᴏɴ ᴏᴘᴇɴ ʟɪɴᴋ ʙᴜᴛᴛᴏɴ..</b>",
    "START_PHOTO": "https://graph.org/file/510affa3d4b6c911c12e3.jpg",
    "FSUB_PHOTO": "https://telegra.ph/file/7a16ef7abae23bd238c82-b8fbdcb05422d71974.jpg",
    "SHORT_PIC": "https://telegra.ph/file/7a16ef7abae23bd238c82-b8fbdcb05422d71974.jpg",
    "SHORT": "https://telegra.ph/file/8aaf4df8c138c6685dcee-05d3b183d4978ec347.jpg",
    "UNLOCK_PHOTO": "https://telegra.ph/file/7a16ef7abae23bd238c82-b8fbdcb05422d71974.jpg"
}

# Images can differ per bot, so they can be set in .env too (START_PHOTO, FSUB_PHOTO, SHORT_PIC, SHORT_IMAGE, UNLOCK_PHOTO).
for _key, _var in (("START_PHOTO", "START_PHOTO"), ("FSUB_PHOTO", "FSUB_PHOTO"), ("SHORT_PIC", "SHORT_PIC"),
                   ("SHORT", "SHORT_IMAGE"), ("UNLOCK_PHOTO", "UNLOCK_PHOTO")):
    if _key in MESSAGES:
        MESSAGES[_key] = _env(_var, MESSAGES[_key])


_configured_loggers = set()


def LOGGER(name: str, client_name: str) -> logging.Logger:
    """Logger for `name`. Handlers are attached only the first time: this function is called
    for every log line (`client.LOGGER(__name__, ...).warning(...)`), and adding a fresh file +
    console handler on each call made every line print N times after N calls and leaked an open
    file handle per call."""
    logger = logging.getLogger(name)
    if name in _configured_loggers:
        return logger
    _configured_loggers.add(name)
    formatter = logging.Formatter(
        f"[%(asctime)s - %(levelname)s] - {client_name} - %(name)s - %(message)s",
        datefmt='%d-%b-%y %H:%M:%S'
    )
    file_handler = RotatingFileHandler(LOG_FILE_NAME, maxBytes=LOG_MAX_MB * 1_000_000, backupCount=LOG_BACKUPS)
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger
