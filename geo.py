"""Firmanın gerçek ülkesini sitesinden çıkarır: alan adı uzantısı, uluslararası telefon kodları, e-posta uzantıları, adres.

Neden: firmalar hangi ülke için aranırken bulunduysa o ülkeye yazılıyordu. Mısır'da satılan bir ürünün markası Kamerunlu
olabilir; arama sonucu başka ülkenin sitesini getirebilir. Tek zayıf ipucuyla (tek telefon) ülke değiştirilmez.
"""
import re
import urllib.parse

# Uluslararası telefon kodları (en uzun önek eşleşir). +7 Rusya ve Kazakistan'ın ortak kodudur.
CALLING = {
    "1": "US", "7": "RU", "20": "EG", "27": "ZA", "30": "GR", "31": "NL", "32": "BE", "33": "FR", "34": "ES", "36": "HU", "39": "IT", "40": "RO",
    "41": "CH", "43": "AT", "44": "GB", "45": "DK", "46": "SE", "47": "NO", "48": "PL", "49": "DE", "51": "PE", "52": "MX", "53": "CU", "54": "AR",
    "55": "BR", "56": "CL", "57": "CO", "58": "VE", "60": "MY", "61": "AU", "62": "ID", "63": "PH", "64": "NZ", "65": "SG", "66": "TH", "81": "JP",
    "82": "KR", "84": "VN", "86": "CN", "90": "TR", "91": "IN", "92": "PK", "93": "AF", "94": "LK", "95": "MM", "98": "IR", "211": "SS", "212": "MA",
    "213": "DZ", "216": "TN", "218": "LY", "220": "GM", "221": "SN", "222": "MR", "223": "ML", "224": "GN", "225": "CI", "226": "BF", "227": "NE",
    "228": "TG", "229": "BJ", "230": "MU", "231": "LR", "232": "SL", "233": "GH", "234": "NG", "235": "TD", "236": "CF", "237": "CM", "238": "CV",
    "239": "ST", "240": "GQ", "241": "GA", "242": "CG", "243": "CD", "244": "AO", "248": "SC", "249": "SD", "250": "RW", "251": "ET", "252": "SO",
    "253": "DJ", "254": "KE", "255": "TZ", "256": "UG", "257": "BI", "258": "MZ", "260": "ZM", "261": "MG", "263": "ZW", "264": "NA", "265": "MW",
    "266": "LS", "267": "BW", "268": "SZ", "269": "KM", "291": "ER", "351": "PT", "352": "LU", "353": "IE", "354": "IS", "355": "AL", "356": "MT",
    "357": "CY", "358": "FI", "359": "BG", "370": "LT", "371": "LV", "372": "EE", "373": "MD", "374": "AM", "375": "BY", "380": "UA", "381": "RS",
    "382": "ME", "385": "HR", "386": "SI", "387": "BA", "389": "MK", "420": "CZ", "421": "SK", "591": "BO", "593": "EC", "595": "PY", "598": "UY",
    "852": "HK", "855": "KH", "856": "LA", "880": "BD", "886": "TW", "960": "MV", "961": "LB", "962": "JO", "963": "SY", "964": "IQ", "965": "KW",
    "966": "SA", "967": "YE", "968": "OM", "970": "PS", "971": "AE", "972": "IL", "973": "BH", "974": "QA", "976": "MN", "977": "NP", "992": "TJ",
    "993": "TM", "994": "AZ", "995": "GE", "996": "KG", "998": "UZ",
}
# Ülke kodu gibi görünen ama her yerde kullanılan uzantılar (Kolombiya .co, Montenegro .me gibi) ülke sayılmaz
GENERIC_TLD = {"com", "net", "org", "info", "biz", "co", "io", "ai", "me", "tv", "cc", "eu", "app", "shop", "store", "online", "site", "pro", "group",
               "company", "global", "world", "ws", "fm", "am", "to", "ly", "gg", "la", "md", "su"}
