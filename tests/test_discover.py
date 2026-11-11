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
    leads.focus_countries = lambda: list(leads.COUNTRIES)  # eski testler: tüm ülkeler odakta
    leads.products.find_site = lambda brand, cc: None  # testte ağa çıkılmaz
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
        self.assertIn("hız sınırı", out.getvalue())

    def test_list_mining_page2_and_daily_cap(self):
        keys = {"serper_api_key": "serper-key"}
        secrets_util.get = lambda n: keys.get(n, "")
        bodies, fetched = [], []
        listing = ('<h1>Кондитерские фабрики Беларуси</h1><a href="https://kommunarka.by/">Коммунарка</a>'
                   '<a href="https://spartak.by/">Спартак</a><a href="https://vk.com/k">ВКонтакте</a><a href="https://spartak.by/">Подробнее</a>')

        def fake(req, timeout=0):
            if getattr(req, "data", None):  # arama isteği
                body = json.loads(req.data.decode())
                bodies.append(body)
                url = "https://rating-by.example/fabriki" if "список" in body["q"] else f"https://factory{len(bodies)}.by/"
                return R({"organic": [{"title": "Фабрика", "link": url, "snippet": "шоколад"}]})
            fetched.append(req.full_url)  # liste sayfasının kendisi
            return R(listing.encode())
        urllib.request.urlopen = fake
        orig_fetch = leads.crawler.fetch
        leads.crawler.fetch = lambda url, timeout=0: (url, listing)
        old_cfg = leads.config
        plan = len(discover.build_queries(["BY"], ["chocolate_maker"]))
        con = leads.db()
        leads.meta_set(con, f"search_{leads.today()}", 0)  # önceki testlerin bugünkü aramaları sayılmasın
        con.close()
        out = io.StringIO()
        sys.stdout, old = out, sys.stdout
        try:
            leads.config = lambda: {**old_cfg(), "daily_search_cap": 20}
            leads.cmd_discover(argparse.Namespace(country="BY", segments="chocolate_maker", max_queries=100))
            first = len(bodies)
            leads.config = lambda: {**old_cfg(), "daily_search_cap": 100}
            leads.cmd_discover(argparse.Namespace(country="BY", segments="chocolate_maker", max_queries=100))  # kalanlar; yapılanlar tekrarlanmaz
        finally:
            sys.stdout = old
            leads.crawler.fetch, leads.config = orig_fetch, old_cfg
        self.assertEqual((first, len(bodies)), (20, plan))  # günlük sınır, sonra planın geri kalanı
        self.assertIn("кондитерские фабрики Беларусь список", bodies[9]["q"])  # çikolata listeleri şehirlerden önce
        self.assertTrue(any(b.get("page") == 2 for b in bodies[20:]))  # 2. sayfalar en sonda
        con = leads.db()
        got = {r[0]: (r[1], r[2]) for r in con.execute("SELECT domain, source, segment FROM companies WHERE country='BY' AND source='liste'")}
        self.assertEqual(got, {"kommunarka.by": ("liste", "chocolate_maker"), "spartak.by": ("liste", "chocolate_maker")})
        done, total = leads.search_plan_status(con, ["BY"])
        self.assertEqual(done, plan)  # tüm çikolata sorguları yapıldı; diğer segmentler planda bekliyor
        self.assertGreater(total, done)
        con.close()

    def test_serper_then_tavily(self):
        keys = {"serper_api_key": "serper-key", "tavily_api_key": "tvly-key"}
        secrets_util.get = lambda n: keys.get(n, "")
        self.assertEqual(discover.providers(), ["serper", "tavily"])
        calls = []

        def fake(req, timeout=0):
            body = json.loads(req.data.decode())
            calls.append((req.full_url, body))
            if "serper" in req.full_url:
                assert req.headers.get("X-api-key") == "serper-key"
                if len(calls) > 1:  # ilk aramadan sonra kredi biter
                    raise urllib.error.HTTPError(req.full_url, 400, "Not enough credits", {}, None)
                return R({"organic": [{"title": "Оптовик Сырье | Главная", "link": "https://optovik-syrye.kz/", "snippet": "Какао порошок оптом"}]})
            assert req.headers.get("Authorization") == "Bearer tvly-key"
            return R({"results": [{"title": "Кондитерское сырье Алматы", "url": "https://konditer-almaty.kz/ru", "content": "Ингредиенты оптом"}]})
        urllib.request.urlopen = fake
        out = io.StringIO()
        sys.stdout, old = out, sys.stdout
        try:
            leads.cmd_discover(argparse.Namespace(country="KZ", segments="distributor", max_queries=3))
        finally:
            sys.stdout = old
        self.assertEqual((calls[0][1]["gl"], calls[0][1]["hl"]), ("kz", "ru"))  # Kazakistan Google'ında Rusça
        self.assertIn("какао порошок оптом", calls[0][1]["q"])
        self.assertTrue(any("tavily" in u and b.get("country") == "kazakhstan" for u, b in calls))
        self.assertIn("sıradaki servise", out.getvalue())
        con = leads.db()
        got = {r[0]: r[1] for r in con.execute("SELECT domain, segment FROM companies WHERE country='KZ' AND source='search'")}
        self.assertEqual(got, {"optovik-syrye.kz": "distributor", "konditer-almaty.kz": "distributor"})
        self.assertLessEqual(discover.quota_left(con, "serper")[0], 0)  # bitmiş sayılır, sonraki turda tekrar denenmez
        con.close()

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
