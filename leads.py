#!/usr/bin/env python3
"""Imesta Food – ücretsiz potansiyel müşteri (lead) sistemi.

Sadece Python standart kütüphanesi + SQLite kullanır; kurulum ve ücret yok.
Kullanım: python3 leads.py --help
"""
import argparse
import csv
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
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
sys.path.insert(0, HERE)
import crawler  # noqa: E402
import translate  # noqa: E402
import discover  # noqa: E402
import products  # noqa: E402
import focus  # noqa: E402
import geo  # noqa: E402
import xlsx  # noqa: E402
import secrets_util  # noqa: E402
DB_PATH = os.environ.get("LEADS_DB", os.path.join(HERE, "leads.db"))
UA = "ImestaFoodBot/1.0 (+https://imestafood.com; B2B supplier research)"

SEGMENTS = {  # segment: (taban puan, e-posta metninde geçen etiket)
    "chocolate_maker": (40, "chocolate manufacturing"),
    "confectionery": (35, "confectionery and biscuits"),
    "distributor": (35, "ingredient distribution"),
    "biscuit_bakery": (36, "biscuits, cakes and bakery products"),
    "cereal_snack": (30, "cereals, snacks and spreads"),
    "bakery_ingredient": (30, "bakery and ingredients"),
    "ice_cream": (30, "ice cream and desserts"),
    "dairy_beverage": (25, "dairy and beverages"),
    "retail_craft": (10, "chocolate and confectionery"),
    "other": (5, "the food industry"),
}
STATUSES = ["new", "saved", "contacted", "replied", "sample", "negotiation", "won", "lost", "nurture"]  # saved: CRM'e kaydedildi, henüz yazılmadı
FOLLOWUP_DAYS = {"email": 5, "call": 7, "sample": 10, "meeting": 7, "quote": 5, "note": None}

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
    "CM": ("Kamerun", "CMR"), "CI": ("Fildişi Sahili", "CIV"), "GH": ("Gana", "GHA"), "EC": ("Ekvador", "ECU"), "SN": ("Senegal", "SEN"),
    "TG": ("Togo", "TGO"), "BJ": ("Benin", "BEN"), "NG": ("Nijerya", "NGA"), "ZA": ("Güney Afrika", "ZAF"), "KE": ("Kenya", "KEN"), "PK": ("Pakistan", "PAK"),
    "SY": ("Suriye", "SYR"), "BY": ("Belarus", "BLR"), "IR": ("İran", "IRN"),
    "UZ": ("Özbekistan", "UZB"), "KG": ("Kırgızistan", "KGZ"), "TM": ("Türkmenistan", "TKM"), "TJ": ("Tacikistan", "TJK"), "MN": ("Moğolistan", "MNG"),
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
CREATE TABLE IF NOT EXISTS deals(  -- kind: quote (teklif) | sample (numune); status: open | won | lost
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  kind TEXT DEFAULT 'quote', product TEXT, qty_t REAL, price_kg REAL, currency TEXT DEFAULT 'USD', incoterm TEXT,
  valid_until TEXT, tracking TEXT, status TEXT DEFAULT 'open', note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, closed_at TEXT);