TLD_FIX = {"uk": "GB", "gb": "GB"}
# Adreste geçen ülke adları (İngilizce, Fransızca, yerel). Odak pazarlar ve sık karışan kakao üreticisi ülkeler.
NAMES = {
    "cameroon": "CM", "cameroun": "CM", "ghana": "GH", "nigeria": "NG", "côte d'ivoire": "CI", "cote d'ivoire": "CI", "ivory coast": "CI",
    "ecuador": "EC", "indonesia": "ID", "malaysia": "MY", "senegal": "SN", "sénégal": "SN", "togo": "TG", "benin": "BJ", "bénin": "BJ",
    "egypt": "EG", "égypte": "EG", "egypte": "EG", "مصر": "EG", "morocco": "MA", "maroc": "MA", "المغرب": "MA", "algeria": "DZ", "algérie": "DZ",
    "algerie": "DZ", "الجزائر": "DZ", "tunisia": "TN", "tunisie": "TN", "jordan": "JO", "الأردن": "JO", "iraq": "IQ", "العراق": "IQ", "syria": "SY",
    "سوريا": "SY", "iran": "IR", "ایران": "IR", "russia": "RU", "russian federation": "RU", "россия": "RU", "российская федерация": "RU",
    "kazakhstan": "KZ", "казахстан": "KZ", "uzbekistan": "UZ", "узбекистан": "UZ", "o'zbekiston": "UZ", "kyrgyzstan": "KG", "кыргызстан": "KG",
    "киргизия": "KG", "tajikistan": "TJ", "таджикистан": "TJ", "turkmenistan": "TM", "туркменистан": "TM", "belarus": "BY", "беларусь": "BY",
    "республика беларусь": "BY", "azerbaijan": "AZ", "azərbaycan": "AZ", "азербайджан": "AZ", "mongolia": "MN", "монгол": "MN", "turkey": "TR",
    "türkiye": "TR", "turkiye": "TR", "united arab emirates": "AE", "uae": "AE", "saudi arabia": "SA", "lebanon": "LB", "liban": "LB",
    "germany": "DE", "deutschland": "DE", "france": "FR", "netherlands": "NL", "belgium": "BE", "belgique": "BE", "italy": "IT", "italia": "IT",
    "spain": "ES", "españa": "ES", "united kingdom": "GB", "poland": "PL", "polska": "PL", "ukraine": "UA", "україна": "UA", "india": "IN",
    "china": "CN", "united states": "US", "usa": "US", "south africa": "ZA", "kenya": "KE", "ethiopia": "ET", "sudan": "SD", "libya": "LY",
}
_NAME_RE = re.compile(r"(?<![\w])(" + "|".join(re.escape(n) for n in sorted(NAMES, key=len, reverse=True)) + r")(?![\w])", re.I)
ISO2 = re.compile(r"^[A-Z]{2}$")


def tld_country(host_or_url):
    """'chococam.cm' → 'CM'; genel uzantılar (.com, .co, .io…) → None."""
    host = urllib.parse.urlparse(host_or_url).hostname if "//" in (host_or_url or "") else host_or_url
    tld = (host or "").lower().rstrip(".").rsplit(".", 1)[-1]
    if tld in TLD_FIX:
        return TLD_FIX[tld]
    return tld.upper() if len(tld) == 2 and tld not in GENERIC_TLD else None


def phone_country(phone):
    """'+237 6 99…' → 'CM' (yalnızca + ile yazılmış uluslararası numaralar)."""
    d = re.sub(r"\D", "", phone or "")
    if not (phone or "").strip().startswith("+") or len(d) < 8:
        return None
    for n in (3, 2, 1):
        if d[:n] in CALLING:
            return CALLING[d[:n]]
    return None


def address_country(text):
    """Adresin sonundaki ülke (ad ya da 'CM' gibi kod)."""
    if not text:
        return None
    last = text.strip().rstrip(".").split(",")[-1].strip()
    if ISO2.match(last):
        return last
    hits = _NAME_RE.findall(text.lower())
    return NAMES.get(hits[-1].lower()) if hits else None


def detect(stored, website=None, emails=(), phones=(), address=None, dial=None):
    """Kanıtlara göre gerçek ülke: (ülke, gerekçe) ya da None (değişiklik gerekmiyor / emin değiliz).
    dial: saklı ülkenin telefon kodu (ör. Kazakistan için '7'; +7 numara Kazakistan'ı destekler)."""
    stored = (stored or "").upper()
    votes, why, support = {}, {}, 0.0

    def vote(cc, w, reason):
        if not cc:
            return
        votes[cc] = votes.get(cc, 0) + w
        why.setdefault(cc, []).append(reason)

    t = tld_country(website or "")
    if t == stored:
        support += 2
    else:
        vote(t, 2, f"alan adı .{(t or '').lower()}")
    a = address_country(address)
    if a == stored:
        support += 3
    else:
        vote(a, 3, "adres")
    for dom in list(dict.fromkeys(e.split("@")[-1].lower() for e in emails if e and "@" in e))[:3]:
        c = tld_country(dom)
        if c == stored:
            support += 1
        else:
            vote(c, 1, f"e-posta .{(c or '').lower()}")
    seen = set()
    for p in phones:
        d = re.sub(r"\D", "", p or "")
        if d in seen:
            continue
        seen.add(d)
        if dial and d.startswith(dial) and (p or "").strip().startswith("+"):
            support += 0.5  # saklı ülkenin koduyla yazılmış numara (kodu bizim eklemiş olabileceğimiz için zayıf destek)
            continue
        c = phone_country(p)
        if c and c != stored:
            vote(c, 1, f"telefon +{d[:3]}")
    if not votes:
        return None
    best = max(votes, key=votes.get)
    # Saklı ülkeyi hiçbir şey desteklemiyorsa sitedeki tek yabancı telefon bile yeter (firma sitesinde kendi merkez numarasını yazar)
    if votes[best] > support and (votes[best] >= 2 or support == 0):
        return best, ", ".join(dict.fromkeys(why[best]))
    return None
