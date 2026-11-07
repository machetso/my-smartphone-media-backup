import json
import time
import unittest
import urllib.request
from unittest import mock

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

                nonce = "0f" * 16
                self.assertEqual(post({"token": "wrong", "fingerprint": "a" * 64, "port": 1, "nonce": nonce}), 403)
                self.assertEqual(post({"token": srv.token, "fingerprint": "zz", "port": 1, "nonce": nonce}), 400)
                self.assertEqual(post({"token": srv.token, "fingerprint": "a" * 64, "port": 1, "nonce": "x"}), 400)
                revealed = []
                with mock.patch.object(companion.SetupServer, "reveal", lambda s, r: revealed.append(r)):
                    self.assertEqual(post({"token": srv.token, "fingerprint": "a" * 64, "port": 47823,
                                           "nonce": nonce, "model": "Pixel"}), 200)
                    for _ in range(50):
                        if revealed:
                            break
                        time.sleep(0.02)
                self.assertEqual(len(got), 1)
                self.assertEqual(revealed, got)                 # the key goes out right after
                self.assertEqual(got[0].address, "127.0.0.1:47823")
                self.assertEqual(got[0].code, companion.pairing_code_v2(srv.key, "a" * 64, nonce))
                # the link only carries the commitment, never the key itself
                self.assertEqual(srv.token, companion.token_for(srv.key))
                self.assertNotIn(srv.key, page)
                self.assertNotIn(srv.key, srv.intent_url())
                # unknown token in the URL: no page, no app
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(srv.base + "/s/other")
            finally:
                srv.stop()
        finally:
            config.save = saved


if __name__ == "__main__":
    unittest.main()


class CommitRevealTest(unittest.TestCase):
    """The key only goes to the phone over TLS pinned to the fingerprint it sent; claim uses it."""

    def test_reveal_and_claim_send_the_key_only_pinned(self):
        calls = []

        class FakeClient:
            def __init__(self, address, fingerprint, secret=None, timeout=0):
                self.fp = fingerprint

            def request(self, method, path, body=None):
                calls.append((self.fp, path, dict(body)))
                return {"secret": "s" * 40, "phone_id": "p"} if path == "/claim" else {"ok": True}

            def close(self):
                pass

        with mock.patch.object(companion, "local_ips", lambda: ["127.0.0.1"]), \
                mock.patch.object(companion, "Client", FakeClient), \
                mock.patch.object(companion, "save_phone", lambda cfg, e: None):
            srv = companion.SetupServer({"pc_id": "x"}, lambda r: None, port=0)
            req = companion.PairRequest(srv.token, "c" * 64, "10.0.0.5:1", "p", "Pixel", "Google", "16")
            self.assertTrue(srv.reveal(req))
            entry = srv.claim(req)
        self.assertEqual([c[1] for c in calls], ["/reveal", "/claim"])
        for fp, _path, body in calls:
            self.assertEqual(fp, "c" * 64)
            self.assertEqual(body, {"token": srv.token, "key": srv.key})
        self.assertEqual(entry["secret"], "s" * 40)

    def test_codes_depend_on_every_part(self):
        k, fp, n = "1" * 64, "a" * 64, "2" * 32
        c = companion.pairing_code_v2(k, fp, n)
        self.assertNotEqual(c, companion.pairing_code_v2("3" * 64, fp, n))
        self.assertNotEqual(c, companion.pairing_code_v2(k, "b" * 64, n))
        self.assertNotEqual(c, companion.pairing_code_v2(k, fp, "4" * 32))
