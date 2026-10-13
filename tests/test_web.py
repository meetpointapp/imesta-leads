import argparse
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import crawler  # noqa: E402
import leads  # noqa: E402
import secrets_util  # noqa: E402
import web  # noqa: E402

orig_crawl = crawler.crawl_site
orig_open = urllib.request.urlopen
SRV = {}

TEXT = {
    "biscuit_bakery": "<html lang='de'><head><title>{n} – Kekse und Waffeln</title><meta name='description' content='Hersteller von Keksen, Waffeln und Kuchen für Handel und Industrie.'>"
                      "<script type='application/ld+json'>{{\"@type\":\"Organization\",\"name\":\"{n}\",\"numberOfEmployees\":{{\"value\":{emp}}},\"foundingDate\":\"1950\"}}</script></head>"
                      "<body><h1>Hersteller von Keksen, Waffeln und Kuchen</h1><p>Unsere Fabrik produziert Biscuit, Waffel, Kuchen, Gebäck für Industriekunden (Eigenmarke). Kakao, Schokolade.</p>"
                      "<a href='/kontakt'>Kontakt</a><p>Einkauf: Anna Beispiel</p><a href='mailto:einkauf@{d}'>Einkauf</a><a href='tel:+4922112345{emp}'>Tel</a></body></html>",
    "distributor": "<html lang='en'><head><title>{n}</title><meta name='description' content='Wholesale distributor of bakery ingredients, cocoa and sugar.'></head><body><h1>Wholesale distributor</h1>"
                   "<p>Ingredients ingredients ingredients. B2B bulk 25 kg pallets. Distributor importer wholesale. Bakery ingredients.</p><a href='mailto:sales@{d}'>sales</a></body></html>",
    "chocolate_maker": "<html lang='en'><head><title>{n}</title></head><body><h1>Cocoa processor</h1><p>Cocoa processing and cocoa grinding. Bean to bar. Cocoa butter producer. Cocoa processor origin cocoa. "
                       "Manufacturer factory.</p><a href='mailto:info@{d}'>info</a></body></html>",
    "other": "<html><body><h1>Online Shop</h1><p>In den Warenkorb. Warenkorb Checkout. Schokolade Pralinen Geschenkbox. Öffnungszeiten. Ladengeschäft Filialen.</p></body></html>",
}


def gen_fetch(url, timeout=0):
    p = urllib.parse.urlparse(url)
    host = p.netloc[4:] if p.netloc.startswith("www.") else p.netloc
    if p.path.rstrip("/") not in ("", "/kontakt") or host not in SRV:
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)
    seg, emp, name = SRV[host]
    return url, TEXT.get(seg, TEXT["other"]).format(n=name, d=host, emp=emp)


