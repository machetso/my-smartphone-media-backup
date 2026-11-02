import sys
import unittest

from phonebackup.keepawake import KeepAwake


class KeepAwakeTest(unittest.TestCase):
    def test_disabled_does_nothing(self):
        with KeepAwake("Backup", enabled=False) as ka:
            self.assertFalse(ka.active)
        self.assertIn("could not", ka.message().lower())

    def test_enable_and_release_never_raises(self):
        # On CI there may be no logind session - then it must just report why, not fail.
        with KeepAwake("Backup") as ka:
            self.assertIsInstance(ka.message(), str)
            proc = ka._proc
        self.assertFalse(ka.active)
        if proc is not None:
            self.assertIsNotNone(proc.poll(), "inhibitor process must end after the job")

    def test_desktop_idle_inhibit_is_released(self):
        calls = []
        ka = KeepAwake("Backup")
        ka._idle = [(lambda: calls.append("un1"), None), (lambda: calls.append("un2"), None)]
        ka.release()
        self.assertEqual(sorted(calls), ["un1", "un2"])
        self.assertEqual(ka._idle, [])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux only")
    def test_exception_inside_job_releases(self):
        try:
            with KeepAwake("Backup") as ka:
                proc = ka._proc
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        if proc is not None:
            self.assertIsNotNone(proc.poll())


if __name__ == "__main__":
    unittest.main()
