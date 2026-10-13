#!/usr/bin/env python3
"""Imesta Food – ücretsiz potansiyel müşteri (lead) sistemi.

Sadece Python standart kütüphanesi + SQLite kullanır; kurulum ve ücret yok.
Kullanım: python3 leads.py --help
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("LEADS_DB", os.path.join(HERE, "leads.db"))
UA = "ImestaFoodBot/1.0 (+https://imestafood.com; B2B supplier research)"

SEGMENTS = {  # segment: (taban puan, e-posta metninde geçen etiket)
    "chocolate_maker": (40, "chocolate manufacturing"),
    "confectionery": (35, "confectionery and biscuits"),
    "distributor": (35, "ingredient distribution"),
    "bakery_ingredient": (30, "bakery and ingredients"),
    "ice_cream": (30, "ice cream and desserts"),
    "dairy_beverage": (25, "dairy and beverages"),
    "retail_craft": (10, "chocolate and confectionery"),
    "other": (5, "the food industry"),
}
STATUSES = ["new", "contacted", "replied", "sample", "negotiation", "won", "lost", "nurture"]
FOLLOWUP_DAYS = {"email": 5, "call": 7, "sample": 10, "meeting": 7, "note": None}

COUNTRIES = {  # ISO2: (Türkçe ad, ISO3)
    "DE": ("Almanya", "DEU"), "NL": ("Hollanda", "NLD"), "BE": ("Belçika", "BEL"), "FR": ("Fransa", "FRA"),
    "GB": ("Birleşik Krallık", "GBR"), "IT": ("İtalya", "ITA"), "ES": ("İspanya", "ESP"), "PL": ("Polonya", "POL"),
    "RU": ("Rusya", "RUS"), "US": ("ABD", "USA"), "CA": ("Kanada", "CAN"), "AE": ("BAE", "ARE"),
    "SA": ("Suudi Arabistan", "SAU"), "EG": ("Mısır", "EGY"), "IQ": ("Irak", "IRQ"), "JO": ("Ürdün", "JOR"),
    "LB": ("Lübnan", "LBN"), "KW": ("Kuveyt", "KWT"), "QA": ("Katar", "QAT"), "OM": ("Umman", "OMN"),
    "MA": ("Fas", "MAR"), "DZ": ("Cezayir", "DZA"), "TN": ("Tunus", "TUN"), "LY": ("Libya", "LBY"),
    "IN": ("Hindistan", "IND"), "CN": ("Çin", "CHN"), "JP": ("Japonya", "JPN"), "KR": ("Güney Kore", "KOR"),
    "MY": ("Malezya", "MYS"), "ID": ("Endonezya", "IDN"), "SG": ("Singapur", "SGP"), "AU": ("Avustralya", "AUS"),
    "NZ": ("Yeni Zelanda", "NZL"), "BR": ("Brezilya", "BRA"), "MX": ("Meksika", "MEX"), "CH": ("İsviçre", "CHE"),
    "AT": ("Avusturya", "AUT"), "SE": ("İsveç", "SWE"), "DK": ("Danimarka", "DNK"), "NO": ("Norveç", "NOR"),
    "FI": ("Finlandiya", "FIN"), "IE": ("İrlanda", "IRL"), "PT": ("Portekiz", "PRT"), "GR": ("Yunanistan", "GRC"),
    "CZ": ("Çekya", "CZE"), "SK": ("Slovakya", "SVK"), "SI": ("Slovenya", "SVN"), "HR": ("Hırvatistan", "HRV"),
    "RS": ("Sırbistan", "SRB"), "RO": ("Romanya", "ROU"), "BG": ("Bulgaristan", "BGR"), "HU": ("Macaristan", "HUN"),
    "LT": ("Litvanya", "LTU"), "LV": ("Letonya", "LVA"), "EE": ("Estonya", "EST"), "UA": ("Ukrayna", "UKR"),
    "KZ": ("Kazakistan", "KAZ"), "AZ": ("Azerbaycan", "AZE"), "GE": ("Gürcistan", "GEO"), "IL": ("İsrail", "ISR"),
    "NG": ("Nijerya", "NGA"), "ZA": ("Güney Afrika", "ZAF"), "KE": ("Kenya", "KEN"), "PK": ("Pakistan", "PAK"),
    "BD": ("Bangladeş", "BGD"), "PH": ("Filipinler", "PHL"), "TH": ("Tayland", "THA"), "VN": ("Vietnam", "VNM"),
}
ISO2_TO_ISO3 = {k: v[1] for k, v in COUNTRIES.items()}

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, country TEXT, city TEXT, website TEXT, domain TEXT,
  segment TEXT DEFAULT 'other', source TEXT, notes TEXT, score INTEGER DEFAULT 0,
  status TEXT DEFAULT 'new', last_contacted TEXT, next_followup TEXT, enriched_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS ux_company_domain ON companies(domain) WHERE domain IS NOT NULL AND domain<>'';
CREATE TABLE IF NOT EXISTS contacts(
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name TEXT, role TEXT, email TEXT, email_ok INTEGER DEFAULT 0, phone TEXT, linkedin TEXT, source TEXT,
  UNIQUE(company_id, email));
CREATE TABLE IF NOT EXISTS activities(
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  ts TEXT DEFAULT CURRENT_TIMESTAMP, kind TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS ignored(key TEXT PRIMARY KEY, name TEXT, deleted_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS suppressed(value TEXT PRIMARY KEY, added_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS trade_flows(
  year INTEGER, hs TEXT, importer_iso3 TEXT, importer TEXT, partner TEXT,  -- partner: WORLD | TUR
  value_usd REAL, qty_kg REAL, PRIMARY KEY(year, hs, importer_iso3, partner));
"""


