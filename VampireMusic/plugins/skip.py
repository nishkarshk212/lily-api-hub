from pyrogram import filters, types

from VampireMusic import app, VampireMusic, db, lang
from VampireMusic.helpers import can_manage_vc


@app.on_message(filters.command(["skip", "next"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _skip(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])

    await VampireMusic.play_next(m.chat.id, skip_user=m.from_user.mention)