CREATE TABLE IF NOT EXISTS notes(
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  body TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
  title TEXT NOT NULL, due TEXT, done_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


# ---------------------------------------------------------------- yardımcılar
NEW_COLUMNS = [("value_usd", "REAL"), ("product", "TEXT"), ("lost_reason", "TEXT"),
               ("starred", "INTEGER DEFAULT 0"), ("snoozed_until", "TEXT"),
               ("address", "TEXT"), ("phone", "TEXT"), ("linkedin", "TEXT"), ("facebook", "TEXT"), ("instagram", "TEXT"),
               ("twitter", "TEXT"), ("youtube", "TEXT"), ("whatsapp", "TEXT"), ("description", "TEXT"), ("legal_id", "TEXT"),
               ("lang", "TEXT"), ("cocoa_signal", "INTEGER"), ("business_type", "TEXT"), ("employees", "TEXT"), ("founded", "TEXT"),
               ("lat", "REAL"), ("lon", "REAL"), ("data_score", "INTEGER DEFAULT 0"), ("enrich_pages", "INTEGER DEFAULT 0"),
               ("enrich_error", "TEXT"), ("enrich_v", "INTEGER DEFAULT 0"),
               ("buyer_type", "TEXT"), ("categories", "TEXT"), ("b2b_signal", "INTEGER"), ("fit_reasons", "TEXT"), ("name_gloss", "TEXT"),
               ("name_latin", "TEXT"), ("desc_tr", "TEXT"), ("summary_tr", "TEXT"), ("offer", "TEXT"),
               ("evidence", "TEXT"), ("archived", "INTEGER DEFAULT 0"), ("nkey", "TEXT")]
CONTACT_COLUMNS = [("dept", "TEXT"), ("kind", "TEXT"), ("confidence", "INTEGER"), ("source_url", "TEXT")]


def migrate(con):
    """Eski veritabanlarına yeni sütunları ekler (veri kaybı olmaz)."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(companies)")}
    for name, typ in NEW_COLUMNS:
        if name not in cols:
            con.execute(f"ALTER TABLE companies ADD COLUMN {name} {typ}")
    for r in con.execute("SELECT id, name FROM companies WHERE nkey IS NULL").fetchall():  # karşılaştırma anahtarı (bir kez doldurulur)
        con.execute("UPDATE companies SET nkey=? WHERE id=?", (name_key(r[1]), r[0]))
    con.execute("CREATE INDEX IF NOT EXISTS ix_company_nkey ON companies(country, nkey)")
    kcols = {r[1] for r in con.execute("PRAGMA table_info(contacts)")}
    for name, typ in CONTACT_COLUMNS:
        if name not in kcols:
            con.execute(f"ALTER TABLE contacts ADD COLUMN {name} {typ}")
    con.commit()


def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    # WAL: otomatik tarama, web istekleri ve arka planda site ekleme aynı anda okuyup yazabilsin (okuyan yazanı, yazan okuyanı bekletmez)
    if con.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
        con.execute("PRAGMA journal_mode=WAL")
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


def block_companies(con, ids):
    """Engelle: firmayı siler, adını/alan adını engel listesine ve e-posta engeline ekler; otomatik tarama bir daha eklemez."""
    for r in con.execute(f"SELECT domain FROM companies WHERE id IN ({','.join('?' * len(ids))}) AND IFNULL(domain,'')<>''", ids).fetchall():
        con.execute("INSERT OR IGNORE INTO suppressed(value) VALUES(?)", (r[0],))
    return delete_companies(con, ids)


def unblock(con, name):
    """Engeli kaldırır: firma sonraki taramalarda yeniden bulunabilir."""
    for (key,) in con.execute("SELECT key FROM ignored WHERE name=?", (name,)).fetchall():
        if key.startswith("d:"):
            con.execute("DELETE FROM suppressed WHERE value=?", (key[2:],))
    con.execute("DELETE FROM ignored WHERE name=?", (name,))
    con.commit()


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


CONFIG_PATH = os.environ.get("LEADS_CONFIG") or os.path.join(HERE, "config.json")  # sunucuda kod klasörü dışında tutulur


def config():
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else os.path.join(HERE, "config.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_config(updates):
    """config.json'daki alanları günceller (diğer ayarlar ve tema korunur)."""
    cfg = config()
    cfg.update({k: v for k, v in updates.items() if isinstance(v, (str, bool, list))})  # ülke listesi ve aç/kapa ayarları da kaydedilir
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
        f.write("\n")


def focus_countries():
    """Odak pazarlar (Ayarlar'dan değiştirilebilir). Sistem yalnızca bu ülkelerde firma arar ve gösterir."""
    return [c for c in (config().get("focus_countries") or focus.DEFAULT_FOCUS) if c in COUNTRIES]


def upgrade_config():
    """Eski varsayılan metinleri İmesta'nın gerçek bilgileriyle değiştirir (kullanıcının yazdıklarına dokunmaz)."""
    cfg = config()
    real = {"products": "alkalized cocoa powder (İ8, İ9, İ10, İ12, MS10), natural cocoa powder (İ6), deodorized cocoa butter (CB-İ50) and cocoa liquor (CMS-i20, CMS-i60)",
            "certifications": "FSSC 22000, ISO 22000, ISO 9001, HACCP, Halal and Kosher certified",
            "postal_address": "İmesta Food Lojistik Dış Ticaret Ltd. Şti., Şerifali Mah. Şehit Sok. No:50, Ümraniye, İstanbul, Türkiye",
            "website": "https://imestafood.com", "company_name": "İmesta Food"}
    old = {"products": "couverture", "certifications": "düzenleyin", "postal_address": "Şirket adresiniz", "website": "imestafood.com", "company_name": "Imesta Food"}
    upd = {k: v for k, v in real.items() if old[k] in (cfg.get(k) or old[k]) and cfg.get(k) != v}
    if cfg.get("focus_countries") and not cfg.get("focus_v3"):  # yeni eklenen pazarlar (Türk cumhuriyetleri, Moğolistan) kayıtlı listeye bir kez eklenir
        upd["focus_countries"] = cfg["focus_countries"] + [c for c in focus.NEW_IN_V3 if c not in cfg["focus_countries"]]
    if not cfg.get("focus_v3"):
        upd["focus_v3"] = True
    if upd.get("website") and cfg.get("website") not in ("https://imestafood.com", "http://imestafood.com", None, ""):
        upd.pop("website")
    if upd:
        save_config(upd)
    return upd


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


_MAIL_DOMAIN_CACHE = {}


def mail_domain_ok(domain):
    """Alan adı e-posta alabilir mi? Önce MX kaydı (DNS-over-HTTPS, ücretsiz), olmazsa A kaydı. Sonuç önbelleğe alınır."""
    domain = domain.lower().strip(".")
    if domain in _MAIL_DOMAIN_CACHE:
        return _MAIL_DOMAIN_CACHE[domain]
    ok = None
    try:
        req = urllib.request.Request("https://cloudflare-dns.com/dns-query?name=" + urllib.parse.quote(domain) + "&type=MX",
                                     headers={"accept": "application/dns-json", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        if data.get("Status") == 3:  # NXDOMAIN
            ok = False
        elif any(a.get("type") == 15 for a in data.get("Answer", [])):
            ok = True
    except Exception:
        pass
    if ok is None:  # MX yok ya da DoH ulaşılamadı: A kaydı (RFC: örtük MX)
        try:
            socket.getaddrinfo(domain, None)
            ok = True
        except OSError:
            ok = False
    _MAIL_DOMAIN_CACHE[domain] = ok
    return ok


def check_email(email):
    """Sözdizimi + alan adı e-posta alabiliyor mu (MX/A). 1 = geçerli görünüyor."""
    if not EMAIL_RE.fullmatch(email or ""):
        return 0
    return 1 if mail_domain_ok(email.split("@")[1]) else 0


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


LEGAL_WORDS = re.compile(r"\b(ooo|ооо|ao|ао|zao|зао|oao|оао|pao|пао|tov|тов|llc|ltd|limited|inc|jsc|gmbh|sa|sarl|spa|srl|co|company|group|"
                         r"holding|компания|группа|ширкати|şirketi)\b", re.I)


def name_key(name):
    """Karşılaştırma anahtarı: parantez içi, şirket türü ve noktalama atılır ("Rakhat (Рахат)" ve "Rakhat" aynı)."""
    base = re.split(r"[(\[]", name or "")[0]
    return re.sub(r"[\W_]+", "", LEGAL_WORDS.sub(" ", base.lower()))


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
    key = name_key(name)
    if not row and len(key) >= 3:  # aynı firmanın farklı yazımı: "Rakhat (Рахат)" = "Rakhat", "ООО «Конти»" = "Конти"
        row = con.execute("SELECT id FROM companies WHERE IFNULL(country,'')=IFNULL(?,'') AND nkey=?", (country, key)).fetchone()
    if row:
        cid, new = row["id"], False
    else:
        cur = con.execute("INSERT INTO companies(name,country,city,website,domain,segment,source,notes,nkey) VALUES(?,?,?,?,?,?,?,?,?)",
                          (name, country, city, website or None, domain or None, segment, source, notes, key))
        cid, new = cur.lastrowid, True
        con.execute("UPDATE companies SET name_gloss=?, name_latin=? WHERE id=?", (translate.gloss_name(name), translate.translit(name), cid))
    if email or phone:
        add_contact(con, cid, email=email, phone=phone, source=source)
    return cid, new


DIAL = {"SY": "963", "BY": "375", "IR": "98", "UZ": "998", "KG": "996", "TM": "993", "TJ": "992", "MN": "976", "KZ": "7", "DE": "49", "AT": "43", "CH": "41", "NL": "31", "BE": "32", "FR": "33", "GB": "44", "IT": "39", "ES": "34", "PL": "48", "RU": "7",
        "US": "1", "CA": "1", "AE": "971", "SA": "966", "EG": "20", "IQ": "964", "JO": "962", "LB": "961", "KW": "965", "QA": "974", "OM": "968",
        "MA": "212", "DZ": "213", "TN": "216", "LY": "218", "IN": "91", "CN": "86", "JP": "81", "KR": "82", "MY": "60", "ID": "62", "SG": "65",
        "AU": "61", "NZ": "64", "BR": "55", "MX": "52", "SE": "46", "DK": "45", "NO": "47", "FI": "358", "IE": "353", "PT": "351", "GR": "30",
        "CZ": "420", "SK": "421", "SI": "386", "HR": "385", "RS": "381", "RO": "40", "BG": "359", "HU": "36", "LT": "370", "LV": "371",
        "EE": "372", "UA": "380", "KZ": "7", "AZ": "994", "GE": "995", "IL": "972", "NG": "234", "ZA": "27", "KE": "254", "PK": "92",
        "BD": "880", "PH": "63", "TH": "66", "VN": "84", "TR": "90"}


def format_phone(p, country=None):
    """crawler telefon sözlüğünü '+90...' biçimine çevirir; ulusal numaraya ülke kodunu ekler."""
    d = p["digits"]
    if p["intl"]:
        return "+" + d
    cc = DIAL.get((country or "").upper())
    return "+" + cc + d[1:] if cc and d.startswith("0") else d


def norm_phone_text(raw, country=None):
    p = crawler._norm_phone(raw or "")
    return format_phone(p, country) if p else None


FILL_COLS = {"buyer_type", "address", "phone", "linkedin", "facebook", "instagram", "twitter", "youtube", "whatsapp", "description", "legal_id",
             "lang", "employees", "founded", "lat", "lon", "city"}


def fill_company(con, cid, **fields):
    """Sadece boş olan alanları doldurur (elle girilen bilgilerin üzerine yazmaz)."""
    for k, v in fields.items():
        if k in FILL_COLS and v not in (None, ""):
            con.execute(f"UPDATE companies SET {k}=? WHERE id=? AND ({k} IS NULL OR {k}='')", (v, cid))


def add_contact(con, cid, name=None, role=None, email=None, phone=None, linkedin=None, source=None,
                dept=None, kind=None, confidence=None, source_url=None, email_ok=None):
    """Kişi/iletişim kaydı ekler; aynı e-posta, aynı isim ya da aynı telefon varsa yenisini açmaz, boş alanları tamamlar."""
    email = (email or "").strip().lower() or None
    name = (name or "").strip() or None
    if email and is_suppressed(con, email=email):
        return None
    if email and not dept:
        r = con.execute("SELECT domain FROM companies WHERE id=?", (cid,)).fetchone()
        dept = crawler.classify_email(email, (r["domain"] if r else "") or "")["dept"]
    if email:
        row = con.execute("SELECT id FROM contacts WHERE company_id=? AND email=?", (cid, email)).fetchone()
        ok = check_email(email) if email_ok is None else email_ok
    else:
        digits = re.sub(r"\D", "", phone or "")
        row = None
        if name:
            row = con.execute("SELECT id FROM contacts WHERE company_id=? AND lower(name)=lower(?)", (cid, name)).fetchone()
        elif digits:
            for k in con.execute("SELECT id,phone FROM contacts WHERE company_id=? AND phone IS NOT NULL", (cid,)):
                if re.sub(r"\D", "", k["phone"]) == digits:
                    row = k
                    break
        ok = 0
    if row:
        con.execute("UPDATE contacts SET role=COALESCE(NULLIF(role,''),?), phone=COALESCE(NULLIF(phone,''),?), linkedin=COALESCE(NULLIF(linkedin,''),?), "
                    "dept=COALESCE(NULLIF(dept,''),?), kind=COALESCE(NULLIF(kind,''),?), source_url=COALESCE(NULLIF(source_url,''),?), "
                    "confidence=MAX(IFNULL(confidence,0),?) WHERE id=?",
                    (role, phone, linkedin, dept, kind, source_url, confidence or 0, row["id"]))
        return row["id"]
    cur = con.execute("INSERT INTO contacts(company_id,name,role,email,email_ok,phone,linkedin,source,dept,kind,confidence,source_url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (cid, name, role, email, ok, phone, linkedin, source, dept, kind, confidence, source_url))
    return cur.lastrowid


def update_data_score(con, cid):
    """Veri doluluğu 0-100: ne kadar iletişim bilgisi toplandı?"""
    c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    if not c:
        return 0
    ks = con.execute("SELECT * FROM contacts WHERE company_id=?", (cid,)).fetchall()
    s = 15 if c["website"] else 0
    s += 25 if any(k["email_ok"] for k in ks) else 0
    s += 15 if (c["phone"] or any(k["phone"] for k in ks)) else 0
    s += 15 if any(k["name"] for k in ks) else 0
    s += 10 if c["address"] else 0
    s += 10 if (c["linkedin"] or c["facebook"] or c["instagram"] or c["twitter"] or c["youtube"]) else 0
    s += 5 if c["description"] else 0
    s += 5 if c["legal_id"] else 0
    con.execute("UPDATE companies SET data_score=? WHERE id=?", (s, cid))
    return s


CAT_TR = {"biscuit": "bisküvi", "wafer": "gofret", "cake": "kek/pasta", "bakery": "fırın ürünleri", "ice_cream": "dondurma", "dairy": "süt ürünleri",
          "beverage": "içecek", "cereal_snack": "tahıl/atıştırmalık", "spread": "ezme/dolgu", "confectionery": "şekerleme", "chocolate": "çikolata",
          "ingredients": "hammadde/katkı"}
BUYER_TR = {"industrial": "Kakao kullanan üretici", "distributor": "Toptancı / distribütör", "craft": "Küçük / butik üretici", "retail": "Perakende (dükkân)",
            "competitor": "Kakao işleyici (rakip olabilir)", "unknown": "Sınıflanmadı"}


def infer_segment(cats, buyer, current):
    if buyer == "distributor":
        return "distributor"
    top = {k: v for k, v in cats.items() if k in crawler.USER_CATS}
    if not top:
        return current
    best = max(top, key=top.get)
    return {"biscuit": "biscuit_bakery", "wafer": "biscuit_bakery", "cake": "biscuit_bakery", "bakery": "biscuit_bakery", "ice_cream": "ice_cream",
            "dairy": "dairy_beverage", "beverage": "dairy_beverage", "cereal_snack": "cereal_snack", "spread": "cereal_snack",
            "confectionery": "confectionery", "chocolate": "chocolate_maker"}.get(best, current)


def better_name(res, domain):
    """Sitenin JSON-LD adı ya da başlığından firma adı çıkarır (alan adından türetilmiş geçici ad yerine)."""
    n = (res.get("ld_name") or "").strip()
    if not n:
        title = res.get("title") or ""
        parts = [p.strip() for p in re.split(r"\s[|\-–—:·•]\s|\|", title) if p.strip()]
        label = re.sub(r"[^a-z0-9]", "", (domain or "").split(".")[0].lower())
        match = [p for p in parts if label and label[:5] in re.sub(r"[^a-z0-9]", "", p.lower())]
        n = (match or parts[:1] or [""])[0]
    n = re.sub(r"(?i)^(home|startseite|welcome|willkommen|accueil|homepage)\b[\s|:\-–]*", "", n).strip()
    return n[:80] if 2 <= len(n) <= 80 else None


def _emp_int(v):
    m = re.search(r"\d[\d.,]*", str(v or ""))
    return int(re.sub(r"\D", "", m.group(0))) if m else 0


def suggest_offer(buyer, cats, evidence=None):
    """İmesta'nın gerçek ürün kodlarıyla teklif önerisi (İmesta çikolata üretmez; kakao tozu, yağı ve likörü satar)."""
    if buyer == "distributor":
        return "Teklif: 25 kg torbada alkalize İ10 ve doğal İ6 kakao tozu, CB-İ50 kakao yağı; özel marka ve palet bazında fiyat"
    o = []
    if any(k in cats for k in ("ice_cream", "dairy", "beverage")):
        o.append("koyu renkli, iyi çözünen alkalize kakao tozu (İ10 / İ12)")
    if any(k in cats for k in ("biscuit", "wafer", "cake", "bakery")):
        o.append("bisküvi ve kek için alkalize İ8 / İ9, dolgu için İ10 kakao tozu")
    if any(k in cats for k in ("chocolate", "confectionery")):
        o.append("CB-İ50 deodorize kakao yağı ve CMS-i20 / CMS-i60 kakao likörü")
    if any(k in cats for k in ("cereal_snack", "spread")):
        o.append("ezme ve kaplama için İ10 kakao tozu ve CB-İ50 kakao yağı")
    if evidence and "en:cocoa-butter" in evidence.get("ingredients", []) and not any("CB-İ50" in x for x in o):
        o.append("ürünlerinde kullandığı kakao yağı için CB-İ50")
    if evidence and "en:cocoa-powder" in evidence.get("ingredients", []) and not any("kakao tozu" in x for x in o):
        o.append("ürünlerinde kullandığı kakao tozu için alkalize İ10 ya da doğal İ6")
    return ("Teklif: " + "; ".join(o[:3]) + " — TDS, COA ve ücretsiz numuneyle") if o else \
        "Teklif: alkalize İ10 ve doğal İ6 kakao tozu, CB-İ50 kakao yağı — TDS ve ücretsiz numuneyle"


def build_summary(c, cats, buyer):
    parts = [BUYER_TR.get(buyer or "unknown", "Sınıflanmadı")]
    rel = [CAT_TR[k] for k in crawler.USER_CATS if cats.get(k, 0) >= 2 and k in CAT_TR]
    if rel:
        txt = ", ".join(rel[:4])
        parts.append(txt if txt.endswith("ürünleri") else txt + " ürünleri")
    if c["employees"]:
        parts.append(f"~{c['employees']} çalışan")
    if c["founded"]:
        parts.append(f"{c['founded']}'den beri")
    loc = ", ".join(x for x in (c["city"], COUNTRIES.get((c["country"] or "").upper(), ("",))[0]) if x)
    if loc:
        parts.append(loc)
    return " · ".join(parts)


def refresh_derived(con, cid):
    """Ad çevirisi, Türkçe özet ve teklif önerisini günceller."""
    c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    try:
        cats = json.loads(c["categories"] or "{}")
    except ValueError:
        cats = {}
    con.execute("UPDATE companies SET name_gloss=?, name_latin=?, summary_tr=?, offer=? WHERE id=?",
                (translate.gloss_name(c["name"]), translate.translit(c["name"]), build_summary(c, cats, c["buyer_type"]),
                 suggest_offer(c["buyer_type"], cats, load_evidence(c)), cid))


def load_evidence(c):
    try:
        return json.loads(c["evidence"]) if c["evidence"] else None
    except (ValueError, IndexError, KeyError):
        return None


def apply_enrichment(con, cid, res):
    """Tarama sonucunu (crawler.crawl_site) veritabanına yazar. {'emails','phones','people','socials'} sayılarını döner."""
    stats = {"emails": 0, "phones": 0, "people": 0, "socials": 0}
    c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    if not c:
        return stats
    if not res["ok"]:
        con.execute("UPDATE companies SET enriched_at=?, enrich_error=?, enrich_pages=0, enrich_v=2 WHERE id=?",
                    (today(), "; ".join(res["errors"])[:300], cid))
        con.commit()
        return stats
    domain = c["domain"] or get_domain(res["final_url"])
    country = c["country"]
    prio = crawler.DEPT_PRIORITY
    ranked = sorted(res["emails"].items(), key=lambda kv: (prio.get(kv[1]["dept"], 12), kv[0]))[:12]
    for e, m in ranked:
        conf = (90 if m["via"] in ("mailto", "jsonld", "cf") else 75) - (30 if m["free"] else 0)
        add_contact(con, cid, email=e, dept=m["dept"], kind="email", confidence=conf, source_url=m["source_url"], source="web")
    stats["emails"] = len(ranked)
    phones = sorted(res["phones"].values(), key=lambda p: ({"jsonld": 0, "tel": 1, "label": 2, "text": 3, "whatsapp": 4}.get(p["via"], 5), not p["intl"]))
    plist = []
    for p in phones:
        t = format_phone(p, country)
        if t not in plist:
            plist.append(t)
    if plist:
        fill_company(con, cid, phone=plist[0])
        for t in plist[1:3]:
            add_contact(con, cid, phone=t, dept="info", kind="phone", confidence=70, source="web")
    for p in phones:
        if p["via"] == "whatsapp":
            fill_company(con, cid, whatsapp=format_phone(p, country))
    stats["phones"] = len(plist)
    soc = {k: v for k, v in res["socials"].items() if k in ("linkedin", "facebook", "instagram", "twitter", "youtube")}
    fill_company(con, cid, **soc)
    stats["socials"] = len(soc)
    people = res["people"][:10]
    for p in people:
        add_contact(con, cid, name=p["name"], role=p.get("role"), email=p.get("email"), phone=p.get("phone"), dept=p.get("dept") or "management",
                    kind="person", confidence=70, source_url=p.get("source_url"), source="web")
    stats["people"] = len(people)
    # kişi ↔ e-posta eşleştirme (ad.soyad@ gibi) ve kalıptan tahmin
    for g in crawler.guess_emails(people, domain, list(res["emails"]))[:4]:
        if mail_domain_ok(domain):
            add_contact(con, cid, name=g["name"], role=g.get("role"), email=g["email"], dept="person", kind="guess", confidence=35,
                        source="tahmin", email_ok=1)
    for k in con.execute("SELECT id,email FROM contacts WHERE company_id=? AND email IS NOT NULL AND (name IS NULL OR name='')", (cid,)).fetchall():
        loc = re.sub(r"[^a-z.]", "", k["email"].split("@")[0].lower())
        for p in con.execute("SELECT id,name,role FROM contacts WHERE company_id=? AND email IS NULL AND name IS NOT NULL AND kind='person'", (cid,)).fetchall():
            toks = re.sub(r"[^a-zA-Zà-ÿ ]", "", p["name"]).lower().split()
            if len(toks) >= 2 and loc in (f"{toks[0]}.{toks[-1]}", f"{toks[0][0]}.{toks[-1]}", f"{toks[0]}{toks[-1]}"):
                con.execute("UPDATE contacts SET name=?, role=COALESCE(NULLIF(role,''),?) WHERE id=?", (p["name"], p["role"], k["id"]))
                con.execute("DELETE FROM contacts WHERE id=?", (p["id"],))
                break
    legal = res["legal"]
    legal_txt = " · ".join(x for x in (f"VAT {legal['vat']}" if legal.get("vat") else "", legal.get("register", "")) if x)
    fill_company(con, cid, address=res["address"], description=res["description"], legal_id=legal_txt, lang=res["lang"],
                 employees=res["facts"].get("employees"), founded=res["facts"].get("founded"))
    a = res.get("analysis") or {}
    cats = a.get("cats", {})
    buyer = a.get("buyer", "unknown")
    buyer = buyer if buyer != "unknown" else (c["buyer_type"] or "unknown")
    seg = c["segment"]
    if seg in ("other", "retail_craft"):
        seg = infer_segment(cats, buyer, seg)
    name = c["name"]
    if c["source"] == "search":  # aramadan gelen firmanın adı alan adından türetilmişti: sitedeki gerçek adı kullan
        name = better_name(res, domain) or name
    con.execute("UPDATE companies SET name=?, cocoa_signal=?, business_type=?, segment=?, buyer_type=?, categories=?, b2b_signal=?, "
                "enriched_at=?, enrich_pages=?, enrich_error=NULL, enrich_v=2 WHERE id=?",
                (name, res["cocoa_signal"], res["business_type"], seg, buyer, json.dumps(cats, ensure_ascii=False), a.get("b2b", 0),
                 today(), len(res["pages"]), cid))
    fix_country(con, cid)
    refresh_derived(con, cid)
    update_data_score(con, cid)
    con.commit()
    return stats


def fix_country(con, cid):
    """Sitedeki kanıtlara göre (alan adı, telefon kodu, e-posta, adres) ülkeyi düzeltir. (eski, yeni, gerekçe) ya da None döner."""
    c = con.execute("SELECT country, website, domain, address, phone, whatsapp FROM companies WHERE id=?", (cid,)).fetchone()
    if not c:
        return None
    ks = con.execute("SELECT email, phone FROM contacts WHERE company_id=?", (cid,)).fetchall()
    old = (c["country"] or "").upper()
    res = geo.detect(old, c["website"] or c["domain"], [k["email"] for k in ks if k["email"]],
                     [p for p in [c["phone"], c["whatsapp"]] + [k["phone"] for k in ks] if p], c["address"], DIAL.get(old))
    if not res:
        return None
    new, why = res
    con.execute("UPDATE companies SET country=? WHERE id=?", (new, cid))
    con.execute("INSERT INTO activities(company_id,kind,summary) VALUES(?,?,?)",
                (cid, "note", f"Ülke düzeltildi: {COUNTRIES.get(old, (old or '—',))[0]} → {COUNTRIES.get(new, (new,))[0]} ({why})"))
    return old, new, why


def cmd_fix_countries(a=None):
    """Tüm aktif firmalarda ülke kontrolü; odak dışına çıkanlar sonraki arşiv adımında listelerden kalkar."""
    con = db()
    rows = con.execute("SELECT id FROM companies WHERE IFNULL(archived,0)=0 AND (IFNULL(domain,'')<>'' OR IFNULL(phone,'')<>'' "
                       "OR IFNULL(address,'')<>'' OR id IN (SELECT company_id FROM contacts))").fetchall()
    moved = {}
    for r in rows:
        ch = fix_country(con, r["id"])
        if ch:
            moved[ch[1]] = moved.get(ch[1], 0) + 1
    con.commit()
    fc = set(focus_countries())
    out = sum(n for cc, n in moved.items() if cc not in fc)
    print(f"Ülke kontrolü: {len(rows)} firma, {sum(moved.values())} firmanın ülkesi düzeltildi"
          + (f" ({', '.join(f'{COUNTRIES.get(k, (k,))[0]}: {v}' for k, v in sorted(moved.items(), key=lambda x: -x[1])[:8])})" if moved else "")
          + (f"; {out} tanesi odak pazar dışında, arşive kalkacak." if out else "."), flush=True)
    return moved


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
        if cid and r.get("buyer_type") in ("industrial", "distributor", "craft", "retail", "competitor"):
            fill_company(con, cid, buyer_type=r["buyer_type"])
        if cid and r.get("segment") in SEGMENTS:  # başka kaynaktan "Diğer" olarak gelmişse listedeki segmenti al
            con.execute("UPDATE companies SET segment=? WHERE id=? AND segment='other'", (r["segment"], cid))
        if cid and r.get("employees"):
            fill_company(con, cid, employees=r["employees"])
        new += is_new
        dup += (cid is not None and not is_new)
    con.commit()
    return new, dup


def cmd_seed(a):
    """Odak pazarlardaki bilinen kakao kullanıcılarını (data/seed_*.csv) ekler; web sitesi olmayanların sitesini bulup doğrular."""
    fc = set(focus_countries())
    rows = []
    for fn in ("seed_focus.csv", "seed_buyers.csv"):  # odak pazar listesi + eski Avrupa listesi (yalnızca odak ülkelerdekiler)
        with open(os.path.join(HERE, "data", fn), newline="", encoding="utf-8-sig") as f:
            rows += [r for r in csv.DictReader(f) if r["country"] in fc]
    con = db()
    new, dup = import_csv_text(con, "name,country,website,segment,buyer_type,notes\n" + "".join(
        ",".join('"' + (r[k] or "").replace('"', '""') + '"' for k in ("name", "country", "website", "segment", "buyer_type", "notes")) + "\n" for r in rows), "seed")
    todo = con.execute("SELECT id, name, country FROM companies WHERE source='seed' AND IFNULL(website,'')='' AND IFNULL(enrich_v,0)<2").fetchall()
    if todo:
        print(f"{len(todo)} firmanın web sitesi aranıyor (Wikidata + alan adı, gıda sitesi doğrulamalı)…", flush=True)
        with ThreadPoolExecutor(max_workers=8) as ex:
            sites = list(ex.map(lambda r: None if CANCEL.is_set() else products.find_site(re.sub(r"[«»]", "", r["name"]), r["country"]), todo))
        found = 0
        for r, site in zip(todo, sites):
            if site:
                try:
                    con.execute("UPDATE companies SET website=?, domain=? WHERE id=?", (norm_url(site), get_domain(site), r["id"]))
                    found += 1
                except sqlite3.IntegrityError:
                    pass
        print(f"  {found} web sitesi bulundu.", flush=True)
    for r in con.execute("SELECT id FROM companies WHERE source='seed'").fetchall():
        refresh_derived(con, r["id"])
    con.commit()
    print(f"Hazır liste: {new} yeni firma eklendi, {dup} zaten vardı. Sıradaki: siteleri tara (derin tarama) ve puanla.")


def cmd_import_csv(a):
    with open(a.file, newline="", encoding="utf-8-sig") as f:
        new, dup = import_csv_text(db(), f.read(), a.source or os.path.basename(a.file), a.segment)
    print(f"{new} yeni firma, {dup} tekrar (atlandı).")


OSM_FILTERS = {  # segment -> Overpass filtreleri. Varsayılan: kakao KULLANAN sanayi/toptan; perakende dükkânlar (retail_craft) isteğe bağlı.
    "biscuit_bakery": ['["industrial"~"^(bakery|food_industry|food|confectionery|biscuit)"]',
                       '["man_made"="works"]["name"~"biscuit|keks|cookie|wafer|waffel|bakery|baecker|bäcker|biscotti|galleta|ciastk|geb[aä]ck|backwaren|kuchen|gofret|bisk[uü]vi|f[ıi]r[ıi]n",i]'],
    "chocolate_maker": ['["craft"="chocolatier"]', '["industrial"="confectionery"]', '["product"="chocolate"]', '["product"="cocoa"]',
                        '["man_made"="works"]["name"~"chocolate|schokolade|cioccolat|chocolat|confectionery|s[uü]ßwaren|dolciari|[sş]ekerleme|[cç]ikolata",i]'],
    "ice_cream": ['["product"="ice_cream"]', '["man_made"="works"]["name"~"ice ?cream|speiseeis|gelato|helado|glace|dondurma|lody",i]'],
    "dairy_beverage": ['["industrial"="dairy"]', '["man_made"="works"]["name"~"dairy|molkerei|milch|latte|laiterie|l[aá]cteos|zuivel|mleczarnia|beverage|getr[aä]nke|bevande|boissons|i[cç]ecek",i]'],
    # ofis/şirket adlarında ülke çapında metin araması harita sunucusunda zaman aşımına düşüyor: yalnızca toptan satış noktaları
    "distributor": ['["shop"="wholesale"]["name"~"food|ingredient|zutaten|bak|import|trading|gro[ßs]handel|alimentar|g[ıi]da|toptan|ingredienti|hammadde",i]'],
    "retail_craft": ['["shop"="chocolate"]', '["craft"="confectionery"]', '["shop"="confectionery"]'],
    "bakery_ingredient": ['["shop"="wholesale"]["wholesale"="food"]', '["shop"="pastry"]'],
}
OSM_LOCAL = {  # Overpass büyük/küçük harf duyarlılığı Latin dışında güvenilmez: ilk harfler iki türlü yazıldı
    "biscuit_bakery": "[Пп]еченье|[Вв]афел|[Хх]лебозавод|[Хх]лебокомбинат|[Кк]рекер|بسكويت|معجنات|ويفر|بیسکویت|ویفر|کیک|[Pp]eçenye|[Bb]iscuiterie",
    "chocolate_maker": "[Кк]ондитер|[Шш]околад|حلويات|شوكولا|شیرینی|شکلات|[Şş]irniyyat|[Qq]ənnadı|[Şş]okolad|[Cc]hocolaterie|[Cc]onfiserie",
    "ice_cream": "[Мм]орожен|[Хх]ладокомбинат|مثلجات|بوظة|آيس ?كريم|بستنی|[Dd]ondurma|[Gg]lacier",
    "dairy_beverage": "[Мм]олочн|[Мм]олокозавод|[Мм]олкомбинат|ألبان|البان|لبنیات|[Ss]üd |[Ll]aiterie",
    # toptancılar: kakao tozunu fırın, pastane ve küçük üreticilere yeniden satanlar
    "distributor": "[Оо]птов|[Оо]птом|[Сс]ырь|[Ии]нгредиент|[Дд]истриб|[Кк]ондитерск|[Тт]орговый дом|جملة|موزع|مواد|پخش|عمده|بازرگانی|"
                   "[Uu]lgurji|[Тт]оптан|[Tt]opdan|[Gg]rossiste|[Dd]istribut|[Ii]mport",
}
for _seg, _rx in OSM_LOCAL.items():
    OSM_FILTERS[_seg] = OSM_FILTERS[_seg] + ([f'["shop"="wholesale"]["name"~"{_rx}"]',
                                              '["shop"="wholesale"]["wholesale"~"food|confectionery|bakery"]', '["shop"="pastry_supplies"]']
                                             if _seg == "distributor" else
                                             [f'["man_made"="works"]["name"~"{_rx}"]', f'["industrial"]["name"~"{_rx}"]', f'["building"="industrial"]["name"~"{_rx}"]'])
DEFAULT_OSM_SEGMENTS = ["biscuit_bakery", "chocolate_maker", "ice_cream", "dairy_beverage", "distributor"]
OVERPASS_URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                 "https://overpass.private.coffee/api/interpreter", "https://overpass.openstreetmap.fr/api/interpreter"]
SEG_LABEL = {"retail_craft": "butik/perakende", "chocolate_maker": "çikolata üreticisi", "ice_cream": "dondurma",
             "bakery_ingredient": "pastane/toptan", "biscuit_bakery": "bisküvi/kek/fırın sanayi", "dairy_beverage": "süt/içecek",
             "distributor": "hammadde toptancısı", "cereal_snack": "tahıl/atıştırmalık"}
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
    segs = a.segments.split(",") if a.segments else DEFAULT_OSM_SEGMENTS
    segs = [s for s in segs if s in OSM_FILTERS] or ["chocolate_maker"]
    log = lambda m: print(m, flush=True)  # noqa: E731
    total = 0
    for cc in [c.strip() for c in a.country.upper().split(",") if re.fullmatch(r"[A-Z]{2}", c.strip())]:
        if CANCEL.is_set():
            log("Durduruldu.")
            break
        log(f"{cc}:")
        n_cc = fails = 0
        for seg in segs:
            if CANCEL.is_set():
                break
            if fails >= 2:  # çok büyük ülke ya da harita sunucuları meşgul: turu boşa harcama, sonraki turda tekrar denenir
                log(f"  {cc}: harita sunucuları yanıt vermiyor, bu ülkenin kalan sorguları sonraki tura bırakıldı")
                break
            parts = "".join(f"nwr{flt}(area.a);" for flt in OSM_FILTERS[seg])
            q = (f'[out:json][timeout:120][maxsize:268435456];area["ISO3166-1"="{cc}"][admin_level=2]->.a;'
                 f'({parts});out tags center 3000;')
            try:
                data = overpass(q, log)
                fails = 0
            except Exception as e:
                log(f"  {SEG_LABEL.get(seg, seg)}: BAŞARISIZ ({e})")
                fails += 1
                continue
            els = data.get("elements", [])
            named = [e for e in els if e.get("tags", {}).get("name")]
            n = 0
            for el in named:
                t = el["tags"]
                cid, is_new = upsert_company(
                    con, t["name"], cc, t.get("addr:city"), t.get("website") or t.get("contact:website") or t.get("url"),
                    seg, "osm", None, t.get("email") or t.get("contact:email"), None)
                if cid:
                    street = " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x)
                    zipcity = " ".join(x for x in (t.get("addr:postcode"), t.get("addr:city")) if x)
                    ctr = el.get("center") or {}
                    fill_company(con, cid, address=", ".join(x for x in (street, zipcity) if x), city=t.get("addr:city"),
                                 phone=norm_phone_text(t.get("phone") or t.get("contact:phone") or t.get("contact:mobile"), cc),
                                 whatsapp=norm_phone_text(t.get("contact:whatsapp"), cc), description=t.get("description"),
                                 facebook=t.get("contact:facebook") or t.get("facebook"), instagram=t.get("contact:instagram") or t.get("instagram"),
                                 twitter=t.get("contact:twitter") or t.get("twitter"), linkedin=t.get("contact:linkedin"),
                                 lat=el.get("lat") or ctr.get("lat"), lon=el.get("lon") or ctr.get("lon"))
                    update_data_score(con, cid)
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
    """Firma sitelerini derinlemesine tarar (iletişim, impressum, ekip, hakkında sayfaları) ve e-posta, telefon, kişi, sosyal medya,
    adres, vergi/sicil no, çalışan sayısı ve kakao ilgi sinyalini kaydeder. Paralel çalışır, robots.txt'e uyar."""
    con = db()
    workers = max(1, min(int(getattr(a, "workers", 0) or 6), 16))
    pages = int(getattr(a, "pages", 0) or 8)
    force = bool(getattr(a, "force", False))
    where = "website IS NOT NULL AND website<>'' AND IFNULL(archived,0)=0" + ("" if force else " AND IFNULL(enrich_v,0)<2")
    if getattr(a, "ids", None):
        where += f" AND id IN ({','.join(str(int(i)) for i in a.ids)})"
    ccs = [c for c in (getattr(a, "countries", None) or []) if c in COUNTRIES]
    if ccs:
        where += " AND country IN (" + ",".join("'" + c + "'" for c in ccs) + ")"
    rows = con.execute(f"SELECT id,name,website,country FROM companies WHERE {where} ORDER BY score DESC, id LIMIT ?", (a.limit,)).fetchall()
    print(f"{len(rows)} firma taranacak ({workers} paralel, firma başına en fazla {pages} sayfa)…", flush=True)
    tot = {"emails": 0, "phones": 0, "people": 0, "socials": 0, "ok": 0, "fail": 0}
    imp = market_ranks(con)

    def work(r):
        try:
            return r, crawler.crawl_site(r["website"], max_pages=pages, delay=1.0, cancel=CANCEL)
        except Exception as e:  # tarayıcıdaki beklenmedik hata tek firmayı etkilesin
            return r, {"ok": False, "errors": [str(e)], "final_url": ""}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, r) for r in rows]
        for fut in as_completed(futs):
            if CANCEL.is_set():
                for f in futs:
                    f.cancel()
                print("Durduruldu.", flush=True)
                break
            r, res = fut.result()
            st = apply_enrichment(con, r["id"], res)
            score_company(con, con.execute("SELECT * FROM companies WHERE id=?", (r["id"],)).fetchone(), imp)
            con.commit()
            done += 1
            if res["ok"]:
                tot["ok"] += 1
                for k in ("emails", "phones", "people", "socials"):
                    tot[k] += st[k]
                print(f"[{done}/{len(rows)}] {get_domain(r['website'])}: {st['emails']} e-posta, {st['phones']} tel, {st['people']} kişi, "
                      f"{st['socials']} sosyal · {BUYER_TR.get((res.get('analysis') or {}).get('buyer', 'unknown'))}", flush=True)
            else:
                tot["fail"] += 1
                print(f"[{done}/{len(rows)}] {get_domain(r['website'])}: ulaşılamadı ({(res['errors'] or ['?'])[0][:90]})", flush=True)
    con.commit()
    print(f"Bitti: {tot['ok']} site tarandı, {tot['fail']} ulaşılamadı → {tot['emails']} e-posta, {tot['phones']} telefon, "
          f"{tot['people']} kişi, {tot['socials']} sosyal hesap.", flush=True)


SEARCH_DAILY_CAP = 60  # günde en çok bu kadar arama (ücretsiz kotalar birkaç günde bitmesin); config: daily_search_cap
REQUERY_DAYS = 90  # bir sorgu bu kadar gün sonra yeniden yapılır (yeni firmalar çıkar)


def search_plan_status(con, countries=None):
    """(yapılan, toplam) — odak ülkelerin arama planında son REQUERY_DAYS günde yapılmış sorgu sayısı."""
    con.execute("CREATE TABLE IF NOT EXISTS discover_queries(query TEXT PRIMARY KEY, country TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP, n INTEGER)")
    plan = discover.build_queries(countries or focus_countries())
    done = {r[0] for r in con.execute("SELECT query FROM discover_queries WHERE ts>=datetime('now', ?)", (f"-{REQUERY_DAYS} day",))}
    return sum(1 for q in plan if discover.query_key(q) in done), len(plan)


def cmd_discover(a):
    """Arama motoru (Serper, Tavily, Brave ya da Google resmî API) ile önce çikolata fabrikaları, sonra toptancılar ve diğer alıcılar için
    yerel dilde, şehir şehir arar. Liste sorgularında çıkan sektör listesi / dernek üye listesi sayfalarını açıp içindeki firma bağlantılarını aday yapar.
    Bir servisin hakkı biterse sıradakine geçer; günlük arama sınırı ücretsiz kotaları aylara yayar."""
    con = db()
    log = lambda m: print(m, flush=True)  # noqa: E731
    provs = discover.providers()
    if not provs:
        log("Arama anahtarı tanımlı değil. Ayarlar sayfasından ücretsiz bir Tavily ya da Serper anahtarı ekleyin.")
        return
    ccs = [c.strip().upper() for c in (a.country or "").split(",") if c.strip().upper() in COUNTRIES]
    segs = [s.strip() for s in (getattr(a, "segments", "") or "").split(",") if s.strip()] or None
    con.execute("CREATE TABLE IF NOT EXISTS discover_queries(query TEXT PRIMARY KEY, country TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP, n INTEGER)")
    done = {r[0] for r in con.execute("SELECT query FROM discover_queries WHERE ts>=datetime('now', ?)", (f"-{REQUERY_DAYS} day",))}
    left = sum(max(0, discover.quota_left(con, p)[0]) for p in provs)
    day = f"search_{today()}"
    used = int(meta_get(con, day, 0) or 0)
    cap = int(config().get("daily_search_cap") or SEARCH_DAILY_CAP)
    todo = [q for q in discover.build_queries(ccs, segs) if discover.query_key(q) not in done]
    todo = todo[:max(0, min(int(getattr(a, "max_queries", 0) or 40), left, cap - used))]
    log(f"{', '.join(provs)}: {len(todo)} sorgu çalıştırılacak (kalan hak ~{left}, bugün {used}/{cap}).")
    total = 0
    for cc, seg, q in todo:
        if CANCEL.is_set():
            log("Durduruldu.")
            break
        prov = next((p for p in provs if discover.quota_left(con, p)[0] > 0), None)
        if not prov:
            log("  Tüm arama servislerinin bu dönemki hakkı doldu; sonraki turda devam edilir.")
            break
        period = discover.quota_left(con, prov)[1]
        base, page, listing = discover.parse_seg(seg)
        try:
            res = discover.search(prov, q, cc, 20 if prov in ("brave", "tavily") else 10, page)
        except urllib.error.HTTPError as e:
            why = ("anahtar geçersiz ya da kredi bitti" if e.code in (400, 401, 402, 403, 432, 433) else
                   "hız sınırı, sonra tekrar denenecek" if e.code == 429 else str(e))
            log(f"  ! {prov} HTTP {e.code}: {why}" + (" → sıradaki servise geçiliyor" if e.code != 429 else ""))
            if e.code != 429:
                discover.exhaust(con, prov, period)
                con.commit()
            continue
        except Exception as e:
            log(f"  ! {e}")
            continue
        discover.use_quota(con, prov, period)
        used += 1
        meta_set(con, day, used)
        n, found = 0, 0
        if listing:  # liste/dernek/sıralama sayfalarını aç, içindeki firma bağlantılarını al
            for r in res[:5]:
                if CANCEL.is_set() or not r.get("url", "").startswith("http"):
                    continue
                try:
                    final, page_html = crawler.fetch(r["url"], timeout=15)
                except Exception:
                    continue
                links = discover.list_links(page_html, final, cc)
                found += len(links)
                for host, name, url in links:
                    cid, is_new = upsert_company(con, name, cc, None, url, base, "liste", notes=f"Kaynak liste: {final[:200]}")
                    n += bool(cid and is_new)
        else:
            cands = discover.candidates(res)
            found = len(cands)
            for host, name, snippet, url in cands:
                cid, is_new = upsert_company(con, name, cc, None, url, base, "search")
                if cid and is_new:
                    fill_company(con, cid, description=snippet)
                    n += 1
        con.execute("INSERT OR REPLACE INTO discover_queries(query,country,n,ts) VALUES(?,?,?,CURRENT_TIMESTAMP)", (discover.query_key((cc, seg, q)), cc, found))
        con.commit()
        total += n
        kind = " [liste]" if listing else f" [sayfa {page}]" if page > 1 else ""
        log(f"  [{cc}] {q}{kind}: {found} site, {n} yeni")
        CANCEL.wait(1.1)  # API nezaketi
    log(f"Arama keşfi bitti: {total} yeni aday firma. Sıradaki adım: derin tarama (alıcı olup olmadığını site belirler).")


def translate_one(con, cid):
    """Tek firmanın site açıklamasını Türkçeye çevirir (elle eklenen firma hemen okunabilsin)."""
    c = con.execute("SELECT description, desc_tr, lang, country FROM companies WHERE id=?", (cid,)).fetchone()
    if not c or not c["description"] or c["desc_tr"]:
        return
    src = (c["lang"] or discover.LANG_OF.get((c["country"] or "").upper(), "en")).lower()
    if src == "tr":
        con.execute("UPDATE companies SET desc_tr=description WHERE id=?", (cid,))
        return
    email = config().get("sender_email", "")
    res, _ = translate.translate_text(con, c["description"], src, email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email or "") else "")
    if res:
        con.execute("UPDATE companies SET desc_tr=? WHERE id=?", (res, cid))


