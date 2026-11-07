"""Is there a newer version on GitHub? (user request 2026-11-07)

One small request to GitHub's public API at start, at most once a day, only when the setting
"Check for a new version at start" is on (default). Nothing about the computer, the phone or
the backups is sent – only the usual request (address of this computer, program name as
User-Agent). Any problem (no internet, Direct Wi-Fi, GitHub down) is silently ignored: the
program never depends on it.
"""

import json
import re
import time
import urllib.request

from . import __version__

REPO = "machetso/my-smartphone-media-backup"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
EVERY = 24 * 3600              # seconds between two checks
TIMEOUT = 8
MAX_ANSWER = 512 * 1024


def parse_version(text):
    """'v0.9.7' / '0.9.7' → (0, 9, 7); None if it is not a plain version number."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+){1,3})", (text or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _pad(v):
    return v + (0,) * (4 - len(v))


def is_newer(candidate, current=__version__):
    a, b = parse_version(candidate), parse_version(current)
    return bool(a and b and _pad(a) > _pad(b))


def latest_release(fetch=None):
    """(version text, page url) of the newest published release, or None."""
    def default_fetch(url):
        req = urllib.request.Request(url, headers={"User-Agent": "my-smartphone-media-backup",
                                                   "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(MAX_ANSWER)
    try:
        data = json.loads((fetch or default_fetch)(API_URL))
    except Exception:  # noqa: BLE001 - offline, rate limit, odd answer: just no hint
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name", ""))
    url = str(data.get("html_url", ""))
    if not parse_version(tag):
        return None
    if not url.startswith(f"https://github.com/{REPO}/releases/"):
        url = RELEASES_URL                       # never open a link from the answer elsewhere
    return tag.lstrip("v"), url


def due(cfg, now=None):
    """Should the program look now? (setting on, last check more than a day ago)"""
    if not cfg.get("update_check", True):
        return False
    now = time.time() if now is None else now
    return now - float(cfg.get("update_checked_at", 0) or 0) >= EVERY


def check(cfg, fetch=None, now=None):
    """(version, url) when a newer version than this one exists and was not skipped, else None.
    Notes the time of the check in cfg (the caller saves it)."""
    rel = latest_release(fetch)
    if rel is None:
        return None
    cfg["update_checked_at"] = time.time() if now is None else now
    version, url = rel
    if not is_newer(version) or version == cfg.get("update_skip"):
        return None
    return version, url
