"""Manage backups → "Backups" tab and the program settings' lists (user request 2026-11-10).

Backups tab: the known backups on top; choose one and
  * Phone      – its standard folders (used by "Update backup" on the start screen), update it now,
                 or back up other phone folders once,
  * Drives     – the backup drives of this backup,
  * Import     – folders (old drives, old phone copies) to import into it: sorted into YYYY/YY.MM or
                 with their original folder structure.
"New backup of an old phone / old drive" is a page of its own with a way back.

Program settings: standard folders for new backups and the phones paired with this computer.
"""

import html
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QRadioButton,
                               QStackedWidget, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import APP_NAME, backuplist, companion, lastbackup, setfolders, ui
from .i18n import N_, tr, trp
from .importer import CAMERA, OTHER, check_selection, guess_kind, scan_folder
from .index import backup_totals, describe_totals
from .locations import detect_drives, find_backups, mount_for_paths_status

GRAY, GREEN = "#808080", "#1f8a4c"
CAMERA_FOLDER = backuplist.CAMERA_FOLDER


def _gui():
    from . import gui            # gui imports this module: look it up when used
    return gui


def _fit_height(view, rows_min=2, rows_max=6):
    """A list as high as its rows (between rows_min and rows_max) – no big empty boxes."""
    n = view.topLevelItemCount() if isinstance(view, QTreeWidget) else view.count()
    row = view.sizeHintForRow(0) if n else view.fontMetrics().height() + 8
    row = max(row, view.fontMetrics().height() + 6)
    head = view.header().height() if isinstance(view, QTreeWidget) and not view.isHeaderHidden() else 0
    view.setFixedHeight(head + row * max(rows_min, min(n, rows_max)) + 2 * view.frameWidth() + 6)


def _short(path):
    parts = Path(path).parts
    return "/".join(parts[-2:]) if len(parts) > 1 else str(path)


# =========================================================================== folder list

class FolderListEditor(QWidget):
    """Phone folders: Camera, Choose folders…, Select all, Remove (several at once)."""
    changed = Signal(list)
    choose_requested = Signal()

    def __init__(self, hint=""):
        super().__init__()
        self._folders = []
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setMinimumWidth(150)
        cam = QPushButton(tr("Camera"))
        cam.setToolTip(tr("Adds the phone's camera folder (%s) – the standard place "
                          "for photos and videos on Android.", CAMERA_FOLDER))
        cam.clicked.connect(self._add_camera)
        choose = QPushButton(tr("Choose folders…"))
        choose.setToolTip(tr("Other folders: screenshots, WhatsApp, downloads … (lists the phone's folders "
                             "when it is connected)."))
        choose.clicked.connect(self.choose_requested.emit)
        sel_all = QPushButton(tr("Select all"))
        sel_all.clicked.connect(self.list.selectAll)
        rm = QPushButton(tr("Remove"))
        rm.setToolTip(tr("Removes the selected folders from the list (several: Ctrl- or Shift-click, "
                         "or “Select all”). Nothing on the phone is changed."))
        rm.clicked.connect(self._remove)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        if hint:
            lab = QLabel(hint)
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color:{GRAY}")
            lay.addWidget(lab)
        row = QHBoxLayout()
        row.addWidget(self.list, 1)
        btns = QVBoxLayout()
        for b in (cam, choose, sel_all, rm):
            btns.addWidget(b)
        btns.addStretch()
        row.addLayout(btns)
        lay.addLayout(row)

    def folders(self):
        return list(self._folders)

    def set_folders(self, folders, emit=False):
        self._folders = list(dict.fromkeys(folders))
        self.list.clear()
        for f in self._folders:
            it = QListWidgetItem(tr("%s   (Camera)", f) if f == CAMERA_FOLDER else f)
            it.setData(Qt.UserRole, f)
            self.list.addItem(it)
        self.list.setFixedHeight(max(4, min(len(self._folders), 6)) * (self.list.fontMetrics().height() + 8) + 8)
        if emit:
            self.changed.emit(self.folders())

    def _add_camera(self):
        if CAMERA_FOLDER not in self._folders:
            self.set_folders([CAMERA_FOLDER] + self._folders, emit=True)

    def _remove(self):
        names = {it.data(Qt.UserRole) for it in self.list.selectedItems()}
        if not names:
            QMessageBox.information(self, APP_NAME, tr("Select one or more folders in the list first "
                                                       "(Ctrl- or Shift-click, or “Select all”)."))
            return
        rest = [f for f in self._folders if f not in names]
        if not rest:
            QMessageBox.information(self, APP_NAME, tr("At least one folder must stay in the list."))
            return
        self.set_folders(rest, emit=True)


# =========================================================================== import sources

