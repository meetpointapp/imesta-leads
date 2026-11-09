"""Arama motoru ile alıcı keşfi (Google'a elle yazmanın otomatiği).

Ülke × sektör × yerel dilde anahtar sözcüklerle sorgular üretir ("Keks Hersteller Deutschland", "fabricant biscuits France"...),
resmî API'lerle çalıştırır ve sonuçlardaki firma sitelerini aday olarak döner. Kullanılan API'ler (ücretsiz katman, anahtar gerekir):
  • Brave Search API  → ayda ~2000 sorgu  (BRAVE_API_KEY)
  • Google Programmable Search (CSE) → günde 100 sorgu  (GOOGLE_API_KEY + GOOGLE_CX)
Arama sonuç sayfalarını doğrudan kazımayız (şartlar yasaklıyor); yalnızca bu resmî API'ler kullanılır.
"""
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import secrets_util

UA = "ImestaFoodBot/1.0 (+https://imestafood.com)"

LANG_OF = {"RU": "ru", "BY": "ru", "KZ": "ru", "KG": "ru", "UZ": "ru", "TJ": "ru", "TM": "ru", "AZ": "az", "IR": "fa", "SY": "ar", "DE": "de", "AT": "de", "CH": "de", "LI": "de", "NL": "nl", "BE": "nl", "FR": "fr", "LU": "fr", "MA": "fr", "DZ": "fr", "TN": "fr", "IT": "it",
           "ES": "es", "MX": "es", "AR": "es", "CO": "es", "PT": "pt", "BR": "pt", "PL": "pl", "SA": "ar", "EG": "ar", "IQ": "ar", "JO": "ar", "LB": "ar",
           "KW": "ar", "QA": "ar", "OM": "ar", "LY": "ar"}
COUNTRY_LOCAL = {"RU": "Россия", "BY": "Беларусь", "KZ": "Казахстан", "KG": "Кыргызстан", "UZ": "Узбекистан", "TJ": "Таджикистан", "TM": "Туркменистан", "AZ": "Azərbaycan", "IR": "ایران", "SY": "سوريا", "DE": "Deutschland", "AT": "Österreich", "CH": "Schweiz", "NL": "Nederland", "BE": "België", "FR": "France", "IT": "Italia", "ES": "España",
                 "PL": "Polska", "PT": "Portugal", "BR": "Brasil", "MX": "México", "SA": "السعودية", "AE": "الإمارات", "EG": "مصر", "IQ": "العراق",
                 "JO": "الأردن", "KW": "الكويت", "QA": "قطر", "OM": "عمان", "LB": "لبنان", "MA": "Maroc", "DZ": "Algérie", "TN": "Tunisie", "LY": "ليبيا"}
COUNTRY_EN = {"SY": "Syria", "BY": "Belarus", "IR": "Iran", "UZ": "Uzbekistan", "KG": "Kyrgyzstan", "TJ": "Tajikistan", "TM": "Turkmenistan", "MN": "Mongolia", "DE": "Germany", "NL": "Netherlands", "BE": "Belgium", "FR": "France", "GB": "United Kingdom", "IT": "Italy", "ES": "Spain", "PL": "Poland",
              "RU": "Russia", "US": "USA", "CA": "Canada", "AE": "UAE", "SA": "Saudi Arabia", "EG": "Egypt", "IQ": "Iraq", "JO": "Jordan", "LB": "Lebanon",
              "KW": "Kuwait", "QA": "Qatar", "OM": "Oman", "MA": "Morocco", "DZ": "Algeria", "TN": "Tunisia", "LY": "Libya", "IN": "India", "CN": "China",
              "JP": "Japan", "KR": "South Korea", "MY": "Malaysia", "ID": "Indonesia", "SG": "Singapore", "AU": "Australia", "NZ": "New Zealand", "BR": "Brazil",
              "MX": "Mexico", "CH": "Switzerland", "AT": "Austria", "SE": "Sweden", "DK": "Denmark", "NO": "Norway", "FI": "Finland", "IE": "Ireland",
              "PT": "Portugal", "GR": "Greece", "CZ": "Czech Republic", "SK": "Slovakia", "SI": "Slovenia", "HR": "Croatia", "RS": "Serbia", "RO": "Romania",
              "BG": "Bulgaria", "HU": "Hungary", "LT": "Lithuania", "LV": "Latvia", "EE": "Estonia", "UA": "Ukraine", "KZ": "Kazakhstan", "AZ": "Azerbaijan",
              "GE": "Georgia", "IL": "Israel", "NG": "Nigeria", "ZA": "South Africa", "KE": "Kenya", "PK": "Pakistan", "BD": "Bangladesh", "PH": "Philippines",
              "TH": "Thailand", "VN": "Vietnam", "AR": "Argentina", "CO": "Colombia", "LU": "Luxembourg", "LI": "Liechtenstein"}

