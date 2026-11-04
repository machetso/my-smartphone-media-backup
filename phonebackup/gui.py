"""Graphical interface (PySide6 / Qt).

All long work (connecting, backup, export, restore) runs in ONE background worker
thread, so the window never freezes. Questions from the backend (e.g. "drive almost
full - continue?") are shown as dialogs in the main thread via ui.set_handler().
"""

import html
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea, QSpinBox,
                               QSplitter, QStackedWidget, QStyle, QTabWidget, QTextEdit, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import APP_NAME, __version__, config, ui
from .keepawake import KeepAwake, windows_block_shutdown
from .backup import backup_parent_name, perform_backup
from .export import Catalog, has_catalog, perform_export, perform_restore
from .importer import (CAMERA, OTHER, check_selection, guess_kind, perform_old_phone_import,
                       perform_selection_import, scan_folder)
from .layout import same_volume
from .locations import (describe_unmounted, detect_drives, detect_unmounted, drive_label_of,
                        find_backups, find_export_sets, free_space, is_backup_folder,
                        mount_device, mount_for_paths)
from .sources import AdbSource, adb_devices, connect_source, find_adb
from . import adbsetup, lastbackup, phoneid, wireless
from .companion import (AppGuard, CompanionSource, apk_path, ble_scan, find_phone,
                        link_over_cable, pair_over_cable, phones as paired_phones, _port_open)
from .gui_setup import ConnectionOverview, UsbDebugGuide

PHONE_FOLDER_ROOTS = ["DCIM", "Pictures", "Movies", "Download",
                      "Android/media/com.whatsapp/WhatsApp/Media"]
CAMERA_FOLDER = "DCIM/Camera"       # Android's standard camera folder (almost every phone)

GREEN, ORANGE, RED, GRAY = "#1f8a4c", "#c76a00", "#c62828", "#808080"


DESKTOP_ID = "fast-smartphone-media-backup"   # matches the .desktop file / icon name on Linux