class ImportSources(QWidget):
    """Folders to import from (old drive, old phone copy) and how they are sorted."""
    changed = Signal()

    HOW_SORT, HOW_KEEP, HOW_MIXED = "sort", "keep", "mixed"

    def __init__(self, into_existing):
        super().__init__()
        self.into_existing = into_existing
        self.roots = []            # in the order added
        self.scans = {}            # root -> [FolderInfo] (read when needed)
        self.choices = {}          # root -> {rel: CAMERA | OTHER}
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Folder"), tr("Selected")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemDoubleClicked.connect(lambda *_: self.choose())
        btns = QHBoxLayout()
        for text, fn, tip in (
                (tr("Add folder…"), self.add_root, tr("A folder on an old drive, a copy of an old phone, "
                                                      "an SD card …")),
                (tr("Choose folders to import…"), self.choose, tr("Tick the folders inside and how each "
                                                                  "is sorted.")),
                (tr("Select all"), self.tree.selectAll, ""),
                (tr("Remove"), self.remove_selected, tr("Removes the selected folders from this list. "
                                                        "Nothing on the drive is changed."))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            if tip:
                b.setToolTip(tip)
            btns.addWidget(b)
        btns.addStretch()

        self.how_sort = QRadioButton(tr("Sort the photos and videos into year/month folders (YYYY/YY.MM)"))
        self.how_keep = QRadioButton(tr("Keep the original folder structure"))
        self.how_mixed = QRadioButton(tr("Chosen per folder (“Choose folders to import…”)"))
        self.how_group = QButtonGroup(self)
        for i, rb in enumerate((self.how_sort, self.how_keep, self.how_mixed)):
            self.how_group.addButton(rb, i)
        (self.how_sort if into_existing else self.how_mixed).setChecked(True)
        self.how_group.idClicked.connect(self._how_clicked)
        self.other_check = _gui().WrapCheck(tr(
            "Also import other files (documents, audio, …) – they keep their original folder"))
        self.other_check.setChecked(not into_existing)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tree)
        lay.addLayout(btns)
        how = QLabel(tr("How:"))
        how.setStyleSheet("font-weight:600")
        lay.addWidget(how)
        for rb in (self.how_sort, self.how_keep, self.how_mixed):
            lay.addWidget(rb)
        lay.addWidget(self.other_check)
        self.fill()

    # ---- data
    def load(self, roots, choices):
        """Roots and choices from the settings (not read yet – read when needed)."""
        self.roots = [r for r in roots]
        self.scans = {r: s for r, s in self.scans.items() if r in self.roots}
        self.choices = {r: dict(choices.get(r, {})) for r in self.roots}
        self._sync_how()
        self.fill()

    def how(self):
        return {0: self.HOW_SORT, 1: self.HOW_KEEP}.get(self.how_group.checkedId(), self.HOW_MIXED)

    def selections(self):
        return [(root, rel, kind) for root in self.roots for rel, kind in self.choices.get(root, {}).items()]

    def other_files(self):
        return self.other_check.isChecked()

    # ---- view
    def fill(self):
        self.tree.clear()
        if not self.roots:
            it = QTreeWidgetItem([tr("No folder added yet – click “Add folder…”"), ""])
            it.setFlags(Qt.NoItemFlags)
            self.tree.addTopLevelItem(it)
        for root in self.roots:
            chosen = self.choices.get(root, {})
            infos = self.scans.get(root)
            cams = sum(1 for k in chosen.values() if k == CAMERA)
            if infos is None:
                text = (trp("%d folder ticked (%d sorted, %d kept as they are)",
                            "%d folders ticked (%d sorted, %d kept as they are)",
                            len(chosen), len(chosen), cams, len(chosen) - cams)
                        if chosen else tr("nothing ticked yet – “Choose folders to import…”"))
            else:
                ticked = [i for i in infos if i.rel in chosen]
                files = sum(i.files for i in ticked)
                text = (trp("%d of %d folder (%d sorted, %d kept as they are)",
                            "%d of %d folders (%d sorted, %d kept as they are)",
                            len(infos), len(ticked), len(infos), cams, len(ticked) - cams) + ", "
                        + trp("%d file", "%d files", files, files) + ", "
                        + ui.human_size(sum(i.size for i in ticked)))
            it = QTreeWidgetItem([root, text])
            it.setData(0, Qt.UserRole, root)
            it.setToolTip(0, root)
            if not os.path.isdir(root):
                it.setForeground(0, QColor(GRAY))
                it.setText(1, tr("not connected") + ("  ·  " + text if chosen else ""))
            self.tree.addTopLevelItem(it)
        _fit_height(self.tree, 2, 5)

    def _sync_how(self):
        kinds = {k for ch in self.choices.values() for k in ch.values()}
        if kinds == {CAMERA}:
            self.how_sort.setChecked(True)
        elif kinds == {OTHER}:
            self.how_keep.setChecked(True)
        elif kinds:
            self.how_mixed.setChecked(True)

    def _how_clicked(self, _id):
        how = self.how()
        if how == self.HOW_MIXED:
            if self.roots:
                self.choose()
            return
        kind = CAMERA if how == self.HOW_SORT else OTHER
        for root in self.roots:
            self.choices[root] = {rel: kind for rel in self.choices.get(root, {})}
        self.fill()
        self.changed.emit()

    # ---- actions
    def scan(self, root):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ui.info(tr("Reading the folders of %s ...", root))
            QApplication.processEvents()
            infos = scan_folder(root, into_existing=self.into_existing)
        finally:
            QApplication.restoreOverrideCursor()
        self.scans[root] = infos
        return infos

    def _suggest(self, root, infos):
        how = self.how()
        chosen = {}
        for i in infos:
            if i.suggested:
                chosen[i.rel] = (i.kind if how == self.HOW_MIXED else
                                 CAMERA if how == self.HOW_SORT else OTHER)
        self.choices[root] = chosen
        ui.info("  " + trp("%d folder with files, %d suggested.", "%d folders with files, %d suggested.",
                           len(infos), len(infos), len(chosen)))

    def add_root(self):
        drives = detect_drives()
        start = self.roots[0] if self.roots else (drives[0][0] if drives else str(Path.home()))
        p = QFileDialog.getExistingDirectory(self, tr("Choose a folder to import (e.g. the copy of an old phone)"),
                                             start)
        if not p:
            return
        p = str(Path(p).resolve())
        for other in self.roots:
            o = Path(other)
            if Path(p) == o or o in Path(p).parents or Path(p) in o.parents:
                QMessageBox.warning(self, tr("Folder already added"),
                                    tr("%s\noverlaps with the folder already in the list:\n%s\n\n"
                                       "Choose the sub-folders with “Choose folders to import…” instead.",
                                       p, other))
                return
        self.roots.append(p)
        self._suggest(p, self.scan(p))
        self.fill()
        self.changed.emit()
        self.choose()

    def remove_selected(self):
        roots = {it.data(0, Qt.UserRole) for it in self.tree.selectedItems()} - {None}
        if not roots:
            QMessageBox.information(self, APP_NAME, tr("Select one or more folders in the list first "
                                                       "(Ctrl- or Shift-click, or “Select all”)."))
            return
        self.roots = [r for r in self.roots if r not in roots]
        for r in roots:
            self.scans.pop(r, None)
            self.choices.pop(r, None)
        self.fill()
        self.changed.emit()

    def choose(self):
        if not self.roots:
            self.add_root()
            return
        missing = [r for r in self.roots if not os.path.isdir(r)]
        if missing:
            QMessageBox.warning(self, tr("Folder not found"),
                                tr("These folders are not connected right now:") + "\n\n" + "\n".join(missing))
        roots = [r for r in self.roots if os.path.isdir(r)]
        for r in roots:
            if r not in self.scans:
                old = self.choices.get(r)
                infos = self.scan(r)
                if old is None:
                    self._suggest(r, infos)
        if not roots:
            return
        scans = {r: self.scans[r] for r in roots}
        for infos in scans.values():
            for info in infos:
                guess_kind(info.rel, info, into_existing=self.into_existing)
        dlg = _gui().ImportSelectionDialog(self, scans, {r: self.choices.get(r, {}) for r in roots})
        if dlg.exec() == dlg.Accepted:
            self.choices.update(dlg.choices())
            self._sync_how()
            self.fill()
            self.changed.emit()

    def check_ready(self):
        """None if it can start, else the reason."""
        if not self.roots:
            return tr("Add the folder(s) to import.")
        if not self.selections():
            return tr("No folder is ticked – click “Choose folders to import…”.")
        gone = [r for r in self.roots if self.choices.get(r) and not os.path.isdir(r)]
        if gone:
            return tr("These folders are not connected right now:") + "\n\n" + "\n".join(gone)
        return None


