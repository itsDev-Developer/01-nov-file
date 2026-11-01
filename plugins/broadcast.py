from pyrogram import Client, filters
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
import asyncio
from collections import Counter
from helper.helper_func import flood_seconds

#===============================================================#

@Client.on_message(filters.command('users'))
async def user_count(client, message):
    if not message.from_user.id in client.admins:
        return await client.send_message(message.from_user.id, client.reply_text)
    total_users = await client.mongodb.count_users()  # a server-side count instead of loading every id
    await message.reply(f"**{total_users} Users are using this bot currently!**")

#===============================================================#

CONCURRENCY = 10  # messages in flight at once; Telegram allows ~30/second to different chats, so this stays well under


async def _send_one(client, broadcast_msg, chat_id, pin):
    """Deliver to one user. Returns "ok", "blocked", "deleted" or "failed" — never raises.
    (Before, a failure while retrying after a flood-wait escaped the loop and aborted the whole
    broadcast, and a pin error was counted as a failed delivery of an already-delivered message.)"""
    for attempt in (1, 2):
        try:
            sent = await broadcast_msg.copy(chat_id)
            if pin:
                try:
                    await client.pin_chat_message(chat_id=chat_id, message_id=sent.id, both_sides=True)
                except Exception:
                    pass  # delivered is delivered; a missing pin is not a failure
            return "ok"
        except FloodWait as e:
            if attempt == 2:
                return "failed"
            await asyncio.sleep(flood_seconds(e))
        except UserIsBlocked:
            await client.mongodb.del_user(chat_id)
            return "blocked"
        except InputUserDeactivated:
            await client.mongodb.del_user(chat_id)
            return "deleted"
        except Exception as e:
            print(f"Failed to send message to {chat_id}: {e}")
            return "failed"
    return "failed"


async def run_broadcast(client, message, pin=False):
    if not message.reply_to_message:
        msg = await message.reply("Use This Command As A Reply To Any Telegram Message Without Any Spaces.")
        await asyncio.sleep(8)
        return await msg.delete()

    user_ids = await client.mongodb.full_userbase()
    broadcast_msg = message.reply_to_message
    pls_wait = await message.reply("<blockquote><i>Broadcasting Message.. This will Take Some Time</i></blockquote>")

    counts = Counter()
    pending = iter(user_ids)  # shared: each id goes to exactly one worker

    async def worker():
        for chat_id in pending:
            counts[await _send_one(client, broadcast_msg, chat_id, pin)] += 1

    await asyncio.gather(*(worker() for _ in range(CONCURRENCY)))

    status = f"""<blockquote><b><u>Broadcast Completed</u></b></blockquote>
<blockquote expandable><b>Total Users :</b> <code>{len(user_ids)}</code>
<b>Successful :</b> <code>{counts['ok']}</code>
<b>Blocked Users :</b> <code>{counts['blocked']}</code>
<b>Deleted Accounts :</b> <code>{counts['deleted']}</code>
<b>Unsuccessful :</b> <code>{counts['failed']}</code></blockquote>"""
    return await pls_wait.edit(status)


@Client.on_message(filters.private & filters.command('broadcast'))
async def send_text(client, message):
    if message.from_user.id in client.admins:
        await run_broadcast(client, message)


@Client.on_message(filters.private & filters.command('pbroadcast'))
async def pin_bdcst_text(client, message):
    if message.from_user.id in client.admins:
        await run_broadcast(client, message, pin=True)
