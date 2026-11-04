"""Backup settings widgets (user request 2026-11-04): the phone-connection chooser with the speed
overview, and the beginner's guide for switching on USB debugging."""

import html

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
                               QRadioButton, QVBoxLayout, QWidget)

from . import adbsetup

GRAY = "#808080"


class ConnectionChooser(QWidget):
    """Radio buttons for the connection modes, each with its speed and a bar to compare."""
    changed = Signal(str)

    def __init__(self, current):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        self.group = QButtonGroup(self)
        top = max(c.mb_s[1] for c in adbsetup.CONNECTIONS)
        for row, c in enumerate(adbsetup.CONNECTIONS):
            label = (c.short or c.title) + ("  (recommended)" if c.key == adbsetup.DEFAULT_CONNECTION else "")
            rb = QRadioButton(label)
            rb.setToolTip(f"{c.title}\n{c.speed}\n\n{c.note}")
            rb.setProperty("key", c.key)
            self.group.addButton(rb, row)
            bar = QProgressBar()
            bar.setRange(0, top)
            bar.setValue(c.mb_s[1])
            bar.setTextVisible(False)
            bar.setFixedSize(60, 8)
            bar.setToolTip(c.speed)
            speed = QLabel(c.speed_short)
            speed.setToolTip(c.speed)
            speed.setStyleSheet(f"color:{GRAY}")
            grid.addWidget(rb, row, 0)
            grid.addWidget(bar, row, 1, Qt.AlignVCenter)
            grid.addWidget(speed, row, 2)
            if c.key == current:
                rb.setChecked(True)
        if self.group.checkedButton() is None:
            self.group.button(0).setChecked(True)
        grid.setColumnStretch(2, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{GRAY}")
        grid.addWidget(self.note, len(adbsetup.CONNECTIONS), 0, 1, 3)
        self.group.idToggled.connect(self._toggled)
        self._show_note()

    def key(self):
        return self.group.checkedButton().property("key")

    def _show_note(self):
        self.note.setText(adbsetup.CONNECTIONS_BY_KEY[self.key()].note)

    def _toggled(self, _id, on):
        if on:
            self._show_note()
            self.changed.emit(self.key())


class UsbDebugGuide(QDialog):
    """Step by step: Developer options → USB debugging, for the connected / named phone."""

    def __init__(self, parent, model="", with_app=True):
        super().__init__(parent)
        self.with_app = with_app
        self.setWindowTitle("Switch on USB debugging – first time")
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        intro = QLabel("Android allows USB debugging only when you switch it on yourself on the "
                       "phone – once. This takes about a minute.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        row = QHBoxLayout()
        row.addWidget(QLabel("Phone:"))
        self.model_edit = QLineEdit(model)
        self.model_edit.setPlaceholderText("e.g. Pixel 10 Pro, Galaxy S25 – or plug the phone in "
                                           "and click “Detect”")
        detect = QPushButton("Detect")
        detect.setToolTip("Reads the model of the phone on the USB cable (works without USB debugging).")
        detect.clicked.connect(self._detect)
        row.addWidget(self.model_edit, 1)
        row.addWidget(detect)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Brand:"))
        self.brand = QComboBox()
        for key, g in adbsetup.GUIDES.items():
            self.brand.addItem(g.brand, key)
        row2.addWidget(self.brand, 1)
        lay.addLayout(row2)

        self.steps = QLabel()
        self.steps.setWordWrap(True)
        self.steps.setTextFormat(Qt.RichText)
        self.steps.setAlignment(Qt.AlignTop)
        self.steps.setStyleSheet("QLabel{padding:8px}")
        lay.addWidget(self.steps, 1)

        search = QPushButton("Search the web for this phone")
        search.setToolTip("Opens your browser with a search for how to switch on USB debugging on "
                          "this model.")
        search.clicked.connect(self._search)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.addButton(search, QDialogButtonBox.ActionRole)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.model_edit.textChanged.connect(self._model_changed)
        self.brand.currentIndexChanged.connect(self._show)
        self._model_changed(model)
        if not model:
            self._detect()

    def _detect(self):
        found = adbsetup.detect_usb_phone()
        if found:
            self.model_edit.setText(found)

    def _model_changed(self, text):
        key = adbsetup.brand_key(text) if text.strip() else "other"
        self.brand.setCurrentIndex(max(0, self.brand.findData(key)))
        self._show()

    def _show(self):
        g = adbsetup.GUIDES[self.brand.currentData()]
        items = "".join(f"<li style='margin-bottom:6px'>{html.escape(s)}</li>"
                        for s in adbsetup.guide_steps(g, self.with_app))
        self.steps.setText(f"<b>{html.escape(g.brand)}</b><ol>{items}</ol>")

    def _search(self):
        QDesktopServices.openUrl(QUrl(adbsetup.search_url(self.model_edit.text().strip())))
