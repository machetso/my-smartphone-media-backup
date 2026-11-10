"""GUI for backups over Wi-Fi: pairing dialog (QR code or 6-digit code) and direct Wi-Fi (hotspot)."""

import html
import sys
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from . import config, wireless
from .i18n import tr, N_

GREEN, ORANGE, RED, GRAY = "#1f8a4c", "#c76a00", "#c62828", "#808080"
# Android setting names as on an English phone (a translator may adapt them)
WD_PATH = N_("Settings → System → Developer options → Wireless debugging")


def qr_pixmap(text, scale=6):
    """QR code as QPixmap, or None if the optional 'segno' package is missing."""
    try:
        import segno
    except ImportError:
        return None
    import io
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=3,
                                     dark="#000000", light="#ffffff")
    pm = QPixmap()
    pm.loadFromData(buf.getvalue(), "PNG")
    return pm


def _label(text, rich=True):
    lab = QLabel(text)
    lab.setWordWrap(True)
    if rich:
        lab.setTextFormat(Qt.RichText)
    lab.setTextInteractionFlags(Qt.TextBrowserInteraction)
    return lab


def _status_html(text, color):
    return f"<span style='color:{color};font-weight:600'>{html.escape(text)}</span>"


class WifiPairDialog(QDialog):
    """Pair the phone once with this computer for wireless debugging (ADB over Wi-Fi)."""

    services = Signal(object)      # list[MdnsService] from the background scan
    finished_pair = Signal(bool, str, str)   # ok, message, connected address

    def __init__(self, parent, adb, cfg):
        super().__init__(parent)
        self.adb, self.cfg = adb, cfg
        self.connected_address = ""
        self._busy = False
        self._qr_used = False
        self._stop = threading.Event()
        self.qr_name, self.qr_password, qr_text = wireless.new_qr_pairing()
        self.setWindowTitle(tr("Pair phone over Wi-Fi"))
        self.resize(620, 600)
        lay = QVBoxLayout(self)
        lay.addWidget(_label(
            tr("Back up without a cable: Android's <b>Wireless debugging</b> (Android 11 or newer, "
               "no app needed). Pairing is needed <b>only once</b> per phone and computer. "
               "Afterwards the phone is found automatically whenever Wireless debugging is on and "
               "phone and computer are in the same Wi-Fi (or the phone is in the computer's "
               "<i>Direct Wi-Fi</i>).") + "<br><br>"
            + tr("On the phone: <b>%s</b> → switch on (allow it for this network).", tr(WD_PATH))))

        self.tabs = QTabWidget()
        # --- QR code
        qr_w = QWidget()
        ql = QHBoxLayout(qr_w)
        pm = qr_pixmap(qr_text)
        if pm is not None:
            img = QLabel()
            img.setPixmap(pm)
            img.setAlignment(Qt.AlignCenter)
            ql.addWidget(img)
            ql.addWidget(_label(
                "<b>" + tr("Scan this code only from the Wireless debugging screen:") + "</b><ol>"
                "<li>" + tr("%s → switch on.", tr(WD_PATH)) + "</li>"
                "<li>" + tr("Tap the words <b>Wireless debugging</b> to open the screen.") + "</li>"
                "<li>" + tr("Tap <b>Pair device with QR code</b> and scan.") + "</li></ol>"
                f"<span style='color:{ORANGE}'>"
                + tr("Do <b>not</b> scan it with the camera app or in the Wi-Fi "
                     "settings – the phone then thinks it is a Wi-Fi network and reports a wrong "
                     "password.") + "</span><br><br>"
                + tr("The phone must be in the same Wi-Fi as this computer. "
                     "The computer finishes the pairing by itself (a few seconds).")), 1)
        else:
            ql.addWidget(_label(tr("QR codes need the Python package <tt>segno</tt>. "
                                   "Use the tab <b>Pairing code</b> instead.")))
        self.tabs.addTab(qr_w, tr("Scan QR code"))
        # --- 6-digit code
        code_w = QWidget()
        cl = QVBoxLayout(code_w)
        cl.addWidget(_label(tr(
            "On the phone in <b>Wireless debugging</b> tap <b>Pair device with pairing code</b>. "
            "The phone shows a 6-digit code and an address (IP address &amp; port). "
            "The address is usually found automatically below.")))
        self.found = QListWidget()
        self.found.setMaximumHeight(70)
        self.found.itemClicked.connect(lambda it: self.addr_edit.setText(it.data(Qt.UserRole)))
        cl.addWidget(self.found)
        form = QFormLayout()
        self.addr_edit = QLineEdit()
        self.addr_edit.setPlaceholderText(tr("e.g. %s", "192.168.1.23:41234"))
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText(tr("6 digits"))
        self.code_edit.setMaxLength(7)
        form.addRow(tr("Address from the pairing window:"), self.addr_edit)
        form.addRow(tr("Pairing code:"), self.code_edit)
        cl.addLayout(form)
        self.pair_btn = QPushButton(tr("Pair"))
        self.pair_btn.clicked.connect(self._pair_code)
        cl.addWidget(self.pair_btn, 0, Qt.AlignRight)
        self.tabs.addTab(code_w, tr("Pairing code"))
        lay.addWidget(self.tabs, 1)

        # --- already paired: connect by address
        ml = QHBoxLayout()
        self.conn_edit = QLineEdit(cfg.get("wifi_last_address", ""))
        self.conn_edit.setPlaceholderText(tr("IP address & port from the Wireless debugging screen"))
        b = QPushButton(tr("Connect"))
        b.clicked.connect(self._connect_manual)
        ml.addWidget(QLabel(tr("Already paired – connect to:")))
        ml.addWidget(self.conn_edit, 1)
        ml.addWidget(b)
        lay.addLayout(ml)

        self.status = _label(_status_html(tr("Waiting for the phone …"), GRAY))
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.services.connect(self._on_services)
        self.finished_pair.connect(self._on_finished)
        threading.Thread(target=self._scan, daemon=True).start()

    # ------------------------------------------------------------------ background
    def _scan(self):
        while not self._stop.is_set():
            self.services.emit(wireless.mdns_services(self.adb))
            self._stop.wait(1.5)

    def _on_services(self, svcs):
        if self._busy or self._stop.is_set():
            return
        pairing = [s for s in svcs if s.kind == wireless.PAIRING]
        # the phone scanned our QR code → it announces a pairing service with our name
        for s in pairing:
            if s.name == self.qr_name and not self._qr_used:
                self._qr_used = True     # try once; to retry, close and reopen the dialog
                self._start(lambda: self._do_pair(s.address, self.qr_password),
                            tr("QR code scanned – pairing …"))
                return
        current = {self.found.item(i).data(Qt.UserRole) for i in range(self.found.count())}
        others = [s for s in pairing if s.name != self.qr_name]
        if {s.address for s in others} != current:
            self.found.clear()
            for s in others:
                it = QListWidgetItem(f"{s.address}   ({s.name})")
                it.setData(Qt.UserRole, s.address)
                self.found.addItem(it)
            if len(others) == 1 and not self.addr_edit.text().strip():
                self.addr_edit.setText(others[0].address)

    def _start(self, func, text):
        self._busy = True
        self.pair_btn.setEnabled(False)
        self.status.setText(_status_html(text, GRAY))

        def run():
            try:
                ok, msg, addr = func()
            except Exception as e:  # noqa: BLE001
                ok, msg, addr = False, str(e), ""
            self.finished_pair.emit(ok, msg, addr)

        threading.Thread(target=run, daemon=True).start()

    def _do_pair(self, address, code):
        ok, msg = wireless.pair(self.adb, address, code)
        if not ok:
            return False, tr("Pairing failed: %s", msg), ""
        ip = address.rsplit(":", 1)[0]
        # after pairing the phone announces its connect port (differs from the pairing port)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            for s in wireless.mdns_services(self.adb):
                if s.kind == wireless.CONNECT and s.address.rsplit(":", 1)[0] == ip:
                    cok, cmsg = wireless.connect(self.adb, s.address)
                    if cok:
                        return True, tr("Paired and connected."), s.address
            time.sleep(1)
        return True, tr("Paired. Now enter the address shown at the top of the Wireless debugging "
                        "screen (IP address & port) below and click Connect."), ""

    def _do_connect(self, address):
        if not wireless.valid_address(address):
            return False, tr("The address must look like %s (IP address and port).",
                             "192.168.1.23:37123"), ""
        ok, msg = wireless.connect(self.adb, address)
        return ok, (tr("Connected.") if ok else tr("Could not connect: %s", msg)), (address if ok else "")

    def _pair_code(self):
        code = self.code_edit.text().strip().replace(" ", "")
        if not code.isdigit() or len(code) != 6:
            self.status.setText(_status_html(tr("The pairing code has 6 digits."), RED))
            return
        addr = self.addr_edit.text().strip()
        self._start(lambda: self._do_pair(addr, code), tr("Pairing …"))

    def _connect_manual(self):
        addr = self.conn_edit.text().strip()
        self._start(lambda: self._do_connect(addr), tr("Connecting …"))

    def _on_finished(self, ok, msg, addr):
        self._busy = False
        self.pair_btn.setEnabled(True)
        if ok and addr:
            self.connected_address = addr
            wireless.remember(self.cfg, addr, self.adb)
            self.status.setText(_status_html(msg, GREEN))
            QTimer.singleShot(900, self.accept)
            return
        self.status.setText(_status_html(msg, GREEN if ok else RED))

    def done(self, r):
        self._stop.set()
        super().done(r)