# =========================================================================== paired phones

class KnownPhonesBox(QWidget):
    """Program settings: the phones paired with this computer (phone app). Delete = unpair."""

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Phone"), tr("Paired on"), tr("Paired via"), tr("App version")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        sel_all = QPushButton(tr("Select all"))
        sel_all.clicked.connect(self.tree.selectAll)
        delete = QPushButton(tr("Delete…"))
        delete.setToolTip(tr("Removes the selected phones from this computer. Their backups are NOT "
                             "deleted. To use the phone app again, pair the phone again."))
        delete.clicked.connect(self.delete_selected)
        row = QHBoxLayout()
        row.addWidget(sel_all)
        row.addWidget(delete)
        row.addStretch()
        lab = QLabel(tr("Phones paired with this computer (phone app “My Media Backup”). "
                        "Select one or more (Ctrl- or Shift-click) to delete them."))
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{GRAY}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(lab)
        lay.addWidget(self.tree)
        lay.addLayout(row)
        self.fill()

    def fill(self):
        self.tree.clear()
        phones = companion.phones(self.cfg)
        if not phones:
            it = QTreeWidgetItem([tr("No phone paired yet."), "", "", ""])
            it.setFlags(Qt.NoItemFlags)
            self.tree.addTopLevelItem(it)
        for p in phones:
            via = {"cable": tr("USB cable")}.get(p.get("via", ""), tr("Wi-Fi"))
            it = QTreeWidgetItem([p.get("name") or tr("unknown phone"), p.get("paired", ""), via,
                                  p.get("app_version") or "–"])
            it.setData(0, Qt.UserRole, p.get("phone_id"))
            self.tree.addTopLevelItem(it)
        _fit_height(self.tree, 2, 6)

    def delete_selected(self):
        items = [it for it in self.tree.selectedItems() if it.data(0, Qt.UserRole)]
        if not items:
            QMessageBox.information(self, APP_NAME, tr("Select one or more phones first (or “Select all”)."))
            return
        names = "\n".join(it.text(0) for it in items)
        box = QMessageBox(QMessageBox.Warning, tr("Delete phones?"),
                          trp("Are you sure you want to delete this phone from this computer?",
                              "Are you sure you want to delete these %d phones from this computer?",
                              len(items), len(items))
                          + "\n\n" + names + "\n\n"
                          + tr("Their backups are NOT deleted. To back up over Wi-Fi with the phone app "
                               "again, the phone must be paired again."), parent=self)
        yes = box.addButton(tr("Delete"), QMessageBox.DestructiveRole)
        box.addButton(tr("Cancel"), QMessageBox.RejectRole)
        box.setDefaultButton(box.buttons()[-1])
        box.exec()
        if box.clickedButton() is not yes:
            return
        for it in items:
            companion.forget_phone(self.cfg, it.data(0, Qt.UserRole))
        ui.ok(trp("%d phone deleted from this computer.", "%d phones deleted from this computer.",
                  len(items), len(items)))
        self.fill()


# =========================================================================== the Backups tab

