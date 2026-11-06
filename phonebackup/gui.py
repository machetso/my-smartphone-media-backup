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

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QApplication, QBoxLayout, QButtonGroup, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea, QSpinBox,
                               QSplitter, QStackedWidget, QStyle, QTabWidget, QTextEdit, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import APP_NAME, __version__, config, i18n, ui
from .i18n import N_, tr, trp  # noqa: F401 - used throughout
from .keepawake import KeepAwake, windows_block_shutdown
from .backup import backup_parent_name, perform_backup
from .export import Catalog, folder_size, has_catalog, perform_export, perform_restore, remove_runs
from . import gfs
from . import gdrive, gdrive_gfs
from .copier import Cancelled
from .importer import (CAMERA, OTHER, check_selection, guess_kind, perform_old_phone_import,
                       perform_selection_import, scan_folder)
from .layout import same_volume
from .index import backup_totals, describe_totals
from .locations import (describe_unmounted, detect_drives, detect_unmounted, drive_label_of,
                        find_backups, find_export_sets, free_space, is_backup_folder,
                        mount_device, mount_for_paths_status)
from .sources import AdbSource, adb_devices, connect_source, find_adb
from . import adbsetup, lastbackup, phoneid, wireless
from .companion import (APP_NAME as COMPANION_NAME, APP_VERSION_NAME as COMPANION_VERSION, AppGuard,
                        CompanionSource, apk_path, ble_scan, find_phone, install_question,
                        link_over_cable, pair_over_cable, phones as paired_phones, _port_open)
from .gui_setup import ConnectionOverview, UsbDebugGuide

PHONE_FOLDER_ROOTS = ["DCIM", "Pictures", "Movies", "Download",
                      "Android/media/com.whatsapp/WhatsApp/Media"]
CAMERA_FOLDER = "DCIM/Camera"       # Android's standard camera folder (almost every phone)

GREEN, ORANGE, RED, GRAY = "#1f8a4c", "#c76a00", "#c62828", "#808080"


# short names of the connection in use, for the status headline
CONN_SHORT = {"adb_app": N_("USB cable"), "adb_manual": N_("USB cable"), "wifi_adb": N_("Wi-Fi debugging"),
              "app_wifi": N_("Wi-Fi via the phone app"), "mtp": N_("USB cable, file transfer (slow)")}


class WrapCheck(QWidget):
    """A check box whose text wraps (long texts in German, French … must not make the window
    wider). Behaves like a QCheckBox for the calls the window uses; clicking the text toggles."""

    def __init__(self, text):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.box = QCheckBox()
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.label.setContentsMargins(0, 1, 0, 0)
        self.label.mousePressEvent = lambda _e: self.box.isEnabled() and self.box.toggle()
        lay.setAlignment(Qt.AlignTop)
        lay.addWidget(self.box, 0, Qt.AlignTop)
        lay.addWidget(self.label, 1)
        self.toggled = self.box.toggled

    def isChecked(self):
        return self.box.isChecked()

    def setChecked(self, on):
        self.box.setChecked(on)

    def blockSignals(self, on):
        return self.box.blockSignals(on)

    def setToolTip(self, tip):
        super().setToolTip(tip)
        self.box.setToolTip(tip)
        self.label.setToolTip(tip)


class StatusBanner(QFrame):
    """The connection status, clearly visible (user request 2026-11-06): a coloured stripe, a big
    headline (state · phone · connection) and the details below in normal size."""

    SYMBOL = {GREEN: "●", ORANGE: "▲", RED: "✕", GRAY: "○"}

    def __init__(self):
        super().__init__()
        self.setObjectName("statusBanner")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)
        self.head = QLabel()
        self.head.setWordWrap(True)
        self.head.setTextFormat(Qt.RichText)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.RichText)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.head)
        lay.addWidget(self.detail)

    def show_status(self, headline, detail, color):
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        self.setStyleSheet(f"#statusBanner{{border-left:6px solid {color};border-radius:6px;"
                           f"background:rgba({r},{g},{b},0.12)}}")
        self.head.setText(f"<span style='color:{color};font-size:18px;font-weight:700'>"
                          f"{self.SYMBOL.get(color, '●')}&nbsp; {html.escape(headline)}</span>")
        self.detail.setText(html.escape(detail))
        self.detail.setVisible(bool(detail))


DESKTOP_ID = "my-smartphone-media-backup"   # matches the .desktop file / icon name on Linux


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

    def ask_install(self, title, text, details):
        return self._ask("install", title, text, details)

    def choose(self, prompt, options, default=1):
        return self._ask("choose", prompt, options, default)

    def ask_directory(self, prompt):
        return self._ask("dir", prompt)


# =========================================================================== widgets

GDRIVE = "gdrive:"                 # the Google Drive entry in a location list (second storage only)
CLOUD_SERVICES = [("gdrive", "Google Drive")]      # more cloud storage in later versions


def is_cloud(p):
    return p == GDRIVE


class LocationList(QWidget):
    """List of saved folders on drives. multi=True: tick several; False: select one.
    cloud=True: also "Add to cloud storage" (Google Drive), shown as its own entry."""
    changed = Signal()
    cloud_requested = Signal(str)

    def __init__(self, cfg, key, sel_key, multi, default_folder, hint, cloud=False, plans_column=False):
        super().__init__()
        self.cloud = cloud
        self.plans_column = plans_column      # backup drives: "Backup plan" per drive
        self.cloud_info = {}           # GDRIVE -> {"email", "free"} filled by the main window
        self.cfg, self.key, self.sel_key = cfg, key, sel_key
        self.multi, self.default_folder = multi, default_folder
        self.cfg.setdefault(sel_key, list(cfg.get(key, [])) if multi else cfg.get(key, [])[:1])
        self._updating = False

        self.tree = QTreeWidget()
        # backup drives: short name + plan first, the full folder last (long paths scroll sideways)
        if plans_column:
            self.col_status, self.col_free, self.col_plan, self.col_path = 2, 3, 1, 4
            self.tree.setHeaderLabels([tr("Drive"), tr("Backup plan"), tr("Status"), tr("Free space"), tr("Folder")])
        else:
            self.col_status, self.col_free, self.col_plan, self.col_path = 1, 2, None, None
            self.tree.setHeaderLabels([tr("Folder"), tr("Status"), tr("Free space")])
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumHeight(110)
        # long folder names: the column is as wide as the name and the list scrolls sideways;
        # status and free space only as wide as needed (user request 2026-11-04)
        h = self.tree.header()
        h.setStretchLastSection(False)
        for col in range(self.tree.columnCount()):
            h.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setTextElideMode(Qt.ElideNone)
        self.tree.setMinimumWidth(150)       # the page must not grow with long names
        if multi:
            self.tree.itemChanged.connect(self._check_changed)
        else:
            self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
            self.tree.itemSelectionChanged.connect(self._selection_changed)

        self.btn_drive = QPushButton(tr("Add drive…"))
        self.drive_menu = QMenu(self.btn_drive)
        self.drive_menu.aboutToShow.connect(self._fill_drive_menu)
        self.btn_drive.setMenu(self.drive_menu)
        btn_folder = QPushButton(tr("Add folder…"))
        btn_folder.clicked.connect(self._add_folder)
        btn_remove = QPushButton(tr("Remove from list"))
        btn_remove.clicked.connect(self._remove)

        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_drive)
        buttons.addWidget(btn_folder)
        if cloud:
            self.btn_cloud = QPushButton(tr("Add to cloud storage"))
            cmenu = QMenu(self.btn_cloud)
            for key_, name in CLOUD_SERVICES:
                cmenu.addAction(name, lambda k=key_: self.cloud_requested.emit(k))
            self.btn_cloud.setMenu(cmenu)
            self.btn_cloud.setToolTip(tr("Mirror the backup to a cloud storage (Google Drive for now – "
                                         "more services in later versions)."))
            buttons.addWidget(self.btn_cloud)
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
        return [p for p in self.selected_paths()
                if (gdrive.signed_in_email() if is_cloud(p) else os.path.isdir(p))]

    def add_cloud(self, entry):
        self._add(entry)

    # ---- view
    def rebuild(self):
        self._updating = True
        self.tree.clear()
        sel = set(self.selected_paths())
        for p in self.paths():
            if self.plans_column:
                parts = Path(p).parts
                short = "/".join(parts[-2:]) if len(parts) > 1 else p
                it = QTreeWidgetItem([short, "", "", "", p])
            else:
                it = QTreeWidgetItem(["Google Drive" if is_cloud(p) else p, "", ""])
            it.setData(0, Qt.UserRole, p)
            it.setToolTip(0, f"My Drive/{gdrive.ROOT_NAME}" if is_cloud(p) else p)
            if self.multi:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked if p in sel else Qt.Unchecked)
            self.tree.addTopLevelItem(it)
            if not self.multi and p in sel:
                it.setSelected(True)
            if self.plans_column:
                self.tree.setItemWidget(it, self.col_plan, self._plan_combo(p))
        self._updating = False
        self.update_status()

    def _plan_combo(self, base):
        from . import plans
        cb = QComboBox()
        for key_ in (plans.SIMPLE, plans.GFS):
            cb.addItem(tr(plans.NAMES[key_]), key_)
            cb.setItemData(cb.count() - 1, tr(plans.DESCRIPTION[key_]), Qt.ToolTipRole)
        cb.setCurrentIndex(max(cb.findData(plans.plan_of(self.cfg, base)), 0))
        cb.setToolTip(tr("Simple: one folder that grows.\nGrandfather-Father-Son: dated full (every 3 months), "
                         "differential (monthly) and incremental backups – older states can be restored."))
        cb.currentIndexChanged.connect(lambda _i, b=base, c=cb: self._plan_changed(b, c))
        return cb

    def _plan_changed(self, base, cb):
        from . import plans
        plan = cb.currentData()
        # phones that already have a backup with the other plan on this drive keep it
        clash = []
        if os.path.isdir(base):
            for e in sorted(os.scandir(base), key=lambda e: e.name):
                have = plans.folder_plan(e.path) if e.is_dir() else None
                if have and have != plan:
                    clash.append(e.name)
        if clash:
            r = QMessageBox.question(
                self, tr("Backup plan"),
                tr("On %s these phones already have a %s backup:", base,
                   tr(plans.NAMES[plans.SIMPLE if plan == plans.GFS else plans.GFS]).lower())
                + "\n\n" + "\n".join(clash) + "\n\n" +
                tr("Their folders keep their plan (nothing is converted or deleted). The plan "
                   "“%s” is used for phones that are new on this drive.", tr(plans.NAMES[plan])) + "\n\n" +
                tr("Tip: for a Grandfather-Father-Son backup of the same phone add another folder on the "
                   "drive (e.g. “PhoneBackups-GFS”).") + "\n\n" + tr("Change the plan anyway?"))
            if r != QMessageBox.Yes:
                cb.blockSignals(True)
                cb.setCurrentIndex(cb.findData(plans.plan_of(self.cfg, base)))
                cb.blockSignals(False)
                return
        plans.set_plan(self.cfg, base, plan)
        config.save(self.cfg)
        self.changed.emit()

    def update_status(self):
        self._updating = True       # setText/setForeground also fire itemChanged
        unmounted_labels = None
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            p = it.data(0, Qt.UserRole)
            if is_cloud(p):
                email = gdrive.signed_in_email()
                info = self.cloud_info.get(p) or {}
                it.setText(0, f"Google Drive ({email})" if email else "Google Drive")
                it.setText(1, tr("signed in") if email else tr("not signed in – click “Add to cloud storage”"))
                it.setForeground(1, QColor(GREEN if email else ORANGE))
                free = info.get("free") if email and info.get("email") == email else None
                it.setText(2, ui.human_size(free) if free is not None else
                           (tr("no limit") if email and info.get("email") == email else "–"))
                continue
            avail = os.path.isdir(p)
            free = free_space(p) if avail else None
            status, color = (tr("connected"), GREEN) if avail else (tr("not connected"), GRAY)
            if not avail:
                if unmounted_labels is None:
                    unmounted_labels = {d["label"] for d in detect_unmounted()}
                if drive_label_of(p) in unmounted_labels:
                    status, color = tr("attached, not mounted (mounted automatically at start)"), ORANGE
            it.setText(self.col_status, status)
            it.setForeground(self.col_status, QColor(color))
            for col in (0, self.col_path):
                if col is not None:
                    it.setForeground(col, QColor(self.palette().text().color() if avail else QColor(GRAY)))
            it.setText(self.col_free, ui.human_size(free) if free is not None else "–")
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
            a = self.drive_menu.addAction(tr("No external drive found – plug one in"))
            a.setEnabled(False)
        for p, free in drives:
            a = self.drive_menu.addAction(tr("%s    (%s free)", p, ui.human_size(free)))
            a.triggered.connect(lambda _checked=False, p=p: self._add_on_drive(p))
        if unmounted:
            self.drive_menu.addSection(tr("Attached but not mounted – click to mount"))
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
            QMessageBox.critical(self, tr("Mount failed"), tr("The drive “%s” could not be mounted:", name) + f"\n\n{err}")
            return
        ui.ok(tr("Drive “%s” mounted at %s", name, mountpoint))
        if not os.access(mountpoint, os.W_OK):
            QMessageBox.warning(
                self, tr("Drive is read-only"),
                tr("“%s” was mounted READ-ONLY, so no backup can be written to it.\n\n"
                   "For NTFS drives this usually means Windows did not shut the drive down cleanly "
                   "(Fast Startup / hibernation). Connect it to Windows, run “chkdsk /f”, and use "
                   "“Safely remove” – or switch off Fast Startup in Windows.", name))
            return
        self._add_on_drive(mountpoint)

    def _add_on_drive(self, drive):
        name, ok = QInputDialog.getText(self, tr("Backup folder on the drive"),
                                        tr("Name of the folder on %s:", drive), text=self.default_folder)
        if ok and name.strip():
            self._add(os.path.join(drive, name.strip()))

    def _add_folder(self):
        drives = detect_drives()
        start = drives[0][0] if drives else str(Path.home())
        p = QFileDialog.getExistingDirectory(self, tr("Choose a folder"), start)
        if p:
            self._add(p)

    def _add(self, path):
        if not is_cloud(path):
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, APP_NAME, tr("Cannot create the folder:") + f"\n{path}\n\n{e}")
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
            QMessageBox.information(self, APP_NAME, tr("Click a folder in the list first."))
            return
        p = it.data(0, Qt.UserRole)
        if is_cloud(p):
            box = QMessageBox(QMessageBox.Question, tr("Remove from list"),
                              tr("Remove Google Drive from the list?\n\nThe files on Google Drive are NOT "
                                 "deleted."), parent=self)
            rm_only = box.addButton(tr("Remove"), QMessageBox.AcceptRole)
            rm_out = box.addButton(tr("Remove and sign out"), QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() not in (rm_only, rm_out):
                return
            if box.clickedButton() is rm_out:
                gdrive.sign_out()
                ui.info(tr("Signed out of Google Drive."))
        elif QMessageBox.question(self, tr("Remove from list"),
                                  tr("Remove this folder from the list?\n\n%s\n\n"
                                     "The files on the drive are NOT deleted.", p)) != QMessageBox.Yes:
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
        self.setWindowTitle(tr("Folders on the phone"))
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        info = (tr("Tick the folders to back up. Paths are inside the phone's internal storage.")
                if connected else
                tr("The phone is not connected, so its folders cannot be listed. "
                   "You can still type a folder path, e.g. Pictures/Screenshots."))
        lab = QLabel(info)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.list = QListWidget()
        for c in sorted(set(candidates) | set(current)):
            self._add_item(c, c in current)
        lay.addWidget(self.list)
        sel = QHBoxLayout()
        for text, on in ((tr("Select all"), True), (tr("Select none"), False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, on=on: self._tick_all(on))
            sel.addWidget(b)
        sel.addStretch()
        lay.addLayout(sel)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Other folder, e.g. Pictures/Screenshots"))
        add = QPushButton(tr("Add"))
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

    KINDS = [(CAMERA, N_("Camera → month folders")), (OTHER, N_("Other → other/… (original folder)"))]

    def __init__(self, parent, scans, choices):
        """scans: {root: [FolderInfo]}, choices: {root: {rel: kind}} (the current selection)."""
        super().__init__(parent)
        self.setWindowTitle(tr("Choose folders to import"))
        self.resize(980, 600)
        self.scans = scans
        lay = QVBoxLayout(self)
        lab = QLabel(tr(
            "Every folder that contains files is listed (app data, caches, thumbnails, trash and hidden "
            "folders are left out). Each ticked folder is imported with its own files; its sub-folders "
            "are separate lines. <b>Camera</b> folders go into the year/month folders, <b>Other</b> folders "
            "keep their original folder name under <i>year/other/pictures | movies | other-files</i>."))
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Folder"), tr("Photos"), tr("Videos"), tr("Other files"), tr("Size"),
                                    tr("Sort as"), tr("Note")])
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
                it = QTreeWidgetItem([tr("(this folder itself)") if info.rel == "." else info.rel,
                                      str(info.photos), str(info.videos), str(info.other),
                                      ui.human_size(info.size), "", tr(info.note) if info.note else ""])
                for c in (1, 2, 3, 4):
                    it.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked if info.rel in chosen else Qt.Unchecked)
                it.setData(0, Qt.UserRole, (root, info.rel))
                top.addChild(it)
                cb = QComboBox()
                for k, text in self.KINDS:
                    cb.addItem(tr(text), k)
                cb.setCurrentIndex(0 if chosen.get(info.rel, info.kind) == CAMERA else 1)
                self.tree.setItemWidget(it, 5, cb)
                self.combos[(root, info.rel)] = (it, cb, info)
            if not infos:
                top.addChild(QTreeWidgetItem([tr("no files found in this folder")]))
            top.setExpanded(True)

        row = QHBoxLayout()
        for text, fn in ((tr("Suggested"), self._suggested), (tr("Tick all"), lambda: self._tick(True)),
                         (tr("Untick all"), lambda: self._tick(False))):
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
        files = sum(i.files for i in ticked)
        self.summary.setText(trp("%d folder ticked", "%d folders ticked", len(ticked), len(ticked)) + ", "
                             + trp("%d file", "%d files", files, files) + ", "
                             + ui.human_size(sum(i.size for i in ticked)))

    def choices(self):
        out = {root: {} for root in self.scans}
        for (root, rel), (it, cb, _info) in self.combos.items():
            if it.checkState(0) == Qt.Checked:
                out[root][rel] = cb.currentData()
        return out