class HotspotDialog(QDialog):
    """Direct Wi-Fi: the computer opens its own Wi-Fi network and the phone joins it."""

    result_ready = Signal(bool, str)

    def __init__(self, parent, cfg, on_pair):
        super().__init__(parent)
        self.cfg = cfg
        self.on_pair = on_pair
        self.setWindowTitle(tr("Direct Wi-Fi (no router)"))
        self.resize(600, 560)
        lay = QVBoxLayout(self)
        win = sys.platform.startswith("win")
        lay.addWidget(_label(
            tr("The computer opens <b>its own Wi-Fi network</b> and the phone joins it – a direct "
               "phone ↔ computer connection, no router or internet needed (e.g. on the road).")
            + f"<br><span style='color:{ORANGE}'>"
            + tr("While it is on, this computer may lose its normal Wi-Fi "
                 "(most Wi-Fi adapters can do only one at a time). It comes back when you stop the "
                 "direct Wi-Fi.") + "</span>"))

        if not cfg.get("hotspot_ssid") or not cfg.get("hotspot_password"):
            cfg["hotspot_ssid"], cfg["hotspot_password"] = wireless.new_hotspot_credentials()
            config.save(cfg)
        ssid, pw = cfg["hotspot_ssid"], cfg["hotspot_password"]

        if win:
            lay.addWidget(_label(tr(
                "<b>Windows:</b> switch on <b>Mobile hotspot</b> in the Windows settings "
                "(button below) and connect the phone to the network name and password shown there.")))
            b = QPushButton(tr("Open Mobile hotspot settings"))
            b.clicked.connect(wireless.open_windows_hotspot_settings)
            lay.addWidget(b, 0, Qt.AlignLeft)
        else:
            row = QHBoxLayout()
            pm = qr_pixmap(wireless.wifi_qr_text(ssid, pw), scale=5)
            if pm is not None:
                img = QLabel()
                img.setPixmap(pm)
                row.addWidget(img)
            row.addWidget(_label(
                tr("Network: %s", f"<b style='font-size:15pt'>{html.escape(ssid)}</b>") + "<br>"
                + tr("Password: %s",
                     f"<b style='font-size:15pt;font-family:monospace'>{html.escape(pw)}</b>")
                + "<br><br>"
                + tr("Join it with the phone: scan the QR code with the camera, or choose the network "
                     "in the phone's Wi-Fi settings. The phone remembers it for next time.")), 1)
            lay.addLayout(row)
            br = QHBoxLayout()
            self.start_btn = QPushButton(tr("Start direct Wi-Fi"))
            self.start_btn.clicked.connect(self._start)
            self.stop_btn = QPushButton(tr("Stop direct Wi-Fi"))
            self.stop_btn.clicked.connect(self._stop)
            br.addWidget(self.start_btn)
            br.addWidget(self.stop_btn)
            br.addStretch()
            lay.addLayout(br)

        lay.addWidget(_label(
            "<b>" + tr("Then on the phone:") + "</b><ol>"
            "<li>" + tr("%s → on (tap <i>Allow</i> for this network).", tr(WD_PATH)) + "</li>"
            "<li>" + tr("First time only: pair the phone (button below).") + "</li>"
            "<li>" + tr("The phone is found automatically – start the backup as usual.") + "</li></ol>"
            + tr("Tip: keep the phone close to the computer and plugged into a charger for large "
                 "backups.")))
        pb = QPushButton(tr("Pair phone over Wi-Fi…"))
        pb.clicked.connect(self.on_pair)
        lay.addWidget(pb, 0, Qt.AlignLeft)

        self.status = _label("")
        lay.addWidget(self.status)
        lay.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.steps = _label("")              # live: what is happening now (user request 2026-11-10)
        lay.insertWidget(lay.indexOf(self.status) + 1, self.steps)
        self.result_ready.connect(self._on_result)
        if not win:
            self._refresh()
            self._steps_timer = QTimer(self)
            self._steps_timer.timeout.connect(self._show_steps)
            self._steps_timer.start(1000)

    def _show_steps(self):
        """The four steps with ✓ / … and what to do now – from the main window's background check."""
        par = self.parent()
        info = getattr(par, "_hotspot_info", None)
        if not self.stop_btn.isEnabled() and info is None:
            self.steps.setText("")
            return
        if info is None:
            self.steps.setText(_status_html(tr("Checking whether the phone has joined …"), GRAY))
            return
        joined, answers, conn = bool(info["clients"]), info["app"] or info["adb"], info["connected"]

        def step(done, text, now):
            mark, col = ("✓", GREEN) if done else ("→", ORANGE) if now else ("○", GRAY)
            return f"<div style='color:{col}'>{mark} {text}</div>"

        rows = [step(True, html.escape(tr("Direct Wi-Fi is on")), False),
                step(joined, html.escape(tr("The phone joins the network")
                                         + (f" ({info['clients'][0]})" if joined else "")), not joined),
                step(answers or conn, html.escape(tr("The phone app or Wireless debugging answers")),
                     joined and not (answers or conn)),
                step(conn, html.escape(tr("Connected – you can close this window and start the backup")),
                     answers and not conn)]
        msg = par.hotspot_progress_text() if hasattr(par, "hotspot_progress_text") else None
        hint = ""
        if msg and not conn:
            hint = f"<br><span style='color:{msg[1]}'>" + html.escape(msg[0]).replace("\n", "<br>") + "</span>"
        self.steps.setText("".join(rows) + hint)

    def _refresh(self):
        active = wireless.hotspot_active()
        self.start_btn.setEnabled(not active)
        self.stop_btn.setEnabled(active)
        if active:
            self.status.setText(_status_html(tr("Direct Wi-Fi is ON."), GREEN))
        else:
            self.status.setText(_status_html(tr("Direct Wi-Fi is off."), GRAY))

    def _run(self, func, text):
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.status.setText(_status_html(text, GRAY))

        def run():
            try:
                ok, msg = func()
            except Exception as e:  # noqa: BLE001
                ok, msg = False, str(e)
            self.result_ready.emit(ok, msg)

        threading.Thread(target=run, daemon=True).start()

    def _start(self):
        ssid, pw = self.cfg["hotspot_ssid"], self.cfg["hotspot_password"]
        self._run(lambda: wireless.start_hotspot(ssid, pw), tr("Starting direct Wi-Fi … (up to a minute)"))

    def _stop(self):
        self._run(wireless.stop_hotspot, tr("Stopping direct Wi-Fi …"))

    def _on_result(self, ok, msg):
        par = self.parent()
        if hasattr(par, "_hotspot_next"):
            par._hotspot_next = 0.0           # check at once whether the phone joins
        self._refresh()
        if not ok:
            self.status.setText(_status_html(tr("Did not work: %s", msg), RED))
        elif msg:
            self.status.setText(_status_html(msg, GREEN))