# segment → dil → aranacak ifadeler (kakao kullanan üreticiler ve hammadde distribütörleri)
TERMS = {
    "ru": {"distributor": ["какао порошок оптом", "кондитерское сырье оптом", "ингредиенты для кондитерского производства", "дистрибьютор какао продуктов"],
           "biscuit_bakery": ["кондитерская фабрика печенье", "производство вафель", "хлебозавод кондитерские изделия"], "ice_cream": ["производство мороженого"],
           "dairy_beverage": ["молочный комбинат", "производство какао напитков"], "cereal_snack": ["производство сухих завтраков", "производство шоколадной пасты"],
           "chocolate_maker": ["шоколадная фабрика", "кондитерская фабрика"]},
    "fa": {"distributor": ["پخش عمده پودر کاکائو", "مواد اولیه قنادی عمده", "واردکننده پودر کاکائو"],
           "biscuit_bakery": ["کارخانه بیسکویت", "تولید کیک و کلوچه"], "ice_cream": ["کارخانه بستنی"], "dairy_beverage": ["کارخانه لبنیات", "تولید شیر کاکائو"],
           "cereal_snack": ["تولید غلات صبحانه", "تولید شکلات صبحانه"], "chocolate_maker": ["کارخانه شکلات", "تولید شیرینی و شکلات"]},
    "az": {"distributor": ["kakao tozu topdan", "qənnadı xammalı topdan"], "biscuit_bakery": ["peçenye istehsalı", "qənnadı fabriki"],
           "ice_cream": ["dondurma istehsalı"], "dairy_beverage": ["süd məhsulları zavodu"], "cereal_snack": ["səhər yeməyi taxıl istehsalı"],
           "chocolate_maker": ["şokolad fabriki"]},
    "en": {"distributor": ["cocoa powder importer distributor", "bakery ingredients wholesale distributor", "food ingredients importer"],
           "biscuit_bakery": ["biscuit manufacturer", "cake and bakery products manufacturer", "wafer manufacturer"],
           "ice_cream": ["ice cream manufacturer"], "dairy_beverage": ["chocolate milk drink manufacturer", "dairy desserts manufacturer", "instant cocoa drink manufacturer"],
           "cereal_snack": ["breakfast cereal manufacturer", "snack bar manufacturer", "chocolate spread manufacturer"],
           "chocolate_maker": ["chocolate manufacturer", "confectionery manufacturer"]},
    "de": {"distributor": ["Kakaopulver Großhandel Importeur", "Backzutaten Großhandel", "Lebensmittelzutaten Großhandel"],
           "biscuit_bakery": ["Keks Hersteller", "Kuchen Backwaren Hersteller Industrie", "Waffel Hersteller"], "ice_cream": ["Speiseeis Hersteller"],
           "dairy_beverage": ["Kakaogetränk Hersteller", "Milchdessert Hersteller"], "cereal_snack": ["Müsli Cerealien Hersteller", "Schokoladenaufstrich Hersteller", "Riegel Hersteller"],
           "chocolate_maker": ["Schokolade Hersteller", "Süßwaren Hersteller"]},
    "fr": {"distributor": ["poudre de cacao grossiste", "importateur cacao en poudre grossiste", "grossiste ingrédients boulangerie pâtisserie"],
           "biscuit_bakery": ["fabricant biscuits", "fabricant gâteaux viennoiseries industriels", "fabricant gaufrettes"], "ice_cream": ["fabricant glaces"],
           "dairy_beverage": ["fabricant boisson chocolatée", "fabricant desserts lactés"], "cereal_snack": ["fabricant céréales petit déjeuner", "fabricant barres céréales", "fabricant pâte à tartiner"],
           "chocolate_maker": ["fabricant chocolat", "fabricant confiserie"]},
    "it": {"distributor": ["importatore cacao in polvere", "ingrosso ingredienti pasticceria"],
           "biscuit_bakery": ["produttore biscotti", "produttore prodotti da forno dolci industriali", "produttore wafer"], "ice_cream": ["produttore gelato industriale"],
           "dairy_beverage": ["produttore bevande al cacao", "produttore dessert al latte"], "cereal_snack": ["produttore cereali colazione", "produttore barrette", "produttore crema spalmabile"],
           "chocolate_maker": ["produttore cioccolato", "produttore dolciumi"]},
    "es": {"distributor": ["importador cacao en polvo", "distribuidor ingredientes panadería pastelería"],
           "biscuit_bakery": ["fabricante galletas", "fabricante bollería industrial", "fabricante barquillos"], "ice_cream": ["fabricante helados"],
           "dairy_beverage": ["fabricante bebidas de cacao", "fabricante postres lácteos"], "cereal_snack": ["fabricante cereales desayuno", "fabricante barritas", "fabricante crema de cacao untable"],
           "chocolate_maker": ["fabricante chocolate", "fabricante confitería"]},
    "nl": {"distributor": ["cacaopoeder importeur groothandel", "bakkerij grondstoffen groothandel"],
           "biscuit_bakery": ["koekjes fabrikant", "banket gebak fabrikant", "wafels fabrikant"], "ice_cream": ["ijs fabrikant"],
           "dairy_beverage": ["chocolademelk fabrikant", "zuiveldesserts fabrikant"], "cereal_snack": ["ontbijtgranen fabrikant", "repen fabrikant", "chocoladepasta fabrikant"],
           "chocolate_maker": ["chocolade fabrikant", "snoep fabrikant"]},
    "pl": {"distributor": ["importer kakao hurtownia", "hurtownia surowców piekarniczych cukierniczych"],
           "biscuit_bakery": ["producent ciastek", "producent wyrobów cukierniczych ciasta", "producent wafli"], "ice_cream": ["producent lodów"],
           "dairy_beverage": ["producent napojów kakaowych", "producent deserów mlecznych"], "cereal_snack": ["producent płatków śniadaniowych", "producent batonów", "producent kremów czekoladowych"],
           "chocolate_maker": ["producent czekolady", "producent słodyczy"]},
    "pt": {"distributor": ["importador cacau em pó", "distribuidor ingredientes panificação"],
           "biscuit_bakery": ["fabricante biscoitos", "fabricante bolos industriais", "fabricante wafers"], "ice_cream": ["fabricante sorvetes"],
           "dairy_beverage": ["fabricante achocolatado", "fabricante sobremesas lácteas"], "cereal_snack": ["fabricante cereais matinais", "fabricante barras de cereais", "fabricante creme de avelã"],
           "chocolate_maker": ["fabricante chocolate", "fabricante confeitaria"]},
    "ar": {"distributor": ["كاكاو بودرة بالجملة", "مستورد كاكاو بودرة", "موزع مواد خام المخابز والحلويات"], "biscuit_bakery": ["مصنع بسكويت", "مصنع كيك ومعجنات", "مصنع ويفر"],
           "ice_cream": ["مصنع آيس كريم"], "dairy_beverage": ["مصنع مشروبات الشوكولاتة", "مصنع ألبان وحلويات"], "cereal_snack": ["مصنع حبوب إفطار", "مصنع كريمة الشوكولاتة"],
           "chocolate_maker": ["مصنع شوكولاتة", "مصنع حلويات"]},
}
SEG_ORDER = ["distributor", "biscuit_bakery", "dairy_beverage", "ice_cream", "cereal_snack", "chocolate_maker"]

