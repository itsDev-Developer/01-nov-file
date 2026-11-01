"""/resources — real RAM / CPU / etc. figures (now, min, avg, max) for this bot and its server.
The numbers come from helper/monitor.py, which samples in the background."""

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from helper.monitor import gather_extras, render_report

WINDOWS = {"1h": 1, "24h": 24}


@Client.on_message(filters.command("resources") & filters.private)
async def resources_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply("✗ Only admins can use this.")
    monitor = getattr(client, "monitor", None)
    if monitor is None:
        return await message.reply("The resource monitor isn't running (see the start-up log).")

    hours = WINDOWS.get(message.command[1].lower() if len(message.command) > 1 else "24h")
    if hours is None:
        return await message.reply("**Usage:** `/resources` or `/resources 1h`")
    days = await client.mongodb.get_resource_days(7)
    await message.reply(render_report(monitor, days, hours, gather_extras(client)), parse_mode=ParseMode.HTML)
