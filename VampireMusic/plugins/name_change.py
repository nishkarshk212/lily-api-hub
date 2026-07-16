import asyncio

from pyrogram import Client, filters, types, enums

from VampireMusic import app, db, logger


async def check_name_change(chat_id: int, user: types.User):
    user_id = user.id
    current_name = user.first_name
    if user.last_name:
        current_name += f" {user.last_name}"

    logger.info(f"[Name Change Tracker] Checking user {user_id}: current_name = {current_name}")
    old_name = await db.get_user_name(user_id)
    logger.info(f"[Name Change Tracker] Stored old_name for user {user_id}: {old_name}")

    if old_name and old_name != current_name:
        # Name changed! Send message!
        logger.info(f"[Name Change Tracker] Name changed! Old: {old_name} → New: {current_name}")
        msg_text = f"<blockquote>ᴜꜱᴇʀ ᴄʜᴀɴɢᴇ {current_name} ꜰʀᴏᴍ {old_name}</blockquote>"
        sent_msg = await app.send_message(
            chat_id=chat_id,
            text=msg_text,
            parse_mode=enums.ParseMode.HTML
        )
        # Auto delete after 5 seconds!
        await asyncio.sleep(5)
        try:
            await sent_msg.delete()
        except Exception as e:
            logger.warning(f"Failed to delete message: {e}")
    elif not old_name:
        logger.info(f"[Name Change Tracker] No stored name for user {user_id}, storing {current_name}")

    # Update the stored name
    await db.set_user_name(user_id, current_name)


@app.on_message(~filters.private, group=20)
async def track_user_name_on_message(client: Client, message: types.Message):
    if not message.from_user:
        return
    await check_name_change(message.chat.id, message.from_user)


@app.on_chat_member_updated()
async def track_user_name_on_member_update(client: Client, update: types.ChatMemberUpdated):
    if not update.new_chat_member or not update.new_chat_member.user:
        return
    await check_name_change(update.chat.id, update.new_chat_member.user)

