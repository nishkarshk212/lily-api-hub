import asyncio

from pyrogram import filters, types

from VampireMusic import app, db, lang


def _txt(m: types.Message, key: str, default: str) -> str:
    return m.lang.get(key, default)


async def _autodelete(message: types.Message, delay: int = 30) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


@app.on_message(filters.video_chat_started & filters.group & ~app.bl_users)
@lang.language()
async def _vc_started(_, m: types.Message):
    if not await db.get_vclogger(m.chat.id):
        return
    starter = m.from_user.mention if m.from_user else "someone"
    try:
        sent = await m.reply_text(
            _txt(
                m,
                "vc_started",
                "#VideoChat\n<b>● Action :</b> Started\n<b>● By :</b> {0}",
            ).format(starter)
        )
        asyncio.create_task(_autodelete(sent))
    except Exception:
        pass


@app.on_message(filters.video_chat_ended & filters.group & ~app.bl_users)
@lang.language()
async def _vc_ended(_, m: types.Message):
    if not await db.get_vclogger(m.chat.id):
        return
    ender = m.from_user.mention if m.from_user else "someone"
    duration = ""
    if m.video_chat_ended and m.video_chat_ended.duration:
        total = m.video_chat_ended.duration
        mins, secs = divmod(total, 60)
        duration = f"{mins}m {secs}s"
    try:
        sent = await m.reply_text(
            _txt(
                m,
                "vc_ended",
                "#VideoChat\n<b>● Action :</b> Ended\n<b>● By :</b> {0}\n<b>● Duration :</b> {1}",
            ).format(ender, duration or "N/A")
        )
        asyncio.create_task(_autodelete(sent))
    except Exception:
        pass


@app.on_message(filters.video_chat_members_invited & filters.group & ~app.bl_users)
@lang.language()
async def _vc_invited(_, m: types.Message):
    if not await db.get_vclogger(m.chat.id):
        return
    inviter = m.from_user.mention if m.from_user else "someone"
    invited = m.video_chat_members_invited.users if m.video_chat_members_invited else []
    if not invited:
        return
    names = ", ".join(u.mention for u in invited)
    try:
        sent = await m.reply_text(
            _txt(
                m,
                "vc_invited",
                "#VideoChat\n<b>● Action :</b> Invited\n<b>● By :</b> {0}\n<b>● Invited :</b> {1}",
            ).format(inviter, names)
        )
        asyncio.create_task(_autodelete(sent))
    except Exception:
        pass
