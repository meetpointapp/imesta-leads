import argparse
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import focus  # noqa: E402
import leads  # noqa: E402

FC = ["RU", "EG", "MA", "AZ"]


class T(unittest.TestCase):
    def setUp(self):
        self._fc, self._site, self._db = leads.focus_countries, leads.products.find_site, leads.DB_PATH
        leads.focus_countries = lambda: list(FC)
        leads.products.find_site = lambda brand, cc: "https://www.edita.com.eg" if brand.startswith("Edita") else None
        leads.DB_PATH = os.path.join(tempfile.mkdtemp(), "f.db")

    def tearDown(self):
        leads.focus_countries, leads.products.find_site, leads.DB_PATH = self._fc, self._site, self._db

    def quiet(self, fn):
        out, sys.stdout = sys.stdout, io.StringIO()
        try:
            return fn()
        finally:
            sys.stdout = out

    def test_seed_only_focus_and_sites_found(self):
        self.quiet(lambda: leads.cmd_seed(argparse.Namespace()))
        con = leads.db()
        ccs = {r[0] for r in con.execute("SELECT DISTINCT country FROM companies")}
        self.assertEqual(ccs, set(FC))  # Almanya'daki Bahlsen vb. eklenmez
        e = con.execute("SELECT * FROM companies WHERE name LIKE 'Edita%'").fetchone()
        self.assertEqual((e["domain"], e["buyer_type"]), ("edita.com.eg", "industrial"))
        self.assertIn("İ", e["offer"])  # İmesta ürün kodlarıyla teklif
        self.assertNotIn("kuvertür", e["offer"])  # İmesta çikolata üretmez
        con.close()

    def test_non_focus_countries_archived(self):
        con = leads.db()
        de, _ = leads.upsert_company(con, "Kekse GmbH", "DE", None, "https://kekse.de", "biscuit_bakery", "test")
        ru, _ = leads.upsert_company(con, "Печенье ООО", "RU", None, "https://pechenye.ru", "biscuit_bakery", "test")
        con.execute("UPDATE companies SET evidence='{\"n\":5}' WHERE id=?", (de,))  # kanıtlı olsa da odak dışı
        con.commit()
        self.assertEqual(dict(leads.archive_candidates(con))["odak pazarlar dışındaki ülkeler"], 1)
        leads.auto_archive(con)
        got = {r[0]: r[1] for r in con.execute("SELECT id, archived FROM companies")}
        self.assertEqual(got, {de: 1, ru: 0})
        # site yurt dışından açılmasa da (İran) hazır listedeki bilinen alıcı arşive gitmez; bilinmeyen gider
        known, _ = leads.upsert_company(con, "Kalleh Dairy", "RU", None, "https://kalleh.com", "dairy_beverage", "seed")
        unknown, _ = leads.upsert_company(con, "Bilinmeyen", "RU", None, "https://bilinmeyen.ru", "dairy_beverage", "osm")
        con.execute("UPDATE companies SET enrich_error='timeout' WHERE id IN (?,?)", (known, unknown))
        con.commit()
        leads.auto_archive(con)
        got = {r[0]: r[1] for r in con.execute("SELECT id, archived FROM companies WHERE id IN (?,?)", (known, unknown))}
        self.assertEqual(got, {known: 0, unknown: 1})
        con.close()

    def test_evidence_does_not_unarchive_other_countries(self):
        con = leads.db()
        de, _ = leads.upsert_company(con, "Ehrmann", "DE", None, "https://ehrmann.de", "dairy_beverage", "test")
        con.execute("UPDATE companies SET archived=1 WHERE id=?", (de,))
        con.commit()
        con.close()
        orig = leads.products.harvest
        ev = {"brand": "Ehrmann", "n": 4, "ingredients": ["en:cocoa-powder"], "examples": ["Пудинг"], "cats": {"dairy": 2},
              "website": "https://ehrmann.de", "segment": "dairy_beverage"}
        leads.products.harvest = lambda ccs, **kw: [("RU", ev)]
        try:
            self.quiet(lambda: leads.cmd_harvest_products(argparse.Namespace(country="RU", pages=1)))
        finally:
            leads.products.harvest = orig
        con = leads.db()
        c = con.execute("SELECT * FROM companies WHERE id=?", (de,)).fetchone()
        self.assertEqual((c["archived"], json.loads(c["evidence"])["markets"]), (1, ["RU"]))  # kanıt eklenir ama arşivde kalır
        con.close()

    def test_email_in_buyer_language(self):
        con = leads.db()
        langs = sorted({f.split("_")[0] for f in os.listdir(os.path.join(leads.HERE, "templates"))})
        for cc, lang, needle in (("RU", "ru", "использует какао-порошок в таких продуктах, как «Шоколадный торт»"),
                                 ("MA", "fr", "utilise de la poudre de cacao dans des produits comme « Gâteau »"),
                                 ("EG", "ar", "تستخدم مسحوق الكاكاو في منتجات مثل «كيك»"),
                                 ("AZ", "tr", "«Tort» gibi ürünlerinde kakao tozu kullandığını gördük")):
            self.assertEqual(focus.email_lang(cc, langs), lang)
            ex = needle.split("«")[1].split("»")[0].strip()
            cid, _ = leads.upsert_company(con, f"Firma {cc}", cc, None, f"https://firma-{cc.lower()}.com", "biscuit_bakery", "test")
            con.execute("UPDATE companies SET evidence=? WHERE id=?", (json.dumps({"n": 3, "ingredients": ["en:cocoa-powder"], "examples": [ex]}), cid))
            con.commit()
            _, text = leads.render_email(con, cid, lang, "cold")
            self.assertIn(needle.replace("«" + ex + "»", "«" + ex + "»"), text)
            self.assertNotIn("{", text)  # tüm yer tutucular doldu
            for tpl in ("followup1", "followup2"):
                self.assertNotIn("{", leads.render_email(con, cid, lang, tpl)[1])
        con.close()

    def test_score_mentions_market_and_fta(self):
        con = leads.db()
        cid, _ = leads.upsert_company(con, "Bisco", "EG", None, "https://bisco.eg", "biscuit_bakery", "test")
        con.commit()
        leads.score_company(con, con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone(), {})
        reasons = json.loads(con.execute("SELECT fit_reasons FROM companies WHERE id=?", (cid,)).fetchone()[0])
        self.assertTrue(any(r.startswith("Odak pazar: Mısır") for r in reasons))
        self.assertTrue(any("serbest ticaret" in r for r in reasons))
        con.close()

    def test_auto_cycle_rotates_countries(self):
        calls = []
        names = ("cmd_seed", "cmd_harvest_products", "cmd_harvest_wikidata", "cmd_harvest_osm", "cmd_enrich", "cmd_score", "cmd_translate", "cmd_cleanup")
        saved = {n: getattr(leads, n) for n in names}
        for n in names:
            setattr(leads, n, lambda a, n=n: calls.append((n, getattr(a, "country", None) or getattr(a, "countries", None))))
        try:
            leads.auto_cycle(lambda m: None)
            first = [c for n, c in calls if n == "cmd_harvest_products"]
            calls.clear()
            leads.auto_cycle(lambda m: None)
            second = [c for n, c in calls if n == "cmd_harvest_products"]
        finally:
            for n, f in saved.items():
                setattr(leads, n, f)
        self.assertEqual(first, ["RU,EG,MA"])
        self.assertEqual(second, ["AZ,RU,EG"])  # sıra döner
        con = leads.db()
        self.assertIn("yeni firma", leads.meta_get(con, "auto_summary"))
        con.close()


if __name__ == "__main__":
    unittest.main()
