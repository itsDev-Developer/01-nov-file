#SahilxCodes

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from helper.premium_ui import get_buy_url
from datetime import datetime
from datetime import timedelta
import html
import re
from config import OWNER_ID
#--------------------------------

def parse_duration(duration_str: str) -> timedelta:
    """
    Parse duration strings like '1 day', '2 weeks', '3 months', '1 year' into timedelta
    Returns None if the format is invalid
    """
    duration_str = duration_str.lower().strip()
    match = re.match(r'^(\d+)\s*(day|days|week|weeks|month|months|year|years)$', duration_str)
    
    if not match:
        return None
        
    amount = int(match.group(1))
    unit = match.group(2).rstrip('s')  # Remove 's' from plural forms
    
    if unit == 'day':
        return timedelta(days=amount)
    elif unit == 'week':
        return timedelta(weeks=amount)
    elif unit == 'month':
        return timedelta(days=amount * 30)  # Approximate
    elif unit == 'year':
        return timedelta(days=amount * 365)  # Approximate
    
    return None

#========================================================================#

@Client.on_message(filters.command('addpremium') & filters.private)
async def add_admin_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return await message.reply_text("Only Owner can use this command...!")

    usage = """<b>Usage:</b> 
/addpremium <userid> [duration]

<b>Examples:</b>
• /addpremium 123456 1 day
• /addpremium 123456 2 weeks
• /addpremium 123456 1 month
• /addpremium 123456 1 year
• /addpremium 123456 (for permanent premium)"""

    parts = message.command[1:]
    if not parts:
        return await message.reply_text(usage)

    try:
        user_id_to_add = int(parts[0])
    except ValueError:
        return await message.reply_text("Invalid user ID. Please check again...!")

    try:
        user = await client.get_users(user_id_to_add)
        user_name = user.first_name + (" " + user.last_name if user.last_name else "")
    except Exception as e:
        return await message.reply_text(f"Error fetching user information: {e}")

    # Parse duration if provided
    duration_str = " ".join(parts[1:]) if len(parts) > 1 else None
    expiry_date = None
    duration_text = "permanently"

    if duration_str:
        duration = parse_duration(duration_str)
        if not duration:
            return await message.reply_text(f"Invalid duration format. {usage}")
        expiry_date = datetime.now() + duration
        duration_text = f"until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}"

    if not await client.mongodb.is_pro(user_id_to_add):
        await client.mongodb.add_pro(user_id_to_add, expiry_date)
        await message.reply_text(f"<b>User {user_name} - {user_id_to_add} is now a pro user {duration_text}!</b>")
        try:
            notify_msg = "<b>🎉 Congratulations! Your premium membership has been activated"
            notify_msg += f" until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}</b>" if expiry_date else " permanently</b>"
            await client.send_message(user_id_to_add, notify_msg)
        except Exception as e:
            await message.reply_text(f"Failed to notify the user: {e}")
    else:
        current_expiry = await client.mongodb.get_expiry_date(user_id_to_add)
        if current_expiry:
            await message.reply_text(
                f"<b>User {user_name} - {user_id_to_add} is already a pro user "
                f"until {current_expiry.strftime('%Y-%m-%d %H:%M:%S')}.</b>"
            )
        else:
            await message.reply_text(f"<b>User {user_name} - {user_id_to_add} is already a permanent pro user.</b>")

#========================================================================#

@Client.on_message(filters.command('delpremium') & filters.private)
async def remove_admin_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return await message.reply_text("Only Owner can use this command...!")

    if len(message.command) != 2:
        return await message.reply_text("<b>You're using wrong format do like this:</b> /delpremium <userid>")

    try:
        user_id_to_remove = int(message.command[1])
    except ValueError:
        return await message.reply_text("Invalid user ID. Please check again...!")

    try:
        user = await client.get_users(user_id_to_remove)
        user_name = user.first_name + (" " + user.last_name if user.last_name else "")
    except Exception as e:
        return await message.reply_text(f"Error fetching user information: {e}")

    if await client.mongodb.is_pro(user_id_to_remove):
        await client.mongodb.remove_pro(user_id_to_remove)
        await message.reply_text(f"<b>User {user_name} - {user_id_to_remove} has been removed from pro users...!</b>")
        try:
            buy_url = await get_buy_url(client)  # follows /setpremiumurl, not a hard-coded contact
            await client.send_message(
                user_id_to_remove,
                "<b>Your membership has ended.</b>\n\nTo renew it, tap below.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Premium", url=buy_url)]]),
            )
        except Exception as e:
            await message.reply_text(f"Failed to notify the user: {e}")
    else:
        await message.reply_text(f"<b>User {user_name} - {user_id_to_remove} is not a pro user or was not found in the pro list.</b>")

#========================================================================#


LIST_LIMIT = 1000          # a chat list this long is already unwieldy; the API pages through everyone
MESSAGE_BUDGET = 3800      # Telegram rejects messages over 4096 characters


async def _display_names(client: Client, ids: list) -> dict:
    """{user_id: (name, username)} using one Telegram call per 200 users (was one call per user,
    one after another). If a batch is rejected because it contains an account the bot has never
    seen, fall back to asking one by one so a single bad id can't hide everyone else."""
    names = {}
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        try:
            users = await client.get_users(batch)
            users = users if isinstance(users, list) else [users]
        except Exception:
            users = []
            for uid in batch:
                try:
                    users.append(await client.get_users(uid))
                except Exception:
                    pass
        for u in users:
            names[u.id] = (" ".join(x for x in (u.first_name, u.last_name) if x) or "Unknown",
                           f"@{u.username}" if u.username else "No Username")
    return names


@Client.on_message(filters.command('premiumusers') & filters.private)
async def admin_list_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return await message.reply_text("Only Owner can use this command...!")

    total = await client.mongodb.count_pros()
    docs = await client.mongodb.get_pros_page(LIST_LIMIT, 0)  # one query: ids and expiry together
    if not docs:
        return await message.reply_text("<b>No premium users found.</b>")

    names = await _display_names(client, [d["_id"] for d in docs])
    lines = []
    for d in docs:
        name, username = names.get(d["_id"], ("Unknown", "No Username"))
        expiry = d.get("expiry_date")
        status = f"(Expires: {expiry.strftime('%Y-%m-%d %H:%M:%S')})" if expiry else "(Permanent)"
        lines.append(f"{html.escape(name)} - {html.escape(username)} <code>{d['_id']}</code> {status}")

    # Pack lines into as few messages as fit under Telegram's size limit.
    header = f"<b>📊 Premium Users List ({total}):</b>\n\n"
    chunks, current = [], header
    for line in lines:
        if len(current) + len(line) + 1 > MESSAGE_BUDGET:
            chunks.append(current)
            current = ""
        current += line + "\n"
    chunks.append(current)
    if total > len(docs):
        chunks[-1] += f"\n<i>Showing the first {len(docs)} of {total}. Use GET /api/v1/premium to page through everyone.</i>"
    for chunk in chunks:
        await message.reply_text(chunk, disable_web_page_preview=True, parse_mode=ParseMode.HTML)
