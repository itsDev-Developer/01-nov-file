import asyncio
import requests
import random
import time
import string
from config import SHORT_URL, SHORT_API, MESSAGES
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from pyrogram.errors.pyromod import ListenerTimeout

# ✅ In-memory cache
shortened_urls_cache = {}

def generate_random_alphanumeric():
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(8))

SHORT_TIMEOUT = 8          # seconds: a slow shortener must never be able to stall someone's /start
MAX_CACHED_LINKS = 5000    # bounded, so a long-running bot can't grow this forever
COOLDOWN_AFTER_FAILURE = 30  # seconds to skip the shortener after it failed (provider outage)
_inflight = {}
_failed_until = 0.0


async def get_short(url, client):
    """Short link for `url` (the original url if the shortener is off or failing).

    The HTTP call used to be a blocking `requests.get` with no timeout running
    on the event loop, so one slow response froze every user, the watch page
    and the API at the same time. It now runs in a worker thread with a
    timeout, concurrent requests for the same link share one call (a popular
    new file can be opened by hundreds of people at once), and after a failure
    the shortener is skipped for a short cooldown instead of making each
    following user wait out the timeout again."""
    global _failed_until
    if not getattr(client, 'shortner_enabled', True):
        return url
    cached = shortened_urls_cache.get(url)
    if cached:
        return cached
    if time.monotonic() < _failed_until:
        return url

    task = _inflight.get(url)
    if task is None:
        task = _inflight[url] = asyncio.ensure_future(_fetch_short(url, client))
        task.add_done_callback(lambda _t: _inflight.pop(url, None))
    return await asyncio.shield(task)  # one caller going away must not cancel the shared request


async def _fetch_short(url, client):
    global _failed_until
    short_url = getattr(client, 'short_url', SHORT_URL)
    short_api = getattr(client, 'short_api', SHORT_API)
    api_url = f"https://{short_url}/api?api={short_api}&url={url}&alias={generate_random_alphanumeric()}"
    try:
        response = await asyncio.to_thread(requests.get, api_url, timeout=SHORT_TIMEOUT)
        rjson = response.json()
        if rjson.get("status") == "success" and response.status_code == 200:
            result = rjson.get("shortenedUrl", url)
            if len(shortened_urls_cache) >= MAX_CACHED_LINKS:
                shortened_urls_cache.clear()
            shortened_urls_cache[url] = result
            return result
    except Exception as e:
        print(f"[Shortener Error] {e}")
    _failed_until = time.monotonic() + COOLDOWN_AFTER_FAILURE
    return url  # fallback: the direct bot link


#===============================================================#

@Client.on_message(filters.command('shortner') & filters.private)
async def shortner_command(client: Client, message: Message):
    await shortner_panel(client, message)

#===============================================================#

async def shortner_panel(client, query_or_message):
    # Get current shortner settings
    short_url = getattr(client, 'short_url', SHORT_URL)
    short_api = getattr(client, 'short_api', SHORT_API)
    tutorial_link = getattr(client, 'tutorial_link', "https://t.me/How_to_Download_7x/26")
    shortner_enabled = getattr(client, 'shortner_enabled', True)
    
    # Check if shortner is working (only if enabled)
    if shortner_enabled:
        try:
            test_response = await asyncio.to_thread(requests.get, f"https://{short_url}/api?api={short_api}&url=https://google.com&alias=test", timeout=5)
            status = "✓ ᴡᴏʀᴋɪɴɢ" if test_response.status_code == 200 else "✗ ɴᴏᴛ ᴡᴏʀᴋɪɴɢ"
        except Exception:
            status = "✗ ɴᴏᴛ ᴡᴏʀᴋɪɴɢ"
    else:
        status = "✗ ᴅɪsᴀʙʟᴇᴅ"
    
    enabled_text = "✓ ᴇɴᴀʙʟᴇᴅ" if shortner_enabled else "✗ ᴅɪsᴀʙʟᴇᴅ"
    toggle_text = "✗ ᴏғғ" if shortner_enabled else "✓ ᴏɴ"
    
    msg = f"""<blockquote>✦ 𝗦𝗛𝗢𝗥𝗧𝗡𝗘𝗥 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦</blockquote>
**<u>ᴄᴜʀʀᴇɴᴛ ꜱᴇᴛᴛɪɴɢꜱ:</u>**
<blockquote>›› **ꜱʜᴏʀᴛɴᴇʀ ꜱᴛᴀᴛᴜꜱ:** {enabled_text}
›› **ꜱʜᴏʀᴛɴᴇʀ ᴜʀʟ:** `{short_url}`
›› **ꜱʜᴏʀᴛɴᴇʀ ᴀᴘɪ:** `{short_api}`</blockquote> 
<blockquote>›› **ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ:** `{tutorial_link}`
›› **ᴀᴘɪ ꜱᴛᴀᴛᴜꜱ:** {status}</blockquote>

<blockquote>**≡ ᴜꜱᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴꜱ ʙᴇʟᴏᴡ ᴛᴏ ᴄᴏɴꜰɪɢᴜʀᴇ ʏᴏᴜʀ ꜱʜᴏʀᴛɴᴇʀ ꜱᴇᴛᴛɪɴɢꜱ!**</blockquote>"""
    
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f'• {toggle_text} ꜱʜᴏʀᴛɴᴇʀ •', 'toggle_shortner'), InlineKeyboardButton('• ᴀᴅᴅ ꜱʜᴏʀᴛɴᴇʀ •', 'add_shortner')],
        [InlineKeyboardButton('• ꜱᴇᴛ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ •', 'set_tutorial_link')],
        [InlineKeyboardButton('• ᴛᴇꜱᴛ ꜱʜᴏʀᴛɴᴇʀ •', 'test_shortner')],
        [InlineKeyboardButton('◂ ʙᴀᴄᴋ ᴛᴏ ꜱᴇᴛᴛɪɴɢꜱ', 'settings')] if hasattr(query_or_message, 'message') else []
    ])
    
    image_url = MESSAGES.get("SHORT", "https://telegra.ph/file/8aaf4df8c138c6685dcee-05d3b183d4978ec347.jpg")
    
    if hasattr(query_or_message, 'message'):
        await query_or_message.message.edit_media(
            media=InputMediaPhoto(media=image_url, caption=msg),
            reply_markup=reply_markup
        )
    else:
        await query_or_message.reply_photo(photo=image_url, caption=msg, reply_markup=reply_markup)