def _status_text(status):
    """A core status / verdict for display. Status strings stay English internally (they are
    compared and stored); report.shown translates known ones (and a report.Shown's own text)."""
    from .report import shown
    return str(shown(status or ""))


# beginnings of a successful verdict – English (compared) and the same keys translated, because
# some modules hand over verdicts that are already translated
_GOOD_VERDICTS = ("EVERYTHING COPIED CORRECTLY - %d new files (%s) secured and verified "
                  "with SHA-256 on %d destination(s).",
                  "EVERYTHING EXPORTED CORRECTLY - %s export on Google Drive: %d files (%s) verified "
                  "with SHA-256.",
                  "EVERYTHING EXPORTED CORRECTLY - %d files (%s) uploaded to Google "
                  "Drive and verified with SHA-256.",
                  "RESTORE OK - %d files downloaded from Google Drive and verified.")


def _verdict_good(verdict):
    v = str(verdict or "")
    if v.startswith(("EVERYTHING", "RESTORE OK")):
        return True
    for key in _GOOD_VERDICTS:
        pre = tr(key).split("%")[0].strip()
        if len(pre) >= 6 and v.startswith(pre):
            return True
    return False


def _log_mount_msgs(results):
    """[(ok, message)] of locations.mount_for_paths_status: success green, failure orange."""
    for ok, m in results:
        (ui.ok if ok else ui.warn)(m)


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

