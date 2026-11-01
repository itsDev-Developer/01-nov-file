
import asyncio
import sys
from bot import Bot, web_app
from pyrogram import compose
from config import *

bot = None  # populated inside main() once the event loop is running


async def main():
    global bot
    # Stop early, with a readable message, if the settings are missing or unusable.
    from helper.preflight import config_errors
    problems = config_errors()
    if problems:
        sys.exit("\nCannot start — fix these settings first:\n  - " + "\n  - ".join(problems) + "\n")
    # IMPORTANT: the Bot (and the Motor/MongoDB client created inside it)
    # must be constructed *after* asyncio.run() has started the event loop.
    # Building it at module level, before any loop exists, was the bug that
    # broke every command last time: Motor binds its client to whatever
    # event loop is current at construction time, so a client built before
    # the real loop starts ends up attached to the wrong loop and every
    # database call afterwards fails silently.
    bot = Bot(
        SESSION,
        WORKERS,
        DB_CHANNEL,
        FSUBS,
        TOKEN,
        ADMINS,
        MESSAGES,
        AUTO_DEL,
        DB_URI,
        DB_NAME,
        API_ID,
        API_HASH,
        PROTECT,
        DISABLE_BTN
    )
    await asyncio.gather(
        compose([bot]),
        web_app(bot)
    )

asyncio.run(main())
