import json
import unittest
import urllib.request

from phonebackup import companion, config


class CompanionTest(unittest.TestCase):
    def test_pairing_code(self):
        c = companion.pairing_code("tok", "ab" * 32)
        self.assertEqual(len(c), 6)
        self.assertTrue(c.isdigit())
        self.assertEqual(c, companion.pairing_code("tok", "ab" * 32))
        self.assertNotEqual(c, companion.pairing_code("tok2", "ab" * 32))

    def test_setup_server_pair_flow(self):
        saved = config.save
        config.save = lambda cfg: None
        try:
            got = []
            srv = companion.SetupServer({"pc_id": "x"}, got.append, port=0)
            srv.ip = "127.0.0.1"
            srv.start()
            try:
                page = urllib.request.urlopen(srv.page_url).read().decode()
                self.assertIn("intent://pair?", page)
                self.assertIn("package=" + companion.APP_PACKAGE, page)

                def post(d):
                    req = urllib.request.Request(srv.base + "/pair", json.dumps(d).encode(),
                                                 {"Content-Type": "application/json"})
                    try:
                        return urllib.request.urlopen(req).status
                    except urllib.error.HTTPError as e:
                        return e.code

                self.assertEqual(post({"token": "wrong", "fingerprint": "a" * 64, "port": 1}), 403)
                self.assertEqual(post({"token": srv.token, "fingerprint": "zz", "port": 1}), 400)
                self.assertEqual(post({"token": srv.token, "fingerprint": "a" * 64, "port": 47823,
                                       "model": "Pixel"}), 200)
                self.assertEqual(len(got), 1)
                self.assertEqual(got[0].address, "127.0.0.1:47823")
                self.assertEqual(got[0].code, companion.pairing_code(srv.token, "a" * 64))
                # unknown token in the URL: no page, no app
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(srv.base + "/s/other")
            finally:
                srv.stop()
        finally:
            config.save = saved


if __name__ == "__main__":
    unittest.main()