def gear_icon(color, size=64):
    """Settings gear like in VideoSpeedControl: 8 teeth around a ring with a hole, drawn here."""
    import math
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    pts = []
    for i in range(8):
        a = i * 2 * math.pi / 8
        for da, r in ((-0.30, 8.0), (-0.17, 11.0), (0.17, 11.0), (0.30, 8.0)):
            pts.append((12 + r * math.cos(a + da), 12 + r * math.sin(a + da)))
    path.moveTo(*pts[0])
    for x, y in pts[1:]:
        path.lineTo(x, y)
    path.closeSubpath()
    path.addEllipse(8.5, 8.5, 7, 7)                      # the hole
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24, size / 24)
    p.fillPath(path, QColor(color))
    p.end()
    return QIcon(pm)


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
        self._job = None
        self._gdrive_runs = {}          # set name -> (runs, sizes) | "loading"   (GFS on Google Drive)
        self._gdrive_sets = None        # names of the GFS backups on Google Drive (restore tab)
        self._close_when_idle = False
        self._adb_retry_at = 0.0
        self._stop = threading.Event()

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        icon = app_icon()
        self.setWindowIcon(icon if not icon.isNull() else self.style().standardIcon(QStyle.SP_DriveHDIcon))
        self.resize(1040, 860)

        # start screen → backup settings (subpage) / more (the other tabs)  - user request 2026-11-04
        self.tabs = QTabWidget()
        # contents scroll when the window is small, the start buttons always stay visible
        self.tabs.addTab(self._scroll_page(self._build_import_tab(), self.start_import_btn),
                         tr("Import old backup"))
        self.tabs.addTab(self._scroll_page(self._build_export_tab(), self.start_export_btn),
                         tr("Second storage (export)"))
        self.tabs.addTab(self._scroll_page(self._build_restore_tab(), self.start_restore_btn), tr("Restore"))
        self.tabs.addTab(self._scroll_page(self._build_settings_tab()), tr("Settings"))
        self.tabs.currentChanged.connect(self._tab_changed)
        self.pages = QStackedWidget()
        self.home_page = self._build_home()
        self.backup_page = self._build_backup_page()
        self.more_page = self._subpage(tr("Manage backups"), self.tabs)
        for page in (self.home_page, self.backup_page, self.more_page):
            self.pages.addWidget(page)

        # pages and log share the height (the log gives way first); the progress panel below is
        # never squeezed – all upload/copy information visible without scrolling
        bottom = self._build_bottom()
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.pages)
        splitter.addWidget(self.log)
        splitter.setStretchFactor(0, 1)          # more height goes to the page, not the log
        splitter.setStretchFactor(1, 0)
        splitter.setCollapsible(0, False)
        splitter.setSizes([800, 90])
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(splitter, 1)
        cl.addWidget(bottom)
        self.setCentralWidget(central)
        self._phone_status_text = (tr("Looking for a phone …"), GRAY)
        self._set_phone_status(tr("Looking for a phone …"), GRAY, searching=True)
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
        if not os.environ.get("PHONEBACKUP_NO_ADB_OFFER"):
            QTimer.singleShot(1500, self._offer_adb_download)     # ADB missing → ask once
        threading.Thread(target=self._adb_poller, daemon=True).start()
        lastbackup.discover(self.cfg)          # backups on the drives made before the phone list
        self._update_preview()
        self._update_home()

    # ------------------------------------------------------------------ tabs
    @staticmethod
    def _scroll_page(content, action=None):
        """`content` in a scroll area (small windows), `action` (a start button) fixed below it."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(content)
        if action is None:
            return area
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(area, 1)
        row = QHBoxLayout()
        row.setContentsMargins(9, 0, 9, 6)
        row.addStretch()
        row.addWidget(action)
        lay.addLayout(row)
        return w

    def _subpage(self, title, content, scroll=False, action=None):
        """A page with '← Back' and a title above `content` (and a fixed start button below)."""
        w = QWidget()
        lay = QVBoxLayout(w)
        head = QHBoxLayout()
        back = QPushButton(tr("← Back"))
        back.clicked.connect(self._go_home)
        lab = QLabel(title)
        lab.setStyleSheet("font-size:17px;font-weight:600")
        head.addWidget(back)
        head.addSpacing(10)
        head.addWidget(lab, 1)
        lay.addLayout(head)
        if scroll or action is not None:
            content = self._scroll_page(content, action)
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
        self.home_status = StatusBanner()
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
        sel_all = QPushButton(tr("Select all"))
        sel_all.clicked.connect(lambda: [w.pick.setChecked(True) for w in self._phone_widgets.values()])
        rm = QPushButton(tr("Remove from list"))
        rm.setToolTip(tr("Removes the ticked phones from this list. Their backups on the drives are NOT "
                         "deleted; a new backup of the phone adds it again."))
        rm.clicked.connect(self._remove_phones)
        prow.addWidget(sel_all)
        prow.addWidget(rm)
        prow.addStretch()
        pl.addLayout(prow)
        lay.addWidget(_group(tr("Your phones"), pl), 1)
        self._phone_widgets = {}
        lay.addSpacing(8)

        row = QHBoxLayout()
        new = _big_button(tr("New backup…"))
        new.setToolTip(tr("Another phone, or other folders / drives: choose the connection, folders and "
                          "drives, then start."))
        new.clicked.connect(lambda: self._open_backup_page(True))
        settings = QToolButton()
        settings.setIcon(gear_icon(self.palette().buttonText().color()))
        settings.setIconSize(QSize(26, 26))
        settings.setFixedSize(44, 44)
        settings.setToolTip(tr("Backup settings – phone connection, folders and drives"))
        settings.setAccessibleName(tr("Backup settings"))
        settings.clicked.connect(lambda: self._open_backup_page(False))
        more = QPushButton(tr("Manage backups…"))
        more.setMinimumHeight(40)
        more.setToolTip(tr("Import old backups, copy backups to a second storage (export), restore, "
                           "program settings."))
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
        self.backup_page.title_label.setText(tr("New backup") if new_backup else tr("Backup settings"))
        self.start_backup_btn.setVisible(new_backup)
        self.dest_list.update_status()
        self._update_preview()
        self.pages.setCurrentWidget(self.backup_page)

    def _build_backup_page(self):
        # two columns, so everything is visible without scrolling (user request 2026-11-04):
        # left = who + phone connection, right = folders + destinations + start
        # (narrow window, e.g. half the screen: the columns are stacked – see resizeEvent)
        w = QWidget()
        cols = QHBoxLayout(w)
        self._backup_cols = cols
        self._backup_cols_w = w
        lay = QVBoxLayout()
        right = QVBoxLayout()
        cols.addLayout(lay, 1)
        cols.addLayout(right, 1)

        form = QFormLayout()
        self.owner_edit = QLineEdit(self.cfg.get("owner", ""))
        self.owner_edit.setPlaceholderText(tr("e.g. Sam"))
        self.owner_edit.textChanged.connect(self._update_preview)
        self.owner_edit.editingFinished.connect(self._load_profile)
        form.addRow(tr("Owner:"), self.owner_edit)
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText(tr("filled in automatically when the phone is connected"))
        self.phone_edit.textChanged.connect(self._update_preview)
        self.phone_edit.editingFinished.connect(self._load_profile)
        form.addRow(tr("Smartphone name:"), self.phone_edit)
        lay.addWidget(_group(tr("Who and which phone"), form))

        phone_box = QVBoxLayout()
        self.phone_status = StatusBanner()
        phone_box.addWidget(self.phone_status)
        self.conn_overview = ConnectionOverview()
        self.conn_overview.setToolTip(tr("The program always uses the fastest connection it finds."))
        phone_box.addWidget(self.conn_overview)
        self.debug_off_check = WrapCheck(tr("Switch USB debugging / Wireless debugging off on the phone "
                                            "after the backup"))
        self.debug_off_check.setChecked(bool(self.cfg.get("debugging_off_after", True)))
        self.debug_off_check.toggled.connect(self._debug_off_changed)
        phone_box.addWidget(self.debug_off_check)
        self.connect_btn = QPushButton(tr("Connect phone"))
        self.connect_btn.setToolTip(tr("Tries ADB first; if that does not work, the MTP fallback."))
        self.connect_btn.clicked.connect(self._connect_manual)
        self.guide_btn = QPushButton(tr("Switch on USB debugging (first time)…"))
        self.guide_btn.setToolTip(tr("Step-by-step guide for your phone."))
        self.guide_btn.clicked.connect(self._show_usb_guide)
        self.wifi_pair_btn = QPushButton(tr("Pair over Wi-Fi…"))
        self.wifi_pair_btn.setToolTip(tr("Back up without a cable: Android's Wireless debugging "
                                         "(Android 11+). Pair once, then the phone is found "
                                         "automatically in the same Wi-Fi."))
        self.wifi_pair_btn.clicked.connect(self._pair_wifi)
        self.hotspot_btn = QPushButton(tr("Direct Wi-Fi…"))
        self.hotspot_btn.setToolTip(tr("No router? The computer opens its own Wi-Fi network and the "
                                       "phone joins it directly."))
        self.hotspot_btn.clicked.connect(self._direct_wifi)
        self.app_btn = QPushButton(tr("Set up phone app over Wi-Fi…"))
        self.app_btn.setToolTip(tr("Phone app 'My Media Backup': backups over Wi-Fi without USB debugging. "
                                   "It may only read photos and videos."))
        self.app_btn.clicked.connect(self._setup_phone_app)
        self.fastest_btn = QPushButton(tr("Find the fastest connection"))
        self.fastest_btn.setStyleSheet("QPushButton{font-weight:600}")
        self.fastest_btn.setToolTip(tr("Checks the USB cable, the Wi-Fi and Bluetooth and uses the fastest "
                                       "connection – and says what would make it faster."))
        self.fastest_btn.clicked.connect(self._find_fastest)
        self.connect_btn.setText(tr("Connect via file transfer (MTP)"))
        self.connect_btn.setToolTip(tr("Only if nothing else works: the phone's normal file transfer "
                                       "(slower, no check on the phone)."))
        self.app_btn.setText(tr("Phone app over Wi-Fi…"))
        self.connect_btn.setText(tr("File transfer (MTP)"))
        for row in ((self.fastest_btn, self.guide_btn),
                    (self.app_btn, self.wifi_pair_btn, self.hotspot_btn),
                    (self.connect_btn,)):
            btns = QHBoxLayout()
            for b in row:
                btns.addWidget(b)
            btns.addStretch()
            phone_box.addLayout(btns)
        lay.addWidget(_group(tr("Phone connection"), phone_box))

        fl = QHBoxLayout()
        self.folder_list = QListWidget()
        self.folder_list.setMaximumHeight(110)
        # several at once: Ctrl/Shift-click, "Select all" (user request 2026-11-04)
        self.folder_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.folder_list.setMinimumWidth(150)
        self._fill_folder_list()
        fbtn = QVBoxLayout()
        cam = QPushButton(tr("Camera"))
        cam.setToolTip(tr("Adds the phone's camera folder (%s) – the standard place "
                          "for photos and videos on Android.", CAMERA_FOLDER))
        cam.clicked.connect(self._add_camera_folder)
        b = QPushButton(tr("Choose folders…"))
        b.setToolTip(tr("Other folders: screenshots, WhatsApp, downloads … (lists the phone's folders "
                        "when it is connected)."))
        b.clicked.connect(self._choose_folders)
        sel_all = QPushButton(tr("Select all"))
        sel_all.setToolTip(tr("Selects every folder in the list (then “Remove” removes them all)."))
        sel_all.clicked.connect(self.folder_list.selectAll)
        rm = QPushButton(tr("Remove"))
        rm.setToolTip(tr("Removes the selected folders from the list (several: Ctrl- or Shift-click, "
                         "or “Select all”). Nothing on the phone is changed."))
        rm.clicked.connect(self._remove_folder)
        for x in (cam, b, sel_all, rm):
            fbtn.addWidget(x)
        fbtn.addStretch()
        fl.addWidget(self.folder_list, 1)
        fl.addLayout(fbtn)
        fbox = QVBoxLayout()
        fbox.addLayout(fl)
        self.keep_structure_check = WrapCheck(tr("Other folders than Camera: keep the phone's folder "
                                                 "structure\n(e.g. Pictures/Screenshots/…) instead of "
                                                 "sorting them into year/month folders"))
        self.keep_structure_check.setToolTip(tr(
            "On: files from folders like Pictures/Screenshots or WhatsApp land in the same folders "
            "in the backup (…/Pixel 10 Pro - Sam/Pictures/Screenshots/). The camera folder is always "
            "sorted into year/month folders. Files that were already backed up stay where they are."))
        self.keep_structure_check.setChecked(bool(self.cfg.get("keep_structure", False)))
        self.keep_structure_check.toggled.connect(self._keep_structure_changed)
        fbox.addWidget(self.keep_structure_check)
        right.addWidget(_group(tr("Folders on the phone"), fbox))

        self.dest_list = LocationList(
            self.cfg, "destinations", "selected_destinations", True, "PhoneBackups",
            tr("Tick one or more drives - all ticked drives are written at the same time. "
               "Use “Add drive…” for a connected external drive or “Add folder…” to pick any folder."),
            plans_column=True)
        self.dest_list.changed.connect(self._update_preview)
        right.addWidget(_group(tr("Backup destinations"), self.dest_list), 1)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.addWidget(self.preview)

        self.start_backup_btn = _big_button(tr("Start backup"))
        self.start_backup_btn.clicked.connect(lambda: self._start_backup())
        lay.addStretch()
        return self._subpage(tr("New backup"), w, scroll=True, action=self.start_backup_btn)

    def _build_import_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.import_scans, self.import_choices = {}, {}

        mode_row = QHBoxLayout()
        self.imp_existing = QRadioButton(tr("Add to an existing backup"))
        self.imp_new = QRadioButton(tr("New backup of an old phone"))
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
        self.import_roots.setHeaderLabels([tr("Folder"), tr("Selected")])
        self.import_roots.setRootIsDecorated(False)
        self.import_roots.setMaximumHeight(120)
        self.import_roots.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.import_roots.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.import_roots.itemDoubleClicked.connect(lambda *_: self._choose_import_folders())
        src.addWidget(self.import_roots)
        btns = QHBoxLayout()
        for text, fn in ((tr("Add folder…"), self._add_import_root), (tr("Remove"), self._remove_import_root),
                         (tr("Choose folders to import…"), self._choose_import_folders)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        src.addLayout(btns)
        self.import_other_check = WrapCheck(tr(
            "Also import other files (documents, audio, …) – they keep their original folder "
            "under year/other/other-files"))
        src.addWidget(self.import_other_check)
        lay.addWidget(_group(tr("Folders to import (one or more, e.g. the old phone and its SD card)"), src))

        # --- into an existing backup
        self.import_existing_box = QWidget()
        v = QVBoxLayout(self.import_existing_box)
        v.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.import_target = QComboBox()
        self.import_target.currentIndexChanged.connect(self._fill_import_copies)
        refresh = QPushButton(tr("Refresh"))
        refresh.setToolTip(tr("Search the saved backup drives again (attached drives are mounted)"))
        refresh.clicked.connect(lambda: self._fill_import_targets(mount=True))
        top.addWidget(self.import_target, 1)
        top.addWidget(refresh)
        v.addLayout(top)
        hint = QLabel(tr("Copies of this backup on your drives – all ticked copies are updated at the same time:"))
        hint.setStyleSheet(f"color:{GRAY}")
        v.addWidget(hint)
        self.import_copies = QListWidget()
        v.addWidget(self.import_copies)
        self.import_size = QLabel()
        v.addWidget(self.import_size)
        lay.addWidget(_group(tr("Import into backup"), self.import_existing_box), 1)
        self.import_existing_group = self.import_existing_box.parentWidget()

        # --- as a new backup of an old phone
        self.import_new_box = QWidget()
        v = QVBoxLayout(self.import_new_box)
        v.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.import_phone_edit = QLineEdit()
        self.import_phone_edit.setPlaceholderText(tr("e.g. Galaxy S7"))
        self.import_owner_edit = QLineEdit(self.cfg.get("owner", ""))
        self.import_owner_edit.setPlaceholderText(tr("e.g. Sam"))
        form.addRow(tr("Old phone name:"), self.import_phone_edit)
        form.addRow(tr("Owner:"), self.import_owner_edit)
        v.addLayout(form)
        self.import_dest_list = LocationList(
            self.cfg, "destinations", "import_selected_destinations", True, "PhoneBackups",
            tr("Tick the drive(s) to write the old phone's backup to – all ticked drives at the same time."),
            plans_column=True)
        self.import_dest_list.changed.connect(self._update_import_preview)
        v.addWidget(self.import_dest_list, 1)
        self.import_preview = QLabel()
        self.import_preview.setWordWrap(True)
        self.import_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.import_preview)
        self.import_phone_edit.textChanged.connect(self._update_import_preview)
        self.import_owner_edit.textChanged.connect(self._update_import_preview)
        lay.addWidget(_group(tr("New backup"), self.import_new_box), 1)
        self.import_new_group = self.import_new_box.parentWidget()

        self.start_import_btn = _big_button(tr("Start import"))
        self.start_import_btn.clicked.connect(self._start_import)
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
            self.import_info.setText(tr(
                "Makes a backup of its own for an old phone (folder “Phone - Owner” on the drive). Add "
                "the copied folder(s) of the old phone, then choose which folders count: camera folders "
                "are sorted into year/month folders like a real phone backup, all other ticked folders "
                "(pictures, movies, other files) keep their original folder under year/other/. Every "
                "file is checked with SHA-256, identical files are stored only once, and the old folders "
                "are only read – never changed."))
        else:
            self.import_info.setText(tr(
                "Adds the photos and videos of an old backup (or any folders) to one of your backups. "
                "Everything is sorted into the same year/month folders, every file is checked with "
                "SHA-256, identical files are stored only once (also against what is already in the "
                "backup), and the old folders are only read – never changed. Files that are not photos "
                "or videos are skipped and listed in the report (unless “Also import other files” is ticked)."))
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
            it = QTreeWidgetItem([tr("No folder added yet – click “Add folder…”"), ""])
            it.setFlags(Qt.NoItemFlags)
            self.import_roots.addTopLevelItem(it)
        for root, infos in self.import_scans.items():
            chosen = self.import_choices.get(root, {})
            ticked = [i for i in infos if i.rel in chosen]
            cams = sum(1 for i in ticked if chosen[i.rel] == CAMERA)
            files = sum(i.files for i in ticked)
            text = (trp("%d of %d folder (%d camera, %d other)", "%d of %d folders (%d camera, %d other)",
                        len(infos), len(ticked), len(infos), cams, len(ticked) - cams) + ", "
                    + trp("%d file", "%d files", files, files) + ", "
                    + ui.human_size(sum(i.size for i in ticked)))
            it = QTreeWidgetItem([root, text])
            it.setData(0, Qt.UserRole, root)
            self.import_roots.addTopLevelItem(it)

    def _scan_import_root(self, root):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ui.info(tr("Reading the folders of %s ...", root))
            QApplication.processEvents()
            infos = scan_folder(root, into_existing=not self._import_new_mode())
        finally:
            QApplication.restoreOverrideCursor()
        self.import_scans[root] = infos
        self.import_choices[root] = {i.rel: i.kind for i in infos if i.suggested}
        ui.info("  " + trp("%d folder with files, %d suggested.", "%d folders with files, %d suggested.",
                           len(infos), len(infos), len(self.import_choices[root])))

    def _add_import_root(self):
        drives = detect_drives()
        start = next(iter(self.import_scans), None) or (drives[0][0] if drives else str(Path.home()))
        p = QFileDialog.getExistingDirectory(self, tr("Choose a folder to import (e.g. the copy of an old phone)"),
                                             start)
        if not p:
            return
        p = str(Path(p).resolve())
        for other in self.import_scans:
            o = Path(other)
            if Path(p) == o or o in Path(p).parents or Path(p) in o.parents:
                QMessageBox.warning(self, tr("Folder already added"),
                                    tr("%s\noverlaps with the folder already in the list:\n%s\n\n"
                                       "Choose the sub-folders with “Choose folders to import…” instead.",
                                       p, other))
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
        phone = self.import_phone_edit.text().strip() or tr("<old phone>")
        owner = self.import_owner_edit.text().strip() or tr("<owner>")
        dests = self.import_dest_list.selected_paths()
        base = Path(dests[0]) if dests else Path(tr("<drive>"))
        parent = base / backup_parent_name(phone, owner)
        self.import_preview.setText(
            tr("Camera folders → %s   (RAW → YEAR/raw/)", parent / tr("YEAR") / tr("MM.Month-photos | -videos"))
            + "\n" + tr("Other folders → %s/<original folder>",
                        parent / tr("YEAR") / "other" / "pictures | movies | other-files"))

    def _backup_sets(self):
        sets = {}
        for p in find_backups(self.cfg):
            sets.setdefault(Path(p).name, []).append(p)
        return sets

    def _fill_import_targets(self, mount=False):
        if mount:
            _log_mount_msgs(mount_for_paths_status(self.cfg.get("destinations", [])))
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
            it = QListWidgetItem(tr("No backup found on the connected drives – make a phone backup first, "
                                    "or connect the drives and click Refresh."))
            it.setFlags(Qt.NoItemFlags)
            self.import_copies.addItem(it)
        sizes = [backup_totals(p) for p in copies]
        for p, t in zip(copies, sizes):
            it = QListWidgetItem(f"{p}    ({describe_totals(t)})")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, p)
            self.import_copies.addItem(it)

        known = [t for t in sizes if t]
        self.import_size.setText(
            tr("Current state of the backup: %s",
               f"<b>{describe_totals(max(known, key=lambda t: t[0]))}</b>")
            + ("  " + tr("(the copies differ – the largest is shown)") if len(set(known)) > 1 else "")
            if known else "")

    def _start_import(self):
        sel = self._import_selections()
        other_files = self.import_other_check.isChecked()
        if not self.import_scans:
            QMessageBox.warning(self, tr("Cannot start yet"), tr("Add the folder(s) to import."))
            return
        if not sel:
            QMessageBox.warning(self, tr("Cannot start yet"),
                                tr("No folder is ticked – click “Choose folders to import…”."))
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
                problems.append(tr("Enter the name of the old phone."))
            if not owner:
                problems.append(tr("Enter the owner's name."))
            if not dests:
                problems.append(tr("Tick at least one connected destination drive."))
            if problems:
                QMessageBox.warning(self, tr("Cannot start yet"), "\n".join(problems))
                return
            name = backup_parent_name(phone, owner)
            try:
                check_selection(sel, [Path(d) / name for d in dests])
            except ValueError as e:
                QMessageBox.warning(self, tr("Cannot start yet"), str(e))
                return
            existing = [d for d in dests if (Path(d) / name).is_dir()]
            if existing and QMessageBox.question(
                    self, tr("Backup already exists"),
                    tr("There is already a backup “%s” on", name) + "\n" + "\n".join(existing) + "\n\n" +
                    tr("Add the files to it? (Files already in it are not copied twice.)")) \
                    != QMessageBox.Yes:
                return
            self.last_folder = str(Path(dests[0]) / name)
            ui.title(tr("Import old phone %s – %s", phone, owner))
            self.run_job(lambda: perform_old_phone_import(sel, phone, owner, dests, self.cfg,
                                                          other_files=other_files, interactive=True,
                                                          cancel=self.cancel_event),
                         self._import_done, awake=N_("Import"))
            return

        parents = [self.import_copies.item(i).data(Qt.UserRole) for i in range(self.import_copies.count())
                   if self.import_copies.item(i).data(Qt.UserRole)
                   and self.import_copies.item(i).checkState() == Qt.Checked]
        try:
            check_selection(sel, parents)
        except ValueError as e:
            QMessageBox.warning(self, tr("Cannot start yet"), str(e))
            return
        self.last_folder = parents[0]
        ui.title(tr("Import into %s", Path(parents[0]).name))
        self.run_job(lambda: perform_selection_import(sel, parents, self.cfg, other_files=other_files,
                                                      interactive=True, cancel=self.cancel_event),
                     self._import_done, awake=N_("Import"))

    def _import_done(self, res):
        status, paths, _results, verdict = res
        self._finished(status, paths, verdict, N_("Import"))
        self._fill_import_targets()
        self._fill_export_sources()

    def _build_export_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QVBoxLayout()
        row = QHBoxLayout()
        self.export_set = QComboBox()
        self.export_set.currentIndexChanged.connect(lambda *_: self._fill_export_copies())
        refresh = QPushButton(tr("Refresh"))
        refresh.setToolTip(tr("Search the saved backup drives again (attached drives are mounted)"))
        refresh.clicked.connect(lambda: self._fill_export_sources(mount=True))
        b = QPushButton(tr("Browse…"))
        b.setToolTip(tr("Choose a backup folder (“Phone - Owner”) that is not on a saved drive"))
        b.clicked.connect(self._browse_export_src)
        row.addWidget(self.export_set, 1)
        row.addWidget(refresh)
        row.addWidget(b)
        box.addLayout(row)
        row = QHBoxLayout()
        lbl = QLabel(tr("Read from copy:"))
        lbl.setStyleSheet(f"color:{GRAY}")
        self.export_src = QComboBox()
        self.export_src.setToolTip(tr("The backup is on several drives – choose which copy is read"))
        self.export_src.currentIndexChanged.connect(self._refresh_export_info)
        row.addWidget(lbl)
        row.addWidget(self.export_src, 1)
        box.addLayout(row)
        self.export_size = QLabel()
        box.addWidget(self.export_size)
        lay.addWidget(_group(tr("Backup to export"), box))

        self.export_targets = LocationList(
            self.cfg, "export_targets", "selected_export_target", False, "PhoneBackups-Export",
            tr("Click the drive, folder or cloud storage to export to (a different drive than the backup)."),
            cloud=True)
        self.export_targets.changed.connect(self._refresh_export_info)
        self.export_targets.cloud_requested.connect(self._add_cloud)
        lay.addWidget(_group(tr("Second storage"), self.export_targets), 1)

        mode_box = QVBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for i, (m, text) in enumerate([
                ("mirror", tr("Copy – a mirror of the backup: only new files are uploaded, nothing is "
                              "deleted or overwritten")),
                ("auto", tr("Automatic – Grandfather-Father-Son: full every 3 months, differential "
                            "every month, incremental in between")),
                ("full", tr("Full – copy everything")),
                ("differential", tr("Differential – everything new since the last FULL export")),
                ("incremental", tr("Incremental – everything new since the LAST export (any type)"))]):
            rb = QRadioButton(text)
            self.mode_group.addButton(rb, i)
            self.mode_buttons[m] = rb
            mode_box.addWidget(rb)
        self._show_modes(cloud=False)
        self.mode_group.idClicked.connect(self._export_mode_clicked)
        mode_w = QWidget()
        mode_box.setContentsMargins(0, 0, 0, 0)
        mode_w.setLayout(mode_box)
        lay.addWidget(_group(tr("Export type"), mode_w))
        self.export_mode_group = mode_w.parentWidget()
        self.export_hint = QLabel()
        self.export_hint.setWordWrap(True)
        lay.addWidget(self.export_hint)

        self.export_runs = QListWidget()
        self.export_runs.setMaximumHeight(120)
        self.export_runs.itemDoubleClicked.connect(
            lambda it: self._open(it.data(Qt.UserRole)) if it.data(Qt.UserRole) else None)
        runs_box = QVBoxLayout()
        runs_box.addWidget(self.export_runs)
        crow = QHBoxLayout()
        self.export_cleanup_btn = QPushButton(tr("Clean up old exports…"))
        self.export_cleanup_btn.setToolTip(tr("Shows the exports the Grandfather-Father-Son scheme no longer "
                                              "needs – they are only deleted after you confirm."))
        self.export_cleanup_btn.clicked.connect(lambda: self._cleanup_exports())
        crow.addWidget(self.export_cleanup_btn)
        crow.addStretch()
        runs_box.addLayout(crow)
        lay.addWidget(_group(tr("Previous exports on this storage"), runs_box))

        self.start_export_btn = _big_button(tr("Start export"))
        self.start_export_btn.clicked.connect(self._start_export)
        self._fill_export_sources()
        return w

    def _build_restore_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.restore_set = QComboBox()
        self.restore_set.currentIndexChanged.connect(self._refresh_restore_runs)
        b = QPushButton(tr("Browse…"))
        b.clicked.connect(self._browse_restore_set)
        row.addWidget(self.restore_set, 1)
        row.addWidget(b)
        lay.addWidget(_group(tr("Export set on the second storage"), row))
        self.restore_runs = QListWidget()
        lay.addWidget(_group(tr("Restore the state of which export (newest = complete current state)"),
                             self.restore_runs), 1)
        row2 = QHBoxLayout()
        self.restore_dest = QLineEdit()
        self.restore_dest.setPlaceholderText(tr("new or empty folder"))
        b2 = QPushButton(tr("Browse…"))
        b2.clicked.connect(self._browse_restore_dest)
        row2.addWidget(self.restore_dest, 1)
        row2.addWidget(b2)
        lay.addWidget(_group(tr("Restore into"), row2))
        self.start_restore_btn = _big_button(tr("Start restore"))
        self.start_restore_btn.clicked.connect(self._start_restore)
        self._fill_restore_sets()
        return w

    def _choose_language(self, code):
        if not code or code == i18n.stored_choice(self.cfg):
            return
        i18n.store_choice(self.cfg, code)
        new, old = i18n.resolve(code), i18n.current()
        i18n.use(code)                      # ask in the language just picked
        title, text = tr("Language"), tr("The program shows %s after a restart. Restart now?", new.name)
        yes, no = tr("Restart now"), tr("Later")
        i18n.use(old.code)
        box = QMessageBox(QMessageBox.Question, title, text, parent=self)
        restart = box.addButton(yes, QMessageBox.AcceptRole)
        box.addButton(no, QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is restart and not self.busy and self.close():
            from PySide6.QtCore import QProcess
            args = sys.argv[1:] if getattr(sys, "frozen", False) else [os.path.abspath(sys.argv[0]), *sys.argv[1:]]
            QProcess.startDetached(sys.executable, args)

    def _build_settings_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        # Language (user request 2026-11-06): the same languages as VideoSpeedControl
        self.lang_combo = QComboBox()
        stored = i18n.stored_choice(self.cfg)
        self.lang_combo.addItem(tr("System language (%s)", i18n.resolve(i18n.SYSTEM).name), i18n.SYSTEM)
        for lang in i18n.languages():
            self.lang_combo.addItem(lang.name, lang.code)
        idx = self.lang_combo.findData(stored)
        self.lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.lang_combo.currentIndexChanged.connect(lambda _i: self._choose_language(self.lang_combo.currentData()))
        form.addRow(tr("Language:"), self.lang_combo)
        # ADB: one status line; details behind ⓘ, rarely needed choices behind "Change…"
        self.adb_custom = self.cfg.get("adb_path", "")
        row = QHBoxLayout()
        self.adb_status = QLabel()
        self.adb_status.setTextFormat(Qt.RichText)
        self.adb_status.setWordWrap(True)
        self.adb_download_btn = QPushButton(tr("Download ADB…"))
        self.adb_download_btn.setToolTip(tr("Downloads Google's official ADB tool (about 10 MB) – one click, "
                                            "no installation, no admin rights."))
        self.adb_download_btn.clicked.connect(self._download_adb)
        info_btn = QToolButton()
        info_btn.setText("ⓘ")
        info_btn.setToolTip(tr("What is ADB?"))
        info_btn.setAutoRaise(True)
        info_btn.clicked.connect(self._adb_info)
        change = QToolButton()
        change.setText(tr("Change…"))
        change.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(change)
        menu.addAction(tr("Find ADB automatically (recommended)"), self._adb_auto)
        menu.addAction(tr("Use another adb program…"), self._browse_adb)
        menu.addAction(tr("Download the newest ADB from Google…"), self._download_adb)
        change.setMenu(menu)
        # status text above, buttons below: a long (translated) status may wrap freely
        row.addWidget(self.adb_download_btn)
        row.addWidget(info_btn)
        row.addWidget(change)
        row.addStretch()
        adb_box = QVBoxLayout()
        adb_box.addWidget(self.adb_status)
        adb_box.addLayout(row)
        form.addRow(tr("ADB (cable backups):"), adb_box)
        self._update_adb_hint()
        self.wait_spin = QSpinBox()
        self.wait_spin.setRange(1, 300)
        self.wait_spin.setSuffix(tr(" s"))
        self.wait_spin.setValue(int(self.cfg.get("adb_wait_seconds", 20)))
        form.addRow(tr("Wait for the phone (Connect button):"), self.wait_spin)
        self.fsync_check = WrapCheck(tr("Force data onto the disk before verifying (safer, slightly slower)"))
        self.fsync_check.setChecked(bool(self.cfg.get("fsync", True)))
        form.addRow("", self.fsync_check)
        self.awake_check = WrapCheck(tr("Keep the computer awake during backup, import, export and restore\n"
                                        "(no standby or shutdown while a job runs, the screen stays on; "
                                        "power settings stay unchanged)"))
        self.awake_check.setChecked(bool(self.cfg.get("keep_awake", True)))
        form.addRow("", self.awake_check)
        save = QPushButton(tr("Save settings"))
        save.clicked.connect(self._save_settings)
        form.addRow("", save)
        lab = QLabel(tr("Settings file: %s", config.config_path()))
        lab.setWordWrap(True)
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
        self.progress_label = QLabel(tr("Ready."))
        self.progress_label.setWordWrap(True)
        self.progress_label.setTextFormat(Qt.RichText)
        self.progress_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # room for 3 lines (progress, amount/speed, files now) so the panel does not jump
        self.progress_label.setMinimumHeight(self.progress_label.fontMetrics().lineSpacing() * 3 + 4)
        self.progress_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(60)
        row = QHBoxLayout()
        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.report_btn = QPushButton(tr("Open report"))
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(lambda: self._open(self.last_report))
        self.folder_btn = QPushButton(tr("Open backup folder"))
        self.folder_btn.setEnabled(False)
        self.folder_btn.clicked.connect(lambda: self._open(self.last_folder))
        row.addWidget(self.cancel_btn)
        row.addWidget(self.report_btn)
        row.addWidget(self.folder_btn)
        row.addStretch()
        lay.setContentsMargins(9, 6, 9, 6)
        lay.addWidget(self.progress)
        lay.addWidget(self.progress_label)
        lay.addLayout(row)
        return w

    # ------------------------------------------------------------------ jobs
    def run_job(self, func, on_done, busy=True, awake=None):
        """awake = name of a long job ("Backup", ...): the computer is kept from sleeping meanwhile."""
        if busy:
            self._set_busy(True)
        if awake:                       # long job: summary + log file at the end
            self._job = {"name": awake, "t0": time.monotonic(), "started": time.time(),
                         "log_from": len(self.log.toPlainText().split("\n")) if self.log.toPlainText() else 0}
            ui.last_transfer = None
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
            log = self._save_job_log(tr("stopped with an error")) if getattr(self, "_job", None) else None
            box = QMessageBox(QMessageBox.Critical, APP_NAME, tr("Something went wrong:") + f"\n\n{last}"
                              + ("\n\n" + tr("Time: %s", self._job_time()) + "\n" + tr("Log file: %s", log)
                                 if log else ""), parent=self)
            open_btn = box.addButton(tr("Open log file"), QMessageBox.AcceptRole) if log else None
            box.addButton(QMessageBox.Close)
            box.exec()
            if open_btn is not None and box.clickedButton() is open_btn:
                self._open(log)
            self._job = None
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
            self.progress_label.setText(tr("Working …"))

    def _cancel(self):
        self.cancel_event.set()
        self.cancel_btn.setEnabled(False)
        self.progress_label.setText(tr("Cancelling after the current file …"))

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
        if kind == "install":                 # installing on the phone: always asked, clearly
            title, text, details = args
            self.showNormal()
            self.raise_()
            self.activateWindow()
            box = QMessageBox(QMessageBox.Warning, title, text, parent=self)
            box.setTextFormat(Qt.RichText)
            d = html.escape(details).replace("\n", "<br>")
            # the headings in bold – English or in the chosen language (the text comes translated)
            from .companion import INSTALL_HEADINGS
            for head in INSTALL_HEADINGS:
                for h in dict.fromkeys((html.escape(tr(head)), html.escape(head))):
                    if h in d:
                        d = d.replace(h, f"<b>{h}</b>")
                        break
            box.setInformativeText(d)
            yes = box.addButton(tr("Install on the phone"), QMessageBox.AcceptRole)
            no = box.addButton(tr("Not now"), QMessageBox.RejectRole)
            box.setDefaultButton(no)
            box.setEscapeButton(no)
            box.exec()
            return box.clickedButton() is yes
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
        pct = d.get("percent", 100.0 * d["bytes"] / tb if tb else 100.0)
        to_go = d.get("to_go", d["total_files"] - d["files"])
        line = (f"<b>{tr('%.1f %%', pct)}</b>  –  "
                + trp("%s of %s file done", "%s of %s files done", d["total_files"],
                      f"{d['files']:,}", f"{d['total_files']:,}")
                + ", <b>" + tr("%s to go", f"{to_go:,}") + "</b><br>"
                + tr("%s of %s", ui.human_size(d["bytes"]), ui.human_size(tb)) + "  ·  "
                + f"<b>{ui.human_size(d['speed'])}/s</b>  ·  "
                + tr("about %s left", ui.human_duration(d["eta"])))
        active = d.get("active") or ([d["current"]] if d.get("current") else [])
        if active:
            short = [a if len(a) <= 40 else a[:24] + "…" + a[-14:] for a in active[:4]]
            names = ", ".join(html.escape(a) for a in short) + (" …" if len(active) > 4 else "")
            line += f"<br><span style='color:{GRAY}'>{tr('Now: %s', names)}</span>"
        self.progress_label.setText(line)

    # ------------------------------------------------------------------ phone
    def _status_headline(self, color):
        src = self.source
        if src is not None and color in (GREEN, ORANGE):
            phone = f"{getattr(src, 'manufacturer', '')} {src.device_name or ''}".strip() or tr("Phone")
            key = adbsetup.source_key(src)
            conn = tr(CONN_SHORT[key]) if key in CONN_SHORT else getattr(src, "kind", "")
            verified = getattr(src, "link", None) is not None or isinstance(src, CompanionSource)
            return (tr("Connected: %s · %s · verified", phone, conn) if verified
                    else tr("Connected: %s · %s", phone, conn))
        return {ORANGE: tr("Action needed"), RED: tr("Not connected")}.get(color, tr("No phone connected"))

    def _set_phone_status(self, text, color, searching=False):
        """searching=True: the program is looking for / connecting to the phone (headline
        "Searching …") – a flag, so the (translated) text is never compared."""
        head = self._status_headline(color)
        if color == GRAY and searching:
            head = tr("Searching for the phone …")
        self.phone_status.show_status(head, text, color)
        self.home_status.show_status(head, text, color)
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
        w.pick.setToolTip(tr("Tick to remove it from the list (several: tick several, or “Select all”)."))
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
        w.button = _big_button(tr("Update backup"))
        w.button.setToolTip(tr("Same phone, folders and drives as last time – only new photos and "
                               "videos are copied."))
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
                lab = QLabel(tr("No backup yet. Click “New backup…”: choose how the phone is connected, "
                                "which folders and which drives."))
                lab.setWordWrap(True)
                lab.setStyleSheet(f"color:{GRAY}")
                self.phone_rows.addWidget(lab)
        connected = self._connected_phone()
        for key, e in zip(keys, entries):
            w = self._phone_widgets[key]
            w.title.setText(lastbackup.title(e))
            when = e.get("when", "").replace("T", " ") or tr("unknown")
            status = e.get("status", "")
            note = "" if not status or status.startswith("COMPLETED") else f" – {_status_text(status).lower()}"
            w.info.setText(tr("Last backup %s%s  ·  Backup: %s", when, note, self._phone_backup_size(key, e)))
            attached = ()
            if not any(os.path.isdir(d) for d in e["destinations"]):
                try:
                    attached = {d["label"] for d in detect_unmounted()}
                except Exception:  # noqa: BLE001
                    attached = ()
            ok, hint = lastbackup.check(e, connected, attached_labels=attached)
            if not connected:
                hint += " " + tr("Fastest: open “My Media Backup” on the phone, tap “Allow backup over "
                                 "cable” and plug in the USB cable (Wi-Fi: “Start backup mode” in the app).")
            w.button.setEnabled(ok and not self.busy)
            w.hint.setText(f"<span style='color:{GREEN if ok else GRAY}'>{html.escape(hint)}</span>")

    def _phone_backup_size(self, key, e):
        """Size of a phone's backup from a connected drive; remembered for when no drive is there."""
        for d in e.get("destinations", []):
            t = backup_totals(Path(d) / key) if os.path.isdir(Path(d) / key) else None
            if t:
                if [e.get("size_files"), e.get("size_bytes")] != list(t):
                    e["size_files"], e["size_bytes"] = t
                    config.save(self.cfg)
                return describe_totals(t)
        if e.get("size_files") is not None:
            return describe_totals((e["size_files"], e["size_bytes"])) + " " + tr("(drive not connected)")
        return tr("size shown when a backup drive is connected")

    def _remove_phones(self):
        keys = [k for k, w in self._phone_widgets.items() if w.pick.isChecked()]
        if not keys:
            QMessageBox.information(self, APP_NAME, tr("Tick one or more phones first (or “Select all”)."))
            return
        if QMessageBox.question(
                self, tr("Remove from list"),
                tr("Remove these phones from the list?") + "\n\n" + "\n".join(keys)
                + "\n\n" + tr("Their backups on the drives are NOT deleted.")) != QMessageBox.Yes:
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
            if not setup:
                return link
            # also when the app answered: an OUTDATED app is offered for update (asked first)
            state = src.companion_state()
            if link and state != "outdated":
                return link
            if state != "ready":
                if apk is None:
                    ui.warn(tr("The phone app is not included in this program."))
                    return None
                # NEVER install or update anything on the phone without asking (user 2026-11-05)
                phone = f"{src.manufacturer} {src.device_name}".strip() or tr("the phone")
                title, text, details = install_question(state, phone, src.serial,
                                                        getattr(src, "companion_version", ""),
                                                        os.path.getsize(apk))
                if not ui.ask_install(title, text, details):
                    ui.info(tr("Nothing installed on %s (you chose “Not now”).", phone))
                    return link                   # an outdated app keeps working as before
                ui.info(tr("Updating the phone app “%s” %s on %s (serial %s) over the USB cable …",
                           COMPANION_NAME, COMPANION_VERSION, phone, src.serial) if state == "outdated" else
                        tr("Installing the phone app “%s” %s on %s (serial %s) over the USB cable …",
                           COMPANION_NAME, COMPANION_VERSION, phone, src.serial))
                ok, msg = src.install_companion(apk)
                if not ok:
                    ui.warn(tr("The phone app could not be set up: %s – Samsung: switch off “Auto "
                               "Blocker”. Xiaomi: switch on “Install via USB” in the Developer options.", msg))
                    return None
                ui.ok(tr("Phone app “%s” %s updated on %s – it may switch USB debugging.",
                         COMPANION_NAME, COMPANION_VERSION, phone) if state == "outdated" else
                      tr("Phone app “%s” %s installed on %s – it may switch USB debugging.",
                         COMPANION_NAME, COMPANION_VERSION, phone))
                if link is not None:
                    link.close()                      # the old app was stopped by the update
                    link = None
                if state == "outdated":
                    ui.warn(tr("The update restarted the phone app, so its safety countdown for USB "
                               "debugging starts anew: on the phone tap “Allow backup over cable” once "
                               "more (USB debugging stays on), then start the backup."))
            src.control("companion_open")
            for _ in range(10):                       # the app starts its server
                time.sleep(1)
                link, _why = link_over_cable(src, self.cfg)
                if link:
                    return link
            if not ui.ask_yes_no(tr(
                    "Pair the phone app with this computer over the USB cable?\n\nThe phone then "
                    "asks “Pair over the USB cable” and shows a 6-digit code; this program shows "
                    "the same code in the log. Only if both are the same, tap “Pair” on the phone. "
                    "Afterwards this computer recognises the phone by its key (over the cable and "
                    "over Wi-Fi).")):
                return None
            pair_over_cable(src, self.cfg, cancel=self.cancel_event, on_code=lambda code: ui.warn(tr(
                "The phone must show the code  %s %s  – only then tap “Pair” "
                "there (3 minutes). A different code: tap “Refuse”.", code[:3], code[3:])))
            ui.ok(tr("Paired over the USB cable."))
            link, why = link_over_cable(src, self.cfg)
            if not link:
                ui.warn(tr("Paired, but the phone could not be checked: %s", why))
            return link

        def done(link):
            if link is None or self.source is not src:
                return
            src.link = link
            self._set_phone_status(tr(
                "Connected via ADB and verified: %s %s (Android %s) – the phone's key matches the "
                "paired phone. Fast mode with hash check on the phone.",
                src.manufacturer, src.device_name, src.android), GREEN)

        self.run_job(job, done, busy=True)

    def _adb_poller(self):
        """Background: watch `adb devices` so a plugged-in phone is picked up automatically.

        Without a phone it also looks every ~10 s for a paired phone with Wireless debugging
        in the same Wi-Fi and connects it.
        """
        next_wifi = next_app = next_check = next_ble = next_cable = 0.0
        cable_cache = ""
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
                            addr = wireless.auto_connect(adb, self.cfg.get("wifi_last_address", ""),
                                                         self.cfg.get("wifi_serials", []))
                            if addr:
                                wireless.remember(self.cfg, addr, adb)
                                devs = adb_devices(adb)
                    except Exception:  # noqa: BLE001
                        devs = []
                # a phone on the cable WITHOUT USB debugging (e.g. switched off after the last
                # backup) – only found this way; checked at most every 10 s
                cable = ""
                if not any(st in ("device", "unauthorized") and not wireless.is_wireless(s)
                           for s, st in (devs or [])):
                    if now >= next_cable:
                        next_cable = now + 10
                        cable_cache = adbsetup.detect_usb_phone()
                    cable = cable_cache
                else:
                    cable_cache, next_cable = "", 0.0
                self.bridge.adb_state.emit((adb, devs, cable))
            self._stop.wait(2)

    def _on_companion_found(self, found):
        entry, addr = found
        if self.busy or self.connecting or self.source is not None:
            return
        on_cable = adbsetup.detect_usb_phone()
        if on_cable:                  # the phone on the cable comes first - never take another one
            self._set_phone_status(tr(
                "%s is on the USB cable, but USB debugging is off. Tap “Allow backup over "
                "cable” in the phone app (or switch on USB debugging). Phones in the Wi-Fi are not "
                "used while a phone is on the cable.", on_cable), ORANGE)
            return
        self.connecting = True
        self._set_phone_status(tr("Phone app found – connecting …"), GRAY, searching=True)

        def attempt():
            try:
                src = CompanionSource(entry, addr)
            except Exception as e:  # noqa: BLE001
                ui.warn(tr("Phone app connection failed: %s", e))
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
            self._set_phone_status(tr("The phone app is no longer reachable (backup mode off?)."), GRAY)

    def _on_ble_seen(self, entry):
        if self.source is None and not self.busy and not self.connecting:
            self._set_phone_status(tr("%s found over Bluetooth, but it cannot "
                                      "be reached over Wi-Fi. Connect it with the USB cable or to the "
                                      "same Wi-Fi as this computer (Bluetooth is only used to find it).",
                                      entry.get('name') or tr("Your phone")), ORANGE)

    def _setup_phone_app(self):
        from .gui_wireless import PhoneAppDialog
        PhoneAppDialog(self, self.cfg).exec()

    def _on_adb_state(self, state):
        adb, devs, cable = state
        if self.busy or self.connecting:
            return
        src = self.source
        usb_ready = [s for s, st in (devs or []) if st == "device" and not wireless.is_wireless(s)]
        slower = src is not None and (not isinstance(src, AdbSource) or src.wireless)
        if slower and usb_ready and time.monotonic() >= self._adb_retry_at:
            # always the fastest: a phone with USB debugging on the cable beats Wi-Fi / MTP
            ui.info(tr("USB debugging on the cable found – switching from %s to the cable "
                       "(faster).", tr(src.kind)))
            try:
                if isinstance(src, CompanionSource):
                    src.close()
            except Exception:  # noqa: BLE001
                pass
            self.source = src = None
        if isinstance(src, AdbSource):
            if devs is None or src.serial not in [s for s, st in devs if st == "device"]:
                self.source = None
                self._set_phone_status(tr("The phone was disconnected."), GRAY)
            return
        if src is not None:          # phone app / MTP / folder source: keep it
            return
        if adb is None:
            self._set_phone_status(tr("ADB is not installed (see README). Click “Connect phone” to use "
                                      "the MTP fallback."), ORANGE)
            return
        ready = wireless.usb_first([s for s, st in devs if st == "device"])
        if ready and time.monotonic() >= self._adb_retry_at:
            self.connecting = True
            self._set_phone_status(tr("Phone found – connecting via ADB …"), GRAY)

            def attempt(serial=ready[0]):
                try:
                    return AdbSource(adb, serial)
                except Exception as e:  # noqa: BLE001
                    ui.warn(tr("ADB connection failed: %s", e))
                    return None

            self.run_job(attempt, self._on_connected, busy=False)
        elif any(st == "unauthorized" for _, st in devs):
            self._set_phone_status(tr("Phone found: unlock it and tap “Allow USB debugging” "
                                      "(tick “Always allow from this computer”)."), ORANGE)
        elif cable:
            app = bool(self.cfg.get("companion_phones"))
            self._set_phone_status(
                tr("%s is on the USB cable, but USB debugging is off – the computer cannot read "
                   "it yet.", cable) + " " +
                (tr("On the phone open “My Media Backup” and tap “Allow backup over "
                    "cable” (or switch on USB debugging in the Developer options).")
                 if app else tr("Switch on USB debugging on the phone – see “Switch on "
                                "USB debugging (first time)…” in the backup settings.")), ORANGE)
        else:
            self._set_phone_status(tr("No phone connected yet. Plug it in (USB debugging on) or switch "
                                      "on Wireless debugging on a paired phone – it is detected "
                                      "automatically."), GRAY)

    def _pair_wifi(self):
        from .gui_wireless import WifiPairDialog
        adb = find_adb(self.cfg)
        if not adb:
            QMessageBox.warning(self, tr("Pair over Wi-Fi"), tr("ADB is needed for Wi-Fi backups. "
                                                               "Use Settings → ADB → Download ADB… first."))
            return
        dlg = WifiPairDialog(self, adb, self.cfg)
        if dlg.exec() and dlg.connected_address:
            self._adb_retry_at = 0
            self._set_phone_status(tr("Phone connected over Wi-Fi – getting its details …"), GRAY)

    def _direct_wifi(self):
        from .gui_wireless import HotspotDialog
        if not wireless.hotspot_supported():
            QMessageBox.warning(self, tr("Direct Wi-Fi"),
                                tr("NetworkManager (nmcli) was not found. Start a Wi-Fi hotspot in the "
                                   "system settings and connect the phone to it."))
            return
        HotspotDialog(self, self.cfg, self._pair_wifi).exec()

    def _connect_manual(self):
        self.connecting = True
        self._set_phone_status(tr("Connecting …"), GRAY, searching=True)
        self.run_job(lambda: connect_source(self.cfg), self._on_connected)

    def _on_connected(self, src):
        self.connecting = False
        if src is None:
            self._adb_retry_at = time.monotonic() + 10
            self._set_phone_status(tr("Not connected."), RED)
            return
        self.source = src
        typed = self.phone_edit.text().strip()
        if src.device_name and (not typed or typed == self._auto_phone_name):
            self.phone_edit.setText(src.device_name)
            self._auto_phone_name = src.device_name
            self._load_profile()                  # this phone's own folder list
        elif src.device_name and typed.casefold() != src.device_name.casefold():
            QMessageBox.warning(       # never mix up phones: do not silently take the other one
                self, tr("A different phone is connected"),
                tr("Connected: %s %s (%s).\nThe backup is set up for: %s.\n\nThe name was NOT changed. "
                   "A backup only starts if the connected phone is the right one – connect the right "
                   "phone, or change the smartphone name in “Backup settings”.",
                   src.manufacturer, src.device_name, tr(src.kind), typed))
        if isinstance(src, CompanionSource):
            self._set_phone_status(tr(
                "Connected via the phone app: %s %s (Android %s) – Wi-Fi, encrypted, read-only, hash "
                "check on the phone. Backup mode on the phone switches off after the backup.",
                src.manufacturer, src.device_name, src.android), GREEN)
            if not src.full_access:
                QMessageBox.warning(self, tr("Phone app"), tr("The app on the phone has no full access to "
                                    "photos and videos. Open it on the phone and tap “Allow access” "
                                    "→ “Allow all”."))
        elif isinstance(src, AdbSource):
            how = tr("ADB over Wi-Fi") if src.wireless else "ADB"
            self._set_phone_status(tr("Connected via %s: %s %s (Android %s) – fast mode with hash check "
                                      "on the phone.", how, src.manufacturer, src.device_name, src.android)
                                   + (" " + tr("Keep the phone near the computer and on a charger.")
                                      if src.wireless else ""), GREEN)
            self._cable_setup(src)
        else:
            reason = getattr(src, "fallback_reason", "") or ""
            self._set_phone_status(tr("Connected via %s. ADB did not work: %s", tr(src.kind), reason), ORANGE)
            QMessageBox.warning(self, tr("ADB not working – using fallback"),
                                tr("ADB did not work:\n%s\n\n"
                                   "The backup now uses the %s connection instead.\n"
                                   "This is slower, and the phone itself cannot calculate hashes; "
                                   "the copies are compared with the received data instead.", reason, tr(src.kind)))
        self._say_connection(src)
        self._update_preview()

    def _say_connection(self, src):
        """Log which connection is used and - if it is not the fastest - how to get a faster one."""
        key = adbsetup.source_key(src)
        conn = adbsetup.CONNECTIONS_BY_KEY[key]
        if key in ("adb_app", "adb_manual") and not src.wireless:
            mbit = phoneid.usb_speed_mbit()
            if mbit is not None and mbit < 5000:
                ui.warn(tr("Connection: %s – only USB 2 speed. A USB 3 cable and port are "
                           "about 2× faster.", tr(conn.short)))
            else:
                ui.ok(tr("Connection: %s – the fastest connection.", tr(conn.short)))
            return
        on_cable = adbsetup.detect_usb_phone()
        ui.warn(tr("Connection: %s (%s) – not the fastest.", tr(conn.short), conn.speed_short) + " "
                + (tr("The %s is on the USB cable: tap “Allow backup over cable” in the phone "
                      "app – the program then switches to the cable by itself.", on_cable) if on_cable else
                   tr("Faster: plug the phone in with a USB cable and tap “Allow backup over cable” in "
                      "the phone app – the program switches to the cable by itself.")))

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
                    addr = wireless.auto_connect(adb, cfg.get("wifi_last_address", ""),
                                                 cfg.get("wifi_serials", []))
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
                        p["ble"] = e.get("name", tr("your phone"))
            return p

        def show(p):
            best, rows, advice = adbsetup.describe_probe(p)
            lines = "".join(
                f"<tr><td>{'✅' if ok else '–'}</td><td><b>{html.escape(t)}</b></td>"
                f"<td>{html.escape(txt)}</td></tr>" for t, ok, txt in rows)
            QMessageBox.information(self, tr("Fastest connection"),
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
            # the folder itself in the item data: the shown text (translated) is never parsed
            it = QListWidgetItem(tr("%s   (Camera)", f) if f == CAMERA_FOLDER else f)
            it.setData(Qt.UserRole, f)
            self.folder_list.addItem(it)

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
        names = {it.data(Qt.UserRole) or it.text() for it in self.folder_list.selectedItems()}
        if not names:
            QMessageBox.information(self, APP_NAME, tr("Select one or more folders in the list first "
                                                       "(Ctrl- or Shift-click, or “Select all”)."))
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
                    self, tr("Folders on the phone"),
                    trp("%d folder in the list is not on this phone (probably from another "
                        "phone) and was left out:",
                        "%d folders in the list are not on this phone (probably from another "
                        "phone) and were left out:", len(dropped), len(dropped))
                    + "\n\n" + "\n".join(dropped[:15])
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
            self.preview.setText(f"<i>{tr('No destination ticked.')}</i>")
            return
        name = backup_parent_name(phone or tr("<phone>"), owner or tr("<owner>"))
        lines = []
        for d in dests:
            ok = os.path.isdir(d)
            p = html.escape(str(Path(d) / name))
            plan = self._plan_preview(d, name)
            lines.append(f"{p}  <span style='color:{GRAY}'>– {html.escape(plan)}</span>" if ok else
                         f"<span style='color:{GRAY}'>{tr('%s (drive not connected – skipped)', p)}</span>")
        self.preview.setText(f"<b>{tr('Files will be saved to:')}</b><br>" + "<br>".join(lines))

    def _plan_preview(self, base, name):
        from . import plans
        set_dir = Path(base) / name
        have = plans.folder_plan(set_dir)
        plan = have or plans.plan_of(self.cfg, base)
        if plan == plans.SIMPLE:
            return tr("Simple (one folder, new files are added)")
        runs = []
        if have == plans.GFS:
            cat = Catalog(set_dir)
            runs = cat.runs()
            cat.close()
        mode, _why = gfs.choose(runs)
        return tr("Grandfather-Father-Son – this backup will be: %s (%s)", tr(gfs.ROLE[mode]), mode)

    def _mount_selected(self, location_list):
        """Mount ticked drives that are attached but not mounted yet."""
        msgs = mount_for_paths_status(location_list.selected_paths())
        _log_mount_msgs(msgs)
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
            problems.append(tr("Choose at least one folder on the phone (e.g. “Camera”)."))
        if not owner:
            problems.append(tr("Enter the owner's name."))
        if self.source is None:
            problems.append(tr("Connect the phone (or click “Connect phone”)."))
        if not phone:
            problems.append(tr("Enter the name of the smartphone."))
        if not dests:
            problems.append(tr("Tick at least one connected destination drive."))
        if problems:
            QMessageBox.warning(self, tr("Cannot start yet"), "\n".join(problems))
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
        ui.title(tr("Backup %s – %s", phone, owner))

        guard = None
        if isinstance(src, CompanionSource):
            guard = AppGuard(src.client, "wifi")
        elif isinstance(src, AdbSource) and getattr(src, "link", None):
            guard = AppGuard(src.link.client, "wifi-adb" if src.wireless else "usb")

        def job():
            if not src.is_connected():
                raise RuntimeError(tr("The phone is no longer connected - please reconnect it."))
            again = phoneid.identify(src)          # double check right before the first file
            if not phoneid.same_phone(pid, again):
                raise RuntimeError(tr("The phone changed after the check (%s → %s). Nothing was copied.",
                                      pid.label, again.label))
            for parent, result in zip(parents, results):
                phoneid.learn(parent, pid, result)
            ui.ok(tr("Phone checked twice: %s", pid.label)
                  + (tr(", serial %s", pid.serial) if pid.serial else "")
                  + (tr(", phone-app key verified") if pid.app_id else "") + ".")
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

        self.run_job(job, self._backup_done, awake=N_("Backup"))

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
            QMessageBox.warning(self, tr("Folders on the phone"), tr("None of the chosen folders is on this "
                                "phone. Choose its folders with “Choose folders…”."))
            return None
        if QMessageBox.question(
                self, tr("Folders not on this phone"),
                trp("%d of the chosen folders is not on this phone (probably from another phone):",
                    "%d of the chosen folders are not on this phone (probably from another phone):",
                    len(drop), len(drop))
                + "\n\n" + "\n".join(drop[:15]) + ("\n…" if len(drop) > 15 else "")
                + "\n\n" + tr("Remove them from this backup's list and start?")) != QMessageBox.Yes:
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
            QMessageBox.critical(self, tr("Phone check"), tr("The phone could not be identified:") + f"\n{e}")
            return None
        QApplication.restoreOverrideCursor()
        target = f"“{backup_parent_name(phone, owner)}”"
        results = [phoneid.compare(phoneid.load(p), pid) for p in parents]
        if phoneid.MISMATCH in results:
            QMessageBox.critical(
                self, tr("Wrong phone – backup NOT started"),
                (tr("The connected phone is a %s (serial %s), but the backup %s belongs to a different "
                    "phone.", pid.label, pid.serial, target) if pid.serial else
                 tr("The connected phone is a %s, but the backup %s belongs to a different phone.",
                    pid.label, target))
                + "\n\n" + tr("Nothing was copied. Connect the right phone, or choose the right "
                               "smartphone name and owner."))
            return None
        name_ok = phoneid._same(pid.model, phone)
        if phoneid.PROBABLE in results:
            q = tr("The connected %s could only be compared by its model name (this "
                   "connection gives no serial number). Is it really the phone of %s?", pid.label, target)
        elif not name_ok and all(r == phoneid.NEW for r in results):
            q = tr("The connected phone is a %1$s, but the backup is named %2$s.\n\n"
                   "Only continue if this %1$s really is that phone (for example because you "
                   "gave it your own name).", pid.label, target)
        else:
            q = None
        if q is not None:
            box = QMessageBox(QMessageBox.Warning, tr("Is this the right phone?"), q, parent=self)
            yes = box.addButton(tr("Yes, back up this %s", pid.model) if pid.model else
                                tr("Yes, back up this phone"), QMessageBox.AcceptRole)
            box.addButton(tr("Cancel"), QMessageBox.RejectRole)
            box.setDefaultButton(box.buttons()[-1])
            box.exec()
            if box.clickedButton() is not yes:
                return None
        on_cable = adbsetup.detect_usb_phone() if pid.connection != "usb-adb" else ""
        fastest, advice = phoneid.speed_advice(
            pid, phoneid.usb_speed_mbit() if (pid.connection == "usb-adb" or on_cable) else None,
            on_cable)
        how = {"usb-adb": tr("USB cable (USB debugging)"), "wifi-adb": tr("Wi-Fi (Wireless debugging)"),
               "app-wifi": tr("Wi-Fi (phone app)"), "mtp": tr("USB file transfer (MTP)")}.get(pid.connection,
                                                                                         pid.connection)
        text = (tr("Phone: %s", pid.label) + (tr("  ·  serial %s", pid.serial) if pid.serial else "")
                + (tr("  ·  phone-app key verified") if pid.app_id else "")
                + "\n" + tr("Backup: %s", target) + "\n" + tr("Connection: %s", how) + "\n\n" + advice)
        box = QMessageBox(QMessageBox.Information if fastest else QMessageBox.Warning,
                          tr("Start backup?"), text, parent=self)
        go = box.addButton(tr("Start backup") if fastest else tr("Start anyway (slower)"), QMessageBox.AcceptRole)
        box.addButton(tr("Cancel"), QMessageBox.RejectRole)
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
            self._set_phone_status(tr("Backup done – backup mode on the phone was switched off."), GRAY)
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
            what = tr("Wireless debugging") if src.wireless else tr("USB debugging")
            ui.ok(tr("%s on the phone was switched off.", what))
            self._set_phone_status(tr("Backup done – %s on the phone was switched off. "
                                      "You can unplug the phone.", what), GRAY)
        self._finished(status, paths, verdict, N_("Backup"))
        self._fill_export_sources()
        from . import plans
        if status == "COMPLETED":                 # Grandfather-Father-Son drives: suggest cleanup
            name = backup_parent_name(phone, owner)
            for base in dests:
                set_dir = Path(base) / name
                if plans.folder_plan(set_dir) == plans.GFS:
                    self._cleanup_exports(after_export=True, tparent=set_dir)

    def _job_time(self):
        j = getattr(self, "_job", None)
        return ui.human_duration(time.monotonic() - j["t0"]) if j else "–"

    def _job_summary(self):
        """'Time … · Copied … · Average speed …' of the job that just ended."""
        parts = [tr("Time: %s", self._job_time())]
        t = ui.last_transfer
        if t and t["bytes"]:
            parts.append(trp("Copied: %s file, %s", "Copied: %s files, %s", t["files"],
                             f"{t['files']:,}", ui.human_size(t["bytes"])))
            parts.append(tr("Average speed: %s/s", ui.human_size(t["bytes"] / max(t["seconds"], 0.001))))
        elif t:
            parts.append(tr("Nothing new to copy"))
        return parts

    def _save_job_log(self, outcome):
        """The window log of this job as a text file (also when the job stopped with an error)."""
        from .adbdownload import data_dir
        j = self._job
        lines = self.log.toPlainText().split("\n")[j["log_from"]:]
        d = Path(data_dir()) / "logs"
        try:
            d.mkdir(parents=True, exist_ok=True)
            p = d / time.strftime(f"{j['name']} log %Y-%m-%d %H-%M-%S.txt", time.localtime(j["started"]))
            p.write_text(f"{APP_NAME} – {tr(j['name'])} {outcome}\n"
                         + "\n".join(f"  {x}" for x in self._job_summary()) + "\n\n"
                         + "\n".join(lines) + "\n", encoding="utf-8")
            return p
        except OSError as e:
            ui.warn(tr("Could not write the log file: %s", e))
            return None

    def _finished(self, status, paths, verdict, what):
        html_reports = [p for p in paths if str(p).endswith(".html")]
        if html_reports:
            self.last_report = str(html_reports[0])
            self.report_btn.setEnabled(True)
        if self.last_folder:
            self.folder_btn.setEnabled(True)
        summary = self._job_summary()
        what_t, status_t = tr(what), _status_text(status)      # `what`: an N_() text
        self.progress_label.setText(f"{what_t}: {status_t}  ·  " + "  ·  ".join(summary))
        ui.info(f"{what_t}: " + " · ".join(summary))
        txt = [p for p in paths if str(p).endswith(".txt")]
        log = txt[0] if txt else (self._save_job_log(status_t.lower()) if getattr(self, "_job", None) else None)
        if log:
            ui.info(tr("Log file (report): %s", log))
        good = _verdict_good(verdict)            # compared in English, not the shown text
        if good:
            self.progress.setValue(1000)
        text = (f"{_status_text(verdict)}\n\n" + tr("Status: %s", status_t) + "\n\n" + "\n".join(summary)
                + ("\n\n" + tr("Log file (report): %s", log) if log else ""))
        box = QMessageBox(QMessageBox.Information if good else QMessageBox.Warning,
                          tr("%s finished", what_t), text, parent=self)
        open_btn = box.addButton(tr("Open report"), QMessageBox.AcceptRole) if html_reports else None
        log_btn = box.addButton(tr("Open log file"), QMessageBox.ActionRole) if log else None
        box.addButton(QMessageBox.Close)
        box.exec()
        self._job = None
        if open_btn is not None and box.clickedButton() is open_btn:
            self._open(self.last_report)
        elif log_btn is not None and box.clickedButton() is log_btn:
            self._open(log)

    @staticmethod
    def _open(path):
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------------ export
    def _export_sets(self):
        """{backup name: [copies]} – backups on the saved drives plus folders chosen with Browse…
        (Grandfather-Father-Son backups are not exported: they already keep older states.)"""
        from . import plans
        sets = {}
        for name, copies in self._backup_sets().items():
            simple = [p for p in copies if plans.folder_plan(p) != plans.GFS]
            if simple:
                sets[name] = simple
        for e in self.cfg.get("extra_export_sources", []):
            if os.path.isdir(e) and e not in sets.get(Path(e).name, []):
                sets.setdefault(Path(e).name, []).append(e)
        return sets

    def _fill_export_sources(self, select=None, mount=False):
        if mount:
            _log_mount_msgs(mount_for_paths_status(self.cfg.get("destinations", [])))
        cur_path = select or self.export_src.currentData()
        cur_name = Path(cur_path).name if cur_path else self.export_set.currentText()
        self.export_set.blockSignals(True)
        self.export_set.clear()
        for name in sorted(self._export_sets()):
            self.export_set.addItem(name)
        idx = self.export_set.findText(cur_name) if cur_name else -1
        self.export_set.setCurrentIndex(idx if idx >= 0 else 0)
        self.export_set.blockSignals(False)
        self._fill_export_copies(select=cur_path)

    def _fill_export_copies(self, select=None):
        cur = select or self.export_src.currentData()
        self.export_src.blockSignals(True)
        self.export_src.clear()
        for p in self._export_sets().get(self.export_set.currentText(), []):
            self.export_src.addItem(p, p)
        idx = self.export_src.findData(cur) if cur else -1
        self.export_src.setCurrentIndex(idx if idx >= 0 else 0)
        self.export_src.setEnabled(self.export_src.count() > 1)
        self.export_src.blockSignals(False)
        self._refresh_export_info()

    def _update_export_size(self):
        src = self.export_src.currentData()
        self.export_size.setText(tr("Size of the backup: %s", f"<b>{describe_totals(backup_totals(src))}</b>")
                                 if src else "")

    def _browse_export_src(self):
        p = QFileDialog.getExistingDirectory(self, tr("Choose the backup folder (Phone - Owner)"),
                                             (self.cfg.get("destinations") or [str(Path.home())])[0])
        if not p:
            return
        if not is_backup_folder(p):
            QMessageBox.warning(self, APP_NAME, tr("This is not a backup folder of this app.\n\n"
                                "Choose the folder named “Phone - Owner” (it contains the year folders)."))
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

    # ---- cloud storage (Google Drive): a mirror, only new files, nothing deleted
    def _add_cloud(self, service):
        if service != "gdrive":
            return
        if not gdrive.is_configured(self.cfg):
            QMessageBox.information(self, "Google Drive", tr("Google Drive is not set up in this version yet "
                                                             "(the app's Google key is missing)."))
            return
        if gdrive.signed_in_email():
            self.export_targets.add_cloud(GDRIVE)
            self._gdrive_refresh_account()
            return
        if QMessageBox.question(
                self, tr("Add Google Drive"),
                tr("The backup is mirrored to Google Drive: same year/month folders in "
                   "“My Drive/%s”, each export uploads only new files, and nothing on "
                   "Google Drive is ever deleted or overwritten.\n\nThe app gets access ONLY to the files "
                   "it uploads itself – nothing else in your Google Drive.\n\n"
                   "Sign in with Google in the browser now?", gdrive.ROOT_NAME)) != QMessageBox.Yes:
            return
        ui.title(tr("Google Drive sign-in"))
        ui.info(tr("Finish the sign-in in the browser window (Cancel stops waiting)."))

        def job():
            try:
                return True, gdrive.sign_in(self.cfg, cancel=self.cancel_event)
            except Cancelled:
                return False, None                 # None = cancelled (no text compared)
            except gdrive.DriveError as e:
                return False, str(e)

        self.run_job(job, self._gdrive_signed_in)

    def _gdrive_signed_in(self, res):
        ok, text = res
        cancelled = not ok and text is None
        if cancelled:
            text = tr("Sign-in cancelled.")
        if ok:
            ui.ok(tr("Signed in to Google Drive as %s.", text))
            self.progress_label.setText(tr("Signed in to Google Drive."))
            self.export_targets.add_cloud(GDRIVE)
            self._gdrive_runs.clear()          # possibly another Google account
            self._gdrive_sets = None
            self._fill_restore_sets()
        else:
            ui.warn(text)
            self.progress_label.setText(text)
            if not cancelled:
                QMessageBox.warning(self, "Google Drive", text)
        self._gdrive_refresh_account()

    def _gdrive_refresh_account(self):
        self.export_targets.update_status()
        if not (gdrive.is_configured(self.cfg) and gdrive.signed_in_email()
                and GDRIVE in self.export_targets.paths()):
            return

        def get():
            try:
                return gdrive.Drive(self.cfg).account()
            except gdrive.DriveError as e:
                return {"error": str(e)}

        self.run_job(get, self._gdrive_account_done, busy=False)

    def _gdrive_account_done(self, acct):
        if acct and "error" in acct:
            ui.warn(tr("Google Drive: %s", acct['error']))
        else:
            self.export_targets.cloud_info[GDRIVE] = acct
        self.export_targets.update_status()
        self._refresh_export_info()

    # ---- export type: Google Drive has "Copy (mirror)" in addition to the HDD types
    def _show_modes(self, cloud):
        self.mode_buttons["mirror"].setVisible(cloud)
        key, default = ("gdrive_export_mode", "mirror") if cloud else ("export_mode", "auto")
        mode = self.cfg.get(key, default)
        if mode not in self.mode_buttons or (mode == "mirror" and not cloud):
            mode = default
        self.mode_buttons[mode].setChecked(True)

    def _mode(self):
        return [m for m, b in self.mode_buttons.items() if b.isChecked()][0]

    def _load_gdrive_runs(self, name, then=None):
        """Read the GFS exports of one phone on Google Drive (in the background)."""
        self._gdrive_runs[name] = "loading"

        def get():
            try:
                return gdrive_gfs.runs_of(name, self.cfg)
            except getattr(gdrive_gfs, "NoGfsBackup", ()):    # by type, not by its (translated) text
                return [], {}
            except gdrive.DriveError as e:
                if "No Grandfather-Father-Son backup" in str(e):
                    return [], {}
                return {"error": str(e)}

        def done(res):
            if isinstance(res, dict):
                ui.warn(tr("Google Drive: %s", res['error']))
                self._gdrive_runs.pop(name, None)
                return
            self._gdrive_runs[name] = res
            self._refresh_export_info()
            self._refresh_restore_runs()
            if then:
                then()

        self.run_job(get, done, busy=False)

    def _refresh_gdrive_export_info(self, src):
        self.export_mode_group.setVisible(True)
        self.export_cleanup_btn.setEnabled(False)
        self.export_runs.clear()
        mode = self._mode()
        name = Path(src).name if src else None
        signed = gdrive.signed_in_email()
        info, warn = [], []
        if mode == "mirror":
            for m in ("differential", "incremental"):
                self.mode_buttons[m].setEnabled(True)
            if name:
                for p in gdrive.last_reports(name):
                    it = QListWidgetItem(p.stem)
                    it.setData(Qt.UserRole, str(p))
                    it.setToolTip(tr("Double-click to open the report"))
                    self.export_runs.addItem(it)
            info.append(html.escape(tr("Google Drive: a copy of the backup in “My Drive/%s/%s” – only files "
                                       "that are not there yet are uploaded, nothing is deleted or overwritten.",
                                       gdrive.ROOT_NAME, name or tr("Phone - Owner"))))
        else:
            info.append(html.escape(tr(
                "Google Drive – Grandfather-Father-Son in “My Drive/%s/%s”. Every photo is stored once: new "
                "files are uploaded, a full or differential export links to files already on Google "
                "Drive (shortcuts – no extra space, also to the Copy if there is one).",
                gdrive.ROOT_NAME, gdrive_gfs.folder_name(name) if name else tr("Phone - Owner"))))
            cached = self._gdrive_runs.get(name) if name else None
            if name and signed and cached is None:
                self._load_gdrive_runs(name)
                cached = "loading"
            if cached == "loading":
                info.append(tr("Reading the exports on Google Drive …"))
                for m in ("differential", "incremental"):
                    self.mode_buttons[m].setEnabled(False)
            elif cached:
                runs, sizes = cached
                act = gfs.active(runs)
                has_full = any(r.type == "full" and r.status == "COMPLETED" for r in act)
                for r in reversed(act):
                    self.export_runs.addItem(f"{r.folder}    {gfs.label(r)}    "
                                             + tr("%s stored", ui.human_size(sizes.get(r.id, 0)))
                                             + f"    [{_status_text(r.status)}]")
                self.export_cleanup_btn.setEnabled(bool(gfs.to_retire(runs)))
                for m in ("differential", "incremental"):
                    self.mode_buttons[m].setEnabled(has_full)
                if not has_full and mode in ("differential", "incremental"):
                    self.mode_buttons["full"].setChecked(True)
                    warn.append(tr("There is no full export on Google Drive yet – the first export must "
                                   "be a full one."))
                if mode == "auto":
                    m, why = gfs.choose(runs)
                    info.append(tr("This export will be: %s (%s).", f"<b>{tr(gfs.ROLE[m])} – {m}</b>",
                                   html.escape(why)))
        if not src:
            warn.append(tr("No backup found – connect the backup drive and click “Refresh”, or use “Browse…”."))
        if not signed:
            warn.append(tr("Not signed in – click “Add to cloud storage” → Google Drive."))
        self.export_hint.setText("<br>".join(info + [f"<span style='color:{ORANGE}'>{html.escape(h)}</span>"
                                                     for h in warn]))

    def _start_gdrive_export(self, src):
        if not gdrive.signed_in_email():
            QMessageBox.warning(self, tr("Cannot start yet"), tr("Sign in to Google Drive first "
                                "(“Add to cloud storage” → Google Drive)."))
            return
        self.last_folder = None
        mode = self._mode()
        if mode == "mirror":
            ui.title(tr("Google Drive export (copy) of %s", src))
            self.run_job(lambda: gdrive.perform_drive_export(src, self.cfg, cancel=self.cancel_event),
                         self._gdrive_export_done, awake=N_("Export"))
            return
        name = Path(src).name
        if self._gdrive_runs.get(name) == "loading":
            QMessageBox.information(self, APP_NAME, tr("Still reading the exports on Google Drive – "
                                                       "please try again in a moment."))
            return
        ui.title(tr("Google Drive export (%s) of %s",
                    tr("Grandfather-Father-Son") if mode == "auto" else mode, src))

        def done(res):
            self._gdrive_export_done(res)
            self._gdrive_runs.pop(name, None)
            self._gdrive_sets = None
            after = (lambda: self._cleanup_gdrive(name, after_export=True)) if res[0] == "COMPLETED" else None
            self._load_gdrive_runs(name, then=after)
            self._fill_restore_sets()

        self.run_job(lambda: gdrive_gfs.perform_drive_gfs_export(src, self.cfg, mode,
                                                                 cancel=self.cancel_event),
                     done, awake=N_("Export"))

    def _gdrive_export_done(self, res):
        status, paths, verdict = res
        self.folder_btn.setEnabled(False)
        self._finished(status, paths, verdict, N_("Google Drive export"))
        self._gdrive_refresh_account()

    def _cleanup_gdrive(self, name, after_export=False):
        cached = self._gdrive_runs.get(name)
        if not isinstance(cached, tuple):
            return
        runs, sizes = cached
        retire = gfs.to_retire(runs)
        if not self._confirm_cleanup(retire, sizes, f"Google Drive: {gdrive_gfs.folder_name(name)}",
                                     after_export):
            return
        ids = [r.id for r in retire]
        ui.title(tr("Clean up Google Drive: %s", gdrive_gfs.folder_name(name)))

        def done(res):
            removed, problems, freed = res
            self._cleanup_done((removed, problems), freed)
            self._gdrive_runs.pop(name, None)
            self._load_gdrive_runs(name)
            self._gdrive_refresh_account()

        self.run_job(lambda: gdrive_gfs.remove_runs(name, self.cfg, ids), done, awake=N_("Clean up"))

    def _refresh_export_info(self):
        self._update_export_size()
        sel = self.export_targets.selected_paths()
        if sel and is_cloud(sel[0]):
            self._show_modes(cloud=True)
            self._refresh_gdrive_export_info(self.export_src.currentData())
            return
        self._show_modes(cloud=False)
        self.export_mode_group.setVisible(True)
        src, tgt, tparent = self._export_target_parent()
        self.export_runs.clear()
        runs = []
        if tparent and has_catalog(tparent):
            cat = Catalog(tparent)
            runs = cat.runs()
            cat.close()
        act = gfs.active(runs)
        has_full = any(r.type == "full" and r.status == "COMPLETED" for r in act)
        for r in reversed(act):
            self.export_runs.addItem(f"{r.folder}    {gfs.label(r)}    [{_status_text(r.status)}]")
        self.export_cleanup_btn.setEnabled(bool(tparent) and bool(gfs.to_retire(runs)))
        for m in ("differential", "incremental"):
            self.mode_buttons[m].setEnabled(has_full)
        hints, info = [], []
        if not src:
            hints.append(tr("No backup found – connect the backup drive and click “Refresh”, or use “Browse…”."))
        if not tgt:
            hints.append(tr("Choose a connected second storage."))
        if src and tgt and not has_full and not self.mode_buttons["auto"].isChecked():
            self.mode_buttons["full"].setChecked(True)
            hints.append(tr("There is no full export on this storage yet – the first export must be a full one."))
        if src and tgt and self.mode_buttons["auto"].isChecked():
            mode, why = gfs.choose(runs)
            info.append(tr("This export will be: %s (%s).", f"<b>{tr(gfs.ROLE[mode])} – {mode}</b>",
                           html.escape(why)))
        if src and tgt and same_volume(src, tgt):
            hints.append(tr("WARNING: the second storage is on the same drive as the backup – "
                            "this does not protect against a drive failure."))
        self.export_hint.setText("<br>".join(info + [f"<span style='color:{ORANGE}'>{html.escape(h)}</span>"
                                                     for h in hints]))

    def _export_mode_clicked(self, _id):
        mode = self._mode()
        sel = self.export_targets.selected_paths()
        self.cfg["gdrive_export_mode" if sel and is_cloud(sel[0]) else "export_mode"] = mode
        config.save(self.cfg)
        self._refresh_export_info()

    def _cleanup_exports(self, after_export=False, tparent=None):
        """GFS cleanup: list the exports the scheme retires, delete only after confirmation.
        tparent: a Grandfather-Father-Son folder (second storage or backup drive)."""
        if tparent is None:
            sel = self.export_targets.selected_paths()
            if sel and is_cloud(sel[0]):
                src = self.export_src.currentData()
                if src:
                    self._cleanup_gdrive(Path(src).name, after_export)
                return
            _src, _tgt, tparent = self._export_target_parent()
        if not tparent or not has_catalog(tparent):
            return
        cat = Catalog(tparent)
        runs = cat.runs()
        cat.close()
        retire = gfs.to_retire(runs)
        sizes = {r.id: folder_size(Path(tparent) / r.folder) for r in retire}
        if not self._confirm_cleanup(retire, sizes, str(tparent), after_export):
            return
        total = sum(sizes.values())
        ids = [r.id for r in retire]
        ui.title(tr("Clean up %s", tparent))
        # deleting many GB on a HDD takes a while: in the background, computer kept awake
        self.run_job(lambda: remove_runs(tparent, ids), lambda res: self._cleanup_done(res, total),
                     awake=N_("Clean up"))

    def _confirm_cleanup(self, retire, sizes, where, after_export):
        if not retire:
            if not after_export:
                QMessageBox.information(self, tr("Clean up"), tr("Nothing to clean up – every export is still "
                                        "kept by the Grandfather-Father-Son scheme."))
            return False
        total = sum(sizes.get(r.id, 0) for r in retire)
        k = gfs.KEEP
        lines = "\n".join(f"  {r.folder}  –  {gfs.label(r)}, {ui.human_size(sizes.get(r.id, 0))}" for r in retire)
        box = QMessageBox(QMessageBox.Question, tr("Clean up old exports"),
                          tr("The Grandfather-Father-Son scheme keeps the newest %d full, "
                             "%d differential and %d incremental exports "
                             "(and everything they need for a restore).",
                             k['full'], k['differential'], k['incremental']) + "\n\n"
                          + trp("In %s\nthis %d older backup is no longer needed (%s):",
                                "In %s\nthese %d older backups are no longer needed (%s):",
                                len(retire), where, len(retire), ui.human_size(total))
                          + f"\n\n{lines}\n\n"
                          + tr("Delete them now? Their states can then no longer be restored. "
                               "The backup itself is not touched."), parent=self)
        yes = box.addButton(tr("Delete these exports"), QMessageBox.DestructiveRole)
        box.addButton(tr("Keep them"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            ui.info(tr("Old exports kept."))
            return False
        return True

    def _cleanup_done(self, res, total):
        removed, problems = res
        for f in removed:
            ui.ok(tr("Removed old backup %s", f))
        for pr in problems:
            ui.warn(pr)
        ui.info(tr("Clean up: %d removed, %s freed.", len(removed), ui.human_size(total)))
        self.progress_label.setText(trp("Clean up: %d old backup removed, %s freed.",
                                        "Clean up: %d old backups removed, %s freed.",
                                        len(removed), len(removed), ui.human_size(total)))
        self._job = None
        self._refresh_export_info()
        self._fill_restore_sets()

    def _start_export(self):
        sel = self.export_targets.selected_paths()
        if sel and is_cloud(sel[0]):
            self._fill_export_sources()
            src = self.export_src.currentData()
            if not src:
                QMessageBox.warning(self, tr("Cannot start yet"), tr("Choose a backup first."))
                return
            self._start_gdrive_export(src)
            return
        self._mount_selected(self.export_targets)
        self._fill_export_sources()
        src, tgt, tparent = self._export_target_parent()
        if not src or not tgt:
            QMessageBox.warning(self, tr("Cannot start yet"), tr("Choose a backup and a connected second storage."))
            return
        if same_volume(src, tgt) and QMessageBox.question(
                self, tr("Same drive"), tr("The second storage is on the same drive as the backup.\n"
                                           "Continue anyway?")) != QMessageBox.Yes:
            return
        mode = [m for m, b in self.mode_buttons.items() if b.isChecked()][0]
        self.last_folder = str(tparent)
        ui.title(tr("Export (%s) of %s", tr("Grandfather-Father-Son") if mode == "auto" else mode, src))
        self.run_job(lambda: perform_export(src, tgt, mode, self.cfg, cancel=self.cancel_event),
                     self._export_done, awake=N_("Export"))

    def _export_done(self, res):
        status, paths, verdict = res
        self._finished(status, paths, verdict, N_("Export"))
        self._refresh_export_info()
        self._fill_restore_sets()
        if status == "COMPLETED":
            self._cleanup_exports(after_export=True)

    # ------------------------------------------------------------------ restore
    def _fill_restore_sets(self, select=None):
        cur = select or self.restore_set.currentData()
        self.restore_set.blockSignals(True)
        self.restore_set.clear()
        items = find_export_sets(self.cfg)
        extra = self.cfg.get("extra_restore_sets", [])
        for p in items + [e for e in extra if e not in items and has_catalog(e)]:
            self.restore_set.addItem(p, p)
        if gdrive.is_configured(self.cfg) and gdrive.signed_in_email():
            if self._gdrive_sets is None:
                self._load_gdrive_sets()
            for name in self._gdrive_sets or []:
                self.restore_set.addItem(tr("Google Drive: %s", gdrive_gfs.folder_name(name)),
                                         gdrive_gfs.PREFIX + name)
        idx = self.restore_set.findData(cur) if cur else -1
        self.restore_set.setCurrentIndex(idx if idx >= 0 else 0)
        self.restore_set.blockSignals(False)
        self._refresh_restore_runs()

    def _load_gdrive_sets(self):
        self._gdrive_sets = []                       # loading – not again meanwhile

        def get():
            try:
                return gdrive_gfs.list_sets(gdrive.Drive(self.cfg))
            except gdrive.DriveError as e:
                return {"error": str(e)}

        def done(res):
            if isinstance(res, dict):
                ui.warn(tr("Google Drive: %s", res['error']))
                return
            self._gdrive_sets = res
            if res:
                self._fill_restore_sets()

        self.run_job(get, done, busy=False)

    def _browse_restore_set(self):
        p = QFileDialog.getExistingDirectory(self, tr("Choose the export set (Phone - Owner) on the second storage"))
        if not p:
            return
        if not has_catalog(p):
            QMessageBox.warning(self, APP_NAME, tr("No exports found in this folder."))
            return
        extra = self.cfg.get("extra_restore_sets", [])
        if p not in extra:
            self.cfg["extra_restore_sets"] = extra + [p]
            config.save(self.cfg)
        self._fill_restore_sets(select=p)

    def _refresh_restore_runs(self):
        self.restore_runs.clear()
        p = self.restore_set.currentData()
        if p and p.startswith(gdrive_gfs.PREFIX):
            name = p[len(gdrive_gfs.PREFIX):]
            cached = self._gdrive_runs.get(name)
            if cached is None:
                self._load_gdrive_runs(name)
            if not isinstance(cached, tuple):
                self.restore_runs.addItem(tr("Reading the exports on Google Drive …"))
                return
            runs = cached[0]
        elif not p or not has_catalog(p):
            return
        else:
            cat = Catalog(p)
            runs = cat.runs()
            cat.close()
        runs = gfs.active(runs)
        for r in reversed(runs):
            role = tr(gfs.ROLE[r.type]) if r.type in gfs.ROLE else ""
            it = QListWidgetItem(f"{r.folder}    {role}    [{_status_text(r.status)}]")
            it.setData(Qt.UserRole, r.id)
            self.restore_runs.addItem(it)
        if runs:
            self.restore_runs.setCurrentRow(0)

    def _browse_restore_dest(self):
        p = QFileDialog.getExistingDirectory(self, tr("Restore into which folder"))
        if p:
            self.restore_dest.setText(p)

    def _start_restore(self):
        tparent = self.restore_set.currentData()
        it = self.restore_runs.currentItem()
        dest = self.restore_dest.text().strip()
        if not tparent or it is None or not dest:
            QMessageBox.warning(self, tr("Cannot start yet"),
                                tr("Choose an export set, the export state and a target folder."))
            return
        if os.path.isdir(dest) and any(os.scandir(dest)) and QMessageBox.question(
                self, tr("Folder not empty"), tr("The folder is not empty – files with the same name will be "
                                                 "overwritten. Continue?")) != QMessageBox.Yes:
            return
        run_id = it.data(Qt.UserRole)
        if run_id is None:
            return
        self.last_folder = dest
        ui.title(tr("Restore into %s", dest))
        if tparent.startswith(gdrive_gfs.PREFIX):
            name = tparent[len(gdrive_gfs.PREFIX):]
            self.run_job(lambda: gdrive_gfs.perform_restore(name, run_id, dest, self.cfg,
                                                            cancel=self.cancel_event),
                         self._restore_done, awake=N_("Restore"))
            return
        self.run_job(lambda: perform_restore(tparent, run_id, dest, self.cfg, cancel=self.cancel_event),
                     self._restore_done, awake=N_("Restore"))

    def _restore_done(self, res):
        status, paths, verdict = res
        self._finished(status, paths, verdict, N_("Restore"))

    # ------------------------------------------------------------------ settings / misc
    def _update_adb_hint(self):
        from .adbdownload import adb_version
        adb = find_adb({"adb_path": self.adb_custom})
        if adb:
            ver = adb_version(adb).replace("Android Debug Bridge version", "version").strip()
            where = tr("your own choice") if self.adb_custom and adb == self.adb_custom else tr("found automatically")
            self.adb_status.setText(f"<span style='color:{GREEN}'>✓ {tr('Ready')}</span> – {html.escape(ver or 'adb')}"
                                    f" <span style='color:{GRAY}'>({where})</span>")
            self.adb_status.setToolTip(adb)
        else:
            self.adb_status.setText(f"<span style='color:{ORANGE}'>{tr('Not installed')}</span> – "
                                    + tr("cable backups then use the slower phone transfer (MTP)."))
            self.adb_status.setToolTip("")
        self.adb_download_btn.setVisible(not adb)

    def _adb_info(self):
        QMessageBox.information(self, tr("What is ADB?"), (
            "<b>ADB (Android Debug Bridge)</b> " + tr("is Google's free tool for talking to an Android phone "
                                                      "over the cable.") + "<br><br>"
            + tr("With ADB the app copies about 3× faster than the normal phone transfer (MTP) and checks "
                 "every file with SHA-256 <i>on the phone</i> before and after copying.") + "<br><br>"
            + f"<b>{tr('Why is it not built into the app?')}</b> "
            + tr("ADB belongs to Google and its licence does not "
                 "allow other programs to ship it. So the app finds an ADB that is already there (like on "
                 "this computer) or downloads Google's official one for you with one click.") + "<br><br>"
            + tr("Normally you never need to change anything here.")))

    def _adb_auto(self):
        self.adb_custom = ""
        self._save_settings()

    def _offer_adb_download(self):
        """Once, when ADB is missing: offer the download instead of hiding it in the settings."""
        if find_adb(self.cfg) or self.cfg.get("adb_offer_declined"):
            return
        box = QMessageBox(QMessageBox.Question, APP_NAME,
                          tr("For fast cable backups the app needs Google's free ADB tool (about 10 MB).\n\n"
                             "Download it now? Without it, the slower phone transfer (MTP) is used."), parent=self)
        yes = box.addButton(tr("Download…"), QMessageBox.AcceptRole)
        box.addButton(tr("Not now"), QMessageBox.RejectRole)
        never = box.addButton(tr("Don't ask again"), QMessageBox.DestructiveRole)
        box.exec()
        if box.clickedButton() is yes:
            self._download_adb()
        elif box.clickedButton() is never:
            self.cfg["adb_offer_declined"] = True
            config.save(self.cfg)

    def _download_adb(self):
        from .adbdownload import LICENSE_URL, download_adb, platform_name
        box = QMessageBox(self)
        box.setWindowTitle(tr("Download ADB"))
        box.setIcon(QMessageBox.Question)
        box.setTextFormat(Qt.RichText)
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)   # licence link clickable
        box.setText(
            tr("The app downloads Google's official <b>Android SDK Platform-Tools</b> "
               "for %s (about 7–15 MB) directly from Google and keeps them in its own folder. "
               "Nothing is installed in the system and no admin rights are needed.",
               'Windows' if platform_name() == 'windows' else platform_name().capitalize()) + "<br><br>"
            + tr("By downloading you accept Google's licence terms for the platform-tools:") + "<br>"
            f"<a href='{LICENSE_URL}'>{LICENSE_URL}</a>"
            + ("<br><br>" + tr("On Linux you can instead install adb with %s.", "<tt>sudo apt install adb</tt>")
               if platform_name() == "linux" else ""))
        ok = box.addButton(tr("Accept and download"), QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is not ok:
            return
        ui.title(tr("Download ADB"))
        self.run_job(lambda: download_adb(cancel=self.cancel_event), self._adb_downloaded)

    def _adb_downloaded(self, res):
        path, version = res
        self.adb_custom = ""             # the downloaded adb is found automatically
        self._save_settings()
        self._update_adb_hint()
        self.progress_label.setText(tr("ADB downloaded"))
        QMessageBox.information(self, tr("Download ADB"),
                                tr("ADB is ready:\n%s\n%s\n\nConnect the phone with USB debugging "
                                   "switched on and allow this computer on the phone.", path, version))

    def _browse_adb(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("Choose the adb program"))
        if p:
            self.adb_custom = p
            self._save_settings()

    def _save_settings(self):
        self.cfg["adb_path"] = self.adb_custom
        self.cfg["adb_wait_seconds"] = self.wait_spin.value()
        self.cfg["fsync"] = self.fsync_check.isChecked()
        self.cfg["keep_awake"] = self.awake_check.isChecked()
        config.save(self.cfg)
        if hasattr(self, "adb_status"):
            self._update_adb_hint()
        ui.ok(tr("Settings saved."))

    def _tab_changed(self, idx):
        if idx == 0:
            self._fill_import_targets()
            self.import_dest_list.rebuild()
        elif idx == 1:
            self._fill_export_sources()
            if GDRIVE in self.export_targets.paths() and GDRIVE not in self.export_targets.cloud_info:
                self._gdrive_refresh_account()          # free space on Google Drive
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_backup_columns()

    def _fit_backup_columns(self):
        """Backup page: two columns when they fit side by side, otherwise one below the other."""
        cols = getattr(self, "_backup_cols", None)
        if cols is None:
            return
        if not hasattr(self, "_backup_two_cols_width"):
            cols.setDirection(QBoxLayout.LeftToRight)
            self._backup_two_cols_width = self._backup_cols_w.minimumSizeHint().width() + 40
        want = (QBoxLayout.LeftToRight if self.width() >= self._backup_two_cols_width
                else QBoxLayout.TopToBottom)
        if cols.direction() != want:
            cols.setDirection(want)

    def closeEvent(self, event):
        if self.busy:
            if QMessageBox.question(self, tr("Job running"), tr("A job is still running.\n"
                                    "Cancel it and quit after the current file?")) == QMessageBox.Yes:
                self._close_when_idle = True
                self._cancel()
            event.ignore()
            return
        if wireless.hotspot_active():
            ans = QMessageBox.question(self, tr("Direct Wi-Fi"),
                                       tr("Direct Wi-Fi (the computer's own hotspot) is still on.\n"
                                          "Stop it so the computer gets its normal Wi-Fi back?"),
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
    if i18n.current().rtl:               # right-to-left interface language
        app.setLayoutDirection(Qt.RightToLeft)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
