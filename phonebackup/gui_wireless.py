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

GREEN, ORANGE, RED, GRAY = "#1f8a4c", "#c76a00", "#c62828", "#808080"
WD_PATH = "Settings → System → Developer options → Wireless debugging"


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
        self.setWindowTitle("Pair phone over Wi-Fi")
        self.resize(620, 600)
        lay = QVBoxLayout(self)
        lay.addWidget(_label(
            "Back up without a cable: Android's <b>Wireless debugging</b> (Android 11 or newer, "
            "no app needed). Pairing is needed <b>only once</b> per phone and computer. "
            "Afterwards the phone is found automatically whenever Wireless debugging is on and "
            "phone and computer are in the same Wi-Fi (or the phone is in the computer's "
            "<i>Direct Wi-Fi</i>).<br><br>"
            f"On the phone: <b>{WD_PATH}</b> → switch on (allow it for this network)."))

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
                "<b>Scan this code only from the Wireless debugging screen:</b><ol>"
                f"<li>{WD_PATH} → switch on.</li>"
                "<li>Tap the words <b>Wireless debugging</b> to open the screen.</li>"
                "<li>Tap <b>Pair device with QR code</b> and scan.</li></ol>"
                "<span style='color:%s'>Do <b>not</b> scan it with the camera app or in the Wi-Fi "
                "settings – the phone then thinks it is a Wi-Fi network and reports a wrong "
                "password.</span><br><br>The phone must be in the same Wi-Fi as this computer. "
                "The computer finishes the pairing by itself (a few seconds)." % ORANGE), 1)
        else:
            ql.addWidget(_label("QR codes need the Python package <tt>segno</tt>. "
                                "Use the tab <b>Pairing code</b> instead."))
        self.tabs.addTab(qr_w, "Scan QR code")
        # --- 6-digit code
        code_w = QWidget()
        cl = QVBoxLayout(code_w)
        cl.addWidget(_label(
            "On the phone in <b>Wireless debugging</b> tap <b>Pair device with pairing code</b>. "
            "The phone shows a 6-digit code and an address (IP address &amp; port). "
            "The address is usually found automatically below."))
        self.found = QListWidget()
        self.found.setMaximumHeight(70)
        self.found.itemClicked.connect(lambda it: self.addr_edit.setText(it.data(Qt.UserRole)))
        cl.addWidget(self.found)
        form = QFormLayout()
        self.addr_edit = QLineEdit()
        self.addr_edit.setPlaceholderText("e.g. 192.168.1.23:41234")
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("6 digits")
        self.code_edit.setMaxLength(7)
        form.addRow("Address from the pairing window:", self.addr_edit)
        form.addRow("Pairing code:", self.code_edit)
        cl.addLayout(form)
        self.pair_btn = QPushButton("Pair")
        self.pair_btn.clicked.connect(self._pair_code)
        cl.addWidget(self.pair_btn, 0, Qt.AlignRight)
        self.tabs.addTab(code_w, "Pairing code")
        lay.addWidget(self.tabs, 1)

        # --- already paired: connect by address
        ml = QHBoxLayout()
        self.conn_edit = QLineEdit(cfg.get("wifi_last_address", ""))
        self.conn_edit.setPlaceholderText("IP address & port from the Wireless debugging screen")
        b = QPushButton("Connect")
        b.clicked.connect(self._connect_manual)
        ml.addWidget(QLabel("Already paired – connect to:"))
        ml.addWidget(self.conn_edit, 1)
        ml.addWidget(b)
        lay.addLayout(ml)

        self.status = _label(_status_html("Waiting for the phone …", GRAY))
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
                            "QR code scanned – pairing …")
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
            return False, f"Pairing failed: {msg}", ""
        ip = address.rsplit(":", 1)[0]
        # after pairing the phone announces its connect port (differs from the pairing port)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            for s in wireless.mdns_services(self.adb):
                if s.kind == wireless.CONNECT and s.address.rsplit(":", 1)[0] == ip:
                    cok, cmsg = wireless.connect(self.adb, s.address)
                    if cok:
                        return True, "Paired and connected.", s.address
            time.sleep(1)
        return True, ("Paired. Now enter the address shown at the top of the Wireless debugging "
                      "screen (IP address & port) below and click Connect."), ""

    def _do_connect(self, address):
        if not wireless.valid_address(address):
            return False, "The address must look like 192.168.1.23:37123 (IP address and port).", ""
        ok, msg = wireless.connect(self.adb, address)
        return ok, ("Connected." if ok else f"Could not connect: {msg}"), (address if ok else "")

    def _pair_code(self):
        code = self.code_edit.text().strip().replace(" ", "")
        if not code.isdigit() or len(code) != 6:
            self.status.setText(_status_html("The pairing code has 6 digits.", RED))
            return
        addr = self.addr_edit.text().strip()
        self._start(lambda: self._do_pair(addr, code), "Pairing …")

    def _connect_manual(self):
        addr = self.conn_edit.text().strip()
        self._start(lambda: self._do_connect(addr), "Connecting …")

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
        self.setWindowTitle("Direct Wi-Fi (no router)")
        self.resize(600, 560)
        lay = QVBoxLayout(self)
        win = sys.platform.startswith("win")
        lay.addWidget(_label(
            "The computer opens <b>its own Wi-Fi network</b> and the phone joins it – a direct "
            "phone ↔ computer connection, no router or internet needed (e.g. on the road)."
            "<br><span style='color:%s'>While it is on, this computer may lose its normal Wi-Fi "
            "(most Wi-Fi adapters can do only one at a time). It comes back when you stop the "
            "direct Wi-Fi.</span>" % ORANGE))

        if not cfg.get("hotspot_ssid") or not cfg.get("hotspot_password"):
            cfg["hotspot_ssid"], cfg["hotspot_password"] = wireless.new_hotspot_credentials()
            config.save(cfg)
        ssid, pw = cfg["hotspot_ssid"], cfg["hotspot_password"]

        if win:
            lay.addWidget(_label(
                "<b>Windows:</b> switch on <b>Mobile hotspot</b> in the Windows settings "
                "(button below) and connect the phone to the network name and password shown there."))
            b = QPushButton("Open Mobile hotspot settings")
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
                f"Network: <b style='font-size:15pt'>{html.escape(ssid)}</b><br>"
                f"Password: <b style='font-size:15pt;font-family:monospace'>{html.escape(pw)}</b><br><br>"
                "Join it with the phone: scan the QR code with the camera, or choose the network "
                "in the phone's Wi-Fi settings. The phone remembers it for next time."), 1)
            lay.addLayout(row)
            br = QHBoxLayout()
            self.start_btn = QPushButton("Start direct Wi-Fi")
            self.start_btn.clicked.connect(self._start)
            self.stop_btn = QPushButton("Stop direct Wi-Fi")
            self.stop_btn.clicked.connect(self._stop)
            br.addWidget(self.start_btn)
            br.addWidget(self.stop_btn)
            br.addStretch()
            lay.addLayout(br)

        lay.addWidget(_label(
            "<b>Then on the phone:</b><ol>"
            f"<li>{WD_PATH} → on (tap <i>Allow</i> for this network).</li>"
            "<li>First time only: pair the phone (button below).</li>"
            "<li>The phone is found automatically – start the backup as usual.</li></ol>"
            "Tip: keep the phone close to the computer and plugged into a charger for large backups."))
        pb = QPushButton("Pair phone over Wi-Fi…")
        pb.clicked.connect(self.on_pair)
        lay.addWidget(pb, 0, Qt.AlignLeft)

        self.status = _label("")
        lay.addWidget(self.status)
        lay.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.result_ready.connect(self._on_result)
        if not win:
            self._refresh()

    def _refresh(self):
        active = wireless.hotspot_active()
        self.start_btn.setEnabled(not active)
        self.stop_btn.setEnabled(active)
        if active:
            self.status.setText(_status_html("Direct Wi-Fi is ON.", GREEN))
        else:
            self.status.setText(_status_html("Direct Wi-Fi is off.", GRAY))

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
        self._run(lambda: wireless.start_hotspot(ssid, pw), "Starting direct Wi-Fi … (up to a minute)")

    def _stop(self):
        self._run(wireless.stop_hotspot, "Stopping direct Wi-Fi …")

    def _on_result(self, ok, msg):
        self._refresh()
        if not ok:
            self.status.setText(_status_html(f"Did not work: {msg}", RED))
        elif msg:
            self.status.setText(_status_html(msg, GREEN))


