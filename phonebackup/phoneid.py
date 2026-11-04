"""Which phone belongs to which backup - never mix up phones (user requirement 2026-11-04).

Every backup folder ("Galaxy A55 - Kim") remembers its phone in .phonebackup/phone.json:
model, the phone's serial numbers (ADB: ro.serialno) and the phone app's ids (its key, paired).
Before a backup the connected phone must match:

* an id that both sides know (serial number or phone-app id) decides - a different id = refused;
* if no id can be compared (e.g. a new connection type), only the same model is accepted, and
  the user has to confirm it; the folder then does not learn new ids from that backup;
* a folder without phone.json (first backup, or made by an older version) is accepted when the
  model matches the backup's phone name or the user confirms it - then the ids are stored.

`identify(source)` reads the ids live from the phone; it is called twice: when Start is clicked and
again right before the first file is read (the phone might have been swapped in between).
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .index import INTERNAL_DIR

FILE = "phone.json"
MATCH, PROBABLE, NEW, MISMATCH = "match", "probable", "new", "mismatch"


@dataclass
class PhoneId:
    model: str = ""
    manufacturer: str = ""
    serial: str = ""            # ro.serialno (ADB) - "" if unknown
    app_id: str = ""            # phone app id (key checked) - "" if unknown
    connection: str = ""        # "usb-adb" | "wifi-adb" | "app-wifi" | "app-cable" | "mtp" | "folder"

    @property
    def label(self):
        return " ".join(x for x in (self.manufacturer, self.model) if x).strip() or "unknown phone"


@dataclass
class Record:
    model: str = ""
    serials: list = field(default_factory=list)
    app_ids: list = field(default_factory=list)


def identify(src):
    """Ask the connected phone who it is (live, no cached values)."""
    from .companion import CompanionSource
    from .sources import AdbSource
    if isinstance(src, AdbSource):
        model = src.shell("getprop ro.product.model").strip() or src.device_name
        serial = src.shell("getprop ro.serialno").strip() or getattr(src, "hw_serial", "")
        link = getattr(src, "link", None)
        app_id = ""
        if link is not None:
            try:                       # key-checked connection to the phone app (adb forward)
                info = link.client.request("GET", "/info")
                app_id = (info or {}).get("phone_id", "") or link.entry.get("phone_id", "")
            except Exception:  # noqa: BLE001 - app gone: the serial still identifies the phone
                app_id = ""
        return PhoneId(model, src.manufacturer, serial, app_id,
                       "wifi-adb" if src.wireless else "usb-adb")
    if isinstance(src, CompanionSource):
        info = src.client.request("GET", "/info") or {}
        return PhoneId(info.get("model", "") or src.device_name, info.get("manufacturer", ""),
                       "", info.get("phone_id", "") or src.entry.get("phone_id", ""), "app-wifi")
    kind = (getattr(src, "kind", "") or "").lower()
    return PhoneId(getattr(src, "device_name", "") or "", "", getattr(src, "serial", "") or "", "",
                   "mtp" if "mtp" in kind else "folder")


def _path(parent):
    return Path(parent) / INTERNAL_DIR / FILE


def load(parent):
    try:
        d = json.loads(_path(parent).read_text(encoding="utf-8"))
        return Record(d.get("model", ""), list(d.get("serials", [])), list(d.get("app_ids", [])))
    except (OSError, ValueError):
        return from_reports(parent)


_SMARTPHONE = re.compile(r"^\s*Smartphone\s*:\s*(.+?)\s*$", re.M)
_SERIAL = re.compile(r"^\s*Connection\s*:.*?\bserial ([^\s,]+)", re.M)


def from_reports(parent):
    """Backups made before phone.json existed: the phone from their reports (model + ADB serial
    numbers; Wi-Fi debugging 'serials' are only ip:port and are ignored)."""
    model, serials = "", []
    try:
        reports = sorted(Path(parent).glob("Backup *.txt"))
    except OSError:
        return None
    for r in reports:
        try:
            text = r.read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            continue
        m = _SMARTPHONE.search(text)
        model = model or (m.group(1) if m else "")
        for sn in _SERIAL.findall(text):
            if ":" not in sn and sn not in serials:
                serials.append(sn)
    return Record(model, serials, []) if (model or serials) else None


def save(parent, rec):
    p = _path(parent)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"model": rec.model, "serials": rec.serials, "app_ids": rec.app_ids},
                              indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _same(a, b):
    return bool(a) and bool(b) and a.strip().casefold() == b.strip().casefold()


def compare(rec, pid):
    """MATCH / PROBABLE (only the model agrees) / NEW (folder knows no phone) / MISMATCH."""
    if rec is None or not (rec.model or rec.serials or rec.app_ids):
        return NEW
    decided = False
    if pid.serial and rec.serials:
        if pid.serial not in rec.serials:
            return MISMATCH
        decided = True
    if pid.app_id and rec.app_ids:
        if pid.app_id not in rec.app_ids:
            return MISMATCH
        decided = True
    if decided:
        return MATCH
    return PROBABLE if _same(rec.model, pid.model) else MISMATCH


def learn(parent, pid, result):
    """After a confirmed backup start: remember the phone's ids in the backup folder.
    Only with an exact match (or a new folder) - a model-only match never adds ids."""
    if result not in (MATCH, NEW):
        return
    rec = load(parent) or Record()
    rec.model = rec.model or pid.model
    if pid.serial and pid.serial not in rec.serials:
        rec.serials.append(pid.serial)
    if pid.app_id and pid.app_id not in rec.app_ids:
        rec.app_ids.append(pid.app_id)
    save(parent, rec)


def same_phone(a, b):
    """Is PhoneId b (read again right before copying) the phone a that was confirmed?"""
    if a.serial and b.serial:
        return a.serial == b.serial
    if a.app_id and b.app_id:
        return a.app_id == b.app_id
    return _same(a.model, b.model)


# --------------------------------------------------------------------------- connection speed

def usb_speed_mbit(vendor_names=("04e8", "18d1", "2717", "22b8", "2a70", "22d9", "12d1", "339b",
                                 "0fce", "2d95", "1004", "0bb4", "19d2", "17ef", "2ae5")):
    """Linux: link speed of the phone on the USB cable (480 = USB 2, 5000+ = USB 3), or None."""
    base = Path("/sys/bus/usb/devices")
    if not base.is_dir():
        return None
    for d in base.glob("*"):
        try:
            if (d / "idVendor").read_text().strip() in vendor_names:
                return int((d / "speed").read_text().strip())
        except (OSError, ValueError):
            continue
    return None


def speed_advice(pid, usb_mbit=None, on_cable=""):
    """(is_fastest, text) about the connection and how to make it faster.
    on_cable: a phone that is on the USB cable without USB debugging (adbsetup.detect_usb_phone)."""
    c = pid.connection
    if c == "usb-adb":
        if usb_mbit is not None and usb_mbit < 5000:
            return False, ("USB cable with USB debugging, but only USB 2 speed (about 20–30 MB/s). "
                           "For about 2× faster: use a USB 3 cable (often blue plugs / “SS”) and a "
                           "USB 3 port on the computer.")
        return True, "USB cable with USB debugging – the fastest connection (about 25–50 MB/s)."
    if on_cable and c != "usb-adb":
        fix = (f"Faster (about 25–50 MB/s): the {on_cable} is already on the USB cable"
               + (" (USB 3)" if usb_mbit and usb_mbit >= 5000 else "")
               + ", only USB debugging is off – tap “Allow backup over cable” in the phone app "
               "(or switch on USB debugging in the Developer options), then click Start again.")
    else:
        fix = ("Faster (about 25–50 MB/s): plug the phone in with a USB cable and tap “Allow backup "
               "over cable” in the phone app (or switch on USB debugging in the Developer options).")
    if c in ("wifi-adb", "app-wifi"):
        return False, "Wi-Fi – slower (about 3–30 MB/s, depends on the Wi-Fi). " + fix
    if c == "mtp":
        return False, ("USB file transfer (MTP) – slower (about 10–20 MB/s) and without a check on "
                       "the phone. " + fix)
    return True, ""
