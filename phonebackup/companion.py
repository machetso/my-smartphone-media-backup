"""The phone app ("My Media Backup" companion): backups without ADB.

The phone app only has Android's permission to READ photos and videos. It runs a small TLS server
while "backup mode" is on; this module talks to it:

* CompanionSource  - a source like AdbSource (list, SHA-256 on the phone, stream files).
* SetupServer      - small HTTP server on the computer: the QR code opens its page, which offers the
                     app (APK) for download and the "Connect app" link that starts the pairing.
* Pairing          - the phone sends its certificate fingerprint; both show the same 6-digit code;
                     after the user confirms, the computer claims a secret over TLS with the
                     fingerprint pinned. Afterwards every request carries that secret.
"""

import asyncio
import hashlib
import hmac
import html
import http.client
import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config
from .i18n import tr, N_
from .copier import CHUNK
from .sources import SourceFile, _dedupe, _run

SERVICE_TYPE = "_phonebkp._tcp"
APP_PACKAGE = "io.github.machetso.mediabackup"
APP_VERSION_CODE = 8          # versionCode of the bundled assets/companion/MediaBackup.apk
APP_VERSION_NAME = "0.5.0"    # its versionName (shown before installing)
APP_NAME = "My Media Backup"
DEFAULT_PORT = 47823
SETUP_PORT = 47824


# headings in install_question's details – the GUI shows them in bold (match tr(heading))
INSTALL_HEADINGS = (N_("What exactly happens now:"), N_("What the app does:"),
                    N_("What it cannot do:"), N_("Remove it at any time"))


def install_question(state, phone, serial, installed_version, apk_size):
    """(title, text, details) shown BEFORE the phone app is installed / updated / given its right
    over the cable – the user decides every time (user request 2026-11-05). In the interface
    language; the headings of INSTALL_HEADINGS appear in `details` as tr(heading)."""
    from html import escape
    mb = tr("%.1f MB", apk_size / 1e6)
    who = tr("%s (serial number %s), connected by USB cable",
             f"<b>{escape(phone)}</b>", escape(serial))
    app = f"<b>“{APP_NAME}”</b>"
    if state == "outdated":
        title = tr("Update the app on the phone?")
        head = tr("This program wants to <b>update</b> the app %s on %s – from "
                  "version %s to %s.", app, who, escape(installed_version or tr("older")),
                  f"<b>{APP_VERSION_NAME}</b>")
        why = tr("The version on the phone is older than the one included in this program. The "
                 "newer version is needed so that phone and computer understand each other and all "
                 "safety switch-offs work.")
    elif state == "no-permission":
        title = tr("Give the app on the phone a right?")
        head = tr("The app %s is already on %s, but it may not switch USB "
                  "debugging yet. This program wants to install version %s "
                  "over it and give it that right.", app, who, f"<b>{APP_VERSION_NAME}</b>")
        why = tr("So that you do not need the Developer options any more: the app switches USB "
                 "debugging on only for a backup, and it is switched off again afterwards.")
    else:
        title = tr("Install an app on the phone?")
        head = tr("This program wants to <b>install</b> the app %s (version "
                  "%s) on %s.", app, APP_VERSION_NAME, who)
        why = tr("So that you do not need the Developer options any more: the app switches USB "
                 "debugging on only for a backup, and it is switched off again afterwards. It also "
                 "lets you back up over Wi-Fi without USB debugging.")
    text = f"{head}<br><br><b>{tr('Why:')}</b> {why}"
    happens, does, cannot, remove = (tr(h) for h in INSTALL_HEADINGS)
    details = (
        happens + "\n"
        + tr("1. The file %s (%s) is installed on the phone (adb install). It is part of "
             "this program – nothing is downloaded from the internet.", "MediaBackup.apk", mb) + "\n"
        + tr("2. The app gets the special right “%s” (pm grant). It is needed to "
             "switch USB debugging on and off and can only be given over the cable.",
             "WRITE_SECURE_SETTINGS") + "\n"
        + tr("3. The app is opened on the phone; the first time you pair it with this computer (tap "
             "“Pair” on the phone).") + "\n\n"
        + does + " "
        + tr("it switches USB debugging on only when you tap “Allow backup over "
             "cable”, and off again after the backup – automatically after 5 minutes without a backup, "
             "2 minutes without contact to the computer, and after a restart. It reads photos and "
             "videos only after you allow it on the phone, and sends them only to the paired computer "
             "in your own Wi-Fi or over the cable (encrypted).") + "\n"
        + cannot + " "
        + tr("delete or change photos, read other files, contacts or messages; it "
             "contacts no server on the internet, has no ads and no tracking.") + "\n\n"
        + tr("%s on the phone: Settings → Apps → %s → Uninstall.", remove, APP_NAME) + "\n\n"
        + tr("Nothing is installed if you choose “%s” – the backup still works with USB debugging "
             "switched on by hand.", tr("Not now")))
    return title, text, details


