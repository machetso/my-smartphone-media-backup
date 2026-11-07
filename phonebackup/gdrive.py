"""Google Drive as second storage: MIRROR of a backup (user decision 2026-11-05).

Layout on Google Drive (same as on the HDD):
  My Drive/My Smartphone Media Backup/<Phone - Owner>/2026/01.January-photos/...
                                                       /Google Drive export reports/...

- Each export uploads only files that are not on Google Drive yet. Nothing on Google Drive is
  ever deleted or overwritten; a file with the same path but other content is reported.
- Every upload is checked: Google's own SHA-256 of the stored file must match the SHA-256 of the
  bytes read from the backup (and the SHA-256 recorded when the file was backed up).
- Rights: only "drive.file" – the app sees ONLY the files it uploaded itself, nothing else in the
  Drive. Login: OAuth for installed apps (browser, loopback address, PKCE). The refresh token is
  stored in the settings folder, readable only by the user.

Standard library only (urllib), no Google client library needed.
"""

import base64
import html
import hashlib
import json
import os
import secrets
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from . import APP_NAME, config, ui
from .copier import Cancelled
from .i18n import N_, tr, trp
from .export import _category, scan_backup
from .index import open_readonly_lookup
from .report import unique_basename, write_reports

# The app's own Google key ("OAuth client, type Desktop app"). For installed apps Google does not
# treat the secret as confidential (it ships in every copy), but it is kept OUT of the public git
# repository: it lives in phonebackup/_gkey.py (git-ignored), written by tools/set_google_key.py
# locally and by the release workflow from the GitHub secrets GOOGLE_CLIENT_ID/_SECRET.
# The settings can override both (cfg gdrive_client_id / gdrive_client_secret).
try:
    from ._gkey import CLIENT_ID, CLIENT_SECRET
except ImportError:
    CLIENT_ID = ""
    CLIENT_SECRET = ""

SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
ROOT_NAME = "My Smartphone Media Backup"
REPORTS_FOLDER = "Google Drive export reports"
CHUNK = 8 * 1024 * 1024            # resumable upload chunk (multiple of 256 KiB)
DOWNLOAD_CHUNK = 16 * 1024 * 1024  # restore: bytes per download request
UPLOAD_WORKERS = 3                 # files uploaded at the same time (many small photos: much faster)
LOGIN_TIMEOUT = 300
LOCK_PROP = "fsmb_lock"            # appProperties key of the "writing now" marker files
LOCK_BEAT = 120                    # seconds between "still writing" updates of the marker
LOCK_STALE = 15 * 60               # a marker not updated for this long is left over (crash, power cut)


class DriveError(Exception):
    """An error shown to the user: the message is in the chosen language. Code that must react
    to a particular error checks `code` (or the subclass), never the text."""
    code = "error"

    def __init__(self, message="", code=None):
        super().__init__(message)
        if code:
            self.code = code


class DriveOffline(DriveError):
    """No internet (e.g. while this computer runs the Direct Wi-Fi hotspot) - not a real error."""

    def __init__(self, message):
        super().__init__(message, "offline")


class DriveBusy(DriveError):
    """Another computer / window is writing to the same Google Drive backups right now."""

    def __init__(self, message):
        super().__init__(message, "busy")


class NotSignedIn(DriveError):
    code = "not_signed_in"


class DriveFull(DriveError):
    """Google Drive has no space left (an upload was refused)."""
    code = "full"

    def __init__(self, message=None, code=None):
        super().__init__(message or tr("Google Drive is full."), code)


# run statuses stored in the catalog / returned to the caller stay English (compared in the code);
# they are translated where they are shown (log, report)
STATUS_FULL = N_("STOPPED - Google Drive is full")
STATUS_SIGNIN_LOST = N_("STOPPED - Google sign-in is no longer valid")
_STATUSES = (N_("COMPLETED"), N_("COMPLETED WITH ERRORS"), N_("CANCELLED by user"))


def token_path() -> Path:
    return config.config_path().parent / "gdrive_token.json"


def reports_dir(set_name) -> Path:
    from .adbdownload import data_dir
    return Path(data_dir()) / "gdrive-reports" / set_name


def client_credentials(cfg):
    cid = (cfg.get("gdrive_client_id") or CLIENT_ID).strip()
    sec = (cfg.get("gdrive_client_secret") or CLIENT_SECRET).strip()
    return cid, sec