def app_icon():
    """The app icon from assets/ (next to the code, or inside the PyInstaller program)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for name in ("icon.ico", "icon.png") if sys.platform.startswith("win") else ("icon.png",):
        p = base / "assets" / name
        if p.is_file():
            return QIcon(str(p))
    return QIcon()


def _com_init():
    """Windows MTP fallback uses COM - initialise it in the worker thread."""
    if sys.platform.startswith("win"):
        try:
            import pythoncom  # type: ignore
            pythoncom.CoInitialize()
        except ImportError:
            pass


# =========================================================================== bridge

class Request:
    def __init__(self, kind, args):
        self.kind, self.args = kind, args
        self.event = threading.Event()
        self.result = None


class Bridge(QObject):
    log = Signal(str, str)
    progress = Signal(dict)
    request = Signal(object)
    done = Signal(object, object, object, bool)
    adb_state = Signal(object)
    companion_found = Signal(object)
    companion_lost = Signal()
    ble_seen = Signal(object)


class GuiHandler:
    """Receives ui.* calls from the worker thread and forwards them to the window."""

    def __init__(self, window):
        self.w = window

    def log(self, level, text):
        self.w.bridge.log.emit(level, str(text))

    def progress(self, d):
        self.w.bridge.progress.emit(d)

    def _ask(self, kind, *args):
        if threading.current_thread() is threading.main_thread():
            return self.w.answer(kind, args)
        req = Request(kind, args)
        self.w.bridge.request.emit(req)
        req.event.wait()
        return req.result

    def ask(self, prompt, default=None):
        return self._ask("text", prompt, default)

    def ask_yes_no(self, prompt, default=True):
        return self._ask("yesno", prompt, default)

    def choose(self, prompt, options, default=1):
        return self._ask("choose", prompt, options, default)

    def ask_directory(self, prompt):
        return self._ask("dir", prompt)


# =========================================================================== widgets

class LocationList(QWidget):
    """List of saved folders on drives. multi=True: tick several; False: select one."""
    changed = Signal()

    def __init__(self, cfg, key, sel_key, multi, default_folder, hint):
        super().__init__()
        self.cfg, self.key, self.sel_key = cfg, key, sel_key
        self.multi, self.default_folder = multi, default_folder
        self.cfg.setdefault(sel_key, list(cfg.get(key, [])) if multi else cfg.get(key, [])[:1])
        self._updating = False

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Folder", "Status", "Free space"])
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumHeight(110)
        # long folder names: the column is as wide as the name and the list scrolls sideways;
        # status and free space only as wide as needed (user request 2026-11-04)
        h = self.tree.header()
        h.setStretchLastSection(False)
        for col in (0, 1, 2):
            h.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setTextElideMode(Qt.ElideNone)
        self.tree.setMinimumWidth(150)       # the page must not grow with long names
        if multi:
            self.tree.itemChanged.connect(self._check_changed)
        else:
            self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
            self.tree.itemSelectionChanged.connect(self._selection_changed)

        self.btn_drive = QPushButton("Add drive…")
        self.drive_menu = QMenu(self.btn_drive)
        self.drive_menu.aboutToShow.connect(self._fill_drive_menu)
        self.btn_drive.setMenu(self.drive_menu)
        btn_folder = QPushButton("Add folder…")
        btn_folder.clicked.connect(self._add_folder)
        btn_remove = QPushButton("Remove from list")
        btn_remove.clicked.connect(self._remove)

        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_drive)
        buttons.addWidget(btn_folder)
        buttons.addWidget(btn_remove)
        buttons.addStretch()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        if hint:
            lab = QLabel(hint)
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color:{GRAY}")
            lay.addWidget(lab)
        lay.addWidget(self.tree)
        lay.addLayout(buttons)
        self.rebuild()

    # ---- data
    def paths(self):
        return list(self.cfg.get(self.key, []))

    def selected_paths(self):
        return [p for p in self.cfg.get(self.sel_key, []) if p in self.paths()]

    def selected_available(self):
        return [p for p in self.selected_paths() if os.path.isdir(p)]

    # ---- view
    def rebuild(self):
        self._updating = True
        self.tree.clear()
        sel = set(self.selected_paths())
        for p in self.paths():
            it = QTreeWidgetItem([p, "", ""])
            it.setData(0, Qt.UserRole, p)
            it.setToolTip(0, p)
            if self.multi:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked if p in sel else Qt.Unchecked)
            self.tree.addTopLevelItem(it)
            if not self.multi and p in sel:
                it.setSelected(True)
        self._updating = False
        self.update_status()

    def update_status(self):
        self._updating = True       # setText/setForeground also fire itemChanged
        unmounted_labels = None
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            p = it.data(0, Qt.UserRole)
            avail = os.path.isdir(p)
            free = free_space(p) if avail else None
            status, color = ("connected", GREEN) if avail else ("not connected", GRAY)
            if not avail:
                if unmounted_labels is None:
                    unmounted_labels = {d["label"] for d in detect_unmounted()}
                if drive_label_of(p) in unmounted_labels:
                    status, color = "attached, not mounted (mounted automatically at start)", ORANGE
            it.setText(1, status)
            it.setForeground(1, QColor(color))
            it.setForeground(0, QColor(self.palette().text().color() if avail else QColor(GRAY)))
            it.setText(2, ui.human_size(free) if free is not None else "–")
        self._updating = False

    # ---- events
    def _store_selection(self, sel):
        self.cfg[self.sel_key] = sel
        config.save(self.cfg)
        self.changed.emit()

    def _check_changed(self, _item, _col):
        if self._updating:
            return
        sel = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.checkState(0) == Qt.Checked:
                sel.append(it.data(0, Qt.UserRole))
        self._store_selection(sel)

    def _selection_changed(self):
        if self._updating:
            return
        sel = [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()][:1]
        self._store_selection(sel)

    def _fill_drive_menu(self):
        self.drive_menu.clear()
        drives = detect_drives()
        unmounted = detect_unmounted()
        if not drives and not unmounted:
            a = self.drive_menu.addAction("No external drive found – plug one in")
            a.setEnabled(False)
        for p, free in drives:
            a = self.drive_menu.addAction(f"{p}    ({ui.human_size(free)} free)")
            a.triggered.connect(lambda _checked=False, p=p: self._add_on_drive(p))
        if unmounted:
            self.drive_menu.addSection("Attached but not mounted – click to mount")
            for d in unmounted:
                a = self.drive_menu.addAction(describe_unmounted(d))
                a.triggered.connect(lambda _checked=False, d=d: self._mount_and_add(d))

    def _mount_and_add(self, d):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            mountpoint, err = mount_device(d["device"])
        finally:
            QApplication.restoreOverrideCursor()
        name = d["label"] or d["device"]
        if not mountpoint:
            QMessageBox.critical(self, "Mount failed", f"The drive “{name}” could not be mounted:\n\n{err}")
            return
        ui.ok(f"Drive “{name}” mounted at {mountpoint}")
        if not os.access(mountpoint, os.W_OK):
            QMessageBox.warning(
                self, "Drive is read-only",
                f"“{name}” was mounted READ-ONLY, so no backup can be written to it.\n\n"
                "For NTFS drives this usually means Windows did not shut the drive down cleanly "
                "(Fast Startup / hibernation). Connect it to Windows, run “chkdsk /f”, and use "
                "“Safely remove” – or switch off Fast Startup in Windows.")
            return
        self._add_on_drive(mountpoint)

    def _add_on_drive(self, drive):
        name, ok = QInputDialog.getText(self, "Backup folder on the drive",
                                        f"Name of the folder on {drive}:", text=self.default_folder)
        if ok and name.strip():
            self._add(os.path.join(drive, name.strip()))

    def _add_folder(self):
        drives = detect_drives()
        start = drives[0][0] if drives else str(Path.home())
        p = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        if p:
            self._add(p)

    def _add(self, path):
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Cannot create the folder:\n{path}\n\n{e}")
            return
        path = str(Path(path).resolve())
        lst = self.paths()
        if path not in lst:
            lst.append(path)
        self.cfg[self.key] = lst
        sel = self.selected_paths()
        if self.multi:
            if path not in sel:
                sel.append(path)
        else:
            sel = [path]
        self.cfg[self.sel_key] = sel
        config.save(self.cfg)
        self.rebuild()
        self.changed.emit()

    def _remove(self):
        it = self.tree.currentItem()
        if it is None:
            QMessageBox.information(self, APP_NAME, "Click a folder in the list first.")
            return
        p = it.data(0, Qt.UserRole)
        if QMessageBox.question(self, "Remove from list",
                                f"Remove this folder from the list?\n\n{p}\n\n"
                                "The files on the drive are NOT deleted.") != QMessageBox.Yes:
            return
        self.cfg[self.key] = [x for x in self.paths() if x != p]
        self.cfg[self.sel_key] = [x for x in self.cfg.get(self.sel_key, []) if x != p]
        config.save(self.cfg)
        self.rebuild()
        self.changed.emit()


def _split_by_phone(folders, on_phone):
    """(folders that exist on the phone, folders that do not). A folder below a folder of the
    phone (typed by hand, e.g. DCIM/Camera/Trip) counts as existing."""
    have = set(on_phone)
    keep, drop = [], []
    for f in folders:
        ok = f in have or any(f.startswith(h + "/") for h in have)
        (keep if ok else drop).append(f)
    return keep, drop


class FolderDialog(QDialog):
    """Tick the phone folders to back up, or type a folder path."""

    def __init__(self, parent, candidates, current, connected):
        super().__init__(parent)
        self.setWindowTitle("Folders on the phone")
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        info = ("Tick the folders to back up. Paths are inside the phone's internal storage."
                if connected else
                "The phone is not connected, so its folders cannot be listed. "
                "You can still type a folder path, e.g. Pictures/Screenshots.")
        lab = QLabel(info)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.list = QListWidget()
        for c in sorted(set(candidates) | set(current)):
            self._add_item(c, c in current)
        lay.addWidget(self.list)
        sel = QHBoxLayout()
        for text, on in (("Select all", True), ("Select none", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, on=on: self._tick_all(on))
            sel.addWidget(b)
        sel.addStretch()
        lay.addLayout(sel)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Other folder, e.g. Pictures/Screenshots")
        add = QPushButton("Add")
        add.clicked.connect(self._add_typed)
        self.edit.returnPressed.connect(self._add_typed)
        row.addWidget(self.edit)
        row.addWidget(add)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add_item(self, text, checked):
        it = QListWidgetItem(text)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.list.addItem(it)

    def _tick_all(self, on):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _add_typed(self):
        p = self.edit.text().strip().strip("/").strip("\\")
        if p.startswith("sdcard/"):
            p = p[len("sdcard/"):]
        if p:
            self._add_item(p, True)
            self.edit.clear()

    def folders(self):
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


class ImportSelectionDialog(QDialog):
    """Tick the folders of an old phone / old backup to import and choose how each is sorted."""

    KINDS = [(CAMERA, "Camera → month folders"), (OTHER, "Other → other/… (original folder)")]

    def __init__(self, parent, scans, choices):
        """scans: {root: [FolderInfo]}, choices: {root: {rel: kind}} (the current selection)."""
        super().__init__(parent)
        self.setWindowTitle("Choose folders to import")
        self.resize(980, 600)
        self.scans = scans
        lay = QVBoxLayout(self)
        lab = QLabel(
            "Every folder that contains files is listed (app data, caches, thumbnails, trash and hidden "
            "folders are left out). Each ticked folder is imported with its own files; its sub-folders "
            "are separate lines. <b>Camera</b> folders go into the year/month folders, <b>Other</b> folders "
            "keep their original folder name under <i>year/other/pictures | movies | other-files</i>.")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Folder", "Photos", "Videos", "Other files", "Size", "Sort as", "Note"])
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 7):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        lay.addWidget(self.tree, 1)
        self.combos = {}
        for root, infos in scans.items():
            top = QTreeWidgetItem([root])
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            top.setFirstColumnSpanned(True)
            chosen = choices.get(root, {})
            for info in infos:
                it = QTreeWidgetItem(["(this folder itself)" if info.rel == "." else info.rel,
                                      str(info.photos), str(info.videos), str(info.other),
                                      ui.human_size(info.size), "", info.note])
                for c in (1, 2, 3, 4):
                    it.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked if info.rel in chosen else Qt.Unchecked)
                it.setData(0, Qt.UserRole, (root, info.rel))
                top.addChild(it)
                cb = QComboBox()
                for k, text in self.KINDS:
                    cb.addItem(text, k)
                cb.setCurrentIndex(0 if chosen.get(info.rel, info.kind) == CAMERA else 1)
                self.tree.setItemWidget(it, 5, cb)
                self.combos[(root, info.rel)] = (it, cb, info)
            if not infos:
                top.addChild(QTreeWidgetItem(["no files found in this folder"]))
            top.setExpanded(True)

        row = QHBoxLayout()
        for text, fn in (("Suggested", self._suggested), ("Tick all", lambda: self._tick(True)),
                         ("Untick all", lambda: self._tick(False))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        self.summary = QLabel()
        row.addWidget(self.summary)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.tree.itemChanged.connect(lambda *_: self._update_summary())
        self._update_summary()

    def _suggested(self):
        for it, cb, info in self.combos.values():
            it.setCheckState(0, Qt.Checked if info.suggested else Qt.Unchecked)
            cb.setCurrentIndex(0 if info.kind == CAMERA else 1)

    def _tick(self, on):
        for it, _cb, _info in self.combos.values():
            it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)

    def _update_summary(self):
        ticked = [info for it, _cb, info in self.combos.values() if it.checkState(0) == Qt.Checked]
        self.summary.setText(f"{len(ticked)} folders ticked, {sum(i.files for i in ticked)} files, "
                             f"{ui.human_size(sum(i.size for i in ticked))}")

    def choices(self):
        out = {root: {} for root in self.scans}
        for (root, rel), (it, cb, _info) in self.combos.items():
            if it.checkState(0) == Qt.Checked:
                out[root][rel] = cb.currentData()
        return out


def _group(title, widget_or_layout):
    g = QGroupBox(title)
    if isinstance(widget_or_layout, QWidget):
        lay = QVBoxLayout(g)
        lay.addWidget(widget_or_layout)
    else:
        g.setLayout(widget_or_layout)
    return g


def _big_button(text):
    b = QPushButton(text)
    b.setMinimumHeight(40)
    b.setStyleSheet("QPushButton{font-weight:600;font-size:15px;padding:6px 22px}")
    return b


# =========================================================================== main window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = config.load()
        self.bridge = Bridge()
        self.bridge.log.connect(self._on_log)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.request.connect(self._on_request)
        self.bridge.done.connect(self._on_done)
        self.bridge.adb_state.connect(self._on_adb_state)
        self.bridge.companion_found.connect(self._on_companion_found)
        self.bridge.companion_lost.connect(self._on_companion_lost)
        self.bridge.ble_seen.connect(self._on_ble_seen)
        ui.set_handler(GuiHandler(self))

        self.executor = ThreadPoolExecutor(max_workers=1, initializer=_com_init)
        self.cancel_event = threading.Event()
        self.busy = False
        self.connecting = False
        self.source = None
        self.last_report = None
        self.last_folder = None
        self._close_when_idle = False
        self._adb_retry_at = 0.0
        self._stop = threading.Event()

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        icon = app_icon()
        self.setWindowIcon(icon if not icon.isNull() else self.style().standardIcon(QStyle.SP_DriveHDIcon))
        self.resize(1040, 860)

        # start screen → backup settings (subpage) / more (the other tabs)  - user request 2026-11-04
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_import_tab(), "Import old backup")
        self.tabs.addTab(self._build_export_tab(), "Second storage (export)")
        self.tabs.addTab(self._build_restore_tab(), "Restore")
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.pages = QStackedWidget()
        self.home_page = self._build_home()
        self.backup_page = self._build_backup_page()
        self.more_page = self._subpage("More", self.tabs)
        for page in (self.home_page, self.backup_page, self.more_page):
            self.pages.addWidget(page)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.pages)
        splitter.addWidget(self._build_bottom())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 200])
        self.setCentralWidget(splitter)
        self._phone_status_text = ("Looking for a phone …", GRAY)
        self._set_phone_status("Looking for a phone …", GRAY)
        self._companion_asked = set()
        self._auto_phone_name = ""        # the name the program filled in itself (may be replaced)
        if "backup_profiles" not in self.cfg:     # first start with folder lists per backup
            lb = lastbackup.get(self.cfg)
            self.cfg["backup_profiles"] = ({backup_parent_name(lb["phone"], lb.get("owner", "")): {
                "folders": list(lb["folders"]), "keep_structure": bool(lb.get("keep_structure"))}}
                if lb else {})
            config.save(self.cfg)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._periodic)
        self.timer.start(3000)
        threading.Thread(target=self._adb_poller, daemon=True).start()
        lastbackup.discover(self.cfg)          # backups on the drives made before the phone list
        self._update_preview()
        self._update_home()

    # ------------------------------------------------------------------ tabs
    def _subpage(self, title, content, scroll=False):
        """A page with '← Back' and a title above `content`."""
        w = QWidget()
        lay = QVBoxLayout(w)
        head = QHBoxLayout()
        back = QPushButton("← Back")
        back.clicked.connect(self._go_home)
        lab = QLabel(title)
        lab.setStyleSheet("font-size:17px;font-weight:600")
        head.addWidget(back)
        head.addSpacing(10)
        head.addWidget(lab, 1)
        lay.addLayout(head)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            area.setFrameShape(QScrollArea.NoFrame)
            area.setWidget(content)
            content = area
        lay.addWidget(content, 1)
        w.title_label = lab
        return w

    def _build_home(self):
        """Start screen: your phones (one backup each, with its own "Update backup" button),
        "New backup…", "Backup settings…" and the other functions. No folder lists here."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 18, 24, 12)
        name = QLabel(APP_NAME)
        name.setStyleSheet("font-size:22px;font-weight:700")
        lay.addWidget(name)
        self.home_status = QLabel()
        self.home_status.setWordWrap(True)
        self.home_status.setTextFormat(Qt.RichText)
        lay.addWidget(self.home_status)
        lay.addSpacing(8)

        self.phone_rows = QVBoxLayout()
        self.phone_rows.setSpacing(10)
        box = QVBoxLayout()
        box.addLayout(self.phone_rows)
        box.addStretch()
        area_w = QWidget()
        area_w.setLayout(box)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(area_w)
        pl = QVBoxLayout()
        pl.addWidget(area)
        prow = QHBoxLayout()
        sel_all = QPushButton("Select all")
        sel_all.clicked.connect(lambda: [w.pick.setChecked(True) for w in self._phone_widgets.values()])
        rm = QPushButton("Remove from list")
        rm.setToolTip("Removes the ticked phones from this list. Their backups on the drives are NOT "
                      "deleted; a new backup of the phone adds it again.")
        rm.clicked.connect(self._remove_phones)
        prow.addWidget(sel_all)
        prow.addWidget(rm)
        prow.addStretch()
        pl.addLayout(prow)
        lay.addWidget(_group("Your phones", pl), 1)
        self._phone_widgets = {}
        lay.addSpacing(8)

        row = QHBoxLayout()
        new = _big_button("New backup…")
        new.setToolTip("Another phone, or other folders / drives: choose the connection, folders and "
                       "drives, then start.")
        new.clicked.connect(lambda: self._open_backup_page(True))
        settings = QPushButton("Backup settings…")
        settings.setMinimumHeight(40)
        settings.clicked.connect(lambda: self._open_backup_page(False))
        more = QPushButton("Import, export, restore…")
        more.setMinimumHeight(40)
        more.setToolTip("Import old backups, copy backups to a second storage (export), restore, "
                        "program settings.")
        more.clicked.connect(lambda: self.pages.setCurrentWidget(self.more_page))
        row.addWidget(new)
        row.addWidget(settings)
        row.addStretch()
        row.addWidget(more)
        lay.addLayout(row)
        return w

    def _go_home(self):
        self.pages.setCurrentWidget(self.home_page)
        self._update_home()

    def _open_backup_page(self, new_backup):
        self.backup_page.title_label.setText("New backup" if new_backup else "Backup settings")
        self.start_backup_btn.setVisible(new_backup)
        self.dest_list.update_status()
        self._update_preview()
        self.pages.setCurrentWidget(self.backup_page)

    def _build_backup_page(self):
        # two columns, so everything is visible without scrolling (user request 2026-11-04):
        # left = who + phone connection, right = folders + destinations + start
        w = QWidget()
        cols = QHBoxLayout(w)
        lay = QVBoxLayout()
        right = QVBoxLayout()
        cols.addLayout(lay, 1)
        cols.addLayout(right, 1)

        form = QFormLayout()
        self.owner_edit = QLineEdit(self.cfg.get("owner", ""))
        self.owner_edit.setPlaceholderText("e.g. Sam")
        self.owner_edit.textChanged.connect(self._update_preview)
        self.owner_edit.editingFinished.connect(self._load_profile)
        form.addRow("Owner:", self.owner_edit)
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("filled in automatically when the phone is connected")
        self.phone_edit.textChanged.connect(self._update_preview)
        self.phone_edit.editingFinished.connect(self._load_profile)
        form.addRow("Smartphone name:", self.phone_edit)
        lay.addWidget(_group("Who and which phone", form))

        phone_box = QVBoxLayout()
        self.phone_status = QLabel()
        self.phone_status.setWordWrap(True)
        self.phone_status.setTextFormat(Qt.RichText)
        phone_box.addWidget(self.phone_status)
        self.conn_overview = ConnectionOverview()
        self.conn_overview.setToolTip("The program always uses the fastest connection it finds.")
        phone_box.addWidget(self.conn_overview)
        self.debug_off_check = QCheckBox("Switch USB debugging / Wireless debugging off on the phone "
                                         "after the backup")
        self.debug_off_check.setChecked(bool(self.cfg.get("debugging_off_after", True)))
        self.debug_off_check.toggled.connect(self._debug_off_changed)
        phone_box.addWidget(self.debug_off_check)
        self.connect_btn = QPushButton("Connect phone")
        self.connect_btn.setToolTip("Tries ADB first; if that does not work, the MTP fallback.")
        self.connect_btn.clicked.connect(self._connect_manual)
        self.guide_btn = QPushButton("Switch on USB debugging (first time)…")
        self.guide_btn.setToolTip("Step-by-step guide for your phone.")
        self.guide_btn.clicked.connect(self._show_usb_guide)
        self.wifi_pair_btn = QPushButton("Pair over Wi-Fi…")
        self.wifi_pair_btn.setToolTip("Back up without a cable: Android's Wireless debugging "
                                      "(Android 11+). Pair once, then the phone is found "
                                      "automatically in the same Wi-Fi.")
        self.wifi_pair_btn.clicked.connect(self._pair_wifi)
        self.hotspot_btn = QPushButton("Direct Wi-Fi…")
        self.hotspot_btn.setToolTip("No router? The computer opens its own Wi-Fi network and the "
                                    "phone joins it directly.")
        self.hotspot_btn.clicked.connect(self._direct_wifi)
        self.app_btn = QPushButton("Set up phone app over Wi-Fi…")
        self.app_btn.setToolTip("Phone app 'Fast Media Backup': backups over Wi-Fi without USB debugging. "
                                "It may only read photos and videos.")
        self.app_btn.clicked.connect(self._setup_phone_app)
        self.fastest_btn = QPushButton("Find the fastest connection")
        self.fastest_btn.setStyleSheet("QPushButton{font-weight:600}")
        self.fastest_btn.setToolTip("Checks the USB cable, the Wi-Fi and Bluetooth and uses the fastest "
                                    "connection – and says what would make it faster.")
        self.fastest_btn.clicked.connect(self._find_fastest)
        self.connect_btn.setText("Connect via file transfer (MTP)")
        self.connect_btn.setToolTip("Only if nothing else works: the phone's normal file transfer "
                                    "(slower, no check on the phone).")
        self.app_btn.setText("Phone app over Wi-Fi…")
        self.connect_btn.setText("File transfer (MTP)")
        for row in ((self.fastest_btn, self.guide_btn),
                    (self.app_btn, self.wifi_pair_btn, self.hotspot_btn),
                    (self.connect_btn,)):
            btns = QHBoxLayout()
            for b in row:
                btns.addWidget(b)
            btns.addStretch()
            phone_box.addLayout(btns)
        lay.addWidget(_group("Phone connection", phone_box))

        fl = QHBoxLayout()
        self.folder_list = QListWidget()
        self.folder_list.setMaximumHeight(110)
        # several at once: Ctrl/Shift-click, "Select all" (user request 2026-11-04)
        self.folder_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.folder_list.setMinimumWidth(150)
        self._fill_folder_list()
        fbtn = QVBoxLayout()
        cam = QPushButton("Camera")
        cam.setToolTip(f"Adds the phone's camera folder ({CAMERA_FOLDER}) – the standard place "
                       "for photos and videos on Android.")
        cam.clicked.connect(self._add_camera_folder)
        b = QPushButton("Choose folders…")
        b.setToolTip("Other folders: screenshots, WhatsApp, downloads … (lists the phone's folders "
                     "when it is connected).")
        b.clicked.connect(self._choose_folders)
        sel_all = QPushButton("Select all")
        sel_all.setToolTip("Selects every folder in the list (then “Remove” removes them all).")
        sel_all.clicked.connect(self.folder_list.selectAll)
        rm = QPushButton("Remove")
        rm.setToolTip("Removes the selected folders from the list (several: Ctrl- or Shift-click, "
                      "or “Select all”). Nothing on the phone is changed.")
        rm.clicked.connect(self._remove_folder)
        for x in (cam, b, sel_all, rm):
            fbtn.addWidget(x)
        fbtn.addStretch()
        fl.addWidget(self.folder_list, 1)
        fl.addLayout(fbtn)
        fbox = QVBoxLayout()
        fbox.addLayout(fl)
        self.keep_structure_check = QCheckBox("Other folders than Camera: keep the phone's folder "
                                              "structure\n(e.g. Pictures/Screenshots/…) instead of "
                                              "sorting them into year/month folders")
        self.keep_structure_check.setToolTip(
            "On: files from folders like Pictures/Screenshots or WhatsApp land in the same folders "
            "in the backup (…/Pixel 10 Pro - Sam/Pictures/Screenshots/). The camera folder is always "
            "sorted into year/month folders. Files that were already backed up stay where they are.")
        self.keep_structure_check.setChecked(bool(self.cfg.get("keep_structure", False)))
        self.keep_structure_check.toggled.connect(self._keep_structure_changed)
        fbox.addWidget(self.keep_structure_check)
        right.addWidget(_group("Folders on the phone", fbox))

        self.dest_list = LocationList(
            self.cfg, "destinations", "selected_destinations", True, "PhoneBackups",
            "Tick one or more drives - all ticked drives are written at the same time. "
            "Use “Add drive…” for a connected external drive or “Add folder…” to pick any folder.")
        self.dest_list.changed.connect(self._update_preview)
        right.addWidget(_group("Backup destinations", self.dest_list), 1)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.addWidget(self.preview)

        self.start_backup_btn = _big_button("Start backup")
        self.start_backup_btn.clicked.connect(lambda: self._start_backup())
        right.addWidget(self.start_backup_btn, 0, Qt.AlignRight)
        lay.addStretch()
        return self._subpage("New backup", w, scroll=True)

    def _build_import_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.import_scans, self.import_choices = {}, {}

        mode_row = QHBoxLayout()
        self.imp_existing = QRadioButton("Add to an existing backup")
        self.imp_new = QRadioButton("New backup of an old phone")
        self.imp_existing.setChecked(True)
        grp = QButtonGroup(w)
        grp.addButton(self.imp_existing)
        grp.addButton(self.imp_new)
        self.imp_new.toggled.connect(self._import_mode_changed)
        mode_row.addWidget(self.imp_existing)
        mode_row.addWidget(self.imp_new)
        mode_row.addStretch()
        lay.addLayout(mode_row)
        self.import_info = QLabel()
        self.import_info.setWordWrap(True)
        self.import_info.setStyleSheet(f"color:{GRAY}")
        lay.addWidget(self.import_info)

        src = QVBoxLayout()
        self.import_roots = QTreeWidget()
        self.import_roots.setHeaderLabels(["Folder", "Selected"])
        self.import_roots.setRootIsDecorated(False)
        self.import_roots.setMaximumHeight(120)
        self.import_roots.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.import_roots.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.import_roots.itemDoubleClicked.connect(lambda *_: self._choose_import_folders())
        src.addWidget(self.import_roots)
        btns = QHBoxLayout()
        for text, fn in (("Add folder…", self._add_import_root), ("Remove", self._remove_import_root),
                         ("Choose folders to import…", self._choose_import_folders)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        src.addLayout(btns)
        self.import_other_check = QCheckBox(
            "Also import other files (documents, audio, …) – they keep their original folder "
            "under year/other/other-files")
        src.addWidget(self.import_other_check)
        lay.addWidget(_group("Folders to import (one or more, e.g. the old phone and its SD card)", src))

        # --- into an existing backup
        self.import_existing_box = QWidget()
        v = QVBoxLayout(self.import_existing_box)
        v.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.import_target = QComboBox()
        self.import_target.currentIndexChanged.connect(self._fill_import_copies)
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Search the saved backup drives again (attached drives are mounted)")
        refresh.clicked.connect(lambda: self._fill_import_targets(mount=True))
        top.addWidget(self.import_target, 1)
        top.addWidget(refresh)
        v.addLayout(top)
        hint = QLabel("Copies of this backup on your drives – all ticked copies are updated at the same time:")
        hint.setStyleSheet(f"color:{GRAY}")
        v.addWidget(hint)
        self.import_copies = QListWidget()
        v.addWidget(self.import_copies)
        lay.addWidget(_group("Import into backup", self.import_existing_box), 1)
        self.import_existing_group = self.import_existing_box.parentWidget()

        # --- as a new backup of an old phone
        self.import_new_box = QWidget()
        v = QVBoxLayout(self.import_new_box)
        v.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.import_phone_edit = QLineEdit()
        self.import_phone_edit.setPlaceholderText("e.g. Galaxy S7")
        self.import_owner_edit = QLineEdit(self.cfg.get("owner", ""))
        self.import_owner_edit.setPlaceholderText("e.g. Sam")
        form.addRow("Old phone name:", self.import_phone_edit)
        form.addRow("Owner:", self.import_owner_edit)
        v.addLayout(form)
        self.import_dest_list = LocationList(
            self.cfg, "destinations", "import_selected_destinations", True, "PhoneBackups",
            "Tick the drive(s) to write the old phone's backup to – all ticked drives at the same time.")
        self.import_dest_list.changed.connect(self._update_import_preview)
        v.addWidget(self.import_dest_list, 1)
        self.import_preview = QLabel()
        self.import_preview.setWordWrap(True)
        self.import_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.import_preview)
        self.import_phone_edit.textChanged.connect(self._update_import_preview)
        self.import_owner_edit.textChanged.connect(self._update_import_preview)
        lay.addWidget(_group("New backup", self.import_new_box), 1)
        self.import_new_group = self.import_new_box.parentWidget()

        self.start_import_btn = _big_button("Start import")
        self.start_import_btn.clicked.connect(self._start_import)
        lay.addWidget(self.start_import_btn, 0, Qt.AlignRight)
        self._import_mode_changed()
        self._fill_import_targets()
        return w

    def _import_new_mode(self):
        return self.imp_new.isChecked()

    def _import_mode_changed(self, *_):
        new = self._import_new_mode()
        self.import_existing_group.setVisible(not new)
        self.import_new_group.setVisible(new)
        self.import_other_check.setChecked(new)
        if new:
            self.import_info.setText(
                "Makes a backup of its own for an old phone (folder “Phone - Owner” on the drive). Add "
                "the copied folder(s) of the old phone, then choose which folders count: camera folders "
                "are sorted into year/month folders like a real phone backup, all other ticked folders "
                "(pictures, movies, other files) keep their original folder under year/other/. Every "
                "file is checked with SHA-256, identical files are stored only once, and the old folders "
                "are only read – never changed.")
        else:
            self.import_info.setText(
                "Adds the photos and videos of an old backup (or any folders) to one of your backups. "
                "Everything is sorted into the same year/month folders, every file is checked with "
                "SHA-256, identical files are stored only once (also against what is already in the "
                "backup), and the old folders are only read – never changed. Files that are not photos "
                "or videos are skipped and listed in the report (unless “Also import other files” is ticked).")
        # the suggestions differ between the two modes
        for root, infos in self.import_scans.items():
            for info in infos:
                guess_kind(info.rel, info, into_existing=not new)
            self.import_choices[root] = {i.rel: i.kind for i in infos if i.suggested}
        self._fill_import_roots()
        self._update_import_preview()

    def _fill_import_roots(self):
        self.import_roots.clear()
        if not self.import_scans:
            it = QTreeWidgetItem(["No folder added yet – click “Add folder…”", ""])
            it.setFlags(Qt.NoItemFlags)
            self.import_roots.addTopLevelItem(it)
        for root, infos in self.import_scans.items():
            chosen = self.import_choices.get(root, {})
            ticked = [i for i in infos if i.rel in chosen]
            cams = sum(1 for i in ticked if chosen[i.rel] == CAMERA)
            text = (f"{len(ticked)} of {len(infos)} folders ({cams} camera, {len(ticked) - cams} other), "
                    f"{sum(i.files for i in ticked)} files, {ui.human_size(sum(i.size for i in ticked))}")
            it = QTreeWidgetItem([root, text])
            it.setData(0, Qt.UserRole, root)
            self.import_roots.addTopLevelItem(it)

    def _scan_import_root(self, root):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ui.info(f"Reading the folders of {root} ...")
            QApplication.processEvents()
            infos = scan_folder(root, into_existing=not self._import_new_mode())
        finally:
            QApplication.restoreOverrideCursor()
        self.import_scans[root] = infos
        self.import_choices[root] = {i.rel: i.kind for i in infos if i.suggested}
        ui.info(f"  {len(infos)} folders with files, {len(self.import_choices[root])} suggested.")

    def _add_import_root(self):
        drives = detect_drives()
        start = next(iter(self.import_scans), None) or (drives[0][0] if drives else str(Path.home()))
        p = QFileDialog.getExistingDirectory(self, "Choose a folder to import (e.g. the copy of an old phone)",
                                             start)
        if not p:
            return
        p = str(Path(p).resolve())
        for other in self.import_scans:
            o = Path(other)
            if Path(p) == o or o in Path(p).parents or Path(p) in o.parents:
                QMessageBox.warning(self, "Folder already added",
                                    f"{p}\noverlaps with the folder already in the list:\n{other}\n\n"
                                    "Choose the sub-folders with “Choose folders to import…” instead.")
                return
        self._scan_import_root(p)
        self._fill_import_roots()
        self._choose_import_folders()

    def _remove_import_root(self):
        it = self.import_roots.currentItem()
        root = it.data(0, Qt.UserRole) if it else None
        if root:
            self.import_scans.pop(root, None)
            self.import_choices.pop(root, None)
            self._fill_import_roots()

    def _choose_import_folders(self):
        if not self.import_scans:
            self._add_import_root()
            return
        dlg = ImportSelectionDialog(self, self.import_scans, self.import_choices)
        if dlg.exec() == QDialog.Accepted:
            self.import_choices = dlg.choices()
            self._fill_import_roots()

    def _import_selections(self):
        return [(root, rel, kind) for root, chosen in self.import_choices.items()
                if root in self.import_scans for rel, kind in chosen.items()]

    def _update_import_preview(self):
        if not hasattr(self, "import_preview"):
            return
        phone = self.import_phone_edit.text().strip() or "<old phone>"
        owner = self.import_owner_edit.text().strip() or "<owner>"
        dests = self.import_dest_list.selected_paths()
        base = Path(dests[0]) if dests else Path("<drive>")
        parent = base / backup_parent_name(phone, owner)
        self.import_preview.setText(
            f"Camera folders → {parent / 'YEAR' / 'MM.Month-photos | -videos'}   (RAW → YEAR/raw/)\n"
            f"Other folders → {parent / 'YEAR' / 'other' / 'pictures | movies | other-files'}"
            f"/<original folder>")

    def _backup_sets(self):
        sets = {}
        for p in find_backups(self.cfg):
            sets.setdefault(Path(p).name, []).append(p)
        return sets

    def _fill_import_targets(self, mount=False):
        if mount:
            for m in mount_for_paths(self.cfg.get("destinations", [])):
                (ui.ok if m.startswith("Mounted") else ui.warn)(m)
        cur = self.import_target.currentText()
        self.import_target.blockSignals(True)
        self.import_target.clear()
        for name in sorted(self._backup_sets()):
            self.import_target.addItem(name)
        idx = self.import_target.findText(cur) if cur else -1
        self.import_target.setCurrentIndex(idx if idx >= 0 else 0)
        self.import_target.blockSignals(False)
        self._fill_import_copies()

    def _fill_import_copies(self):
        self.import_copies.clear()
        copies = self._backup_sets().get(self.import_target.currentText(), [])
        if not copies:
            it = QListWidgetItem("No backup found on the connected drives – make a phone backup first, "
                                 "or connect the drives and click Refresh.")
            it.setFlags(Qt.NoItemFlags)
            self.import_copies.addItem(it)
        for p in copies:
            it = QListWidgetItem(p)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, p)
            self.import_copies.addItem(it)

    def _start_import(self):
        sel = self._import_selections()
        other_files = self.import_other_check.isChecked()
        if not self.import_scans:
            QMessageBox.warning(self, "Cannot start yet", "Add the folder(s) to import.")
            return
        if not sel:
            QMessageBox.warning(self, "Cannot start yet",
                                "No folder is ticked – click “Choose folders to import…”.")
            return
        if self._import_new_mode():
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._mount_selected(self.import_dest_list)
            finally:
                QApplication.restoreOverrideCursor()
            phone = self.import_phone_edit.text().strip()
            owner = self.import_owner_edit.text().strip()
            dests = self.import_dest_list.selected_available()
            problems = []
            if not phone:
                problems.append("Enter the name of the old phone.")
            if not owner:
                problems.append("Enter the owner's name.")
            if not dests:
                problems.append("Tick at least one connected destination drive.")
            if problems:
                QMessageBox.warning(self, "Cannot start yet", "\n".join(problems))
                return
            name = backup_parent_name(phone, owner)
            try:
                check_selection(sel, [Path(d) / name for d in dests])
            except ValueError as e:
                QMessageBox.warning(self, "Cannot start yet", str(e))
                return
            existing = [d for d in dests if (Path(d) / name).is_dir()]
            if existing and QMessageBox.question(
                    self, "Backup already exists",
                    f"There is already a backup “{name}” on\n" + "\n".join(existing) +
                    "\n\nAdd the files to it? (Files already in it are not copied twice.)") \
                    != QMessageBox.Yes:
                return
            self.last_folder = str(Path(dests[0]) / name)
            ui.title(f"Import old phone {phone} – {owner}")
            self.run_job(lambda: perform_old_phone_import(sel, phone, owner, dests, self.cfg,
                                                          other_files=other_files, interactive=True,
                                                          cancel=self.cancel_event),
                         self._import_done, awake="Import")
            return

        parents = [self.import_copies.item(i).data(Qt.UserRole) for i in range(self.import_copies.count())
                   if self.import_copies.item(i).data(Qt.UserRole)
                   and self.import_copies.item(i).checkState() == Qt.Checked]
        try:
            check_selection(sel, parents)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot start yet", str(e))
            return
        self.last_folder = parents[0]
        ui.title(f"Import into {Path(parents[0]).name}")
        self.run_job(lambda: perform_selection_import(sel, parents, self.cfg, other_files=other_files,
                                                      interactive=True, cancel=self.cancel_event),
                     self._import_done, awake="Import")

    def _import_done(self, res):
        status, paths, _results, verdict = res
        self._finished(status, paths, verdict, "Import")
        self._fill_import_targets()
        self._fill_export_sources()

    def _build_export_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.export_src = QComboBox()
        self.export_src.currentIndexChanged.connect(self._refresh_export_info)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_export_src)
        row.addWidget(self.export_src, 1)
        row.addWidget(b)
        lay.addWidget(_group("Backup to export (folder “Phone - Owner” on the first drive)", row))

        self.export_targets = LocationList(
            self.cfg, "export_targets", "selected_export_target", False, "PhoneBackups-Export",
            "Click the drive/folder to export to (a different drive than the backup).")
        self.export_targets.changed.connect(self._refresh_export_info)
        lay.addWidget(_group("Second storage", self.export_targets), 1)

        mode_box = QVBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for i, (m, text) in enumerate([
                ("full", "Full – copy everything"),
                ("differential", "Differential – everything new since the last FULL export"),
                ("incremental", "Incremental – everything new since the LAST export (any type)")]):
            rb = QRadioButton(text)
            self.mode_group.addButton(rb, i)
            self.mode_buttons[m] = rb
            mode_box.addWidget(rb)
        self.mode_buttons["incremental"].setChecked(True)
        self.export_hint = QLabel()
        self.export_hint.setWordWrap(True)
        mode_box.addWidget(self.export_hint)
        lay.addWidget(_group("Export type", mode_box))

        self.export_runs = QListWidget()
        self.export_runs.setMaximumHeight(120)
        lay.addWidget(_group("Previous exports on this storage", self.export_runs))

        self.start_export_btn = _big_button("Start export")
        self.start_export_btn.clicked.connect(self._start_export)
        lay.addWidget(self.start_export_btn, 0, Qt.AlignRight)
        self._fill_export_sources()
        return w

    def _build_restore_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.restore_set = QComboBox()
        self.restore_set.currentIndexChanged.connect(self._refresh_restore_runs)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_restore_set)
        row.addWidget(self.restore_set, 1)
        row.addWidget(b)
        lay.addWidget(_group("Export set on the second storage", row))
        self.restore_runs = QListWidget()
        lay.addWidget(_group("Restore the state of which export (newest = complete current state)",
                             self.restore_runs), 1)
        row2 = QHBoxLayout()
        self.restore_dest = QLineEdit()
        self.restore_dest.setPlaceholderText("new or empty folder")
        b2 = QPushButton("Browse…")
        b2.clicked.connect(self._browse_restore_dest)
        row2.addWidget(self.restore_dest, 1)
        row2.addWidget(b2)
        lay.addWidget(_group("Restore into", row2))
        self.start_restore_btn = _big_button("Start restore")
        self.start_restore_btn.clicked.connect(self._start_restore)
        lay.addWidget(self.start_restore_btn, 0, Qt.AlignRight)
        self._fill_restore_sets()
        return w

    def _build_settings_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        row = QHBoxLayout()
        self.adb_edit = QLineEdit(self.cfg.get("adb_path", ""))
        self.adb_edit.setPlaceholderText("empty = find automatically")
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_adb)
        self.adb_download_btn = QPushButton("Download ADB…")
        self.adb_download_btn.setToolTip("Downloads Google's official Android platform-tools (adb) "
                                         "directly from Google and sets it up for this app.")
        self.adb_download_btn.clicked.connect(self._download_adb)
        row.addWidget(self.adb_edit, 1)
        row.addWidget(b)
        row.addWidget(self.adb_download_btn)
        adb_tip = (
            "<b>ADB (Android Debug Bridge)</b> is Google's tool for talking to an Android phone over USB.<br>"
            "The app uses it to find the phone, list its photos, check every file with SHA-256 "
            "<i>on the phone</i> and copy quickly.<br><br>"
            "<b>Leave empty</b>: adb is found automatically (next to the program in "
            "<i>platform-tools</i>, on the system path, or in the Android SDK).<br>"
            "Only enter a path if adb is somewhere else.<br><br>"
            "ADB is much faster than MTP (the normal phone file transfer): about 45–50 MB/s over USB 3 "
            "here, MTP typically 10–20 MB/s. Without ADB the app falls back to MTP, and the files can "
            "then only be checked on the computer, not on the phone.<br>"
            "On the phone: Developer options → USB debugging must be on.<br><br>"
            "No adb yet? <b>Download ADB…</b> fetches Google's official platform-tools directly "
            "from Google (one click, no installation, no admin rights).")
        adb_label = QLabel("ADB program: ⓘ")
        for wdg in (adb_label, self.adb_edit):
            wdg.setToolTip(adb_tip)
        form.addRow(adb_label, row)
        self.adb_hint = adb_hint = QLabel()
        self._update_adb_hint()
        adb_hint.setWordWrap(True)
        adb_hint.setStyleSheet(f"color:{GRAY}")
        adb_hint.setToolTip(adb_tip)
        form.addRow("", adb_hint)
        self.wait_spin = QSpinBox()
        self.wait_spin.setRange(1, 300)
        self.wait_spin.setSuffix(" s")
        self.wait_spin.setValue(int(self.cfg.get("adb_wait_seconds", 20)))
        form.addRow("Wait for the phone (Connect button):", self.wait_spin)
        self.fsync_check = QCheckBox("Force data onto the disk before verifying (safer, slightly slower)")
        self.fsync_check.setChecked(bool(self.cfg.get("fsync", True)))
        form.addRow("", self.fsync_check)
        self.awake_check = QCheckBox("Keep the computer awake during backup, import, export and restore\n"
                                     "(no standby or shutdown while a job runs, the screen stays on; power settings stay unchanged)")
        self.awake_check.setChecked(bool(self.cfg.get("keep_awake", True)))
        form.addRow("", self.awake_check)
        save = QPushButton("Save settings")
        save.clicked.connect(self._save_settings)
        form.addRow("", save)
        lab = QLabel(f"Settings file: {config.config_path()}")
        lab.setStyleSheet(f"color:{GRAY}")
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("", lab)
        return w

    def _build_bottom(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(9, 0, 9, 9)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress_label = QLabel("Ready.")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        row = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.report_btn = QPushButton("Open report")
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(lambda: self._open(self.last_report))
        self.folder_btn = QPushButton("Open backup folder")
        self.folder_btn.setEnabled(False)
        self.folder_btn.clicked.connect(lambda: self._open(self.last_folder))
        row.addWidget(self.progress_label, 1)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.report_btn)
        row.addWidget(self.folder_btn)
        lay.addWidget(self.progress)
        lay.addLayout(row)
        lay.addWidget(self.log, 1)
        return w

    # ------------------------------------------------------------------ jobs
    def run_job(self, func, on_done, busy=True, awake=None):
        """awake = name of a long job ("Backup", ...): the computer is kept from sleeping meanwhile."""
        if busy:
            self._set_busy(True)
        keep = awake is not None and bool(self.cfg.get("keep_awake", True))
        if keep:
            windows_block_shutdown(self.winId(), True)

        def wrapper():
            try:
                # Entered in the worker thread: on Windows the execution state is per thread.
                with KeepAwake(awake or "", enabled=keep) as ka:
                    if keep:
                        (ui.info if ka.active else ui.warn)(ka.message())
                    res, err = func(), None
            except Exception:  # noqa: BLE001
                res, err = None, traceback.format_exc()
            self.bridge.done.emit(on_done, res, err, busy)

        self.executor.submit(wrapper)

    def _on_done(self, on_done, res, err, busy):
        if busy:
            self._set_busy(False)
        windows_block_shutdown(self.winId(), False)
        if err:
            self.connecting = False
            last = err.strip().splitlines()[-1]
            self._on_log("error", err)
            QMessageBox.critical(self, APP_NAME, f"Something went wrong:\n\n{last}")
        elif on_done:
            on_done(res)
        if self._close_when_idle and not self.busy:
            self.close()

    def _set_busy(self, busy):
        self.busy = busy
        self.pages.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        if busy:
            self.cancel_event.clear()
            self.progress.setValue(0)
            self.progress_label.setText("Working …")

    def _cancel(self):
        self.cancel_event.set()
        self.cancel_btn.setEnabled(False)
        self.progress_label.setText("Cancelling after the current file …")

    # ------------------------------------------------------------------ ui handler targets
    def answer(self, kind, args):
        if kind == "text":
            prompt, default = args
            text, ok = QInputDialog.getText(self, APP_NAME, prompt, text=default or "")
            return text if ok and text else (default or "")
        if kind == "yesno":
            prompt, default = args
            btn = QMessageBox.question(self, APP_NAME, prompt, QMessageBox.Yes | QMessageBox.No,
                                       QMessageBox.Yes if default else QMessageBox.No)
            return btn == QMessageBox.Yes
        if kind == "choose":
            prompt, options, default = args
            item, ok = QInputDialog.getItem(self, APP_NAME, prompt, [str(o) for o in options],
                                            max(0, (default or 1) - 1), False)
            return [str(o) for o in options].index(item) if ok else max(0, (default or 1) - 1)
        if kind == "dir":
            return QFileDialog.getExistingDirectory(self, args[0], str(Path.home())) or ""
        return None

    def _on_request(self, req):
        try:
            req.result = self.answer(req.kind, req.args)
        finally:
            req.event.set()

    def _on_log(self, level, text):
        esc = html.escape(text).replace("\n", "<br>")
        if level == "title":
            self.log.append(f"<br><b>{esc}</b>")
            return
        color = {"ok": GREEN, "warn": ORANGE, "error": RED}.get(level)
        self.log.append(f"<span style='color:{color};font-weight:600'>{esc}</span>" if color else esc)

    def _on_progress(self, d):
        tb = d["total_bytes"] or 0
        self.progress.setValue(int(1000 * d["bytes"] / tb) if tb else 1000)
        self.progress_label.setText(
            f"{d['files']}/{d['total_files']} files  ·  {ui.human_size(d['bytes'])} of "
            f"{ui.human_size(tb)}  ·  {ui.human_size(d['speed'])}/s  ·  "
            f"about {ui.human_duration(d['eta'])} left  ·  {d['current']}")

    # ------------------------------------------------------------------ phone
    def _set_phone_status(self, text, color):
        t = f"<span style='color:{color};font-weight:600'>{html.escape(text)}</span>"
        self.phone_status.setText(t)
        self.home_status.setText(t)
        self._update_home()

    # ------------------------------------------------------------------ start screen
    def _connected_phone(self):
        src = self.source
        return (src.device_name or "") if src is not None else ""

    def _phone_row(self, key):
        """One phone on the start screen: name, last backup, hint, "Update backup"."""
        w = QWidget()
        w.setObjectName("phoneRow")
        w.setStyleSheet("#phoneRow{border:1px solid palette(mid);border-radius:6px}")
        g = QHBoxLayout(w)
        w.pick = QCheckBox()
        w.pick.setToolTip("Tick to remove it from the list (several: tick several, or “Select all”).")
        g.addWidget(w.pick, 0, Qt.AlignVCenter)
        text = QVBoxLayout()
        w.title = QLabel()
        w.title.setStyleSheet("font-size:16px;font-weight:600")
        w.info = QLabel()
        w.info.setStyleSheet(f"color:{GRAY}")
        w.hint = QLabel()
        w.hint.setWordWrap(True)
        w.hint.setTextFormat(Qt.RichText)
        for x in (w.title, w.info, w.hint):
            text.addWidget(x)
        w.button = _big_button("Update backup")
        w.button.setToolTip("Same phone, folders and drives as last time – only new photos and "
                            "videos are copied.")
        w.button.clicked.connect(lambda _c=False, k=key: self._update_latest(k))
        g.addLayout(text, 1)
        g.addWidget(w.button, 0, Qt.AlignVCenter)
        return w

    def _update_home(self):
        if hasattr(self, "conn_overview"):
            self.conn_overview.set_active(adbsetup.source_key(self.source) if self.source else None)
        if not hasattr(self, "phone_rows"):
            return
        entries = lastbackup.phones(self.cfg)
        keys = [backup_parent_name(e["phone"], e.get("owner", "")) for e in entries]
        if list(self._phone_widgets) != keys:            # rebuild the rows
            while self.phone_rows.count():
                it = self.phone_rows.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            self._phone_widgets = {k: self._phone_row(k) for k in keys}
            for k in keys:
                self.phone_rows.addWidget(self._phone_widgets[k])
            if not keys:
                lab = QLabel("No backup yet. Click “New backup…”: choose how the phone is connected, "
                             "which folders and which drives.")
                lab.setWordWrap(True)
                lab.setStyleSheet(f"color:{GRAY}")
                self.phone_rows.addWidget(lab)
        connected = self._connected_phone()
        for key, e in zip(keys, entries):
            w = self._phone_widgets[key]
            w.title.setText(lastbackup.title(e))
            when = e.get("when", "").replace("T", " ") or "unknown"
            status = e.get("status", "")
            note = "" if not status or status.startswith("COMPLETED") else f" – {status.lower()}"
            w.info.setText(f"Last backup {when}{note}")
            attached = ()
            if not any(os.path.isdir(d) for d in e["destinations"]):
                try:
                    attached = {d["label"] for d in detect_unmounted()}
                except Exception:  # noqa: BLE001
                    attached = ()
            ok, hint = lastbackup.check(e, connected, attached_labels=attached)
            if not connected:
                hint += (" Fastest: open “Fast Media Backup” on the phone, tap “Allow backup over "
                         "cable” and plug in the USB cable (Wi-Fi: “Start backup mode” in the app).")
            w.button.setEnabled(ok and not self.busy)
            w.hint.setText(f"<span style='color:{GREEN if ok else GRAY}'>{html.escape(hint)}</span>")

    def _remove_phones(self):
        keys = [k for k, w in self._phone_widgets.items() if w.pick.isChecked()]
        if not keys:
            QMessageBox.information(self, APP_NAME, "Tick one or more phones first (or “Select all”).")
            return
        if QMessageBox.question(
                self, "Remove from list",
                "Remove these phones from the list?\n\n" + "\n".join(keys)
                + "\n\nTheir backups on the drives are NOT deleted.") != QMessageBox.Yes:
            return
        lastbackup.forget(self.cfg, keys)
        self._update_home()

    def _update_latest(self, key):
        """"Update backup" of one phone: its own folders and drives, then the normal checks."""
        e = (self.cfg.get("phones") or {}).get(key)
        if e is None:
            return
        known = self.cfg.get("destinations", [])
        for d in e["destinations"]:
            if d not in known:
                known.append(d)
        self.cfg["destinations"] = known
        self.cfg["selected_destinations"] = list(e["destinations"])
        if e.get("owner"):
            self.owner_edit.setText(e["owner"])
        self.phone_edit.setText(e["phone"])
        self._auto_phone_name = ""
        prof = self.cfg.get("backup_profiles", {}).get(key)
        if prof is None:                         # backups found on a drive: their folders unknown
            prof = {"folders": e.get("folders") or [CAMERA_FOLDER],
                    "keep_structure": bool(e.get("keep_structure", False))}
            self.cfg.setdefault("backup_profiles", {})[key] = prof
        config.save(self.cfg)
        self._load_profile()
        self.dest_list.rebuild()
        self._start_backup()

    # ------------------------------------------------------------------ connection settings
    def _debug_off_changed(self, on):
        self.cfg["debugging_off_after"] = bool(on)
        config.save(self.cfg)

    def _show_usb_guide(self):
        model = self._connected_phone() or self.phone_edit.text().strip()
        UsbDebugGuide(self, model, with_app=True).exec()

    def _cable_setup(self, src):
        """Phone on USB debugging: verify it through the phone app (key check over the cable).
        Mode 'phone app switches it': set the app up first if needed - install, allow switching
        USB debugging, open, pair over the cable (confirmed on the phone). Once per phone and session."""
        src.link = None
        setup = src.serial not in self._companion_asked
        if not paired_phones(self.cfg) and not setup:
            return
        self._companion_asked.add(src.serial)
        apk = apk_path()

        def job():
            link, _why = link_over_cable(src, self.cfg)
            if link or not setup:
                return link
            state = src.companion_state()
            if state == "outdated" and apk is not None:      # own app, already allowed: just update
                ok, msg = src.install_companion(apk)
                (ui.ok if ok else ui.warn)("Phone app “Fast Media Backup” updated." if ok else
                                           f"The phone app could not be updated: {msg}")
                state = "ready" if ok else state
            if state not in ("ready", "outdated"):
                if apk is None:
                    ui.warn("The phone app is not included in this program.")
                    return None
                what = ("install the small phone app “Fast Media Backup”" if state == "missing" else
                        "give the phone app “Fast Media Backup” the right")
                if not ui.ask_yes_no(
                        f"Next time you will not need the Developer options: {what} to switch USB "
                        "debugging on for a backup.\n\nOn the phone you then only open the app and "
                        "tap “Allow backup over cable”; after the backup this program switches USB "
                        "debugging off again.\n\nSet it up now?"):
                    return None
                ok, msg = src.install_companion(apk)
                if not ok:
                    ui.warn(f"The phone app could not be set up: {msg} – Samsung: switch off “Auto "
                            "Blocker”. Xiaomi: switch on “Install via USB” in the Developer options.")
                    return None
                ui.ok("Phone app “Fast Media Backup” installed – it may switch USB debugging.")
            src.control("companion_open")
            for _ in range(10):                       # the app starts its server
                time.sleep(1)
                link, _why = link_over_cable(src, self.cfg)
                if link:
                    return link
            if not ui.ask_yes_no(
                    "Pair the phone app with this computer over the USB cable?\n\nThe phone then "
                    "asks “Pair over the USB cable” – tap “Pair” there. Afterwards this computer "
                    "recognises the phone by its key (over the cable and over Wi-Fi)."):
                return None
            ui.info("Tap “Pair” on the phone (3 minutes) …")
            pair_over_cable(src, self.cfg, cancel=self.cancel_event)
            ui.ok("Paired over the USB cable.")
            link, why = link_over_cable(src, self.cfg)
            if not link:
                ui.warn(f"Paired, but the phone could not be checked: {why}")
            return link

        def done(link):
            if link is None or self.source is not src:
                return
            src.link = link
            self._set_phone_status(
                f"Connected via ADB and verified: {src.manufacturer} {src.device_name} (Android "
                f"{src.android}) – the phone's key matches the paired phone. Fast mode with hash "
                "check on the phone.", GREEN)

        self.run_job(job, done, busy=True)

    def _adb_poller(self):
        """Background: watch `adb devices` so a plugged-in phone is picked up automatically.

        Without a phone it also looks every ~10 s for a paired phone with Wireless debugging
        in the same Wi-Fi and connects it.
        """
        next_wifi = next_app = next_check = next_ble = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if isinstance(self.source, CompanionSource) and not self.busy and now >= next_check:
                next_check = now + 10
                if not self.source.is_connected():
                    self.bridge.companion_lost.emit()
            if (self.source is None and not self.busy and not self.connecting and now >= next_app
                    and self.cfg.get("companion_phones")):
                next_app = now + 6
                try:
                    usb = [s for s, st in adb_devices(find_adb(self.cfg)) if st == "device"
                           and not wireless.is_wireless(s)] if find_adb(self.cfg) else []
                except Exception:  # noqa: BLE001
                    usb = []
                if not usb:
                    entry, addr = find_phone(self.cfg)
                    if entry:
                        self.bridge.companion_found.emit((entry, addr))
                        self._stop.wait(3)
                        continue
                    if now >= next_ble:              # last resort: Bluetooth, only to FIND the phone
                        next_ble = now + 20
                        entry, addr = ble_scan(self.cfg, 4)
                        if entry and addr and _port_open(addr):
                            self.bridge.companion_found.emit((entry, addr))
                            self._stop.wait(3)
                            continue
                        if entry:
                            self.bridge.ble_seen.emit(entry)
            if not self.busy and not self.connecting:
                adb = find_adb(self.cfg)
                devs = None
                if adb:
                    try:
                        devs = adb_devices(adb)
                        if (self.source is None and time.monotonic() >= next_wifi
                                and not any(st == "device" for _, st in devs)):
                            next_wifi = time.monotonic() + 10
                            addr = wireless.auto_connect(adb, self.cfg.get("wifi_last_address", ""))
                            if addr:
                                wireless.remember(self.cfg, addr)
                                devs = adb_devices(adb)
                    except Exception:  # noqa: BLE001
                        devs = []
                self.bridge.adb_state.emit((adb, devs))
            self._stop.wait(2)

    def _on_companion_found(self, found):
        entry, addr = found
        if self.busy or self.connecting or self.source is not None:
            return
        on_cable = adbsetup.detect_usb_phone()
        if on_cable:                  # the phone on the cable comes first - never take another one
            self._set_phone_status(
                f"{on_cable} is on the USB cable, but USB debugging is off. Tap “Allow backup over "
                "cable” in the phone app (or switch on USB debugging). Phones in the Wi-Fi are not "
                "used while a phone is on the cable.", ORANGE)
            return
        self.connecting = True
        self._set_phone_status("Phone app found – connecting …", GRAY)

        def attempt():
            try:
                src = CompanionSource(entry, addr)
            except Exception as e:  # noqa: BLE001
                ui.warn(f"Phone app connection failed: {e}")
                return None
            if entry.get("address") != addr:
                entry["address"] = addr
                from .companion import save_phone
                save_phone(self.cfg, entry)
            return src

        self.run_job(attempt, self._on_connected, busy=False)

    def _on_companion_lost(self):
        if isinstance(self.source, CompanionSource) and not self.busy:
            self.source = None
            self._set_phone_status("The phone app is no longer reachable (backup mode off?).", GRAY)

    def _on_ble_seen(self, entry):
        if self.source is None and not self.busy and not self.connecting:
            self._set_phone_status(f"{entry.get('name') or 'Your phone'} found over Bluetooth, but it cannot "
                                   "be reached over Wi-Fi. Connect it with the USB cable or to the "
                                   "same Wi-Fi as this computer (Bluetooth is only used to find it).", ORANGE)

    def _setup_phone_app(self):
        from .gui_wireless import PhoneAppDialog
        PhoneAppDialog(self, self.cfg).exec()

    def _on_adb_state(self, state):
        adb, devs = state
        if self.busy or self.connecting:
            return
        src = self.source
        usb_ready = [s for s, st in (devs or []) if st == "device" and not wireless.is_wireless(s)]
        slower = src is not None and (not isinstance(src, AdbSource) or src.wireless)
        if slower and usb_ready and time.monotonic() >= self._adb_retry_at:
            # always the fastest: a phone with USB debugging on the cable beats Wi-Fi / MTP
            ui.info(f"USB debugging on the cable found – switching from {src.kind} to the cable "
                    "(faster).")
            try:
                if isinstance(src, CompanionSource):
                    src.close()
            except Exception:  # noqa: BLE001
                pass
            self.source = src = None
        if isinstance(src, AdbSource):
            if devs is None or src.serial not in [s for s, st in devs if st == "device"]:
                self.source = None
                self._set_phone_status("The phone was disconnected.", GRAY)
            return
        if src is not None:          # phone app / MTP / folder source: keep it
            return
        if adb is None:
            self._set_phone_status("ADB is not installed (see README). Click “Connect phone” to use "
                                   "the MTP fallback.", ORANGE)
            return
        ready = wireless.usb_first([s for s, st in devs if st == "device"])
        if ready and time.monotonic() >= self._adb_retry_at:
            self.connecting = True
            self._set_phone_status("Phone found – connecting via ADB …", GRAY)

            def attempt(serial=ready[0]):
                try:
                    return AdbSource(adb, serial)
                except Exception as e:  # noqa: BLE001
                    ui.warn(f"ADB connection failed: {e}")
                    return None

            self.run_job(attempt, self._on_connected, busy=False)
        elif any(st == "unauthorized" for _, st in devs):
            self._set_phone_status("Phone found: unlock it and tap “Allow USB debugging” "
                                   "(tick “Always allow from this computer”).", ORANGE)
        else:
            self._set_phone_status("No phone connected yet. Plug it in (USB debugging on) or switch "
                                   "on Wireless debugging on a paired phone – it is detected "
                                   "automatically.", GRAY)

    def _pair_wifi(self):
        from .gui_wireless import WifiPairDialog
        adb = find_adb(self.cfg)
        if not adb:
            QMessageBox.warning(self, "Pair over Wi-Fi", "ADB is needed for Wi-Fi backups. "
                                "Use Settings → Download ADB… first.")
            return
        dlg = WifiPairDialog(self, adb, self.cfg)
        if dlg.exec() and dlg.connected_address:
            self._adb_retry_at = 0
            self._set_phone_status("Phone connected over Wi-Fi – getting its details …", GRAY)

    def _direct_wifi(self):
        from .gui_wireless import HotspotDialog
        if not wireless.hotspot_supported():
            QMessageBox.warning(self, "Direct Wi-Fi",
                                "NetworkManager (nmcli) was not found. Start a Wi-Fi hotspot in the "
                                "system settings and connect the phone to it.")
            return
        HotspotDialog(self, self.cfg, self._pair_wifi).exec()

    def _connect_manual(self):
        self.connecting = True
        self._set_phone_status("Connecting …", GRAY)
        self.run_job(lambda: connect_source(self.cfg), self._on_connected)

    def _on_connected(self, src):
        self.connecting = False
        if src is None:
            self._adb_retry_at = time.monotonic() + 10
            self._set_phone_status("Not connected.", RED)
            return
        self.source = src
        typed = self.phone_edit.text().strip()
        if src.device_name and (not typed or typed == self._auto_phone_name):
            self.phone_edit.setText(src.device_name)
            self._auto_phone_name = src.device_name
            self._load_profile()                  # this phone's own folder list
        elif src.device_name and typed.casefold() != src.device_name.casefold():
            QMessageBox.warning(       # never mix up phones: do not silently take the other one
                self, "A different phone is connected",
                f"Connected: {src.manufacturer} {src.device_name} ({src.kind}).\n"
                f"The backup is set up for: {typed}.\n\nThe name was NOT changed. A backup only "
                "starts if the connected phone is the right one – connect the right phone, or "
                "change the smartphone name in “Backup settings”.")
        if isinstance(src, CompanionSource):
            self._set_phone_status(
                f"Connected via the phone app: {src.manufacturer} {src.device_name} (Android "
                f"{src.android}) – Wi-Fi, encrypted, read-only, hash check on the phone. Backup mode "
                "on the phone switches off after the backup.", GREEN)
            if not src.full_access:
                QMessageBox.warning(self, "Phone app", "The app on the phone has no full access to "
                                    "photos and videos. Open it on the phone and tap “Allow access” "
                                    "→ “Allow all”.")
        elif isinstance(src, AdbSource):
            how = "ADB over Wi-Fi" if src.wireless else "ADB"
            self._set_phone_status(f"Connected via {how}: {src.manufacturer} {src.device_name} "
                                   f"(Android {src.android}) – fast mode with hash check on the phone."
                                   + (" Keep the phone near the computer and on a charger."
                                      if src.wireless else ""), GREEN)
            self._cable_setup(src)
        else:
            reason = getattr(src, "fallback_reason", "") or ""
            self._set_phone_status(f"Connected via {src.kind}. ADB did not work: {reason}", ORANGE)
            QMessageBox.warning(self, "ADB not working – using fallback",
                                f"ADB did not work:\n{reason}\n\n"
                                f"The backup now uses the {src.kind} connection instead.\n"
                                "This is slower, and the phone itself cannot calculate hashes; "
                                "the copies are compared with the received data instead.")
        self._say_connection(src)
        self._update_preview()

    def _say_connection(self, src):
        """Log which connection is used and - if it is not the fastest - how to get a faster one."""
        key = adbsetup.source_key(src)
        conn = adbsetup.CONNECTIONS_BY_KEY[key]
        if key in ("adb_app", "adb_manual") and not src.wireless:
            mbit = phoneid.usb_speed_mbit()
            if mbit is not None and mbit < 5000:
                ui.warn(f"Connection: {conn.short} – only USB 2 speed. A USB 3 cable and port are "
                        "about 2× faster.")
            else:
                ui.ok(f"Connection: {conn.short} – the fastest connection.")
            return
        on_cable = adbsetup.detect_usb_phone()
        ui.warn(f"Connection: {conn.short} ({conn.speed_short}) – not the fastest. "
                + (f"The {on_cable} is on the USB cable: tap “Allow backup over cable” in the phone "
                   "app – the program then switches to the cable by itself." if on_cable else
                   "Faster: plug the phone in with a USB cable and tap “Allow backup over cable” in "
                   "the phone app – the program switches to the cable by itself."))

    def _find_fastest(self):
        """Check every way to reach a phone, use the fastest, say what would be faster."""
        cfg = self.cfg

        def probe():
            p = {"usb_phone": adbsetup.detect_usb_phone(), "usb_mbit": phoneid.usb_speed_mbit()}
            adb = find_adb(cfg)
            if adb:
                try:
                    devs = adb_devices(adb)
                except Exception:  # noqa: BLE001
                    devs = []
                usb = [s for s, st in devs if st == "device" and not wireless.is_wireless(s)]
                wifi = [s for s, st in devs if st == "device" and wireless.is_wireless(s)]
                p["adb_unauthorized"] = any(st == "unauthorized" for _s, st in devs)
                for key, serials in (("adb_usb", usb), ("adb_wifi", wifi)):
                    if serials:
                        try:
                            p[key] = AdbSource(adb, serials[0]).device_name
                        except Exception:  # noqa: BLE001
                            p[key] = serials[0]
                if not wifi:
                    addr = wireless.auto_connect(adb, cfg.get("wifi_last_address", ""))
                    if addr:
                        p["adb_wifi"] = addr
            if paired_phones(cfg):
                entry, addr = find_phone(cfg)
                if entry:
                    p["app_wifi"] = entry.get("name") or addr
                    p["_app"] = (entry, addr)
                else:
                    e, _a = ble_scan(cfg, 4)
                    if e:
                        p["ble"] = e.get("name", "your phone")
            return p

        def show(p):
            best, rows, advice = adbsetup.describe_probe(p)
            lines = "".join(
                f"<tr><td>{'✅' if ok else '–'}</td><td><b>{html.escape(t)}</b></td>"
                f"<td>{html.escape(txt)}</td></tr>" for t, ok, txt in rows)
            QMessageBox.information(self, "Fastest connection",
                                    f"<table cellspacing=6>{lines}</table><p>{html.escape(advice)}</p>")
            current = adbsetup.source_key(self.source) if self.source else None
            if best == "adb_app" and current not in ("adb_app", "adb_manual"):
                self._adb_retry_at = 0           # the poller switches to the cable
            elif best == "app_wifi" and self.source is None and "_app" in p:
                self.bridge.companion_found.emit(p["_app"])

        self.run_job(probe, show)

    # ------------------------------------------------------------------ folders
    def _fill_folder_list(self):
        self.folder_list.clear()
        for f in self.cfg.get("source_folders") or []:
            self.folder_list.addItem(f"{f}   (Camera)" if f == CAMERA_FOLDER else f)

    def _keep_structure_changed(self, on):
        self.cfg["keep_structure"] = bool(on)
        self._save_profile()

    # ---- every backup ("Galaxy A55 - Kim") has its own folder list - never another phone's
    def _profile_key(self):
        phone, owner = self.phone_edit.text().strip(), self.owner_edit.text().strip()
        return backup_parent_name(phone, owner) if phone and owner else ""

    def _save_profile(self):
        key = self._profile_key()
        if key:
            self.cfg.setdefault("backup_profiles", {})[key] = {
                "folders": list(self.cfg.get("source_folders") or []),
                "keep_structure": bool(self.cfg.get("keep_structure", False))}
        config.save(self.cfg)

    def _load_profile(self):
        key = self._profile_key()
        if not key:
            return
        prof = self.cfg.get("backup_profiles", {}).get(key)
        if prof is None:                       # a backup without its own list: the camera only
            prof = {"folders": [CAMERA_FOLDER], "keep_structure": False}
        if (prof["folders"] != self.cfg.get("source_folders")
                or prof["keep_structure"] != bool(self.cfg.get("keep_structure", False))):
            self.cfg["source_folders"] = list(prof["folders"])
            self.cfg["keep_structure"] = bool(prof["keep_structure"])
            self.keep_structure_check.blockSignals(True)
            self.keep_structure_check.setChecked(self.cfg["keep_structure"])
            self.keep_structure_check.blockSignals(False)
            config.save(self.cfg)
            self._fill_folder_list()

    def _set_folders(self, folders):
        self.cfg["source_folders"] = list(folders)
        self._save_profile()
        self._fill_folder_list()

    def _add_camera_folder(self):
        folders = list(self.cfg.get("source_folders") or [])
        if CAMERA_FOLDER not in folders:
            folders.insert(0, CAMERA_FOLDER)
        self._set_folders(folders)

    def _remove_folder(self):
        names = {it.text().replace("   (Camera)", "") for it in self.folder_list.selectedItems()}
        if not names:
            QMessageBox.information(self, APP_NAME, "Select one or more folders in the list first "
                                    "(Ctrl- or Shift-click, or “Select all”).")
            return
        self._set_folders([f for f in self.cfg.get("source_folders") or [] if f not in names])

    def _choose_folders(self):
        src = self.source
        current = list(self.cfg.get("source_folders") or ["DCIM/Camera"])

        def collect():
            if src is None:
                return []
            out = []
            for root in PHONE_FOLDER_ROOTS:
                out += src.list_subfolders(root)
            return out

        def show(candidates):
            keep, dropped = current, []
            if src is not None:          # never offer folders of another phone
                keep, dropped = _split_by_phone(current, candidates)
            dlg = FolderDialog(self, candidates, keep, src is not None)
            if dropped:
                QMessageBox.information(
                    self, "Folders on the phone",
                    f"{len(dropped)} folder(s) in the list are not on this phone (probably from another "
                    "phone) and were left out:\n\n" + "\n".join(dropped[:15])
                    + ("\n…" if len(dropped) > 15 else ""))
            if dlg.exec() == QDialog.Accepted:
                self._set_folders(dlg.folders() or [CAMERA_FOLDER])
            elif dropped:
                self._set_folders(keep or [CAMERA_FOLDER])

        self.run_job(collect, show)

    # ------------------------------------------------------------------ backup
    def _update_preview(self):
        owner = self.owner_edit.text().strip()
        phone = self.phone_edit.text().strip()
        dests = self.dest_list.selected_paths()
        if not dests:
            self.preview.setText("<i>No destination ticked.</i>")
            return
        name = backup_parent_name(phone or "<phone>", owner or "<owner>")
        lines = []
        for d in dests:
            ok = os.path.isdir(d)
            p = html.escape(str(Path(d) / name))
            lines.append(p if ok else f"<span style='color:{GRAY}'>{p} (drive not connected – skipped)</span>")
        self.preview.setText("<b>Files will be saved to:</b><br>" + "<br>".join(lines))

    def _mount_selected(self, location_list):
        """Mount ticked drives that are attached but not mounted yet."""
        msgs = mount_for_paths(location_list.selected_paths())
        for m in msgs:
            (ui.ok if m.startswith("Mounted") else ui.warn)(m)
        if msgs:
            location_list.update_status()
            self._update_preview()

    def _start_backup(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._mount_selected(self.dest_list)
        finally:
            QApplication.restoreOverrideCursor()
        owner = self.owner_edit.text().strip()
        phone = self.phone_edit.text().strip()
        dests = self.dest_list.selected_available()
        folders = list(self.cfg.get("source_folders") or [])
        problems = []
        if not folders:
            problems.append("Choose at least one folder on the phone (e.g. “Camera”).")
        if not owner:
            problems.append("Enter the owner's name.")
        if self.source is None:
            problems.append("Connect the phone (or click “Connect phone”).")
        if not phone:
            problems.append("Enter the name of the smartphone.")
        if not dests:
            problems.append("Tick at least one connected destination drive.")
        if problems:
            QMessageBox.warning(self, "Cannot start yet", "\n".join(problems))
            return
        src = self.source
        parents = [Path(d) / backup_parent_name(phone, owner) for d in dests]
        confirmed = self._check_phone(src, phone, owner, parents)
        if confirmed is not None:
            folders = self._check_folders(src, folders)
            if folders is None:
                return
        if confirmed is None:
            return
        pid, results = confirmed
        self.cfg["owner"] = owner
        self._save_profile()
        self.last_folder = str(parents[0])
        self._running_backup = (phone, owner, folders, list(self.dest_list.selected_paths()))
        ui.title(f"Backup {phone} – {owner}")

        guard = None
        if isinstance(src, CompanionSource):
            guard = AppGuard(src.client, "wifi")
        elif isinstance(src, AdbSource) and getattr(src, "link", None):
            guard = AppGuard(src.link.client, "wifi-adb" if src.wireless else "usb")

        def job():
            if not src.is_connected():
                raise RuntimeError("The phone is no longer connected - please reconnect it.")
            again = phoneid.identify(src)          # double check right before the first file
            if not phoneid.same_phone(pid, again):
                raise RuntimeError(f"The phone changed after the check ({pid.label} → {again.label}). "
                                   "Nothing was copied.")
            for parent, result in zip(parents, results):
                phoneid.learn(parent, pid, result)
            ui.ok(f"Phone checked twice: {pid.label}"
                  + (f", serial {pid.serial}" if pid.serial else "")
                  + (", phone-app key verified" if pid.app_id else "") + ".")
            if guard:                    # the app switches the other connection off, "still here"
                guard.start()
            elif (isinstance(src, AdbSource) and src.wireless
                  and self.cfg.get("debugging_off_after", True)):
                try:                     # one connection per backup: USB debugging off
                    src.control("usb_debugging_off", timeout=10)
                except Exception:  # noqa: BLE001
                    pass
            try:
                return perform_backup(src, phone, owner, folders, dests, self.cfg,
                                      interactive=True, cancel=self.cancel_event,
                                      keep_structure=bool(self.cfg.get("keep_structure", False)))
            finally:
                if guard:
                    guard.end(switch_off=bool(self.cfg.get("debugging_off_after", True)))

        self.run_job(job, self._backup_done, awake="Backup")

    def _check_folders(self, src, folders):
        """Folders of the list that are not on this phone (e.g. from another phone): say so and
        leave them out. Returns the folders to back up, or None (cancelled)."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            found = []
            for root in PHONE_FOLDER_ROOTS:
                found += [root] if src.folder_exists(root) else []
                found += src.list_subfolders(root)
            keep, drop = _split_by_phone(folders, found)
            drop = [f for f in drop if not src.folder_exists(f)]      # deeper folders: ask directly
            keep = [f for f in folders if f not in drop]
        except Exception:  # noqa: BLE001 - the backup itself reports missing folders
            return folders
        finally:
            QApplication.restoreOverrideCursor()
        if not drop:
            return folders
        if not keep:
            QMessageBox.warning(self, "Folders on the phone", "None of the chosen folders is on this "
                                "phone. Choose its folders with “Choose folders…”.")
            return None
        if QMessageBox.question(
                self, "Folders not on this phone",
                f"{len(drop)} of the chosen folders are not on this phone (probably from another "
                "phone):\n\n" + "\n".join(drop[:15]) + ("\n…" if len(drop) > 15 else "")
                + "\n\nRemove them from this backup's list and start?") != QMessageBox.Yes:
            return None
        self._set_folders(keep)
        return keep

    def _check_phone(self, src, phone, owner, parents):
        """Is the connected phone the one this backup belongs to? Returns (PhoneId, results) or
        None (refused / cancelled). Also tells the user if the connection is not the fastest."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pid = phoneid.identify(src)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Phone check", f"The phone could not be identified:\n{e}")
            return None
        QApplication.restoreOverrideCursor()
        target = f"“{backup_parent_name(phone, owner)}”"
        results = [phoneid.compare(phoneid.load(p), pid) for p in parents]
        if phoneid.MISMATCH in results:
            QMessageBox.critical(
                self, "Wrong phone – backup NOT started",
                f"The connected phone is a {pid.label}"
                + (f" (serial {pid.serial})" if pid.serial else "")
                + f", but the backup {target} belongs to a different phone.\n\nNothing was "
                "copied. Connect the right phone, or choose the right smartphone name and owner.")
            return None
        name_ok = phoneid._same(pid.model, phone)
        if phoneid.PROBABLE in results:
            q = (f"The connected {pid.label} could only be compared by its model name (this "
                 f"connection gives no serial number). Is it really the phone of {target}?")
        elif not name_ok and all(r == phoneid.NEW for r in results):
            q = (f"The connected phone is a {pid.label}, but the backup is named {target}.\n\n"
                 f"Only continue if this {pid.label} really is that phone (for example because you "
                 "gave it your own name).")
        else:
            q = None
        if q is not None:
            box = QMessageBox(QMessageBox.Warning, "Is this the right phone?", q, parent=self)
            yes = box.addButton(f"Yes, back up this {pid.model or 'phone'}", QMessageBox.AcceptRole)
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.setDefaultButton(box.buttons()[-1])
            box.exec()
            if box.clickedButton() is not yes:
                return None
        on_cable = adbsetup.detect_usb_phone() if pid.connection != "usb-adb" else ""
        fastest, advice = phoneid.speed_advice(
            pid, phoneid.usb_speed_mbit() if (pid.connection == "usb-adb" or on_cable) else None,
            on_cable)
        how = {"usb-adb": "USB cable (USB debugging)", "wifi-adb": "Wi-Fi (Wireless debugging)",
               "app-wifi": "Wi-Fi (phone app)", "mtp": "USB file transfer (MTP)"}.get(pid.connection,
                                                                                   pid.connection)
        text = (f"Phone: {pid.label}" + (f"  ·  serial {pid.serial}" if pid.serial else "")
                + ("  ·  phone-app key verified" if pid.app_id else "")
                + f"\nBackup: {target}\nConnection: {how}\n\n" + advice)
        box = QMessageBox(QMessageBox.Information if fastest else QMessageBox.Warning,
                          "Start backup?", text, parent=self)
        go = box.addButton("Start backup" if fastest else "Start anyway (slower)", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            return None
        return pid, results

    def _backup_done(self, res):
        status, paths, results, verdict = res
        phone, owner, folders, dests = self._running_backup
        new = [r for r in results if r.newly_written]
        lastbackup.record(self.cfg, phone, owner, folders, dests, len(new),
                          sum(r.sf.size for r in new), status,
                          model=getattr(self.source, "device_name", "") or "",
                          keep_structure=bool(self.cfg.get("keep_structure", False)))
        if isinstance(self.source, CompanionSource):     # switch backup mode off on the phone
            src, self.source = self.source, None
            threading.Thread(target=src.finish, daemon=True).start()
            self._set_phone_status("Backup done – backup mode on the phone was switched off.", GRAY)
        elif isinstance(self.source, AdbSource) and self.cfg.get("debugging_off_after", True):
            src, self.source = self.source, None
            self._adb_retry_at = time.monotonic() + 30

            def off(src=src):
                link = getattr(src, "link", None)
                if link is not None:                # backup mode on the phone off, then debugging
                    try:
                        link.client.request("POST", "/done", {})
                    except Exception:  # noqa: BLE001 - phone gone: the guard there switches off
                        pass
                    link.close()
                src.switch_off_debugging()

            threading.Thread(target=off, daemon=True).start()
            what = "Wireless debugging" if src.wireless else "USB debugging"
            ui.ok(f"{what} on the phone was switched off.")
            self._set_phone_status(f"Backup done – {what} on the phone was switched off. "
                                   "You can unplug the phone.", GRAY)
        self._finished(status, paths, verdict, "Backup")
        self._fill_export_sources()

    def _finished(self, status, paths, verdict, what):
        html_reports = [p for p in paths if str(p).endswith(".html")]
        if html_reports:
            self.last_report = str(html_reports[0])
            self.report_btn.setEnabled(True)
        if self.last_folder:
            self.folder_btn.setEnabled(True)
        self.progress_label.setText(f"{what}: {status}")
        good = verdict.startswith(("EVERYTHING", "RESTORE OK"))
        if good:
            self.progress.setValue(1000)
        box = QMessageBox(QMessageBox.Information if good else QMessageBox.Warning,
                          f"{what} finished", f"{verdict}\n\nStatus: {status}", parent=self)
        open_btn = box.addButton("Open report", QMessageBox.AcceptRole) if html_reports else None
        box.addButton(QMessageBox.Close)
        box.exec()
        if open_btn is not None and box.clickedButton() is open_btn:
            self._open(self.last_report)

    @staticmethod
    def _open(path):
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------------ export
    def _fill_export_sources(self, select=None):
        cur = select or self.export_src.currentData()
        self.export_src.blockSignals(True)
        self.export_src.clear()
        items = find_backups(self.cfg)
        extra = self.cfg.get("extra_export_sources", [])
        for p in items + [e for e in extra if e not in items and os.path.isdir(e)]:
            self.export_src.addItem(p, p)
        idx = self.export_src.findData(cur) if cur else -1
        self.export_src.setCurrentIndex(idx if idx >= 0 else 0)
        self.export_src.blockSignals(False)
        self._refresh_export_info()

    def _browse_export_src(self):
        p = QFileDialog.getExistingDirectory(self, "Choose the backup folder (Phone - Owner)",
                                             (self.cfg.get("destinations") or [str(Path.home())])[0])
        if not p:
            return
        if not is_backup_folder(p):
            QMessageBox.warning(self, APP_NAME, "This is not a backup folder of this app.\n\n"
                                "Choose the folder named “Phone - Owner” (it contains the year folders).")
            return
        extra = self.cfg.get("extra_export_sources", [])
        if p not in extra:
            self.cfg["extra_export_sources"] = extra + [p]
            config.save(self.cfg)
        self._fill_export_sources(select=p)

    def _export_target_parent(self):
        src = self.export_src.currentData()
        tgt = self.export_targets.selected_available()
        if not src or not tgt:
            return src, None, None
        return src, tgt[0], Path(tgt[0]) / Path(src).name

    def _refresh_export_info(self):
        src, tgt, tparent = self._export_target_parent()
        self.export_runs.clear()
        has_full = False
        if tparent and has_catalog(tparent):
            cat = Catalog(tparent)
            runs = cat.runs()
            has_full = cat.last_full() is not None
            cat.close()
            for r in reversed(runs):
                self.export_runs.addItem(f"{r.folder}    [{r.status}]")
        for m in ("differential", "incremental"):
            self.mode_buttons[m].setEnabled(has_full)
        hints = []
        if not src:
            hints.append("No backup found yet – make a backup first or use “Browse…”.")
        if not tgt:
            hints.append("Choose a connected second storage.")
        if src and tgt and not has_full:
            self.mode_buttons["full"].setChecked(True)
            hints.append("There is no full export on this storage yet – the first export must be a full one.")
        if src and tgt and same_volume(src, tgt):
            hints.append("WARNING: the second storage is on the same drive as the backup – "
                         "this does not protect against a drive failure.")
        self.export_hint.setText("<br>".join(f"<span style='color:{ORANGE}'>{html.escape(h)}</span>"
                                             for h in hints))

    def _start_export(self):
        self._mount_selected(self.export_targets)
        self._fill_export_sources()
        src, tgt, tparent = self._export_target_parent()
        if not src or not tgt:
            QMessageBox.warning(self, "Cannot start yet", "Choose a backup and a connected second storage.")
            return
        if same_volume(src, tgt) and QMessageBox.question(
                self, "Same drive", "The second storage is on the same drive as the backup.\n"
                "Continue anyway?") != QMessageBox.Yes:
            return
        mode = [m for m, b in self.mode_buttons.items() if b.isChecked()][0]
        self.last_folder = str(tparent)
        ui.title(f"Export ({mode}) of {src}")
        self.run_job(lambda: perform_export(src, tgt, mode, self.cfg, cancel=self.cancel_event),
                     self._export_done, awake="Export")

    def _export_done(self, res):
        status, paths, verdict = res
        self._finished(status, paths, verdict, "Export")
        self._refresh_export_info()
        self._fill_restore_sets()

    # ------------------------------------------------------------------ restore
    def _fill_restore_sets(self, select=None):
        cur = select or self.restore_set.currentData()
        self.restore_set.blockSignals(True)
        self.restore_set.clear()
        items = find_export_sets(self.cfg)
        extra = self.cfg.get("extra_restore_sets", [])
        for p in items + [e for e in extra if e not in items and has_catalog(e)]:
            self.restore_set.addItem(p, p)
        idx = self.restore_set.findData(cur) if cur else -1
        self.restore_set.setCurrentIndex(idx if idx >= 0 else 0)
        self.restore_set.blockSignals(False)
        self._refresh_restore_runs()

    def _browse_restore_set(self):
        p = QFileDialog.getExistingDirectory(self, "Choose the export set (Phone - Owner) on the second storage")
        if not p:
            return
        if not has_catalog(p):
            QMessageBox.warning(self, APP_NAME, "No exports found in this folder.")
            return
        extra = self.cfg.get("extra_restore_sets", [])
        if p not in extra:
            self.cfg["extra_restore_sets"] = extra + [p]
            config.save(self.cfg)
        self._fill_restore_sets(select=p)

    def _refresh_restore_runs(self):
        self.restore_runs.clear()
        p = self.restore_set.currentData()
        if not p or not has_catalog(p):
            return
        cat = Catalog(p)
        runs = cat.runs()
        cat.close()
        for r in reversed(runs):
            it = QListWidgetItem(f"{r.folder}    [{r.status}]")
            it.setData(Qt.UserRole, r.id)
            self.restore_runs.addItem(it)
        if runs:
            self.restore_runs.setCurrentRow(0)

    def _browse_restore_dest(self):
        p = QFileDialog.getExistingDirectory(self, "Restore into which folder")
        if p:
            self.restore_dest.setText(p)

    def _start_restore(self):
        tparent = self.restore_set.currentData()
        it = self.restore_runs.currentItem()
        dest = self.restore_dest.text().strip()
        if not tparent or it is None or not dest:
            QMessageBox.warning(self, "Cannot start yet",
                                "Choose an export set, the export state and a target folder.")
            return
        if os.path.isdir(dest) and any(os.scandir(dest)) and QMessageBox.question(
                self, "Folder not empty", "The folder is not empty – files with the same name will be "
                "overwritten. Continue?") != QMessageBox.Yes:
            return
        run_id = it.data(Qt.UserRole)
        self.last_folder = dest
        ui.title(f"Restore into {dest}")
        self.run_job(lambda: perform_restore(tparent, run_id, dest, self.cfg, cancel=self.cancel_event),
                     self._restore_done, awake="Restore")

    def _restore_done(self, res):
        status, paths, verdict = res
        self._finished(status, paths, verdict, "Restore")

    # ------------------------------------------------------------------ settings / misc
    def _update_adb_hint(self):
        adb = find_adb({"adb_path": self.adb_edit.text().strip()})
        found = (f"Found: {adb}" if adb else
                 "No adb found – click “Download ADB…” (otherwise the slower MTP is used).")
        self.adb_hint.setText(f"{found}\nLeave empty = found automatically. ADB is about 3× faster than "
                              "MTP and lets the app check every file on the phone (hover for details).")

    def _download_adb(self):
        from .adbdownload import LICENSE_URL, download_adb, platform_name
        box = QMessageBox(self)
        box.setWindowTitle("Download ADB")
        box.setIcon(QMessageBox.Question)
        box.setTextFormat(Qt.RichText)
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)   # licence link clickable
        box.setText(
            "The app downloads Google's official <b>Android SDK Platform-Tools</b> "
            f"for {'Windows' if platform_name() == 'windows' else platform_name().capitalize()} "
            "(about 7–15 MB) directly from Google and keeps them in its own folder. "
            "Nothing is installed in the system and no admin rights are needed.<br><br>"
            "By downloading you accept Google's licence terms for the platform-tools:<br>"
            f"<a href='{LICENSE_URL}'>{LICENSE_URL}</a>"
            + ("<br><br>On Linux you can instead install adb with <tt>sudo apt install adb</tt>."
               if platform_name() == "linux" else ""))
        ok = box.addButton("Accept and download", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is not ok:
            return
        ui.title("Download ADB")
        self.run_job(lambda: download_adb(cancel=self.cancel_event), self._adb_downloaded)

    def _adb_downloaded(self, res):
        path, version = res
        self.adb_edit.setText(path)
        self._save_settings()
        self._update_adb_hint()
        self.progress_label.setText("ADB downloaded")
        QMessageBox.information(self, "Download ADB",
                                f"ADB is ready:\n{path}\n{version}\n\nConnect the phone with USB debugging "
                                "switched on and allow this computer on the phone.")

    def _browse_adb(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose the adb program")
        if p:
            self.adb_edit.setText(p)

    def _save_settings(self):
        self.cfg["adb_path"] = self.adb_edit.text().strip()
        self.cfg["adb_wait_seconds"] = self.wait_spin.value()
        self.cfg["fsync"] = self.fsync_check.isChecked()
        self.cfg["keep_awake"] = self.awake_check.isChecked()
        config.save(self.cfg)
        if hasattr(self, "adb_hint"):
            self._update_adb_hint()
        ui.ok("Settings saved.")

    def _tab_changed(self, idx):
        if idx == 0:
            self._fill_import_targets()
            self.import_dest_list.rebuild()
        elif idx == 1:
            self._fill_export_sources()
        elif idx == 2:
            self._fill_restore_sets()

    def _periodic(self):
        if self.busy:
            return
        self.dest_list.update_status()
        self.export_targets.update_status()
        self.import_dest_list.update_status()
        self._update_preview()
        self._update_home()

    def closeEvent(self, event):
        if self.busy:
            if QMessageBox.question(self, "Job running", "A job is still running.\n"
                                    "Cancel it and quit after the current file?") == QMessageBox.Yes:
                self._close_when_idle = True
                self._cancel()
            event.ignore()
            return
        if wireless.hotspot_active():
            ans = QMessageBox.question(self, "Direct Wi-Fi",
                                       "Direct Wi-Fi (the computer's own hotspot) is still on.\n"
                                       "Stop it so the computer gets its normal Wi-Fi back?",
                                       QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if ans == QMessageBox.Cancel:
                event.ignore()
                return
            if ans == QMessageBox.Yes:
                wireless.stop_hotspot()
        self._stop.set()
        ui.set_handler(None)
        self.executor.shutdown(wait=False)
        if self.source is not None:
            try:
                self.source.close()
            except Exception:  # noqa: BLE001
                pass
        event.accept()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(DESKTOP_ID)   # Wayland: lets the desktop show our icon in the dock
    app.setWindowIcon(app_icon())
    if sys.platform.startswith("win"):
        try:  # own taskbar group + icon instead of the generic python icon
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(DESKTOP_ID)
        except Exception:  # noqa: BLE001
            pass
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
