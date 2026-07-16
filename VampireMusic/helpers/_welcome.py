"""Welcome-message rendering: placeholder substitution + button parsing.

Supported placeholders (case-insensitive) in the welcome text:
    {id}            -> user id
    {name}          -> first name
    {surname}       -> last name
    {namesurname}   -> first + last name
    {lang}          -> user language code
    {date}          -> current date (YYYY-MM-DD)
    {time}          -> current time (HH:MM)
    {weekday}       -> current weekday name
    {mention}       -> HTML link to the user profile
    {username}      -> @username (falls back to a mention)
    {groupname}     -> group title
    {rules}         -> "rules" literal placeholder for group regulations

Inline buttons use a Telegram-classic spec, one row per line, buttons in a
row separated by ``|``::

    Rules - https://t.me/mygroup/1 | Support - https://t.me/support
    Website - https://example.com
"""
from datetime import datetime
from html import escape

from pyrogram import types


def _mention(user: types.User) -> str:
    name = escape(user.first_name or "User")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def render_text(template: str, user: types.User, chat: types.Chat) -> str:
    """Substitute placeholders in ``template`` for ``user``/``chat``."""
    now = datetime.now()
    first = escape(user.first_name or "")
    last = escape(user.last_name or "")
    username = f"@{user.username}" if user.username else _mention(user)
    values = {
        "id": str(user.id),
        "name": first,
        "surname": last,
        "namesurname": (first + " " + last).strip(),
        "lang": user.language_code or "en",
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "weekday": now.strftime("%A"),
        "mention": _mention(user),
        "username": username,
        "groupname": escape(chat.title or ""),
        "rules": "rules",
    }
    out = template
    for key, val in values.items():
        # Case-insensitive replace of {key} without touching other braces.
        for token in ("{" + key + "}", "{" + key.upper() + "}"):
            out = out.replace(token, val)
    return out


def parse_buttons(spec: str) -> types.InlineKeyboardMarkup | None:
    """Parse a button spec string into an InlineKeyboardMarkup, or None.

    Each non-empty line is a row; ``text - url`` items are split by ``|``.
    Malformed items are skipped; returns None if nothing valid is found.
    """
    if not spec:
        return None
    rows = []
    for line in spec.splitlines():
        line = line.strip()
        if not line:
            continue
        row = []
        for item in line.split("|"):
            if " - " not in item:
                continue
            text, url = item.split(" - ", 1)
            text, url = text.strip(), url.strip()
            if text and url.startswith(("http://", "https://", "tg://")):
                row.append(types.InlineKeyboardButton(text=text, url=url))
        if row:
            rows.append(row)
    return types.InlineKeyboardMarkup(rows) if rows else None
