import unittest

from phonebackup import wireless


class WirelessTest(unittest.TestCase):
    def test_is_wireless(self):
        self.assertFalse(wireless.is_wireless("PX10TEST000001"))
        self.assertTrue(wireless.is_wireless("192.168.1.23:37123"))
        self.assertTrue(wireless.is_wireless("adb-PX10TEST000001-AbCdEf._adb-tls-connect._tcp"))

    def test_usb_first(self):
        self.assertEqual(wireless.usb_first(["10.42.0.5:4000", "PX10TEST000001"]),
                         ["PX10TEST000001", "10.42.0.5:4000"])

    def test_parse_mdns(self):
        out = ("List of discovered mdns services\n"
               "adb-PX10-AbCd\t_adb-tls-connect._tcp\t192.168.1.23:37123\n"
               "phonebackup-1a2b3c4d\t_adb-tls-pairing._tcp.\t192.168.1.23:41234\n"
               "garbage line\n")
        svcs = wireless.parse_mdns(out)
        self.assertEqual([(s.name, s.kind, s.address) for s in svcs],
                         [("adb-PX10-AbCd", wireless.CONNECT, "192.168.1.23:37123"),
                          ("phonebackup-1a2b3c4d", wireless.PAIRING, "192.168.1.23:41234")])

    def test_parse_avahi(self):
        out = ("+;wlp0s20f3;IPv4;phonebackup-5d9cbf9b;_adb-tls-pairing._tcp;local\n"
               "=;wlp0s20f3;IPv6;phonebackup-5d9cbf9b;_adb-tls-pairing._tcp;local;Android.local;"
               "192.168.1.60;33451;\"name=Pixel 10 Pro\"\n"
               "=;wlp0s20f3;IPv4;phonebackup-5d9cbf9b;_adb-tls-pairing._tcp;local;Android.local;"
               "192.168.1.60;33451;\"name=Pixel 10 Pro\"\n"
               "=;wlp0s20f3;IPv6;adb-X;_adb-tls-connect._tcp;local;Android.local;"
               "fe80::1;46417;\n")
        svcs = wireless.parse_avahi(out)
        self.assertEqual([(s.name, s.kind, s.address) for s in svcs],
                         [("phonebackup-5d9cbf9b", wireless.PAIRING, "192.168.1.60:33451")])

    def test_pair_validation(self):
        ok, msg = wireless.pair("/nonexistent/adb", "not an address", "123456")
        self.assertFalse(ok)
        ok, msg = wireless.pair("/nonexistent/adb", "192.168.1.2:4000", "")
        self.assertFalse(ok)

    def test_qr_texts(self):
        name, pw, text = wireless.new_qr_pairing()
        self.assertEqual(text, f"WIFI:T:ADB;S:{name};P:{pw};;")
        self.assertEqual(wireless.wifi_qr_text("My;Net", 'p"w'), 'WIFI:T:WPA;S:My\;Net;P:p\\"w;;')
        ssid, pw = wireless.new_hotspot_credentials()
        self.assertTrue(ssid.startswith("PhoneBackup-"))
        self.assertGreaterEqual(len(pw), 8)       # WPA2 minimum

    def test_port_closed(self):
        self.assertFalse(wireless._port_open("127.0.0.1:1", timeout=0.2))


if __name__ == "__main__":
    unittest.main()
