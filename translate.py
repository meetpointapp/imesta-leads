"""Firma adı/açıklaması çevirisi.

1) gloss_name: firma adındaki sektör sözcüklerini Türkçeye çevirir (çevrimdışı, ücretsiz sözlük).
2) translit: Kiril/Yunan/Arap harfli adları Latin harflerine çevirir (çevrimdışı).
3) translate_text: açıklama metinlerini Türkçeye çevirir. Sırayla: Claude (anahtar varsa), LibreTranslate (URL varsa), MyMemory (ücretsiz). Sonuçlar önbelleğe alınır.
"""
import hashlib
import json
import re
import unicodedata
import urllib.parse
import urllib.request

import secrets_util

UA = "ImestaFoodBot/1.0 (+https://imestafood.com)"


def fold(s):
    """küçük harf, aksansız; Almanca ä/ö/ü → ae/oe/ue (sözlük bu biçimde)."""
    s = s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss").replace("ł", "l").replace("ø", "o")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


_G = {
    # Almanca
    "schokoladen": "Çikolata", "schokolade": "Çikolata", "schoko": "Çikolata", "kakao": "Kakao", "suesswaren": "Şekerleme", "susswaren": "Şekerleme",
    "konfekt": "Şekerleme", "keks": "Bisküvi", "kekse": "Bisküvi", "gebaeck": "Bisküvi/Pasta", "backwaren": "Unlu Mamuller", "baeckerei": "Fırın",
    "konditorei": "Pastane", "waffel": "Gofret", "waffeln": "Gofret", "kuchen": "Kek", "eis": "Dondurma", "eiscreme": "Dondurma", "speiseeis": "Dondurma",
    "molkerei": "Süt Ürünleri", "milch": "Süt", "getraenke": "İçecek", "lebensmittel": "Gıda", "feinkost": "Şarküteri", "grosshandel": "Toptan",
    "handel": "Ticaret", "zutaten": "Hammadde", "fabrik": "Fabrika", "werke": "Fabrikalar", "gruppe": "Grup", "gebrueder": "Kardeşler", "soehne": "Oğulları",
    "nahrungsmittel": "Gıda", "backzutaten": "Fırın Hammaddeleri", "teigwaren": "Makarna",
    # Fransızca
    "chocolaterie": "Çikolata Fabrikası", "chocolat": "Çikolata", "chocolats": "Çikolata", "biscuiterie": "Bisküvi Fabrikası", "biscuits": "Bisküvi",
    "biscuit": "Bisküvi", "boulangerie": "Fırın", "patisserie": "Pastane", "confiserie": "Şekerleme", "glaces": "Dondurma", "glace": "Dondurma",
    "laiterie": "Süt Ürünleri", "boissons": "İçecek", "alimentaire": "Gıda", "alimentaires": "Gıda", "freres": "Kardeşler", "fils": "Oğulları",
    "gourmandises": "Tatlılar",
    # İtalyanca
    "cioccolato": "Çikolata", "cioccolateria": "Çikolata", "dolciaria": "Tatlı/Şekerleme", "dolciumi": "Şekerleme", "pasticceria": "Pastane", "panificio": "Fırın",
    "biscotti": "Bisküvi", "biscottificio": "Bisküvi", "gelati": "Dondurma", "gelateria": "Dondurma", "latteria": "Süt Ürünleri", "bevande": "İçecek",
    "alimentari": "Gıda", "fratelli": "Kardeşler", "figli": "Oğulları", "industria": "Sanayi", "industrie": "Sanayi", "dolci": "Tatlılar",
    # İspanyolca / Portekizce
    "chocolates": "Çikolata", "chocolate": "Çikolata", "galletas": "Bisküvi", "bolachas": "Bisküvi", "panaderia": "Fırın", "pasteleria": "Pastane", "helados": "Dondurma",
    "lacteos": "Süt Ürünleri", "bebidas": "İçecek", "alimentos": "Gıda", "alimentacion": "Gıda", "hermanos": "Kardeşler", "hijos": "Oğulları", "dulces": "Tatlılar/Şekerleme",
    "confiteria": "Şekerleme", "distribuciones": "Dağıtım", "irmaos": "Kardeşler",
    # Felemenkçe
    "chocolade": "Çikolata", "koekjes": "Bisküvi", "bakkerij": "Fırın", "banketbakkerij": "Pastane", "ijs": "Dondurma", "ijsfabriek": "Dondurma Fabrikası",
    "zuivel": "Süt Ürünleri", "dranken": "İçecek", "voedingsmiddelen": "Gıda", "groothandel": "Toptan", "snoep": "Şeker", "fabriek": "Fabrika", "gebroeders": "Kardeşler",
    # Lehçe
    "czekolada": "Çikolata", "czekoladki": "Çikolata", "ciastka": "Bisküvi", "piekarnia": "Fırın", "cukiernia": "Pastane", "lody": "Dondurma", "mleczarnia": "Süt Ürünleri",
    "napoje": "İçecek", "spozywcze": "Gıda", "hurtownia": "Toptan", "wyroby": "Ürünler", "cukierki": "Şeker", "zaklady": "İşletmeleri",
    # İngilizce
    "biscuits ": "Bisküvi", "bakery": "Fırın", "bakeries": "Fırınlar", "confectionery": "Şekerleme", "confectioners": "Şekerleme", "dairy": "Süt Ürünleri",
    "foods": "Gıda", "food": "Gıda", "ingredients": "Hammadde", "wholesale": "Toptan", "trading": "Ticaret", "industries": "Sanayi", "group": "Grup",
    "brothers": "Kardeşler", "bros": "Kardeşler", "sons": "Oğulları", "manufacturing": "İmalat", "beverages": "İçecek", "snacks": "Atıştırmalık",
    "cocoa": "Kakao", "cacao": "Kakao", "candy": "Şeker", "sweets": "Tatlılar", "pastry": "Pasta", "cakes": "Kek", "wafers": "Gofret", "foodstuff": "Gıda",
    "distribution": "Dağıtım", "distributors": "Distribütör", "export": "İhracat", "import": "İthalat", "international": "Uluslararası", "company": "Şirketi",
}
_LEGAL = {"gmbh": "Ltd. Şti.", "ag": "A.Ş.", "kg": "Kom. Şti.", "ohg": "Kollektif", "ug": "Ltd. Şti.", "bv": "Ltd.", "b.v.": "Ltd.", "nv": "A.Ş.", "n.v.": "A.Ş.",
          "sa": "A.Ş.", "s.a.": "A.Ş.", "sarl": "Ltd. Şti.", "sas": "A.Ş.", "spa": "A.Ş.", "s.p.a.": "A.Ş.", "srl": "Ltd. Şti.", "s.r.l.": "Ltd. Şti.",
          "sl": "Ltd. Şti.", "s.l.": "Ltd. Şti.", "ltd": "Ltd. Şti.", "ltd.": "Ltd. Şti.", "limited": "Ltd. Şti.", "llc": "Ltd. Şti.", "inc": "A.Ş.", "inc.": "A.Ş.",
          "corp": "A.Ş.", "corp.": "A.Ş.", "plc": "A.Ş.", "co.": "ve Ortakları", "oy": "A.Ş.", "ab": "A.Ş.", "a/s": "A.Ş.", "as": "A.Ş.", "sp.": "", "z": "", "o.o.": "Ltd. Şti.",
          "gmbh&co": "Komandit"}
