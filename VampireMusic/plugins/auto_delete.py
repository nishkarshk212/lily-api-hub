import asyncio

from pyrogram import filters, types

from VampireMusic import app


async def delete_after_delay(message: types.Message, delay: float = 0.5):
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception:
        pass


@app.on_message(filters.group & filters.text)
async def auto_delete_command(_, message: types.Message):
    try:
        if message.text and message.text.startswith("/"):
            # Delete the command message after a small delay to let command handlers process it
            asyncio.create_task(delete_after_delay(message))
    except Exception:
        pass
