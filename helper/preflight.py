"""Start-up checks of the settings (loaded from .env / the environment by config.py).

`config_errors()` are problems that make the bot unable to run: main.py stops with a clear message instead of
crashing later with something cryptic. `config_warnings()` are settings still at a placeholder value that
silently break a feature; they are logged at boot.
"""

import config
from config import API_ENABLED, POSTBACK_SECRET, WEBAPP_URL

ENV_HINT = "Fill them in `.env` (copy `.env.example` to `.env`) or set them as environment variables."


def config_errors() -> list:
    problems = list(config._ENV_PROBLEMS)  # values that were set but unusable (wrong type, bad JSON, ...)
    required = [
        ("BOT_TOKEN", bool(config.TOKEN)),
        ("API_ID", str(config.API_ID).isdigit()),
        ("API_HASH", bool(config.API_HASH)),
        ("OWNER_ID", config.OWNER_ID != 0),
        ("DB_URI", bool(config.DB_URI)),
        ("DB_NAME", bool(config.DB_NAME)),
        ("DB_CHANNEL", config.DB_CHANNEL != 0),
    ]
    missing = [name for name, ok in required if not ok]
    if missing:
        where = config.ENV_FILE_USED or "no .env file was found next to config.py"
        problems.append(f"Missing or invalid: {', '.join(missing)} (settings file: {where}). {ENV_HINT}")
    return problems


def config_warnings() -> list:
    problems = []
    if "example.com" in WEBAPP_URL or not WEBAPP_URL.startswith("https://"):
        problems.append(
            "WEBAPP_URL is not a real public HTTPS address (currently: %s). The 'Unlock' button, the watch page, "
            "the API docs and API links will not work until you set it in .env." % WEBAPP_URL
        )
    if POSTBACK_SECRET == "change-this-postback-secret":
        problems.append(
            "POSTBACK_SECRET is still the default. Change it in .env, then re-copy the URL from /postbackurl into Monetag."
        )
    if not API_ENABLED:
        problems.append("API_ENABLED is false: the link/premium API will answer 503.")
    return problems