_G.update({"шоколад": "Çikolata", "шоколада": "Çikolata", "кондитерская": "Şekerleme", "кондитерский": "Şekerleme", "фабрика": "Fabrika", "молоко": "Süt",
           "молочный": "Süt", "хлеб": "Ekmek", "хлебозавод": "Ekmek Fabrikası", "печенье": "Bisküvi", "мороженое": "Dondurma", "торты": "Pasta", "пищевой": "Gıda",
           "комбинат": "Kombina", "завод": "Fabrika", "группа": "Grup", "компания": "Şirket",
           "شركة": "Şirket", "حلويات": "Tatlı/Şekerleme", "مصنع": "Fabrika", "مخبز": "Fırın", "ألبان": "Süt Ürünleri", "شوكولاتة": "Çikolata", "بسكويت": "Bisküvi",
           "غذائية": "Gıda", "للتجارة": "Ticaret", "مجموعة": "Grup", "مؤسسة": "Kuruluş", "للصناعات": "Sanayi", "الغذائية": "Gıda"})
_LEGAL.update({"ооо": "Ltd. Şti.", "зао": "A.Ş.", "ао": "A.Ş.", "оао": "A.Ş.", "тоо": "Ltd. Şti."})
GLOSSARY = {fold(k.strip()): v for k, v in _G.items()}
LEGAL = {fold(k).replace(".", ""): v for k, v in _LEGAL.items()}


def gloss_name(name):
    """'Süßwaren Müller GmbH' → 'Şekerleme Müller Ltd. Şti.' (sektör sözcükleri ve şirket türü çevrilir). Çevrilecek bir şey yoksa None."""
    toks = re.split(r"(\s+|[,&/()\-–]+)", name or "")
    out, hit = [], False
    for t in toks:
        k = fold(t).strip(".,")
        kn = k.replace(".", "")
        if not k:
            out.append(t)
        elif k in GLOSSARY and len(k) > 2:
            out.append(GLOSSARY[k])
            hit = True
        elif re.match(r"^(?:ال|لل|و)", k) and re.sub(r"^(?:ال|لل|و)", "", k) in GLOSSARY:
            out.append(GLOSSARY[re.sub(r"^(?:ال|لل|و)", "", k)])
            hit = True
        elif kn in LEGAL and t.strip():
            out.append(LEGAL[kn])
        else:
            out.append(t)
    res = re.sub(r"\s+", " ", "".join(out)).strip(" ,-")
    return res if hit and res and res != name else None


