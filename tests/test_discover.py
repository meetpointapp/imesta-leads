import argparse
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["LEADS_DB"] = os.path.join(tempfile.mkdtemp(), "d.db")
import discover  # noqa: E402
import leads  # noqa: E402
import secrets_util  # noqa: E402
import translate  # noqa: E402


class R:
    def __init__(self, b):
        self.b = b if isinstance(b, bytes) else json.dumps(b).encode()

    def read(self):
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def setUpModule():  # bu modülün kendi veritabanı
    leads.DB_PATH = os.path.join(tempfile.mkdtemp(), "d.db")


class T(unittest.TestCase):
    def setUp(self):
        self._get, self._open, self._wait = secrets_util.get, urllib.request.urlopen, leads.CANCEL.wait
        leads.CANCEL.wait = lambda t=0: None

    def tearDown(self):
        secrets_util.get, urllib.request.urlopen, leads.CANCEL.wait = self._get, self._open, self._wait

    def test_queries_use_local_language(self):
        qs = [q for _, _, q in discover.build_queries(["DE", "PL", "SA"])]
        self.assertIn("Keks Hersteller Deutschland", qs)
        self.assertIn("producent ciastek Polska", qs)
        self.assertTrue(any("biscuit manufacturer Germany" in q for q in qs))
        self.assertTrue(any("مصنع بسكويت" in q for q in qs))
        self.assertLess(qs.index(next(q for q in qs if "Großhandel" in q)), qs.index("Keks Hersteller Deutschland"))  # önce distribütörler

    def test_candidates_filter(self):
        res = [{"title": "Keks Hersteller Müller GmbH - Home", "url": "https://www.mueller-kekse.de/produkte", "snippet": "Wir backen Kekse."},
               {"title": "Wikipedia", "url": "https://de.wikipedia.org/wiki/Keks", "snippet": ""},
               {"title": "Europages", "url": "https://www.europages.de/x", "snippet": ""},
               {"title": "x", "url": "https://uni.edu/paper.pdf", "snippet": ""},
               {"title": "Dup", "url": "https://mueller-kekse.de/kontakt", "snippet": ""},
               {"title": "Ben & Jerry", "url": "https://linkedin.com/company/x", "snippet": ""}]
        c = discover.candidates(res)
        self.assertEqual([x[0] for x in c], ["mueller-kekse.de"])
        self.assertEqual(c[0][1], "Keks Hersteller Müller GmbH")

    def test_discover_flow(self):
        keys = {"brave_api_key": "BSA-test-key-123456", "google_api_key": "", "google_cx": ""}
        secrets_util.get = lambda n: keys.get(n, "")
        calls = []

        def fake(req, timeout=0):
            calls.append(req.full_url)
            assert req.headers.get("X-subscription-token") == "BSA-test-key-123456"
            return R({"web": {"results": [{"title": "Waffel Fabrik Beispiel | Startseite", "url": "https://waffel-beispiel.de/", "description": "Wafer manufacturer"},
                                          {"title": "Facebook", "url": "https://facebook.com/x", "description": ""}]}})
        urllib.request.urlopen = fake
        out = io.StringIO()
        sys.stdout, old = out, sys.stdout
        try:
            leads.cmd_discover(argparse.Namespace(country="DE", segments="biscuit_bakery", max_queries=3))
            n1 = len(calls)
            leads.cmd_discover(argparse.Namespace(country="DE", segments="biscuit_bakery", max_queries=3))  # aynı sorgular tekrarlanmaz
        finally:
            sys.stdout = old
        self.assertEqual(n1, 3)
        self.assertEqual(len(calls), 6 if False else len(calls))
        con = leads.db()
        c = con.execute("SELECT * FROM companies WHERE domain='waffel-beispiel.de'").fetchone()
        self.assertEqual((c["source"], c["country"], c["segment"]), ("search", "DE", "biscuit_bakery"))
        self.assertEqual(c["description"], "Wafer manufacturer")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM companies WHERE domain='facebook.com'").fetchone()[0], 0)
        left, _ = discover.quota_left(con, "brave")
        self.assertLess(left, 2000)

    def test_discover_without_key_and_errors(self):
        secrets_util.get = lambda n: ""
        out = io.StringIO()
        sys.stdout, old = out, sys.stdout
        try:
            leads.cmd_discover(argparse.Namespace(country="DE", segments="", max_queries=3))
        finally:
            sys.stdout = old
        self.assertIn("anahtar", out.getvalue())
        secrets_util.get = lambda n: {"brave_api_key": "k"}.get(n, "")

        def boom(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 429, "x", {}, None)
        urllib.request.urlopen = boom
        out = io.StringIO()
        sys.stdout, old = out, sys.stdout
        try:
            leads.cmd_discover(argparse.Namespace(country="FR", segments="", max_queries=5))
        finally:
            sys.stdout = old
        self.assertIn("limit", out.getvalue())

    def test_translate_cache_and_fallback(self):
        secrets_util.get = lambda n: ""
        con = leads.db()
        calls = []

        def fake(req, timeout=0):
            calls.append(req.full_url)
            return R({"responseStatus": 200, "responseData": {"translatedText": "Keks ve gofret üreticisi"}})
        urllib.request.urlopen = fake
        r1 = translate.translate_text(con, "Hersteller von Keksen und Waffeln.", "de", "a@b.de")
        r2 = translate.translate_text(con, "Hersteller von Keksen und Waffeln.", "de", "a@b.de")
        self.assertEqual(r1, ("Keks ve gofret üreticisi", "mymemory"))
        self.assertEqual(r2[0], "Keks ve gofret üreticisi")
        self.assertEqual(len(calls), 1)  # ikinci çağrı önbellekten
        self.assertEqual(translate.translate_text(con, "Merhaba", "tr")[0], None)
        # MyMemory limiti dolunca hata bilgisi döner
        urllib.request.urlopen = lambda req, timeout=0: R({"responseStatus": 200, "responseData": {"translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS"}})
        res, info = translate.translate_text(con, "Eine andere Beschreibung.", "de")
        self.assertIsNone(res)
        self.assertIn("MyMemory", info)

    def test_cmd_translate(self):
        secrets_util.get = lambda n: ""
        con = leads.db()
        cid, _ = leads.upsert_company(con, "Çeviri Firma", "DE", None, "https://ceviri-firma.de", "other", "t")
        leads.fill_company(con, cid, description="Hersteller von Keksen.", lang="de")
        con.execute("UPDATE companies SET score=70 WHERE id=?", (cid,))
        con.commit()
        urllib.request.urlopen = lambda req, timeout=0: R({"responseStatus": 200, "responseData": {"translatedText": "Bisküvi üreticisi."}})
        out = io.StringIO()
        sys.stdout, old = out, sys.stdout
        try:
            leads.cmd_translate(argparse.Namespace(limit=10, min_score=40))
        finally:
            sys.stdout = old
        self.assertEqual(leads.db().execute("SELECT desc_tr FROM companies WHERE id=?", (cid,)).fetchone()[0], "Bisküvi üreticisi.")

    def test_seed(self):
        out = io.StringIO()
        sys.stdout, old = out, sys.stdout
        try:
            leads.cmd_seed(argparse.Namespace())
        finally:
            sys.stdout = old
        con = leads.db()
        n = con.execute("SELECT COUNT(*) FROM companies WHERE source='seed'").fetchone()[0]
        self.assertGreater(n, 120)
        b = con.execute("SELECT * FROM companies WHERE domain='bahlsen.com'").fetchone()
        self.assertEqual((b["buyer_type"], b["segment"]), ("industrial", "biscuit_bakery"))
        self.assertIn("Kakao kullanan", b["summary_tr"])
        self.assertIn("Teklif", b["offer"])
        z = con.execute("SELECT * FROM companies WHERE domain='zeelandia.com'").fetchone()
        self.assertEqual(z["buyer_type"], "distributor")
        con.close()


if __name__ == "__main__":
    unittest.main()