BLOCK = re.compile(
    r"(^|\.)(wikipedia|wikimedia|wikidata|facebook|instagram|linkedin|youtube|twitter|x|pinterest|tiktok|amazon|ebay|alibaba|aliexpress|made-in-china|indiamart|tradekey|"
    r"europages|kompass|yellowpages|gelbeseiten|goyellow|11880|yelp|tripadvisor|indeed|glassdoor|stepstone|reddit|quora|medium|github|google|bing|yahoo|dnb|zoominfo|"
    r"crunchbase|bloomberg|reuters|forbes|tradeindia|exportersindia|globalsources|volza|panjiva|importyeti|trademap|statista|foodnavigator|foodbev|food-business|"
    r"confectionerynews|bakeryandsnacks|northdata|opencorporates|wlw|firmenwissen|openstreetmap|booking|etsy|walmart|tesco|aldi|lidl|carrefour|dhgate|"
    r"researchgate|academia|slideshare|scribd|issuu|pdfcoffee|apple|microsoft|archive|trustpilot|kayak|expedia|cylex|infobel|manta|bbb|mapquest|pagesjaunes|paginegialle|"
    r"paginasamarillas|goudengids|zlote-strony|yell|thomsonlocal|2gis|zoominfo|rocketreach|apollo|lusha|signalhire|leadiq|hunter|volza|exporthub|tridge|ec21|ecplaza|"
    r"foodmanufacturing|just-food|foodingredientsfirst|nutraingredients|bakeryinfo|candyindustry|zoominfo)\.[a-z.]+$|\.(gov|edu|mil)(\.[a-z]{2})?$", re.I)