#===============================================================#

@Client.on_callback_query(filters.regex("^shortner$"))
async def shortner_callback(client, query):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    await query.answer()
    await shortner_panel(client, query)

#===============================================================#

@Client.on_callback_query(filters.regex("^toggle_shortner$"))
async def toggle_shortner(client: Client, query: CallbackQuery):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    # Toggle the shortner status
    current_status = getattr(client, 'shortner_enabled', True)
    new_status = not current_status
    client.shortner_enabled = new_status
    
    # Save to database
    await client.mongodb.set_shortner_status(new_status)
    
    status_text = "ᴇɴᴀʙʟᴇᴅ" if new_status else "ᴅɪsᴀʙʟᴇᴅ"
    await query.answer(f"✓ ꜱʜᴏʀᴛɴᴇʀ {status_text}!")
    
    # Refresh the panel
    await shortner_panel(client, query)

#===============================================================#

@Client.on_callback_query(filters.regex("^add_shortner$"))
async def add_shortner(client: Client, query: CallbackQuery):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    
    await query.answer()
        
    current_url = getattr(client, 'short_url', SHORT_URL)
    current_api = getattr(client, 'short_api', SHORT_API)
    
    msg = f"""<blockquote>**ꜱᴇᴛ ꜱʜᴏʀᴛɴᴇʀ ꜱᴇᴛᴛɪɴɢꜱ:**</blockquote>
**ᴄᴜʀʀᴇɴᴛ ꜱᴇᴛᴛɪɴɢꜱ:**
• **ᴜʀʟ:** `{current_url}`
• **ᴀᴘɪ:** `{current_api[:20]}...`

__<blockquote>**≡ ꜱᴇɴᴅ ɴᴇᴡ ꜱʜᴏʀᴛɴᴇʀ ᴜʀʟ ᴀɴᴅ ᴀᴘɪ ɪɴ ᴛʜɪꜱ ꜰᴏʀᴍᴀᴛ ɪɴ ᴛʜᴇ ɴᴇxᴛ 60 ꜱᴇᴄᴏɴᴅꜱ!**</blockquote>__

**ꜰᴏʀᴍᴀᴛ:** `ᴜʀʟ ᴀᴘɪ`
**ᴇxᴀᴍᴘʟᴇ:** `inshorturl.com 9435894656863495834957348`"""
    
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        response_text = res.text.strip()
        
        # Parse the response: url api
        parts = response_text.split()
        if len(parts) >= 2:
            new_url = parts[0].replace('https://', '').replace('http://', '').replace('/', '')
            new_api = ' '.join(parts[1:])  # Join remaining parts as API key
            
            if new_url and '.' in new_url and new_api and len(new_api) > 10:
                # Update both settings
                client.short_url = new_url
                client.short_api = new_api
                shortened_urls_cache.clear()  # links made by the previous provider are no longer valid
                
                # Save to database
                await client.mongodb.update_shortner_setting('short_url', new_url)
                await client.mongodb.update_shortner_setting('short_api', new_api)
                
                await query.message.edit_text(f"**✓ ꜱʜᴏʀᴛɴᴇʀ ꜱᴇᴛᴛɪɴɢꜱ ᴜᴘᴅᴀᴛᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ!**\n\n**ɴᴇᴡ ᴜʀʟ:** `{new_url}`\n**ɴᴇᴡ ᴀᴘɪ:** `{new_api[:20]}...`", 
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))
            else:
                await query.message.edit_text("**✗ ɪɴᴠᴀʟɪᴅ ꜰᴏʀᴍᴀᴛ! ᴘʟᴇᴀꜱᴇ ᴄʜᴇᴄᴋ ᴜʀʟ ᴀɴᴅ ᴀᴘɪ ᴋᴇʏ.**", 
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))
        else:
            await query.message.edit_text("**✗ ɪɴᴠᴀʟɪᴅ ꜰᴏʀᴍᴀᴛ! ᴘʟᴇᴀꜱᴇ ᴜꜱᴇ: `ᴜʀʟ ᴀᴘɪ`**", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))
    except ListenerTimeout:
        await query.message.edit_text("**⏰ ᴛɪᴍᴇᴏᴜᴛ! ᴛʀʏ ᴀɢᴀɪɴ.**", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^set_tutorial_link$"))
async def set_tutorial_link(client: Client, query: CallbackQuery):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    
    await query.answer()
        
    current_tutorial = getattr(client, 'tutorial_link', "https://t.me/How_to_Download_7x/26")
    msg = f"""<blockquote>**ꜱᴇᴛ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ:**</blockquote>
**ᴄᴜʀʀᴇɴᴛ ᴛᴜᴛᴏʀɪᴀʟ:** `{current_tutorial}`

__ꜱᴇɴᴅ ᴛʜᴇ ɴᴇᴡ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ ɪɴ ᴛʜᴇ ɴᴇxᴛ 60 ꜱᴇᴄᴏɴᴅꜱ!__
**ᴇxᴀᴍᴘʟᴇ:** `https://t.me/How_to_Download_7x/26`"""
    
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        new_tutorial = res.text.strip()
        
        if new_tutorial and (new_tutorial.startswith('https://') or new_tutorial.startswith('http://')):
            client.tutorial_link = new_tutorial
            # Save to database
            await client.mongodb.update_shortner_setting('tutorial_link', new_tutorial)
            await query.message.edit_text(f"**✓ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ ᴜᴘᴅᴀᴛᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ!**", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))
        else:
            await query.message.edit_text("**✗ ɪɴᴠᴀʟɪᴅ ʟɪɴᴋ ꜰᴏʀᴍᴀᴛ! ᴍᴜꜱᴛ ꜱᴛᴀʀᴛ ᴡɪᴛʜ https:// ᴏʀ http://**", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))
    except ListenerTimeout:
        await query.message.edit_text("**⏰ ᴛɪᴍᴇᴏᴜᴛ! ᴛʀʏ ᴀɢᴀɪɴ.**", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^test_shortner$"))
async def test_shortner(client: Client, query: CallbackQuery):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    
    await query.answer()
        
    await query.message.edit_text("**🔄 ᴛᴇꜱᴛɪɴɢ ꜱʜᴏʀᴛɴᴇʀ...**")
    
    short_url = getattr(client, 'short_url', SHORT_URL)
    short_api = getattr(client, 'short_api', SHORT_API)
    
    try:
        test_url = "https://google.com"
        alias = generate_random_alphanumeric()
        api_url = f"https://{short_url}/api?api={short_api}&url={test_url}&alias={alias}"
        
        response = await asyncio.to_thread(requests.get, api_url, timeout=10)
        rjson = response.json()
        
        if rjson.get("status") == "success" and response.status_code == 200:
            short_link = rjson.get("shortenedUrl", "")
            msg = f"""**✅ ꜱʜᴏʀᴛɴᴇʀ ᴛᴇꜱᴛ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟ!**

**ᴛᴇꜱᴛ ᴜʀʟ:** `{test_url}`
**ꜱʜᴏʀᴛ ᴜʀʟ:** `{short_link}`
**ʀᴇꜱᴘᴏɴꜱᴇ:** `{rjson.get('status', 'Unknown')}`"""
        else:
            msg = f"""**❌ ꜱʜᴏʀᴛɴᴇʀ ᴛᴇꜱᴛ ꜰᴀɪʟᴇᴅ!**

**ᴇʀʀᴏʀ:** `{rjson.get('message', 'Unknown error')}`
**ꜱᴛᴀᴛᴜꜱ ᴄᴏᴅᴇ:** `{response.status_code}`"""
            
    except Exception as e:
        msg = f"**❌ ꜱʜᴏʀᴛɴᴇʀ ᴛᴇꜱᴛ ꜰᴀɪʟᴇᴅ!**\n\n**ᴇʀʀᴏʀ:** `{str(e)}`"
    
    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))


