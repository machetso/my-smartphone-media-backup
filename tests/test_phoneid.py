"""Never mix up phones: the backup folder remembers its phone (user requirement 2026-11-04)."""
import tempfile
import unittest
from pathlib import Path

from phonebackup import phoneid as P

SAMSUNG_USB = P.PhoneId("SM-G780G", "samsung", "RF8TEST0001", "", "usb-adb")
SAMSUNG_APP = P.PhoneId("SM-G780G", "samsung", "", "app-samsung", "app-wifi")
SAMSUNG_LINKED = P.PhoneId("SM-G780G", "samsung", "RF8TEST0001", "app-samsung", "usb-adb")
PIXEL_APP = P.PhoneId("Pixel 10 Pro", "Google", "", "app-pixel", "app-wifi")
PIXEL_USB = P.PhoneId("Pixel 10 Pro", "Google", "PX10TEST000001", "", "usb-adb")
OTHER_S20 = P.PhoneId("SM-G780G", "samsung", "OTHERSERIAL", "", "usb-adb")


class PhoneIdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name) / "Galaxy A55 - Kim"

    def tearDown(self):
        self.tmp.cleanup()

    def test_todays_mixup_is_refused(self):
        """Samsung backed up over the cable, then the Pixel turns up over Wi-Fi → refused."""
        P.learn(self.parent, SAMSUNG_USB, P.compare(P.load(self.parent), SAMSUNG_USB))
        self.assertEqual(P.compare(P.load(self.parent), PIXEL_APP), P.MISMATCH)
        self.assertEqual(P.compare(P.load(self.parent), PIXEL_USB), P.MISMATCH)

    def test_same_phone_other_connection(self):
        P.learn(self.parent, SAMSUNG_LINKED, P.NEW)       # cable + app verified: both ids known
        for pid in (SAMSUNG_USB, SAMSUNG_APP, SAMSUNG_LINKED):
            self.assertEqual(P.compare(P.load(self.parent), pid), P.MATCH, pid)

    def test_other_phone_same_model_is_refused(self):
        P.learn(self.parent, SAMSUNG_USB, P.NEW)
        self.assertEqual(P.compare(P.load(self.parent), OTHER_S20), P.MISMATCH)

    def test_model_only_is_probable_and_learns_nothing(self):
        P.learn(self.parent, SAMSUNG_USB, P.NEW)
        self.assertEqual(P.compare(P.load(self.parent), SAMSUNG_APP), P.PROBABLE)
        P.learn(self.parent, SAMSUNG_APP, P.PROBABLE)
        self.assertEqual(P.load(self.parent).app_ids, [])

    def test_new_folder(self):
        self.assertEqual(P.compare(P.load(self.parent), PIXEL_APP), P.NEW)
        P.learn(self.parent, PIXEL_APP, P.NEW)
        self.assertEqual(P.load(self.parent).app_ids, ["app-pixel"])

    def test_double_check(self):
        self.assertTrue(P.same_phone(SAMSUNG_LINKED, SAMSUNG_USB))
        self.assertFalse(P.same_phone(SAMSUNG_USB, OTHER_S20))
        self.assertFalse(P.same_phone(SAMSUNG_APP, PIXEL_APP))

    def test_speed_advice(self):
        self.assertTrue(P.speed_advice(SAMSUNG_USB, 5000)[0])
        fast, text = P.speed_advice(SAMSUNG_USB, 480)
        self.assertFalse(fast)
        self.assertIn("USB 3", text)
        fast, text = P.speed_advice(PIXEL_APP)
        self.assertFalse(fast)
        self.assertIn("Allow backup over cable", text)


if __name__ == "__main__":
    unittest.main()


class OldReportTest(unittest.TestCase):
    def test_identity_from_old_report(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "Backup Galaxy A55 Kim 2026-11-04.txt").write_text(
                "  Smartphone       : SM-G780G\n"
                "  Connection       : ADB - ADB (USB debugging), serial RF8TEST0001, Android 13\n",
                encoding="utf-8")
            (Path(d) / "Backup Galaxy A55 Kim 2026-11-05.txt").write_text(
                "  Smartphone       : SM-G780G\n"
                "  Connection       : ADB over Wi-Fi - ADB (Wi-Fi), serial 192.168.1.5:4321, Android 13\n",
                encoding="utf-8")
            rec = P.load(d)
            self.assertEqual((rec.model, rec.serials), ("SM-G780G", ["RF8TEST0001"]))
            self.assertEqual(P.compare(rec, PIXEL_APP), P.MISMATCH)
            self.assertEqual(P.compare(rec, SAMSUNG_USB), P.MATCH)
            self.assertEqual(P.compare(rec, SAMSUNG_APP), P.PROBABLE)

    def test_identity_from_report_in_logs_folder(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "Logs").mkdir()
            (Path(d) / "Logs" / "Backup Galaxy A55 Kim 2026-11-11.txt").write_text(
                "  Smartphone       : SM-G780G\n"
                "  Connection       : ADB - ADB (USB debugging), serial RF8TEST0002, Android 13\n",
                encoding="utf-8")
            (Path(d) / "Backup Galaxy A55 Kim 2026-11-04.txt").write_text(      # old place
                "  Smartphone       : SM-G780G\n"
                "  Connection       : ADB - ADB (USB debugging), serial RF8TEST0001, Android 13\n",
                encoding="utf-8")
            rec = P.load(d)
            self.assertEqual((rec.model, sorted(rec.serials)), ("SM-G780G", ["RF8TEST0001", "RF8TEST0002"]))


class CableAdviceTest(unittest.TestCase):
    def test_phone_already_on_cable(self):
        fast, text = P.speed_advice(SAMSUNG_APP, 5000, "Samsung phone")
        self.assertFalse(fast)
        self.assertIn("already on the USB cable (USB 3)", text)
        self.assertNotIn("plug the phone in", text)

    def test_samsung_name_on_cable(self):
        import tempfile as tf
        from phonebackup import adbsetup
        with tf.TemporaryDirectory() as d:
            p = Path(d) / "4-1"
            p.mkdir()
            (p / "idVendor").write_text("04e8")
            (p / "manufacturer").write_text("SAMSUNG")
            (p / "product").write_text("SAMSUNG_Android")
            self.assertEqual(adbsetup._linux_usb_phones(d), ["Samsung phone"])
