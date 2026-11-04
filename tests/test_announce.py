"""Anonymous announcement (same format as Announce.kt) and the debugging guard on the computer."""
import hashlib
import hmac
import unittest

from phonebackup import companion as c

SECRET = "ab" * 32
OTHER = "cd" * 32
NOW = 1_800_000_000


def kotlin_ble(secrets, ip, port, w):
    """Re-implementation of Announce.bleData for the test."""
    out = b"FB\x01"
    for s in secrets[:2]:
        tok = hmac.new(s.encode(), f"fmb-announce:{w}".encode(), hashlib.sha256).digest()[:6]
        mask = hmac.new(s.encode(), f"fmb-addr:{w}".encode(), hashlib.sha256).digest()[:6]
        plain = bytes(int(x) for x in ip.split(".")) + port.to_bytes(2, "big")
        out += tok + bytes(a ^ b for a, b in zip(plain, mask))
    return out


class AnnounceTest(unittest.TestCase):
    entries = [{"phone_id": "p1", "secret": SECRET}, {"phone_id": "p2", "secret": OTHER}]

    def test_token_changes_every_window(self):
        w = c.window(NOW)
        self.assertNotEqual(c.announce_token(SECRET, w), c.announce_token(SECRET, w + 1))
        self.assertEqual(len(c.announce_token(SECRET, w)), 6)

    def test_match_with_clock_skew(self):
        w = c.window(NOW)
        for skew in (-1, 0, 1):
            tok = c.announce_token(OTHER, w + skew)
            self.assertEqual(c.match_token(self.entries, [tok], NOW)["phone_id"], "p2")
        self.assertIsNone(c.match_token(self.entries, [c.announce_token(OTHER, w + 3)], NOW))
        self.assertIsNone(c.match_token(self.entries, [b"\0" * 6], NOW))

    def test_ble_roundtrip(self):
        w = c.window(NOW)
        data = kotlin_ble([OTHER, SECRET], "192.168.1.60", 47823, w)
        self.assertLessEqual(len(data), 27)              # fits a legacy advertisement
        e, addr = c.decode_ble(self.entries, data, NOW)
        self.assertEqual(e["phone_id"], "p2")
        self.assertEqual(addr, "192.168.1.60:47823")
        e, addr = c.decode_ble([self.entries[0]], data, NOW)
        self.assertEqual((e["phone_id"], addr), ("p1", "192.168.1.60:47823"))

    def test_ble_unknown_or_no_network(self):
        w = c.window(NOW)
        self.assertEqual(c.decode_ble(self.entries, kotlin_ble(["ef" * 32], "10.0.0.1", 1, w), NOW),
                         (None, None))
        e, addr = c.decode_ble(self.entries, kotlin_ble([SECRET], "0.0.0.0", 47823, w), NOW)
        self.assertEqual((e["phone_id"], addr), ("p1", None))
        self.assertEqual(c.decode_ble(self.entries, b"XX", NOW), (None, None))


class GuardTest(unittest.TestCase):
    def test_start_beat_end(self):
        calls = []

        class FakeClient:
            def request(self, method, path, body=None):
                calls.append((path, body))
                return {"ok": True}

        g = c.AppGuard(FakeClient(), "usb")
        g.INTERVAL = 0.05
        g.start()
        import time
        time.sleep(0.2)
        g.end(switch_off=True)
        paths = [p for p, _ in calls]
        self.assertEqual(paths[0], "/guard/start")
        self.assertEqual(calls[0][1], {"channel": "usb"})
        self.assertIn("/guard/alive", paths)
        self.assertEqual(calls[-1], ("/guard/end", {"off": True}))


if __name__ == "__main__":
    unittest.main()