class BackupsTabMixin:
    """Methods of the main window for the "Backups" tab (Manage backups)."""

    def _backup_sets(self):
        """{key: [backup folders on the connected drives]}"""
        sets = {}
        for p in find_backups(self.cfg):
            sets.setdefault(setfolders.key_of(p), []).append(p)
        return sets

    def _build_backups_tab(self):
        self.backups_stack = QStackedWidget()
        self.backups_stack.addWidget(self._build_backups_manage())
        self.backups_stack.addWidget(self._build_old_import_page())
        return self.backups_stack

    # ---------------------------------------------------------------- page 1: your backups
    def _build_backups_manage(self):
        g = _gui()
        w = QWidget()
        lay = QVBoxLayout(w)
        self.backups_tree = QTreeWidget()
        self.backups_tree.setHeaderLabels([tr("Backup"), tr("Last backup"), tr("Size"), tr("Backup drives")])
        self.backups_tree.setRootIsDecorated(False)
        self.backups_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        h = self.backups_tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.backups_tree.itemSelectionChanged.connect(self._backup_selected)
        top = QVBoxLayout()
        top.addWidget(self.backups_tree)
        row = QHBoxLayout()
        sel_all = QPushButton(tr("Select all"))
        sel_all.clicked.connect(self.backups_tree.selectAll)
        rm = QPushButton(tr("Remove from list"))
        rm.setToolTip(tr("Removes the selected backups from this list and from the start screen. "
                         "The backups on the drives are NOT deleted; a new backup of the phone adds it again."))
        rm.clicked.connect(self._remove_backups_from_list)
        self.backups_show_hidden = g.WrapCheck(tr("Also show removed backups"))
        self.backups_show_hidden.toggled.connect(lambda _on: self._refresh_backups())
        refresh = QPushButton(tr("Refresh"))
        refresh.setToolTip(tr("Search the saved backup drives again (attached drives are mounted)"))
        refresh.clicked.connect(lambda: self._refresh_backups(mount=True))
        new_old = QPushButton(tr("New backup of an old phone or drive…"))
        new_old.setToolTip(tr("Backs up an old phone or an old hard drive like a phone – its own backup."))
        new_old.clicked.connect(lambda: self._show_old_import(True))
        for b in (sel_all, rm, refresh):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(new_old)
        top.addLayout(row)
        top.addWidget(self.backups_show_hidden)
        lay.addWidget(g._group(tr("Your backups"), top))

        # ---- the chosen backup
        self.backup_detail_hint = QLabel()
        self.backup_detail_hint.setWordWrap(True)
        self.backup_detail_hint.setStyleSheet(f"color:{GRAY}")
        self.backup_tabs = QTabWidget()
        self.backup_tabs.addTab(self._build_backup_phone_tab(), tr("Phone"))
        self.backup_tabs.addTab(self._build_backup_drives_tab(), tr("Backup drives"))
        self.backup_tabs.addTab(self._build_backup_import_tab(), tr("Import folders"))
        box = QVBoxLayout()
        box.addWidget(self.backup_detail_hint)
        box.addWidget(self.backup_tabs)
        # the buttons ("Update backup now" …) are pinned below the scroll area (main window): always
        # visible, whichever tab is open (user request 2026-11-10)
        self.backup_actions = QWidget()
        self.backup_actions.setLayout(self._build_backup_actions())
        self.backup_detail = g._group(tr("Selected backup"), box)
        lay.addWidget(self.backup_detail)
        lay.addStretch(1)
        self._backups = []
        return w

    def _build_backup_phone_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.backup_folders = FolderListEditor(tr(
            "Standard folders on the phone – “Update backup” on the start screen backs up these folders:"))
        self.backup_folders.changed.connect(self._backup_folders_changed)
        self.backup_folders.choose_requested.connect(
            lambda: self._pick_phone_folders(self.backup_folders.folders(),
                                             lambda f: self.backup_folders.set_folders(f, emit=True)))
        lay.addWidget(self.backup_folders)
        self.backup_keep_check = _gui().WrapCheck(tr("Other folders than Camera: keep the phone's folder "
                                                     "structure instead of sorting them into year/month folders"))
        self.backup_keep_check.toggled.connect(self._backup_keep_changed)
        lay.addWidget(self.backup_keep_check)
        lay.addStretch()
        return w

    def _build_backup_actions(self):
        """Below the tabs (user request 2026-11-10): usable from every tab of the chosen backup."""
        actions = QVBoxLayout()
        row = QHBoxLayout()
        self.backup_update_btn = QPushButton(tr("Update backup now"))
        self.backup_update_btn.setStyleSheet("QPushButton{font-weight:600}")
        self.backup_update_btn.setToolTip(tr("Connect the phone: copies the new photos and videos of the "
                                             "standard folders."))
        self.backup_update_btn.clicked.connect(lambda: self._backup_update_now(False))
        once = QPushButton(tr("Back up other phone folders…"))
        once.setToolTip(tr("Choose folders on the connected phone and back them up into this backup once – "
                           "the standard folders stay as they are."))
        once.clicked.connect(lambda: self._backup_update_now(True))
        connect = QPushButton(tr("Connect phone…"))
        connect.setToolTip(tr("Without a cable: a QR code to scan with the phone."))
        connect.clicked.connect(self._connect_phone_dialog)
        row.addWidget(self.backup_update_btn)
        row.addWidget(once)
        row.addWidget(connect)
        row.addStretch()
        actions.addLayout(row)
        self.backup_phone_hint = QLabel()
        self.backup_phone_hint.setWordWrap(True)
        actions.addWidget(self.backup_phone_hint)
        return actions

    def _build_backup_drives_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lab = QLabel(tr("The drives this backup is written to (all at the same time). Removing a drive "
                        "here does not delete anything on it."))
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{GRAY}")
        lay.addWidget(lab)
        self.backup_drives = QTreeWidget()
        self.backup_drives.setHeaderLabels([tr("Drive"), tr("Status"), tr("This backup"), tr("Folder")])
        self.backup_drives.setRootIsDecorated(False)
        self.backup_drives.setSelectionMode(QAbstractItemView.ExtendedSelection)
        h = self.backup_drives.header()
        for c in range(4):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        lay.addWidget(self.backup_drives)
        row = QHBoxLayout()
        add = QPushButton(tr("Add drive…"))
        self.backup_drive_menu = QMenu(add)
        self.backup_drive_menu.aboutToShow.connect(self._fill_backup_drive_menu)
        add.setMenu(self.backup_drive_menu)
        sel_all = QPushButton(tr("Select all"))
        sel_all.clicked.connect(self.backup_drives.selectAll)
        rm = QPushButton(tr("Remove from this backup"))
        rm.clicked.connect(self._remove_backup_drives)
        for b in (add, sel_all, rm):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        lay.addStretch()
        return w

    def _build_backup_import_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lab = QLabel(tr("Adds the photos and videos of old drives, old phones or any folders to this backup. "
                        "Every file is checked with SHA-256, files already in the backup are not copied "
                        "twice, and the old folders are only read – never changed."))
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{GRAY}")
        lay.addWidget(lab)
        self.backup_import = ImportSources(into_existing=True)
        self.backup_import.changed.connect(self._backup_import_changed)
        lay.addWidget(self.backup_import)
        row = QHBoxLayout()
        self.backup_import_info = QLabel()
        self.backup_import_info.setWordWrap(True)
        row.addWidget(self.backup_import_info, 1)
        self.start_import_btn = _gui()._big_button(tr("Start"))
        self.start_import_btn.clicked.connect(self._start_import)
        row.addWidget(self.start_import_btn, 0, Qt.AlignBottom)
        lay.addLayout(row)
        lay.addStretch()
        return w

    # ---------------------------------------------------------------- list
    def _refresh_backups(self, mount=False):
        if mount:
            _gui()._log_mount_msgs(mount_for_paths_status(self.cfg.get("destinations", [])))
            lastbackup.discover(self.cfg)
        keep = self._current_backup_key()
        self._backups = backuplist.known(self.cfg, self._backup_sets(), self.backups_show_hidden.isChecked())
        tree = self.backups_tree
        tree.blockSignals(True)
        tree.clear()
        for b in self._backups:
            e = b["entry"] or {}
            when = e.get("when", "").replace("T", " ") or "–"
            sizes = [backup_totals(c) for c in b["copies"]]
            sizes = [s for s in sizes if s]
            size = (describe_totals(max(sizes, key=lambda t: t[0])) if sizes else
                    describe_totals((e["size_files"], e["size_bytes"])) if e.get("size_files") is not None
                    else "–")
            title = lastbackup.title({"owner": b["owner"], "phone": b["phone"]})
            if b["hidden"]:
                title += "  " + tr("(removed from the list)")
            it = QTreeWidgetItem([title, when, size, ", ".join(_short(d) for d in b["drives"]) or "–"])
            it.setData(0, Qt.UserRole, b["key"])
            it.setToolTip(3, "\n".join(b["drives"]))
            tree.addTopLevelItem(it)
            if b["key"] == keep:
                it.setSelected(True)
                tree.setCurrentItem(it)
        if not self._backups:
            it = QTreeWidgetItem([tr("No backup yet – make one with “New backup…” on the start screen."), "", "", ""])
            it.setFlags(Qt.NoItemFlags)
            tree.addTopLevelItem(it)
        elif not tree.selectedItems():
            tree.topLevelItem(0).setSelected(True)
            tree.setCurrentItem(tree.topLevelItem(0))
        tree.blockSignals(False)
        _fit_height(tree, 3, 7)
        self._backup_selected()

    def _current_backup_key(self):
        sel = [it.data(0, Qt.UserRole) for it in self.backups_tree.selectedItems()]
        sel = [k for k in sel if k]
        return sel[0] if len(sel) == 1 else None

    def _current_backup(self):
        key = self._current_backup_key()
        return next((b for b in self._backups if b["key"] == key), None)

    def _backup_selected(self):
        b = self._current_backup()
        n = len([it for it in self.backups_tree.selectedItems() if it.data(0, Qt.UserRole)])
        self.backup_tabs.setEnabled(b is not None)
        self.backup_actions.setEnabled(b is not None)
        if b is None:
            self.backup_detail.setTitle(tr("Selected backup"))
            self.backup_detail_hint.setText(tr("%d backups selected – choose one to change it.", n) if n > 1
                                            else tr("Choose a backup in the list above."))
            self.backup_detail_hint.show()
            return
        self.backup_detail_hint.hide()
        self.backup_detail.setTitle(tr("Selected backup: %s",
                                       lastbackup.title({"owner": b["owner"], "phone": b["phone"]})))
        prof = backuplist.profile(self.cfg, b["key"])
        self.backup_folders.set_folders(prof["folders"])
        self.backup_keep_check.blockSignals(True)
        self.backup_keep_check.setChecked(bool(prof["keep_structure"]))
        self.backup_keep_check.blockSignals(False)
        self.backup_import.load(prof["import_roots"], prof["import_choices"])
        self._fill_backup_drives()
        self._update_backup_hints()

    def _update_backup_hints(self):
        b = self._current_backup()
        if b is None:
            return
        e = dict(b["entry"] or {"phone": b["phone"], "owner": b["owner"]})
        e["destinations"] = b["drives"]
        ok, hint = lastbackup.check(e, self._connected_phone())
        self.backup_phone_hint.setText(f"<span style='color:{GREEN if ok else GRAY}'>{html.escape(hint)}</span>")
        self.backup_update_btn.setEnabled(ok and not self.busy)
        copies = [c for c in (backuplist.copy_on(d, b["phone"], b["owner"]) for d in b["drives"]) if c]
        self.backup_import_info.setText(
            trp("Imports into %d copy of this backup: %s", "Imports into %d copies of this backup: %s",
                len(copies), len(copies), ", ".join(_short(Path(c).parent.parent) for c in copies))
            if copies else
            f"<span style='color:{GRAY}'>" + tr("No backup drive of this backup is connected.") + "</span>")

    def _remove_backups_from_list(self):
        keys = [it.data(0, Qt.UserRole) for it in self.backups_tree.selectedItems() if it.data(0, Qt.UserRole)]
        if not keys:
            QMessageBox.information(self, APP_NAME, tr("Select one or more backups first (or “Select all”)."))
            return
        if QMessageBox.question(
                self, tr("Remove from list"),
                tr("Remove these backups from the list?") + "\n\n" + "\n".join(keys)
                + "\n\n" + tr("Their backups on the drives are NOT deleted.")) != QMessageBox.Yes:
            return
        lastbackup.forget(self.cfg, keys)
        self._refresh_backups()
        self._update_home()

    # ---------------------------------------------------------------- phone tab
    def _backup_folders_changed(self, folders):
        b = self._current_backup()
        if b is None:
            return
        backuplist.save_profile(self.cfg, b["key"], folders=list(folders))
        if self._profile_key() == b["key"]:          # the New backup page shows the same backup
            self._load_profile()

    def _backup_keep_changed(self, on):
        b = self._current_backup()
        if b is not None:
            backuplist.save_profile(self.cfg, b["key"], keep_structure=bool(on))
            if self._profile_key() == b["key"]:
                self._load_profile()

    def _backup_update_now(self, other_folders):
        b = self._current_backup()
        if b is None:
            return
        if not other_folders:
            self._update_latest(b["key"])
            return
        if self.source is None:
            QMessageBox.information(self, APP_NAME, tr("Connect the phone first – its folders are listed then."))
            return
        self._pick_phone_folders([], lambda folders: folders and self._update_latest(b["key"], folders_once=folders),
                                 title=tr("Back up these folders once"))

    def _pick_phone_folders(self, current, done, title=None):
        """The connected phone's folders to tick (or typed ones) → done(list)."""
        src = self.source
        g = _gui()

        def collect():
            if src is None:
                return []
            out = []
            for root in g.PHONE_FOLDER_ROOTS:
                out += src.list_subfolders(root)
            return out

        def show(candidates):
            dlg = g.FolderDialog(self, candidates or [], current, src is not None)
            if title:
                dlg.setWindowTitle(title)
            if dlg.exec() == dlg.Accepted and dlg.folders():
                done(dlg.folders())

        self.run_job(collect, show)

    # ---------------------------------------------------------------- drives tab
    def _fill_backup_drives(self):
        b = self._current_backup()
        t = self.backup_drives
        t.clear()
        if b is None:
            return
        for d in b["drives"]:
            avail = os.path.isdir(d)
            copy = backuplist.copy_on(d, b["phone"], b["owner"]) if avail else None
            have = (describe_totals(backup_totals(copy) or (0, 0)) if copy else
                    tr("not on this drive yet") if avail else "–")
            it = QTreeWidgetItem([_short(d), tr("connected") if avail else tr("not connected"), have, d])
            it.setForeground(1, QColor(GREEN if avail else GRAY))
            it.setData(0, Qt.UserRole, d)
            it.setToolTip(0, d)
            t.addTopLevelItem(it)
        if not b["drives"]:
            it = QTreeWidgetItem([tr("No backup drive – click “Add drive…”"), "", "", ""])
            it.setFlags(Qt.NoItemFlags)
            t.addTopLevelItem(it)
        _fit_height(t, 2, 6)

    def _set_backup_drives(self, drives):
        b = self._current_backup()
        if b is None:
            return
        backuplist.save_profile(self.cfg, b["key"], destinations=list(drives))
        b["drives"] = list(drives)
        self._fill_backup_drives()
        self._update_backup_hints()
        self._refresh_backups()

    def _fill_backup_drive_menu(self):
        m = self.backup_drive_menu
        m.clear()
        b = self._current_backup()
        if b is None:
            return
        known = [d for d in self.cfg.get("destinations", []) if d not in b["drives"] and not d.startswith("gdrive:")]
        if known:
            m.addSection(tr("Backup folders used before"))
            for d in known:
                a = m.addAction(d + ("" if os.path.isdir(d) else "  " + tr("(not connected)")))
                a.triggered.connect(lambda _c=False, d=d: self._set_backup_drives(b["drives"] + [d]))
            m.addSeparator()
        m.addAction(tr("Other folder…"), self._add_backup_drive_folder)

    def _add_backup_drive_folder(self):
        b = self._current_backup()
        if b is None:
            return
        drives = detect_drives()
        start = drives[0][0] if drives else str(Path.home())
        p = QFileDialog.getExistingDirectory(self, tr("Choose the backup folder on the drive"), start)
        if not p:
            return
        p = str(Path(p).resolve())
        if p not in b["drives"]:
            self._set_backup_drives(b["drives"] + [p])

    def _remove_backup_drives(self):
        b = self._current_backup()
        drives = {it.data(0, Qt.UserRole) for it in self.backup_drives.selectedItems()} - {None}
        if b is None or not drives:
            QMessageBox.information(self, APP_NAME, tr("Select one or more drives in the list first "
                                                       "(Ctrl- or Shift-click, or “Select all”)."))
            return
        if QMessageBox.question(
                self, tr("Remove from this backup"),
                tr("This backup is no longer written to:") + "\n\n" + "\n".join(sorted(drives)) + "\n\n"
                + tr("Nothing on the drives is deleted.")) != QMessageBox.Yes:
            return
        self._set_backup_drives([d for d in b["drives"] if d not in drives])

    # ---------------------------------------------------------------- import tab
    def _backup_import_changed(self):
        b = self._current_backup()
        if b is not None:
            src = self.backup_import
            backuplist.save_profile(self.cfg, b["key"], import_roots=list(src.roots),
                                    import_choices={r: dict(src.choices.get(r, {})) for r in src.roots})

    def _start_import(self):
        g = _gui()
        b = self._current_backup()
        if b is None:
            QMessageBox.information(self, APP_NAME, tr("Choose a backup in the list above."))
            return
        why = self.backup_import.check_ready()
        if why:
            QMessageBox.warning(self, tr("Cannot start yet"), why)
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            g._log_mount_msgs(mount_for_paths_status(b["drives"]))
            for d in b["drives"]:
                if os.path.isdir(d):
                    setfolders.relocate(d, self.cfg)
        finally:
            QApplication.restoreOverrideCursor()
        parents = [c for c in (backuplist.copy_on(d, b["phone"], b["owner"]) for d in b["drives"]) if c]
        if not parents:
            QMessageBox.warning(self, tr("Cannot start yet"),
                                tr("No backup drive of this backup is connected. Connect one (tab “Backup "
                                   "drives”) and try again."))
            return
        sel = self.backup_import.selections()
        try:
            check_selection(sel, parents)
        except ValueError as e:
            QMessageBox.warning(self, tr("Cannot start yet"), str(e))
            return
        if not g.ask_layout(self, self.cfg, parents):
            return
        self.last_folder = parents[0]
        other = self.backup_import.other_files()
        ui.title(tr("Import into %s", lastbackup.title({"owner": b["owner"], "phone": b["phone"]})))
        self.run_job(lambda: g.perform_selection_import(sel, parents, self.cfg, other_files=other,
                                                        interactive=True, cancel=self.cancel_event),
                     self._import_done, awake=N_("Import"))

    def _import_done(self, res):
        status, paths, _results, verdict = res
        self._finished(status, paths, verdict, N_("Import"))
        self._refresh_backups()
        self._fill_export_sources()

    # ---------------------------------------------------------------- page 2: old phone / drive
    def _build_old_import_page(self):
        g = _gui()
        w = QWidget()
        lay = QVBoxLayout(w)
        head = QHBoxLayout()
        back = QPushButton(tr("← Back to your backups"))
        back.clicked.connect(lambda: self._show_old_import(False))
        title = QLabel(tr("New backup of an old phone or old drive"))
        title.setStyleSheet("font-size:15px;font-weight:600")
        head.addWidget(back)
        head.addSpacing(10)
        head.addWidget(title, 1)
        lay.addLayout(head)
        info = QLabel(tr(
            "Backs up an old phone or an old hard drive like a phone (its own backup “Owner/Name” on the "
            "drive). Add the folder(s) – e.g. the copy of the old phone or the photo folders on the old "
            "drive – and choose how they are sorted. Every file is checked with SHA-256, identical files "
            "are stored only once, and the old folders are only read – never changed."))
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{GRAY}")
        lay.addWidget(info)
        self.old_import = ImportSources(into_existing=False)
        self.old_import.changed.connect(self._update_import_preview)
        lay.addWidget(g._group(tr("Folders to import (one or more, e.g. the old phone and its SD card)"),
                               self.old_import))
        form = QFormLayout()
        self.import_phone_edit = QLineEdit()
        self.import_phone_edit.setPlaceholderText(tr("e.g. Galaxy S7"))
        self.import_owner_edit = QLineEdit(self.cfg.get("owner", ""))
        self.import_owner_edit.setPlaceholderText(tr("e.g. Sam"))
        form.addRow(tr("Name (old phone or drive):"), self.import_phone_edit)
        form.addRow(tr("Owner:"), self.import_owner_edit)
        box = QVBoxLayout()
        box.addLayout(form)
        self.import_dest_list = g.LocationList(
            self.cfg, "destinations", "import_selected_destinations", True, "PhoneBackups",
            tr("Tick the drive(s) to write the new backup to – all ticked drives at the same time."),
            plans_column=True)
        self.import_dest_list.changed.connect(self._update_import_preview)
        box.addWidget(self.import_dest_list)
        self.import_preview = QLabel()
        self.import_preview.setWordWrap(True)
        self.import_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(self.import_preview)
        self.import_phone_edit.textChanged.connect(self._update_import_preview)
        self.import_owner_edit.textChanged.connect(self._update_import_preview)
        lay.addWidget(g._group(tr("New backup"), box))
        row = QHBoxLayout()
        row.addStretch()
        self.start_old_import_btn = g._big_button(tr("Start"))
        self.start_old_import_btn.clicked.connect(self._start_old_import)
        row.addWidget(self.start_old_import_btn)
        lay.addLayout(row)
        lay.addStretch()
        self._update_import_preview()
        return w

    def _show_old_import(self, on):
        if on:
            self.import_dest_list.rebuild()
            self._update_import_preview()
        else:
            self._refresh_backups()
        self.backups_stack.setCurrentIndex(1 if on else 0)
        self.backup_actions.setVisible(not on)

    def _update_import_preview(self):
        if not hasattr(self, "import_preview"):
            return
        phone = self.import_phone_edit.text().strip() or tr("<old phone>")
        owner = self.import_owner_edit.text().strip() or tr("<owner>")
        dests = self.import_dest_list.selected_paths()
        base = Path(dests[0]) if dests else Path(tr("<drive>"))
        parent = base / setfolders.rel(phone, owner)
        self.import_preview.setText(
            tr("Sorted folders → %s   (RAW → YEAR/raw/)", parent / tr("YEAR") / tr("YY.MM"))
            + "\n" + tr("Kept folders → %s", parent / tr("<original folder>")))

    def _start_old_import(self):
        g = _gui()
        why = self.old_import.check_ready()
        if why:
            QMessageBox.warning(self, tr("Cannot start yet"), why)
            return
        sel = self.old_import.selections()
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
        name = setfolders.rel(phone, owner)          # 'Sam/Galaxy S7'
        for d in dests:
            setfolders.relocate(d, self.cfg)
        try:
            check_selection(sel, [Path(d) / name for d in dests])
        except ValueError as e:
            QMessageBox.warning(self, tr("Cannot start yet"), str(e))
            return
        existing = [d for d in dests if (Path(d) / name).is_dir()]
        if existing and QMessageBox.question(
                self, tr("Backup already exists"),
                tr("There is already a backup “%s” on", name) + "\n" + "\n".join(existing) + "\n\n" +
                tr("Add the files to it? (Files already in it are not copied twice.)")) != QMessageBox.Yes:
            return
        if not g.ask_layout(self, self.cfg, [Path(d) / name for d in dests]):
            return
        self.last_folder = str(Path(dests[0]) / name)
        other = self.old_import.other_files()
        ui.title(tr("Import old phone %s – %s", phone, owner))
        self.run_job(lambda: g.perform_old_phone_import(sel, phone, owner, dests, self.cfg,
                                                        other_files=other, interactive=True,
                                                        cancel=self.cancel_event),
                     self._import_done, awake=N_("Import"))


