"""Phone connection choices and the beginner's guide for switching on USB debugging
(user request 2026-11-04).

No Qt here: the GUI (`gui_setup.py`) shows it. Contents:
- CONNECTIONS: the ways to connect, with the speed to expect (USB 3 cable measured with a Pixel
  10 Pro; the others are typical values).
- detect_usb_phone(): the model of a phone on the cable *before* USB debugging is on (it shows up
  as a normal USB / file-transfer device), so the guide can name the phone.
- guide_for(): step-by-step text for the common brands; search_url(): a ready-made web search
  for any other phone.
"""

import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0


@dataclass(frozen=True)
class Connection:
    key: str
    title: str
    speed: str          # what to expect
    mb_s: tuple         # (low, high) MB/s, for sorting / the bar in the overview
    note: str
    short: str = ""     # short title for the settings page

    @property
    def speed_short(self):
        return f"{self.mb_s[0]}–{self.mb_s[1]} MB/s"


DEFAULT_CONNECTION = "adb_app"
CONNECTIONS = (
    Connection("adb_app", "USB cable + USB debugging, switched on and off by the phone app",
               "45–50 MB/s (USB 3 cable) · about 20–30 MB/s (USB 2)", (45, 50),
               "Fastest, every file checked on the phone. Before a backup tap “Allow backup over "
               "cable” in the phone app; the computer switches USB debugging off again afterwards. "
               "One-time setup: switch on USB debugging by hand once.",
               short="Cable + USB debugging via the phone app"),
    Connection("adb_manual", "USB cable + USB debugging, switched on by hand",
               "45–50 MB/s (USB 3 cable) · about 20–30 MB/s (USB 2)", (45, 50),
               "Same speed. Without the phone app you switch USB debugging on in the Developer "
               "options before each backup; the computer switches it off again afterwards.",
               short="Cable + USB debugging, switched on by hand"),
    Connection("mtp", "USB cable, normal file transfer (MTP)",
               "10–20 MB/s", (10, 20),
               "Nothing to switch on – choose “File transfer” on the phone. Slower; the files "
               "can only be checked on the computer, not on the phone.",
               short="Cable, normal file transfer (MTP)"),
    Connection("wifi_adb", "Wi-Fi: Wireless debugging",
               "10–40 MB/s, depends on the Wi-Fi", (10, 40),
               "No cable. Pair once with a QR code (Android 11+); the computer switches Wireless "
               "debugging off again after the backup.",
               short="Wi-Fi: Wireless debugging"),
    Connection("app_wifi", "Wi-Fi: phone app only (no debugging)",
               "10–30 MB/s, depends on the Wi-Fi", (10, 30),
               "No Developer options at all. Start backup mode in the phone app; it may only read "
               "photos and videos.",
               short="Wi-Fi: phone app (no debugging)"),
    Connection("hotspot", "Wi-Fi directly to this computer (no router)",
               "10–30 MB/s", (10, 30),
               "The computer opens its own Wi-Fi network (Linux), the phone joins it. Then Wireless "
               "debugging or the phone app as above.",
               short="Wi-Fi directly to this computer"),
)
CONNECTIONS_BY_KEY = {c.key: c for c in CONNECTIONS}
USB_DEBUGGING_MODES = ("adb_app", "adb_manual")


# --------------------------------------------------------------------------- brand guides

_PLUG_IN = ("Connect the phone to this computer with a USB cable and unlock it. Tap “Allow” in "
            "the question “Allow USB debugging?” and tick “Always allow from this computer”.")


@dataclass(frozen=True)
class Guide:
    brand: str
    developer: list      # how to get Developer options
    debugging: list      # where USB debugging is
    extra: list          # brand-specific obstacles