def parse_sites(text):
    """Yapıştırılan metinden web siteleri: satır, boşluk ya da virgülle ayrılmış; tekrarlar atılır."""
    out = []
    for tok in re.split(r"[\s,;]+", text or ""):
        tok = tok.strip().strip("<>()[]\"'")
        if "." in tok and not tok.startswith("@") and "@" not in tok:
            dom = get_domain(norm_url(tok))
            if dom and dom not in [get_domain(u) for u in out]:
                out.append(norm_url(tok))
    return out[:200]


def add_by_website(con, url, country=None, name=None):
    """Kendi bulduğun firma sitesini ekler ve hemen tarar: ad, ülke, e-posta, kişi, telefon, firma tipi, puan, Türkçe gerekçe ve açıklama.
    Site zaten kayıtlıysa yeni kayıt açmaz, yeniden tarar. {'id','new','ok','stats','error'} döner."""
    site = norm_url(url)
    dom = get_domain(site)
    if not dom or "." not in dom:
        raise ValueError(f"Geçerli bir web sitesi değil: {url}")
    chosen = (country or "").upper() or None
    row = con.execute("SELECT id FROM companies WHERE domain=?", (dom,)).fetchone()
    if row:
        cid, new = row["id"], False
        con.execute("UPDATE companies SET archived=0 WHERE id=?", (cid,))
    else:
        cc = chosen or geo.tld_country(dom)
        label = name or re.sub(r"[-_]+", " ", dom.split(".")[0]).title()
        cid, new = upsert_company(con, label, cc, None, site, "other", "manuel", manual=True)
        if not cid:
            raise ValueError(f"Eklenemedi: {url}")
    res = crawler.crawl_site(site, max_pages=12, delay=0.6)
    stats = apply_enrichment(con, cid, res)
    if res["ok"] and new and not name:  # alan adından türetilen geçici ad yerine sitedeki gerçek ad
        real = better_name(res, dom)
        if real:
            con.execute("UPDATE companies SET name=?, nkey=?, name_gloss=?, name_latin=? WHERE id=?",
                        (real, name_key(real), translate.gloss_name(real), translate.translit(real), cid))
    if chosen:  # elle seçilen ülke sitedeki ipuçlarından önce gelir
        con.execute("UPDATE companies SET country=? WHERE id=?", (chosen, cid))
    try:
        translate_one(con, cid)
    except Exception:
        pass
    refresh_derived(con, cid)
    score_company(con, con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone(), market_ranks(con))
    con.commit()
    return {"id": cid, "new": new, "ok": res["ok"], "stats": stats, "error": (res["errors"] or [""])[0][:120] if not res["ok"] else ""}


