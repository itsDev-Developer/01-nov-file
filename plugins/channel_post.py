import asyncio
from pyrogram import filters, Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from helper.helper_func import encode, flood_seconds

#===============================================================#

# Any private *text* message starting with "/" is a command meant for some
# other handler. The old version hard-coded a list of command names here, so
# every command added later (/help, /nbatch, the ads and API commands...) got
# silently swallowed and copied into the DB channel whenever this plugin loaded
# first. Matching "any slash command" once is robust no matter what gets added.
def _is_not_command(_, __, message):
    return not (message.text and message.text.startswith("/"))

not_command = filters.create(_is_not_command)

@Client.on_message(filters.private & not_command)
async def channel_post(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    reply_text = await message.reply_text("Please Wait...!", quote = True)
    try:
        post_message = await message.copy(chat_id = client.db, disable_notification=True)
    except FloodWait as e:
        await asyncio.sleep(flood_seconds(e))
        post_message = await message.copy(chat_id = client.db, disable_notification=True)
    except Exception as e:
        print(e)
        await reply_text.edit_text("Something went Wrong..!")
        return
    converted_id = post_message.id * abs(client.db)
    string = f"get-{converted_id}"
    base64_string = await encode(string)
    link = f"https://t.me/{client.username}?start={base64_string}"

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Share URL", url=f'https://telegram.me/share/url?url={link}')]])

    await reply_text.edit(f"<b>Here is your link</b>\n\n{link}", reply_markup=reply_markup, disable_web_page_preview = True)

    if not client.disable_btn:
        await post_message.edit_reply_markup(reply_markup)

#===============================================================#

@Client.on_message(filters.channel & filters.incoming)
async def new_post(client: Client, message: Message):
    if message.chat.id != client.db:
        return
    if client.disable_btn:
        return

    converted_id = message.id * abs(client.db)
    string = f"get-{converted_id}"
    base64_string = await encode(string)
    link = f"https://t.me/{client.username}?start={base64_string}"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Share URL", url=f'https://telegram.me/share/url?url={link}')]])
    try:
        await message.edit_reply_markup(reply_markup)
    except Exception as e:
        print(e)

        pass





