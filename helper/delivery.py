"""Decodes a payload into DB-channel message ids and copies the file(s) to a
user. Pushed via `client.send_message`/`client.get_messages` rather than
`message.reply`, so it works identically whether it's triggered by an
incoming /start message or pushed proactively from the ad-unlock web API
(the Mini App has no Pyrogram `Message` to reply to — only a user id).
"""

import asyncio

from pyrogram.errors import FloodWait

from helper.helper_func import batch_auto_del_notification, decode, flood_seconds, get_messages


async def deliver_payload(client, user_id: int, base64_string: str, transfer_link: str) -> bool:
    """Returns True if at least one file was delivered."""
    try:
        string = await decode(base64_string)
        argument = string.split("-")
        ids = []
        source_channel_id = None

        if len(argument) == 3:
            encoded_start = int(argument[1])
            encoded_end = int(argument[2])

            primary_multiplier = abs(client.db)
            start_primary = int(encoded_start / primary_multiplier)
            end_primary = int(encoded_end / primary_multiplier)

            if encoded_start % primary_multiplier == 0 and encoded_end % primary_multiplier == 0:
                source_channel_id = client.db
                start, end = start_primary, end_primary
            else:
                db_channels = getattr(client, "db_channels", {})
                for channel_id_str in db_channels.keys():
                    channel_id = int(channel_id_str)
                    channel_multiplier = abs(channel_id)
                    start_test = int(encoded_start / channel_multiplier)
                    end_test = int(encoded_end / channel_multiplier)
                    if encoded_start % channel_multiplier == 0 and encoded_end % channel_multiplier == 0:
                        source_channel_id, start, end = channel_id, start_test, end_test
                        break
                if source_channel_id is None:
                    source_channel_id = client.db
                    start, end = start_primary, end_primary

            ids = range(start, end + 1) if start <= end else list(range(start, end - 1, -1))

        elif len(argument) == 2:
            encoded_msg = int(argument[1])

            if hasattr(client, "db_channel") and client.db_channel:
                primary_multiplier = abs(client.db_channel.id)
                msg_id_primary = int(encoded_msg / primary_multiplier)

                if encoded_msg % primary_multiplier == 0:
                    source_channel_id = client.db_channel.id
                    ids = [msg_id_primary]
                else:
                    db_channels = getattr(client, "db_channels", {})
                    for channel_id_str in db_channels.keys():
                        channel_id = int(channel_id_str)
                        channel_multiplier = abs(channel_id)
                        msg_id_test = int(encoded_msg / channel_multiplier)
                        if encoded_msg % channel_multiplier == 0:
                            source_channel_id, ids = channel_id, [msg_id_test]
                            break
                    if source_channel_id is None:
                        source_channel_id = client.db_channel.id if hasattr(client, "db_channel") else client.db
                        ids = [msg_id_primary]
            else:
                source_channel_id = client.db
                ids = [int(encoded_msg / abs(client.db))]

    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"Error decoding base64: {e}")
        await client.send_message(user_id, "⚠️ Invalid or expired link.")
        return False

    temp_msg = await client.send_message(user_id, "Wait A Sec..")
    messages = []

    try:
        if source_channel_id:
            try:
                msgs = await client.get_messages(chat_id=source_channel_id, message_ids=list(ids))
                valid_msgs = [msg for msg in msgs if msg is not None]
                messages.extend(valid_msgs)

                if len(valid_msgs) < len(list(ids)):
                    missing_ids = [mid for mid in ids if mid not in {msg.id for msg in valid_msgs}]
                    if missing_ids:
                        messages.extend(await get_messages(client, missing_ids))
            except Exception as e:
                client.LOGGER(__name__, client.name).warning(f"Error getting messages from source channel {source_channel_id}: {e}")
                messages = await get_messages(client, ids)
        else:
            messages = await get_messages(client, ids)
    except Exception as e:
        await temp_msg.edit_text("Something went wrong!")
        client.LOGGER(__name__, client.name).warning(f"Error getting messages: {e}")
        return False

    if not messages:
        await temp_msg.edit_text("Couldn't find the files in the database.")
        return False
    await temp_msg.delete()

    delivered_msgs = []
    for msg in messages:
        caption = (
            client.messages.get('CAPTION', '').format(
                previouscaption=msg.caption.html if msg.caption else msg.document.file_name
            ) if bool(client.messages.get('CAPTION', '')) and bool(msg.document)
            else ("" if not msg.caption else msg.caption.html)
        )
        reply_markup = msg.reply_markup if not client.disable_btn else None

        try:
            copied_msg = await msg.copy(chat_id=user_id, caption=caption, reply_markup=reply_markup, protect_content=client.protect)
            delivered_msgs.append(copied_msg)
        except FloodWait as e:
            await asyncio.sleep(flood_seconds(e))
            copied_msg = await msg.copy(chat_id=user_id, caption=caption, reply_markup=reply_markup, protect_content=client.protect)
            delivered_msgs.append(copied_msg)
        except Exception as e:
            client.LOGGER(__name__, client.name).warning(f"Failed to send message: {e}")

    if delivered_msgs and client.auto_del > 0:
        asyncio.create_task(batch_auto_del_notification(
            bot_username=client.username,
            messages=delivered_msgs,
            delay_time=client.auto_del,
            transfer_link=transfer_link,
            chat_id=user_id,
            client=client
        ))

    return bool(delivered_msgs)
