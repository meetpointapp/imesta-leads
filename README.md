# Imesta Food – Ücretsiz Alıcı (Lead) Sistemi

Panjiva / Volza / ImportGenius gibi ücretli gümrük veri servislerinin yerine **sıfır maliyetli** çalışan sistem.
Sadece Python 3 ve SQLite kullanır (kurulum yok, `pip install` yok). Veriler tek dosyada: `leads.db`.

## Mantık: 4 adım

1. **Nereye satacağım?** → Pazar seçimi (UN Comtrade ücretsiz gümrük istatistiği)
2. **Kim alıyor?** → Firma listesi toplama (OSM, fuar listeleri, ImportYeti, dizinler)
3. **Nasıl ulaşırım?** → Site tarama ile e-posta/telefon, puanlama
4. **Takip** → Kayıt, hatırlatma, e-posta şablonları, rapor

## Windows'ta kurulum (5 dakika)

1. Python kurun: https://www.python.org/downloads/ → indir → kurulumda **"Add python.exe to PATH"** kutusunu işaretleyin.
2. Git'i kurun (https://git-scm.com/download/win), sonra cmd'de:
   ```
   git clone https://github.com/meetpointapp/imesta-leads.git
   cd imesta-leads
   ```
   (Git istemezseniz GitHub'da **Code → Download ZIP**.) Güncellemek için klasörde `git pull`; `leads.db` verileriniz git'e girmez, silinmez.
3. `baslat.bat` dosyasına çift tıklayın; tarayıcıda panel açılır. (Komut satırından: `py web.py`. Windows'ta `python3` değil `py` veya `python` yazılır.)

## Derin veri toplama (iletişim bilgileri)

**Firma bul → Seçili ülkelerde bul ve tara** (ya da komut satırında `python3 leads.py enrich`) her firmanın web sitesine girip herkese açık sayfalarını (ana sayfa, iletişim, impressum, ekip, hakkında, ürünler, sitemap) gezer ve şunları kaydeder:

- **E-postalar** (gizlenmiş `[at]` ve Cloudflare şifreli olanlar dahil), departmana göre sınıflandırılır: satın alma, ihracat, satış, yönetim, genel… Üçüncü taraf (ajans/hosting) adresleri alınmaz. Alan adının MX kaydı kontrol edilir.
- **Telefon, WhatsApp, adres** (JSON-LD yapısal veri + Impressum), **sosyal medya** (LinkedIn, Facebook, Instagram, X, YouTube).
- **Kişiler**: Impressum'daki yöneticiler, ekip sayfasındaki satın alma/satış/ihracat sorumluları (ad + görev). Sitede ad.soyad@ kalıbı varsa diğer kişiler için adres **tahmin** edilir ve "tahmin" diye işaretlenir.
- **Firma bilgisi**: vergi/sicil no (VAT, HRB, KvK, SIRET…), çalışan sayısı, kuruluş yılı, açıklama, site dili.
- **Sinyaller**: sitede kakao/çikolata geçme yoğunluğu (0–100), üretici/toptancı/perakende tahmini. Puanlama bunları kullanır; segment "Diğer" ise otomatik düzeltilir.
- **Veri doluluğu** (%0–100) her firmada ve Firma bul sayfasında genel olarak görünür; Firmalar listesinde buna göre sıralanır.

Ek kaynaklar: **Bilinen firmalar (Wikidata)** düğmesi/komutu (`harvest-wikidata`) büyük ve orta ölçekli şirketleri çeker; OpenStreetMap'ten telefon, adres, sosyal hesap ve konum da alınır.
Hedefli e-posta için: Firmalar sayfasında 🎯 *satın alma/ihracat/satış* filtresi, ve **Kişiler** CSV'si (`export-contacts`) toplu posta içindir.

Sınırlar ve etik: robots.txt'e uyulur, siteler yavaş taranır, LinkedIn gibi giriş gerektiren/taramayı yasaklayan platformlardan veri çekilmez. Kişi adları Impressum gibi yasal zorunlulukla yayımlanan sayfalardan gelir; yalnızca B2B satış amacıyla kullanın, bireysel (gmail vb.) adreslere toplu yazmayın.

Testler: `python3 -m unittest discover tests`

## Web arayüzü

```bash
python3 web.py              # http://127.0.0.1:8765
```
Sayfalar:
- **Bugün** – her sabah ilk açılacak ekran: geciken takipler, bugünkü işler, cevap bekleyen sıcak müşteriler, soğuyanlar, yazılacak en iyi firmalar. Her satırda tek tıkla *Mail attım / Aradım / Cevap geldi / 3 gün ertele*; takip tarihi otomatik kurulur (1. mailden sonra 5 gün, 2.'den sonra 7, 3.'den sonra 14, sonra 30).
- **Satış hattı** – kartları sürükle-bırak ile durumlar arasında taşı; fırsat değeri ve soğuyan müşteri uyarısı.
- **Firmalar** – sütun başlığına tıklayarak sıralama, filtre, yıldızlama, sayfalama, **toplu işlem** (silme, durum, segment) ve Excel'e aktarma. Silinen firma, otomatik taramalarda tekrar eklenmez.
- **Firma detayı** – sıradaki adım önerisi, tek tıkla kayıt, kişiler, geçmiş, düzenleme, sil, e-posta taslağı (ülkeye ve gönderilen e-posta sayısına göre dil/şablon önerir).
- **Pazarlar** – ülke sıralaması + her ülke için **Firma bul** düğmesi. **Firma bul** – otomatik firma + e-posta toplama. **Liste yükle** / **Firma ekle**.
- **Yedek:** `leads.db` her gün otomatik olarak `backups/` klasörüne yedeklenir (son 14 gün); toplu/tekli silmeden önce de ek yedek alınır.

- Renkler ve logo: `config.json` → `theme` (`brand`, `accent`, `cream`, `cocoa`, `logo_url`). imestafood.com'a erişemediğim için kakao kahvesi + krem + altın paleti kullandım; kurumsal renk kodlarınızı buraya yazın.
- Ekip içinde paylaşmak için: `WEB_PASSWORD=sifreniz python3 web.py --host 0.0.0.0` (kullanıcı adı: `imesta`). Şifresiz sadece kendi bilgisayarınızda (127.0.0.1) açılır. İnternete açacaksanız HTTPS arkasına (ör. Caddy/nginx) koyun.

## Hızlı başlangıç (komut satırı)

```bash

# 1) config.json'ı doldurun (ad, unvan, e-posta, adres, sertifikalar)
python3 leads.py init

# 2) Hangi ülkeler çok kakao ithal ediyor, Türkiye'den ne kadar alıyor?
python3 leads.py harvest-comtrade          # HS 1801/1803/1804/1805/1806
python3 leads.py markets --hs 1805 --top 30   # kakao tozu

# 3) Firma toplama
python3 leads.py harvest-osm --country DE,NL,GB,AE
python3 leads.py import-csv data/ornek_liste.csv --source "Gulfood 2026"

# 4) E-posta bul, puanla, listele
python3 leads.py enrich --limit 100
python3 leads.py score
python3 leads.py list --with-email --min-score 60

# 5) Mail yaz, kaydet, takip et
python3 leads.py compose 12 --lang de            # metni üretir, siz gönderirsiniz
python3 leads.py log 12 email "ilk teklif gitti"     # 5 gün sonrası için hatırlatma kurar
python3 leads.py due                              # bugün kimi takip etmeliyim?
python3 leads.py log 12 sample "numune gönderildi" --status sample
python3 leads.py report ; python3 leads.py export out.csv   # Excel'de açılır
```

Tüm komutlar: `python3 leads.py --help`. Günlük rutin: `due` → mail/arama → `log`.

## Müşteriyi nereden bulurum? (hepsi ücretsiz)

| Kaynak | Ne verir | Nasıl |
|---|---|---|
| **UN Comtrade** (comtradeapi.un.org) | Hangi ülke ne kadar kakao ithal ediyor, Türkiye'den alıyor mu | `harvest-comtrade` (ücretsiz anahtar alırsanız `COMTRADE_KEY` ortam değişkeni, daha fazla veri) |
| **ITC Trade Map, Eurostat Comext** | Ülke bazlı ürün/ithalat detayı, ek pazar doğrulama | Elle (ücretsiz kayıt) |
| **ImportYeti** (importyeti.com) | ABD'ye kakao ürünü ithal eden firmalar ve tedarikçileri (gümrük konşimento verisi) | "cocoa powder / cocoa butter" arayın, firmaları CSV'ye yazıp `import-csv` |
| **Fuar katılımcı listeleri** | Doğrudan alıcı/üretici, genelde web sitesi + ülke | ISM Köln, ProSweets, Gulfood, Anuga, SIAL, Biofach, Fancy Food, Sweets & Snacks, Chocoa, Salon du Chocolat, FoodEx, Gulfood Manufacturing. Katılımcı listesini kopyala → CSV → `import-csv` |
| **OpenStreetMap** | Çikolatacı/şekerleme/dondurma üreticileri (özellikle küçük-orta) | `harvest-osm` |
| **Dernek üye listeleri** | Sektör odaklı, kaliteli | CAOBISCO, ECA, BDSI (DE), AIDEPI (IT), ICA, NCA, ICCO; ulusal fırıncı/dondurma dernekleri |
| **B2B platformlar** | Hazır alım talepleri (RFQ) | Alibaba RFQ, TradeKey, EC21, Tridge, Europages, Kompass (ücretsiz katman) |
| **Ticaret Bakanlığı / TİM / İhracatçı Birlikleri / Ticaret Müşavirlikleri** | Ücretsiz B2B eşleştirme, alıcı heyeti, fuar desteği (Türkiye devlet teşvikleri) | Ticaret müşavirliğinizden hedef ülke alıcı listesi isteyin |
| **Enterprise Europe Network** (een.ec.europa.eu) | Avrupa'da ücretsiz B2B eşleştirme | Profil açın |
| **LinkedIn** (elle) | Satın alma müdürü adı/unvanı | "Purchasing Manager cocoa" aramaları; ad-soyadı `add`/CSV ile ekleyin |
| **Google dork'ları** | Ürün sayfalarından rakip müşterileri | `"cocoa powder" supplier Germany bakery`, `"Impressum" Schokolade Hersteller` |

**En iyi hedef segmentler (puan sırasıyla):** çikolata üreticisi → şekerleme/bisküvi → hammadde distribütörü → pastane/fırın malzemesi → dondurma → süt/içecek → butik çikolatacı. İlk 3 segment, tonla alım yapan müşteridir.

## Puanlama (0–100)
Segment (5–40) + web sitesi (5) + doğrulanmış e-posta (15) + ülke ithalat sıralaması (maks. 24) + o ülke Türkiye'den zaten alıyorsa (10). Mantığı `cmd_score` içinden değiştirebilirsiniz.

## Kural ve yasal çerçeve
- Soğuk e-posta **B2B + tek satıcıya özel, kısa, abonelikten çıkış satırı olan** olmalı (şablonlarda var). AB'de kurumsal adreslere meşru menfaat dayanağıyla yazılır, bireysel kişilere (gmail vb.) toplu yazmayın.
- Biri "unsubscribe" derse: `python3 leads.py suppress adres@firma.com` — sistem bir daha `compose` etmez, listeye almaz.
- `enrich` robots.txt'e uyar, her istek arası 1–2 sn bekler. Bu aracı sitelerde toplu kazıma (aggressive scraping) için kullanmayın.
- Toplu gönderim için gmail yerine alan adınıza bağlı posta + SPF/DKIM/DMARC ayarlayın; günde 30–50 mail ile başlayın.
- Kişisel veri tutuyorsunuz (ad, e-posta): amacı sadece B2B satış, saklama süresini sınırlayın (ör. 2 yıl).

## Dosyalar
- `leads.py` – tüm sistem · `config.json` – firma bilgileri · `templates/` – EN/DE e-posta (cold, followup1, followup2); yeni dil için `fr_cold.txt` gibi ekleyin
- `data/ornek_liste.csv` – içe aktarma formatı: `name,country,website,segment,city,email,phone,notes`
- `leads.db` – veriler (git'e girmez; **düzenli yedekleyin**)

## Önemli notlar
- `harvest-comtrade` ve `harvest-osm` internet gerektirir; geliştirme ortamında dış erişim kapalı olduğundan bu iki modül gerçek servislerle denenmedi, sahte yanıtla test edildi. İlk çalıştırmada hata verirse çıktıyı paylaşın, düzeltelim.
- E-posta doğrulaması zayıf (sözdizimi + alan adı çözümleme). Kesin doğrulama için ücretsiz katmanı olan bir servis (ör. Hunter/ZeroBounce aylık ücretsiz kredi) eklenebilir.
- Sonraki aşamalar: web arayüzü (Streamlit/Flask), otomatik e-posta dizisi (SMTP), fuar PDF listelerinden otomatik ayıklama.