class CompanionError(Exception):
    """status: the phone's HTTP status if it answered with an error (compare that, never the
    message - it is in the interface language)."""

    def __init__(self, message="", status=None):
        super().__init__(message)
        self.status = status


# =========================================================================== helpers

def apk_path():
    """The phone app shipped with this program (assets/companion/MediaBackup.apk)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    p = base / "assets" / "companion" / "MediaBackup.apk"
    return p if p.is_file() else None


def pairing_code(token, fingerprint):
    """Same as Identity.pairingCode on the phone."""
    d = hashlib.sha256(f"{token}:{fingerprint}".encode()).digest()
    return "%06d" % (int.from_bytes(d[:4], "big") % 1_000_000)


def pc_identity(cfg):
    if not cfg.get("pc_id"):
        cfg["pc_id"] = str(uuid.uuid4())
        config.save(cfg)
    return cfg["pc_id"], socket.gethostname() or "Computer"


def local_ips():
    """IPv4 addresses of this computer that a phone in the local network can reach, best first."""
    ips = []
    try:   # the address used for the default route (no packet is sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    if not sys.platform.startswith("win"):
        try:
            out = _run(["ip", "-4", "-o", "addr", "show"], timeout=5).stdout.decode()
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[2] == "inet":
                    ips.append(parts[3].split("/")[0])
        except (OSError, subprocess.SubprocessError):
            pass

    def bad(ip):
        return (ip.startswith("127.") or ip.startswith("169.254.") or ip.startswith("192.168.122.")
                or ip.startswith("172.17.") or ip.startswith("100."))   # libvirt, docker, tailscale

    seen, res = set(), []
    for ip in ips:
        if ip not in seen and not bad(ip):
            seen.add(ip)
            res.append(ip)
    return res


def phones(cfg):
    return list(cfg.get("companion_phones", []))


def save_phone(cfg, entry):
    lst = [p for p in phones(cfg) if p.get("phone_id") != entry["phone_id"]] + [entry]
    cfg["companion_phones"] = lst
    config.save(cfg)


def forget_phone(cfg, phone_id):
    cfg["companion_phones"] = [p for p in phones(cfg) if p.get("phone_id") != phone_id]
    config.save(cfg)


# =========================================================================== anonymous announcement
# Same format as Announce.kt: per paired computer a 6-byte token HMAC-SHA256(secret,
# "fmb-announce:<window>") that changes every 10 minutes - only whoever knows the secret
# recognises the phone. Wi-Fi: mDNS TXT "t" (hex tokens joined by "."). Bluetooth LE (ONLY to find
# the phone): manufacturer data 0xFFFF "FB" 1 + per computer token(6) + IPv4(4)+port(2) XOR mask.

WINDOW_S = 600
BLE_COMPANY = 0xFFFF


def window(now=None):
    return int((time.time() if now is None else now) // WINDOW_S)


def _hmac(secret, msg):
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()


def announce_token(secret, w):
    return _hmac(secret, f"fmb-announce:{w}")[:6]


def _windows(now=None):
    w = window(now)
    return (w, w - 1, w + 1)          # clocks of phone and computer may differ a little


def match_token(entries, tokens, now=None):
    """The paired phone whose current token is among `tokens` (bytes), or None."""
    tokens = set(tokens)
    for e in entries:
        if any(announce_token(e["secret"], w) in tokens for w in _windows(now)):
            return e
    return None


def decode_ble(entries, data, now=None):
    """(entry, 'ip:port' or None) from a Bluetooth LE manufacturer-data block, or (None, None)."""
    if len(data) < 3 or data[:3] != b"FB\x01":
        return None, None
    body = data[3:]
    for i in range(0, len(body) - 11, 12):
        tok, enc = body[i:i + 6], body[i + 6:i + 12]
        for e in entries:
            for w in _windows(now):
                if hmac.compare_digest(announce_token(e["secret"], w), tok):
                    mask = _hmac(e["secret"], f"fmb-addr:{w}")[:6]
                    plain = bytes(a ^ b for a, b in zip(enc, mask))
                    ip, port = ".".join(str(b) for b in plain[:4]), int.from_bytes(plain[4:6], "big")
                    return e, (f"{ip}:{port}" if plain[:4] != b"\0\0\0\0" else None)
    return None, None


def ble_available():
    try:
        import bleak  # noqa: F401
        return True
    except ImportError:
        return False


def ble_scan(cfg, seconds=5.0):
    """Bluetooth LE: a paired phone in backup mode nearby → (entry, 'ip:port' or None).
    Only finds the phone - no data is ever transferred over Bluetooth."""
    entries = phones(cfg)
    if not entries or not ble_available():
        return None, None
    from bleak import BleakScanner

    async def scan():
        found = await BleakScanner.discover(timeout=seconds, return_adv=True)
        for _dev, adv in found.values():
            data = (adv.manufacturer_data or {}).get(BLE_COMPANY)
            if data:
                hit = decode_ble(entries, bytes(data))
                if hit[0]:
                    return hit
        return None, None

    try:
        return asyncio.run(scan())
    except Exception:  # noqa: BLE001 - no adapter, Bluetooth off, no permission …
        return None, None


# =========================================================================== discovery

def discover(timeout=6):
    """Phones in backup mode in the local network: list of (txt dict, 'ip:port').
    The phone announces itself anonymously (see above)."""
    res = []
    if shutil_which("avahi-browse"):
        try:
            r = _run(["avahi-browse", "-rpt", SERVICE_TYPE], timeout=timeout + 2)
            for line in r.stdout.decode("utf-8", "replace").splitlines():
                f = line.split(";")
                if len(f) < 10 or f[0] != "=" or ":" in f[7]:
                    continue
                txt = dict(kv.strip('"').split("=", 1) for kv in f[9].split(" ") if "=" in kv)
                addr = f"{f[7]}:{f[8]}"
                if all(a != addr for _t, a in res):
                    res.append((txt, addr))
        except (OSError, subprocess.SubprocessError):
            pass
    return res


def shutil_which(name):
    import shutil
    return shutil.which(name)


def _port_open(address, timeout=1.0):
    host, _, port = address.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def find_phone(cfg):
    """A paired phone that is in backup mode right now: (entry, address) or (None, None)."""
    known = {p["phone_id"]: p for p in phones(cfg)}
    if not known:
        return None, None
    for txt, addr in discover():
        try:
            tokens = [bytes.fromhex(t) for t in txt.get("t", "").split(".") if t]
        except ValueError:
            continue
        hit = match_token(known.values(), tokens)
        if hit:
            return hit, addr
    for p in known.values():          # mDNS may be blocked: try the last address
        addr = p.get("address")
        if addr and _port_open(addr):
            return p, addr
    return None, None


# =========================================================================== TLS client

class Client:
    """HTTPS to the phone with the certificate pinned (self-signed; trust = fingerprint)."""

    def __init__(self, address, fingerprint, secret=None, timeout=120):
        self.host, _, port = address.rpartition(":")
        self.port = int(port)
        self.address = address
        self.fingerprint = fingerprint.lower()
        self.secret = secret
        self.timeout = timeout
        self._local = threading.local()

    def _ctx(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE          # verified below by fingerprint
        return ctx

    def _conn(self, fresh=False):
        c = getattr(self._local, "conn", None)
        if c is None or fresh:
            if c is not None:
                c.close()
            c = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=self._ctx())
            c.connect()
            der = c.sock.getpeercert(binary_form=True)
            if hashlib.sha256(der).hexdigest() != self.fingerprint:
                c.close()
                raise CompanionError(tr("the phone's certificate does not match the paired phone "
                                        "(different phone or manipulated connection) - refused"))
            self._local.conn = c
        return c

    def request(self, method, path, body=None, stream=False):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        if self.secret:
            headers["Authorization"] = "Bearer " + self.secret
        for attempt in (0, 1):
            try:
                c = self._conn(fresh=attempt > 0)
                c.request(method, path, body=data, headers=headers)
                resp = c.getresponse()
                break
            except (OSError, http.client.HTTPException):
                self._local.conn = None
                if attempt:
                    raise
        if stream and resp.status == 200:
            return resp
        raw = resp.read()
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            payload = None
        if not 200 <= resp.status < 300:
            msg = payload.get("error") if isinstance(payload, dict) else raw[:200]
            raise CompanionError(tr("phone answered %d: %s", resp.status, msg), status=resp.status)
        return payload

    def close(self):
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None


# =========================================================================== source

class Prefetcher:
    """Fetches the next files while the current one is written and checked. Over Wi-Fi each file
    costs a round trip, over ADB a new command (~65 ms) - with many small photos that cost more than
    the data. Files are fetched in groups (`fetch_group(list) -> {rel: bytes}`), WORKERS groups at a
    time, only files up to MAX_FILE, at most MAX_BYTES in memory. The data is checked exactly as
    before (SHA-256 of the received bytes = SHA-256 calculated on the phone); a file that could not
    be prefetched is simply streamed directly."""
    WORKERS = 3
    MAX_FILE = 32 * 1024 * 1024
    MAX_BYTES = 128 * 1024 * 1024

    def __init__(self, fetch_group, files, group_files=1, group_bytes=16 * 1024 * 1024,
                 workers=None, max_file=None):
        self.fetch_group = fetch_group
        max_file = max_file or self.MAX_FILE
        groups, cur, cur_bytes = [], [], 0
        for f in files:
            if f.size > max_file:
                continue
            if cur and (len(cur) >= group_files or cur_bytes + f.size > group_bytes):
                groups.append(cur)
                cur, cur_bytes = [], 0
            cur.append(f)
            cur_bytes += f.size
        if cur:
            groups.append(cur)
        self.groups = groups
        self.wanted = {f.rel for g in groups for f in g}
        self.done = {}                    # rel -> bytes | None (failed)
        self.cond = threading.Condition()
        self.in_memory = 0
        self.next = 0
        self.stopped = False
        self.threads = [threading.Thread(target=self._work, daemon=True)
                        for _ in range(workers or self.WORKERS)]
        for t in self.threads:
            t.start()

    def _work(self):
        while True:
            with self.cond:
                while (not self.stopped and self.next < len(self.groups) and self.in_memory > 0
                       and self.in_memory + sum(f.size for f in self.groups[self.next]) > self.MAX_BYTES):
                    self.cond.wait()
                if self.stopped or self.next >= len(self.groups):
                    return
                group = self.groups[self.next]
                self.next += 1
                size = sum(f.size for f in group)
                self.in_memory += size
            try:
                got = self.fetch_group(group) or {}
            except Exception:  # noqa: BLE001 - the caller streams these files directly instead
                got = {}
            with self.cond:
                if self.stopped:
                    return
                for f in group:
                    data = got.get(f.rel)
                    if not isinstance(data, (bytes, bytearray)) or len(data) != f.size:
                        data = None
                        self.in_memory -= f.size
                    self.done[f.rel] = data
                self.cond.notify_all()

    def take(self, sf, timeout=900):
        """The prefetched bytes of sf, or None (not prefetched / failed → stream it directly)."""
        with self.cond:
            if sf.rel not in self.wanted:
                return None
            end = time.monotonic() + timeout
            while sf.rel not in self.done and not self.stopped:
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self.cond.wait(left)
            data = self.done.pop(sf.rel, None)
            self.wanted.discard(sf.rel)
            if data is not None:
                self.in_memory -= sf.size
                self.cond.notify_all()
            return data

    def stop(self):
        with self.cond:
            self.stopped = True
            self.done.clear()
            self.cond.notify_all()


class CompanionSource:
    supports_phone_hash = True
    kind = N_("Phone app (Wi-Fi)")       # stays English (data); shown with tr(src.kind)

    def __init__(self, entry, address):
        self.entry = entry
        self.client = Client(address, entry["fingerprint"], entry["secret"], timeout=900)
        info = self.client.request("GET", "/info")
        self.manufacturer = info.get("manufacturer", "")
        self.device_name = info.get("model", "") or entry.get("name", "Phone")
        self.android = info.get("android", "")
        self.app_version = info.get("app_version", "")
        self.full_access = bool(info.get("full_access", True))
        self.fallback_reason = None
        self.address = address
        self._prefetch = None

    @property
    def description(self):
        return tr("Phone app '%s' %s over Wi-Fi (%s, TLS, read-only), Android %s",
                  APP_NAME, self.app_version, self.address, self.android)

    def is_connected(self):
        try:
            self.client.request("GET", "/info")
            return True
        except (OSError, CompanionError, http.client.HTTPException):
            return False

    def folder_exists(self, rel):
        q = urllib.parse.urlencode({"path": rel.strip("/")})
        return bool(self.client.request("GET", "/exists?" + q).get("exists"))

    def list_subfolders(self, rel):
        q = urllib.parse.urlencode({"path": rel.strip("/")})
        return sorted(self.client.request("GET", "/folders?" + q) or [])

    def list_files(self, folders):
        files, missing, wanted = [], [], []
        for rel in folders:
            rel = rel.strip("/")
            (wanted if self.folder_exists(rel) else missing).append(rel)
        if wanted:
            for it in self.client.request("POST", "/list", {"folders": wanted}) or []:
                files.append(SourceFile(it["rel"], int(it["size"]), int(it["mtime"])))
        return _dedupe(files), missing

    def phone_hashes(self, rels):
        if not rels:
            return {}
        return dict(self.client.request("POST", "/hashes", {"rels": list(rels)}) or {})

    def prefetch(self, files):
        """Called by perform_backup with the files to copy, in order."""
        if self._prefetch is not None:
            self._prefetch.stop()
        self._prefetch = Prefetcher(lambda g: {sf.rel: self._fetch_whole(sf) for sf in g}, files)

    def _fetch_whole(self, sf):
        data = bytearray()
        for b in self._stream(sf):
            data += b
        if len(data) != sf.size:
            raise CompanionError(tr("incomplete: %s", sf.rel))
        return bytes(data)

    def open_stream(self, sf):
        data = self._prefetch.take(sf) if self._prefetch is not None else None
        if data is None:
            yield from self._stream(sf)
            return
        for i in range(0, len(data), CHUNK):
            yield data[i:i + CHUNK]

    def _stream(self, sf):
        q = urllib.parse.urlencode({"rel": sf.rel})
        resp = self.client.request("GET", "/file?" + q, stream=True)
        if not hasattr(resp, "read"):
            raise CompanionError(tr("could not read %s", sf.rel))
        ok = False
        try:
            while True:
                b = resp.read(CHUNK)
                if not b:
                    break
                yield b
            ok = True
        finally:
            if not ok:              # interrupted mid-file: the connection cannot be reused
                self.client.close()

    def finish(self):
        """Tell the phone the backup is done: it switches backup mode off."""
        try:
            self.client.request("POST", "/done", {})
        except (OSError, CompanionError, http.client.HTTPException):
            pass

    def close(self):
        if self._prefetch is not None:
            self._prefetch.stop()
            self._prefetch = None
        self.client.close()


# =========================================================================== guard + cable

class AppGuard:
    """Tells the phone app that a backup runs (it switches the other connection off), says
    "still here" every 30 s (no signal for 2 minutes → the app switches debugging off) and ends it.
    channel: "usb" | "wifi" | "wifi-adb"."""
    INTERVAL = 30

    def __init__(self, client, channel):
        self.client, self.channel = client, channel
        self._stop = threading.Event()
        self._thread = None

    def _call(self, path, body=None):
        try:
            return self.client.request("POST", path, body or {})
        except (OSError, CompanionError, http.client.HTTPException):
            return None

    def start(self):
        res = self._call("/guard/start", {"channel": self.channel})
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()
        return res

    def _beat(self):
        while not self._stop.wait(self.INTERVAL):
            self._call("/guard/alive")

    def end(self, switch_off=True):
        self._stop.set()
        self._call("/guard/end", {"off": bool(switch_off)})


class CableLink:
    """The phone app reached through the USB cable (adb forward to its server). The phone is
    verified by the key pinned at pairing - a phone that only copies name or serial is refused."""

    def __init__(self, adb_source, entry, port):
        self.src, self.entry, self.port = adb_source, entry, port
        self.client = Client(f"127.0.0.1:{port}", entry["fingerprint"], entry["secret"], timeout=30)

    def close(self):
        self.client.close()
        self.src.unforward(self.port)


def link_over_cable(adb_source, cfg):
    """Verify the phone on the cable: (CableLink, None) or (None, reason).
    Needs the phone app in backup mode (it runs after 'Allow backup over cable')."""
    entries = phones(cfg)
    if not entries:
        return None, tr("no phone paired with the phone app yet")
    port = adb_source.forward(DEFAULT_PORT)
    if not port:
        return None, tr("port forwarding over the cable failed")
    for e in entries:                 # the secret is only sent after the certificate matched
        c = Client(f"127.0.0.1:{port}", e["fingerprint"], e["secret"], timeout=10)
        try:
            c.request("GET", "/info")
        except (OSError, CompanionError, http.client.HTTPException):
            continue
        finally:
            c.close()
        return CableLink(adb_source, e, port), None
    adb_source.unforward(port)
    return None, tr("the phone app is not in backup mode, or this phone is not paired")


def fingerprint_over_cable(adb_source):
    """Certificate fingerprint of the phone app on the cable (for pairing): (port, fp) or (None, None)."""
    port = adb_source.forward(DEFAULT_PORT)
    if not port:
        return None, None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
            with ctx.wrap_socket(raw) as tls:
                return port, hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
    except (OSError, ssl.SSLError):
        adb_source.unforward(port)
        return None, None


def pair_over_cable(adb_source, cfg, wait_s=180, cancel=None, on_code=None):
    """Pair with the phone app over the USB cable; the user compares a 6-digit code and taps
    "Pair" on the phone. The code comes from a random value of this computer and the phone key
    this computer just pinned: another app on the phone that put itself in between (its own key)
    shows a different code (security review 2026-11-06). Returns the new phone entry."""
    port, fp = fingerprint_over_cable(adb_source)
    if not port:
        raise CompanionError(tr("the phone app does not answer over the cable (is it open?)"))
    pc_id, pc_name = pc_identity(cfg)
    nonce = secrets.token_hex(16)
    code = pairing_code(nonce, fp)
    c = Client(f"127.0.0.1:{port}", fp, timeout=20)
    try:
        c.request("POST", "/usbpair", {"pc_id": pc_id, "pc_name": pc_name, "nonce": nonce})
        if on_code:
            on_code(code)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                raise CompanionError(tr("cancelled"))
            res = c.request("POST", "/usbpair/claim", {"pc_id": pc_id})
            if isinstance(res, dict) and res.get("secret"):
                entry = {"phone_id": res.get("phone_id"), "name": adb_source.device_name,
                         "fingerprint": fp, "secret": res["secret"], "address": "",
                         "paired": time.strftime("%Y-%m-%d %H:%M"), "via": "cable"}
                save_phone(cfg, entry)
                return entry
            time.sleep(1)
        raise CompanionError(tr("not confirmed on the phone in time"))
    finally:
        c.close()
        adb_source.unforward(port)


def connect_companion(cfg):
    """(CompanionSource, None) or (None, reason)."""
    entry, addr = find_phone(cfg)
    if not entry:
        return None, tr("no paired phone with the app in backup mode was found")
    try:
        src = CompanionSource(entry, addr)
    except (OSError, CompanionError, http.client.HTTPException) as e:
        return None, tr("phone app error: %s", e)
    if entry.get("address") != addr:
        entry["address"] = addr
        save_phone(cfg, entry)
    return src, None


# =========================================================================== setup / pairing server

@dataclass
class PairRequest:
    token: str
    fingerprint: str
    address: str            # ip:port of the phone's TLS server
    phone_id: str
    model: str
    manufacturer: str
    android: str
    code: str = ""
    done: threading.Event = field(default_factory=threading.Event)


class SetupServer:
    """Serves the setup page + APK and receives the phone's pairing request.

    on_pair_request(PairRequest) is called from a server thread.
    """

    def __init__(self, cfg, on_pair_request, port=SETUP_PORT):
        self.cfg = cfg
        self.on_pair_request = on_pair_request
        self.token = secrets.token_urlsafe(18)
        self.pc_id, self.pc_name = pc_identity(cfg)
        self.apk = apk_path()
        self.httpd = None
        self.port = 0
        self._preferred = port
        self.ip = (local_ips() or ["127.0.0.1"])[0]
        self._paired = False             # the first pairing request wins – no later replacement
        self._lock = threading.Lock()

    # -- urls
    @property
    def base(self):
        return f"http://{self.ip}:{self.port}"

    @property
    def page_url(self):
        return f"{self.base}/s/{self.token}"

    def intent_url(self):
        q = urllib.parse.urlencode({"pc": f"{self.ip}:{self.port}", "t": self.token,
                                    "id": self.pc_id, "name": self.pc_name})
        fallback = urllib.parse.quote(self.page_url + "#install", safe="")
        return (f"intent://pair?{q}#Intent;scheme=phonebackup;package={APP_PACKAGE};"
                f"S.browser_fallback_url={fallback};end")

    def start(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 10                 # silent / slow connections are dropped

            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urllib.parse.urlparse(self.path).path
                prefix = f"/s/{server.token}"
                if path == prefix:
                    return self._send(200, server.page().encode())
                if path == prefix + "/MediaBackup.apk" and server.apk:
                    data = server.apk.read_bytes()
                    return self._send(200, data, "application/vnd.android.package-archive",
                                      {"Content-Disposition": 'attachment; filename="MediaBackup.apk"'})
                self._send(404, b"Not found")

            def do_POST(self):
                if urllib.parse.urlparse(self.path).path != "/pair":
                    return self._send(404, b"Not found")
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    if not 0 < n <= 10000:                  # also no negative length (= read all)
                        raise ValueError("bad length")
                    d = json.loads(self.rfile.read(n))
                    if not secrets.compare_digest(str(d.get("token", "")), server.token):
                        return self._send(403, b'{"error":"wrong token"}', "application/json")
                    fp = str(d["fingerprint"]).lower()
                    if len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
                        raise ValueError("bad fingerprint")
                    req = PairRequest(server.token, fp, f"{self.client_address[0]}:{int(d['port'])}",
                                      str(d.get("phone_id", "")), str(d.get("model", "")),
                                      str(d.get("manufacturer", "")), str(d.get("android", "")))
                    req.code = pairing_code(server.token, fp)
                except (ValueError, KeyError, TypeError):
                    return self._send(400, b'{"error":"bad request"}', "application/json")
                with server._lock:
                    if server._paired:     # a second phone/attacker must not replace the shown code
                        return self._send(409, b'{"error":"pairing already requested"}',
                                          "application/json")
                    server._paired = True
                server.on_pair_request(req)
                self._send(200, b'{"ok":true}', "application/json")

        last = None
        for port in (self._preferred, 0):
            try:
                # only on the address shown in the QR code, not on every network interface
                self.httpd = ThreadingHTTPServer((self.ip, port), Handler)
                break
            except OSError as e:
                last = e
        if self.httpd is None:
            raise CompanionError(tr("could not open the setup server: %s", last))
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def page(self):
        """The setup page shown in the PHONE's browser - in the interface language of this
        computer (the user reads it on the phone next to the program)."""
        from .i18n import current
        e = html.escape
        lang = current()
        apk_link = (f"<a class='btn' href='/s/{self.token}/MediaBackup.apk'>{e(tr('1. Download the app'))}</a>"
                    if self.apk else f"<p class='warn'>{e(tr('The app file is missing in this program.'))}</p>")
        return f"""<!doctype html><html lang="{e(lang.locale)}" dir="{'rtl' if lang.rtl else 'ltr'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(tr("%s – set up", APP_NAME))}</title>