def cmd_add_sites(a):
    """Komut satırı: py leads.py add-sites firma1.com firma2.ru --country RU"""
    con = db()
    for url in parse_sites(" ".join(a.sites)):
        try:
            r = add_by_website(con, url, a.country)
            c = con.execute("SELECT name, country, score FROM companies WHERE id=?", (r["id"],)).fetchone()
            print(f"{url}: {c['name']} ({c['country'] or '?'}) puan {c['score']}" + ("" if r["ok"] else f" · site açılmadı: {r['error']}"), flush=True)
        except ValueError as e:
            print(f"{url}: {e}", flush=True)


def cmd_translate(a):
    """En uygun firmaların site açıklamalarını Türkçeye çevirir (önbellekli; ücretsiz MyMemory, anahtar varsa Claude/LibreTranslate)."""
    con = db()
    log = lambda m: print(m, flush=True)  # noqa: E731
    email = config().get("sender_email", "")
    email = email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email or "") else ""
    rows = con.execute("SELECT id,description,lang,country FROM companies WHERE IFNULL(archived,0)=0 AND description IS NOT NULL AND description<>'' AND (desc_tr IS NULL OR desc_tr='') "
                       "AND score>=? ORDER BY score DESC LIMIT ?", (int(getattr(a, "min_score", 0) or 40), int(getattr(a, "limit", 0) or 40))).fetchall()
    ok = fail = 0
    for r in rows:
        if CANCEL.is_set():
            break
        src = (r["lang"] or discover.LANG_OF.get((r["country"] or "").upper(), "en")).lower()
        if src == "tr":
            con.execute("UPDATE companies SET desc_tr=description WHERE id=?", (r["id"],))
            continue
        res, info = translate.translate_text(con, r["description"], src, email)
        if res:
            con.execute("UPDATE companies SET desc_tr=? WHERE id=?", (res, r["id"]))
            ok += 1
        else:
            fail += 1
            log(f"  çevrilemedi: {info}")
            if info and "limit" in str(info).lower():
                break
        con.commit()
    con.commit()
    log(f"Çeviri: {ok} açıklama Türkçeye çevrildi" + (f", {fail} başarısız (ücretsiz günlük limit dolmuş olabilir; yarın ya da Ayarlar'dan Claude/LibreTranslate anahtarı ekleyin)" if fail else "."))