# ---------------------------------------------------------------- yardımcılar
NEW_COLUMNS = [("value_usd", "REAL"), ("product", "TEXT"), ("lost_reason", "TEXT"),
               ("starred", "INTEGER DEFAULT 0"), ("snoozed_until", "TEXT")]


def migrate(con):
    """Eski veritabanlarına yeni sütunları ekler (veri kaybı olmaz)."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(companies)")}
    for name, typ in NEW_COLUMNS:
        if name not in cols:
            con.execute(f"ALTER TABLE companies ADD COLUMN {name} {typ}")
    con.commit()


def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    migrate(con)
    return con


def backup_db(keep=14, force=False):
    """Günde bir kez backups/ klasörüne tutarlı yedek alır, eskileri siler. Yedek dosya yolunu döner."""
    if not os.path.exists(DB_PATH):
        return None
    folder = os.path.join(os.path.dirname(DB_PATH), "backups")
    os.makedirs(folder, exist_ok=True)
    now = dt.datetime.now()
    path = os.path.join(folder, f"leads-{now:%Y%m%d}" + (f"-{now:%H%M%S}" if force else "") + ".db")
    if os.path.exists(path) and not force:
        return path
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(path)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    for old in sorted(f for f in os.listdir(folder) if f.startswith("leads-") and f.endswith(".db"))[:-keep]:
        os.remove(os.path.join(folder, old))
    return path


def ignore_keys(name, country, domain):
    keys = []
    if domain:
        keys.append("d:" + domain)
    if name:
        keys.append(f"n:{name.strip().lower()}|{(country or '').upper()}")
    return keys


def delete_companies(con, ids):
    """Firmaları (kişi ve geçmişiyle) siler; aynı firma sonraki taramalarda tekrar eklenmesin diye 'ignored'a yazar."""
    n = 0
    for cid in ids:
        r = con.execute("SELECT name,country,domain FROM companies WHERE id=?", (cid,)).fetchone()
        if not r:
            continue
        for k in ignore_keys(r["name"], r["country"], r["domain"]):
            con.execute("INSERT OR IGNORE INTO ignored(key,name) VALUES(?,?)", (k, r["name"]))
        con.execute("DELETE FROM companies WHERE id=?", (cid,))
        n += 1
    con.commit()
    return n


def config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def today():
    return dt.date.today().isoformat()


def get_domain(url):
    if not url:
        return ""
    if "//" not in url:
        url = "http://" + url
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def norm_url(url):
    if not url:
        return ""
    url = url.strip()
    return url if "//" in url else "https://" + url


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JUNK_EMAIL = re.compile(r"(\.(png|jpe?g|gif|svg|webp|css|js)$)|sentry|example\.|wixpress|your-?domain|@2x", re.I)


def check_email(email):
    """Sözdizimi + alan adı çözümleniyor mu (ücretsiz, zayıf ama işe yarar kontrol)."""
    if not EMAIL_RE.fullmatch(email or ""):
        return 0
    try:
        socket.getaddrinfo(email.split("@")[1], None)
        return 1
    except OSError:
        return 0


def is_suppressed(con, company_id=None, email=None, domain=None):
    vals = set()
    if email:
        vals |= {email.lower(), email.split("@")[-1].lower()}
    if domain:
        vals.add(domain.lower())
    if company_id:
        for r in con.execute("SELECT email FROM contacts WHERE company_id=?", (company_id,)):
            if r["email"]:
                vals.add(r["email"].lower())
        r = con.execute("SELECT domain FROM companies WHERE id=?", (company_id,)).fetchone()
        if r and r["domain"]:
            vals.add(r["domain"])
    if not vals:
        return False
    q = ",".join("?" * len(vals))
    return con.execute(f"SELECT 1 FROM suppressed WHERE value IN ({q})", list(vals)).fetchone() is not None


def http_get(url, timeout=20, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def upsert_company(con, name, country=None, city=None, website=None, segment="other",
                   source=None, notes=None, email=None, phone=None, manual=False):
    """Aynı alan adı (veya aynı ad+ülke) varsa tekrar eklemez. (id, yeni_mi) döner.
    Daha önce silinmiş firmalar otomatik kaynaklardan (manual=False) tekrar eklenmez; elle eklemek silinenler listesinden çıkarır."""
    name = (name or "").strip()
    if not name:
        return None, False
    website = norm_url(website)
    domain = get_domain(website)
    country = (country or "").upper() or None
    if segment not in SEGMENTS:
        segment = "other"
    keys = ignore_keys(name, country, domain)
    if keys:
        q = ",".join("?" * len(keys))
        if manual:
            con.execute(f"DELETE FROM ignored WHERE key IN ({q})", keys)
        elif con.execute(f"SELECT 1 FROM ignored WHERE key IN ({q})", keys).fetchone():
            return None, False
    row = None
    if domain:
        row = con.execute("SELECT id FROM companies WHERE domain=?", (domain,)).fetchone()
    if not row:
        row = con.execute("SELECT id FROM companies WHERE lower(name)=lower(?) AND IFNULL(country,'')=IFNULL(?,'')",
                          (name, country)).fetchone()
    if row:
        cid, new = row["id"], False
    else:
        cur = con.execute("INSERT INTO companies(name,country,city,website,domain,segment,source,notes) VALUES(?,?,?,?,?,?,?,?)",
                          (name, country, city, website or None, domain or None, segment, source, notes))
        cid, new = cur.lastrowid, True
    if email or phone:
        add_contact(con, cid, email=email, phone=phone, source=source)
    return cid, new


def add_contact(con, cid, name=None, role=None, email=None, phone=None, linkedin=None, source=None):
    email = (email or "").strip().lower() or None
    if email and is_suppressed(con, email=email):
        return
    con.execute("INSERT OR IGNORE INTO contacts(company_id,name,role,email,email_ok,phone,linkedin,source) VALUES(?,?,?,?,?,?,?,?)",
                (cid, name, role, email, check_email(email) if email else 0, phone, linkedin, source))


# ---------------------------------------------------------------- komutlar
def cmd_init(a):
    db().close()
    print(f"Veritabanı hazır: {DB_PATH}")


def cmd_add(a):
    con = db()
    cid, new = upsert_company(con, a.name, a.country, a.city, a.website, a.segment, a.source or "manual", a.notes, a.email, a.phone)
    con.commit()
    print(("Eklendi" if new else "Zaten vardı") + f": #{cid}")


def import_csv_text(con, text, source, segment=None):
    """CSV metnini içe aktarır; (yeni, tekrar) döner."""
    new = dup = 0
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    for r in csv.DictReader(io.StringIO(text), dialect=dialect):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        cid, is_new = upsert_company(
            con, r.get("name") or r.get("company"), r.get("country"), r.get("city"),
            r.get("website") or r.get("url"), r.get("segment") or segment or "other",
            source, r.get("notes"), r.get("email"), r.get("phone"))
        new += is_new
        dup += (cid is not None and not is_new)
    con.commit()
    return new, dup


def cmd_import_csv(a):
    with open(a.file, newline="", encoding="utf-8-sig") as f:
        new, dup = import_csv_text(db(), f.read(), a.source or os.path.basename(a.file), a.segment)
    print(f"{new} yeni firma, {dup} tekrar (atlandı).")


OSM_FILTERS = {  # segment -> Overpass filtreleri (hafif tutuldu: ülke çapında ağır regex sorgusu zaman aşımına düşer)
    "retail_craft": ['["shop"="chocolate"]', '["craft"="confectionery"]', '["shop"="confectionery"]'],
    "chocolate_maker": ['["craft"="chocolatier"]', '["industrial"="confectionery"]', '["product"="chocolate"]', '["product"="cocoa"]'],
    "bakery_ingredient": ['["shop"="wholesale"]["wholesale"="food"]', '["shop"="pastry"]'],
    "ice_cream": ['["craft"="ice_cream"]', '["shop"="ice_cream"]', '["product"="ice_cream"]'],
}
OVERPASS_URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                 "https://overpass.private.coffee/api/interpreter", "https://overpass.openstreetmap.fr/api/interpreter"]
SEG_LABEL = {"retail_craft": "butik/perakende", "chocolate_maker": "çikolata üreticisi", "ice_cream": "dondurma",
             "bakery_ingredient": "pastane/toptan"}
CANCEL = threading.Event()  # web arayüzündeki "Durdur" düğmesi bunu kurar


def overpass(query, log):
    """Sunucuları sırayla dener; 504/429 (meşgul) ve zaman aşımında bekleyip yedeğe geçer. Çalışan sunucuyu öne alır."""
    body = urllib.parse.urlencode({"data": query}).encode()
    last = "bilinmeyen hata"
    for url in list(OVERPASS_URLS):
        host = url.split("/")[2]
        for attempt in range(2):
            if CANCEL.is_set():
                raise RuntimeError("iptal edildi")
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=240) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
            except Exception as e:
                code = getattr(e, "code", None)
                last = f"{host}: " + (f"sunucu meşgul (HTTP {code})" if code in (429, 502, 503, 504) else str(e))
                wait = 10 * (attempt + 1)
                log(f"    ! {last} – {wait} sn sonra {'tekrar denenecek' if attempt == 0 else 'yedek sunucuya geçilecek'}")
                CANCEL.wait(wait)
                continue
            remark = data.get("remark", "")
            if remark and not data.get("elements"):
                last = f"{host}: {remark}"
                log(f"    ! {last} – yedek sunucuya geçiliyor")
                break  # zaman aşımı/bellek sınırı: yedeğe geç
            OVERPASS_URLS.remove(url)
            OVERPASS_URLS.insert(0, url)  # çalışan sunucuyu bir sonraki sorgu için öne al
            return data
    raise RuntimeError(last)


def cmd_harvest_osm(a):
    """OpenStreetMap'ten (ücretsiz) çikolata/şekerleme/dondurma firmalarını çeker. Ülke başına segment başına 1 sorgu."""
    con = db()
    segs = a.segments.split(",") if a.segments else ["chocolate_maker", "retail_craft", "ice_cream"]
    segs = [s for s in segs if s in OSM_FILTERS] or ["chocolate_maker"]
    log = lambda m: print(m, flush=True)  # noqa: E731
    total = 0
    for cc in [c.strip() for c in a.country.upper().split(",") if re.fullmatch(r"[A-Z]{2}", c.strip())]:
        if CANCEL.is_set():
            log("Durduruldu.")
            break
        log(f"{cc}:")
        n_cc = 0
        for seg in segs:
            if CANCEL.is_set():
                break
            parts = "".join(f"nwr{flt}(area.a);" for flt in OSM_FILTERS[seg])
            q = (f'[out:json][timeout:120][maxsize:268435456];area["ISO3166-1"="{cc}"][admin_level=2]->.a;'
                 f'({parts});out tags center 3000;')
            try:
                data = overpass(q, log)
            except Exception as e:
                log(f"  {SEG_LABEL.get(seg, seg)}: BAŞARISIZ ({e})")
                continue
            els = data.get("elements", [])
            named = [e for e in els if e.get("tags", {}).get("name")]
            n = 0
            for el in named:
                t = el["tags"]
                _, is_new = upsert_company(
                    con, t["name"], cc, t.get("addr:city"), t.get("website") or t.get("contact:website") or t.get("url"),
                    seg, "osm", None, t.get("email") or t.get("contact:email"), t.get("phone") or t.get("contact:phone"))
                n += is_new
            con.commit()
            n_cc += n
            warn = " (3000 sınırına ulaştı, eksik olabilir)" if len(els) >= 3000 else ""
            log(f"  {SEG_LABEL.get(seg, seg)}: {len(els)} kayıt, {len(named)} isimli, {n} yeni{warn}")
            CANCEL.wait(2)
        total += n_cc
        log(f"{cc}: toplam {n_cc} yeni firma")
    log(f"Toplam yeni: {total}")


