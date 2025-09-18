from __future__ import annotations

from typing import Union

try:
    from pyrogram.enums import ChatType
except Exception:
    ChatType = None  # type: ignore


def normalize_recipient(value: str) -> str:
    """Normalize recipient string to '@username' or '-100…' form.

    Accepts raw usernames, '@username', and full t.me URLs.
    Preserves numeric chat ids (e.g. -100123...).
    """
    if not value:
        return ""
    s = value.strip()
    # Strip t.me prefixes
    for pref in ("https://t.me/", "http://t.me/", "t.me/"):
        if s.lower().startswith(pref):
            s = s[len(pref):]
            break
    # Remove leading '@' for processing
    if s.startswith('@'):
        s = s[1:]

    # If it's a numeric chat id (may start with -100 or -)
    if s.startswith('-') or s[:3] == '100' and value.startswith('-'):
        # Caller may pass already normalized id with leading '-100'
        return value.strip()
    if s.startswith('-100'):
        return '-' + s[1:] if not s.startswith('-') else s
    # If the remaining string is all digits (e.g., -100123 handled above)
    if s.isdigit():
        return s if s.startswith('-') else '-' + s

    # Username: ensure single leading '@'
    return f"@{s}" if s else ""


def is_supported_chat_type(chat_type: Union[str, "ChatType"]) -> bool:
    """Return True if chat type is one of GROUP/SUPERGROUP/CHANNEL."""
    try:
        if ChatType is not None and isinstance(chat_type, ChatType):
            return chat_type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL)
    except Exception:
        pass
    name = str(chat_type)
    if name.startswith('ChatType.'):
        name = name.split('.', 1)[1]
    name = name.upper()
    return name in {"GROUP", "SUPERGROUP", "CHANNEL"}