WIKIDATA_TERMS = ["chocolate", "confectionery", "cocoa", "candy", "biscuit", "bakery", "ice cream"]


def wikidata_query(terms):
    union = " UNION ".join(
        '{ SERVICE wikibase:mwapi { bd:serviceParam wikibase:api "EntitySearch" . bd:serviceParam wikibase:endpoint "www.wikidata.org" . '
        f'bd:serviceParam mwapi:search "{t}" . bd:serviceParam mwapi:language "en" . ?ind wikibase:apiOutputItem mwapi:item . }} }}' for t in terms)
    return ("SELECT DISTINCT ?c ?cLabel ?site ?cc ?cityLabel ?emp ?inc ?indLabel ?li ?fb ?tw ?ig WHERE { " + union +
            " ?c wdt:P452 ?ind . ?c wdt:P856 ?site . OPTIONAL { ?c wdt:P17 ?country . ?country wdt:P297 ?cc . } OPTIONAL { ?c wdt:P159 ?city . } "
            "OPTIONAL { ?c wdt:P1128 ?emp . } OPTIONAL { ?c wdt:P571 ?inc . } OPTIONAL { ?c wdt:P4264 ?li . } OPTIONAL { ?c wdt:P2013 ?fb . } "
            "OPTIONAL { ?c wdt:P2002 ?tw . } OPTIONAL { ?c wdt:P2003 ?ig . } SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". } } LIMIT 4000")


WD_COUNTRY_QUERY = """SELECT ?c ?cLabel ?site ?indLabel ?emp ?inc ?cityLabel WHERE {
  VALUES ?cc { "%s" } ?country wdt:P297 ?cc . ?c wdt:P17 ?country . ?c wdt:P452 ?ind .
  ?ind rdfs:label ?il . FILTER(LANG(?il) = "en" && REGEX(?il, "%s", "i"))
  OPTIONAL { ?c wdt:P856 ?site . } OPTIONAL { ?c wdt:P1128 ?emp . } OPTIONAL { ?c wdt:P571 ?inc . } OPTIONAL { ?c wdt:P159 ?city . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,ru,fr,ar,fa,az". } } LIMIT 1500"""
WD_INDUSTRY = ["food industry|confection|chocolate|cocoa|biscuit|bak|dairy|ice cream|snack|cereal|sweet|candy", "confection|chocolate|biscuit|dairy|ice cream"]
WD_SKIP = re.compile(r"fast food|seafood|fish|pet food|restaurant|food service|meat|poultry|water|catering|retail|supermarket", re.I)