class PhoneAppDialog(QDialog):
    """Set up the phone app: QR code → setup page on this computer → install → pair."""

    pair_request = Signal(object)
    claimed = Signal(object, str)        # entry or None, error
    pair_error = Signal(str)             # the key could not be handed to the phone

    def __init__(self, parent, cfg, first_run=False):
        super().__init__(parent)
        from . import companion
        self.companion = companion
        self.cfg = cfg
        self.paired = None
        self.req = None
        self.setWindowTitle(tr("Connect your phone") if first_run else tr("Set up phone app"))
        self.resize(640, 680)
        lay = QVBoxLayout(self)
        if first_run:          # the first connection ever (user request 2026-11-10): as easy as possible
            lay.addWidget(_label("<span style='font-size:16px;font-weight:600'>"
                                 + tr("Connect your phone") + "</span>"))
            lay.addWidget(_label("<b>" + tr("Easiest – works with every phone:") + "</b> " + tr(
                "plug the phone in with the USB cable, unlock it and choose “File transfer” on the phone. "
                "The program connects by itself (slower, but nothing to install).") + "<br><br><b>"
                + tr("Without a cable – phone app over Wi-Fi:") + "</b>"))
        lay.addWidget(_label(tr(
            "The phone app <b>My Media Backup</b> backs up without USB debugging or developer options. "
            "It may only <b>read photos and videos</b> – nothing else – and the connection is "
            "encrypted. Phone and computer must be in the same Wi-Fi (or the phone in the computer's "
            "Direct Wi-Fi).")))
        self.server = companion.SetupServer(cfg, lambda r: self.pair_request.emit(r),
                                            on_error=lambda t: self.pair_error.emit(t))
        try:
            self.server.start()
            err = None
        except Exception as e:  # noqa: BLE001
            err = str(e)
        row = QHBoxLayout()
        if err is None:
            pm = qr_pixmap(self.server.page_url, scale=6)
            if pm is not None:
                img = QLabel()
                img.setPixmap(pm)
                row.addWidget(img)
            row.addWidget(_label(
                tr("<b>Scan with the phone's camera</b> and open the link. The page offers:") + "<ol>"
                "<li>" + tr("<b>Download the app</b> – then open the file and tap <i>Install</i> "
                            "(Android asks once to allow installs from the browser).") + "</li>"
                "<li>" + tr("<b>Connect app with this computer</b> – the app opens and shows a "
                            "code.") + "</li></ol>"
                + tr("Link (to type it in): %s", f"<tt>{html.escape(self.server.page_url)}</tt>")
                + ("" if self.server.apk else
                   f"<br><span style='color:{RED}'>"
                   + tr("The app file is missing in this program (%s) – only pairing works.",
                        "assets/companion/MediaBackup.apk") + "</span>")), 1)
        else:
            row.addWidget(_label(_status_html(tr("Could not start: %s", err), RED)))
        lay.addLayout(row)
        vpn = _label(tr("The phone cannot open the page? Then it is not in the same Wi-Fi as this computer – or a VPN on "
                 "the phone (e.g. Tailscale) sends it elsewhere: switch the VPN off for a moment, or allow "
                 "“local network access” in the VPN app."))
        vpn.setStyleSheet(f"color:{ORANGE}")
        lay.addWidget(vpn)
        bt_row = QHBoxLayout()
        bt_row.addWidget(_label(tr("Phone not in the same Wi-Fi? Send the app over Bluetooth instead:")), 1)
        bt = QPushButton(tr("Send the app over Bluetooth…"))
        bt.setToolTip(tr("Last resort: only the app file goes over Bluetooth – never photos or videos."))
        bt.clicked.connect(lambda: parent._install_app_bluetooth())
        bt_row.addWidget(bt)
        lay.addLayout(bt_row)

        self.code_box = QWidget()
        cl = QVBoxLayout(self.code_box)
        self.code_label = _label("")
        cl.addWidget(self.code_label)
        br = QHBoxLayout()
        self.ok_btn = QPushButton(tr("Same code – pair"))
        self.ok_btn.clicked.connect(self._confirm)
        no = QPushButton(tr("Different code – refuse"))
        no.clicked.connect(self._refuse)
        br.addWidget(self.ok_btn)
        br.addWidget(no)
        br.addStretch()
        cl.addLayout(br)
        self.code_box.hide()
        lay.addWidget(self.code_box)

        self.status = _label(_status_html(tr("Waiting for the phone …"), GRAY))
        lay.addWidget(self.status)

        paired = companion.phones(cfg)
        if paired:
            lay.addWidget(_label("<b>" + tr("Paired phones:") + "</b> " + ", ".join(
                html.escape(p.get("name", "?")) for p in paired)))
        lay.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.pair_request.connect(self._on_request)
        self.pair_error.connect(self._on_pair_error)
        self.claimed.connect(self._on_claimed)

    def _on_request(self, req):
        if req.outdated:
            self.status.setText(_status_html(tr(
                "The phone app is too old for this program. Download the app again on the phone "
                "(step 1 on the page), install it, then scan the code again."), RED))
            return
        self.req = req
        code = req.code[:3] + " " + req.code[3:]
        self.code_label.setText(
            tr("%s wants to pair.",
               f"<b>{html.escape((req.manufacturer + ' ' + req.model).strip())}</b>") + "<br>"
            + tr("Code: %s",
                 f"<span style='font-size:28pt;font-family:monospace;font-weight:700'>{code}</span>")
            + "<br>" + tr("Does the phone show <b>exactly the same code</b>?"))
        self.code_box.show()
        self.ok_btn.setEnabled(True)
        self.status.setText("")

    def _confirm(self):
        req = self.req
        if req is None:
            return
        self.ok_btn.setEnabled(False)
        self.status.setText(_status_html(tr("Now tap “Same code – Pair” on the phone too …"), GRAY))

        def run():
            try:
                self.claimed.emit(self.server.claim(req), "")
            except Exception as e:  # noqa: BLE001
                self.claimed.emit(None, str(e))

        threading.Thread(target=run, daemon=True).start()

    def _on_pair_error(self, text):
        self.code_box.hide()
        self.req = None
        self.status.setText(_status_html(tr("Pairing failed: %s", text), RED))

    def _refuse(self):
        self.req = None
        self.code_box.hide()
        self.status.setText(_status_html(tr("Refused. Somebody else may have tried to pair – "
                                            "close this window and start again."), RED))

    def _on_claimed(self, entry, err):
        self.code_box.hide()
        if entry:
            self.paired = entry
            self.status.setText(_status_html(tr("Paired with %s. The phone is now in "
                                                "backup mode and will be connected.", entry['name']),
                                             GREEN))
            QTimer.singleShot(1500, self.accept)
        else:
            self.status.setText(_status_html(tr("Pairing failed: %s", err), RED))

    def done(self, r):
        self.server.stop()
        super().done(r)


