import unittest

from phonebackup import phoneguard
from phonebackup.sources import _q

ALLOWED = [
    "getprop ro.product.model",
    "[ -d " + _q("/sdcard/DCIM/Camera") + " ] && echo YES",
    "find " + _q("/sdcard/DCIM") + " -mindepth 1 -maxdepth 1 -type d 2>/dev/null",
    "find " + _q("/sdcard/DCIM/Camera") + " -type f -exec stat -c '%s %Y %n' {} + 2>/dev/null",
    "command -v sha256sum >/dev/null && echo YES",
    "sha256sum " + _q("/sdcard/DCIM/a.jpg") + " " + _q("/sdcard/DCIM/it's; rm -rf x.jpg"),
    "cat " + _q("/sdcard/DCIM/Camera/PXL_1.jpg"),
    "cat " + _q("/sdcard/weird $(name) `x` ; | & .jpg"),
]

FORBIDDEN = [
    "rm -rf /sdcard/DCIM",
    "cat " + _q("/sdcard/a.jpg") + "; rm -rf /sdcard",
    "cat " + _q("/data/data/com.bank/secret"),
    "cat " + _q("/sdcard/../data/x"),
    "cat '/sdcard/a.jpg' && rm '/sdcard/a.jpg'",
    "pm install x.apk",
    "screencap -p",
    "input tap 1 1",
    "settings put global adb_enabled 0",
    "getprop",
    "sha256sum",
    "cat " + _q("/sdcard/a.jpg") + "\nrm x",
]


class PhoneGuardTest(unittest.TestCase):
    def test_allowed(self):
        for c in ALLOWED:
            phoneguard.check(c)      # must not raise

    def test_forbidden(self):
        for c in FORBIDDEN:
            with self.assertRaises(phoneguard.ForbiddenPhoneCommand, msg=c):
                phoneguard.check(c)


if __name__ == "__main__":
    unittest.main()
