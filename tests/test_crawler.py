import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import crawler  # noqa: E402


def cfhex(email, key=0x2A):
    return f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in email)


HOME = """<html lang="de"><head><title>Köln Kakao GmbH – Kakaoverarbeitung</title>
<meta name="description" content="Hersteller von Keksen und Waffeln seit 1987.">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Köln Kakao GmbH","telephone":"+49 221 123456",
"email":"info@koeln-kakao.de","address":{"@type":"PostalAddress","streetAddress":"Kakaostraße 12","postalCode":"50667","addressLocality":"Köln","addressCountry":"DE"},
"sameAs":["https://www.linkedin.com/company/koeln-kakao","https://www.facebook.com/koelnkakao"],"numberOfEmployees":{"@type":"QuantitativeValue","value":120},"foundingDate":"1987"}</script>
</head><body><nav><a href="/impressum">Impressum</a> <a href="/kontakt">Kontakt</a> <a href="/team">Unser Team</a> <a href="/produkte/kakaopulver">Produkte</a>
<a href="/karriere">Karriere</a> <a href="/datenschutz">Datenschutz</a> <a href="https://agentur.example/">Webdesign</a></nav>
<h1>Wir sind Hersteller von Keksen und Waffeln</h1><p>Unsere Produktion in Köln liefert Kekse, Waffeln und Kuchen mit Kakao und Schokolade an den Handel (Eigenmarke). Kakao, Kakao, Schokolade.</p>
<a href="https://www.instagram.com/koelnkakao/">IG</a><a href="https://www.facebook.com/sharer/sharer.php?u=x">share</a></body></html>"""
IMPRESSUM = f"""<html lang="de"><body><h1>Impressum</h1><p>Köln Kakao GmbH<br>Kakaostraße 12<br>50667 Köln</p>
<p>Geschäftsführer: Hans Müller, Anna Schmidt</p>
<p>Telefon: +49 (0) 221 123456-0<br>Telefax: +49 221 123456-99<br>E-Mail: einkauf [at] koeln-kakao.de</p>
<p>USt-IdNr.: DE 123 456 789<br>Handelsregister: HRB 12345, Amtsgericht Köln</p>
<a href="mailto:vertrieb@koeln-kakao.de?subject=Anfrage">Vertrieb</a><a href="tel:+4922112345678">Call</a>
<a href="https://wa.me/4915112345678">WhatsApp</a><span data-cfemail="{cfhex('export@koeln-kakao.de')}">[email&#160;protected]</span>
<p>Webdesign: kontakt@agentur-xyz.example, Fotos: mail@fotograf.example</p><p>Privat: hans.mueller@gmail.com</p></body></html>"""
TEAM = """<html><body><div><h3>Maria Rossi</h3><p>Purchasing Manager</p></div><div><h3>John Smith</h3><p>Head of Sales</p></div>
<p>Dr. Peter Weber – Managing Director</p><p>Kontakt Telefon: 0221 987654</p><p>maria.rossi@koeln-kakao.de</p></body></html>"""
SHOP = """<html><body><h1>Süßes Lädchen</h1><p>Unser Online Shop: In den Warenkorb, Warenkorb, Checkout. Öffnungszeiten Mo-Fr.</p>
<p>Schokolade und Pralinen. Tel. +49 30 5551234</p></body></html>"""


def fake(pages):
    def f(url, timeout=0):
        u = url.split("?")[0].rstrip("/")
        for k, v in pages.items():
            if u == k.rstrip("/"):
                return url, v
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)
    return f


