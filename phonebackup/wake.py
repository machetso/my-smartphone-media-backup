"""Connect a paired phone without a cable (user request 2026-11-10): the "Connect phone" QR code.

Only for phones already paired with the phone app; the pairing secret signs it:

* QR code: the computer shows  phonebackup://connect?pc=<pc id>&a=<ip:port>&n=<nonce>&e=<expiry>&t=<tokens>
  with one token per paired phone = HMAC(secret, "fmb-connect:<nonce>:<expiry>")[:8]. The phone's
  camera opens the app; the app checks the token, switches backup mode on and tells the computer
  where it is (POST /here to ip:port with proof = HMAC(secret, "fmb-here:<nonce>:<ip:port>")).
  The address in the QR means the phone is found even where mDNS does not work.
Afterwards the computer connects over TLS pinned to the phone's key – a wrong answer to /here can
not make it talk to another device. The QR code opens a page first (page()): it opens the app, or
offers to install it when it is missing or too old.
"""

import hmac
import json
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import companion
from .i18n import tr

QR_SECONDS = 300            # a QR code is valid for 5 minutes, and only once


def _hmac(secret, msg):
    return companion._hmac(secret, msg)


# ------------------------------------------------------------------ QR code
def connect_token(secret, nonce, expiry):
    return _hmac(secret, f"fmb-connect:{nonce}:{expiry}")[:8].hex()


def here_proof(secret, nonce, address):
    return _hmac(secret, f"fmb-here:{nonce}:{address}")[:16].hex()


def connect_link(pc_id, address, entries, nonce, expiry):
    q = urllib.parse.urlencode({"pc": pc_id, "a": address, "n": nonce, "e": str(expiry),
                                "t": ".".join(connect_token(e["secret"], nonce, expiry) for e in entries)})
    return f"phonebackup://connect?{q}"


def verify_here(entries, nonce, address, proof):
    """The paired phone that sent a valid /here, or None."""
    if not (isinstance(proof, str) and isinstance(address, str)):
        return None
    for e in entries:
        if hmac.compare_digest(here_proof(e["secret"], nonce, address), proof):
            return e
    return None


class ConnectServer:
    """Shows the way for the QR code: the phone tells this computer where it is (once)."""

    def __init__(self, cfg, on_here, ip=None):
        self.cfg = cfg
        self.on_here = on_here               # (entry, 'ip:port') from a server thread
        self.ip = ip or (companion.local_ips() or ["127.0.0.1"])[0]
        self.nonce = secrets.token_hex(8)
        self.expiry = int(time.time()) + QR_SECONDS
        self.used = False
        self.httpd = None

    @property
    def address(self):
        return f"{self.ip}:{self.httpd.server_address[1]}" if self.httpd else ""

    def link(self):
        """phonebackup://connect?… – opens the app directly (only when it is installed)."""
        pc_id, _name = companion.pc_identity(self.cfg)
        return connect_link(pc_id, self.address, companion.phones(self.cfg), self.nonce, self.expiry)

    def page_url(self):
        """What the QR code shows (user 2026-11-10): a page in the phone's browser that opens the
        app – or, when the app is missing or too old, offers to download and install it."""
        return f"http://{self.address}/c/{self.nonce}"

    def intent_url(self):
        q = self.link().split("?", 1)[1]
        fallback = urllib.parse.quote(self.page_url() + "#install", safe="")
        return (f"intent://connect?{q}#Intent;scheme=phonebackup;package={companion.APP_PACKAGE};"
                f"S.browser_fallback_url={fallback};end")

    def page(self):
        import html
        from . import APP_NAME as PROGRAM
        from .i18n import current
        e = html.escape
        lang = current()
        apk = companion.apk_path()
        name = companion.APP_NAME
        install = (f"<a class='btn btn2' href='/c/{self.nonce}/MediaBackup.apk'>"
                   f"{e(tr('Install or update the app (version %s)', companion.APP_VERSION_NAME))}</a>"
                   f"<small>{tr('Then open the downloaded file and tap <i>Install</i>. Android may ask once to '
                                'allow installing apps from your browser. Afterwards come back here and tap '
                                'the blue button.')}</small>"
                   if apk else f"<p>{e(tr('The app file is missing in this program.'))}</p>")
        return f"""<!doctype html><html lang="{e(lang.locale)}" dir="{'rtl' if lang.rtl else 'ltr'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(tr("Connect phone"))}</title>
<style>
body{{font-family:sans-serif;margin:0;padding:20px;max-width:560px;background:#fff;color:#222}}
@media (prefers-color-scheme:dark){{body{{background:#121212;color:#eee}}}}
.btn{{display:block;text-align:center;padding:16px;margin:14px 0;border-radius:12px;background:#1f6feb;
color:#fff;text-decoration:none;font-size:18px;font-weight:600}}
.btn2{{background:#1f8a4c}} small{{color:#888;display:block}}
</style></head><body>
<h2>{e(PROGRAM)}</h2>
<a class="btn" href="{e(self.intent_url())}">{e(tr("Open “%s” and connect", name))}</a>
<small>{tr("Opens the app on this phone, switches backup mode on and connects to the computer. If "
           "the app is missing or too old, you land below.")}</small>
<h3 id="install">{e(tr("App not installed yet, or too old?"))}</h3>
{install}
<p><small>{tr("Not paired with this computer yet? After installing, on the computer: ⚙ → "
              "“Install with QR code…” and tap “Connect app with this computer”.")}</small></p>
</body></html>"""

    def start(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 10

            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urllib.parse.urlparse(self.path).path
                base = f"/c/{server.nonce}"
                if path == base:
                    body = server.page().encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                apk = companion.apk_path()
                if path == base + "/MediaBackup.apk" and apk:
                    data = apk.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.android.package-archive")
                    self.send_header("Content-Disposition", 'attachment; filename="MediaBackup.apk"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self._send(404, {"error": "not found"})

            def do_POST(self):
                if self.path != "/here":
                    return self._send(404, {"error": "not found"})
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    data = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
                except (ValueError, OSError):
                    return self._send(400, {"error": "bad request"})
                entry, addr = server.check(data, self.client_address[0])
                if entry is None:
                    return self._send(403, {"error": "refused"})
                server.on_here(entry, addr)          # quick: the window only gets a signal
                self._send(200, {"ok": True})

        self.httpd = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def check(self, data, client_ip):
        """(entry, 'ip:port') for a valid, first, unexpired answer from the QR code's phone."""
        if self.used or time.time() > self.expiry or data.get("n") != self.nonce:
            return None, None
        try:
            port = int(data.get("port"))
        except (TypeError, ValueError):
            return None, None
        if not 0 < port < 65536:
            return None, None
        addr = f"{client_ip}:{port}"               # the address the request really came from
        entry = verify_here(companion.phones(self.cfg), self.nonce, addr, data.get("proof"))
        if entry is None:
            return None, None
        self.used = True
        return entry, addr

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