<style>
body{{font-family:sans-serif;margin:0;padding:20px;max-width:560px;background:#fff;color:#222}}
@media (prefers-color-scheme:dark){{body{{background:#121212;color:#eee}}}}
.btn{{display:block;text-align:center;padding:16px;margin:14px 0;border-radius:12px;background:#1f6feb;
color:#fff;text-decoration:none;font-size:18px;font-weight:600}}
.btn2{{background:#1f8a4c}} small{{color:#888}} .warn{{color:#c62828}}
</style></head><body>
<h2>{tr("%s for %s", e(APP_NAME), e(self.pc_name))}</h2>
<p>{tr("This app lets the computer back up your photos and videos. It can only <b>read</b> photos and "
       "videos – nothing else, and it cannot delete or change anything.")}</p>
{apk_link}
<small>{tr("Then open the downloaded file and tap <i>Install</i>. Android may ask once to allow "
           "installing apps from your browser.")}</small>
<a class="btn btn2" href="{e(self.intent_url())}">{e(tr("2. Connect app with this computer"))}</a>
<small>{tr("Already installed? Just tap step 2. The phone and the computer then show the same 6-digit "
           "code – confirm it on the phone AND on the computer.")}</small>
</body></html>"""

    def claim(self, req, cancel=None, wait=180):
        """After the user confirmed the code: fetch the secret from the phone over pinned TLS.
        The phone hands it out only after the code was ALSO confirmed on the phone (answer 409
        "wait" until then) – so no app or web link on the phone can pair by itself."""
        deadline = time.monotonic() + wait
        while True:
            c = Client(req.address, req.fingerprint, timeout=20)
            try:
                res = c.request("POST", "/claim", {"token": req.token})
                break
            except CompanionError as e:
                wait_more = e.status == 409       # the phone: "wait" (not confirmed there yet)
                if not wait_more or time.monotonic() > deadline or (cancel and cancel.is_set()):
                    if wait_more:
                        raise CompanionError(tr("the pairing was not confirmed on the phone")) from e
                    raise
            finally:
                c.close()
            time.sleep(1.5)
        if not isinstance(res, dict) or not res.get("secret"):
            raise CompanionError("the phone did not hand out a key")
        entry = {"phone_id": res.get("phone_id") or req.phone_id,
                 "name": f"{req.manufacturer} {req.model}".strip(),
                 "fingerprint": req.fingerprint, "secret": res["secret"], "address": req.address,
                 "paired": time.strftime("%Y-%m-%d %H:%M")}
        save_phone(self.cfg, entry)
        return entry