SKIP_EXT = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|zip|jpe?g|png)(\?|$)", re.I)


def host_of(url):
    h = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    return h[4:] if h.startswith("www.") else h


def clean_title(title, host):
    parts = [p.strip() for p in re.split(r"\s[|\-–—:·•»]\s|\|", title or "") if p.strip()]
    label = re.sub(r"[^a-z0-9]", "", host.split(".")[0])
    match = [p for p in parts if label and label[:5] in re.sub(r"[^a-z0-9]", "", p.lower())]
    n = (match or parts[:1] or [host.split(".")[0].title()])[0]
    n = re.sub(r"(?i)^(home|startseite|welcome|willkommen|accueil|homepage|official site|official website)\b[\s|:\-–]*", "", n).strip()
    return (n if 2 <= len(n) <= 70 else host.split(".")[0].title())[:70]


# Toptancılar şehirde ilan verir: ülke geneli sorgulardan sonra büyük şehirlerle de aranır (sonraki turlarda sırayla)
CITIES = {"RU": ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань", "Краснодар", "Ростов-на-Дону", "Самара"],
          "BY": ["Минск", "Гомель", "Брест"], "KZ": ["Алматы", "Астана", "Шымкент", "Караганда"], "UZ": ["Ташкент", "Самарканд", "Наманган"],
          "KG": ["Бишкек", "Ош"], "TJ": ["Душанбе", "Худжанд"], "TM": ["Ашхабад"], "AZ": ["Bakı", "Gəncə"], "MN": ["Ulaanbaatar"],
          "IR": ["تهران", "تبریز", "مشهد", "اصفهان"], "IQ": ["بغداد", "أربيل", "البصرة"], "SY": ["دمشق", "حلب"], "JO": ["عمان", "إربد"],
          "EG": ["القاهرة", "الإسكندرية"], "MA": ["Casablanca", "Fès", "Tanger"], "DZ": ["Alger", "Oran", "Constantine"]}


def build_queries(countries, segments=None):
    """[(ülke, segment, sorgu)] — önce dağıtıcılar ve bisküvi/fırın, her ülke için yerel dil + İngilizce; en sonda şehir bazlı toptancı sorguları."""
    segs = [s for s in SEG_ORDER if not segments or s in segments]
    out = []
    for seg in segs:
        for cc in countries:
            lang = LANG_OF.get(cc, "en")
            loc = COUNTRY_LOCAL.get(cc) or COUNTRY_EN.get(cc, cc)
            for t in TERMS.get(lang, TERMS["en"])[seg][:2 if lang != "en" else 3]:
                out.append((cc, seg, f"{t} {loc}"))
            if lang != "en":  # birçok firma İngilizce de yayın yapar (özellikle ihracatçılar/distribütörler)
                en = TERMS["en"][seg][0]
                out.append((cc, seg, f"{en} {COUNTRY_EN.get(cc, cc)}"))
    if "distributor" in segs:
        for cc in countries:
            terms = TERMS.get(LANG_OF.get(cc, "en"), TERMS["en"])["distributor"][:2]
            out += [(cc, "distributor", f"{t} {city}") for city in CITIES.get(cc, []) for t in terms]
    seen, uniq = set(), []
    for q in out:
        if q[2] not in seen:
            seen.add(q[2])
            uniq.append(q)
    return uniq


# Kota: (miktar, dönem) — dönem "month" her ay, "day" her gün yenilenir, "all" tek seferlik hak
QUOTA = {"serper": (2500, "all"), "tavily": (1000, "month"), "brave": (1000, "month"), "google": (100, "day")}


def providers():
    """Tanımlı arama servisleri, kullanım sırasıyla. Serper (ülkeye özel Google sonuçları) önce, bitince Tavily (her ay yenilenir)."""
    out = []
    if secrets_util.get("serper_api_key"):
        out.append("serper")
    if secrets_util.get("tavily_api_key"):
        out.append("tavily")
    if secrets_util.get("brave_api_key"):
        out.append("brave")
    if secrets_util.get("google_api_key") and secrets_util.get("google_cx"):
        out.append("google")
    return out


