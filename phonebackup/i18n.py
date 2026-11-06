"""Interface languages (user request 2026-11-06) – the same languages and the same dictionary
format as VideoSpeedControl, shared by this program and the phone app: i18n/<code>.json at the
top of the repository

    { "language": "Deutsch", "locale": "de-DE", "rtl": false,
      "texts": { "Save video": "Video speichern",
                 "%d sections": { "one": "%d Abschnitt", "other": "%d Abschnitte" } } }

Texts stay English in the code – tr("Save video"), trp("%d section", "%d sections", n, n) – and
are looked up in the chosen language; a missing text stays English. Templates use printf
placeholders like on Android (%s, %d, %.1f, %1$s). The choice is stored in the settings
(cfg["language"]; "system" = the computer's language if there is a dictionary for it) and takes
effect at the next start (the settings offer to restart). Reports and the log use it too.
No Qt needed here (the terminal version and the core use it too).
"""
from __future__ import annotations

import json
import locale as _locale
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path

SYSTEM = "system"


@dataclass
class Language:
    code: str
    name: str
    locale: str
    rtl: bool
    texts: dict = field(default_factory=dict)


ENGLISH = Language("en", "English", "en-US", False, {})
_languages = None  # type: Optional[List[Language]]
_current: Language = ENGLISH


def i18n_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / "i18n"


def languages() -> list[Language]:
    """English first, then every dictionary, sorted by its own name."""
    global _languages
    if _languages is None:
        found = []
        d = i18n_dir()
        for f in sorted(d.glob("*.json")) if d.is_dir() else []:
            try:
                o = json.loads(f.read_text(encoding="utf-8"))
                found.append(Language(f.stem, o["language"], o.get("locale", f.stem),
                                      bool(o.get("rtl", False)), dict(o.get("texts", {}))))
            except (OSError, ValueError, KeyError):
                continue
        _languages = [ENGLISH] + sorted((l for l in found if l.code != "en"), key=lambda l: l.name)
    return _languages


def system_code() -> str:
    """The computer's language (2-letter code), '' if unknown."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(var, "")
        if v and v not in ("C", "POSIX") and not v.startswith("C."):
            return _norm(v)
    try:
        from PySide6.QtCore import QLocale
        return _norm(QLocale.system().name())
    except Exception:  # noqa: BLE001 - no Qt (CLI / tests)
        pass
    try:
        return _norm(_locale.getlocale()[0] or "")
    except ValueError:
        return ""


def _norm(v: str) -> str:
    code = re.split(r"[_.:@-]", v.strip())[0].lower()
    return {"iw": "he", "in": "id", "ji": "yi"}.get(code, code)


def resolve(choice: str | None) -> Language:
    """The language for a stored choice ('system', 'de', …)."""
    langs = {l.code: l for l in languages()}
    if choice and choice != SYSTEM and choice in langs:
        return langs[choice]
    return langs.get(system_code(), ENGLISH)


def use(choice: str | None) -> Language:
    """Switch the language for this process (at start, and in tests)."""
    global _current
    _current = resolve(choice)
    return _current


def current() -> Language:
    return _current


def stored_choice(cfg=None) -> str:
    """The choice saved in the settings (PHONEBACKUP_LANG overrides it, for tests)."""
    if os.environ.get("PHONEBACKUP_LANG"):
        return os.environ["PHONEBACKUP_LANG"]
    if cfg is None:
        from . import config
        cfg = config.load()
    return str(cfg.get("language") or SYSTEM)


def store_choice(cfg, code: str) -> None:
    from . import config
    cfg["language"] = code
    config.save(cfg)


def plural_category(code: str, n: int) -> str:
    """CLDR plural category of n – the same rules as I18n.pluralCategory on Android."""
    n = abs(int(n))
    if code == "fr":
        return "one" if n in (0, 1) else "other"
    if code == "he":
        return {1: "one", 2: "two"}.get(n, "other")
    if code == "ro":
        if n == 1:
            return "one"
        return "few" if n == 0 or 1 <= n % 100 <= 19 else "other"
    if code in ("tlh", "ja", "zh", "ko"):
        return "other"
    return "one" if n == 1 else "other"


_PH = re.compile(r"%(?:(\d+)\$)?([-+ 0#,]*\d*(?:\.\d+)?)([sdfi%])")


def _format(template: str, args: tuple) -> str:
    """printf formatting like Java's String.format: %s %d %.1f %1$s %%; right-to-left languages
    wrap every inserted value in Unicode isolates (a number or file name stays one run)."""
    rtl = _current.rtl
    seq = iter(range(len(args)))

    def one(m):
        pos, spec, conv = m.group(1), m.group(2), m.group(3)
        if conv == "%":
            return "%"
        try:
            i = int(pos) - 1 if pos else next(seq)
            v = args[i]
        except (StopIteration, IndexError, ValueError):
            return m.group(0)
        if conv in "di":
            try:
                v = int(v)
            except (TypeError, ValueError):
                conv = "s"
        try:
            s = ("%" + spec.replace(",", "") + (conv if conv != "i" else "d")) % v
        except (TypeError, ValueError):
            s = str(v)
        return f"⁨{s}⁩" if rtl else s

    return _PH.sub(one, template)


def tr(en: str, *args) -> str:
    """`en` in the current language; with args it is a printf template."""
    v = _current.texts.get(en)
    text = v if isinstance(v, str) else (v.get("other", en) if isinstance(v, dict) else en)
    return _format(text, args) if args else text


def trp(one: str, other: str, n, *args) -> str:
    """A text with a number: English `one` / `other`; dictionaries key it by `other` and may give
    every plural form of their language ("one", "two", "few", "other")."""
    v = _current.texts.get(other)
    if isinstance(v, str):
        text = v
    elif isinstance(v, dict):
        text = v.get(plural_category(_current.code, n), v.get("other", other))
    else:
        text = one if abs(int(n)) == 1 else other
    return _format(text, args)


def N_(en: str) -> str:
    """Marks a text for translation without translating it now (tables built at import time):
    the extractor finds it, the code calls tr(value) where it is shown."""
    return en


# English unless the program chose a language at start (gui.main / cli)
use("en")