# =========================================================================== phone app (settings)

class PhoneAppMixin:
    """Program settings → "Versions and phone app" (user request 2026-11-10): versions, what the
    phone app does, and installing it by USB cable, QR code or – as a last resort – Bluetooth."""

    def _build_phone_app_box(self):
        from . import __version__
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.versions_label = QLabel()
        self.versions_label.setWordWrap(True)
        self.versions_label.setTextFormat(Qt.RichText)
        self.versions_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.versions_label)
        info = QLabel(
            "<b>" + tr("What the phone app does") + "</b><br>"
            + tr("“My Media Backup” is a small app for the phone. It may only <b>read</b> photos and videos – "
                 "it cannot delete or change anything, reads no other files, contacts or messages, has no "
                 "ads and talks to no server on the internet. It only answers the computer it is paired "
                 "with (encrypted).") + "<br><br><b>" + tr("What you gain") + "</b><ul>"
            + "<li>" + tr("Backups over Wi-Fi – no cable, no USB debugging, no Developer options.") + "</li>"
            + "<li>" + tr("Fast cable backups: one tap “Allow backup over cable” switches USB debugging on "
                          "just for the backup – and off again afterwards.") + "</li>"
            + "<li>" + tr("“Connect phone…”: scan a QR code instead of searching settings.") + "</li>"
            + "<li>" + tr("The phone is recognised by its own key – a backup never lands in the wrong "
                          "phone's folder.") + "</li></ul><b>"
            + tr("Without the phone app") + "</b><ul>"
            + "<li>" + tr("USB cable with USB debugging switched on by hand (Developer options): fast, "
                          "every file checked on the phone.") + "</li>"
            + "<li>" + tr("Wi-Fi with Android's Wireless debugging (Android 11+, pair once).") + "</li>"
            + "<li>" + tr("USB cable with “File transfer” (MTP): works on every phone, but slower and "
                          "without a check on the phone.") + "</li></ul>")
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        lay.addWidget(info)
        row = QHBoxLayout()
        cable = QPushButton(tr("Install / update over USB cable…"))
        cable.setToolTip(tr("Phone on the USB cable: with “File transfer” the app file is copied onto the "
                            "phone (you install it there); with USB debugging it is installed directly. "
                            "You are asked first."))
        cable.clicked.connect(self._install_app_cable)
        qr = QPushButton(tr("Install with QR code…"))
        qr.setToolTip(tr("Phone and computer in the same Wi-Fi: scan the code, download the app on the "
                         "phone and install it."))
        qr.clicked.connect(self._setup_phone_app)
        bt = QPushButton(tr("Send over Bluetooth…"))
        bt.setToolTip(tr("If nothing else works: sends the app file to a phone paired with this computer "
                         "over Bluetooth. Install it on the phone by tapping the received file."))
        bt.clicked.connect(self._install_app_bluetooth)
        for b in (cable, qr, bt):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.auto_update_row = QHBoxLayout()
        self.auto_update_label = QLabel()
        self.auto_update_label.setWordWrap(True)
        ask_again = QPushButton(tr("Ask again before updating the phone app"))
        ask_again.clicked.connect(self._ask_again_before_update)
        self.auto_update_btn = ask_again
        self.auto_update_row.addWidget(self.auto_update_label, 1)
        self.auto_update_row.addWidget(ask_again)
        lay.addLayout(self.auto_update_row)
        self._update_versions()
        return w

    def _ask_again_before_update(self):
        self.cfg["companion_auto"] = []
        from . import config
        config.save(self.cfg)
        ui.ok(tr("The program asks again before it installs or updates the phone app."))
        self._update_versions()

    def _update_versions(self):
        from . import __version__
        from .companion import APP_VERSION_NAME, CompanionSource
        lines = [tr("This program: version %s", f"<b>{html.escape(__version__)}</b>"),
                 tr("Phone app included in this program: version %s", f"<b>{APP_VERSION_NAME}</b>")]
        # only the phone connected right now – never phones used before (user request 2026-11-10)
        src = self.source
        now = ""
        if isinstance(src, CompanionSource):
            now = src.app_version
        elif src is not None:
            now = getattr(src, "companion_version", "")
        if now:
            name = f"{getattr(src, 'manufacturer', '')} {src.device_name or ''}".strip() or tr("the connected phone")
            lines.append(tr("Phone app on %s: %s", html.escape(name), f"<b>{html.escape(now)}</b>")
                         + (f" <span style='color:#c76a00'>– {tr('an update is available')}</span>"
                            if _older(now, APP_VERSION_NAME) else ""))
        self.versions_label.setText("<br>".join(lines))
        auto = self.cfg.get("companion_auto", [])
        self.auto_update_label.setText(
            trp("The phone app is updated automatically (without asking) on %d phone.",
                "The phone app is updated automatically (without asking) on %d phones.", len(auto), len(auto))
            if auto else "")
        self.auto_update_label.setVisible(bool(auto))
        self.auto_update_btn.setVisible(bool(auto))

    def _remember_app_version(self, entry, version):
        if not entry or not version or entry.get("app_version") == version:
            return
        for p in companion.phones(self.cfg):
            if p.get("phone_id") == entry.get("phone_id"):
                p["app_version"] = version
                companion.save_phone(self.cfg, p)
                break
        if hasattr(self, "versions_label"):
            self._update_versions()

    # ---- install over the USB cable (always asked first - user rule 2026-11-05)
    def _install_app_cable(self):
        g = _gui()
        src = self.source
        if src is not None and hasattr(src, "put_file") and not isinstance(src, g.AdbSource):
            self._copy_app_by_file_transfer(src)
            return
        if not (isinstance(src, g.AdbSource) and not src.wireless):
            box = QMessageBox(QMessageBox.Information, tr("Install over USB cable"), tr(
                "Connect the phone with the USB cable, unlock it and choose “File transfer” on the phone – "
                "the program connects by itself. Then click this button again: the app file is copied "
                "onto the phone and you install it there."), parent=self)
            guide = box.addButton(tr("How to switch on USB debugging…"), QMessageBox.ActionRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() is guide:
                self._show_usb_guide()
            return
        apk = g.apk_path()
        if apk is None:
            QMessageBox.warning(self, APP_NAME, tr("The phone app is not included in this program."))
            return

        def job():
            state = src.companion_state()
            installed = getattr(src, "companion_version", "")
            phone = f"{src.manufacturer} {src.device_name}".strip() or tr("the phone")
            ask = "reinstall" if state == "ready" else state
            title, text, details = g.install_question(ask, phone, src.serial, installed, os.path.getsize(apk))
            if not ui.ask_install(title, text, details):
                ui.info(tr("Nothing installed on %s.", phone))
                return False
            ui.info(tr("Installing the phone app “%s” %s on %s (serial %s) over the USB cable …",
                       g.COMPANION_NAME, g.COMPANION_VERSION, phone, src.serial))
            ok, msg = src.install_companion(apk)
            if not ok:
                ui.warn(tr("The phone app could not be set up: %s – Samsung: switch off “Auto "
                           "Blocker”. Xiaomi: switch on “Install via USB” in the Developer options.", msg))
                return False
            src.companion_version = g.COMPANION_VERSION
            ui.ok(tr("Phone app “%s” %s installed on %s.", g.COMPANION_NAME, g.COMPANION_VERSION, phone))
            return True

        def done(ok):
            if ok and self.source is src:
                self._companion_asked.discard(src.serial)       # check / pair it like a new phone
                self._cable_setup(src)
            self._update_versions()

        self.run_job(job, done)

    def _copy_app_by_file_transfer(self, src, asked=False):
        """Phone on the cable in "File transfer" mode: copy the app file into its Download folder –
        no network, no browser, no USB debugging needed. Asked first (user rule 2026-11-05)."""
        g = _gui()
        apk = g.apk_path()
        if apk is None:
            QMessageBox.warning(self, APP_NAME, tr("The phone app is not included in this program."))
            return
        name = f"My-Media-Backup-{g.COMPANION_VERSION}.apk"
        steps = tr("On the phone: open “Files” → “Downloads”, tap “%s” and then “Install” (Android asks once "
                   "to allow installs from “Files”).", name)
        if asked:
            return self._run_app_copy(src, apk, name, steps)
        box = QMessageBox(QMessageBox.Question, tr("Copy the phone app onto the phone?"), tr(
            "This copies the file %s (%s, version %s) into the folder “Download” of %s over the USB "
            "cable. Nothing is installed by itself – you install it on the phone:",
            name, f"{os.path.getsize(apk) / 1e6:.1f} MB", g.COMPANION_VERSION,
            src.device_name or tr("the phone")) + "\n\n" + steps, parent=self)
        yes = box.addButton(tr("Copy onto the phone"), QMessageBox.AcceptRole)
        box.addButton(tr("Not now"), QMessageBox.RejectRole)
        box.setDefaultButton(box.buttons()[-1])
        box.exec()
        if box.clickedButton() is not yes:
            return
        self._run_app_copy(src, apk, name, steps)

    def _run_app_copy(self, src, apk, name, steps):
        def job():
            try:
                return src.put_file(apk, "Download", name), None
            except Exception as e:  # noqa: BLE001
                return None, str(e)

        def done(res):
            where, err = res
            if err:
                QMessageBox.warning(self, APP_NAME, tr("The file could not be copied onto the phone: %s", err))
                return
            ui.ok(tr("Phone app copied onto the phone: %s", where))
            QMessageBox.information(self, tr("Phone app copied"), tr("Done.") + "\n\n" + steps + "\n\n" + tr(
                "Then open the app, allow access to photos and videos, and connect it with this computer: "
                "“Connect phone…” on the start screen."))

        self.run_job(job, done)

    # ---- last resort: Bluetooth file transfer
    def _install_app_bluetooth(self):
        from . import btsend
        g = _gui()
        apk = g.apk_path()
        if apk is None:
            QMessageBox.warning(self, APP_NAME, tr("The phone app is not included in this program."))
            return
        ok, why = btsend.supported()
        if not ok:
            QMessageBox.warning(self, tr("Send over Bluetooth"), why)
            return
        steps = tr("On the phone: accept the file, open it (notification or Files → Downloads) and tap "
                   "“Install” (Android asks once to allow installs from that app). Then pair the app with "
                   "this computer: “Install with QR code…” or the USB cable.")
        if sys.platform.startswith("win"):
            QMessageBox.information(self, tr("Send over Bluetooth"), tr(
                "Windows opens “Send files via Bluetooth” and shows the app file %s – choose the phone, "
                "then that file.", Path(apk).name) + "\n\n" + steps)
            btsend.windows_wizard(apk)
            return
        try:
            devices = btsend.paired_devices()
        except btsend.BtSendError as e:
            QMessageBox.warning(self, tr("Send over Bluetooth"), str(e))
            return
        if not devices:
            QMessageBox.information(self, tr("Send over Bluetooth"), tr(
                "No phone is paired with this computer over Bluetooth yet. Pair it first in the "
                "computer's Bluetooth settings (switch on Bluetooth on the phone, choose it on the "
                "computer, confirm the code on both), then click this button again."))
            return
        names = [f"{n}  ({a})" for a, n in devices]
        from PySide6.QtWidgets import QInputDialog
        choice, ok = QInputDialog.getItem(self, tr("Send over Bluetooth"),
                                          tr("Send the phone app (%s, version %s) to:",
                                             f"{os.path.getsize(apk) / 1e6:.1f} MB", g.COMPANION_VERSION),
                                          names, 0, False)
        if not ok:
            return
        address = devices[names.index(choice)][0]
        if QMessageBox.question(self, tr("Send over Bluetooth"), tr(
                "Send the app file to %s now?", choice) + "\n\n" + steps) != QMessageBox.Yes:
            return
        ui.info(tr("Sending the phone app over Bluetooth to %s – accept the file on the phone …", choice))

        def job():
            try:
                btsend.send_apk(address, apk, g.COMPANION_VERSION, progress=None, cancel=self.cancel_event)
                return None
            except btsend.BtSendError as e:
                return str(e)

        def done(err):
            if err:
                QMessageBox.warning(self, tr("Send over Bluetooth"), err)
            else:
                ui.ok(tr("Phone app sent. Now install it on the phone by tapping the received file."))
                QMessageBox.information(self, tr("Send over Bluetooth"), tr("Sent.") + "\n\n" + steps)

        self.run_job(job, done)


def _older(a, b):
    """Version a older than b ('0.6.0' < '0.7.0')."""
    def parts(v):
        return [int(x) if x.isdigit() else 0 for x in str(v).split(".")]
    return parts(a) < parts(b)
