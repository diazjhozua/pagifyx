"""Font availability on the local machine, so the .docx only names fonts Word can render."""

import sys
from functools import cache

FALLBACK_FONT = "Calibri"
_WINDOWS_FONT_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"


@cache
def installed_font_families() -> frozenset[str]:
    """Lowercased family names registered with Windows. Empty on other platforms."""
    if sys.platform != "win32":
        return frozenset()
    import winreg

    names: set[str] = set()
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, _WINDOWS_FONT_KEY) as key:
                index = 0
                while True:
                    try:
                        value_name, _, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    # Entries look like "Calibri (TrueType)".
                    names.add(value_name.split(" (")[0].strip().lower())
                    index += 1
        except OSError:
            continue
    return frozenset(names)


def resolve_font(site_font: str | None, installed: frozenset[str] | None = None) -> str:
    """Use the site's font when this machine has it; otherwise the fallback font."""
    available = installed_font_families() if installed is None else installed
    if site_font and site_font.lower() in available:
        return site_font
    return FALLBACK_FONT