# ----------------------------------------------------------------------------- harf çevirisi (Latin'e)
_CYR = dict(zip("абвгдежзийклмнопрстуфхцчшщъыьэюяіїєґ", ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya", "i", "yi", "ye", "g"]))
_GRK = dict(zip("αβγδεζηθικλμνξοπρσςτυφχψω", ["a", "v", "g", "d", "e", "z", "i", "th", "i", "k", "l", "m", "n", "x", "o", "p", "r", "s", "s", "t", "y", "f", "ch", "ps", "o"]))
_ARB = dict(zip("ابتثجحخدذرزسشصضطظعغفقكلمنهويىةءأإآؤئ", ["a", "b", "t", "th", "j", "h", "kh", "d", "dh", "r", "z", "s", "sh", "s", "d", "t", "z", "'", "gh", "f", "q", "k", "l", "m", "n", "h", "w", "y", "a", "a", "'", "a", "a", "a", "u", "i"]))


def has_non_latin(s):
    return any(ord(c) > 0x024F and c.isalpha() for c in s or "")


def translit(s):
    """Kiril/Yunan/Arap harflerini Latin'e çevirir. Çin/Japon/Kore için None (çeviri API'si gerekir)."""
    if not has_non_latin(s):
        return None
    if re.search(r"[぀-ヿ㐀-鿿가-힯]", s):
        return None
    out = []
    for c in s:
        lc = c.lower()
        m = _CYR.get(lc) or _GRK.get(lc) or _ARB.get(lc)
        if m is None and lc not in "abcdefghijklmnopqrstuvwxyz":
            base = unicodedata.normalize("NFD", lc)[0]  # ά → α, й → и
            m = _CYR.get(base) or _GRK.get(base) or _ARB.get(base)
        if m is None:
            out.append(c)
        else:
            out.append(m.capitalize() if c != lc and m else m)
    res = re.sub(r"\s+", " ", "".join(out)).strip()
    return res.title() if res.islower() else res


# ----------------------------------------------------------------------------- metin çevirisi
def _http_json(url, data=None, headers=None, timeout=25):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"User-Agent": UA, **({"Content-Type": "application/json"} if data is not None else {}), **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _claude(text, src, key):
    d = _http_json("https://api.anthropic.com/v1/messages", {
        "model": "claude-haiku-5-5", "max_tokens": 800,
        "messages": [{"role": "user", "content": f"Translate this company description from {src or 'the source language'} to Turkish. Return only the translation, no comments.\n\n{text}"}]},
        {"x-api-key": key, "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in d.get("content", [])).strip()


def _libre(text, src, url, key):
    d = _http_json(url.rstrip("/") + "/translate", {"q": text, "source": src or "auto", "target": "tr", "format": "text", **({"api_key": key} if key else {})})
    return (d.get("translatedText") or "").strip()


def _mymemory(text, src, email):
    out = []
    for chunk in re.findall(r".{1,420}(?:[.!?]\s|$)", text.strip(), re.S) or [text[:420]]:
        q = urllib.parse.urlencode({"q": chunk.strip(), "langpair": f"{src or 'en'}|tr", **({"de": email} if email else {})})
        d = _http_json("https://api.mymemory.translated.net/get?" + q)
        t = (d.get("responseData") or {}).get("translatedText") or ""
        if str(d.get("responseStatus")) != "200" or "MYMEMORY WARNING" in t.upper() or not t:
            raise RuntimeError("MyMemory: " + (d.get("responseDetails") or "limit"))
        out.append(t)
    return " ".join(out)


def translate_text(con, text, src, email=""):
    """Metni Türkçeye çevirir; önbellekten okur. Dönüş: (çeviri | None, sağlayıcı)."""
    text = " ".join((text or "").split())[:900]
    if not text or (src or "").lower().startswith("tr"):
        return None, None
    h = hashlib.sha1(f"{src}|tr|{text}".encode()).hexdigest()
    con.execute("CREATE TABLE IF NOT EXISTS translations(hash TEXT PRIMARY KEY, src TEXT, text TEXT, result TEXT, provider TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP)")
    row = con.execute("SELECT result, provider FROM translations WHERE hash=?", (h,)).fetchone()
    if row:
        return row[0], row[1]
    tries = []
    if secrets_util.get("anthropic_api_key"):
        tries.append(("claude", lambda: _claude(text, src, secrets_util.get("anthropic_api_key"))))
    if secrets_util.get("libretranslate_url"):
        tries.append(("libretranslate", lambda: _libre(text, src, secrets_util.get("libretranslate_url"), secrets_util.get("libretranslate_key"))))
    tries.append(("mymemory", lambda: _mymemory(text, src, email)))
    last = None
    for name, fn in tries:
        try:
            res = fn()
            if res:
                con.execute("INSERT OR REPLACE INTO translations(hash,src,text,result,provider) VALUES(?,?,?,?,?)", (h, src, text, res, name))
                con.commit()
                return res, name
        except Exception as e:
            last = f"{name}: {e}"
    return None, last
