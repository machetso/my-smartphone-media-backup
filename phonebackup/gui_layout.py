"""Before the first conversion to the new month folders (user request 2026-11-09): the user chooses
which old month folders keep their name and structure (see migrate.py)."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from . import config, migrate
from .i18n import tr


class LayoutDialog(QDialog):
    """Old month folders grouped by year; ticked = change to the new name, unticked = keep."""

    def __init__(self, parent, set_name, folders):
        super().__init__(parent)
        self.setWindowTitle(tr("New month folders for %s", set_name))
        self.resize(560, 520)
        lay = QVBoxLayout(self)
        lab = QLabel(tr("The month folders get new names: <b>2026/02.February-photos</b> and "
                        "<b>02.February-videos</b> become <b>2026/26.02</b> (photos and videos "
                        "together), RAW photos <b>2026/raw/26.02</b>.<br><br>"
                        "<b>Untick the folders that should keep their old name and structure.</b> "
                        "They are never changed – on every drive and on Google Drive. New photos "
                        "of those months go into the new folders.<br><br>"
                        "The files are only moved on the same drive – nothing is copied or deleted."))
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.RichText)
        lay.addWidget(lab)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Folder"), tr("Files")])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)   # Ctrl/Shift-click
        self.items = {}
        years = {}
        for rel in sorted(folders):
            year = rel.split("/")[0]
            if year not in years:
                y = QTreeWidgetItem([year, ""])
                y.setFlags(y.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                y.setCheckState(0, Qt.Checked)
                self.tree.addTopLevelItem(y)
                years[year] = y
            it = QTreeWidgetItem([rel.split("/", 1)[1], str(folders[rel])])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked)
            it.setData(0, Qt.UserRole, rel)
            it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            years[year].addChild(it)
            self.items[rel] = it
        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)
        self.tree.itemChanged.connect(self._changed)
        lay.addWidget(self.tree)

        row = QHBoxLayout()
        for text, on in ((tr("Select all"), True), (tr("Select none"), False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, on=on: self._tick_all(on))
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        hint = QLabel(tr("Several at once: select them (Ctrl- or Shift-click), then tick or untick "
                         "one of them."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#808080")
        lay.addWidget(hint)

        bb = QDialogButtonBox()
        bb.addButton(tr("Change ticked folders"), QDialogButtonBox.AcceptRole)
        bb.addButton(tr("Not now"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._busy = False

    def _changed(self, item, column):
        """Ticking one of several selected rows ticks all of them."""
        if self._busy or column != 0 or not item.isSelected():
            return
        self._busy = True
        try:
            state = item.checkState(0)
            if state != Qt.PartiallyChecked:
                for other in self.tree.selectedItems():
                    if other is not item:
                        other.setCheckState(0, state)
        finally:
            self._busy = False

    def _tick_all(self, on):
        state = Qt.Checked if on else Qt.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, state)

    def kept(self):
        return [rel for rel, it in self.items.items() if it.checkState(0) != Qt.Checked]


def ask_layout(parent, cfg, set_dirs):
    """Ask once per backup ('Phone - Owner') that still has old month folders and no choice yet.
    Returns False when the user chose "Not now" (the job is not started)."""
    found = {}
    for sd in set_dirs:
        if not sd:
            continue
        sd = Path(sd)
        for rel, n in migrate.to_choose(cfg, sd).items():
            have = found.setdefault(migrate.key_of(sd), {})
            have[rel] = max(have.get(rel, 0), n)
    for name, folders in found.items():
        dlg = LayoutDialog(parent, name, folders)
        if dlg.exec() != QDialog.Accepted:
            return False
        migrate.set_decision(cfg, name, dlg.kept())
        config.save(cfg)
    return True

