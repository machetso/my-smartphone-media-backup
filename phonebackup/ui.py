"""Small terminal helpers: questions, colours, progress line, formatting."""

import os
import shutil
import sys
import time

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


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def info(msg):
    if _handler:
        return _handler.log("info", msg)
    print(msg)


def ok(msg):
    if _handler:
        return _handler.log("ok", msg)
    print(_c("32", msg))


def warn(msg):
    if _handler:
        return _handler.log("warn", msg)
    print(_c("33;1", msg))


def error(msg):
    if _handler:
        return _handler.log("error", msg)
    print(_c("31;1", msg))


def title(msg):
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
        print("  Please enter a value.")


def ask_yes_no(prompt, default=True):
    if _handler:
        return _handler.ask_yes_no(prompt, default)
    d = "Y/n" if default else "y/N"
    while True:
        try:
            ans = input(f"{prompt} [{d}]: ").strip().lower()
        except EOFError:
            ans = ""
        if not ans:
            return default
        if ans in ("y", "yes", "j", "ja"):
            return True
        if ans in ("n", "no", "nein"):
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
        print("  Invalid choice.")


def ask_directory(prompt):
    """Ask for a folder; returns '' if cancelled."""
    if _handler:
        return _handler.ask_directory(prompt)
    return ask(prompt + " (or press Enter to cancel)", allow_empty=True)


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
        return f"{h} h {m:02d} min {s:02d} s"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


class Progress:
    """Single updating status line."""

    def __init__(self, total_files, total_bytes):
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.files = 0
        self.bytes = 0
        self.start = time.monotonic()
        self._last = 0.0

    def update(self, files_done=None, add_bytes=0, current="", force=False):
        if files_done is not None:
            self.files = files_done
        self.bytes += add_bytes
        now = time.monotonic()
        if not force and now - self._last < 0.25:
            return
        self._last = now
        elapsed = max(now - self.start, 0.001)
        speed = self.bytes / elapsed
        remaining = (self.total_bytes - self.bytes) / speed if speed > 0 else 0
        pct = 100.0 * self.bytes / self.total_bytes if self.total_bytes else 100.0
        line = (f"  {self.files}/{self.total_files} files  {pct:5.1f}%  "
                f"{human_size(self.bytes)}/{human_size(self.total_bytes)}  "
                f"{human_size(speed)}/s  ETA {human_duration(remaining)}  {current}")
        if _handler:
            _handler.progress({"files": self.files, "total_files": self.total_files,
                               "bytes": self.bytes, "total_bytes": self.total_bytes,
                               "speed": speed, "eta": remaining, "current": current})
            return
        width = shutil.get_terminal_size((100, 20)).columns - 1
        line = line[:width]
        if sys.stdout is not None and sys.stdout.isatty():
            sys.stdout.write("\r" + line.ljust(width))
            sys.stdout.flush()

    def finish(self):
        self.update(force=True)
        if not _handler and sys.stdout is not None and sys.stdout.isatty():
            sys.stdout.write("\n")
