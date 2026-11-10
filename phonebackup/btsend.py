"""Send the phone app to a phone over Bluetooth (user request 2026-11-10) – the last way when
neither the USB cable (USB debugging) nor the QR code (same Wi-Fi) works.

Bluetooth "file transfer" (OBEX Object Push): the phone must be paired with this computer in the
computer's Bluetooth settings. The phone asks "Accept file?", the file lands in "Downloads" /
"Bluetooth received", a tap on it installs the app (Android asks once to allow installs from that
app). Only the bundled MediaBackup.apk is ever sent.

Linux: BlueZ obexd over D-Bus (package "bluez-obexd" on Debian/Ubuntu/Pop!_OS).
Windows: the system's "Send files via Bluetooth" wizard (fsquirt.exe) – the file is chosen there.
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .i18n import tr


class BtSendError(Exception):
    pass


def supported():
    """(True, '') or (False, why)."""
    if sys.platform.startswith("win"):
        return (True, "") if shutil.which("fsquirt") or Path(os.environ.get("SystemRoot", r"C:\Windows"),
                                                             "System32", "fsquirt.exe").is_file() \
            else (False, tr("Windows' “Send files via Bluetooth” is missing."))
    if not sys.platform.startswith("linux"):
        return False, tr("Not available on this system.")
    try:
        import dbus_fast  # noqa: F401
    except ImportError:
        return False, tr("The Python package dbus-fast is missing.")
    return True, ""


def _run(coro):
    return asyncio.run(coro)


async def _paired():
    from dbus_fast import BusType
    from dbus_fast.aio import MessageBus
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        om = bus.get_proxy_object("org.bluez", "/", await bus.introspect("org.bluez", "/"))
        objs = await om.get_interface("org.freedesktop.DBus.ObjectManager").call_get_managed_objects()
        out = []
        for _path, ifs in objs.items():
            d = ifs.get("org.bluez.Device1")
            if d and d.get("Paired") and d["Paired"].value:
                name = (d.get("Alias") or d.get("Name"))
                out.append((d["Address"].value, name.value if name else d["Address"].value))
        return sorted(out, key=lambda x: x[1].lower())
    finally:
        bus.disconnect()


def paired_devices():
    """[(address, name)] of the devices paired with this computer over Bluetooth (Linux)."""
    try:
        return _run(_paired())
    except Exception as e:  # noqa: BLE001
        raise BtSendError(tr("Bluetooth is not available: %s", e)) from e


async def _send(address, path, progress, cancel):
    from dbus_fast import Variant
    from dbus_fast.aio import MessageBus
    from dbus_fast.errors import DBusError
    bus = await MessageBus().connect()            # obexd runs on the session bus
    try:
        try:
            intro = await bus.introspect("org.bluez.obex", "/org/bluez/obex")
        except DBusError as e:
            raise BtSendError(tr("The Bluetooth file transfer service is missing on this computer. "
                                 "Install the package “bluez-obexd” (e.g. sudo apt install bluez-obexd), "
                                 "then try again.")) from e
        client = bus.get_proxy_object("org.bluez.obex", "/org/bluez/obex", intro) \
            .get_interface("org.bluez.obex.Client1")
        try:
            session = await client.call_create_session(address, {"Target": Variant("s", "opp")})
        except DBusError as e:
            raise BtSendError(tr("The phone did not accept the connection: %s – is Bluetooth on on the phone "
                                 "and is it paired with this computer?", e.text)) from e
        try:
            sobj = bus.get_proxy_object("org.bluez.obex", session, await bus.introspect("org.bluez.obex", session))
            push = sobj.get_interface("org.bluez.obex.ObjectPush1")
            transfer, _props = await push.call_send_file(str(path))
            tobj = bus.get_proxy_object("org.bluez.obex", transfer, await bus.introspect("org.bluez.obex", transfer))
            props = tobj.get_interface("org.freedesktop.DBus.Properties")
            size = os.path.getsize(path)
            deadline = time.monotonic() + 600
            while True:
                if cancel is not None and cancel.is_set():
                    try:
                        await tobj.get_interface("org.bluez.obex.Transfer1").call_cancel()
                    except DBusError:
                        pass
                    raise BtSendError(tr("Cancelled."))
                try:
                    status = (await props.call_get("org.bluez.obex.Transfer1", "Status")).value
                    done = (await props.call_get("org.bluez.obex.Transfer1", "Transferred")).value
                except DBusError:          # the transfer object is gone when it ended
                    return
                if progress:
                    progress(done, size, status)
                if status == "complete":
                    return
                if status == "error":
                    raise BtSendError(tr("The phone refused the file or the connection broke off."))
                if time.monotonic() > deadline:
                    raise BtSendError(tr("No answer from the phone – accept the file there in time."))
                await asyncio.sleep(0.5)
        finally:
            try:
                await client.call_remove_session(session)
            except DBusError:
                pass
    finally:
        bus.disconnect()


def send_apk(address, apk, version, progress=None, cancel=None):
    """Send the bundled phone app (as 'My Media Backup <version>.apk') to a paired device."""
    if Path(apk).name != "MediaBackup.apk" or not Path(apk).is_file():
        raise BtSendError("refused: only the bundled phone app is sent")
    with tempfile.TemporaryDirectory() as d:
        named = Path(d) / f"My-Media-Backup-{version}.apk"
        shutil.copyfile(apk, named)
        _run(_send(address, named, progress, cancel))


def windows_wizard(apk):
    """Windows: open 'Send files via Bluetooth' and show the file in Explorer to pick it."""
    subprocess.Popen(["explorer", "/select,", str(apk)])
    subprocess.Popen(["fsquirt.exe"])
