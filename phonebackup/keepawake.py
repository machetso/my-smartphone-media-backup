"""Keep the computer awake while a job runs.

The computer's power settings are NOT changed. Instead the operating system is told
"a backup is running" for as long as the job takes, and everything returns to normal
automatically when the job ends - even if the program crashes or is killed.

* Linux: a logind inhibitor (systemd-inhibit) blocks suspend/hibernate, closing the laptop
  lid and a normal shutdown/reboot. In addition the desktop's own idle timer is paused via
  D-Bus (org.freedesktop.ScreenSaver.Inhibit, plus org.freedesktop.PowerManagement.Inhibit
  where it exists). This second part is essential: desktops like COSMIC suspend after idle
  by running "systemctl suspend" as the user, and logind lets a user override their own block
  inhibitors - only the desktop idle inhibit stops that. While it is held the screen stays on.
  The D-Bus inhibit is tied to our connection, so it also ends if the program dies.
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

from .i18n import tr

# sent to the operating system (logind / D-Bus / Windows), not translated
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
        self.how = tr("disabled in the settings")
        self._proc = None
        self._idle = []           # held desktop idle inhibits: (uninhibit function, objects to keep)

    # ------------------------------------------------------------------ public
    def __enter__(self):
        if self.enabled:
            try:
                if sys.platform.startswith("win"):
                    self._start_windows()
                elif sys.platform.startswith("linux"):
                    self._start_linux()
                else:
                    self.how = tr("not supported on this system")
            except Exception as e:  # noqa: BLE001 - never let this stop a backup
                self.active = False
                self.how = tr("not possible (%s)", e)
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def release(self):
        self._release_idle()
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
            what = tr(self.what)                       # "Backup", "Export", … (English keys)
            what = what.lower() if what == self.what else what   # English: "while the backup runs"
            return tr("Standby/shutdown blocked while the %s runs (%s).", what, self.how)
        return tr("Could not keep the computer awake: %s. Make sure it does not go to standby.",
                  self.how)

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
        self.how = tr("Windows sleep timer paused")

    def _start_linux(self):
        idle = self._inhibit_desktop_idle()
        self._start_logind()
        if idle:
            self.how = (self.how + "; " if self.active else "") + tr("desktop idle timer paused (%s)", idle)
            self.active = True
        elif self.active:
            self.how += "; " + tr("desktop idle timer NOT paused (no D-Bus idle inhibit available)")

    def _start_logind(self):
        exe = shutil.which("systemd-inhibit")
        if not exe:
            self.how = tr("%s not found", "systemd-inhibit")
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
                parts = {"sleep": tr("standby"), "idle": tr("idle suspend"),
                         "handle-lid-switch": tr("lid close"), "shutdown": tr("shutdown")}
                self.how = tr("blocked: %s", ", ".join(parts[p] for p in what.split(":")))
                return
            err = (proc.stderr.read() or b"").decode(errors="replace").strip()
            self.how = err or tr("%s exited with code %d", "systemd-inhibit", proc.returncode)


    # ---- desktop idle timer (D-Bus session bus)
    _IDLE_SERVICES = [("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver",
                       "org.freedesktop.ScreenSaver"),
                      ("org.freedesktop.PowerManagement", "/org/freedesktop/PowerManagement/Inhibit",
                       "org.freedesktop.PowerManagement.Inhibit")]

    def _inhibit_desktop_idle(self):
        """Returns a short description of what was inhibited, or "" if nothing worked."""
        # GUI: Qt's own D-Bus connection. Terminal: dbus-python if installed, else QtDBus anyway.
        backends = ([_qt_dbus_inhibit] if _qt_app_running() else []) + [_py_dbus_inhibit, _qt_dbus_inhibit]
        names = []
        for service, path, iface in self._IDLE_SERVICES:
            held = None
            for backend in backends:
                try:
                    held = backend(service, path, iface)
                except Exception:  # noqa: BLE001 - service missing, no session bus, ...
                    held = None
                if held is not None:
                    break
            if held is not None:
                self._idle.append(held)
                names.append(service.rsplit(".", 1)[-1])
        return ", ".join(names)

    def _release_idle(self):
        while self._idle:
            uninhibit, _keep = self._idle.pop()
            try:
                uninhibit()
            except Exception:  # noqa: BLE001
                pass


def _qt_app_running():
    try:
        from PySide6.QtCore import QCoreApplication
    except ImportError:
        return False
    return QCoreApplication.instance() is not None


def _qt_dbus_inhibit(service, path, iface):
    """Inhibit via PySide6 QtDBus (GUI). Returns (uninhibit function, objects to keep) or None."""
    from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    proxy = QDBusInterface(service, path, iface, bus)
    if not proxy.isValid():
        return None
    reply = proxy.call("Inhibit", WHO, WHY)
    if reply.type() != QDBusMessage.ReplyMessage or not reply.arguments():
        return None
    cookie = int(reply.arguments()[0])
    return (lambda: proxy.call("UnInhibit", cookie)), proxy


def _py_dbus_inhibit(service, path, iface):
    """Inhibit via dbus-python (terminal version), if it is installed."""
    try:
        import dbus  # type: ignore
    except ImportError:
        return None
    bus = dbus.SessionBus()
    proxy = dbus.Interface(bus.get_object(service, path), iface)
    cookie = proxy.Inhibit(WHO, WHY)
    return (lambda: proxy.UnInhibit(cookie)), (bus, proxy)


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