GUIDES = {
    "google": Guide("Google Pixel",
                    ["Open Settings → About phone.",
                     "Tap “Build number” 7 times (at the very bottom) and enter your PIN. "
                     "“You are now a developer” appears."],
                    ["Settings → System → Developer options → switch on “USB debugging”."],
                    []),
    "samsung": Guide("Samsung Galaxy",
                     ["Open Settings → About phone → Software information.",
                      "Tap “Build number” 7 times and enter your PIN."],
                     ["Settings → Developer options (at the very bottom) → switch on “USB debugging”."],
                     ["If “Auto Blocker” is on (Settings → Security and privacy → Auto Blocker), "
                      "switch it off – it blocks USB debugging and installing the phone app."]),
    "xiaomi": Guide("Xiaomi / Redmi / POCO",
                    ["Open Settings → About phone.",
                     "Tap “OS version” (HyperOS) or “MIUI version” 7 times and enter your PIN."],
                    ["Settings → Additional settings → Developer options → switch on "
                     "“USB debugging”."],
                    ["For the phone app also switch on “Install via USB” in the same menu "
                     "(Xiaomi asks you to sign in with a Xiaomi account and may need a SIM card)."]),
    "oneplus": Guide("OnePlus / OPPO / realme",
                     ["Open Settings → About device → Version.",
                      "Tap “Build number” 7 times and enter your PIN."],
                     ["Settings → System (or Additional settings) → Developer options → switch on "
                      "“USB debugging”."],
                     []),
    "motorola": Guide("Motorola",
                      ["Open Settings → About phone.",
                       "Tap “Build number” 7 times and enter your PIN."],
                      ["Settings → System → Developer options → switch on “USB debugging”."],
                      []),
    "huawei": Guide("Huawei / Honor",
                    ["Open Settings → About phone.",
                     "Tap “Build number” 7 times and enter your PIN."],
                    ["Settings → System & updates → Developer options → switch on “USB debugging”."],
                    ["Also switch on “Allow ADB debugging in charge only mode” if the phone is "
                     "not found."]),
    "sony": Guide("Sony Xperia",
                  ["Open Settings → About phone.",
                   "Tap “Build number” 7 times and enter your PIN."],
                  ["Settings → System → Developer options → switch on “USB debugging”."],
                  []),
    "nothing": Guide("Nothing",
                     ["Open Settings → About phone → Software info.",
                      "Tap “Build number” 7 times and enter your PIN."],
                     ["Settings → System → Developer options → switch on “USB debugging”."],
                     []),
    "other": Guide("Other phone",
                   ["Open Settings → About phone (sometimes → Software information).",
                    "Find “Build number” and tap it 7 times, then enter your PIN."],
                   ["Developer options are now in Settings → System (or at the bottom of "
                    "Settings) → switch on “USB debugging”."],
                   ["The names differ between phones – if you cannot find them, use "
                    "“Search the web for this phone”."]),
}

# words in a manufacturer / model name → guide
_BRAND_WORDS = (
    ("google", ("google", "pixel")),
    ("samsung", ("samsung", "galaxy", "sm-")),
    ("xiaomi", ("xiaomi", "redmi", "poco", "mi ")),
    ("oneplus", ("oneplus", "oppo", "realme")),
    ("motorola", ("motorola", "moto")),
    ("huawei", ("huawei", "honor")),
    ("sony", ("sony", "xperia")),
    ("nothing", ("nothing",)),
)


def brand_key(name):
    """Guide key for a manufacturer / model text ('other' if unknown)."""
    low = f" {(name or '').lower()} "
    for key, words in _BRAND_WORDS:
        if any(w in low for w in words):
            return key
    return "other"


def guide_for(name):
    return GUIDES[brand_key(name)]


def guide_steps(guide, with_app=True):
    """All steps as a list of strings."""
    steps = list(guide.developer) + list(guide.debugging) + [_PLUG_IN] + list(guide.extra)
    if with_app:
        steps.append("This program then installs the small phone app “Fast Media Backup” once and "
                     "gives it the right to switch USB debugging on and off. From then on: open the "
                     "app, tap “Allow backup over cable”, plug in – after the backup the computer "
                     "switches USB debugging off again.")
    return steps


def search_url(model):
    """A web search for how to switch on USB debugging on this phone."""
    q = f"enable USB debugging {model}".strip() if model else "enable USB debugging Android"
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(q)


# --------------------------------------------------------------------------- phone on the cable

# USB vendor IDs of phone makers (the phone shows up with one of these even without debugging)
PHONE_VENDORS = {
    "18d1": "Google", "04e8": "Samsung", "2717": "Xiaomi", "22b8": "Motorola", "2a70": "OnePlus",
    "22d9": "OPPO", "12d1": "Huawei", "339b": "Honor", "0fce": "Sony",
    "2d95": "vivo", "1004": "LG", "0bb4": "HTC", "19d2": "ZTE", "17ef": "Lenovo", "0e8d": "MediaTek",
    "05c6": "Qualcomm", "2ae5": "Fairphone",
}


