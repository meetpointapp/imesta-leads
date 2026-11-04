import argparse
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
os.environ["LEADS_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import leads  # noqa: E402
import crawler  # noqa: E402
from test_crawler import HOME, IMPRESSUM, TEAM, fake  # noqa: E402

BASE = "https://koeln-kakao.de"
PAGES = {BASE: HOME, BASE + "/impressum": IMPRESSUM, BASE + "/kontakt": IMPRESSUM, BASE + "/team": TEAM}
leads.mail_domain_ok = lambda d: "bad" not in d
orig_crawl = crawler.crawl_site
leads.time.sleep = lambda s: None


def setUpModule():  # sahte ağ ve ayrı veritabanı sadece bu modülün testlerinde geçerli
    leads.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    crawler.crawl_site = lambda url, **kw: orig_crawl(url, max_pages=kw.get("max_pages", 8), delay=0, cancel=kw.get("cancel"), fetcher=fake(PAGES))


def tearDownModule():
    crawler.crawl_site = orig_crawl


class R:
    def __init__(self, b):
        self.b = b

    def read(self):
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class T(unittest.TestCase):
    def test_pipeline(self):
        con = leads.db()
        cid, new = leads.upsert_company(con, "Köln Kakao GmbH", "de", None, BASE, "other", "osm")
        con.commit()
        leads.cmd_enrich(argparse.Namespace(limit=10, workers=3, pages=8, force=False))
        con = leads.db()
        c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
        ks = con.execute("SELECT * FROM contacts WHERE company_id=?", (cid,)).fetchall()
        by = {k["email"]: k for k in ks if k["email"]}
        self.assertEqual(by["einkauf@koeln-kakao.de"]["dept"], "purchasing")
        self.assertEqual(by["vertrieb@koeln-kakao.de"]["dept"], "sales")
        self.assertEqual(by["maria.rossi@koeln-kakao.de"]["name"], "Maria Rossi")  # kişi ↔ e-posta eşleşti
        self.assertEqual(by["maria.rossi@koeln-kakao.de"]["role"], "Purchasing Manager")
        g = by["hans.mueller@koeln-kakao.de"]
        self.assertEqual((g["kind"], g["confidence"]), ("guess", 35))
        self.assertEqual(c["phone"], "+49221123456")
        self.assertEqual(c["address"], "Kakaostraße 12, 50667 Köln, DE")
        self.assertEqual(c["legal_id"].split(" · ")[0], "VAT DE123456789")
        self.assertIn("linkedin.com/company/koeln-kakao", c["linkedin"])
        self.assertTrue(c["instagram"].endswith("koelnkakao"))
        self.assertEqual((c["employees"], c["founded"], c["lang"]), ("120", "1987", "de"))
        self.assertEqual(c["segment"], "biscuit_bakery")  # 'other' iken ürün kategorilerinden belirlendi
        self.assertEqual(c["buyer_type"], "industrial")
        self.assertEqual(c["business_type"], "manufacturer")
        self.assertGreaterEqual(c["data_score"], 90)
        self.assertEqual(c["enrich_v"], 2)
        self.assertTrue(any(k["kind"] == "phone" for k in ks))
        # en iyi kişi: gerçek satın alma adresi, tahminler değil
        self.assertEqual(leads.best_contact(con, cid)["email"], "einkauf@koeln-kakao.de")
        to, text = leads.render_email(con, cid, "de", "cold")
        self.assertEqual(to, "einkauf@koeln-kakao.de")
        self.assertIn("Sehr geehrte Damen und Herren,", text)
        # puanlama yeni sinyalleri kullanır
        leads.cmd_score(argparse.Namespace())
        con = leads.db()
        row = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
        self.assertGreaterEqual(row["score"], 75)
        reasons = json.loads(row["fit_reasons"])
        self.assertIn("Kakao kullanan üretici (sanayi alıcısı)", reasons)
        self.assertTrue(any("bisküvi" in r for r in reasons))
        self.assertTrue(any("sorumlusu" in r or "e-postası bulundu" in r for r in reasons))
        self.assertIn("bisküvi", row["summary_tr"])
        self.assertIn("Teklif", row["offer"])
        # tekrar tarama: atlanır; force ile çift kayıt oluşmaz
        n0 = con.execute("SELECT COUNT(*) FROM contacts WHERE company_id=?", (cid,)).fetchone()[0]
        out = io.StringIO()
        sys.stdout, old = out, sys.stdout
        leads.cmd_enrich(argparse.Namespace(limit=10, workers=2, pages=8, force=False))
        leads.cmd_enrich(argparse.Namespace(limit=10, workers=2, pages=8, force=True))
        sys.stdout = old
        self.assertIn("0 firma taranacak", out.getvalue())
        self.assertEqual(leads.db().execute("SELECT COUNT(*) FROM contacts WHERE company_id=?", (cid,)).fetchone()[0], n0)

    def test_export(self):
        con = leads.db()
        cid, _ = leads.upsert_company(con, "Export Firma", "DE", None, "https://exportfirma.de", "other", "test", None, "einkauf@koeln-kakao.de")
        con.commit()
        f = os.path.join(tempfile.mkdtemp(), "x.csv")
        leads.cmd_export(argparse.Namespace(file=f))
        leads.cmd_export_contacts(argparse.Namespace(file=f + "2"))
        self.assertIn("phone", open(f, encoding="utf-8-sig").readline())
        self.assertIn("einkauf@koeln-kakao.de", open(f + "2", encoding="utf-8-sig").read())

    def test_failed_site(self):
        con = leads.db()
        cid, _ = leads.upsert_company(con, "Yok Firma", "DE", None, "https://yok-firma.example", "other", "osm")
        con.commit()
        out = io.StringIO()
        sys.stdout, old = out, sys.stdout
        leads.cmd_enrich(argparse.Namespace(limit=10, workers=2, pages=8, force=False))
        sys.stdout = old
        self.assertIn("ulaşılamadı", out.getvalue())
        c = leads.db().execute("SELECT enrich_v, enrich_error FROM companies WHERE id=?", (cid,)).fetchone()
        self.assertEqual(c["enrich_v"], 2)
        self.assertTrue(c["enrich_error"])

    def test_wikidata(self):
        q = leads.wikidata_query(leads.WIKIDATA_TERMS)
        self.assertEqual(q.count("{"), q.count("}"))
        self.assertIn("EntitySearch", q)
        rows = [{"cLabel": {"value": "Barry Callebaut"}, "site": {"value": "https://www.barry-callebaut.com"}, "cc": {"value": "CH"},
                 "cityLabel": {"value": "Zürich"}, "emp": {"value": "13000"}, "inc": {"value": "1996-01-01T00:00:00Z"}, "indLabel": {"value": "chocolate industry"},
                 "li": {"value": "barry-callebaut"}},
                {"cLabel": {"value": "Q12345"}, "site": {"value": "https://x.example"}}, {"cLabel": {"value": "Ferrero"}, "site": {"value": "https://ferrero.com"}, "cc": {"value": "IT"},
                                                                                       "indLabel": {"value": "confectionery industry"}}]
        old = urllib.request.urlopen
        urllib.request.urlopen = lambda req, timeout=0: R(json.dumps({"results": {"bindings": rows}}).encode())
        try:
            leads.cmd_harvest_wikidata(argparse.Namespace(country=""))
            leads.cmd_harvest_wikidata(argparse.Namespace(country="IT"))
        finally:
            urllib.request.urlopen = old
        con = leads.db()
        b = con.execute("SELECT * FROM companies WHERE domain='barry-callebaut.com'").fetchone()
        self.assertEqual((b["segment"], b["employees"], b["founded"], b["city"]), ("chocolate_maker", "13000", "1996", "Zürich"))
        self.assertIn("linkedin.com/company/barry-callebaut", b["linkedin"])
        self.assertEqual(con.execute("SELECT segment FROM companies WHERE domain='ferrero.com'").fetchone()[0], "confectionery")
        self.assertIsNone(con.execute("SELECT 1 FROM companies WHERE name='Q12345'").fetchone())

    def test_osm_tags(self):
        def fake_overpass(q, log):
            return {"elements": [{"center": {"lat": 50.9, "lon": 6.9}, "tags": {"name": "Choc Laden", "phone": "+49 221 777888", "addr:street": "Hauptstr.",
                                                                                 "addr:housenumber": "5", "addr:postcode": "50667", "addr:city": "Köln",
                                                                                 "contact:instagram": "https://instagram.com/chocladen", "website": "https://chocladen.de"}}]}
        old = leads.overpass
        leads.overpass = fake_overpass
        try:
            leads.cmd_harvest_osm(argparse.Namespace(country="DE", segments="retail_craft"))
        finally:
            leads.overpass = old
        c = leads.db().execute("SELECT * FROM companies WHERE domain='chocladen.de'").fetchone()
        self.assertEqual((c["phone"], c["address"], c["lat"]), ("+49221777888", "Hauptstr. 5, 50667 Köln", 50.9))
        self.assertTrue(c["instagram"].endswith("chocladen"))

    def test_names_and_scoring(self):
        con = leads.db()
        cid, _ = leads.upsert_company(con, "Süßwaren Müller GmbH", "DE", None, "https://mueller-suess.de", "other", "test")
        cid2, _ = leads.upsert_company(con, "Мир Шоколада", "RU", None, None, "other", "test")
        con.commit()
        r = con.execute("SELECT name_gloss, name_latin FROM companies WHERE id=?", (cid,)).fetchone()
        self.assertEqual(r["name_gloss"], "Şekerleme Müller Ltd. Şti.")
        self.assertEqual(con.execute("SELECT name_latin FROM companies WHERE id=?", (cid2,)).fetchone()[0], "Mir Shokolada")
        # perakende ve rakip tavanları
        con.execute("UPDATE companies SET buyer_type='retail', categories='{\"chocolate\":5}', cocoa_signal=90 WHERE id=?", (cid,))
        con.execute("UPDATE companies SET buyer_type='competitor' WHERE id=?", (cid2,))
        con.commit()
        imp = leads.market_ranks(con)
        self.assertLessEqual(leads.score_company(con, con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone(), imp), 25)
        self.assertLessEqual(leads.score_company(con, con.execute("SELECT * FROM companies WHERE id=?", (cid2,)).fetchone(), imp), 35)
        con.commit()

    def test_delete_still_blocks(self):
        con = leads.db()
        cid, _ = leads.upsert_company(con, "Silinecek", "DE", None, "https://silinecek.de", "other", "osm")
        con.commit()
        leads.delete_companies(con, [cid])
        self.assertEqual(leads.upsert_company(con, "Silinecek", "DE", None, "https://silinecek.de", "other", "osm"), (None, False))

    def test_quote_sample_task(self):
        con = leads.db()
        cid, _ = leads.upsert_company(con, "Teklif Kek GmbH", "DE", None, "https://teklif-kek.de", "biscuit_bakery", "test")
        con.commit()
        sid = leads.add_deal(con, cid, "sample", "Kakao tozu (alkalize)", tracking="DHL123")
        c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
        self.assertEqual(c["status"], "sample")
        valid = (leads.dt.date.today() + leads.dt.timedelta(days=12)).isoformat()
        qid = leads.add_deal(con, cid, "quote", "Kakao tozu (alkalize)", 20, 8.4, "USD", "FOB", valid)
        c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
        self.assertEqual((c["status"], c["value_usd"]), ("negotiation", 168000))
        self.assertEqual(c["next_followup"], (leads.dt.date.today() + leads.dt.timedelta(days=10)).isoformat())  # bitişten 2 gün önce
        leads.close_deal(con, sid, "won")  # numune beğenildi: durum geri gitmez
        self.assertEqual(con.execute("SELECT status FROM companies WHERE id=?", (cid,)).fetchone()[0], "negotiation")
        leads.close_deal(con, qid, "won")
        self.assertEqual(con.execute("SELECT status FROM companies WHERE id=?", (cid,)).fetchone()[0], "won")
        self.assertEqual(leads.open_deals(con), [])
        tid = leads.add_task(con, "Spec sheet gönder", None, cid)
        self.assertEqual([t["title"] for t in leads.open_tasks(con, cid)], ["Spec sheet gönder"])
        leads.done_task(con, tid)
        self.assertEqual(leads.open_tasks(con, cid), [])
        self.assertIn("Görev tamamlandı", con.execute("SELECT summary FROM activities WHERE company_id=? ORDER BY id DESC", (cid,)).fetchone()[0])

    def test_archive_rules(self):
        con = leads.db()
        shop, _ = leads.upsert_company(con, "Kafe Arşiv", "RU", None, None, "retail_craft", "osm")
        kept, _ = leads.upsert_company(con, "Kanıtlı Dükkan", "RU", None, None, "retail_craft", "osm")
        star, _ = leads.upsert_company(con, "Yıldızlı Dükkan", "RU", None, None, "retail_craft", "osm")
        con.execute("UPDATE companies SET evidence='{\"n\":3,\"ingredients\":[\"en:cocoa-powder\"]}' WHERE id=?", (kept,))
        con.execute("UPDATE companies SET starred=1 WHERE id=?", (star,))
        con.commit()
        self.assertGreaterEqual(dict(leads.archive_candidates(con))["haritadan gelen dükkân/butik (sanayi alıcısı değil)"], 1)
        leads.auto_archive(con)
        arch = {r[0]: r[1] for r in con.execute("SELECT id, archived FROM companies WHERE id IN (?,?,?)", (shop, kept, star))}
        self.assertEqual(arch, {shop: 1, kept: 0, star: 0})

    def test_email_hook_uses_evidence(self):
        con = leads.db()
        cid, _ = leads.upsert_company(con, "Hook Kekse", "DE", None, "https://hook-kekse.de", "biscuit_bakery", "test")
        leads.add_contact(con, cid, email="einkauf@hook-kekse.de", dept="purchasing")
        con.execute("UPDATE companies SET evidence=? WHERE id=?", (json.dumps({"n": 4, "ingredients": ["en:cocoa-powder"], "examples": ["Schoko Taler"]}), cid))
        con.commit()
        _, de = leads.render_email(con, cid, "de", "cold")
        _, en = leads.render_email(con, cid, "en", "cold")
        self.assertIn("Da Hook Kekse in Produkten wie „Schoko Taler“ Kakaopulver verwendet, möchte ich fragen", de)
        self.assertIn("I noticed that Hook Kekse uses cocoa powder in products such as “Schoko Taler”, so I wanted", en)


if __name__ == "__main__":
    unittest.main()