class R:
    def __init__(self, b):
        self.b = json.dumps(b).encode()

    def read(self):
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def setUpModule():
    leads.DB_PATH = os.path.join(tempfile.mkdtemp(), "w.db")
    secrets_util.PATH = os.path.join(tempfile.mkdtemp(), "secrets.json")
    leads.mail_domain_ok = lambda d: True
    leads.time.sleep = lambda s: None
    crawler.crawl_site = lambda url, **kw: orig_crawl(url, max_pages=3, delay=0, cancel=kw.get("cancel"), fetcher=gen_fetch)
    urllib.request.urlopen = lambda req, timeout=0: R({"responseStatus": 200, "responseData": {"translatedText": "Bisküvi, gofret ve kek üreticisi."}})
    con = leads.db()
    out = sys.stdout
    sys.stdout = io.StringIO()
    leads.cmd_seed(argparse.Namespace())
    sys.stdout = out
    for r in con.execute("SELECT name,domain,segment,buyer_type FROM companies WHERE source='seed'").fetchall():
        SRV[r["domain"]] = (r["segment"] if r["buyer_type"] != "distributor" else "distributor", 120 + len(SRV), r["name"])
    SRV["bahlsen.com"] = ("biscuit_bakery", 2800, "Bahlsen")
    SRV["valrhona.com"] = ("chocolate_maker", 900, "Valrhona")
    SRV["gruppocolussi.it"] = ("other", 50, "Colussi")
    con.close()
    out = sys.stdout
    sys.stdout = io.StringIO()
    leads.cmd_enrich(argparse.Namespace(limit=500, workers=8, pages=3, force=False))
    leads.cmd_score(argparse.Namespace())
    leads.cmd_translate(argparse.Namespace(limit=30, min_score=30))
    sys.stdout = out
    srv = ThreadingHTTPServer(("127.0.0.1", 8777), web.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SRV["_srv"] = srv


def tearDownModule():
    crawler.crawl_site = orig_crawl
    urllib.request.urlopen = orig_open
    SRV["_srv"].shutdown()


B = "http://127.0.0.1:8777"


class N(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def post(p, pairs=()):
    r = urllib.request.Request(B + p, urllib.parse.urlencode(list(pairs)).encode(), headers={"Origin": B})
    try:
        return urllib.request.build_opener(N).open(r).status, ""
    except urllib.error.HTTPError as e:
        return e.code, urllib.parse.unquote(e.headers.get("Location", ""))


def get(p):
    r = orig_open(B + p)
    return r.status, r.read()


class T(unittest.TestCase):
    def test_classification_of_seeds(self):
        con = leads.db()
        g = lambda d: con.execute("SELECT * FROM companies WHERE domain=?", (d,)).fetchone()  # noqa: E731
        self.assertEqual(g("bahlsen.com")["buyer_type"], "industrial")
        self.assertEqual(g("valrhona.com")["buyer_type"], "competitor")  # kakao işleyici: fırsat değil
        self.assertLessEqual(g("valrhona.com")["score"], 35)
        self.assertEqual(g("bahlsen.com")["segment"], "biscuit_bakery")
        self.assertGreater(g("bahlsen.com")["score"], g("valrhona.com")["score"] + 30)
        self.assertEqual(g("bahlsen.com")["desc_tr"], "Bisküvi, gofret ve kek üreticisi.")
        self.assertEqual(g("bahlsen.com")["employees"], "2800")

    def test_opportunity_page(self):
        s, b = get("/firsatlar")
        b = b.decode()
        self.assertEqual(s, 200)
        self.assertIn("Bahlsen", b)
        self.assertNotIn(">Valrhona<", b)  # rakip fırsat listesinde yok
        self.assertIn("Kakao kullanan üretici (sanayi alıcısı)", b)
        self.assertIn("Teklif:", b)
        self.assertIn("Anna Beispiel", b)  # satın alma kişisi
        self.assertIn("einkauf@bahlsen.com", b)
        self.assertIn("Almanya", b)
        s, b = get("/firsatlar?country=DE&type=industrial&min=40&ready=1")
        self.assertEqual(s, 200)
        s, b = get("/firsatlar?type=distributor")
        self.assertTrue("Zeelandia" in b.decode(), "distribütör fırsatı yok")

    def test_exports(self):
        s, b = get("/firsatlar.xlsx?min=40")
        self.assertEqual(s, 200)
        z = zipfile.ZipFile(io.BytesIO(b))
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("Bahlsen", sheet)
        self.assertIn("Anna Beispiel", sheet)
        self.assertNotIn("Valrhona", sheet)
        s, b = get("/firsatlar.csv?min=40")
        txt = b.decode("utf-8-sig")
        self.assertIn("Teklif", txt.splitlines()[0])
        self.assertIn("Bahlsen", txt)

    def test_skip_removes_from_list(self):
        con = leads.db()
        cid = con.execute("SELECT id FROM companies WHERE domain='bahlsen.com'").fetchone()[0]
        con.close()
        code, loc = post(f"/lead/{cid}/quick", [("do", "skip"), ("back", "/firsatlar")])
        self.assertEqual(code, 303)
        s, b = get("/firsatlar")
        self.assertNotIn(">Bahlsen<", b.decode())
        c = leads.db()
        c.execute("UPDATE companies SET status='new', lost_reason=NULL WHERE id=?", (cid,))
        c.commit()
        c.close()

    def test_settings_and_tools(self):
        s, b = get("/settings")
        self.assertIn("Brave Search API", b.decode())
        code, loc = post("/settings", [("brave_api_key", "BSA-abcdefghijk123")])
        self.assertEqual(code, 303)
        self.assertEqual(secrets_util.get("brave_api_key"), "BSA-abcdefghijk123")
        s, b = get("/settings")
        self.assertNotIn("abcdefghijk123", b.decode())  # anahtar maskeli gösterilir
        self.assertIn("tanımlı", b.decode())
        s, b = get("/tools")
        self.assertIn("Otopilotu çalıştır", b.decode())
        self.assertIn("brave anahtarı tanımlı", b.decode())
        post("/settings", [("clear", "brave_api_key")])
        self.assertEqual(secrets_util.get("brave_api_key"), "")

    def test_lead_page_and_list(self):
        con = leads.db()
        cid = con.execute("SELECT id FROM companies WHERE domain='bahlsen.com'").fetchone()[0]
        s, b = get(f"/lead/{cid}")
        b = b.decode()
        for needle in ("Alıcı mı?", "Neden potansiyel?", "Ne teklif edilir?", "Bisküvi, gofret ve kek üreticisi."):
            self.assertIn(needle, b)
        s, b = get("/leads?buyer_type=competitor")
        self.assertIn("Valrhona", b.decode())
        self.assertNotIn("Bahlsen", b.decode())

    def test_autopilot_runs(self):
        out = io.StringIO()
        old = sys.stdout
        sys.stdout = out
        calls = []
        o_osm, o_wd = leads.cmd_harvest_osm, leads.cmd_harvest_wikidata
        leads.cmd_harvest_osm = lambda a: calls.append(("osm", a.country))
        leads.cmd_harvest_wikidata = lambda a: calls.append(("wd", a.country))
        try:
            web.autopilot(["DE", "IT"])
        finally:
            sys.stdout = old
            leads.cmd_harvest_osm, leads.cmd_harvest_wikidata = o_osm, o_wd
        self.assertEqual(calls, [("osm", "DE,IT"), ("wd", "DE,IT")])
        self.assertIn("alıcı fırsatı hazır", web.JOB["summary"])


if __name__ == "__main__":
    unittest.main()
