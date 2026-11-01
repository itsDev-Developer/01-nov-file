"""User-facing premium commands: /myplan and /profile.

The `?start=premium` deep link lives in start.py (it has to run before the
file-link logic) but builds its screen with the same helper, so all three
always agree. See helper/premium_ui.py.
"""

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from helper.premium_ui import build_premium_screen, build_profile


@Client.on_message(filters.command("myplan") & filters.private)
async def myplan_command(client: Client, message: Message):
    text, markup = await build_premium_screen(client, message.from_user.id, detailed=True)
    await message.reply(text, reply_markup=markup, parse_mode=ParseMode.HTML)


@Client.on_message(filters.command("profile") & filters.private)
async def profile_command(client: Client, message: Message):
    text, markup = await build_profile(client, message.from_user)
    await message.reply(text, reply_markup=markup, parse_mode=ParseMode.HTML)
