"""Backup over Wi-Fi: Android's built-in "Wireless debugging" (ADB over Wi-Fi, Android 11+).

No app on the phone is needed. Pair once with the 6-digit code from
  Settings → System → Developer options → Wireless debugging → Pair device with pairing code,
afterwards the phone is found automatically (mDNS) whenever Wireless debugging is on and phone and
computer are in the same Wi-Fi.

No router? The computer can open its own Wi-Fi hotspot ("Direct Wi-Fi") and the phone joins it -
a direct phone ↔ computer link, like Wi-Fi Direct (Linux: NetworkManager; Windows: Mobile hotspot).

Everything else (listing, SHA-256 on the phone, copying) is the normal AdbSource.
"""

import re
import secrets
import shutil
import string
import subprocess
import sys
from dataclasses import dataclass

from .sources import _run

PAIRING = "_adb-tls-pairing._tcp"
CONNECT = "_adb-tls-connect._tcp"
HOTSPOT_CON = "PhoneBackup-Hotspot"
_ADDR = re.compile(r"^(\[[0-9a-fA-F:.]+\]|[0-9]{1,3}(?:\.[0-9]{1,3}){3}|[A-Za-z0-9.-]+):([0-9]{1,5})$")


def is_wireless(serial):
    """ADB serials of Wi-Fi connections: 'ip:port' or 'adb-…._adb-tls-connect._tcp'."""
    return CONNECT in serial or bool(_ADDR.match(serial))


def usb_first(serials):
    return sorted(serials, key=is_wireless)


def valid_address(addr):
    return bool(_ADDR.match(addr.strip()))


@dataclass
class MdnsService:
    name: str       # e.g. adb-5A111FDCH0014T-AbCdEf
    kind: str       # PAIRING or CONNECT
    address: str    # ip:port


def parse_mdns(out):
    res = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1].rstrip(".") in (PAIRING, CONNECT) and valid_address(parts[2]):
            res.append(MdnsService(parts[0], parts[1].rstrip("."), parts[2]))
    return res


def parse_avahi(out):
    """Parse `avahi-browse -rpt` lines ('=;iface;IPv4;name;type;domain;host;address;port;txt')."""
    res, seen = [], set()
    for line in out.splitlines():
        f = line.split(";")
        if len(f) < 9 or f[0] != "=" or f[4] not in (PAIRING, CONNECT):
            continue
        ip = f[7]
        if ":" in ip:                        # IPv6 address
            if ip.lower().startswith("fe80"):        # link-local needs a zone id - skip
                continue
            ip = f"[{ip}]"
        key = (f[3], f[4])
        if key in seen:
            continue
        addr = f"{ip}:{f[8]}"
        if valid_address(addr):
            seen.add(key)
            res.append(MdnsService(f[3], f[4], addr))
    # IPv4 first
    return sorted(res, key=lambda s: s.address.startswith("["))


def _avahi_services():
    if not shutil.which("avahi-browse"):
        return []
    res = []
    for kind in (PAIRING, CONNECT):
        try:
            r = _run(["avahi-browse", "-rpt", kind], timeout=8)
        except (OSError, subprocess.SubprocessError):
            continue
        res += parse_avahi(r.stdout.decode("utf-8", "replace"))
    return res


def mdns_services(adb):
    """Phones announcing wireless debugging in the Wi-Fi.

    adb's built-in mDNS often finds nothing on Linux (seen with adb 34 and 37 on Pop!_OS), while
    the system's Avahi sees the phone - so Avahi is asked as well.
    """
    res = []
    try:
        r = _run([adb, "mdns", "services"], timeout=10)
        res = parse_mdns(r.stdout.decode("utf-8", "replace"))
    except (OSError, subprocess.SubprocessError):
        pass
    known = {(s.name, s.kind) for s in res}
    res += [s for s in _avahi_services() if (s.name, s.kind) not in known]
    return res


def pair(adb, address, code):
    """Returns (ok, message)."""
    code = code.strip().replace(" ", "")
    if not valid_address(address):
        return False, "The address must look like 192.168.1.23:41234 (IP address and port)."
    if not code:
        return False, "The pairing code is missing."
    try:
        r = _run([adb, "pair", address.strip(), code], timeout=40)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"adb pair failed: {e}"
    out = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    if "Successfully paired" in out:
        return True, out
    return False, out or f"adb pair ended with code {r.returncode}"


