import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import geo  # noqa: E402
import leads  # noqa: E402


class T(unittest.TestCase):
    def test_signals(self):
        self.assertEqual(geo.tld_country("https://www.chococam.cm/fr"), "CM")
        self.assertEqual(geo.tld_country("shop.example.co.uk"), "GB")
        self.assertIsNone(geo.tld_country("https://brand.com"))
        self.assertIsNone(geo.tld_country("https://brand.co"))  # .co Kolombiya değil, genel uzantı
        self.assertEqual(geo.phone_country("+237 6 99 12 34 56"), "CM")
        self.assertEqual(geo.phone_country("+212 522 33 44 55"), "MA")
        self.assertIsNone(geo.phone_country("0699 12 34 56"))  # ülke kodu yok
        self.assertEqual(geo.address_country("Rue 1.234, Douala, Cameroun"), "CM")
        self.assertEqual(geo.address_country("Akwa, Douala, CM"), "CM")

    def test_detect(self):
        # Mısır diye kayıtlı, sitesi .com, tek telefon +237, Mısır'ı destekleyen hiçbir şey yok → Kamerun
        self.assertEqual(geo.detect("EG", "https://cocoa-brand.com", [], ["+237 6 99 12 34 56"], None, "20")[0], "CM")
        # .cm alan adı + Kamerun adresi
        self.assertEqual(geo.detect("EG", "https://x.cm", ["info@x.cm"], [], "Douala, Cameroun", "20"), ("CM", "alan adı .cm, adres, e-posta .cm"))
        # Mısır'ı destekleyen kanıt varken tek yabancı telefon ülkeyi değiştirmez (ör. bir tedarikçinin numarası)
        self.assertIsNone(geo.detect("EG", "https://brand.com.eg", [], ["+237 6 99 12 34 56"], None, "20"))
        # Kazakistan ve Rusya +7'yi paylaşır: Kazakistan kaydı +7 numarayla bozulmaz
        self.assertIsNone(geo.detect("KZ", "https://rakhat.kz", [], ["+7 727 123 45 67"], None, "7"))
        # kanıt yoksa değişiklik yok
        self.assertIsNone(geo.detect("RU", "https://brand.com", [], [], None, "7"))

    def test_fix_country_in_db(self):
        orig, leads.DB_PATH = leads.DB_PATH, os.path.join(tempfile.mkdtemp(), "g.db")
        orig_fc, leads.focus_countries = leads.focus_countries, lambda: list(leads.focus.DEFAULT_FOCUS)
        try:
            con = leads.db()
            cid, _ = leads.upsert_company(con, "Choco Cam", "EG", None, "https://chococam.cm", "chocolate_maker", "urun-kaniti")
            ok, _ = leads.upsert_company(con, "Edita", "EG", None, "https://edita.com.eg", "biscuit_bakery", "seed")
            con.execute("UPDATE companies SET phone='+237 233 42 15 00', address='Douala, Cameroun' WHERE id=?", (cid,))
            con.commit()
            leads.cmd_fix_countries()
            got = {r[0]: r[1] for r in con.execute("SELECT id, country FROM companies")}
            self.assertEqual(got, {cid: "CM", ok: "EG"})
            self.assertIn("Mısır → Kamerun", con.execute("SELECT summary FROM activities WHERE company_id=?", (cid,)).fetchone()[0])
            leads.auto_archive(con)  # Kamerun odak pazar değil: listelerden kalkar
            self.assertEqual(con.execute("SELECT archived FROM companies WHERE id=?", (cid,)).fetchone()[0], 1)
            con.close()
        finally:
            leads.DB_PATH, leads.focus_countries = orig, orig_fc


if __name__ == "__main__":
    unittest.main()