class T(unittest.TestCase):
    def test_full_site(self):
        base = "https://koeln-kakao.de"
        r = crawler.crawl_site(base, delay=0, fetcher=fake({base: HOME, base + "/impressum": IMPRESSUM, base + "/kontakt": IMPRESSUM,
                                                            base + "/team": TEAM, base + "/produkte/kakaopulver": "<html><body><p>Kakaopulver 10-12% Fett, 25 kg Säcke, Big Bags</p></body></html>"}))
        self.assertTrue(r["ok"])
        em = r["emails"]
        for e, dept in (("einkauf@koeln-kakao.de", "purchasing"), ("vertrieb@koeln-kakao.de", "sales"), ("export@koeln-kakao.de", "export"),
                        ("info@koeln-kakao.de", "info"), ("maria.rossi@koeln-kakao.de", "person")):
            self.assertIn(e, em, e)
            self.assertEqual(em[e]["dept"], dept, e)
        self.assertEqual(em["vertrieb@koeln-kakao.de"]["via"], "mailto")
        self.assertEqual(em["export@koeln-kakao.de"]["via"], "cf")
        self.assertNotIn("kontakt@agentur-xyz.example", em)  # üçüncü taraf
        self.assertNotIn("mail@fotograf.example", em)
        self.assertIn("hans.mueller@gmail.com", em)  # serbest posta kutusu işaretli gelir
        self.assertTrue(em["hans.mueller@gmail.com"]["free"])
        self.assertEqual(em["hans.mueller@gmail.com"]["dept"], "personal")
        digits = set(r["phones"])
        self.assertIn("4922112345678", digits)
        self.assertIn("492211234560", digits)  # (0) temizlendi
        self.assertNotIn("4922112345699", digits)  # fax
        names = {p["name"]: p for p in r["people"]}
        for n in ("Hans Müller", "Anna Schmidt", "Maria Rossi", "John Smith", "Peter Weber"):
            self.assertIn(n, names, n)
        self.assertEqual(names["Maria Rossi"]["dept"], "purchasing")
        self.assertEqual(names["John Smith"]["dept"], "sales")
        self.assertEqual(r["address"], "Kakaostraße 12, 50667 Köln, DE")
        self.assertEqual(r["legal"]["vat"], "DE123456789")
        self.assertTrue(r["legal"]["register"].startswith("HRB 12345"))
        self.assertEqual(r["facts"]["employees"], "120")
        self.assertEqual(r["facts"]["founded"], "1987")
        self.assertEqual(r["socials"]["linkedin"], "https://www.linkedin.com/company/koeln-kakao")
        self.assertEqual(r["socials"]["instagram"], "https://www.instagram.com/koelnkakao")
        self.assertEqual(r["socials"]["facebook"], "https://www.facebook.com/koelnkakao")
        self.assertIn("whatsapp", {p["via"] for p in r["phones"].values()})
        self.assertEqual(r["lang"], "de")
        self.assertGreater(r["cocoa_signal"], 50)
        self.assertEqual(r["business_type"], "manufacturer")
        self.assertEqual(r["analysis"]["buyer"], "industrial")
        self.assertIn("biscuit", r["analysis"]["cats"])
        self.assertIn("Hersteller", r["description"])
        self.assertNotIn("https://koeln-kakao.de/karriere", r["pages"])
        self.assertNotIn("https://koeln-kakao.de/datenschutz", r["pages"])

    def test_retail_and_missing(self):
        base = "https://laedchen.de"
        r = crawler.crawl_site(base, delay=0, fetcher=fake({base: SHOP}))
        self.assertEqual(r["business_type"], "retail")
        self.assertTrue(any(p["digits"].startswith("49305551234") for p in r["phones"].values()))
        r2 = crawler.crawl_site("https://yok.example", delay=0, fetcher=fake({}))
        self.assertFalse(r2["ok"])
        self.assertTrue(r2["errors"])

    def test_robots_block(self):
        base = "https://blocked.de"
        f = fake({base: HOME, base + "/robots.txt": "User-agent: *\nDisallow: /\n"})
        r = crawler.crawl_site(base, delay=0, fetcher=f)
        self.assertFalse(r["ok"])
        self.assertIn("robots", " ".join(r["errors"]))

    def test_buyer_types(self):
        a = crawler.analyze
        self.assertEqual(a("Wir sind Hersteller von Kakaopulver und Kakaobutter. Kakaoverarbeitung. Bean to bar.")["buyer"], "competitor")
        self.assertEqual(a("Online Shop. In den Warenkorb. Warenkorb Checkout. Pralinen Schokolade Geschenkbox. Öffnungszeiten.")["buyer"], "retail")
        self.assertEqual(a("Wholesale distributor of bakery ingredients. Ingredients, ingredients, ingredients. B2B bulk 25 kg pallets. Importer.")["buyer"], "distributor")
        self.assertEqual(a("Ice cream manufacturer. Gelato, frozen dessert, ice cream. Our factory produces for foodservice. We produce.")["buyer"], "industrial")

    def test_guess_emails(self):
        g = crawler.guess_emails([{"name": "Anna Schmidt", "role": "GF"}, {"name": "Jörg Müller", "role": ""}], "firma.de", ["maria.rossi@firma.de"])
        self.assertEqual([x["email"] for x in g], ["anna.schmidt@firma.de", "joerg.mueller@firma.de"])
        self.assertEqual(crawler.guess_emails([{"name": "Anna Schmidt"}], "firma.de", ["info@firma.de"]), [])  # kalıp yoksa tahmin yok

    def test_classify(self):
        self.assertEqual(crawler.classify_email("einkauf@x.de", "x.de")["dept"], "purchasing")
        self.assertEqual(crawler.classify_email("anna@gmail.com", "x.de")["dept"], "personal")
        self.assertTrue(crawler.classify_email("sales@x.co.uk", "www.x.com")["same_domain"])
        self.assertFalse(crawler.classify_email("a@agency.com", "x.de")["same_domain"])


if __name__ == "__main__":
    unittest.main()