def comtrade_get(url, key, log):
    """429 (hız sınırı) durumunda bekleyip yeniden dener. Başarısızsa None döner."""
    for attempt in range(5):
        try:
            return json.loads(http_get(url, headers={"Ocp-Apim-Subscription-Key": key} if key else None, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code != 429:
                log(f"    hata: {e}")
                return None
            wait = int(e.headers.get("Retry-After") or 0) or 30 * (attempt + 1)
            log(f"    hız sınırı (429), {wait} sn bekleniyor... ({attempt + 1}/5)")
            time.sleep(min(wait, 120))
        except Exception as e:
            log(f"    hata: {e}")
            return None
    log("    vazgeçildi; birkaç dakika sonra aynı komutu tekrar çalıştırın (çekilenler atlanır).")
    return None


def cmd_harvest_comtrade(a):
    """UN Comtrade (ücretsiz önizleme API'si) ile kakao ithalatçı ülkeleri ve Türkiye'den alım yapanları çeker.
    Zaten çekilmiş (yıl, ürün kodu, kaynak) kombinasyonlarını atlar; eksikleri tamamlamak için tekrar çalıştırın."""
    con = db()
    cfg = config()
    log = lambda m: print(m, flush=True)  # noqa: E731
    year = a.year or cfg["comtrade_year"]
    key = os.environ.get("COMTRADE_KEY")  # isteğe bağlı: ücretsiz anahtar daha yüksek limit verir
    base = ("https://comtradeapi.un.org/data/v1/get/C/A/HS" if key else "https://comtradeapi.un.org/public/v1/preview/C/A/HS")
    pause = 3 if key else 12  # anahtarsız önizleme API'si çok düşük limitli
    done = failed = 0
    for hs in (a.hs.split(",") if a.hs else cfg["hs_codes"]):
        for tag, partner in (("WORLD", "0"), ("TUR", cfg["home_country_code"])):
            if con.execute("SELECT 1 FROM trade_flows WHERE year=? AND hs=? AND partner=? LIMIT 1", (year, hs, tag)).fetchone() and not getattr(a, "force", False):
                log(f"HS {hs} {tag}: zaten var, atlandı")
                continue
            qs = urllib.parse.urlencode({"period": year, "cmdCode": hs, "flowCode": "M", "partnerCode": partner,
                                         "includeDesc": "true", "maxRecords": 500})
            data = comtrade_get(f"{base}?{qs}", key, log)
            if data is None:
                failed += 1
                log(f"HS {hs} {tag}: ÇEKİLEMEDİ")
                continue
            n = 0
            for r in data.get("data", []):
                iso, val = r.get("reporterISO"), r.get("primaryValue")
                if not iso or val is None or iso == "W00":
                    continue
                con.execute("INSERT OR REPLACE INTO trade_flows VALUES(?,?,?,?,?,?,?)",
                            (year, hs, iso, r.get("reporterDesc"), tag, val, r.get("netWgt")))
                n += 1
            con.commit()
            done += 1
            log(f"HS {hs} {tag}: {n} ülke")
            time.sleep(pause)
    log(f"Bitti: {done} çekildi, {failed} başarısız." + (" Başarısızlar için birkaç dakika sonra tekrar çalıştırın." if failed else ""))


def market_rows(con, hs=None, year=None, top=30):
    return con.execute("""
      SELECT w.importer, w.importer_iso3 iso, SUM(w.value_usd) total,
             IFNULL(SUM(t.value_usd),0) from_tr
      FROM trade_flows w LEFT JOIN trade_flows t
        ON t.year=w.year AND t.hs=w.hs AND t.importer_iso3=w.importer_iso3 AND t.partner='TUR'
      WHERE w.partner='WORLD' AND (? IS NULL OR w.year=?) AND (? IS NULL OR w.hs=?)
      GROUP BY w.importer_iso3 ORDER BY total DESC LIMIT ?""", (year, year, hs, hs, top)).fetchall()


def cmd_markets(a):
    rows = market_rows(db(), a.hs, a.year, a.top)
    if not rows:
        print("Veri yok. Önce: python3 leads.py harvest-comtrade")
        return
    print(f"{'#':>3} {'Ülke':<28}{'Toplam ithalat $':>18}{'Türkiye payı %':>16}")
    for i, r in enumerate(rows, 1):
        print(f"{i:>3} {r['importer'][:27]:<28}{r['total']:>18,.0f}{100 * r['from_tr'] / r['total'] if r['total'] else 0:>16.1f}")


def cmd_enrich(a):
    """Firma sitelerinden (iletişim/impressum sayfaları) e-posta toplar; robots.txt'e uyar."""
    con = db()
    rows = con.execute("SELECT id,website FROM companies WHERE website IS NOT NULL AND enriched_at IS NULL "
                       "ORDER BY score DESC LIMIT ?", (a.limit,)).fetchall()
    for r in rows:
        if CANCEL.is_set():
            print("Durduruldu.")
            break
        base = r["website"]
        found = set()
        try:
            rp = urllib.robotparser.RobotFileParser(urllib.parse.urljoin(base, "/robots.txt"))
            rp.read()
            allowed = lambda u: rp.can_fetch(UA, u)  # noqa: E731
        except Exception:
            allowed = lambda u: True  # noqa: E731
        try:
            home = http_get(base, timeout=15) if allowed(base) else ""
        except Exception as e:
            print(f"#{r['id']} {base}: {e}")
            con.execute("UPDATE companies SET enriched_at=? WHERE id=?", (today(), r["id"]))
            continue
        pages = [home]
        links = re.findall(r'href=["\']([^"\']+)["\']', home, re.I)
        extra = [urllib.parse.urljoin(base, l) for l in links
                 if re.search(r"contact|kontakt|impressum|imprint|about|iletisim|contatt|mentions", l, re.I)]
        for u in list(dict.fromkeys(extra))[:3]:
            if allowed(u) and get_domain(u) == get_domain(base):
                try:
                    pages.append(http_get(u, timeout=15))
                except Exception:
                    pass
                time.sleep(1)
        for p in pages:
            for m in EMAIL_RE.findall(p):
                if not JUNK_EMAIL.search(m):
                    found.add(m.lower())
        for e in sorted(found)[:5]:
            add_contact(con, r["id"], email=e, source="web")
        con.execute("UPDATE companies SET enriched_at=? WHERE id=?", (today(), r["id"]))
        print(f"#{r['id']} {get_domain(base)}: {len(found)} e-posta")
        time.sleep(2)
    con.commit()


def cmd_score(a):
    con = db()
    imp = {r["iso"]: (r["rk"], r["from_tr"]) for r in con.execute("""
      SELECT w.importer_iso3 iso, IFNULL(SUM(t.value_usd),0) from_tr,
             (SELECT COUNT(*)+1 FROM (SELECT importer_iso3, SUM(value_usd) v FROM trade_flows WHERE partner='WORLD' GROUP BY 1) x
              WHERE x.v > SUM(w.value_usd)) rk
      FROM trade_flows w LEFT JOIN trade_flows t ON t.year=w.year AND t.hs=w.hs AND t.importer_iso3=w.importer_iso3 AND t.partner='TUR'
      WHERE w.partner='WORLD' GROUP BY w.importer_iso3""")}
    n = 0
    for c in con.execute("SELECT * FROM companies").fetchall():
        s = SEGMENTS.get(c["segment"], SEGMENTS["other"])[0]
        s += 5 if c["website"] else 0
        ok = con.execute("SELECT COUNT(*) FROM contacts WHERE company_id=? AND email_ok=1", (c["id"],)).fetchone()[0]
        s += 15 if ok else 0
        info = imp.get(ISO2_TO_ISO3.get(c["country"] or ""))
        if info:
            s += max(0, 25 - info[0])  # ilk sıradaki ithalatçı ülke 24 puan alır
            s += 10 if info[1] > 0 else 0
        s = min(s, 100)
        con.execute("UPDATE companies SET score=? WHERE id=?", (s, c["id"]))
        n += 1
    con.commit()
    print(f"{n} firma puanlandı.")


def fmt_row(r):
    return f"#{r['id']:<5}{r['score']:>3}  {r['status']:<12}{(r['country'] or '--'):<4}{r['segment']:<18}{r['name'][:38]:<39}{get_domain(r['website']) if r['website'] else ''}"


def cmd_list(a):
    con = db()
    w, p = ["1=1"], []
    for col, val in (("status", a.status), ("country", a.country and a.country.upper()), ("segment", a.segment)):
        if val:
            w.append(f"{col}=?")
            p.append(val)
    if a.min_score:
        w.append("score>=?")
        p.append(a.min_score)
    if a.with_email:
        w.append("id IN (SELECT company_id FROM contacts WHERE email_ok=1)")
    for r in con.execute(f"SELECT * FROM companies WHERE {' AND '.join(w)} ORDER BY score DESC, id LIMIT ?", p + [a.limit]):
        print(fmt_row(r))


def cmd_show(a):
    con = db()
    c = con.execute("SELECT * FROM companies WHERE id=?", (a.id,)).fetchone()
    if not c:
        sys.exit("Bulunamadı")
    print(json.dumps(dict(c), ensure_ascii=False, indent=2))
    print("\nKişiler:")
    for k in con.execute("SELECT * FROM contacts WHERE company_id=?", (a.id,)):
        print(f"  {k['name'] or '-'} | {k['role'] or '-'} | {k['email'] or '-'} {'(geçerli)' if k['email_ok'] else ''} | {k['phone'] or '-'}")
    print("\nGeçmiş:")
    for x in con.execute("SELECT * FROM activities WHERE company_id=? ORDER BY ts", (a.id,)):
        print(f"  {x['ts'][:16]} [{x['kind']}] {x['summary']}")


EMAIL_CADENCE = [5, 7, 14, 30]  # 1., 2., 3., 4.+ e-postadan sonra kaç gün içinde takip
NEXT_TEMPLATE = ["cold", "followup1", "followup2"]  # sıradaki e-posta şablonu (gönderilen e-posta sayısına göre)


def email_count(con, cid):
    return con.execute("SELECT COUNT(*) FROM activities WHERE company_id=? AND kind='email'", (cid,)).fetchone()[0]


def do_log(con, cid, kind, summary, status=None, followup=None):
    """Aktivite kaydeder, takip tarihini ve durumu günceller. Sonraki takip tarihini döner (not kaydı takibi bozmaz)."""
    cur = con.execute("SELECT status,next_followup FROM companies WHERE id=?", (cid,)).fetchone()
    if not cur:
        raise ValueError("Bulunamadı")
    if status and status not in STATUSES:
        raise ValueError("Durumlar: " + ", ".join(STATUSES))
    con.execute("INSERT INTO activities(company_id,kind,summary) VALUES(?,?,?)", (cid, kind, summary))
    days = followup
    if days is None and kind == "email":
        days = EMAIL_CADENCE[min(email_count(con, cid), len(EMAIL_CADENCE)) - 1]  # bu e-posta dahil sayıldı
    elif days is None:
        days = FOLLOWUP_DAYS.get(kind)
    sets, p = [], []
    if days is not None or kind != "note":
        nxt = (dt.date.today() + dt.timedelta(days=days)).isoformat() if days else None
        sets.append("next_followup=?")
        p.append(nxt)
    if kind in ("email", "call", "sample", "meeting"):
        sets.append("last_contacted=?")
        p.append(today())
    status = status or ("contacted" if kind in ("email", "call") and cur[0] == "new" else None)
    if status:
        sets.append("status=?")
        p.append(status)
        if status in ("won", "lost"):
            sets.append("next_followup=NULL")
    if sets:
        con.execute(f"UPDATE companies SET {','.join(sets)}, snoozed_until=NULL WHERE id=?", p + [cid])
    con.commit()
    row = con.execute("SELECT next_followup FROM companies WHERE id=?", (cid,)).fetchone()
    return row[0]


def snooze(con, cid, days=3):
    """Takibi birkaç gün erteler (aktivite kaydı oluşturmaz)."""
    d = (dt.date.today() + dt.timedelta(days=days)).isoformat()
    con.execute("UPDATE companies SET next_followup=?, snoozed_until=? WHERE id=?", (d, d, cid))
    con.commit()
    return d


def cmd_log(a):
    con = db()
    try:
        nxt = do_log(con, a.id, a.kind, a.summary, a.status, a.followup)
    except ValueError as e:
        sys.exit(str(e))
    print(f"Kaydedildi. Sonraki takip: {nxt or '-'}")


def cmd_due(a):
    con = db()
    rows = con.execute("SELECT * FROM companies WHERE next_followup IS NOT NULL AND next_followup<=? "
                       "AND status NOT IN ('won','lost') ORDER BY next_followup", (today(),)).fetchall()
    print(f"Bugün takip edilecek {len(rows)} firma:")
    for r in rows:
        print(f"{r['next_followup']}  {fmt_row(r)}")


def cmd_suppress(a):
    con = db()
    con.execute("INSERT OR IGNORE INTO suppressed(value) VALUES(?)", (a.value.lower(),))
    con.execute("UPDATE companies SET status='lost', next_followup=NULL WHERE domain=? OR id IN "
                "(SELECT company_id FROM contacts WHERE lower(email)=?)", (a.value.lower(), a.value.lower()))
    con.commit()
    print("Engelleme listesine eklendi; bu adrese/alan adına bir daha yazılmaz.")


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def render_email(con, cid, lang="en", template="cold"):
    """(alıcı_e-posta | None, metin) döner; hata durumunda ValueError."""
    c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    if not c:
        raise ValueError("Bulunamadı")
    if is_suppressed(con, company_id=cid):
        raise ValueError("Bu firma engelleme listesinde; yazılmaz.")
    path = os.path.join(HERE, "templates", f"{lang}_{template}.txt")
    if not os.path.exists(path):
        raise ValueError(f"Şablon yok: {lang}_{template}")
    k = con.execute("SELECT * FROM contacts WHERE company_id=? AND email_ok=1 ORDER BY (name IS NULL), id", (cid,)).fetchone()
    ctx = _Safe(config(), company=c["name"], contact=(k["name"] if k and k["name"] else "Sir or Madam" if lang == "en" else "Damen und Herren"),
                segment_label=SEGMENTS.get(c["segment"], SEGMENTS["other"])[1])
    with open(path, encoding="utf-8") as f:
        return (k["email"] if k else None), f.read().format_map(ctx)


def cmd_compose(a):
    try:
        to, text = render_email(db(), a.id, a.lang, a.template)
    except ValueError as e:
        sys.exit(str(e))
    print(f"To: {to or '(geçerli e-posta yok — önce enrich çalıştırın)'}\n")
    print(text)


def cmd_report(a):
    con = db()
    q = lambda s, *p: con.execute(s, p).fetchall()  # noqa: E731
    tot = q("SELECT COUNT(*) FROM companies")[0][0]
    print(f"== Imesta Food lead raporu ({today()}) ==\nToplam firma: {tot}")
    print("\nHuni:")
    for r in q("SELECT status, COUNT(*) n FROM companies GROUP BY status"):
        print(f"  {r['status']:<12}{r['n']:>6}")
    print("\nÜlkeye göre ilk 10:")
    for r in q("SELECT IFNULL(country,'--') c, COUNT(*) n, ROUND(AVG(score)) s FROM companies GROUP BY 1 ORDER BY n DESC LIMIT 10"):
        print(f"  {r['c']:<4}{r['n']:>6}  ort.puan {r['s']:.0f}")
    print("\nKaynağa göre:")
    for r in q("SELECT IFNULL(source,'?') s, COUNT(*) n FROM companies GROUP BY 1 ORDER BY n DESC"):
        print(f"  {r['s']:<28}{r['n']:>6}")
    print("\nGeçerli e-postalı ve henüz yazılmamış en iyi 10 firma:")
    for r in q("SELECT * FROM companies WHERE status='new' AND id IN (SELECT company_id FROM contacts WHERE email_ok=1) "
               "ORDER BY score DESC LIMIT 10"):
        print("  " + fmt_row(r))
    due = q("SELECT COUNT(*) FROM companies WHERE next_followup<=? AND status NOT IN ('won','lost')", today())[0][0]
    print(f"\nTakibi gelmiş: {due}")


def cmd_export(a):
    con = db()
    rows = con.execute("""SELECT c.id,c.name,c.country,c.city,c.website,c.segment,c.score,c.status,c.last_contacted,c.next_followup,
        (SELECT group_concat(email,'; ') FROM contacts k WHERE k.company_id=c.id AND k.email_ok=1) emails,
        (SELECT group_concat(phone,'; ') FROM contacts k WHERE k.company_id=c.id AND k.phone IS NOT NULL) phones
        FROM companies c ORDER BY score DESC""").fetchall()
    with open(a.file, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel Türkçe karakterleri doğru açar
        w = csv.writer(f)
        w.writerow(rows[0].keys() if rows else [])
        w.writerows([tuple(r) for r in rows])
    print(f"{len(rows)} satır → {a.file}")


def main():
    p = argparse.ArgumentParser(description="Imesta Food lead sistemi")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_)
        s.set_defaults(fn=fn)
        return s

    add("init", cmd_init, "veritabanını oluştur")
    s = add("add", cmd_add, "tek firma ekle")
    s.add_argument("name"); s.add_argument("--country"); s.add_argument("--city"); s.add_argument("--website")
    s.add_argument("--segment", default="other", choices=list(SEGMENTS)); s.add_argument("--source")
    s.add_argument("--notes"); s.add_argument("--email"); s.add_argument("--phone")
    s = add("import-csv", cmd_import_csv, "CSV'den toplu içe aktar (fuar listesi, ImportYeti vb.)")
    s.add_argument("file"); s.add_argument("--source"); s.add_argument("--segment")
    s = add("harvest-osm", cmd_harvest_osm, "OpenStreetMap'ten çikolata/şekerleme firmaları çek")
    s.add_argument("--country", required=True, help="ISO2, virgülle: DE,NL,GB"); s.add_argument("--segments")
    s = add("harvest-comtrade", cmd_harvest_comtrade, "UN Comtrade'den ithalatçı ülke verisi çek")
    s.add_argument("--hs"); s.add_argument("--year", type=int); s.add_argument("--force", action="store_true", help="çekilmiş olanları da yeniden çek")
    s = add("markets", cmd_markets, "hedef pazar sıralaması")
    s.add_argument("--hs"); s.add_argument("--year", type=int); s.add_argument("--top", type=int, default=30)
    s = add("enrich", cmd_enrich, "sitelerden e-posta topla")
    s.add_argument("--limit", type=int, default=50)
    add("score", cmd_score, "firmaları puanla")
    s = add("list", cmd_list, "firmaları listele")
    s.add_argument("--status"); s.add_argument("--country"); s.add_argument("--segment")
    s.add_argument("--min-score", type=int); s.add_argument("--with-email", action="store_true")
    s.add_argument("--limit", type=int, default=30)
    s = add("show", cmd_show, "firma detayı"); s.add_argument("id", type=int)
    s = add("log", cmd_log, "görüşme/e-posta kaydı + takip tarihi")
    s.add_argument("id", type=int); s.add_argument("kind", choices=list(FOLLOWUP_DAYS)); s.add_argument("summary")
    s.add_argument("--status", choices=STATUSES); s.add_argument("--followup", type=int, help="kaç gün sonra takip")
    add("due", cmd_due, "bugün takip edilecekler")
    s = add("suppress", cmd_suppress, "e-posta/alan adını engelle (abonelikten çık)"); s.add_argument("value")
    s = add("compose", cmd_compose, "firma için e-posta metni üret")
    s.add_argument("id", type=int); s.add_argument("--lang", default="en"); s.add_argument("--template", default="cold")
    add("report", cmd_report, "özet rapor")
    s = add("export", cmd_export, "CSV (Excel) dışa aktar"); s.add_argument("file")

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