def is_configured(cfg):
    return bool(client_credentials(cfg)[0])


def _rfc3339(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _q(s):
    """Quote a value inside a Drive search query."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


# ---------------------------------------------------------------------------------------- login
def sign_in(cfg, cancel=None, open_browser=webbrowser.open):
    """Browser login. Returns the signed-in account's e-mail address."""
    cid, sec = client_credentials(cfg)
    if not cid:
        raise DriveError(tr("Google Drive is not set up in this version (no Google key)."),
                         "not_configured")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        timeout = 5             # a silent local connection must not block the sign-in

        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if qs.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                return
            result["code"] = qs.get("code", [""])[0]
            result["error"] = qs.get("error", [""])[0]
            ok = bool(result["code"])
            from .i18n import current
            lang = current()
            msg = (tr("Signed in – you can close this tab and go back to the app.")
                   if ok else tr("Sign-in was not completed – you can close this tab."))
            body = (f"<html lang='{html.escape(lang.locale)}' dir='{'rtl' if lang.rtl else 'ltr'}'>"
                    f"<head><meta charset='utf-8'><title>{html.escape(APP_NAME)}</title></head>"
                    f"<body style='font-family:sans-serif;padding:3em'><h2>{html.escape(APP_NAME)}</h2>"
                    f"<p>{html.escape(msg)}</p></body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.timeout = 0.5
    redirect = f"http://127.0.0.1:{srv.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "access_type": "offline", "prompt": "consent select_account"})
    ui.info(tr("Opening Google sign-in in the browser …"))
    open_browser(url)
    deadline = time.monotonic() + LOGIN_TIMEOUT
    try:
        while "code" not in result:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if time.monotonic() > deadline:
                raise DriveError(tr("No sign-in within 5 minutes."), "timeout")
            srv.handle_request()
    finally:
        srv.server_close()
    if not result.get("code"):
        raise DriveError(tr("Google sign-in was not completed (%s).",
                              result.get("error") or tr("cancelled")), "sign_in_incomplete")
    tok = _post_form(TOKEN_URL, {"code": result["code"], "client_id": cid, "client_secret": sec,
                                 "redirect_uri": redirect, "grant_type": "authorization_code",
                                 "code_verifier": verifier})
    if "refresh_token" not in tok:
        raise DriveError(tr("Google did not give a lasting sign-in (no refresh token)."), "no_refresh_token")
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    _save_token(tok)
    acct = Drive(cfg).account()
    tok["email"] = acct.get("email", "")
    _save_token(tok)
    return tok["email"]


def sign_out():
    tok = _load_token()
    if tok:
        try:
            _post_form(REVOKE_URL, {"token": tok.get("refresh_token") or tok.get("access_token", "")})
        except DriveError:
            pass                       # already revoked / offline: the local key is deleted anyway
    try:
        token_path().unlink()
    except FileNotFoundError:
        pass


def signed_in_email():
    tok = _load_token()
    return (tok.get("email") or "?") if tok and tok.get("refresh_token") else None


def _load_token():
    try:
        return json.loads(token_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_token(tok):
    config.write_private(token_path(), json.dumps(tok))


def _post_form(url, fields):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise DriveError(tr("Google answered %s: %s", e.code,
                              e.read()[:300].decode(errors="replace")), "http") from None
    except (urllib.error.URLError, socket.timeout) as e:
        raise DriveOffline(tr("No connection to Google (%s).", e)) from None


# ------------------------------------------------------------------------------------------ API
class Drive:
    """Minimal Drive v3 client. `transport(method, url, headers, body) -> (status, headers, bytes)`
    can be replaced in tests."""

    def __init__(self, cfg, transport=None):
        self.cfg = cfg
        self._writer = None                        # DriveLock while this client writes
        self._writer_depth = 0
        self._tok_lock = threading.Lock()          # parallel uploads share the sign-in
        self._folder_lock = threading.RLock()      # a folder must never be created twice
        self.transport = transport or self._urllib
        self.tok = None if transport else _load_token()
        if not transport and not (self.tok and self.tok.get("refresh_token")):
            raise NotSignedIn(tr("Not signed in to Google Drive."))

    # --- low level
    @staticmethod
    def _urllib(method, url, headers, body):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read()

    def _access(self):
        if self.tok is None:
            return "test"
        with self._tok_lock:
            return self._access_locked()

    def _access_locked(self):
        if time.time() >= self.tok.get("expires_at", 0):
            cid, sec = client_credentials(self.cfg)
            new = _post_form(TOKEN_URL, {"client_id": cid, "client_secret": sec,
                                         "refresh_token": self.tok["refresh_token"],
                                         "grant_type": "refresh_token"})
            if "access_token" not in new:
                raise NotSignedIn(tr("Google sign-in expired – please sign in again."))
            self.tok["access_token"] = new["access_token"]
            self.tok["expires_at"] = time.time() + int(new.get("expires_in", 3600)) - 60
            _save_token(self.tok)
        return self.tok["access_token"]

    def call(self, method, url, params=None, body=None, headers=None, ok=(200,), raw=False, attempts=7):
        if params:
            url += "?" + urllib.parse.urlencode(params)
        h = dict(headers or {})
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            h["Content-Type"] = "application/json; charset=UTF-8"
        delay = 1.0
        last = attempts - 1
        for attempt in range(attempts):
            h["Authorization"] = "Bearer " + self._access()
            try:
                status, rh, data = self.transport(method, url, h, body)
            except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
                status, rh, data = 0, {}, str(e).encode()
            if status == 401 and self.tok is not None and attempt == 0:
                self.tok["expires_at"] = 0              # refresh once
                continue
            if status in ok:
                if raw:
                    return status, rh, data
                return json.loads(data) if data else {}
            retry = status in (0, 429, 500, 502, 503, 504) or (
                status == 403 and b"ateLimitExceeded" in data)
            if not retry or attempt == last:
                if status == 0:                          # never reached Google: no internet
                    raise DriveOffline(tr("No connection to Google (%s).", data[:200].decode(errors="replace")))
                if status == 403 and b"storageQuotaExceeded" in data:
                    raise DriveFull()
                if status == 401:
                    raise NotSignedIn(tr("Google sign-in is no longer valid – please sign in again."))
                raise DriveError(tr("Google Drive error %s: %s", status, data[:300].decode(errors="replace")),
                                 "http")
            time.sleep(delay)
            delay = min(delay * 2, 32)

    # --- account
    def account(self):
        a = self.call("GET", f"{API}/about", {"fields": "user(emailAddress),storageQuota(limit,usage)"},
                      attempts=2)                    # only for display: do not wait a minute offline
        q = a.get("storageQuota", {})
        lim = int(q["limit"]) if q.get("limit") else None          # None = unlimited
        use = int(q.get("usage", 0))
        return {"email": a.get("user", {}).get("emailAddress", ""), "limit": lim, "usage": use,
                "free": None if lim is None else max(lim - use, 0)}

    # --- one writer at a time
    def hold_lock(self, root_id):
        """Only ONE computer/window may change this app's Google Drive folder at a time
        (two exports would overwrite each other's catalog, a clean-up could delete files the
        other one just linked). Re-entrant per Drive client. Raises DriveBusy."""
        if self._writer is None:
            lk = DriveLock(self, root_id)
            lk.acquire()
            self._writer = lk
        self._writer_depth += 1

    def release_lock(self):
        if self._writer_depth == 0:
            return
        self._writer_depth -= 1
        if self._writer_depth == 0 and self._writer is not None:
            lk, self._writer = self._writer, None
            lk.release()

    # --- folders / listing
    def find_or_create_folder(self, name, parent=None, app_key=None):
        q = [f"name = {_q(name)}", f"mimeType = '{FOLDER_MIME}'", "trashed = false",
             f"{_q(parent)} in parents" if parent else "'root' in parents"]
        r = self.call("GET", f"{API}/files", {"q": " and ".join(q), "fields": "files(id)",
                                              "spaces": "drive", "pageSize": 10})
        if r.get("files"):
            return r["files"][0]["id"]
        meta = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent or "root"]}
        if app_key:
            meta["appProperties"] = {"fsmb": app_key}
        return self.call("POST", f"{API}/files", {"fields": "id"}, body=meta)["id"]

    def list_tree(self, top_id):
        """All files below a folder (only what this app created – drive.file).
        Returns ({rel_path: {"id","size","sha256"[,"target"]}}, {rel_folder: id}).
        A shortcut has "target" (the id of the file it points to)."""
        items, token = [], None
        while True:
            p = {"q": "trashed = false", "spaces": "drive", "pageSize": 1000,
                 "fields": "nextPageToken,files(id,name,mimeType,parents,size,sha256Checksum,"
                           "shortcutDetails(targetId))"}
            if token:
                p["pageToken"] = token
            r = self.call("GET", f"{API}/files", p)
            items += r.get("files", [])
            token = r.get("nextPageToken")
            if not token:
                break
        by_id = {f["id"]: f for f in items}

        def rel_of(f):
            parts = [f["name"]]
            seen = set()
            parent = (f.get("parents") or [None])[0]
            while parent and parent != top_id:
                if parent in seen or parent not in by_id:
                    return None                      # not below top_id
                seen.add(parent)
                parts.append(by_id[parent]["name"])
                parent = (by_id[parent].get("parents") or [None])[0]
            return "/".join(reversed(parts)) if parent == top_id else None

        files, folders = {}, {"": top_id}
        for f in items:
            rel = rel_of(f)
            if rel is None:
                continue
            if f["mimeType"] == FOLDER_MIME:
                folders.setdefault(rel, f["id"])
            elif f["mimeType"] == SHORTCUT_MIME:
                if rel not in files:
                    files[rel] = {"id": f["id"], "size": 0, "sha256": "",
                                  "target": (f.get("shortcutDetails") or {}).get("targetId", "")}
            elif rel not in files or "target" in files[rel]:      # a real file wins over a shortcut
                files[rel] = {"id": f["id"], "size": int(f.get("size", 0)),
                              "sha256": f.get("sha256Checksum", "")}
        return files, folders

    def ensure_path(self, folders, rel_folder):
        """Folder id for 'a/b/c' below the set folder, created when missing (cache: folders)."""
        with self._folder_lock:
            if rel_folder in folders:
                return folders[rel_folder]
            parent_rel, _, name = rel_folder.rpartition("/")
            pid = self.ensure_path(folders, parent_rel)
            fid = self.find_or_create_folder(name, pid)
            folders[rel_folder] = fid
            return fid

    # --- upload
    def upload(self, path, parent_id, name, on_bytes=None, cancel=None):
        """Resumable upload. Returns (file id, sha256 of the bytes read, Google's sha256)."""
        st = os.stat(path)
        size = st.st_size
        meta = {"name": name, "parents": [parent_id], "modifiedTime": _rfc3339(st.st_mtime)}
        _, rh, _ = self.call("POST", UPLOAD_API, {"uploadType": "resumable", "fields": "id"},
                             body=meta, headers={"X-Upload-Content-Length": str(size)}, raw=True)
        session = {k.lower(): v for k, v in rh.items()}.get("location")
        if not session:
            raise DriveError(tr("Google Drive did not start the upload."))
        h = hashlib.sha256()
        sent = 0
        result = None
        with open(path, "rb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    self._abort(session)
                    raise Cancelled()
                chunk = f.read(CHUNK)
                end = sent + len(chunk)
                h.update(chunk)
                rng = f"bytes {sent}-{end - 1}/{size}" if chunk else f"bytes */{size}"
                status, rh, data = self.call(
                    "PUT", session, {"fields": "id,size,sha256Checksum"} if end >= size else None,
                    body=chunk, headers={"Content-Range": rng}, ok=(200, 201, 308), raw=True)
                if on_bytes and chunk:
                    on_bytes(len(chunk))
                sent = end
                if status in (200, 201):
                    result = json.loads(data)
                    break
                if not chunk:
                    raise DriveError(tr("Upload incomplete."))
        if sent != size:
            raise DriveError(tr("The file changed while it was uploaded."))
        return result["id"], h.hexdigest(), result.get("sha256Checksum", "")

    def copy(self, file_id, parent_id, name):
        """Server-side copy (nothing is uploaded again). Returns (new id, Google's sha256)."""
        r = self.call("POST", f"{API}/files/{file_id}/copy", {"fields": "id,size,sha256Checksum"},
                      body={"name": name, "parents": [parent_id]})
        return r["id"], r.get("sha256Checksum", "")

    def shortcut(self, target_id, parent_id, name):
        """A shortcut (link, uses no storage) to a file. Returns its id."""
        return self.call("POST", f"{API}/files", {"fields": "id"},
                         body={"name": name, "mimeType": SHORTCUT_MIME, "parents": [parent_id],
                               "shortcutDetails": {"targetId": target_id}})["id"]

    def move(self, file_id, from_parent, to_parent):
        """Move a file into another folder (its id stays, shortcuts to it keep working)."""
        self.call("PATCH", f"{API}/files/{file_id}",
                  {"addParents": to_parent, "removeParents": from_parent, "fields": "id"}, body={})

    def delete(self, file_id):
        """Delete permanently (a folder with everything in it). Only for files this app made."""
        self.call("DELETE", f"{API}/files/{file_id}", ok=(200, 204, 404))

    def download(self, file_id, path, size, on_bytes=None, cancel=None):
        """Download in pieces into `path`. Returns the sha256 of the bytes received."""
        h = hashlib.sha256()
        got = 0
        with open(path, "wb") as f:
            while got < size or size == 0:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                end = min(got + DOWNLOAD_CHUNK, size) - 1
                hdr = {"Range": f"bytes={got}-{end}"} if size else {}
                _, _, data = self.call("GET", f"{API}/files/{file_id}", {"alt": "media"},
                                       headers=hdr, ok=(200, 206), raw=True)
                if not data:
                    break
                f.write(data)
                h.update(data)
                got += len(data)
                if on_bytes:
                    on_bytes(len(data))
                if size == 0:
                    break
            f.flush()
            os.fsync(f.fileno())
        if got != size:
            raise DriveError(tr("Download incomplete (%s of %s bytes).", got, size))
        return h.hexdigest()

    def _abort(self, session):
        try:
            self.transport("DELETE", session, {"Authorization": "Bearer " + self._access()}, None)
        except Exception:  # noqa: BLE001 - best effort
            pass


# --------------------------------------------------------------------------------------- export
class DriveLock:
    """A "writing now" marker file in the app's root folder on Google Drive.

    Drive has no atomic "create if absent", so: create our own marker, then list all markers -
    the oldest live one wins (ties: smaller id); a loser removes its marker again. Markers are
    refreshed every LOCK_BEAT seconds; one older than LOCK_STALE is left over and ignored."""

    def __init__(self, drive, root_id, now=None):
        self.drive, self.root = drive, root_id
        self.now = now or (lambda: time.time())
        self.id = None
        self._stop = threading.Event()
        self._thread = None

    def _markers(self):
        r = self.drive.call("GET", f"{API}/files", {
            "q": f"{_q(self.root)} in parents and trashed = false and "
                 f"appProperties has {{ key='{LOCK_PROP}' and value='1' }}",
            "fields": "files(id,name,createdTime,modifiedTime,appProperties)",
            "spaces": "drive", "pageSize": 100})
        return r.get("files", [])

    @staticmethod
    def _ts(v):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except (AttributeError, ValueError):
            return 0.0

    def acquire(self):
        host = socket.gethostname() or "?"
        meta = {"name": f".writing-{host}-{os.getpid()}", "parents": [self.root],
                "mimeType": "text/plain",
                "appProperties": {LOCK_PROP: "1", "host": host[:60], "pid": str(os.getpid())}}
        self.id = self.drive.call("POST", f"{API}/files", {"fields": "id"}, body=meta)["id"]
        live = []
        for m in self._markers():
            if m["id"] != self.id and self.now() - self._ts(m.get("modifiedTime")) > LOCK_STALE:
                self.drive.delete(m["id"])                       # left over by a crash
                continue
            live.append(m)
        live.sort(key=lambda m: (self._ts(m.get("createdTime")), m["id"]))
        if live and live[0]["id"] != self.id:
            other = (live[0].get("appProperties") or {}).get("host", "?")
            self.drive.delete(self.id)
            self.id = None
            raise DriveBusy(tr("Another computer or window (%s) is writing to the Google Drive backups "
                               "right now. Try again when it has finished.", other))
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()

    def _beat(self):
        while not self._stop.wait(LOCK_BEAT):
            try:
                self.drive.call("PATCH", f"{API}/files/{self.id}", {"fields": "id"},
                                body={"appProperties": {"beat": str(int(self.now()))}})
            except DriveError:
                pass                  # next beat tries again; the job itself reports real errors

    def release(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self.id:
            try:
                self.drive.delete(self.id)
            except DriveError:
                pass                  # becomes stale after LOCK_STALE
            self.id = None


def perform_drive_export(source_parent, cfg, cancel=None, drive=None, report_dir=None):
    """Mirror a backup folder to Google Drive. Returns (status, report paths, verdict)."""
    drive = drive or Drive(cfg)
    root = drive.find_or_create_folder(ROOT_NAME, None, app_key="root")
    drive.hold_lock(root)
    try:
        return _perform_drive_export(source_parent, cfg, cancel, drive, report_dir)
    finally:
        drive.release_lock()


def _perform_drive_export(source_parent, cfg, cancel, drive, report_dir):
    source_parent = Path(source_parent)
    name = source_parent.name
    started = datetime.now()
    t0 = time.monotonic()

    acct = drive.account()
    ui.info(tr("Google Drive: %s", acct["email"]))
    root = drive.find_or_create_folder(ROOT_NAME, None, app_key="root")
    set_id = drive.find_or_create_folder(name, root)
    ui.info(tr("Reading what is already on Google Drive …"))
    remote, folders = drive.list_tree(set_id)
    ui.info(tr("Scanning the backup folder …"))
    current = scan_backup(source_parent)
    known = open_readonly_lookup(source_parent)

    todo, conflicts = [], []
    for rel, (sz, mt) in sorted(current.items()):
        r = remote.get(rel)
        if r is None:
            todo.append((rel, sz))
            continue
        k = known.get(rel)
        if r["size"] != sz or (k and k[0] == sz and r["sha256"] and r["sha256"] != k[1]):
            conflicts.append((rel, sz))
    total = sum(sz for _, sz in todo)
    ui.info("  " + trp("%d file in the backup, %d already on Google Drive, %d to upload (%s).",
                       "%d files in the backup, %d already on Google Drive, %d to upload (%s).",
                       len(current), len(current), len(current) - len(todo) - len(conflicts),
                       len(todo), ui.human_size(total)))
    if todo and acct["free"] is not None and total > acct["free"]:
        raise DriveError(tr("Not enough space on Google Drive: %s free, %s needed.",
                            ui.human_size(acct["free"]), ui.human_size(total)), "no_space")

    prog = ui.Progress(len(todo), total)
    rows, status, errors, warnings = [], "COMPLETED", 0, 0
    by_cat = {}
    stop = threading.Event()                    # cancelled, Drive full or sign-in lost
    fatal = []
    lock = threading.Lock()

    def one(nr, rel, sz):
        if stop.is_set() or (cancel is not None and cancel.is_set()):
            return None
        folder_rel, _, fname = rel.rpartition("/")
        k = known.get(rel)
        expected = k[1] if k and k[0] == sz else None
        sha = ""
        token = prog.begin(fname)
        done = False
        try:
            pid = drive.ensure_path(folders, folder_rel)
            _, sha, gsha = drive.upload(source_parent / rel, pid, fname,
                                        on_bytes=lambda b: prog.update(add_bytes=b), cancel=cancel)
            done = True
            if gsha and gsha != sha:
                st = "ERROR: Google Drive stored different data (SHA-256 mismatch)"
            elif expected and expected != sha:
                st = ("WARNING: uploaded, but the backup file differs from the SHA-256 recorded "
                      "when it was backed up - the backup drive may be damaged")
            elif not gsha:
                st = "OK - uploaded (Google gave no SHA-256, checked while reading)"
            else:
                st = "OK - uploaded and verified"
        except Cancelled:
            stop.set()
            return None
        except NotSignedIn as e:
            fatal.append(e)
            stop.set()
            return None
        except (DriveError, OSError) as e:
            st = f"ERROR: {e}"
            if isinstance(e, DriveFull):
                fatal.append(STATUS_FULL)
                stop.set()
        finally:
            prog.end(token, done=done)
        return [nr, fname, tr(_category(rel)), ui.human_size(sz), sz, rel, st, sha]

    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        futures = [pool.submit(one, nr, rel, sz) for nr, (rel, sz) in enumerate(todo, 1)]
        for f in futures:
            row = f.result()
            if row is None:
                continue
            st, sz, rel = row[6], row[4], row[5]
            with lock:
                if st.startswith("ERROR"):
                    errors += 1
                else:
                    if st.startswith("WARNING"):
                        warnings += 1
                    c = _category(rel)
                    by_cat.setdefault(c, [0, 0])
                    by_cat[c][0] += 1
                    by_cat[c][1] += sz
                rows.append(row)
    prog.finish()
    if any(isinstance(e, NotSignedIn) for e in fatal):
        raise next(e for e in fatal if isinstance(e, NotSignedIn))
    if cancel is not None and cancel.is_set():
        status = "CANCELLED by user"
    elif fatal:
        status = fatal[0]
    for rel, sz in conflicts:
        warnings += 1
        rows.append(["", Path(rel).name, tr(_category(rel)), ui.human_size(sz), sz, rel,
                     "WARNING: a different file with this name is already on Google Drive - "
                     "not overwritten", ""])
    if status == "COMPLETED" and errors:
        status = "COMPLETED WITH ERRORS"

    duration = time.monotonic() - t0
    ok = status == "COMPLETED" and not warnings
    n = sum(v[0] for v in by_cat.values())
    b = sum(v[1] for v in by_cat.values())
    everything = ("EVERYTHING EXPORTED CORRECTLY - %d files (%s) uploaded to Google Drive and "
                  "verified with SHA-256.")         # English says "1 files" here (tests check it)
    from .report import both
    verdict = (both.trp(everything, "EVERYTHING EXPORTED CORRECTLY - %d files (%s) uploaded to Google "
                   "Drive and verified with SHA-256.", n, n, ui.human_size(b)) if ok else
               attention(status, errors, warnings))
    sections = [
        (tr("General"), [(tr("Export type"), tr("Google Drive (mirror – only new files)")),
                         (tr("Status"), tr(status)),
                         (tr("Google account"), acct["email"]),
                         (tr("Source (backup folder)"), str(source_parent)),
                         (tr("Target on Google Drive"), f"My Drive/{ROOT_NAME}/{name}"),
                         (tr("Started"), f"{started:%Y-%m-%d %H:%M:%S}"),
                         (tr("Duration"), ui.human_duration(duration)),
                         (tr("Average upload speed"),
                          tr("%s/s", ui.human_size(b / duration if duration > 0 else 0)))]),
        (tr("Data exported"), [(tr("Total"), files_size(n, b))] +
         [(category_label(c), files_size(v[0], v[1])) for c, v in sorted(by_cat.items())] +
         [(tr("Files in backup"), str(len(current))),
          (tr("Already on Google Drive"), str(len(current) - len(todo) - len(conflicts))),
          (tr("Errors"), str(errors)), (tr("Warnings"), str(warnings))]),
    ]
    columns = [tr("Nr"), tr("File"), tr("Type"), tr("Size"), tr("Bytes"), tr("Path in backup"),
               tr("Status"), tr("SHA-256")]
    rdir = Path(report_dir) if report_dir else reports_dir(name)
    base = unique_basename(rdir, f"Google Drive export {name}", started)
    paths = write_reports(rdir, base, tr("Google Drive export %s - %s", name,
                                         f"{started:%Y-%m-%d %H:%M}"),
                          ok, verdict, sections, columns, rows)
    # the report also goes to Google Drive (next to the mirrored backup)
    try:
        pid = drive.ensure_path(folders, REPORTS_FOLDER)
        for p in paths:
            drive.upload(p, pid, p.name)
    except (DriveError, OSError, Cancelled) as e:
        ui.warn(tr("Report could not be uploaded to Google Drive: %s", e))
    (ui.ok if ok else ui.error)(verdict)
    return status, paths, verdict


def attention(status, errors, warnings):
    """The verdict of an export that did not go perfectly (status: the English run status)."""
    from .report import both
    return both.tr("ATTENTION - %s, %s, %s", both.tr(status),
                   both.trp("%d error", "%d errors", errors, errors),
                   both.trp("%d warning", "%d warnings", warnings, warnings))


def files_size(n, size):
    """'12 files, 3.4 MB' for the report."""
    return trp("%d file, %s", "%d files, %s", n, n, ui.human_size(size))


_CATEGORIES = (N_("photo"), N_("video"), N_("raw"), N_("other"),        # report "Type" cells
               N_("Photo"), N_("Video"), N_("Raw"), N_("Other"))        # report row labels


def category_label(c):
    """Report row label of a file category ('photos' -> 'Photos' in the chosen language)."""
    return tr(c.capitalize())


def last_reports(set_name, limit=10):
    d = reports_dir(set_name)
    try:
        return sorted(d.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    except OSError:
        return []


if __name__ == "__main__":       # manual check: python -m phonebackup.gdrive
    c = config.load()
    print("configured:", is_configured(c), "signed in:", signed_in_email())
    sys.exit(0)
