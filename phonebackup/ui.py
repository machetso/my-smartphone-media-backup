"""Small terminal helpers: questions, colours, progress line, formatting."""

import collections
import os
import shutil
import sys
import threading
import time

from .i18n import tr

if os.name == "nt" and sys.stdout is not None and sys.stdout.isatty():
    os.system("")  # enables ANSI colour codes in the Windows console

_COLOR = sys.stdout is not None and sys.stdout.isatty()

# A graphical front end can install a handler object with the methods
# log(level, text), ask(prompt, default), ask_yes_no(prompt, default), choose(prompt, options, default),
# ask_directory(prompt) and progress(dict). Without a handler everything goes to the terminal.
_handler = None


def set_handler(handler):
    global _handler
    _handler = handler


def _shown(msg):
    """A report.Shown (English value for the program) is shown in the chosen language."""
    return getattr(msg, "local", msg)


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def info(msg):
    msg = _shown(msg)
    if _handler:
        return _handler.log("info", msg)
    print(msg)


def ok(msg):
    msg = _shown(msg)
    if _handler:
        return _handler.log("ok", msg)
    print(_c("32", msg))


def warn(msg):
    msg = _shown(msg)
    if _handler:
        return _handler.log("warn", msg)
    print(_c("33;1", msg))


def error(msg):
    msg = _shown(msg)
    if _handler:
        return _handler.log("error", msg)
    print(_c("31;1", msg))


def title(msg):
    msg = _shown(msg)
    if _handler:
        return _handler.log("title", msg)
    print()
    print(_c("1", msg))
    print(_c("1", "=" * len(msg)))


def ask(prompt, default=None, allow_empty=False):
    if _handler:
        return _handler.ask(prompt, default)
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            ans = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            ans = ""
        if not ans and default is not None:
            return str(default)
        if ans or allow_empty:
            return ans
        print("  " + tr("Please enter a value."))


def ask_install(title, text, details):
    """Before anything is installed on a phone: always asked, never answered by default."""
    if _handler and hasattr(_handler, "ask_install"):
        return _handler.ask_install(title, text, details)
    import re
    plain = lambda t: re.sub(r"<[^>]+>", "", t.replace("<br>", "\n").replace("</li>", "\n"))
    print(f"\n=== {title} ===\n{plain(text)}\n{plain(details)}")
    return ask_yes_no(tr("Install on the phone now?"), default=False)


def ask_yes_no(prompt, default=True):
    if _handler:
        return _handler.ask_yes_no(prompt, default)
    d = tr("Y/n") if default else tr("y/N")
    yes = {"y", "yes", "j", "ja", tr("y").lower(), tr("yes").lower()}
    no = {"n", "no", "nein", tr("n").lower(), tr("no").lower()}
    while True:
        try:
            ans = input(f"{prompt} [{d}]: ").strip().lower()
        except EOFError:
            ans = ""
        if not ans:
            return default
        if ans in yes:
            return True
        if ans in no:
            return False


def choose(prompt, options, default=1):
    """Show a numbered list, return the chosen index (0-based)."""
    if _handler:
        return _handler.choose(prompt, options, default)
    for i, opt in enumerate(options, 1):
        print(f"  {i}) {opt}")
    while True:
        ans = ask(prompt, str(default) if default else None)
        if ans.isdigit() and 1 <= int(ans) <= len(options):
            return int(ans) - 1
        print("  " + tr("Invalid choice."))


def ask_directory(prompt):
    """Ask for a folder; returns '' if cancelled."""
    if _handler:
        return _handler.ask_directory(prompt)
    return ask(tr("%s (or press Enter to cancel)", prompt), allow_empty=True)


def parse_numbers(text, maximum):
    """'1,3 4-6' -> [1,3,4,5,6] (1-based, validated)."""
    out = []
    for part in text.replace(",", " ").split():
        if "-" in part:
            a, b = part.split("-", 1)
            if a.isdigit() and b.isdigit():
                out.extend(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.append(int(part))
    return [n for n in dict.fromkeys(out) if 1 <= n <= maximum]


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def human_duration(seconds):
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return tr("%d h %02d min %02d s", h, m, s)
    if m:
        return tr("%d min %02d s", m, s)
    return tr("%d s", s)


last_transfer = None          # {"files", "bytes", "seconds"} of the last finished Progress (summary)


class Progress:
    """Single updating status line. Thread-safe: parallel uploads update it together.

    Shows: percentage, files done / to go, current speed (last ~5 s, the average at the start),
    time left, and the file(s) being copied right now (`begin` / `end` per file)."""

    SPEED_WINDOW = 5.0

    def __init__(self, total_files, total_bytes):
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.files = 0
        self.bytes = 0
        self.start = time.monotonic()
        self._last = 0.0
        self._lock = threading.Lock()
        self._samples = collections.deque()          # (time, bytes) for the current speed
        self._active = {}                            # token -> file name being copied now
        self._n = 0

    def begin(self, name):
        """A file starts (several at once for parallel uploads). Returns a token for end()."""
        with self._lock:
            self._n += 1
            self._active[self._n] = name
            return self._n

    def end(self, token, done=True):
        with self._lock:
            self._active.pop(token, None)
            if done:
                self.files += 1
        self.update()

    def _speed(self, now):
        self._samples.append((now, self.bytes))
        while len(self._samples) > 2 and now - self._samples[0][0] > self.SPEED_WINDOW:
            self._samples.popleft()
        t0, b0 = self._samples[0]
        if now - self.start < self.SPEED_WINDOW or now - t0 < 1.0:
            return self.bytes / max(now - self.start, 0.001)
        return (self.bytes - b0) / (now - t0)

    def update(self, files_done=None, add_bytes=0, current="", force=False):
        with self._lock:
            if files_done is not None:
                self.files = files_done
            self.bytes += add_bytes
            now = time.monotonic()
            if not force and now - self._last < 0.25:
                return
            self._last = now
            speed = self._speed(now)
            avg = self.bytes / max(now - self.start, 0.001)
            remaining = (self.total_bytes - self.bytes) / speed if speed > 0 else 0
            pct = 100.0 * self.bytes / self.total_bytes if self.total_bytes else 100.0
            active = list(self._active.values()) or ([current] if current else [])
            files = self.files
        line = "  " + tr("%5.1f%%  %d/%d files  %s/%s  %s/s  ETA %s  %s", pct, files,
                         self.total_files, human_size(self.bytes), human_size(self.total_bytes),
                         human_size(speed), human_duration(remaining), ", ".join(active))
        if _handler:
            _handler.progress({"files": files, "total_files": self.total_files,
                               "to_go": max(self.total_files - files, 0), "percent": pct,
                               "bytes": self.bytes, "total_bytes": self.total_bytes,
                               "speed": speed, "speed_avg": avg, "eta": remaining,
                               "current": ", ".join(active), "active": active})
            return
        width = shutil.get_terminal_size((100, 20)).columns - 1
        line = line[:width]
        if sys.stdout is not None and sys.stdout.isatty():
            sys.stdout.write("\r" + line.ljust(width))
            sys.stdout.flush()

    def finish(self):
        global last_transfer
        self.update(force=True)
        last_transfer = {"files": self.files, "bytes": self.bytes,
                         "seconds": time.monotonic() - self.start}
        if not _handler and sys.stdout is not None and sys.stdout.isatty():
            sys.stdout.write("\n")