def wikidata_country(cc, log):
    """Bir ülkenin gıda sanayi firmaları (Wikidata). Büyük ülkelerde zaman aşımında dar sorguyla tekrar dener."""
    for rx in WD_INDUSTRY:
        q = WD_COUNTRY_QUERY % (cc, rx)
        try:
            req = urllib.request.Request("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q),
                                         headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                rows = json.loads(r.read().decode("utf-8", "replace"))["results"]["bindings"]
        except Exception as e:
            log(f"  {cc}: Wikidata yanıt vermedi ({str(e)[:60]}), daha dar sorgu deneniyor")
            continue
        seen = {}
        for b in rows:
            seen.setdefault(b["c"]["value"], b)
        return list(seen.values())
    return []


def cmd_harvest_wikidata(a):
    """Wikidata'dan (ücretsiz, açık veri) çikolata/şekerleme/kakao/bisküvi sektöründeki bilinen firmaları web sitesi, ülke,
    çalışan sayısı, kuruluş yılı ve sosyal hesaplarıyla çeker. Büyük/orta ölçekli alıcıları bulmak için iyi bir kaynaktır."""
    con = db()
    log = lambda m: print(m, flush=True)  # noqa: E731
    only = {c.strip().upper() for c in (getattr(a, "country", "") or "").split(",") if c.strip()}
    if only and only <= set(focus.PROFILE):  # odak pazarlar: ülke ülke gıda sanayi sorgusu
        new = 0
        for cc in sorted(only):
            if CANCEL.is_set():
                break
            rows = [b for b in wikidata_country(cc, log) if not WD_SKIP.search(b.get("indLabel", {}).get("value", ""))]
            v = lambda b, k: b.get(k, {}).get("value")  # noqa: E731
            todo = [b for b in rows if not v(b, "site")]
            with ThreadPoolExecutor(max_workers=8) as ex:
                found = dict(zip([id(b) for b in todo], ex.map(lambda b: products.find_site(v(b, "cLabel"), cc), todo)))
            n = 0
            for b in rows:
                name, site = v(b, "cLabel"), v(b, "site") or found.get(id(b))
                if not name or re.fullmatch(r"Q\d+", name):
                    continue
                ind = (v(b, "indLabel") or "").lower()
                seg = ("chocolate_maker" if re.search("chocolate|cocoa", ind) else "ice_cream" if "ice cream" in ind else "dairy_beverage" if re.search("dairy|beverage", ind)
                       else "biscuit_bakery" if re.search("biscuit|bak", ind) else "confectionery" if re.search("confection|sweet|candy", ind) else "other")
                cid, is_new = upsert_company(con, name, cc, v(b, "cityLabel"), site, seg, "wikidata")
                if not cid:
                    continue
                fill_company(con, cid, city=v(b, "cityLabel"), employees=(v(b, "emp") or "").split(".")[0] or None, founded=(v(b, "inc") or "")[:4] or None)
                update_data_score(con, cid)
                n += is_new
            con.commit()
            new += n
            log(f"  {cc}: Wikidata'da {len(rows)} gıda sanayi firması, {n} yeni")
        log(f"Wikidata: {new} yeni firma.")
        return
    q = wikidata_query(WIKIDATA_TERMS)
    try:
        req = urllib.request.Request("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q),
                                     headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        log(f"Wikidata hatası: {e}")
        return
    new = seen = 0
    for b in data.get("results", {}).get("bindings", []):
        v = lambda k: b.get(k, {}).get("value")  # noqa: E731
        name, site, cc = v("cLabel"), v("site"), (v("cc") or "").upper() or None
        if not name or not site or re.fullmatch(r"Q\d+", name) or (only and cc not in only):
            continue
        ind = (v("indLabel") or "").lower()
        seg = ("chocolate_maker" if re.search("chocolate|cocoa", ind) else "confectionery" if re.search("confection|candy|sweet|biscuit|cookie", ind)
               else "ice_cream" if "ice" in ind else "bakery_ingredient" if "bakery" in ind else "other")
        cid, is_new = upsert_company(con, name, cc, v("cityLabel"), site, seg, "wikidata")
        if not cid:
            continue
        seen += 1
        new += is_new
        fill_company(con, cid, city=v("cityLabel"), employees=(v("emp") or "").split(".")[0] or None, founded=(v("inc") or "")[:4] or None,
                     linkedin=f"https://www.linkedin.com/company/{v('li')}" if v("li") else None,
                     facebook=f"https://www.facebook.com/{v('fb')}" if v("fb") else None,
                     twitter=f"https://twitter.com/{v('tw')}" if v("tw") else None,
                     instagram=f"https://www.instagram.com/{v('ig')}" if v("ig") else None)
        update_data_score(con, cid)
    con.commit()
    log(f"Wikidata: {seen} firma işlendi, {new} yeni eklendi. Sıradaki adım: Firma bul → Derin tarama (e-posta, telefon, kişi).")


def cmd_harvest_products(a):
    """Kanıtlı alıcılar: ürün etiketinde kakao tozu/kakao yağı geçen markalar (OpenFoodFacts). Market markaları ve dev gruplar elenir."""
    con = db()
    log = lambda m: print(m, flush=True)  # noqa: E731
    ccs = [c.strip().upper() for c in (getattr(a, "country", "") or "").split(",") if c.strip().upper() in COUNTRIES]
    if not ccs:
        log("Ülke seçilmedi.")
        return
    found = products.harvest(ccs, log=log, cancel=CANCEL, pages=int(getattr(a, "pages", 0) or 8))
    new = upd = 0
    for cc, e in found:
        site = e.get("website")
        if not site and e["n"] < 2:  # sitesi bulunamayan tek ürünlü markalar işe yaramaz
            continue
        dom = get_domain(site) if site else ""
        country = geo.tld_country(dom) or cc  # Mısır'da satılan bir marka Kamerunlu olabilir: sitesinin uzantısı ülkeyi söyler
        cid, is_new = upsert_company(con, e["brand"], country, None, site, e["segment"], "urun-kaniti",
                                     notes="Ürün etiketinde kakao: " + products.evidence_text(e))
        if not cid:
            continue
        c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
        if site and not c["website"]:  # daha önce sitesiz eklenmişse şimdi bulunan siteyi yaz
            try:
                con.execute("UPDATE companies SET website=?, domain=? WHERE id=?", (norm_url(site), dom or None, cid))
            except sqlite3.IntegrityError:
                pass
        old = load_evidence(c) or {}
        ev = {"n": max(e["n"], old.get("n", 0)), "ingredients": sorted(set(e["ingredients"]) | set(old.get("ingredients", []))),
              "examples": (old.get("examples", []) + [x for x in e["examples"] if x not in old.get("examples", [])])[:4],
              "markets": sorted(set(old.get("markets", [])) | {cc}), "brand": e["brand"]}
        try:
            cats = json.loads(c["categories"] or "{}")
        except ValueError:
            cats = {}
        for k, v in e["cats"].items():
            cats[k] = max(cats.get(k, 0), min(v * 2, 10))
        con.execute("UPDATE companies SET evidence=?, categories=?, buyer_type=CASE WHEN IFNULL(buyer_type,'unknown') IN ('unknown','retail','craft') "
                    "THEN 'industrial' ELSE buyer_type END, segment=CASE WHEN segment IN ('other','retail_craft') THEN ? ELSE segment END, "
                    "archived=CASE WHEN ? THEN 0 ELSE archived END WHERE id=?",  # odak dışı firmayı (ör. Almanya'daki marka) geri getirme
                    (json.dumps(ev, ensure_ascii=False), json.dumps(cats), e["segment"], (c["country"] or country) in focus_countries(), cid))
        refresh_derived(con, cid)
        new += is_new
        upd += not is_new
    con.commit()
    log(f"Ürün kanıtı: {new} yeni alıcı eklendi, {upd} mevcut firmaya kanıt eklendi. Sıradaki: derin tarama (iletişim) ve puanlama.")


ARCHIVE_RULES = [  # (açıklama, koşul) — yalnızca henüz temas edilmemiş ('new') firmalar arşivlenir
    ("perakende dükkân / kafe", "buyer_type='retail'"),
    ("kakao işleyici (rakip)", "buyer_type='competitor'"),
    ("haritadan gelen dükkân/butik (sanayi alıcısı değil)", "segment='retail_craft' AND IFNULL(buyer_type,'unknown') NOT IN ('industrial','distributor')"),
    ("gıda firması olmayan site", "enrich_v>=2 AND enrich_error IS NULL AND IFNULL(cocoa_signal,0)<10 AND IFNULL(categories,'{}') IN ('{}','') "
     "AND IFNULL(buyer_type,'unknown') IN ('unknown','retail')"),
    # hazır listedeki bilinen alıcılar korunur: İran gibi ülkelerde siteler yurt dışından açılmayabilir
    ("sitesi açılmayan, iletişimi olmayan", "enrich_error IS NOT NULL AND IFNULL(source,'')<>'seed' AND IFNULL(phone,'')='' AND NOT EXISTS("
     "SELECT 1 FROM contacts k WHERE k.company_id=companies.id AND k.email_ok=1)"),
]
ARCHIVE_BASE = "IFNULL(archived,0)=0 AND status='new' AND IFNULL(starred,0)=0 AND evidence IS NULL AND IFNULL(source,'')<>'manuel'"


def archive_rules():
    """[(açıklama, tam koşul)]. Odak dışı ülkeler kanıtlı olsa da arşive gider; diğer kurallar kanıtlı ve yıldızlıları korur."""
    fc = ",".join(f"'{c}'" for c in focus_countries())
    rules = [("odak pazarlar dışındaki ülkeler", f"IFNULL(archived,0)=0 AND status='new' AND IFNULL(starred,0)=0 AND IFNULL(source,'')<>'manuel' "
                                                f"AND IFNULL(country,'') NOT IN ({fc})")]
    return rules + [(label, f"{ARCHIVE_BASE} AND ({cond})") for label, cond in ARCHIVE_RULES]


def archive_candidates(con):
    """[(açıklama, adet)] — arşive gidecek firmalar (yıldızlılar ve temas edilenler hiç arşivlenmez)."""
    return [(label, con.execute(f"SELECT COUNT(*) FROM companies WHERE {cond}").fetchone()[0]) for label, cond in archive_rules()]


def auto_archive(con):
    """İşe yaramayan firmaları silmeden arşive kaldırır; Firmalar → Arşiv'den geri alınabilir. Arşivlenen sayıyı döner."""
    n = sum(con.execute(f"UPDATE companies SET archived=1 WHERE {cond}").rowcount for _, cond in archive_rules())
    con.commit()
    return n


# ---------------------------------------------------------------- otomatik tarama
def meta_get(con, key, default=None):
    con.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def meta_set(con, key, value):
    con.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    con.commit()


AUTO_BATCH = 2  # her otomatik turda taranan ülke sayısı (sırayla döner; tur bitince kısa aradan sonra sıradakiler)
SOURCE_DAYS = 7  # bir ülkenin kaynakları (ürün, Wikidata, harita) en sık bu kadar günde bir yeniden taranır
NET_CHECK = ["https://search.openfoodfacts.org/search?q=cocoa&page_size=1", "https://www.wikidata.org/w/api.php?action=query&format=json"]


def net_ok():
    """Sunucu dış kaynaklara (açık veri servisleri) ulaşabiliyor mu? (True, '') ya da (False, hata)."""
    err = ""
    for url in NET_CHECK:
        try:
            crawler.fetch(url, timeout=20)
            return True, ""
        except Exception as e:
            err = f"{urllib.parse.urlparse(url).hostname}: {str(e)[:120]}"
    return False, err


def auto_cycle(log=print):
    """Komut beklemeden çalışan tur: sıradaki ülkelerde hazır liste → ürün kanıtı → Wikidata → harita → site taraması → puan → çeviri → arşiv.
    Ülkeler sırayla döner; tur bitince kısa bir aradan sonra sıradaki ülkelerle devam eder. Her adım ekranda canlı görünür."""
    N = argparse.Namespace
    con = db()
    fc = focus_countries()
    i = int(meta_get(con, "auto_next", 0) or 0) % max(len(fc), 1)
    batch = [fc[(i + k) % len(fc)] for k in range(min(AUTO_BATCH, len(fc)))]
    before = con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    names = ", ".join(COUNTRIES[c][0] for c in batch)
    meta_set(con, "auto_started", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    meta_set(con, "auto_now", names)
    meta_set(con, "auto_error", "")
    ok, err = net_ok()
    if not ok:  # en sık sorun: sunucunun dışarıya bağlantısı ya da SSL sertifikaları
        meta_set(con, "auto_error", "Sunucu açık veri servislerine bağlanamıyor: " + err)
        meta_set(con, "auto_step", "")
        meta_set(con, "auto_last", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
        con.close()
        log("Bağlantı yok, tur atlandı: " + err)
        return "Bağlantı yok: " + err
    con.close()
    log(f"Otomatik tarama: {names}")

    def fresh_run(key, fn):
        """Kaynak taramasını ülke başına haftada bir yapar (sürekli turda aynı servisleri boşuna yormamak için)."""
        con = db()
        todo = [c for c in batch if (meta_get(con, f"src_{key}_{c}") or "") < (dt.date.today() - dt.timedelta(days=SOURCE_DAYS)).isoformat()]
        con.close()
        if not todo:
            log(f"  son {SOURCE_DAYS} günde tarandı, atlandı")
            return
        fn(",".join(todo))
        con = db()
        for c in todo:
            meta_set(con, f"src_{key}_{c}", today())
        con.close()

    steps = [("Hazır alıcı listesi", lambda: cmd_seed(N())),
             ("Ürün kanıtı (etiketinde kakao olan markalar)", lambda: fresh_run("off", lambda cc: cmd_harvest_products(N(country=cc, pages=8)))),
             ("Wikidata gıda sanayi firmaları", lambda: fresh_run("wd", lambda cc: cmd_harvest_wikidata(N(country=cc)))),
             ("Harita: fabrikalar (yerel dillerde)", lambda: fresh_run("osm", lambda cc: cmd_harvest_osm(N(country=cc, segments=None)))),
             ("Arama motoru: çikolata fabrikaları, listeler, toptancılar", lambda: cmd_discover(N(country=",".join(batch), segments="", max_queries=40))
              if discover.provider() else log("  anahtar yok, atlandı")),
             ("Site taraması: iletişim, kişiler, firma tipi", lambda: cmd_enrich(N(limit=150, workers=8, pages=8, force=False, countries=fc))),
             ("Puanlama ve çeviri", lambda: (cmd_score(N()), cmd_translate(N(limit=40, min_score=50)))),
             ("Ülke kontrolü (site, telefon kodu, adres)", lambda: cmd_fix_countries(N())),
             ("Alıcı olmayanları arşive kaldırma", lambda: cmd_cleanup(N()))]
    errors = []
    for k, (title, fn) in enumerate(steps, 1):
        if CANCEL.is_set():
            log("Durduruldu.")
            break
        con = db()
        meta_set(con, "auto_step", f"{k}/{len(steps)} {title}")
        con.close()
        log(f"\n=== {title} ===")
        try:
            fn()
        except Exception as e:  # bir adımın hatası turu durdurmasın
            log(f"  ! {e}")
            errors.append(f"{title}: {str(e)[:120]}")
    con = db()
    after = con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    good = con.execute("SELECT COUNT(*) FROM companies WHERE IFNULL(archived,0)=0 AND score>=55 AND created_at>=datetime('now','-1 day')").fetchone()[0]
    summary = f"{names}: {after - before} yeni firma, {good} tanesi güçlü aday (55+)"
    meta_set(con, "auto_next", (i + len(batch)) % max(len(fc), 1))
    meta_set(con, "auto_last", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    meta_set(con, "auto_summary", summary)
    meta_set(con, "auto_step", "")
    meta_set(con, "auto_error", " · ".join(errors))
    con.close()
    log(summary)
    return summary


def cmd_auto(a):
    auto_cycle()


def cmd_cleanup(a):
    con = db()
    for label, k in archive_candidates(con):
        print(f"  {label}: {k}")
    print(f"{auto_archive(con)} firma arşive kaldırıldı (silinmedi; Firmalar → Arşiv'den geri alınabilir).")


def market_ranks(con):
    return {r["iso"]: (r["rk"], r["from_tr"]) for r in con.execute("""
      SELECT w.importer_iso3 iso, IFNULL(SUM(t.value_usd),0) from_tr,
             (SELECT COUNT(*)+1 FROM (SELECT importer_iso3, SUM(value_usd) v FROM trade_flows WHERE partner='WORLD' GROUP BY 1) x
              WHERE x.v > SUM(w.value_usd)) rk
      FROM trade_flows w LEFT JOIN trade_flows t ON t.year=w.year AND t.hs=w.hs AND t.importer_iso3=w.importer_iso3 AND t.partner='TUR'
      WHERE w.partner='WORLD' GROUP BY w.importer_iso3""")}


def score_company(con, c, imp):
    """Alıcı uygunluk puanı 0-100 + 'neden potansiyel' gerekçeleri (Türkçe). Puan: firma tipi + ürünler + kakao sinyali + ölçek + B2B + iletişim + pazar."""
    ks = con.execute("SELECT * FROM contacts WHERE company_id=?", (c["id"],)).fetchall()
    bt = c["buyer_type"] or "unknown"
    enriched = (c["enrich_v"] or 0) >= 2 and not c["enrich_error"]
    reasons = []
    ev = load_evidence(c)
    if ev and bt in ("unknown", "retail", "craft"):  # ürünlerinde kakao kullandığı kanıtlı: kendi markasıyla üretici/marka sahibi
        bt = "industrial"
        con.execute("UPDATE companies SET buyer_type='industrial' WHERE id=?", (c["id"],))
    base = {"industrial": 38, "distributor": 32, "craft": 10, "retail": 0, "competitor": 6}.get(bt)
    if base is None:  # henüz sınıflanmadı: segmentten kaba tahmin
        base = round(SEGMENTS.get(c["segment"], SEGMENTS["other"])[0] * 0.55)
    s = base
    reasons.append({"industrial": "Kakao kullanan üretici (sanayi alıcısı)", "distributor": "Toptancı/distribütör: tekrar eden toplu alım",
                    "craft": "Küçük/butik üretici: düşük hacim", "retail": "Perakende dükkân: toplu alıcı değil",
                    "competitor": "Kakao işleyici: rakip olabilir"}.get(bt, "Site henüz taranmadı" if not enriched else "Firma tipi belirlenemedi"))
    try:
        cats = json.loads(c["categories"] or "{}")
    except ValueError:
        cats = {}
    if ev:
        s += min(18, 8 + 2 * ev.get("n", 1))
        reasons.insert(0, "Kanıt: " + products.evidence_text(ev))
    if bt == "industrial" and (c["segment"] in ("chocolate_maker", "confectionery") or cats.get("chocolate", 0) >= 3) and c["business_type"] != "wholesale":
        s += 8
        reasons.insert(1 if ev else 0, "Çikolata/şekerleme fabrikası: kakao yağı, kakao likörü ve kakao tozunun en büyük alıcısı")
    if not c["website"] and not ks and not c["phone"]:  # ulaşılamayan aday, ulaşılabilenlerin arkasında sıralansın
        s -= 15
        reasons.append("Web sitesi ve iletişim bilgisi henüz bulunamadı")
    rel = [k for k in crawler.USER_CATS if cats.get(k, 0) >= 2]
    if rel:
        s += min(14, 4 * len(rel))
        reasons.append("Ürünler: " + ", ".join(CAT_TR[k] for k in rel[:4]))
    if bt == "distributor" and cats.get("ingredients", 0) >= 3:
        s += 8
        reasons.append("Gıda/fırın hammaddesi ticareti yapıyor: kakao ürünlerini portföyüne ekleyebilir")
    cocoa = c["cocoa_signal"] or 0
    if cocoa >= 30:
        s += min(8, cocoa // 12)
        reasons.append("Sitede kakao/çikolata ifadeleri yoğun")
    emp = _emp_int(c["employees"])
    if emp:
        if 50 <= emp <= 2000:
            s += 10
            reasons.append(f"Orta/büyük ölçek (~{emp} çalışan): doğrudan tedarikçi arar")
        elif 20 <= emp < 50:
            s += 6
            reasons.append(f"Küçük-orta ölçek (~{emp} çalışan)")
        elif emp > 2000:
            s += 4
            reasons.append(f"Çok büyük (~{emp}): merkezi satın alma, zor ama hacimli")
        elif emp < 10:
            s -= 4
            reasons.append("Çok küçük işletme")
    if (c["b2b_signal"] or 0) >= 2:
        s += 6
        reasons.append("B2B / toptan / özel markalı üretim sinyali")
    buyer_ct = [k for k in ks if k["dept"] in ("purchasing", "export", "sales")]
    if any(k["name"] for k in buyer_ct):
        s += 9
        reasons.append("Satın alma/ihracat/satış sorumlusu adıyla bulundu")
    elif buyer_ct:
        s += 6
        reasons.append("Satın alma/ihracat/satış e-postası bulundu")
    elif any(k["name"] for k in ks):
        s += 4
    if any(k["email_ok"] for k in ks):
        s += 4
    if c["phone"] or any(k["phone"] for k in ks):
        s += 1
    prof = focus.PROFILE.get(c["country"] or "")
    if prof and (c["country"] in focus_countries()):
        s += 4
        reasons.append(f"Odak pazar: {COUNTRIES[c['country']][0]} · {prof['route'].split(';')[0]}")
        if "Serbest Ticaret" in prof["deal"]:
            reasons.append(f"Türkiye–{COUNTRIES[c['country']][0]} serbest ticaret anlaşması: EUR.1 ile gümrük avantajı olabilir")
    info = imp.get(ISO2_TO_ISO3.get(c["country"] or ""))
    if info:
        bonus = round(max(0, 25 - info[0]) * 0.5)
        if bonus:
            s += bonus
            reasons.append(f"Pazar: {COUNTRIES[c['country']][0]} kakao ithalatında {info[0]}. sırada")
        if info[1] > 0:
            s += 3
            reasons.append("Bu ülke Türkiye'den zaten kakao alıyor")
    s = max(0, min(s, 100))
    s = min(s, {"retail": 25, "competitor": 35, "craft": 45}.get(bt, 100))
    con.execute("UPDATE companies SET score=?, fit_reasons=? WHERE id=?", (s, json.dumps(reasons, ensure_ascii=False), c["id"]))
    update_data_score(con, c["id"])
    return s


def cmd_score(a):
    con = db()
    imp = market_ranks(con)
    rows = con.execute("SELECT * FROM companies").fetchall()
    for c in rows:
        refresh_derived(con, c["id"])
        score_company(con, con.execute("SELECT * FROM companies WHERE id=?", (c["id"],)).fetchone(), imp)
    con.commit()
    print(f"{len(rows)} firma puanlandı.")


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
    status = status or ("contacted" if kind in ("email", "call") and cur[0] in ("new", "saved") else None)
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


# ---------------------------------------------------------------- teklif, numune, görev
DEAL_PRODUCTS = ["Kakao tozu (doğal)", "Kakao tozu (alkalize)", "Kakao yağı", "Kakao hamuru (liquor)", "Kuvertür / kompunt çikolata", "Diğer"]
INCOTERMS = ["EXW", "FCA", "FOB", "CFR", "CIF", "DAP", "DDP"]
STATUS_ORDER = {s: i for i, s in enumerate(["new", "saved", "contacted", "replied", "sample", "negotiation", "won"])}


def fx_usd(currency):
    """Para birimini dolara çevirme katsayısı (config.json → fx; ör. {"EUR": 1.08})."""
    return 1.0 if (currency or "USD") == "USD" else float((config().get("fx") or {}).get(currency, {"EUR": 1.08, "GBP": 1.27}.get(currency, 1.0)))


def deal_total_usd(d):
    return (d["qty_t"] or 0) * 1000 * (d["price_kg"] or 0) * fx_usd(d["currency"])


def refresh_value(con, cid):
    """Firmanın fırsat değeri = açık ve kazanılmış tekliflerinin toplamı ($)."""
    rows = con.execute("SELECT * FROM deals WHERE company_id=? AND kind='quote' AND status IN ('open','won')", (cid,)).fetchall()
    if rows:
        con.execute("UPDATE companies SET value_usd=? WHERE id=?", (round(sum(deal_total_usd(d) for d in rows)), cid))


def _raise_status(con, cid, status):
    cur = con.execute("SELECT status FROM companies WHERE id=?", (cid,)).fetchone()[0]
    return status if STATUS_ORDER.get(status, 0) > STATUS_ORDER.get(cur, 0) and cur not in ("lost", "won") else None


def add_deal(con, cid, kind="quote", product=None, qty_t=None, price_kg=None, currency="USD", incoterm=None, valid_until=None, tracking=None, note=None):
    """Teklif ya da numune kaydı. Geçmişe yazar, durumu ilerletir (teklif → Pazarlık, numune → Numune) ve takip tarihini kurar."""
    if kind not in ("quote", "sample"):
        raise ValueError("kind: quote | sample")
    cur = con.execute("INSERT INTO deals(company_id,kind,product,qty_t,price_kg,currency,incoterm,valid_until,tracking,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (cid, kind, product, qty_t, price_kg, currency or "USD", incoterm, valid_until, tracking, note))
    if kind == "quote":
        parts = [product or "teklif", f"{qty_t:g} ton" if qty_t else "", f"{price_kg:g} {currency}/kg" if price_kg else "", incoterm or "",
                 f"geçerli: {valid_until}" if valid_until else ""]
        days = None
        if valid_until:
            try:
                days = max(1, (dt.date.fromisoformat(valid_until) - dt.date.today()).days - 2)  # süresi dolmadan 2 gün önce hatırlat
            except ValueError:
                days = None
        do_log(con, cid, "quote", "Teklif verildi: " + " · ".join(x for x in parts if x), _raise_status(con, cid, "negotiation"), days)
    else:
        parts = [product or "numune", f"takip no: {tracking}" if tracking else "", note or ""]
        do_log(con, cid, "sample", "Numune gönderildi: " + " · ".join(x for x in parts if x), _raise_status(con, cid, "sample"), 10)
    refresh_value(con, cid)
    con.commit()
    return cur.lastrowid


DEAL_OUTCOME = {("quote", "won"): "Teklif kabul edildi", ("quote", "lost"): "Teklif reddedildi",
                ("sample", "won"): "Numune beğenildi", ("sample", "lost"): "Numune beğenilmedi"}


def close_deal(con, deal_id, outcome, note=""):
    d = con.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if not d or outcome not in ("won", "lost"):
        raise ValueError("Bulunamadı")
    con.execute("UPDATE deals SET status=?, closed_at=? WHERE id=?", (outcome, today(), deal_id))
    status = None
    if d["kind"] == "quote" and outcome == "won":
        status = "won"
    elif d["kind"] == "sample" and outcome == "won":
        status = _raise_status(con, d["company_id"], "negotiation")
    summary = DEAL_OUTCOME[(d["kind"], outcome)] + f" ({d['product'] or ''})" + (f" – {note}" if note else "")
    do_log(con, d["company_id"], "note", summary, status, 3 if d["kind"] == "sample" and outcome == "won" else None)
    refresh_value(con, d["company_id"])
    con.commit()


def open_deals(con, kind=None):
    sql = "SELECT d.*, c.name, c.country FROM deals d JOIN companies c ON c.id=d.company_id WHERE d.status='open'"
    p = []
    if kind:
        sql += " AND d.kind=?"
        p.append(kind)
    return con.execute(sql + " ORDER BY IFNULL(d.valid_until,'9999'), d.created_at", p).fetchall()


def add_note(con, cid, body):
    body = (body or "").strip()
    if not body:
        raise ValueError("Not boş olamaz")
    con.execute("INSERT INTO notes(company_id, body) VALUES(?,?)", (cid, body[:5000]))
    con.commit()


def add_task(con, title, due=None, cid=None):
    title = (title or "").strip()
    if not title:
        raise ValueError("Görev boş olamaz")
    cur = con.execute("INSERT INTO tasks(company_id,title,due) VALUES(?,?,?)", (cid, title, due or today()))
    con.commit()
    return cur.lastrowid


def done_task(con, tid):
    t = con.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t:
        raise ValueError("Bulunamadı")
    con.execute("UPDATE tasks SET done_at=? WHERE id=?", (today(), tid))
    if t["company_id"]:
        con.execute("INSERT INTO activities(company_id,kind,summary) VALUES(?,?,?)", (t["company_id"], "note", "Görev tamamlandı: " + t["title"]))
    con.commit()
    return t


def open_tasks(con, cid=None, until=None):
    sql, p = "SELECT t.*, c.name FROM tasks t LEFT JOIN companies c ON c.id=t.company_id WHERE t.done_at IS NULL", []
    if cid:
        sql += " AND t.company_id=?"
        p.append(cid)
    if until:
        sql += " AND IFNULL(t.due,'')<=?"
        p.append(until)
    return con.execute(sql + " ORDER BY IFNULL(t.due,'9999'), t.id", p).fetchall()


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


def best_contact(con, cid):
    """E-postası geçerli kişiler arasında en uygununu seçer: gerçek adres > tahmin; satın alma > ihracat > satış > yönetim > kişi > genel."""
    rows = con.execute("SELECT * FROM contacts WHERE company_id=? AND email_ok=1 AND email IS NOT NULL", (cid,)).fetchall()
    if not rows:
        return None
    return sorted(rows, key=lambda k: (k["kind"] == "guess", crawler.DEPT_PRIORITY.get(k["dept"] or "other", 12), -(k["confidence"] or 0),
                                       k["name"] is None, k["id"]))[0]


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
    k = best_contact(con, cid)
    name = k["name"] if k and k["name"] else None
    greeting = {"en": (f"Dear {name}", "Dear Sir or Madam"), "de": (f"Guten Tag {name}", "Sehr geehrte Damen und Herren"),
                "ru": (f"Здравствуйте, {name}!", "Здравствуйте!"), "fr": (f"Bonjour {name}", "Madame, Monsieur"),
                "ar": (f"السيد/السيدة {name} المحترم،", "السادة المحترمون،"), "tr": (f"Sayın {name}", "Merhaba")}.get(lang, ("Dear " + str(name), "Dear Sir or Madam"))
    greeting = greeting[0] if name else greeting[1]
    seg = SEGMENTS.get(c["segment"], SEGMENTS["other"])[1]
    ctx = _Safe(config(), company=c["name"], contact=(name or ("Sir or Madam" if lang == "en" else "Damen und Herren")), greeting=greeting,
                segment_label=seg, hook=email_hook(c, lang, seg))
    with open(path, encoding="utf-8") as f:
        return (k["email"] if k else None), f.read().format_map(ctx)


HOOK = {  # dil: (içerik adları {etiket: ad}, bağlaç, kanıtlı+örnekli, kanıtlı, kanıtsız)
    "ru": ({"en:cocoa-powder": "какао-порошок", "en:cocoa-butter": "какао-масло"}, " и ",
           "Мы обратили внимание, что {c} использует {i} в таких продуктах, как «{x}»", "Мы обратили внимание, что {c} использует {i}",
           "Мы изучили продукцию {c}"),
    "fr": ({"en:cocoa-powder": "de la poudre de cacao", "en:cocoa-butter": "du beurre de cacao"}, " et ",
           "Nous avons remarqué que {c} utilise {i} dans des produits comme « {x} »", "Nous avons remarqué que {c} utilise {i}",
           "Nous suivons avec intérêt les produits de {c}"),
    "ar": ({"en:cocoa-powder": "مسحوق الكاكاو", "en:cocoa-butter": "زبدة الكاكاو"}, " و",
           "لاحظنا أن {c} تستخدم {i} في منتجات مثل «{x}»", "لاحظنا أن {c} تستخدم {i}", "اطلعنا على منتجات {c}"),
    "tr": ({"en:cocoa-powder": "kakao tozu", "en:cocoa-butter": "kakao yağı"}, " ve ",
           "{c} firmasının «{x}» gibi ürünlerinde {i} kullandığını gördük", "{c} firmasının ürünlerinde {i} kullandığını gördük",
           "{c} firmasının ürünlerini inceledik"),
}


def email_hook(c, lang, seg):
    """Giriş cümlesi. Ürün kanıtı varsa firmanın kendi ürününden söz eder (soğuk e-postada yanıt oranını en çok artıran şey)."""
    ev = load_evidence(c)
    if lang in HOOK:
        names, join, with_ex, with_ing, plain = HOOK[lang]
        ings = join.join(names[x] for x in (ev or {}).get("ingredients", []) if x in names)
        ex = (ev or {}).get("examples", [])[:1]
        return (with_ex if ex else with_ing).format(c=c["name"], i=ings, x=ex[0] if ex else "") if ings else plain.format(c=c["name"])
    i = {"de": 2}.get(lang, 1)
    if ev and ev.get("ingredients"):
        ings = (" und " if lang == "de" else " and ").join(products.INGREDIENTS[x][i] for x in ev["ingredients"] if x in products.INGREDIENTS)
        ex = ev.get("examples", [])[:1]
        if lang == "de":
            return f"Da {c['name']} in Produkten wie „{ex[0]}“ {ings} verwendet" if ex else f"Da {c['name']} {ings} verarbeitet"
        return f"I noticed that {c['name']} uses {ings} in products such as \u201c{ex[0]}\u201d" if ex else f"I noticed that {c['name']} uses {ings} in its products"
    return f"Da {c['name']} im Bereich {seg} tätig ist" if lang == "de" else f"I noticed {c['name']} works in {seg}"


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


def contact_summary(con, cid):
    """Bir firmada ulaşılacak en uygun kişi: (adlı karar verici, en iyi geçerli e-posta, telefon)."""
    ks = con.execute("SELECT * FROM contacts WHERE company_id=?", (cid,)).fetchall()
    prio = crawler.DEPT_PRIORITY
    people = sorted([k for k in ks if k["name"]], key=lambda k: (k["dept"] not in ("purchasing", "export", "sales", "management"), prio.get(k["dept"] or "other", 12), k["id"]))
    em = best_contact(con, cid)
    phone = next((k["phone"] for k in ks if k["phone"]), None)
    person = people[0] if people else None
    # adlı kişinin e-postası varsa onu, yoksa en iyi genel/departman adresini göster
    return {"person": person["name"] if person else None, "role": person["role"] if person else None, "dept": (person["dept"] if person else (em["dept"] if em else None)),
            "email": (person["email"] if person and person["email"] and person["email_ok"] else (em["email"] if em else None)),
            "email_dept": em["dept"] if em else None, "email_guess": bool(em and em["kind"] == "guess"), "phone": phone}


def opportunity_rows(con, country=None, min_score=50, btype=None, ready=False, limit=None):
    """Kakao alıcısı olması muhtemel firmalar (sanayi kullanıcısı / distribütör), uygunluk puanına göre. Her satıra 'contact' eklenir."""
    types = (btype,) if btype in ("industrial", "distributor") else ("industrial", "distributor")
    sql = ("SELECT * FROM companies WHERE IFNULL(archived,0)=0 AND status NOT IN ('lost','won') AND score>=? AND IFNULL(buyer_type,'unknown') IN (" + ",".join("?" * len(types)) + ")")
    p = [min_score, *types]
    if country:
        sql += " AND country=?"
        p.append(country)
    if ready:
        sql += " AND id IN (SELECT company_id FROM contacts WHERE email_ok=1)"
    sql += " ORDER BY score DESC, id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    out = []
    for r in con.execute(sql, p).fetchall():
        d = dict(r)
        d["contact"] = contact_summary(con, r["id"])
        try:
            d["reasons"] = json.loads(r["fit_reasons"] or "[]")
        except ValueError:
            d["reasons"] = []
        out.append(d)
    return out


def opportunity_table(con, **kw):
    """Excel/CSV için: (başlıklar, satırlar)."""
    from collections import OrderedDict  # noqa: F401
    head = ["#", "Ülke", "Firma", "Firma adı (Türkçe anlamı / Latin harfli)", "Tip", "Segment", "Uygunluk", "Neden potansiyel", "Özet", "Teklif önerisi", "Web sitesi",
            "Kişi (satın alma/ihracat/satış)", "Görev", "E-posta", "E-posta türü", "Telefon", "WhatsApp", "LinkedIn", "Adres", "Çalışan", "Durum", "Açıklama (Türkçe)"]
    rows = []
    for i, d in enumerate(opportunity_rows(con, **kw), 1):
        ct = d["contact"]
        rows.append([i, COUNTRIES.get(d["country"] or "", (d["country"] or "",))[0], d["name"], d["name_gloss"] or d["name_latin"] or "", BUYER_TR.get(d["buyer_type"] or "unknown"),
                     d["segment"], d["score"], " • ".join(d["reasons"]), d["summary_tr"] or "", d["offer"] or "", d["website"] or "", ct["person"] or "", ct["role"] or "",
                     ct["email"] or "", ("tahmin" if ct["email_guess"] else (ct["email_dept"] or "")), d["phone"] or ct["phone"] or "", d["whatsapp"] or "", d["linkedin"] or "",
                     d["address"] or "", d["employees"] or "", d["status"], d["desc_tr"] or d["description"] or ""])
    return head, rows


def cmd_export_opportunities(a):
    """Fırsat listesi: .xlsx (iki sayfa: Fırsatlar + Tüm kişiler) ya da .csv."""
    con = db()
    head, rows = opportunity_table(con, min_score=int(getattr(a, "min_score", 50) or 50))
    if a.file.lower().endswith(".xlsx"):
        ks = con.execute("""SELECT c.name, c.country, c.score, k.name, k.role, k.dept, k.email, k.kind, k.phone FROM contacts k JOIN companies c ON c.id=k.company_id
                            WHERE c.buyer_type IN ('industrial','distributor') AND c.score>=? ORDER BY c.score DESC, c.id""", (int(getattr(a, "min_score", 50) or 50),)).fetchall()
        with open(a.file, "wb") as f:
            f.write(xlsx.make_xlsx([("Fırsatlar", [head] + rows, [5, 14, 30, 34, 22, 20, 10, 60, 50, 50, 28, 26, 24, 32, 12, 18, 18, 36, 36, 10, 14, 60]),
                                    ("Tüm kişiler", [["Firma", "Ülke", "Uygunluk", "Kişi", "Görev", "Departman", "E-posta", "Tür", "Telefon"]] + [list(map(lambda v: v if v is not None else "", r)) for r in ks],
                                     [30, 8, 10, 24, 26, 14, 34, 10, 18])]))
    else:
        with open(a.file, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)
    print(f"{len(rows)} fırsat → {a.file}")


def cmd_export(a):
    con = db()
    rows = con.execute("""SELECT c.id,c.name,c.country,c.city,c.address,c.website,c.segment,c.business_type,c.score,c.data_score,c.status,c.phone,c.whatsapp,
        c.linkedin,c.facebook,c.instagram,c.twitter,c.youtube,c.legal_id,c.employees,c.founded,c.cocoa_signal,c.value_usd,c.product,
        c.last_contacted,c.next_followup,c.source,c.description,
        (SELECT group_concat(email,'; ') FROM contacts k WHERE k.company_id=c.id AND k.email_ok=1) emails,
        (SELECT group_concat(name||' ('||IFNULL(role,'')||')','; ') FROM contacts k WHERE k.company_id=c.id AND k.name IS NOT NULL) people
        FROM companies c ORDER BY score DESC""").fetchall()
    with open(a.file, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel Türkçe karakterleri doğru açar
        w = csv.writer(f)
        w.writerow(rows[0].keys() if rows else [])
        w.writerows([tuple(r) for r in rows])
    print(f"{len(rows)} satır → {a.file}")


def cmd_export_contacts(a):
    """Her satır bir kişi/e-posta/telefon: toplu posta (mail merge) için."""
    con = db()
    rows = con.execute("""SELECT c.id company_id, c.name company, c.country, c.website, c.segment, c.score, c.status,
        k.name contact, k.role, k.dept, k.email, k.email_ok, k.kind, k.confidence, k.phone, k.source_url
        FROM contacts k JOIN companies c ON c.id=k.company_id ORDER BY c.score DESC, c.id, k.confidence DESC""").fetchall()
    with open(a.file, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(rows[0].keys() if rows else [])
        w.writerows([tuple(r) for r in rows])
    print(f"{len(rows)} kişi/iletişim → {a.file}")


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
    s = add("enrich", cmd_enrich, "sitelerden e-posta, telefon, kişi, sosyal medya, adres topla (derin tarama)")
    s.add_argument("--limit", type=int, default=50); s.add_argument("--workers", type=int, default=6)
    s.add_argument("--pages", type=int, default=8); s.add_argument("--force", action="store_true", help="daha önce taranmışları da yeniden tara")
    s = add("discover", cmd_discover, "arama motoru (Brave/Google API) ile yeni alıcı adayları bul")
    s.add_argument("--country", required=True, help="ISO2 virgülle: DE,NL,GB"); s.add_argument("--segments", default=""); s.add_argument("--max-queries", type=int, default=40)
    s = add("translate", cmd_translate, "en uygun firmaların açıklamalarını Türkçeye çevir")
    s.add_argument("--limit", type=int, default=40); s.add_argument("--min-score", type=int, default=40)
    add("seed", cmd_seed, "hazır başlangıç listesini (bilinen alıcılar) içe aktar")
    s = add("harvest-wikidata", cmd_harvest_wikidata, "Wikidata'dan bilinen çikolata/şekerleme firmalarını çek")
    s.add_argument("--country", default="", help="ISO2 virgülle (boş = hepsi)")
    s = add("harvest-products", cmd_harvest_products, "ürün etiketinde kakao geçen markaları bul (OpenFoodFacts, kanıtlı alıcılar)")
    s.add_argument("--country", required=True, help="ISO2 virgülle: DE,NL,PL"); s.add_argument("--pages", type=int, default=8)
    add("cleanup", cmd_cleanup, "dükkân/kafe/rakip gibi uygun olmayanları arşive kaldır (silmez)")
    add("auto", cmd_auto, "otomatik tarama turunu şimdi çalıştır (sıradaki odak ülkeler)")
    add("fix-countries", cmd_fix_countries, "firmaların ülkesini sitelerinden kontrol et ve düzelt")
    s = add("add-sites", cmd_add_sites, "kendi bulduğun firma sitelerini ekle ve hemen tara")
    s.add_argument("sites", nargs="+"); s.add_argument("--country")
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
    s = add("export-opps", cmd_export_opportunities, "fırsat listesi (.xlsx veya .csv)"); s.add_argument("file"); s.add_argument("--min-score", type=int, default=50)
    s = add("export-contacts", cmd_export_contacts, "kişi/e-posta listesini CSV'ye aktar (toplu posta için)"); s.add_argument("file")

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
