"""Which connection is the fastest (user request 2026-11-10)."""
import unittest

from phonebackup import connspeed


class ConnSpeedTest(unittest.TestCase):
    def test_wireless_debugging_is_slower_than_the_phone_app(self):
        # measured 2026-11-10: phone app 8–11 MB/s, Wireless debugging 6.2 MB/s (same Wi-Fi, same files)
        rows = connspeed.options({"app_wifi": True, "adb_wifi": True, "wifi_mbit": 540})
        speeds = {r["key"]: r["speed"] for r in rows}
        self.assertGreater(speeds["app_wifi"], speeds["wifi_adb"])
        self.assertIsNone(connspeed.faster_than(rows, "app_wifi"))

    def test_usb3_debugging_is_fastest(self):
        rows = connspeed.options({"usb_phone": "Pixel", "usb_mbit": 5000, "adb_usb": True,
                                  "app_wifi": True, "wifi_mbit": 866})
        self.assertEqual(rows[0]["key"], "adb_usb")
        self.assertIsNone(connspeed.faster_than(rows, "adb_usb"))

    def test_measured_speed_wins_and_small_differences_give_no_hint(self):
        rows = connspeed.options({"app_wifi": True, "adb_wifi": True, "wifi_mbit": 300},
                                 seen={"app_wifi": 12.4})
        self.assertEqual(next(r for r in rows if r["key"] == "app_wifi")["speed"], 12.4)
        self.assertIsNone(connspeed.faster_than(rows, "app_wifi"))   # 15 vs 12.4: not clearly faster

    def test_remember_only_long_backups(self):
        cfg = {}
        self.assertFalse(connspeed.remember(cfg, "mtp", 10 * 1024 * 1024, 5))
        self.assertTrue(connspeed.remember(cfg, "mtp", 2_000_000_000, 100))
        self.assertEqual(cfg["speed_seen"]["mtp"], 20.0)
        self.assertEqual(connspeed.current_key("adb_app"), "adb_usb")


if __name__ == "__main__":
    unittest.main()