def _read(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _linux_usb_phones(sysfs="/sys/bus/usb/devices"):
    out = []
    for dev in sorted(Path(sysfs).glob("*")):
        vendor = _read(dev / "idVendor").lower()
        if vendor not in PHONE_VENDORS:
            continue
        maker = _read(dev / "manufacturer") or PHONE_VENDORS[vendor]
        product = _read(dev / "product")
        if product and re.fullmatch(r"(?i)[a-z]+[ _-]?(android|mtp|adb)( device)?", product):
            # Samsung & co. only say "SAMSUNG_Android" over the cable - no model name
            out.append(f"{PHONE_VENDORS[vendor]} phone")
        elif product:
            out.append(product if product.lower().startswith(maker.lower().split()[0])
                       else f"{maker} {product}")
    return out


def _windows_usb_phones():
    cmd = ["powershell", "-NoProfile", "-Command",
           "Get-PnpDevice -Class WPD -PresentOnly | Select-Object -ExpandProperty FriendlyName"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    names = [ln.strip() for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    # drives / cameras also appear as WPD: keep what looks like a phone
    return [n for n in names if not re.fullmatch(r"[A-Z]:\\?|.*\b(USB|Disk|Drive)\b.*", n)]


def detect_usb_phone():
    """Model name of a phone on the USB cable ('' if none) - works without USB debugging."""
    try:
        found = _windows_usb_phones() if sys.platform.startswith("win") else _linux_usb_phones()
    except Exception:  # noqa: BLE001 - only a hint for the guide
        found = []
    return found[0] if found else ""


# --------------------------------------------------------------------------- fastest connection
# The program always uses the fastest connection it can find (user request 2026-11-04); the user
# no longer chooses one. Order: USB cable with USB debugging > Wi-Fi (phone app / Wireless
# debugging). File transfer (MTP) only on request ("Connect phone"): slower and no phone check.

def source_key(src):
    """Row of CONNECTIONS for a connected source (for the overview and the status line)."""
    kind = type(src).__name__
    if kind == "AdbSource":
        if getattr(src, "wireless", False):
            return "wifi_adb"
        return "adb_app" if getattr(src, "link", None) is not None else "adb_manual"
    if kind == "CompanionSource":
        return "app_wifi"
    return "mtp"


def describe_probe(p):
    """p: dict from the GUI's probe (usb_phone, usb_mbit, adb_usb, adb_unauthorized, adb_wifi,
    app_wifi, ble). Returns (best key or None, [(title, available, text)], advice)."""
    usb3 = (p.get("usb_mbit") or 0) >= 5000
    cable_speed = "about 25–50 MB/s" if usb3 or not p.get("usb_mbit") else "about 20–30 MB/s (USB 2)"
    rows = []
    if p.get("adb_usb"):
        rows.append(("USB cable + USB debugging", True, f"{p['adb_usb']} – {cable_speed}"))
    elif p.get("adb_unauthorized"):
        rows.append(("USB cable + USB debugging", False, "phone found – unlock it and tap “Allow” "
                     "in “Allow USB debugging?”"))
    elif p.get("usb_phone"):
        rows.append(("USB cable + USB debugging", False,
                     f"{p['usb_phone']} is on the cable, USB debugging is off – tap “Allow backup "
                     "over cable” in the phone app (or switch on USB debugging)"))
    else:
        rows.append(("USB cable + USB debugging", False, "no phone on the cable"))
    rows.append(("Wi-Fi: phone app", bool(p.get("app_wifi")),
                 f"{p['app_wifi']} – about 3–30 MB/s" if p.get("app_wifi") else
                 "no phone app in backup mode found in this Wi-Fi"))
    rows.append(("Wi-Fi: Wireless debugging", bool(p.get("adb_wifi")),
                 f"{p['adb_wifi']} – about 3–30 MB/s" if p.get("adb_wifi") else
                 "no paired phone with Wireless debugging found"))
    if p.get("ble") and not p.get("app_wifi"):
        rows.append(("Bluetooth (only to find the phone)", False,
                     f"{p['ble']} is nearby but not reachable over Wi-Fi – connect it to the same "
                     "Wi-Fi or use the cable"))
    best = ("adb_app" if p.get("adb_usb") else "app_wifi" if p.get("app_wifi")
            else "wifi_adb" if p.get("adb_wifi") else None)
    if best == "adb_app":
        advice = ("Fastest possible connection: USB cable with USB debugging."
                  + ("" if usb3 or not p.get("usb_mbit") else
                     " The cable runs at USB 2 speed only – a USB 3 cable and port are about 2× faster."))
    elif best:
        advice = ("Wi-Fi works, but the cable is about 2–5× faster: plug the phone in and tap "
                  "“Allow backup over cable” in the phone app.")
        if p.get("usb_phone"):
            advice = (f"The {p['usb_phone']} is already on the cable – tap “Allow backup over cable” "
                      "in the phone app (or switch on USB debugging) for the fastest connection.")
    else:
        advice = ("No phone found. Fastest: plug the phone in with a USB cable and tap “Allow backup "
                  "over cable” in the phone app (first time: switch on USB debugging by hand).")
    return best, rows, advice
