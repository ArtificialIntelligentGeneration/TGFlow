from __future__ import annotations

from pathlib import Path
import appdirs
import os

# Application identifiers (used both at runtime and for system paths)
APP_NAME = "SLAVA"
APP_AUTHOR = "AiG"

def _resolve_user_data_dir() -> Path:
    """Return a writable per-user data directory.

    On macOS `appdirs.user_data_dir` falls back to '/Library/...'
    (a system location) when the HOME environment variable is
    undefined, which happens when the app is launched from Finder or
    from a read-only DMG.  Writing there requires root permissions and
    leads to an "unable to open database file" SQLite error.

    This helper detects that situation and substitutes the real home
    obtained via ``Path.home()``.
    """

    proposed = Path(appdirs.user_data_dir(APP_NAME, APP_AUTHOR))

    # Detect real home directory even if $HOME is undefined.
    try:
        import pwd
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    except Exception:
        real_home = Path.home().resolve()

    # If proposed path lies outside the user's home (for example
    # '/Library/Application Support/SLAVA'), rewrite it to the standard
    # '~/Library/Application Support/SLAVA'.
    if not str(proposed).startswith(str(real_home)):
        proposed = real_home / 'Library' / 'Application Support' / APP_NAME

    # --- DEBUG: write the chosen path to Desktop for troubleshooting
    try:
        dbg_log = real_home / 'Desktop' / 'myslava_debug.log'
        dbg_log.parent.mkdir(exist_ok=True)
        with dbg_log.open('a', encoding='utf-8') as f:
            from datetime import datetime
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} → USER_DATA_DIR = {proposed}\n")
    except Exception:
        # Ignore any failure – debug logging is optional
        pass

    return proposed


# Resolve the per-user data directory (~/Library/Application Support/SLAVA on macOS)
USER_DATA_DIR: Path = _resolve_user_data_dir()
# Try to create the directory; on failure, log to Desktop too
try:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    try:
        dbg_log = Path.home() / 'Desktop' / 'myslava_debug.log'
        with dbg_log.open('a', encoding='utf-8') as f:
            from datetime import datetime
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} ! mkdir failed: {e}\n")
    except Exception:
        pass
    raise


def user_file(*parts: str) -> Path:
    """Return path inside the per-user data folder.

    Example:
        user_file('accounts.json') -> ~/Library/Application Support/SLAVA/accounts.json
    """
    return USER_DATA_DIR.joinpath(*parts) 