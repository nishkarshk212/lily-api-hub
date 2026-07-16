import asyncio
import os
import shutil
import sys

from pyrogram import filters, types

from VampireMusic import app, db, lang, stop


@app.on_message(filters.command(["logs"]) & app.sudoers)
@lang.language()
async def _logs(_, m: types.Message):
    if not os.path.exists("log.txt"):
        return await m.reply_text(m.lang["log_not_found"])

    size = os.path.getsize("log.txt")
    size_h = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1048576:.1f} MB"

    try:
        with open("log.txt", "rb") as fh:
            fh.seek(max(0, size - 50 * 1024))
            raw = fh.read().decode("utf-8", "ignore")
        tail = "\n".join(raw.splitlines()[-40:])
    except Exception:
        tail = ""

    header = (
        f"📄 <b>Log file of {app.name}</b>\n"
        f"• Size: <code>{size_h}</code>\n"
        f"• Last 40 lines (tail):\n\n<code>{tail or '— empty —'}</code>"
    )
    await m.reply_text(header)

    try:
        await m.reply_document(
            document="log.txt",
            caption=m.lang["log_sent"].format(app.name),
        )
    except Exception as e:
        await m.reply_text(f"⚠️ Couldn't send full log file: {e}")


@app.on_message(filters.command(["logger"]) & app.sudoers)
@lang.language()
async def _logger(_, m: types.Message):
    if len(m.command) < 2:
        return await m.reply_text(m.lang["logger_usage"].format(m.command[0]))
    if m.command[1] not in ("on", "off"):
        return await m.reply_text(m.lang["logger_usage"].format(m.command[0]))

    if m.command[1] == "on":
        await db.set_logger(True)
        await m.reply_text(m.lang["logger_on"])
    else:
        await db.set_logger(False)
        await m.reply_text(m.lang["logger_off"])


@app.on_message(filters.command(["updates"]) & app.sudoers)
@lang.language()
async def _updates(_, m: types.Message):
    """Pull the latest code from git, then restart in place."""
    sent = await m.reply_text(m.lang["updating"])

    # 1) git pull
    try:
        proc = await asyncio.create_subprocess_shell(
            "git stash -u >/dev/null 2>&1; git pull --ff-only origin main 2>&1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        pull = out.decode("utf-8", "ignore").strip() or "(no output)"
    except Exception as e:
        pull = f"git pull error: {e}"

    await sent.edit_text(f"✅ <b>Pulled:</b>\n<pre>{pull[-1500:]}</pre>\n\n♻️ Restarting…")

    # 2) restart (re-exec in place so the same shell/nohup keeps it alive)
    for directory in ["cache"]:
        shutil.rmtree(directory, ignore_errors=True)

    try:
        await asyncio.wait_for(stop(), timeout=10)
    except Exception:
        pass

    try:
        os.remove("log.txt")
    except Exception:
        pass

    # Edit confirmation won't survive execl; the next boot re-registers the
    # bot. The pull result above is the only user-facing confirmation.
    os.execl(sys.executable, sys.executable, "-m", "VampireMusic")


@app.on_message(filters.command(["restart"]) & app.sudoers)
@lang.language()
async def _restart(_, m: types.Message):
    sent = await m.reply_text(m.lang["restarting"])

    for directory in ["cache", "downloads"]:
        shutil.rmtree(directory, ignore_errors=True)

    await sent.edit_text(m.lang["restarted"])

    try:
        await asyncio.wait_for(stop(), timeout=10)
    except Exception:
        pass

    try:
        os.remove("log.txt")
    except Exception:
        pass

    os.execl(sys.executable, sys.executable, "-m", "VampireMusic")
