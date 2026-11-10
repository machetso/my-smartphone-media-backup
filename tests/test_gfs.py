"""Grandfather-Father-Son: which export type is due, restore chains, safe cleanup (end to end)."""

import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from phonebackup import gfs
from phonebackup.export import (EXPORT_DIR, Catalog, perform_export, perform_restore, remove_runs,
                                restore_chain)


class R:
    def __init__(self, id, type, started, status="COMPLETED", folder=None):
        self.id, self.type, self.started, self.status = id, type, started, status
        self.folder = folder or f"run{id}"
        self.finished = started


def d(s):
    return datetime.fromisoformat(s)


class ChooseTest(unittest.TestCase):
    def test_first_is_full(self):
        self.assertEqual(gfs.choose([], d("2026-11-05 10:00"))[0], "full")

    def test_rhythm(self):
        runs = [R(1, "full", "2026-01-10 10:00:00")]
        self.assertEqual(gfs.choose(runs, d("2026-01-20 10:00"))[0], "incremental")
        self.assertEqual(gfs.choose(runs, d("2026-02-10 10:00"))[0], "differential")
        runs.append(R(2, "differential", "2026-02-11 10:00:00"))
        self.assertEqual(gfs.choose(runs, d("2026-02-20 10:00"))[0], "incremental")
        self.assertEqual(gfs.choose(runs, d("2026-03-11 10:00"))[0], "differential")
        self.assertEqual(gfs.choose(runs, d("2026-04-10 10:00"))[0], "full")      # 3 months

    def test_cancelled_full_does_not_count(self):
        runs = [R(1, "full", "2026-01-10 10:00:00"), R(2, "full", "2026-04-11 10:00:00", "CANCELLED by user")]
        self.assertEqual(gfs.choose(runs, d("2026-04-12 10:00"))[0], "full")

    def test_month_end(self):
        self.assertEqual(gfs.add_months(d("2026-01-31 08:00"), 1), d("2026-02-28 08:00"))


class ChainAndRetireTest(unittest.TestCase):
    def setUp(self):
        self.runs = [R(1, "full", "2026-01-01 10:00:00"), R(2, "incremental", "2026-01-05 10:00:00"),
                     R(3, "differential", "2026-02-01 10:00:00"), R(4, "incremental", "2026-02-03 10:00:00"),
                     R(5, "incremental", "2026-02-05 10:00:00")]

    def test_chain_skips_incrementals_before_differential(self):
        self.assertEqual([r.id for r in gfs.chain(self.runs, 5)], [1, 3, 4, 5])
        self.assertEqual([r.id for r in gfs.chain(self.runs, 3)], [1, 3])
        self.assertEqual([r.id for r in gfs.chain(self.runs, 2)], [1, 2])

    def test_never_retires_what_a_kept_export_needs(self):
        keep = {"full": 1, "differential": 1, "incremental": 1}
        retire = {r.id for r in gfs.to_retire(self.runs, keep)}
        self.assertEqual(retire, {2})          # 4 is needed by 5, 1+3 by everything

    def test_old_full_cycle_retired(self):
        runs = self.runs + [R(6, "full", "2026-04-02 10:00:00"), R(7, "incremental", "2026-04-03 10:00:00")]
        retire = {r.id for r in gfs.to_retire(runs, {"full": 1, "differential": 3, "incremental": 2})}
        # full 1 is still needed by differential 3 (kept: newest 3 differentials)
        self.assertNotIn(1, retire)
        self.assertNotIn(3, retire)
        retire = {r.id for r in gfs.to_retire(runs, {"full": 1, "differential": 0, "incremental": 1})}
        self.assertEqual(retire, {1, 2, 3, 4, 5})


class EndToEndTest(unittest.TestCase):
    """Real exports with the dates moved back, cleanup, then every remaining export restores."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.src = base / "backup" / "Sam" / "Pixel"
        self.target = base / "second"
        self.target.mkdir()
        self.n = 0
        self.cfg = {"fsync": False}

    def tearDown(self):
        self.tmp.cleanup()

    def add_file(self):
        self.n += 1
        p = self.src / "2026" / "26.01" / f"IMG_{self.n}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"photo {self.n}".encode() * 10)

    def export(self, when):
        status, _, _ = perform_export(self.src, self.target, "auto", self.cfg, now=d(when))
        self.assertEqual(status, "COMPLETED")
        db = sqlite3.connect(str(self.target / "Sam" / self.src.name / EXPORT_DIR / "catalog.sqlite"))
        db.execute("UPDATE runs SET started=? WHERE id=(SELECT MAX(id) FROM runs)", (when,))
        db.commit()
        db.close()

    def state_files(self):
        return {p.relative_to(self.src).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.src.rglob("*.jpg")}

    def test_gfs_cycle_cleanup_restore(self):
        states = {}
        dates = ["2025-01-01", "2025-01-10", "2025-02-05", "2025-02-10", "2025-03-08", "2025-04-03",
                 "2025-04-04", "2025-05-05", "2025-05-06", "2025-05-07", "2025-07-05", "2025-07-06"]
        for when in dates:
            self.add_file()
            self.export(when + " 10:00:00")
            cat = Catalog(self.target / "Sam" / self.src.name)
            states[cat.runs()[-1].id] = self.state_files()
            cat.close()
        parent = self.target / "Sam" / self.src.name
        cat = Catalog(parent)
        types = [r.type for r in cat.runs()]
        cat.close()
        self.assertEqual(types[0], "full")
        self.assertIn("differential", types)
        self.assertEqual(types.count("full"), 3)            # 2025-01, 2025-04, 2025-07

        cat = Catalog(parent)
        retire = gfs.to_retire(cat.runs(), {"full": 2, "differential": 1, "incremental": 2})
        cat.close()
        removed, problems = remove_runs(parent, [r.id for r in retire],
                                        {"full": 2, "differential": 1, "incremental": 2})
        self.assertEqual(problems, [])
        self.assertEqual(len(removed), len(retire))
        self.assertTrue(retire)
        for r in retire:
            self.assertFalse((parent / r.folder).exists())

        # every export that is left restores exactly the state it was made from
        cat = Catalog(parent)
        left = gfs.active(cat.runs())
        for r in left:
            chain = restore_chain(cat, r.id)
            self.assertTrue(all((parent / c.folder).is_dir() for c in chain), r.folder)
            out = Path(self.tmp.name) / f"restore{r.id}"
            perform_restore(parent, r.id, out, self.cfg)
            got = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in out.rglob("*.jpg")}
            self.assertEqual(got, states[r.id], f"restore of {r.folder} ({r.type})")
        cat.close()

        # the next export still works and is incremental on top of what is left
        self.add_file()
        perform_export(self.src, self.target, "auto", self.cfg, now=d("2025-07-07 10:00:00"))
        cat = Catalog(parent)
        last = gfs.active(cat.runs())[-1]
        files = cat.files_of([last.id])
        cat.close()
        self.assertEqual(len(files), 1, "only the new photo is exported")

    def test_remove_runs_refuses_needed(self):
        self.add_file()
        self.export("2025-01-01 10:00:00")
        self.add_file()
        self.export("2025-01-02 10:00:00")
        parent = self.target / "Sam" / self.src.name
        removed, problems = remove_runs(parent, [1, 2])
        self.assertEqual(removed, [])
        self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main()