def provider():
    p = providers()
    return p[0] if p else None


def _get_json(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _post_json(url, body, headers=None, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def search(prov, query, country=None, count=10):
    """[{'title','url','snippet'}] döner."""
    lang = LANG_OF.get(country or "", "en")
    if prov == "serper":  # Google sonuçları; gl=ülke, hl=dil: "какао порошок оптом" Kazakistan'daki Google'da aranır
        body = {"q": query, "num": min(count, 10), **({"gl": country.lower()} if country and len(country) == 2 else {}), "hl": lang}
        d = _post_json("https://google.serper.dev/search", body, {"X-API-KEY": secrets_util.get("serper_api_key")})
        return [{"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")} for r in d.get("organic", [])]
    if prov == "tavily":
        body = {"query": query, "max_results": min(count, 20), "search_depth": "basic", "topic": "general"}
        name = COUNTRY_EN.get(country or "", "").lower()
        hdr = {"Authorization": "Bearer " + secrets_util.get("tavily_api_key")}
        try:
            d = _post_json("https://api.tavily.com/search", {**body, **({"country": name} if name else {})}, hdr)
        except urllib.error.HTTPError as e:
            if e.code != 400 or not name:
                raise
            d = _post_json("https://api.tavily.com/search", body, hdr)  # ülke adı servisin listesinde yoksa ülkesiz dene
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")} for r in d.get("results", [])]
    if prov == "brave":
        q = urllib.parse.urlencode({"q": query, "count": min(count, 20), "search_lang": lang if lang != "pt" else "pt-br", **({"country": country.lower()} if country and len(country) == 2 else {})})
        d = _get_json("https://api.search.brave.com/res/v1/web/search?" + q, {"X-Subscription-Token": secrets_util.get("brave_api_key")})
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")} for r in (d.get("web", {}) or {}).get("results", [])]
    if prov == "google":
        q = urllib.parse.urlencode({"key": secrets_util.get("google_api_key"), "cx": secrets_util.get("google_cx"), "q": query, "num": min(count, 10),
                                    **({"gl": country.lower()} if country and len(country) == 2 else {})})
        d = _get_json("https://www.googleapis.com/customsearch/v1?" + q)
        return [{"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")} for r in d.get("items", [])]
    raise RuntimeError("Arama anahtarı tanımlı değil")


def quota_left(con, prov):
    """Kalan sorgu hakkı (kaba, bu sistemin kullandığına göre) ve sayaç dönemi."""
    con.execute("CREATE TABLE IF NOT EXISTS api_usage(period TEXT, provider TEXT, n INTEGER DEFAULT 0, PRIMARY KEY(period, provider))")
    limit, per = QUOTA.get(prov, (100, "day"))
    period = {"all": "all", "month": dt.date.today().strftime("%Y-%m")}.get(per, dt.date.today().isoformat())
    n = (con.execute("SELECT n FROM api_usage WHERE period=? AND provider=?", (period, prov)).fetchone() or [0])[0]
    return limit - n, period


def exhaust(con, prov, period):
    """Servis 'kredi bitti / yetkisiz' dediğinde bu dönemin hakkını bitmiş say (bir sonraki servise geçilir)."""
    limit = QUOTA.get(prov, (100, "day"))[0]
    con.execute("INSERT INTO api_usage(period,provider,n) VALUES(?,?,?) ON CONFLICT(period,provider) DO UPDATE SET n=?", (period, prov, limit, limit))


def use_quota(con, prov, period):
    con.execute("INSERT INTO api_usage(period,provider,n) VALUES(?,?,1) ON CONFLICT(period,provider) DO UPDATE SET n=n+1", (period, prov))


def candidates(results):
    """Arama sonuçlarından firma sitesi adayları: [(host, ad, kısa açıklama, url)] — dizin/pazaryeri/haber siteleri elenir."""
    out, seen = [], set()
    for r in results:
        url = r.get("url", "")
        if not url.startswith("http") or SKIP_EXT.search(url):
            continue
        h = host_of(url)
        if not h or h in seen or BLOCK.search(h):
            continue
        seen.add(h)
        out.append((h, clean_title(r.get("title", ""), h), " ".join((r.get("snippet") or "").split())[:300], f"https://{h}"))
    return out
