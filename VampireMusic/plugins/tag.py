import asyncio

from pyrogram import enums, filters, types

from VampireMusic import app
from VampireMusic.helpers import admin_check

# Dictionary to track running tag operations
running_tags = {}


async def get_chat_members(chat_id: int, only_admins: bool = False):
    members = []
    filter_type = (
        enums.ChatMembersFilter.ADMINISTRATORS
        if only_admins
        else enums.ChatMembersFilter.SEARCH
    )
    async for member in app.get_chat_members(chat_id, filter=filter_type):
        if member.user and not member.user.is_bot:
            members.append(member.user)
    return members


async def tag_all_single(chat_id: int, members: list[types.User], custom_text: str = None):
    count = 0
    for member in members:
        if chat_id not in running_tags:
            break
        try:
            text = member.mention
            if custom_text:
                text = f"{custom_text}\n\n{member.mention}"
            await app.send_message(
                chat_id, 
                text,
                parse_mode=enums.ParseMode.HTML
            )
            count += 1
            await asyncio.sleep(1)
        except Exception:
            continue
    # Update count before clearing
    if chat_id in running_tags:
        running_tags[chat_id]["count"] = count
    return count


async def tag_all_block(chat_id: int, members: list[types.User], per_message: int = 3, custom_text: str = None):
    count = 0
    for i in range(0, len(members), per_message):
        if chat_id not in running_tags:
            break
        chunk = members[i:i + per_message]
        mentions = [m.mention for m in chunk]
        text = "\n".join(mentions)
        if custom_text:
            text = f"{custom_text}\n\n{text}"
        try:
            await app.send_message(
                chat_id, 
                text,
                parse_mode=enums.ParseMode.HTML
            )
            count += len(chunk)
            await asyncio.sleep(1)
        except Exception:
            continue
    if chat_id in running_tags:
        running_tags[chat_id]["count"] = count
    return count


@app.on_message(filters.command("tagall") & filters.group)
@admin_check
async def cmd_tagall(_, message: types.Message):
    chat_id = message.chat.id
    if chat_id in running_tags:
        return await message.reply_text("❌ Already running a tag operation! Use /stag to stop first.")

    # Get custom text from command
    custom_text = None
    if len(message.command) > 1:
        text = " ".join(message.command[1:])
        # Wrap in Telegram block quote using <blockquote> HTML tag
        custom_text = f"<blockquote>{text}</blockquote>"

    await message.reply_text("🔄 Starting to tag all members...")
    members = await get_chat_members(chat_id)
    if not members:
        return await message.reply_text("❌ No members to tag.")

    # Create task
    async def run_task():
        try:
            await tag_all_block(chat_id, members, custom_text=custom_text)
        finally:
            if chat_id in running_tags:
                del running_tags[chat_id]

    task = asyncio.create_task(run_task())
    running_tags[chat_id] = {"task": task, "count": 0}


@app.on_message(filters.command("tag") & filters.group)
@admin_check
async def cmd_tag(_, message: types.Message):
    chat_id = message.chat.id
    if chat_id in running_tags:
        return await message.reply_text("❌ Already running a tag operation! Use /stag to stop first.")

    # Get custom text from command
    custom_text = None
    if len(message.command) > 1:
        text = " ".join(message.command[1:])
        # Wrap in Telegram block quote using <blockquote> HTML tag
        custom_text = f"<blockquote>{text}</blockquote>"

    await message.reply_text("🔄 Starting to tag all members one by one...")
    members = await get_chat_members(chat_id)
    if not members:
        return await message.reply_text("❌ No members to tag.")

    async def run_task():
        try:
            await tag_all_single(chat_id, members, custom_text=custom_text)
        finally:
            if chat_id in running_tags:
                del running_tags[chat_id]

    task = asyncio.create_task(run_task())
    running_tags[chat_id] = {"task": task, "count": 0}


@app.on_message(filters.command("atag") & filters.group)
@admin_check
async def cmd_atag(_, message: types.Message):
    chat_id = message.chat.id
    if chat_id in running_tags:
        return await message.reply_text("❌ Already running a tag operation! Use /stag to stop first.")

    # Get custom text from command
    custom_text = None
    if len(message.command) > 1:
        text = " ".join(message.command[1:])
        # Wrap in Telegram block quote using <blockquote> HTML tag
        custom_text = f"<blockquote>{text}</blockquote>"

    await message.reply_text("🔄 Starting to tag admins...")
    members = await get_chat_members(chat_id, only_admins=True)
    if not members:
        return await message.reply_text("❌ No admins to tag.")

    async def run_task():
        try:
            await tag_all_single(chat_id, members, custom_text=custom_text)
        finally:
            if chat_id in running_tags:
                del running_tags[chat_id]

    task = asyncio.create_task(run_task())
    running_tags[chat_id] = {"task": task, "count": 0}


@app.on_message(filters.command("stag") & filters.group)
@admin_check
async def cmd_stag(_, message: types.Message):
    chat_id = message.chat.id
    if chat_id not in running_tags:
        return await message.reply_text("❌ No tag operation is running.")

    tag_data = running_tags[chat_id]
    tag_data["task"].cancel()
    count = tag_data["count"]
    del running_tags[chat_id]

    await message.reply_text(
        f"✅ Stopped tagging!\n\n"
        f"📊 Total members tagged: {count}"
    )