class ConnectPhoneDialog(QDialog):
    """Connect a paired phone without a cable (user request 2026-11-10): a QR code to scan with the
    phone's camera (opens or installs the phone app); Bluetooth only to send the app file.

    found(entry, 'ip:port') when the phone answered the QR code; the main window connects it.
    The dialog also closes by itself once the main window has a phone (`connected()` → True)."""
    found = Signal(object)

    def __init__(self, parent, cfg, connected):
        super().__init__(parent)
        from . import companion, wake
        self.setWindowTitle(tr("Connect phone"))
        self.cfg, self.connected = cfg, connected
        self.server = None
        lay = QVBoxLayout(self)
        if not companion.phones(cfg):
            lay.addWidget(_label(tr("No phone is paired with this computer yet. Set up the phone app "
                                    "first – install it and pair it with this computer (or connect the "
                                    "phone once with the USB cable).")))
            setup = QPushButton(tr("Set up the phone app…"))
            setup.clicked.connect(lambda: (self.reject(), PhoneAppDialog(parent, cfg).exec()))
            lay.addWidget(setup, 0, Qt.AlignLeft)
            bb = QDialogButtonBox(QDialogButtonBox.Close)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            return
        self.server = wake.ConnectServer(cfg, lambda e, a: self.found.emit((e, a))).start()
        cable = _label("<b>" + tr("Easiest – USB cable:") + "</b> " + tr(
            "plug the phone in, unlock it and choose “File transfer” on the phone – the program connects "
            "by itself. Without a cable:"))
        lay.addWidget(cable)
        row = QHBoxLayout()
        self.qr = QLabel()
        self._show_qr()
        row.addWidget(self.qr, 0, Qt.AlignTop)
        right = QVBoxLayout()
        right.addWidget(_label("<b>" + tr("1. Scan with the phone's camera") + "</b><br>" + tr(
            "The phone app “My Media Backup” opens, switches backup mode on and connects to this computer "
            "(same Wi-Fi). Needs the app version %s or newer on the phone.", "0.7.0") + "<br>" + tr(
            "The phone says the app or the link is not found? Then the app is missing or too old: plug "
            "the phone in with the USB cable, choose “File transfer” and use Program settings → “Install "
            "/ update over USB cable…”.")))
        right.addSpacing(10)
        # Bluetooth ONLY to get the app onto the phone, as a last resort (user 2026-11-10)
        right.addWidget(_label("<b>" + tr("2. The code does not work (no shared Wi-Fi)?") + "</b><br>"
                               + tr("Send the phone app over Bluetooth, install it on the phone, then pair it.")))
        self.bt_btn = QPushButton(tr("Send the app over Bluetooth…"))
        self.bt_btn.setToolTip(tr("Last resort: only the app file goes over Bluetooth – never photos or videos."))
        self.bt_btn.clicked.connect(lambda: parent._install_app_bluetooth())
        right.addWidget(self.bt_btn, 0, Qt.AlignLeft)
        self.status = _label("")
        right.addWidget(self.status)
        right.addStretch()
        row.addLayout(right, 1)
        lay.addLayout(row)
        vpn = _label(tr("The phone cannot open the page? Then it is not in the same Wi-Fi as this computer – or a VPN on "
                 "the phone (e.g. Tailscale) sends it elsewhere: switch the VPN off for a moment, or allow "
                 "“local network access” in the VPN app."))
        vpn.setStyleSheet(f"color:{ORANGE}")
        lay.addWidget(vpn)
        tip = _label(tr("Fastest is still the USB cable: the program switches to it by itself when the "
                        "phone is plugged in."))
        tip.setStyleSheet(f"color:{GRAY}")
        lay.addWidget(tip)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(720, 420)
        self.found.connect(lambda _x: self._say(tr("The phone answered – connecting …"), GREEN))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

    def _show_qr(self):
        # the app link itself, not a web page: Chrome on Android 17 may not reach the computer
        # (local network permission), the phone app may (user test 2026-11-10)
        pm = qr_pixmap(self.server.link(), scale=5)
        if pm is not None:
            self.qr.setPixmap(pm)
        else:
            self.qr.setText(tr("QR codes need the Python package <tt>segno</tt>."))

    def _say(self, text, color=GRAY):
        self.status.setText(_status_html(text, color))

    def _tick(self):
        if self.connected():
            self.accept()
            return
        if time.time() > self.server.expiry - 10 and not self.server.used:   # a fresh code
            from . import wake
            self.server.stop()
            self.server = wake.ConnectServer(self.cfg, lambda e, a: self.found.emit((e, a))).start()
            self._show_qr()

    def done(self, r):
        if self.server:
            self.server.stop()
        super().done(r)