def connect(adb, address):
    """Returns (ok, message)."""
    try:
        r = _run([adb, "connect", address.strip()], timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"adb connect failed: {e}"
    out = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    low = out.lower()
    return ("connected to" in low and "failed" not in low and "cannot" not in low), out


def _port_open(address, timeout=1.0):
    """Quick check so an absent phone does not block for adb's long connect timeout."""
    import socket
    host, _, port = address.rpartition(":")
    try:
        with socket.create_connection((host.strip("[]"), int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def service_serial(name):
    """'adb-5A111FDCH0014T-AbCdEf' → '5A111FDCH0014T' ('' if it does not look like that)."""
    if not name.startswith("adb-"):
        return ""
    return name[4:].rpartition("-")[0]


def auto_connect(adb, last_address="", known_serials=()):
    """Connect phones in the Wi-Fi that THIS computer paired before (and the last used address).

    Only services of known phones are tried (security review 2026-11-06: any device announcing
    "wireless debugging" in the network used to be connected – a fake one could feed files into
    a backup). New phones are added with "Pair over Wi-Fi…". Returns the address or "".
    """
    known = set(known_serials or ())
    candidates = [s.address for s in mdns_services(adb)
                  if s.kind == CONNECT and service_serial(s.name) in known]
    if last_address and last_address not in candidates and _port_open(last_address):
        candidates.append(last_address)
    for addr in candidates:
        ok, _ = connect(adb, addr)
        if ok:
            return addr
    return ""


def new_qr_pairing():
    """(service name, password, QR text) for Android's 'Pair device with QR code'.

    The phone scans the QR code, then announces a pairing service with exactly this name in the
    Wi-Fi; the computer finds it via mDNS and pairs with the password.
    """
    name = "phonebackup-" + secrets.token_hex(4)
    password = secrets.token_hex(6)
    return name, password, f"WIFI:T:ADB;S:{name};P:{password};;"


def remember(cfg, address, adb=None):
    """Remember the address – and the phone behind it (its serial from the Wi-Fi announcement),
    so that only phones this computer connected on purpose are connected automatically."""
    from . import config
    changed = False
    if address and cfg.get("wifi_last_address") != address:
        cfg["wifi_last_address"] = address
        changed = True
    if address and adb:
        try:
            for s in mdns_services(adb):
                serial = service_serial(s.name)
                if s.kind == CONNECT and s.address == address and serial:
                    known = list(cfg.get("wifi_serials", []))
                    if serial not in known:
                        cfg["wifi_serials"] = known + [serial]
                        changed = True
        except Exception:  # noqa: BLE001 - only a convenience for the next automatic connection
            pass
    if changed:
        try:
            config.save(cfg)
        except OSError:
            pass


def disconnect_all(adb):
    try:
        _run([adb, "disconnect"], timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


# =========================================================================== direct Wi-Fi (hotspot)

def hotspot_supported():
    """Linux with NetworkManager: the app starts the hotspot itself. Windows: the user switches on
    'Mobile hotspot' in the Windows settings (opened by the app)."""
    if sys.platform.startswith("win"):
        return True
    return shutil.which("nmcli") is not None


def new_hotspot_credentials():
    ssid = "PhoneBackup-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"     # no 0/O/1/l: easy to type on the phone
    password = "".join(secrets.choice(alphabet) for _ in range(12))
    return ssid, password


def wifi_qr_text(ssid, password):
    """Text for a Wi-Fi QR code (the phone camera joins the network directly)."""
    def esc(s):
        return re.sub(r'([\\;,:"])', r"\\\1", s)
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(password)};;"


def _nmcli(args, timeout=60):
    r = _run(["nmcli"] + args, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").strip()


def wifi_interface():
    code, out = _nmcli(["-t", "-f", "DEVICE,TYPE", "device"], timeout=15)
    if code != 0:
        return None
    for line in out.splitlines():
        dev, _, typ = line.rpartition(":")
        if typ == "wifi" and dev and not dev.startswith("p2p-"):
            return dev
    return None


def hotspot_active():
    if sys.platform.startswith("win") or not shutil.which("nmcli"):
        return False
    try:
        code, out = _nmcli(["-t", "-f", "NAME", "connection", "show", "--active"], timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return code == 0 and HOTSPOT_CON in out.splitlines()


def start_hotspot(ssid, password):
    """Linux: start the hotspot via NetworkManager. Returns (ok, message).

    Tries 5 GHz first (faster), then lets NetworkManager choose. The profile is kept, so the phone
    rejoins the same network automatically next time.
    """
    if sys.platform.startswith("win"):
        return False, "On Windows switch on 'Mobile hotspot' in the settings."
    if not shutil.which("nmcli"):
        return False, "NetworkManager (nmcli) was not found - start a hotspot in the system settings."
    dev = wifi_interface()
    if not dev:
        return False, "No Wi-Fi adapter found."
    msg = ""
    for band in (["band", "a"], []):
        try:
            code, msg = _nmcli(["device", "wifi", "hotspot", "ifname", dev, "con-name", HOTSPOT_CON,
                                "ssid", ssid, "password", password] + band, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            code, msg = 1, str(e)
        if code == 0:
            return True, ("5 GHz" if band else "Wi-Fi") + f" hotspot '{ssid}' is on ({dev})."
        try:      # remove the half-made 5 GHz profile before trying without band
            _nmcli(["connection", "delete", HOTSPOT_CON], timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
    return False, msg or "The hotspot could not be started."


def stop_hotspot():
    """Returns (ok, message). The normal Wi-Fi reconnects by itself afterwards."""
    if sys.platform.startswith("win"):
        return True, ""
    try:
        code, msg = _nmcli(["connection", "down", HOTSPOT_CON], timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return code == 0, msg


def open_windows_hotspot_settings():
    import os
    os.startfile("ms-settings:network-mobilehotspot")  # type: ignore[attr-defined]
