from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from config import MSG_EFFECT, OWNER_ID
from plugins.shortner import get_short
from helper.helper_func import force_sub
from helper.ads_func import get_required_ad_steps, user_is_exempt, create_unlock_session, unlock_keyboard, unlock_caption
from helper.delivery import deliver_payload
from helper.premium_ui import build_premium_screen, get_buy_url
from pyrogram.enums import ParseMode

#===============================================================#

@Client.on_message(filters.command('start') & filters.private)
@force_sub
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id

    # 1+2. Register new users and check bans with a single read
    present, is_banned = await client.mongodb.get_user_state(user_id)
    if not present:
        try:
            await client.mongodb.add_user(user_id)
        except Exception as e:
            client.LOGGER(__name__, client.name).warning(f"Error adding a user:\n{e}")
    if is_banned:
        return await message.reply("**You have been banned from using this bot!**")

    text = message.text
    if len(text) > 7:
        try:
            original_payload = text.split(" ", 1)[1]
            if original_payload.strip().lower() == "premium":  # t.me/<bot>?start=premium
                screen, markup = await build_premium_screen(client, user_id, detailed=False)
                return await message.reply(screen, reply_markup=markup, parse_mode=ParseMode.HTML)
            base64_string = original_payload
            is_short_link = False
            if base64_string.startswith("yu3elk"):
                base64_string = base64_string[6:-1]
                is_short_link = True

        except IndexError:
            return await message.reply("Invalid command format.")

        # 3. Check premium status
        is_user_pro = await client.mongodb.is_pro(user_id)
        
        # 4. Check if shortner is enabled
        shortner_enabled = getattr(client, 'shortner_enabled', True)

        # 5. If user is not premium AND shortner is enabled, send short URL and return
        if not is_user_pro and user_id != OWNER_ID and not is_short_link and shortner_enabled:
            try:
                short_link = await get_short(f"https://t.me/{client.username}?start=yu3elk{base64_string}7", client)
            except Exception as e:
                client.LOGGER(__name__, client.name).warning(f"Shortener failed: {e}")
                return await message.reply("Couldn't generate short link.")

            short_photo = client.messages.get("SHORT_PIC", "")
            short_caption = client.messages.get("SHORT_MSG", "")
            tutorial_link = getattr(client, 'tutorial_link', "https://t.me/How_to_Download_7x/26")

            await client.send_photo(
                chat_id=message.chat.id,
                photo=short_photo,
                caption=short_caption,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("• ᴏᴘᴇɴ ʟɪɴᴋ", url=short_link),
                        InlineKeyboardButton("ᴛᴜᴛᴏʀɪᴀʟ •", url=tutorial_link)
                    ],
                    [
                        InlineKeyboardButton(" • ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ •", url=await get_buy_url(client))
                    ]
                ])
            )
            return  # prevent sending actual files

        # 5b. Ads gate: watch ad(s) in the Mini App before the file unlocks.
        # Skipped for admins/premium users, and fails open if ads are off or
        # unconfigured — misconfiguration should never brick file delivery.
        if not await user_is_exempt(client, user_id, is_user_pro):
            ad_steps = await get_required_ad_steps(client)
            if ad_steps:
                token = await create_unlock_session(client, user_id, base64_string, ad_steps)
                unlock_photo = client.messages.get("UNLOCK_PHOTO", "")
                if unlock_photo:
                    await message.reply_photo(
                        photo=unlock_photo,
                        caption=unlock_caption(ad_steps),
                        reply_markup=unlock_keyboard(token),
                    )
                else:
                    await message.reply(
                        unlock_caption(ad_steps),
                        reply_markup=unlock_keyboard(token),
                        disable_web_page_preview=True,
                    )
                return

        return await deliver_payload(client, user_id, base64_string, transfer_link=original_payload)

    # 9. Normal start message
    else:
        buttons = [[InlineKeyboardButton("Help", callback_data="about"), InlineKeyboardButton("Close", callback_data='close')]]
        if user_id in client.admins:
            buttons.insert(0, [InlineKeyboardButton("⛩️ ꜱᴇᴛᴛɪɴɢꜱ ⛩️", callback_data="settings")])

        photo = client.messages.get("START_PHOTO", "")
        start_caption = client.messages.get('START', 'Welcome, {mention}').format(
            first=message.from_user.first_name,
            last=message.from_user.last_name,
            username=None if not message.from_user.username else '@' + message.from_user.username,
            mention=message.from_user.mention,
            id=message.from_user.id
        )

        if photo:
            await client.send_photo(
                chat_id=message.chat.id,
                photo=photo,
                caption=start_caption,
                message_effect_id=MSG_EFFECT,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await client.send_message(
                chat_id=message.chat.id,
                text=start_caption,
                message_effect_id=MSG_EFFECT,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        return

#===============================================================#

@Client.on_message(filters.command('request') & filters.private)
async def request_command(client: Client, message: Message):
    user_id = message.from_user.id
    is_admin = user_id in client.admins  # ✅ Fix this line
    is_user_premium = await client.mongodb.is_pro(user_id)

    if is_admin or user_id == OWNER_ID:
        await message.reply_text("🔹 **You are my sensei!**\nThis command is only for users.")
        return

    if not is_user_premium: 
        BUTTON_URL = await get_buy_url(client)
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Upgrade to Premium", url=BUTTON_URL)]
        ])
        await message.reply(
            "❌ **You are not a premium user.**\nUpgrade to premium to access this feature.",
            reply_markup=reply_markup
        )
        return

    if len(message.command) < 2:
        await message.reply("⚠️ **Send me your request in this format:**\n`/request Your_Request_Here`")
        return

    requested = " ".join(message.command[1:])

    owner_message = (
        f"📩 **New Request from {message.from_user.mention}**\n\n"
        f"🆔 User ID: `{user_id}`\n"
        f"📝 Request: `{requested}`"
    )

    await client.send_message(OWNER_ID, owner_message)
    await message.reply("✅ **Thanks for your request!**\nYour request will be reviewed soon. Please wait.")

#===============================================================#
