import argparse
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import leads  # noqa: E402
import products  # noqa: E402

FAKE = {
    "en:cocoa-powder": [
        {"brands": "Keksfabrik Müller", "product_name": "Schoko Kekse", "categories_tags": ["en:snacks", "en:biscuits", "en:chocolate-biscuits"]},
        {"brands": "Keksfabrik Müller", "product_name": "Kakao Waffeln", "categories_tags": ["en:wafers"]},
        {"brands": "Lidl, Favorina", "product_name": "Lebkuchen", "categories_tags": ["en:biscuits"]},
        {"brands": "Milka", "product_name": "Milka Tafel", "categories_tags": ["en:chocolates"]},
        {"brands": "Eisgut", "product_name": "Schoko Eis", "categories_tags": ["en:ice-creams"]},
    ],
    "en:cocoa-butter": [
        {"brands": "Keksfabrik Müller", "product_name": "Schoko Kekse", "categories_tags": ["en:biscuits"]},
        {"brands": "J. D. Gross (Lidl)", "product_name": "Edelbitter", "categories_tags": ["en:chocolates"]},
    ],
}


def fake_getter(url, timeout=0):
    for ing, items in FAKE.items():
        if ing.replace(":", "%3A") in url:
            return {"products": items}
    return {"products": []}


class T(unittest.TestCase):
    def test_exclusions(self):
        for b in ("Lidl", "LINDT SPRUNGLI SAS", "Kinder Bueno", "J. D. Gross (Lidl)", "Société des Produits Nestlé S.A.", "AH Glutenvrij"):
            self.assertTrue(products.excluded(b), b)
        for b in ("Bahlsen", "De Ruijter", "Ehrmann", "Balconi"):
            self.assertFalse(products.excluded(b), b)

    def test_aggregate_and_segment(self):
        agg = products.aggregate(FAKE)
        self.assertEqual(set(agg), {"keksfabrik muller", "eisgut"})
        k = agg["keksfabrik muller"]
        self.assertEqual(k["n"], 2)  # aynı ürün iki içerik sorgusunda gelse de bir kez sayılır
        self.assertEqual(sorted(k["ingredients"]), ["en:cocoa-butter", "en:cocoa-powder"])
        self.assertEqual(products.segment_of(k["cats"]), "biscuit_bakery")
        self.assertEqual(products.segment_of(agg["eisgut"]["cats"]), "ice_cream")
        self.assertIn("2 ürününde kakao tozu ve kakao yağı var", products.evidence_text(k))

    def test_site_matching(self):
        self.assertFalse(products.host_matches("Bjorg", "https://ts.domainname.de/bjorg.de"))
        self.assertTrue(products.host_matches("Schär", "https://www.schaer.com"))
        self.assertTrue(products.host_matches("Bonne Maman", "https://www.bonne-maman.com/"))
        self.assertTrue(products.page_matches("Schär", "https://www.schaer.com/", "<title>Schär – glutenfreie Lebensmittel</title><p>Kekse, Kuchen</p>"))
        self.assertFalse(products.page_matches("Ruf", "https://www.ruf.de/", "<title>ruf Jugendreisen</title><p>Cookie-Einstellungen, Landkreis</p>"))
        self.assertFalse(products.page_matches("Trek", "https://www.trek.com/", "<title>Trek Bikes</title><body>Mountain bikes</body>"))
        hits = []

        def fetcher(url, timeout=0):
            hits.append(url)
            if url == "https://www.keksfabrikmuller.de/":
                return url, "<title>Keksfabrik Müller – Kekse seit 1920</title><script>var x='cocoa'</script><p>Schokolade und Waffeln</p>"
            raise OSError("yok")
        self.assertEqual(products.guess_site("Keksfabrik Müller", "DE", fetcher), "https://www.keksfabrikmuller.de/")

    def test_harvest_and_import(self):
        leads.DB_PATH = os.path.join(tempfile.mkdtemp(), "p.db")
        orig = products.harvest

        def fake_harvest(ccs, **kw):
            return orig(ccs, getter=fake_getter, sleep=lambda s: None, pages=1, log=lambda m: None,
                        site_finder=lambda b, cc: "https://www.keksfabrik-mueller.de" if "Keks" in b else None)
        products.harvest = fake_harvest
        try:
            leads.cmd_harvest_products(argparse.Namespace(country="DE", pages=1))
        finally:
            products.harvest = orig
        con = leads.db()
        rows = con.execute("SELECT * FROM companies").fetchall()
        self.assertEqual([r["name"] for r in rows], ["Keksfabrik Müller"])  # sitesiz tek ürünlü Eisgut alınmaz
        c = rows[0]
        self.assertEqual((c["country"], c["segment"], c["buyer_type"], c["source"]), ("DE", "biscuit_bakery", "industrial", "urun-kaniti"))
        ev = json.loads(c["evidence"])
        self.assertEqual(ev["markets"], ["DE"])
        self.assertIn("kakao tozu", c["offer"])
        leads.score_company(con, c, {})
        c = con.execute("SELECT * FROM companies").fetchone()
        self.assertTrue(json.loads(c["fit_reasons"])[0].startswith("Kanıt:"))
        con.close()


if __name__ == "__main__":
    unittest.main()
