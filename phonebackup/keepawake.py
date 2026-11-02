"""Keep the computer awake while a job runs.

The computer's power settings are NOT changed. Instead the operating system is told
"a backup is running" for as long as the job takes, and everything returns to normal
automatically when the job ends - even if the program crashes or is killed.

* Linux: a logind inhibitor (systemd-inhibit) blocks suspend/hibernate, automatic idle
  suspend, closing the laptop lid and a normal shutdown/reboot. The screen may still turn off
  (that does not interrupt the backup).
* Windows: SetThreadExecutionState(ES_SYSTEM_REQUIRED) prevents sleep due to inactivity;
  the GUI additionally registers a shutdown-block reason, so Windows asks before shutting down.
  Closing the lid and pressing the power button still follow the Windows power settings.

Usage:
    with KeepAwake("Backup"):
        ...
"""

import shutil
import subprocess
import sys

WHY = "My Smartphone Media Backup is copying files - do not sleep or shut down"
WHO = "My Smartphone Media Backup"

# Windows SetThreadExecutionState flags
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040


class KeepAwake:
    """Context manager. `active` tells whether the protection really works, `how` describes it."""

    def __init__(self, what="Job", enabled=True):
        self.what = what
        self.enabled = enabled
        self.active = False
        self.how = "disabled in the settings"
        self._proc = None

    # ------------------------------------------------------------------ public
    def __enter__(self):
        if self.enabled:
            try:
                if sys.platform.startswith("win"):
                    self._start_windows()
                elif sys.platform.startswith("linux"):
                    self._start_linux()
                else:
                    self.how = "not supported on this system"
            except Exception as e:  # noqa: BLE001 - never let this stop a backup
                self.active = False
                self.how = f"not possible ({e})"
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def release(self):
        if not self.active:
            return
        self.active = False
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        elif self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None

    def message(self):
        if self.active:
            return f"Standby/shutdown blocked while the {self.what.lower()} runs ({self.how})."
        return f"Could not keep the computer awake: {self.how}. Make sure it does not go to standby."

    # ------------------------------------------------------------------ platforms
    def _start_windows(self):
        import ctypes
        # Per thread: must be called from the thread that does the work (the GUI worker / CLI).
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
        if not ctypes.windll.kernel32.SetThreadExecutionState(flags):
            # Away mode is not available on every edition - try without it.
            if not ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
                raise OSError("SetThreadExecutionState failed")
        self.active = True
        self.how = "Windows sleep timer paused"

    def _start_linux(self):
        exe = shutil.which("systemd-inhibit")
        if not exe:
            self.how = "systemd-inhibit not found"
            return
        # Try the full set first; fall back to sleep/idle only if the system refuses some of it.
        for what in ("sleep:idle:handle-lid-switch:shutdown", "sleep:idle"):
            cmd = [exe, f"--what={what}", f"--who={WHO}", f"--why={WHY}", "--mode=block",
                   # The child waits on a pipe that only we hold open: closing it (or our
                   # death) ends it, and logind releases the inhibitor with the process.
                   "sh", "-c", "read _ignored"]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self._proc = proc
                self.active = True
                parts = {"sleep": "standby", "idle": "idle suspend",
                         "handle-lid-switch": "lid close", "shutdown": "shutdown"}
                self.how = "blocked: " + ", ".join(parts[p] for p in what.split(":"))
                return
            err = (proc.stderr.read() or b"").decode(errors="replace").strip()
            self.how = err or f"systemd-inhibit exited with code {proc.returncode}"


# ---------------------------------------------------------------------- Windows shutdown dialog

def windows_block_shutdown(hwnd, block):
    """GUI only: show a reason in the Windows 'apps are preventing shutdown' screen."""
    if not sys.platform.startswith("win") or not hwnd:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if block:
            user32.ShutdownBlockReasonCreate(ctypes.c_void_p(int(hwnd)), ctypes.c_wchar_p(WHY))
        else:
            user32.ShutdownBlockReasonDestroy(ctypes.c_void_p(int(hwnd)))
    except Exception:  # noqa: BLE001
        pass
