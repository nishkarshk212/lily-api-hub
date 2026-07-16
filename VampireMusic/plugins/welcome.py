from pyrogram import enums, filters, types

from VampireMusic import app, db, lang
from VampireMusic.helpers import admin_check, parse_buttons, render_text


@app.on_message(
    filters.command(["setwelcome", "welcome"]) & filters.group & ~app.bl_users
)
@lang.language()
@admin_check
async def _set_welcome(_, m: types.Message):
    """Set the welcome text (with placeholders + inline buttons)."""
    chat_id = m.chat.id
    # Prefer replied-to message text so long/HTML content is preserved.
    if m.reply_to_message and (m.reply_to_message.text or m.reply_to_message.caption):
        text = (m.reply_to_message.text or m.reply_to_message.caption).html
    elif len(m.command) >= 2:
        text = m.text.html.split(None, 1)[1]
    else:
        return await m.reply_text(m.lang["welcome_instr"])

    await db.set_welcome(chat_id, text=text, enabled=True)
    await m.reply_text(m.lang["welcome_set"])


@app.on_message(
    filters.command(["setwelcomemedia", "welcomemedia"])
    & filters.group
    & ~app.bl_users
)
@lang.language()
@admin_check
async def _set_welcome_media(_, m: types.Message):
    """Set/clear a photo or video shown with the welcome message."""
    chat_id = m.chat.id
    reply = m.reply_to_message
    file_id = None
    if reply:
        if reply.photo:
            file_id = reply.photo.file_id
        elif reply.video:
            file_id = reply.video.file_id
        elif reply.animation:
            file_id = reply.animation.file_id

    if file_id:
        await db.set_welcome(chat_id, media=file_id)
        return await m.reply_text(m.lang["welcome_media_set"])

    if len(m.command) >= 2 and m.command[1].lower() in ("off", "clear", "remove"):
        await db.set_welcome(chat_id, media=None)
        return await m.reply_text(m.lang["welcome_media_clear"])

    await m.reply_text(m.lang["welcome_media_usage"])


@app.on_message(
    filters.command(["setwelcomebutton", "welcomebutton", "welcomebuttons"])
    & filters.group
    & ~app.bl_users
)
@lang.language()
@admin_check
async def _set_welcome_button(_, m: types.Message):
    """Set/clear inline buttons attached to the welcome message."""
    chat_id = m.chat.id
    if len(m.command) >= 2 and m.command[1].lower() in ("off", "clear", "remove"):
        await db.set_welcome(chat_id, buttons=None)
        return await m.reply_text(m.lang["welcome_button_clear"])

    if m.reply_to_message and m.reply_to_message.text:
        spec = m.reply_to_message.text
    elif len(m.command) >= 2:
        spec = m.text.split(None, 1)[1]
    else:
        return await m.reply_text(m.lang["welcome_button_usage"])

    if parse_buttons(spec) is None:
        return await m.reply_text(m.lang["welcome_button_invalid"])

    await db.set_welcome(chat_id, buttons=spec)
    await m.reply_text(m.lang["welcome_button_set"])


@app.on_message(
    filters.command(["welcometoggle", "resetwelcome"]) & filters.group & ~app.bl_users
)
@lang.language()
@admin_check
async def _toggle_welcome(_, m: types.Message):
    chat_id = m.chat.id
    if m.command[0].lower() == "resetwelcome":
        await db.set_welcome(chat_id, enabled=False, text=None, media=None, buttons=None)
        return await m.reply_text(m.lang["welcome_reset"])

    if len(m.command) < 2 or m.command[1].lower() not in (
        "on", "off", "enable", "disable",
    ):
        return await m.reply_text(m.lang["welcome_toggle_usage"])

    enabled = m.command[1].lower() in ("on", "enable")
    await db.set_welcome(chat_id, enabled=enabled)
    await m.reply_text(
        m.lang["welcome_on"] if enabled else m.lang["welcome_off"]
    )


@app.on_message(filters.new_chat_members, group=8)
async def _greet_member(_, message: types.Message):
    """Send the configured welcome message to newly joined members."""
    if message.chat.type != enums.ChatType.SUPERGROUP:
        return

    cfg = await db.get_welcome(message.chat.id)
    if not cfg["enabled"] or not (cfg["text"] or cfg["media"]):
        return

    for member in message.new_chat_members:
        if member.is_bot:
            continue
        text = render_text(cfg["text"] or "", member, message.chat)
        markup = parse_buttons(cfg["buttons"]) if cfg["buttons"] else None
        try:
            if cfg["media"]:
                await message.reply_cached_media(
                    file_id=cfg["media"],
                    caption=text or None,
                    reply_markup=markup,
                    quote=False,
                )
            else:
                await message.reply_text(
                    text, reply_markup=markup, quote=False,
                    disable_web_page_preview=True,
                )
        except Exception:
            pass
