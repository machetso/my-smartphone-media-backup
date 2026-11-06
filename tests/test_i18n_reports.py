"""Reports and the log in another language: shown texts translated, names and statuses English."""

import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phonebackup import i18n  # noqa: E402
from phonebackup.backup import perform_backup  # noqa: E402
from phonebackup.report import shown  # noqa: E402
from phonebackup.sources import FolderSource  # noqa: E402
from tests.test_all import jpeg_with_exif  # noqa: E402

FAKE_DE = {
    "Status": "Zustand",
    "File": "Datei",
    "General": "Allgemein",
    "COMPLETED": "ABGESCHLOSSEN",
    "OK - copied and verified": "OK - kopiert und geprüft",
    "Destination %d": "Ziel %d",
    "%s status": "%s Zustand",
    "EVERYTHING COPIED CORRECTLY - %d new files (%s) secured and verified with SHA-256 on %d destination(s).":
        {"one": "ALLES RICHTIG KOPIERT - %d neue Datei (%s) auf %d Ziel(en) gesichert.",
         "other": "ALLES RICHTIG KOPIERT - %d neue Dateien (%s) auf %d Ziel(en) gesichert."},
}


class GermanReport(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pbi18n_"))
        self.old = i18n.current()
        i18n.use("en")
        self.lang = i18n.Language("de", "Deutsch", "de-DE", False, dict(FAKE_DE))
        i18n._current = self.lang

    def tearDown(self):
        i18n._current = self.old
        i18n.use("en")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_report_translated_names_english(self):
        phone, hdd = self.tmp / "phone", self.tmp / "hdd"
        hdd.mkdir()
        p = phone / "DCIM/Camera/IMG_A.jpg"
        p.parent.mkdir(parents=True)
        p.write_bytes(jpeg_with_exif("2025:01:15 10:00:00"))
        src = FolderSource(phone, device_name="Pixel")
        status, paths, results, verdict = perform_backup(src, "Pixel", "Sam", ["DCIM/Camera"], [hdd],
                                                         {"fsync": False}, interactive=False)
        # the program still sees English
        self.assertEqual(status, "COMPLETED")
        self.assertTrue(verdict.startswith("EVERYTHING"), verdict)
        st, loc = results[0].per_dest["Destination 1"]
        self.assertTrue(st.startswith("OK"), st)
        # shown in the chosen language
        self.assertTrue(shown(verdict).startswith("ALLES RICHTIG KOPIERT - 1 neue Datei"), shown(verdict))
        # folder and report file names stay English
        self.assertEqual(loc, "2025/01.January-photos/IMG_A.jpg")
        set_dir = hdd / "Pixel - Sam"
        self.assertTrue((set_dir / loc).is_file())
        names = {q.name for q in paths}
        self.assertIn(f"Backup Pixel Sam {datetime.now():%Y-%m-%d}.txt", names)
        txt = next(q for q in paths if q.suffix == ".txt").read_text(encoding="utf-8")
        self.assertIn("Allgemein", txt)
        self.assertIn("ABGESCHLOSSEN", txt)
        self.assertIn("OK - kopiert und geprüft", txt)
        self.assertNotIn("OK - copied and verified", txt)
        csv_text = next(q for q in paths if q.suffix == ".csv").read_text(encoding="utf-8-sig")
        header = csv_text.splitlines()[0].split(";")
        self.assertIn("Datei", header)
        self.assertIn("Ziel 1 Zustand", header)
        self.assertIn("OK - kopiert und geprüft", csv_text)
        html = next(q for q in paths if q.suffix == ".html").read_text(encoding="utf-8")
        self.assertIn("lang='de-DE'", html)


if __name__ == "__main__":
    unittest.main()
