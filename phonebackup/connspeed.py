"""Which connection to the phone is the fastest right now (user request 2026-11-10)?

The program checks in the background what is possible – USB cable (USB debugging or file
transfer), Wi-Fi (phone app or Wireless debugging), Direct Wi-Fi – and estimates the speed of
each: from real backups of this computer when there are some (cfg["speed_seen"]), otherwise from
the USB link (USB 2 / USB 3) and the Wi-Fi link rate. No Qt here.
"""

import re
import shutil
import subprocess
import sys

from .i18n import N_, tr

# label, typical speed in MB/s: (USB 2, USB 3) for the cable, else one value per Wi-Fi link
LABELS = {
    "adb_usb": N_("USB cable – USB debugging"),
    "mtp": N_("USB cable – file transfer"),
    "app_wifi": N_("Wi-Fi – phone app"),
    "wifi_adb": N_("Wi-Fi – Wireless debugging"),
    "hotspot": N_("Direct Wi-Fi (no router)"),
}
CABLE_MBS = {"adb_usb": (25.0, 45.0), "mtp": (12.0, 20.0)}
FASTER_FACTOR = 1.5          # only hint when the other way is clearly faster


def wifi_link_mbit():
    """This computer's Wi-Fi link rate in Mbit/s, or None."""
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True,
                                 timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            rates = [float(x) for x in re.findall(rb"(?:Receive|Transmit) rate \(Mbps\)\s*:\s*([\d.]+)", out)]
            return max(rates) if rates else None
        if shutil.which("nmcli"):
            out = subprocess.run(["nmcli", "-t", "-f", "ACTIVE,RATE", "dev", "wifi"], capture_output=True,
                                 timeout=5).stdout.decode("utf-8", "replace")
            for line in out.splitlines():
                if line.startswith(("yes:", "ja:")):
                    m = re.search(r"(\d+)", line.split(":", 1)[1])
                    return float(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def estimate(key, usb_mbit=None, wifi_mbit=None, seen=None):
    """Expected MB/s of a connection: measured before > from the link > typical."""
    seen = seen or {}
    if seen.get(key):
        return float(seen[key])
    if key in CABLE_MBS:
        usb2, usb3 = CABLE_MBS[key]
        return usb3 if (usb_mbit or 5000) >= 5000 else usb2
    if key in ("app_wifi", "wifi_adb", "hotspot"):
        # measured 2026-11-10, Pixel 10 Pro, 540 Mbit/s Wi-Fi, same 250 MB: phone app 8–11 MB/s,
        # Wireless debugging only 6.2 MB/s (ADB adds its own encryption and protocol on top)
        base = 10.0 if not wifi_mbit else min(30.0, wifi_mbit / 8 * 0.15)
        return round(base * (0.65 if key == "wifi_adb" else 1.0), 1)
    return 0.0


def options(probe, seen=None):
    """[{key, label, available, speed, note}] fastest first.
    probe: usb_phone, usb_mbit, adb_usb, mtp, app_wifi, adb_wifi, hotspot_possible, wifi_mbit."""
    rows = []

    def add(key, available, note=""):
        rows.append({"key": key, "label": tr(LABELS[key]), "available": bool(available),
                     "speed": estimate(key, probe.get("usb_mbit"), probe.get("wifi_mbit"), seen),
                     "note": note})

    cable = probe.get("usb_phone")
    add("adb_usb", probe.get("adb_usb"),
        "" if probe.get("adb_usb") else
        tr("phone on the cable – switch on USB debugging (or “Allow backup over cable” in the phone app)")
        if cable else tr("plug the phone in"))
    add("mtp", probe.get("mtp") or (cable and not probe.get("adb_usb")),
        "" if probe.get("mtp") else tr("choose “File transfer” on the phone") if cable else tr("plug the phone in"))
    add("app_wifi", probe.get("app_wifi"),
        "" if probe.get("app_wifi") else tr("open the phone app and tap “Start backup mode”"))
    add("wifi_adb", probe.get("adb_wifi"),
        "" if probe.get("adb_wifi") else tr("“Allow backup over Wireless debugging” in the phone app"))
    if probe.get("hotspot_used"):            # the phone app / Wireless debugging runs over it
        add("hotspot", True)
        rows[-1]["in_use"] = True
    elif probe.get("hotspot_on"):
        add("hotspot", False, tr("on – the phone has not joined it yet"))
        rows[-1]["can_start"] = True                             # "Use" opens the Direct Wi-Fi window
    else:
        add("hotspot", False, tr("start “Direct Wi-Fi…” – the phone joins the computer's own Wi-Fi")
            if probe.get("hotspot_possible") else tr("not possible on this computer"))
        rows[-1]["can_start"] = bool(probe.get("hotspot_possible"))
    rows.sort(key=lambda r: (not r["available"], -r["speed"]))
    return rows


def faster_than(rows, current_key):
    """The clearly faster available option than the one in use, or None."""
    cur = next((r for r in rows if r["key"] == current_key), None)
    if cur is None:
        return None
    for r in rows:
        if r["available"] and r["key"] != current_key and r["speed"] >= cur["speed"] * FASTER_FACTOR:
            return r
    return None


def remember(cfg, key, nbytes, seconds):
    """Keep the real speed of a longer backup (the next estimate uses it)."""
    if key and seconds >= 20 and nbytes >= 100 * 1024 * 1024:
        cfg.setdefault("speed_seen", {})[key] = round(nbytes / seconds / 1e6, 1)
        return True
    return False


def current_key(source_key):
    """adbsetup.source_key → the keys here ('adb_app'/'adb_manual' are both the USB cable)."""
    return {"adb_app": "adb_usb", "adb_manual": "adb_usb"}.get(source_key, source_key)