class PhoneAppDialog(QDialog):
    """Set up the phone app: QR code → setup page on this computer → install → pair."""

    pair_request = Signal(object)
    claimed = Signal(object, str)        # entry or None, error

    def __init__(self, parent, cfg):
        super().__init__(parent)
        from . import companion
        self.companion = companion
        self.cfg = cfg
        self.paired = None
        self.req = None
        self.setWindowTitle("Set up phone app")
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        lay.addWidget(_label(
            "The phone app <b>My Media Backup</b> backs up without USB debugging or developer options. "
            "It may only <b>read photos and videos</b> – nothing else – and the connection is "
            "encrypted. Phone and computer must be in the same Wi-Fi (or the phone in the computer's "
            "Direct Wi-Fi)."))
        self.server = companion.SetupServer(cfg, lambda r: self.pair_request.emit(r))
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
                "<b>Scan with the phone's camera</b> and open the link. The page offers:<ol>"
                "<li><b>Download the app</b> – then open the file and tap <i>Install</i> "
                "(Android asks once to allow installs from the browser).</li>"
                "<li><b>Connect app with this computer</b> – the app opens and shows a code.</li></ol>"
                f"Link (to type it in): <tt>{html.escape(self.server.page_url)}</tt>"
                + ("" if self.server.apk else
                   f"<br><span style='color:{RED}'>The app file is missing in this program "
                   "(assets/companion/MediaBackup.apk) – only pairing works.</span>")), 1)
        else:
            row.addWidget(_label(_status_html(f"Could not start: {err}", RED)))
        lay.addLayout(row)

        self.code_box = QWidget()
        cl = QVBoxLayout(self.code_box)
        self.code_label = _label("")
        cl.addWidget(self.code_label)
        br = QHBoxLayout()
        self.ok_btn = QPushButton("Same code – pair")
        self.ok_btn.clicked.connect(self._confirm)
        no = QPushButton("Different code – refuse")
        no.clicked.connect(self._refuse)
        br.addWidget(self.ok_btn)
        br.addWidget(no)
        br.addStretch()
        cl.addLayout(br)
        self.code_box.hide()
        lay.addWidget(self.code_box)

        self.status = _label(_status_html("Waiting for the phone …", GRAY))
        lay.addWidget(self.status)

        paired = companion.phones(cfg)
        if paired:
            lay.addWidget(_label("<b>Paired phones:</b> " + ", ".join(
                html.escape(p.get("name", "?")) for p in paired)))
        lay.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.pair_request.connect(self._on_request)
        self.claimed.connect(self._on_claimed)

    def _on_request(self, req):
        self.req = req
        code = req.code[:3] + " " + req.code[3:]
        self.code_label.setText(
            f"<b>{html.escape((req.manufacturer + ' ' + req.model).strip())}</b> wants to pair.<br>"
            f"Code: <span style='font-size:28pt;font-family:monospace;font-weight:700'>{code}</span><br>"
            "Does the phone show <b>exactly the same code</b>?")
        self.code_box.show()
        self.ok_btn.setEnabled(True)
        self.status.setText("")

    def _confirm(self):
        req = self.req
        if req is None:
            return
        self.ok_btn.setEnabled(False)
        self.status.setText(_status_html("Now tap “Same code – Pair” on the phone too …", GRAY))

        def run():
            try:
                self.claimed.emit(self.server.claim(req), "")
            except Exception as e:  # noqa: BLE001
                self.claimed.emit(None, str(e))

        threading.Thread(target=run, daemon=True).start()

    def _refuse(self):
        self.req = None
        self.code_box.hide()
        self.status.setText(_status_html("Refused. Somebody else may have tried to pair – "
                                         "close this window and start again.", RED))

    def _on_claimed(self, entry, err):
        self.code_box.hide()
        if entry:
            self.paired = entry
            self.status.setText(_status_html(f"Paired with {entry['name']}. The phone is now in "
                                             "backup mode and will be connected.", GREEN))
            QTimer.singleShot(1500, self.accept)
        else:
            self.status.setText(_status_html(f"Pairing failed: {err}", RED))

    def done(self, r):
        self.server.stop()
        super().done(r)
