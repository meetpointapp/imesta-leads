"""Firma sitesi derin tarayıcı (sadece standart kütüphane).

crawl_site(url) → bir firmanın herkese açık sitesinden iletişim ve firma verisi çıkarır:
e-postalar (departman sınıflandırmalı), telefonlar, WhatsApp, sosyal medya, yönetici/kişi adları (Impressum, ekip sayfaları),
adres, vergi/sicil no, çalışan sayısı, kuruluş yılı, JSON-LD yapısal veri, kakao ilgi sinyali, üretici/toptancı/perakende tahmini.

Kurallar: robots.txt'e uyar, aynı siteye istekler arasında bekler, sayfa sayısını sınırlar, yalnızca herkese açık sayfaları okur.
"""
import gzip
import html
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

UA = "ImestaFoodBot/1.0 (+https://imestafood.com; B2B supplier research)"
MAX_BYTES = 1_500_000

# ----------------------------------------------------------------------------- HTTP
def fetch(url, timeout=12):
    """(son_url, metin) döner. HTTP/ağ hatasında istisna fırlatır."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip",
                                                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
                                                "Accept-Language": "en,de;q=0.8,tr;q=0.6"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype and not any(t in ctype for t in ("html", "xml", "text", "json")):
            raise ValueError(f"desteklenmeyen içerik: {ctype}")
        raw = r.read(MAX_BYTES + 1)[:MAX_BYTES]
        if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        m = re.search(r"charset=([\w\-]+)", ctype) or re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", raw[:3000], re.I)
        enc = (m.group(1).decode() if m and isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
        try:
            text = raw.decode(enc, "replace")
        except LookupError:
            text = raw.decode("utf-8", "replace")
        return r.geturl(), text


class Robots:
    def __init__(self, base, fetcher=fetch):
        self.rp = urllib.robotparser.RobotFileParser()
        self.ok = True
        try:
            _, txt = fetcher(urllib.parse.urljoin(base, "/robots.txt"), timeout=8)
            self.rp.parse(txt.splitlines())
        except Exception:  # robots.txt yok / okunamadı → kısıtlama yok sayılır
            self.rp.allow_all = True

    def allowed(self, url):
        try:
            return self.rp.can_fetch(UA, url)
        except Exception:
            return True


# ----------------------------------------------------------------------------- HTML ayrıştırma
class PageParser(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "address", "footer", "header",
             "article", "table", "ul", "ol", "dd", "dt", "td", "th", "hr", "main", "aside", "nav", "form"}
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.parts, self.ld, self.meta, self.cf = [], [], [], {}, []
        self.title, self.lang = "", ""
        self._skip = 0
        self._in_title = self._in_ld = False
        self._ldbuf = []
        self._href = None
        self._atext = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if "data-cfemail" in a:
            self.cf.append(a["data-cfemail"])
        if tag == "html":
            self.lang = (a.get("lang") or a.get("xml:lang") or "").lower()[:5]
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("itemprop") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"].strip())
        elif tag in self.SKIP:
            if tag == "script" and "ld+json" in a.get("type", "").lower():
                self._in_ld, self._ldbuf = True, []
            else:
                self._skip += 1
            return
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            self._href, self._atext = a.get("href", ""), []
            if "cdn-cgi/l/email-protection#" in self._href:
                self.cf.append(self._href.split("#", 1)[1])
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            if tag == "script" and self._in_ld:
                self.ld.append("".join(self._ldbuf))
                self._in_ld = False
            elif self._skip:
                self._skip -= 1
            return
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._atext).split())))
            self._href = None
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_ld:
            self._ldbuf.append(data)
        elif self._skip:
            return
        elif self._in_title:
            self.title += data
        else:
            self.parts.append(data)
            if self._href is not None:
                self._atext.append(data)

    @property
    def text(self):
        lines = (re.sub(r"[ \t ​]+", " ", l).strip() for l in "".join(self.parts).split("\n"))
        return "\n".join(l for l in lines if l)


# ----------------------------------------------------------------------------- e-posta
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
OBF_AT = re.compile(r"\s*[\[\(\{<]\s*(?:at|AT|@|ät|ät)\s*[\]\)\}>]\s*")
OBF_DOT = re.compile(r"\s*[\[\(\{<]\s*(?:dot|DOT|punkt|nokta)\s*[\]\)\}>]\s*")
JUNK_EMAIL = re.compile(r"(\.(png|jpe?g|gif|svg|webp|css|js|woff2?)$)|sentry|wixpress|godaddy|@example\.|@domain\.|@email\.com|yourdomain|your-?name|"
                        r"^(name|user|username|email|test|mail|vorname\.nachname|max\.mustermann|john\.doe)@|@2x|u003e|"
                        r"^(no-?reply|do-?not-?reply|donotreply|mailer-daemon|postmaster|abuse|webmaster|privacy|datenschutz|dpo|gdpr|unsubscribe)@", re.I)
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.de", "hotmail.com", "outlook.com", "live.com", "gmx.de", "gmx.net",
             "web.de", "t-online.de", "icloud.com", "me.com", "aol.com", "yandex.com", "mail.ru", "proton.me", "protonmail.com",
             "hotmail.de", "hotmail.fr", "yahoo.fr", "orange.fr", "free.fr", "libero.it", "yahoo.com.tr", "hotmail.com.tr"}

DEPT_RULES = [  # (departman, yerel kısım deseni) – sıra = öncelik
    ("purchasing", r"einkauf|purchas|procure|buyer|buying|sourcing|satin?alma|satınalma|achats?|acquisti|compras|inkoop|zakup|supply"),
    ("export", r"export|international|overseas|ihracat"),
    ("sales", r"sales|vertrieb|verkauf|vente|ventas|vendite|satis|satış|verkoop|commercial|kommerz|b2b|order|bestell|anfrage|inquiry|enquiry|angebot|offers?"),
    ("management", r"ceo|director|geschaeftsfuehrung|geschäftsführung|management|direktion|gm|president|owner|inhaber"),
    ("info", r"^(info|contact|kontakt|office|mail|hello|hallo|hi|post|contato|contatto|contacto|iletisim|iletişim|welcome|team|enquiries|general|admin|bonjour|mailbox|zentrale|sekretariat|empfang|reception)$"),
    ("marketing", r"marketing|press|presse|pr|media|communications"),
    ("support", r"support|service|helpdesk|kundendienst|kundenservice|customer|care"),
    ("hr", r"jobs?|career|karriere|hr|bewerbung|recruit|personal|human"),
    ("accounting", r"invoice|rechnung|billing|accounting|finance|buchhaltung|faktura|muhasebe|accounts"),
    ("quality", r"quality|qualit|qa|qs|regulatory|compliance|food-?safety"),
    ("logistics", r"logistic|logistik|shipping|versand|warehouse|lager|dispatch|nakliye"),
]
DEPT_PRIORITY = {"purchasing": 0, "export": 1, "sales": 2, "management": 3, "person": 4, "info": 5, "marketing": 6, "quality": 7,
                 "logistics": 8, "support": 9, "accounting": 10, "hr": 11, "other": 12, "personal": 13}


def sld(domain):
    """'www.firma.co.uk' → 'firma'  (basit ikinci seviye alan adı)."""
    p = domain.lower().split(".")
    if len(p) >= 3 and p[-2] in ("co", "com", "org", "net", "gov", "ac", "edu") and len(p[-1]) == 2:
        return p[-3]
    return p[-2] if len(p) >= 2 else p[0]


def classify_email(email, company_domain=""):
    local, _, dom = email.lower().partition("@")
    free = dom in FREE_MAIL
    same = bool(company_domain) and sld(dom) == sld(company_domain)
    dept = "other"
    for name, pat in DEPT_RULES:
        if re.search(pat, local):
            dept = name
            break
    else:
        if re.fullmatch(r"[a-z]{2,}[._\-][a-z]{2,}|[a-z][._\-][a-z]{2,}", local):
            dept = "person"
    if free and dept not in ("purchasing", "export", "sales", "management"):
        dept = "personal"  # gmail/outlook gibi serbest posta kutusu: firma adresi değil
    return {"dept": dept, "free": free, "same_domain": same}


def decode_cf(hexstr):
    try:
        b = bytes.fromhex(hexstr)
        k = b[0]
        return "".join(chr(c ^ k) for c in b[1:])
    except Exception:
        return ""


def find_emails(text, links, cf_list):
    """[(email, via)] — via: mailto | cf | text."""
    found = {}
    for href, _ in links:
        if href.lower().startswith("mailto:"):
            for part in urllib.parse.unquote(href[7:]).split("?")[0].replace(";", ",").split(","):
                e = part.strip().lower()
                if EMAIL_RE.fullmatch(e):
                    found.setdefault(e, "mailto")
    for h in cf_list:
        e = decode_cf(h).strip().lower()
        if EMAIL_RE.fullmatch(e):
            found.setdefault(e, "cf")
    t = OBF_DOT.sub(".", OBF_AT.sub("@", html.unescape(text)))
    t = re.sub(r"\s+(?:\(at\)|\[at\])\s+", "@", t)
    for m in EMAIL_RE.findall(t):
        found.setdefault(m.strip(".-_").lower(), "text")
    return [(e, v) for e, v in found.items() if not JUNK_EMAIL.search(e) and len(e) < 80]


# ----------------------------------------------------------------------------- telefon
INTL_RE = re.compile(r"(?<![\w+])\+\s?\d{1,3}[\s.\-/]?(?:\(0\)[\s.\-/]?)?(?:\d[\s.\-/()]?){6,12}\d")
LABEL_RE = re.compile(r"(?i)\b(?:tel(?:efon|efone|ephone)?|phone|fon|mobil(?:e|funk)?|handy|call|telefoon|telefono|téléphone|tél|gsm|whatsapp)\b\.?\s*"
                      r"(?:nr\.?|number|no\.?|numarası)?\s*[:.]?\s*((?:\+|00)?\s?\(?\d[\d\s().\-/]{6,18}\d)")


def _norm_phone(raw):
    s = re.sub(r"\(0\)", "", raw).strip()
    plus = s.startswith("+") or s.startswith("00")
    digits = re.sub(r"\D", "", s)
    if s.startswith("00"):
        digits = digits[2:]
    if not (8 <= len(digits) <= 15) or len(set(digits)) < 4:
        return None
    return {"digits": digits, "intl": plus, "text": ("+" if plus else "") + digits}


def find_phones(text, links):
    """[{'digits','intl','text','via'}] — fax numaraları atlanır."""
    out = {}

    def add(raw, via):
        p = _norm_phone(raw)
        if p and p["digits"] not in out:
            p["via"] = via
            out[p["digits"]] = p
    for href, _ in links:
        h = href.strip()
        if h.lower().startswith("tel:"):
            add(urllib.parse.unquote(h[4:]), "tel")
        else:
            m = re.search(r"(?:wa\.me/|whatsapp\.com/send\?phone=|whatsapp://send\?phone=)\+?(\d{8,15})", h)
            if m:
                add("+" + m.group(1), "whatsapp")
    for m in INTL_RE.finditer(text):
        if re.search(r"(?i)fax", text[max(0, m.start() - 12):m.start()]):
            continue
        add(m.group(0), "text")
    for m in LABEL_RE.finditer(text):
        add(m.group(1), "label")
    return list(out.values())


# ----------------------------------------------------------------------------- sosyal
SOCIAL_BAD = re.compile(r"sharer|share\.php|/share|intent/|/plugins|/dialog|/tr\?|login|/policies|/help|/legal|/p/|/explore|/accounts|/reel|/watch|/hashtag|/search|/home|/i/|/status/", re.I)


def find_socials(links):
    soc = {}
    for href, _ in links:
        h = href.strip()
        low = h.lower()
        if not low.startswith(("http", "//")):
            continue
        h = "https:" + h if h.startswith("//") else h
        clean = h.split("?")[0].split("#")[0].rstrip("/")
        if "linkedin.com/company/" in low or "linkedin.com/showcase/" in low or "linkedin.com/school/" in low:
            soc.setdefault("linkedin", clean)
        elif re.search(r"(?:^|//|\.)facebook\.com/", low) and not SOCIAL_BAD.search(low) and clean.count("/") >= 3:
            soc.setdefault("facebook", clean)
        elif re.search(r"(?:^|//|\.)instagram\.com/[\w.]+$", clean.lower()) and not SOCIAL_BAD.search(low):
            soc.setdefault("instagram", clean)
        elif re.search(r"(?:^|//|\.)(?:twitter|x)\.com/\w+$", clean.lower()) and not SOCIAL_BAD.search(low):
            soc.setdefault("twitter", clean)
        elif re.search(r"youtube\.com/(?:channel|c|user|@)", low) and "watch" not in low:
            soc.setdefault("youtube", clean)
        elif re.search(r"tiktok\.com/@", low):
            soc.setdefault("tiktok", clean)
    return soc


# ----------------------------------------------------------------------------- JSON-LD
def _walk(o, out):
    if isinstance(o, list):
        for i in o:
            _walk(i, out)
    elif isinstance(o, dict):
        out.append(o)
        for v in o.values():
            if isinstance(v, (dict, list)):
                _walk(v, out)


def _types(d):
    t = d.get("@type", [])
    return [x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]


def _addr(a):
    if isinstance(a, str):
        return a.strip()
    if isinstance(a, dict):
        c = a.get("addressCountry")
        c = c.get("name") if isinstance(c, dict) else c
        parts = [a.get("streetAddress"), " ".join(x for x in (a.get("postalCode"), a.get("addressLocality")) if x), c]
        return ", ".join(str(p).strip() for p in parts if p)
    return ""


def parse_jsonld(blocks):
    info = {"phones": [], "emails": [], "people": [], "sameAs": []}
    for b in blocks:
        try:
            data = json.loads(re.sub(r"[\x00-\x1f]+", " ", b.strip()))
        except Exception:
            continue
        nodes = []
        _walk(data, nodes)
        for d in nodes:
            ty = _types(d)
            org = any(t in ("organization", "corporation", "localbusiness", "foodestablishment", "store", "manufacturer",
                            "ngo", "onlinestore", "wholesalestore", "confectionerystore", "bakery", "medicalbusiness") or t.endswith("business") or t.endswith("store")
                      for t in ty)
            if org:
                info.setdefault("name", d.get("legalName") or d.get("name"))
                for k, key in (("telephone", "phones"), ("email", "emails")):
                    v = d.get(k)
                    if isinstance(v, str) and v.strip():
                        info[key].append(v.replace("mailto:", "").strip())
                if d.get("address") and not info.get("address"):
                    info["address"] = _addr(d["address"] if not isinstance(d["address"], list) else d["address"][0])
                sa = d.get("sameAs")
                info["sameAs"] += [sa] if isinstance(sa, str) else [x for x in (sa or []) if isinstance(x, str)]
                if d.get("vatID") or d.get("taxID"):
                    info.setdefault("vat", str(d.get("vatID") or d.get("taxID")))
                if d.get("foundingDate"):
                    info.setdefault("founded", str(d["foundingDate"])[:4])
                ne = d.get("numberOfEmployees")
                if ne:
                    info.setdefault("employees", str(ne.get("value") if isinstance(ne, dict) and ne.get("value") else
                                                     (f"{ne.get('minValue')}-{ne.get('maxValue')}" if isinstance(ne, dict) else ne)))
                if d.get("description") and not info.get("description"):
                    info["description"] = str(d["description"])[:400]
                for fk in ("founder", "founders", "employee", "member"):
                    v = d.get(fk)
                    for p in (v if isinstance(v, list) else [v] if v else []):
                        if isinstance(p, dict) and p.get("name"):
                            info["people"].append({"name": str(p["name"]), "role": str(p.get("jobTitle") or fk.title())})
            if "person" in ty and d.get("name"):
                info["people"].append({"name": str(d["name"]), "role": str(d.get("jobTitle") or ""), "email": d.get("email"), "phone": d.get("telephone")})
            if "contactpoint" in ty:
                for k, key in (("telephone", "phones"), ("email", "emails")):
                    if isinstance(d.get(k), str):
                        info[key].append(d[k].replace("mailto:", "").strip())
    return info


# ----------------------------------------------------------------------------- kişiler
_TITLES = (r"Gesch[aä]e?ftsf[uü]e?hrer(?:in)?|Gesch[aä]ftsleitung|Inhaber(?:in)?|Vorstand|Managing\s+Director|General\s+Manager|CEO|COO|CFO|CTO|"
           r"Founder|Co-?Founder|Owner|Director|Head\s+of\s+[A-Za-z&]+(?:\s[A-Za-z&]+)?|Purchasing(?:\s+(?:Manager|Director|Lead|Head))?|"
           r"Procurement(?:\s+(?:Manager|Director|Lead))?|Buyer|Sourcing\s+Manager|Einkauf(?:s?leiter(?:in)?|sleitung)?|Leiter(?:in)?\s+Einkauf|"
           r"Sales(?:\s+(?:Manager|Director|Representative|Executive))?|Export(?:\s+(?:Manager|Director|Sales))?|Vertriebsleiter(?:in)?|Vertrieb|"
           r"G[eé]rant(?:e)?|Directeur(?:rice)?(?:\s+[A-Za-zéèêàç]+)?|Pr[eé]sident(?:e)?|Amministratore(?:\s+Delegato)?|Direttore(?:\s+[A-Za-z]+)?|"
           r"Genel\s+M[uü]d[uü]r|Sat[iı]n\s+Alma(?:\s+M[uü]d[uü]r[uü])?|Kurucu|Y[oö]netim\s+Kurulu\s+Ba[sş]kan[iı]|Dirigente|Responsable\s+[A-Za-zéè]+")
_NAME = (r"(?:(?:Dr|Prof|Dipl|Ing|Mag|Herr|Frau|Mr|Mrs|Ms|Mme|M)\.?\s+)*"
         r"[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’\-]{1,}(?:\s+(?:van|von|de|der|den|di|da|du|le|la|el|al|bin|ibn|zu)?\s*[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’\-]{1,}){1,3}")
TITLE_AFTER = re.compile(rf"(?P<role>(?i:{_TITLES}))\s*(?:[:\-–]|\bis\b)\s*(?P<names>.{{3,140}})")
NAME_THEN_TITLE = re.compile(rf"^(?P<name>{_NAME})\s*[,\-–|:/]\s*(?P<role>(?i:{_TITLES}))\b")
NAME_ONLY = re.compile(rf"^{_NAME}$")
TITLE_LINE = re.compile(rf"^(?i:{_TITLES})\b")
BAD_NAME = re.compile(r"(?i)\b(gmbh|ltd|llc|inc|bv|b\.v|ag|sa|srl|s\.r\.l|kg|ohg|co\.|company|group|holding|contact|phone|email|e-mail|tel|fax|street|straße|strasse|impressum|"
                      r"imprint|privacy|datenschutz|manager|director|team|sales|export|purchasing|office|service|support|department|abteilung|germany|deutschland|turkey|italy|"
                      r"france|spain|netherlands|china|india|chocolate|cocoa|kakao|schokolade|products?|about|home|news|more|read|click|copyright)\b")
ROLE_DEPT = [("purchasing", r"purchas|procure|buyer|sourcing|einkauf|satin|satın|achat|acquist"), ("export", r"export|ihracat"),
             ("sales", r"sales|vertrieb|verkauf|vente|commercial|vendite"), ("management", r".")]


def _clean_name(n):
    n = re.sub(r"^(?:(?:Dr|Prof|Dipl|Ing|Mag|Herr|Frau|Mr|Mrs|Ms|Mme|M)\.?\s+)+", "", n.strip()).strip(" .,;:-–|")
    toks = n.split()
    if not 2 <= len(toks) <= 4 or BAD_NAME.search(n) or any(len(t) < 2 for t in toks) or re.search(r"\d", n):
        return None
    return n


def role_dept(role):
    for d, p in ROLE_DEPT:
        if re.search(p, role or "", re.I):
            return d
    return "management"


def find_people(text):
    people, seen = [], set()

    def add(name, role, via):
        name = _clean_name(name or "")
        if name and name.lower() not in seen:
            seen.add(name.lower())
            people.append({"name": name, "role": " ".join((role or "").split())[:60], "dept": role_dept(role), "via": via})
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = TITLE_AFTER.search(line)
        if m:
            for part in re.split(r"\s*(?:,|;|\bund\b|\band\b|\bet\b|\bve\b|&|/|\|)\s*", m.group("names")):
                nm = re.match(_NAME, part.strip())
                if nm and len(part.strip().split()) <= 5:
                    add(nm.group(0), m.group("role"), "title:")
        m = NAME_THEN_TITLE.match(line)
        if m:
            add(m.group("name"), m.group("role"), "name,title")
        if NAME_ONLY.match(line) and i + 1 < len(lines) and TITLE_LINE.match(lines[i + 1]) and len(lines[i + 1]) < 70:
            add(line, lines[i + 1], "name/title")
        if (TITLE_LINE.match(line) and len(line) < 60 and i + 1 < len(lines) and NAME_ONLY.match(lines[i + 1])
                and not (i > 0 and NAME_ONLY.match(lines[i - 1]))):  # başlık zaten bir önceki isme aitse atla
            add(lines[i + 1], line, "title/name")
    return people


# ----------------------------------------------------------------------------- adres / yasal / sayısal bilgiler
ZIP_CITY = re.compile(r"^(?:[A-Z]{1,2}[-\s])?(\d{4,5}(?:\s?[A-Z]{2})?)\s+([A-ZÄÖÜÇŞİ][\w\-.' ]{2,40})$")
STREET = re.compile(r"^[A-ZÄÖÜa-zäöüßéèçşğı][\w.\- ']{2,50}\s\d+\s?[a-zA-Z]?(?:[-/]\d+)?$|^\d+\s[A-Z][\w.\- ']{2,40}$")
UK_PC = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")


def find_address(text):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = re.search(r"^(.{3,50}?\s\d+\s?[a-zA-Z]?(?:[-/]\d+)?)\s*[,|]\s*((?:[A-Z]{1,2}[-\s])?\d{4,5}\s+[A-ZÄÖÜÇŞİ][\w\-. ']{2,40})$", line)
        if m:
            return f"{m.group(1)}, {m.group(2)}"
        if ZIP_CITY.match(line) and i > 0 and STREET.match(lines[i - 1]):
            return f"{lines[i - 1]}, {line}"
        if UK_PC.search(line) and i > 0 and len(lines[i - 1]) < 60 and len(line) < 90:
            return f"{lines[i - 1]}, {line}"
    return ""


def find_legal(text):
    out = {}
    m = re.search(r"(?:USt\.?-?\s?Id\.?(?:-?Nr\.?)?|VAT(?:\s?(?:ID|No\.?|Number|Reg\.?\s?No\.?))?|UID|MwSt\.?-?Nr\.?|TVA|BTW(?:-?nummer)?|P\.?\s?IVA|Vergi\s?(?:No|Numaras[ıi]))"
                  r"\s*(?:[:.#]|Nr\.?)?\s*((?:[A-Z]{2})\s?[A-Z0-9][A-Z0-9 .\-]{6,16})", text)
    if m:
        v = re.sub(r"[\s.\-]", "", m.group(1))
        mm = re.match(r"[A-Z]{2}[A-Z0-9]{8,12}", v)
        if mm:
            out["vat"] = mm.group(0)
    m = re.search(r"\b(HR[AB])\s*(\d{3,7}\s?[A-Z]{0,2})(?:[,;\s]+(?:Amtsgericht|AG)\s+([A-ZÄÖÜ][\wäöüß\-]+))?", text)
    if m:
        out["register"] = f"{m.group(1)} {m.group(2).strip()}" + (f" {m.group(3)}" if m.group(3) else "")
    m = re.search(r"KvK[\s\-]*(?:nummer|number|nr\.?)?\s*[:.]?\s*(\d{8})", text, re.I)
    if m:
        out["register"] = out.get("register") or f"KvK {m.group(1)}"
    m = re.search(r"SIRET\s*[:.]?\s*(\d{3}\s?\d{3}\s?\d{3}\s?\d{5})", text, re.I)
    if m:
        out["register"] = out.get("register") or f"SIRET {m.group(1)}"
    m = re.search(r"Company\s+(?:number|no\.?|registration(?:\s+number)?)\s*[:.]?\s*(\d{8}|[A-Z]{2}\d{6})", text, re.I)
    if m:
        out["register"] = out.get("register") or f"Companies House {m.group(1)}"
    m = re.search(r"Ticaret\s+Sicil(?:\s+No)?\s*[:.]?\s*(\d{3,10})", text, re.I)
    if m:
        out["register"] = out.get("register") or f"Ticaret Sicil {m.group(1)}"
    return out


def find_facts(text):
    f = {}
    m = re.search(r"(\d{1,3}(?:[.,]\d{3})*|\d{1,5})\+?\s+(?:Mitarbeiter|Mitarbeitende|Besch[aä]ftigte|employees|staff|collaborateurs|dipendenti|çalışan|calisan|werknemers)", text, re.I)
    if m:
        f["employees"] = m.group(1).replace(".", "").replace(",", "")
    m = re.search(r"(?:since|seit|gegr[uü]ndet(?:\s+im|\s+in)?|founded(?:\s+in)?|est\.?|established(?:\s+in)?|kuruluş|kurulu[sş])\s*:?\s*(1[89]\d{2}|20[0-2]\d)", text, re.I)
    if m:
        f["founded"] = m.group(1)
    return f


COCOA_TERMS = [(r"cocoa|cacao|kakao|kakao", 3.0), (r"chocolat|schokolad|cioccolat|çikolata|cikolata|couverture|praline|pralin|truffle|nougat", 2.0),
               (r"confection|konfekt|s[uü](?:ß|ss)waren|bonbon|candy|candies|sweets|[sş]eker|gummy|caramel", 1.0),
               (r"bakery|b[aä]ckerei|patisserie|biscuit|keks|cookie|pastry|dessert|ice cream|eiscreme|gelato|dondurma|wafer|waffel", 0.6)]
MANUF = re.compile(r"manufactur|hersteller|produktion|we produce|we make|production facilit|factory|fabrik|üretici|üretim|fabbrica|fabricant|our plant|werk\b", re.I)
WHOLE = re.compile(r"wholesale|gro(?:ß|ss)handel|distributor|distribution|\bb2b\b|importer|import & export|toptan|ingredient supplier|rohstoff|zutaten|supplier of|ithalat", re.I)
RETAIL = re.compile(r"add to cart|warenkorb|in den warenkorb|shopping cart|checkout|sepete ekle|sepet\b|online shop|webshop|panier|ajouter au panier|öffnungszeiten|opening hours|gift card|geschenkgutschein", re.I)


def signals(text):
    low = text.lower()
    score = sum(min(10, len(re.findall(p, low))) * w for p, w in COCOA_TERMS)
    m, w, r = len(MANUF.findall(text)), len(WHOLE.findall(text)), len(RETAIL.findall(text))
    if m >= 2 and 2 * m >= r:
        btype = "manufacturer"
    elif w >= 2 and 2 * w >= r:
        btype = "wholesale"
    elif r >= 2:
        btype = "retail"
    elif m or w:
        btype = "manufacturer" if m >= w else "wholesale"
    else:
        btype = "unknown"
    return min(100, int(score * 3)), btype


# ----------------------------------------------------------------------------- sayfa seçimi
RANK = [(100, r"impressum|imprint|legal[-_ ]?notice|rechtliche|mentions[-_ ]?l[eé]gales|aviso[-_ ]?legal|note[-_ ]?legali"),
        (95, r"contact|kontakt|contatt|contacto|iletisim|iletişim|contato|nous[-_ ]contacter|ansprech"),
        (80, r"\bteam\b|/team|management|leadership|people|our[-_ ]?team|wer[-_ ]wir|gesch[aä]ftsf|f[uü]hrung|y[oö]netim|ekip|equipe|[eé]quipe"),
        (70, r"about|[uü]ber[-_ ]uns|unternehmen|company|who[-_ ]we|hakk[ıi]m[ıi]zda|chi[-_ ]siamo|[aà][-_ ]propos|qui[-_ ]sommes|firma|kurumsal|profile"),
        (60, r"sales|vertrieb|export|purchas|einkauf|b2b|wholesale|gro(?:ß|ss)handel|distribut|h[aä]ndler|partner|industr|ingredient|zutaten|rohstoff"),
        (45, r"products?|produkte|produits|prodotti|[uü]r[uü]nler|cocoa|kakao|schokolade|chocolate")]
SKIP_LINK = re.compile(r"\.(pdf|jpe?g|png|gif|svg|zip|docx?|xlsx?|mp4|webp)(\?|$)|privacy|datenschutz|cookie|login|account|cart|warenkorb|checkout|"
                       r"career|karriere|jobs|blog|news|presse|press|faq|terms|agb|widerruf|wishlist|sitemap|tel:|mailto:|javascript:", re.I)


def rank_link(href, text):
    key = f"{href} {text}".lower()
    if SKIP_LINK.search(href):
        return 0
    for score, pat in RANK:
        if re.search(pat, key):
            return score
    return 0


def candidate_pages(base, links, limit):
    host = sld(urllib.parse.urlparse(base).netloc.split(":")[0])
    cand = {}
    for href, text in links:
        if not href or href.startswith("#"):
            continue
        u = urllib.parse.urljoin(base, href).split("#")[0]
        p = urllib.parse.urlparse(u)
        if p.scheme not in ("http", "https") or sld(p.netloc.split(":")[0]) != host:
            continue
        s = rank_link(u, text)
        if s and (u.rstrip("/") != base.rstrip("/")):
            if s > cand.get(u, (0,))[0]:
                cand[u] = (s,)
    ordered = sorted(cand, key=lambda u: (-cand[u][0], len(u)))
    out, seen_paths = [], set()
    for u in ordered:  # aynı yolun dil kopyalarını eleme: kabaca ilk 2 benzer kategori
        key = re.sub(r"^/(?:[a-z]{2}(?:-[a-z]{2})?)/", "/", urllib.parse.urlparse(u).path.lower()).rstrip("/")
        if key in seen_paths:
            continue
        seen_paths.add(key)
        out.append(u)
        if len(out) >= limit:
            break
    return out


# ----------------------------------------------------------------------------- tek sayfa
def parse_page(url, html_text, company_domain=""):
    p = PageParser()
    try:
        p.feed(html_text)
        p.close()
    except Exception:
        pass
    text = p.text
    ld = parse_jsonld(p.ld)
    emails = find_emails(text, p.links, p.cf)
    for e in ld["emails"]:
        if EMAIL_RE.fullmatch(e.lower()) and not JUNK_EMAIL.search(e):
            emails.append((e.lower(), "jsonld"))
    phones = find_phones(text, p.links)
    for t in ld["phones"]:
        n = _norm_phone(t)
        if n and all(x["digits"] != n["digits"] for x in phones):
            n["via"] = "jsonld"
            phones.append(n)
    socials = find_socials(p.links + [(u, "") for u in ld["sameAs"]])
    desc = ld.get("description") or p.meta.get("description") or p.meta.get("og:description") or ""
    return {"url": url, "text": text, "links": p.links, "emails": emails, "phones": phones, "socials": socials, "people": ld["people"] + find_people(text),
            "address": ld.get("address") or find_address(text), "legal": {**find_legal(text), **({"vat": ld["vat"]} if ld.get("vat") else {})},
            "facts": {**find_facts(text), **{k: ld[k] for k in ("employees", "founded") if ld.get(k)}}, "description": " ".join(desc.split())[:400],
            "title": " ".join(p.title.split())[:120], "lang": p.lang[:2], "ld_name": ld.get("name") or ""}


# ----------------------------------------------------------------------------- site tarama
def normalize_site(url):
    url = (url or "").strip()
    if not url:
        return ""
    return url if "//" in url else "https://" + url


def crawl_site(website, max_pages=8, delay=1.0, cancel=None, timeout=12, fetcher=fetch):
    """Bir sitenin ana sayfası + iletişim/impressum/ekip/hakkında sayfalarını tarar; birleştirilmiş sonuç döner."""
    wait = (cancel.wait if cancel else threading.Event().wait)
    base = normalize_site(website)
    res = {"ok": False, "final_url": "", "pages": [], "errors": [], "emails": {}, "phones": {}, "socials": {}, "people": [], "address": "", "legal": {},
           "facts": {}, "description": "", "lang": "", "title": "", "cocoa_signal": 0, "business_type": "unknown"}
    if not base:
        res["errors"].append("web sitesi yok")
        return res
    home_html = None
    for attempt in (base, base.replace("https://", "http://", 1), re.sub(r"^(https?://)(?!www\.)", r"\1www.", base)):
        try:
            final, home_html = fetcher(attempt, timeout=timeout)
            break
        except Exception as e:
            res["errors"].append(f"{attempt}: {e}")
    if home_html is None:
        return res
    res["final_url"] = final
    cdom = urllib.parse.urlparse(final).netloc.split(":")[0].lower()
    cdom = cdom[4:] if cdom.startswith("www.") else cdom
    robots = Robots(final, fetcher)
    if not robots.allowed(final):
        res["errors"].append("robots.txt taramayı yasaklıyor")
        return res
    pages = [parse_page(final, home_html, cdom)]
    res["pages"].append(final)
    cands = candidate_pages(final, pages[0]["links"], max_pages - 1)
    if len(cands) < 3:  # bağlantılar yetersizse sitemap'e ve yaygın yollara bak
        try:
            _, sm = fetcher(urllib.parse.urljoin(final, "/sitemap.xml"), timeout=timeout)
            sm_links = [(u, "") for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm)[:400]]
            for u in candidate_pages(final, sm_links, max_pages - 1):
                if u not in cands:
                    cands.append(u)
        except Exception:
            pass
        for path in ("/impressum", "/kontakt", "/contact", "/contact-us", "/about-us", "/iletisim"):
            if len(cands) >= max_pages - 1:
                break
            u = urllib.parse.urljoin(final, path)
            if u not in cands:
                cands.append(u)
    fetched_extra = 0
    for u in cands:
        if fetched_extra >= max_pages - 1 or (cancel and cancel.is_set()):
            break
        if not robots.allowed(u):
            continue
        wait(delay)
        try:
            fu, h = fetcher(u, timeout=timeout)
        except Exception as e:
            res["errors"].append(f"{u}: {e}")
            continue
        fetched_extra += 1
        res["pages"].append(fu)
        pages.append(parse_page(fu, h, cdom))
    res["ok"] = True
    alltext = []
    for pg in pages:
        alltext.append(pg["text"][:60000])
        for e, via in pg["emails"]:
            c = classify_email(e, cdom)
            if not c["same_domain"] and not c["free"]:
                continue  # üçüncü taraf (ajans, hosting) adresleri alma
            cur = res["emails"].get(e)
            if not cur or (via == "mailto" and cur["via"] != "mailto"):
                res["emails"][e] = {"via": via, "source_url": pg["url"], **c}
        for ph in pg["phones"]:
            res["phones"].setdefault(ph["digits"], {**ph, "source_url": pg["url"]})
        for k, v in pg["socials"].items():
            res["socials"].setdefault(k, v)
        for per in pg["people"]:
            nm = _clean_name(per.get("name", ""))
            if nm and all(nm.lower() != x["name"].lower() for x in res["people"]):
                res["people"].append({"name": nm, "role": per.get("role", ""), "dept": per.get("dept") or role_dept(per.get("role", "")),
                                      "email": per.get("email"), "phone": per.get("phone"), "source_url": pg["url"]})
        if pg["address"] and not res["address"]:
            res["address"] = pg["address"]
        res["legal"] = {**pg["legal"], **res["legal"]}
        for k, v in pg["facts"].items():
            res["facts"].setdefault(k, v)
        res["description"] = res["description"] or pg["description"]
        res["lang"] = res["lang"] or pg["lang"]
        res["title"] = res["title"] or pg["title"]
    res["cocoa_signal"], res["business_type"] = signals("\n".join(alltext))
    return res


def guess_emails(people, domain, known_emails):
    """Sitede görülen kişisel e-posta kalıbından (ad.soyad@) yola çıkıp isimlilerin adresini tahmin eder.
    Yalnızca kalıp sitedeki en az bir gerçek kişisel adresten çıkarılabiliyorsa üretilir."""
    pat = None
    for e in known_emails:
        loc = e.split("@")[0].lower()
        if re.fullmatch(r"[a-z]{2,}\.[a-z]{2,}", loc):
            pat = "first.last"
        elif re.fullmatch(r"[a-z]\.[a-z]{2,}", loc):
            pat = "f.last"
        elif re.fullmatch(r"[a-z]{2,}_[a-z]{2,}", loc):
            pat = "first_last"
        if pat:
            break
    if not pat:
        return []
    fold = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e", "ê": "e", "à": "a", "ç": "c", "ş": "s", "ğ": "g", "ı": "i", "ñ": "n", "ø": "o", "å": "a"})
    out = []
    for p in people:
        toks = re.sub(r"[^a-zA-Zà-ÿşğıİ ]", "", p["name"]).lower().translate(fold).split()
        if len(toks) < 2:
            continue
        first, last = toks[0], toks[-1]
        loc = {"first.last": f"{first}.{last}", "f.last": f"{first[0]}.{last}", "first_last": f"{first}_{last}"}[pat]
        e = f"{loc}@{domain}"
        if e not in known_emails:
            out.append({"name": p["name"], "role": p.get("role"), "email": e, "pattern": pat})
    return out
