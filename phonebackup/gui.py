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
                               QProgressBar, QPushButton, QRadioButton, QSpinBox, QSplitter,
                               QStyle, QTabWidget, QTextEdit, QTreeWidget, QTreeWidgetItem,
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

PHONE_FOLDER_ROOTS = ["DCIM", "Pictures", "Movies", "Download",
                      "Android/media/com.whatsapp/WhatsApp/Media"]

GREEN, ORANGE, RED, GRAY = "#1f8a4c", "#c76a00", "#c62828", "#808080"


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
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
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

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_backup_tab(), "Backup")
        self.tabs.addTab(self._build_import_tab(), "Import old backup")
        self.tabs.addTab(self._build_export_tab(), "Second storage (export)")
        self.tabs.addTab(self._build_restore_tab(), "Restore")
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        self.tabs.currentChanged.connect(self._tab_changed)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.tabs)
        splitter.addWidget(self._build_bottom())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([600, 260])
        self.setCentralWidget(splitter)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._periodic)
        self.timer.start(3000)
        threading.Thread(target=self._adb_poller, daemon=True).start()
        self._update_preview()

    # ------------------------------------------------------------------ tabs
    def _build_backup_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        top = QHBoxLayout()
        form = QFormLayout()
        self.owner_edit = QLineEdit(self.cfg.get("owner", ""))
        self.owner_edit.setPlaceholderText("e.g. Sam")
        self.owner_edit.textChanged.connect(self._update_preview)
        form.addRow("Owner:", self.owner_edit)
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("filled in automatically when the phone is connected")
        self.phone_edit.textChanged.connect(self._update_preview)
        form.addRow("Smartphone name:", self.phone_edit)
        top.addWidget(_group("Who and which phone", form), 1)

        phone_box = QVBoxLayout()
        self.phone_status = QLabel()
        self.phone_status.setWordWrap(True)
        self.phone_status.setTextFormat(Qt.RichText)
        self.connect_btn = QPushButton("Connect phone")
        self.connect_btn.setToolTip("Tries ADB first; if that does not work, the MTP fallback.")
        self.connect_btn.clicked.connect(self._connect_manual)
        phone_box.addWidget(self.phone_status)
        phone_box.addWidget(self.connect_btn, 0, Qt.AlignLeft)
        top.addWidget(_group("Phone connection", phone_box), 1)
        lay.addLayout(top)
        self._set_phone_status("Looking for a phone via ADB …", GRAY)

        fl = QHBoxLayout()
        self.folder_list = QListWidget()
        self.folder_list.setMaximumHeight(80)
        self._fill_folder_list()
        fbtn = QVBoxLayout()
        b = QPushButton("Choose folders…")
        b.clicked.connect(self._choose_folders)
        fbtn.addWidget(b)
        fbtn.addStretch()
        fl.addWidget(self.folder_list, 1)
        fl.addLayout(fbtn)
        lay.addWidget(_group("Folders on the phone", fl))

        self.dest_list = LocationList(
            self.cfg, "destinations", "selected_destinations", True, "PhoneBackups",
            "Tick one or more drives - all ticked drives are written at the same time. "
            "Use “Add drive…” for a connected external drive or “Add folder…” to pick any folder.")
        self.dest_list.changed.connect(self._update_preview)
        lay.addWidget(_group("Backup destinations", self.dest_list), 1)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.preview)

        self.start_backup_btn = _big_button("Start backup")
        self.start_backup_btn.clicked.connect(self._start_backup)
        lay.addWidget(self.start_backup_btn, 0, Qt.AlignRight)
        return w

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
        row.addWidget(self.adb_edit, 1)
        row.addWidget(b)
        form.addRow("ADB program:", row)
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
        self.tabs.setEnabled(not busy)
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
        self.phone_status.setText(f"<span style='color:{color};font-weight:600'>{html.escape(text)}</span>")

    def _adb_poller(self):
        """Background: watch `adb devices` so a plugged-in phone is picked up automatically."""
        while not self._stop.is_set():
            if not self.busy and not self.connecting:
                adb = find_adb(self.cfg)
                devs = None
                if adb:
                    try:
                        devs = adb_devices(adb)
                    except Exception:  # noqa: BLE001
                        devs = []
                self.bridge.adb_state.emit((adb, devs))
            self._stop.wait(2)

    def _on_adb_state(self, state):
        adb, devs = state
        if self.busy or self.connecting:
            return
        src = self.source
        if isinstance(src, AdbSource):
            if devs is None or src.serial not in [s for s, st in devs if st == "device"]:
                self.source = None
                self._set_phone_status("The phone was disconnected.", GRAY)
            return
        if src is not None:          # MTP / folder source: keep it
            return
        if adb is None:
            self._set_phone_status("ADB is not installed (see README). Click “Connect phone” to use "
                                   "the MTP fallback.", ORANGE)
            return
        ready = [s for s, st in devs if st == "device"]
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
            self._set_phone_status("No phone connected yet. Plug it in (USB debugging on) – "
                                   "it is detected automatically.", GRAY)

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
        if src.device_name:
            self.phone_edit.setText(src.device_name)
        if src.kind == "ADB":
            self._set_phone_status(f"Connected via ADB: {src.manufacturer} {src.device_name} "
                                   f"(Android {src.android}) – fast mode with hash check on the phone.",
                                   GREEN)
        else:
            reason = getattr(src, "fallback_reason", "") or ""
            self._set_phone_status(f"Connected via {src.kind}. ADB did not work: {reason}", ORANGE)
            QMessageBox.warning(self, "ADB not working – using fallback",
                                f"ADB did not work:\n{reason}\n\n"
                                f"The backup now uses the {src.kind} connection instead.\n"
                                "This is slower, and the phone itself cannot calculate hashes; "
                                "the copies are compared with the received data instead.")
        self._update_preview()

    # ------------------------------------------------------------------ folders
    def _fill_folder_list(self):
        self.folder_list.clear()
        for f in self.cfg.get("source_folders") or ["DCIM/Camera"]:
            self.folder_list.addItem(f)

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
            dlg = FolderDialog(self, candidates, current, src is not None)
            if dlg.exec() == QDialog.Accepted:
                self.cfg["source_folders"] = dlg.folders() or ["DCIM/Camera"]
                config.save(self.cfg)
                self._fill_folder_list()

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
        folders = list(self.cfg.get("source_folders") or ["DCIM/Camera"])
        problems = []
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
        self.cfg["owner"] = owner
        config.save(self.cfg)
        src = self.source
        self.last_folder = str(Path(dests[0]) / backup_parent_name(phone, owner))
        ui.title(f"Backup {phone} – {owner}")

        def job():
            if not src.is_connected():
                raise RuntimeError("The phone is no longer connected - please reconnect it.")
            return perform_backup(src, phone, owner, folders, dests, self.cfg,
                                  interactive=True, cancel=self.cancel_event)

        self.run_job(job, self._backup_done, awake="Backup")

    def _backup_done(self, res):
        status, paths, _results, verdict = res
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
        ui.ok("Settings saved.")

    def _tab_changed(self, idx):
        if idx == 1:
            self._fill_import_targets()
            self.import_dest_list.rebuild()
        elif idx == 2:
            self._fill_export_sources()
        elif idx == 3:
            self._fill_restore_sets()

    def _periodic(self):
        if self.busy:
            return
        self.dest_list.update_status()
        self.export_targets.update_status()
        self.import_dest_list.update_status()
        self._update_preview()

    def closeEvent(self, event):
        if self.busy:
            if QMessageBox.question(self, "Job running", "A job is still running.\n"
                                    "Cancel it and quit after the current file?") == QMessageBox.Yes:
                self._close_when_idle = True
                self._cancel()
            event.ignore()
            return
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
