"""Kanıtlı alıcı keşfi: içinde kakao tozu / kakao yağı geçen ürünleri satan markalar (OpenFoodFacts açık verisi).

Mantık bir ihracatçının düşündüğü gibi: "Kim kakao alıyor?" sorusunun en sağlam cevabı, ürün etiketinde kakao yazan firmalardır.
Her ülke için o ülkede satılan kakaolu ürünler çekilir, markaya göre toplanır; market özel markaları ve dev çokuluslu gruplar
(kakaoyu doğrudan büyük işleyicilerden alırlar) elenir. Kalan markaların web sitesi Wikidata'dan ya da alan adı tahminiyle
(sayfa başlığında marka adı geçiyorsa) bulunur. Sonuç: "12 ürününde kakao tozu var, ör. 'Schoko Kekse'" gerekçesiyle firma.
"""
import json
import re
import time
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import crawler

OFF_SEARCH2 = "https://search.openfoodfacts.org/search"  # yeni arama servisi: hızlı, sınırı gevşek
OFF_SEARCH = "https://world.openfoodfacts.org/cgi/search.pl"  # klasik arama: yedek
UA = "ImestaFoodBot/1.0 (+https://imestafood.com; B2B supplier research)"
OFF_DELAY = 7  # klasik arama sınırı: dakikada ~10 istek
OFF_DELAY2 = 1

INGREDIENTS = {  # OFF içerik etiketi -> (Türkçe, İngilizce, Almanca)
    "en:cocoa-powder": ("kakao tozu", "cocoa powder", "Kakaopulver"),
    "en:cocoa-butter": ("kakao yağı", "cocoa butter", "Kakaobutter"),
}
COUNTRY_TAG = {"GB": "united-kingdom", "US": "united-states", "AE": "united-arab-emirates", "KR": "south-korea", "CZ": "czech-republic",
               "ZA": "south-africa", "NZ": "new-zealand", "SA": "saudi-arabia"}
CCTLD = {"GB": "co.uk", "JP": "co.jp", "ZA": "co.za", "NZ": "co.nz", "AU": "com.au", "BR": "com.br", "MX": "com.mx", "TR": "com.tr", "US": "com", "IN": "in", "KR": "co.kr"}

# OFF kategori etiketi -> crawler kategorisi (teklif önerisi ve puanlama aynı sözlüğü kullanır)
CAT_MAP = [("biscuit", r"biscuit|cookie|cracker"), ("wafer", r"wafer"), ("cake", r"cake|brownie|muffin|pastr|viennoiserie"),
           ("bakery", r"bread|bakery|croissant|brioche"), ("ice_cream", r"ice-cream|frozen-dessert|sorbet"),
           ("dairy", r"dair|yogurt|pudding|dessert|milk(?!-chocolate)|cream-dessert"), ("beverage", r"beverage|drink|cocoa-and-chocolate-powders|hot-chocolate"),
           ("cereal_snack", r"cereal|muesli|granola|cereal-bars|protein-bars|energy-bars"), ("spread", r"spread|hazelnut|filling"),
           ("confectionery", r"confection|candies|candy|bonbon|marzipan"), ("chocolate", r"chocolate")]
CAT_SEGMENT = [("ice_cream", "ice_cream"), ("biscuit", "biscuit_bakery"), ("wafer", "biscuit_bakery"), ("cake", "biscuit_bakery"),
               ("bakery", "biscuit_bakery"), ("dairy", "dairy_beverage"), ("beverage", "dairy_beverage"), ("cereal_snack", "cereal_snack"),
               ("spread", "cereal_snack"), ("confectionery", "confectionery"), ("chocolate", "chocolate_maker")]

# Market özel markaları: üreticisi belli değil, satın almayı market yapar.
RETAIL_BRANDS = """lidl aldi aldi nord aldi süd aldi sud rewe rewe bio rewe beste wahl ja! edeka edeka bio gut & günstig gut&günstig k-classic kaufland penny netto
netto marken-discount dm dmbio dm bio rossmann enerbio alnatura tegut globus real carrefour carrefour bio carrefour classic auchan leclerc marque repère
casino intermarché monoprix u système u franprix crownfield choco nussa sondey fin carré carré fin lidl favorina milbona gelatelli mister choc bellarom
vemondo alesto crusti croc pilos chef select deluxe combino italiamo snack day tastino w5 cien belbake moser roth choceur milsani rio d'oro knusperone
gletscherkrone sweet valley biscotto tandil park lane specially selected cucina nobile westminster happy harvest tesco tesco finest sainsbury's asda
morrisons waitrose co-op m&s marks & spencer albert heijn ah jumbo plus hema delhaize colruyt boni everyday biedronka mercadona hacendado dia eroski
coop migros spar billa clever hofer s-budget esselunga conad despar simpl eco+ tous les jours ica rema 1000 kiwi x-tra prix garantie preferred selection
kaufland k-bio ja tip lidl deluxe aldi gourmet nur nur natur bio bio organic aldi bio rewe feine welt edeka herzstücke gut bio""".split("\n")
# Dev çokuluslu gruplar ve kakao işleyicileri (Türk ihracatçı için gerçekçi hedef değil / rakip).
MULTI_BRANDS = """nestlé nestle nesquik kitkat kit kat mondelez mondelēz milka oreo lu cadbury toblerone côte d'or cote d'or suchard ferrero ferrero rocher kinder
nutella mars twix snickers m&m's m&ms bounty maltesers galaxy kellogg's kelloggs kellogg general mills nature valley unilever magnum ben & jerry's
algida langnese carte d'or cornetto häagen-dazs haagen-dazs lindt lindt & sprüngli lindt & sprungli hershey's hershey pepsico quaker danone
barry callebaut callebaut cargill olam ofi mondelez international nestlé france nestle france societe des produits nestle s.a. mars polska
ferrero technical services srl mondelez schweiz gmbh magnum icc global services b.v. weetabix weetabix limited ritter sport storck merci
haribo kraft heinz coca-cola""".split("\n")
# Bir kelimesi geçen her marka elenir (ör. "Lindt Excellence", "J. D. Gross (Lidl)", "Kinder Bueno").
EXCLUDE_WORDS = set("""lidl aldi rewe edeka kaufland carrefour tesco auchan penny netto rossmann mercadona hacendado biedronka migros
nestle nesquik kitkat milka oreo cadbury toblerone ferrero kinder nutella twix snickers kellogg kellogg's unilever magnum
langnese algida danone hershey hershey's lindt mondelez mentos perfetti barilla knorr nescafe nescafé jumbo ah huismerk glico pocky
prince trader picnic allegro ulker ülker eti belvita winiary slimfast mcvitie's""".split())
EXCLUDE_PHRASES = ["weight watchers", "private label", "eigen merk", "eigenmarke", "marque distributeur", "albert heijn", "j d gross", "j.d. gross", "j.d: gross", "j. d. gross", "cereal partners", "general mills", "fairglobe", "mars inc", "mars wrigley",
                   "mulino bianco", "pavesi"]


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return re.sub(r"\s+", " ", "".join(ch for ch in s if not unicodedata.combining(ch))).strip(" .,-")


def _phrases(block):
    """Çok satırlı listeyi tek tek marka adlarına böler (çok kelimeli adlar korunur)."""
    out = set()
    for line in block:
        words = line.split()
        out.update(fold(w) for w in words)
        out.update(fold(" ".join(words[i:i + n])) for n in (2, 3, 4) for i in range(len(words) - n + 1))
    return out


EXCLUDE = _phrases(RETAIL_BRANDS) | _phrases(MULTI_BRANDS)
EXCLUDE_PREFIX = tuple(fold(x) for x in ("nestl", "mondel", "ferrero", "mars ", "kellogg", "unilever", "lidl", "aldi", "carrefour", "tesco", "rewe", "edeka", "auchan"))


def excluded(brand):
    b = fold(brand)
    words = set(re.findall(r"[\w'&.]+", b))
    return (not b or len(b) < 3 or b in EXCLUDE or b.startswith(EXCLUDE_PREFIX) or bool(words & EXCLUDE_WORDS)
            or any(p in b for p in EXCLUDE_PHRASES))


def country_tag(cc):
    import discover
    name = COUNTRY_TAG.get(cc) or discover.COUNTRY_EN.get(cc, "").lower().replace(" ", "-")
    return f"en:{name}" if name else None


def _get_json(url, timeout=60):
    _, text = crawler.fetch(url, timeout=timeout)
    return json.loads(text)


def search_products(cc, ingredient, page=1, size=100, getter=_get_json, sleep=time.sleep):
    """Bir sayfa ürün: (ürünler, son_sayfa_mı, sonraki istekten önce beklenecek sn). Önce yeni servis, olmazsa klasik arama."""
    tag = country_tag(cc)
    if not tag:
        return [], True, 0
    try:
        d = getter(OFF_SEARCH2 + "?" + urllib.parse.urlencode({"q": f'ingredients_tags:"{ingredient}" AND countries_tags:"{tag}"', "page": page,
                                                               "page_size": size, "fields": "brands,brand_owner,product_name,categories_tags"}))
        hits = [dict(h, brands=", ".join(h["brands"]) if isinstance(h.get("brands"), list) else h.get("brands")) for h in d["hits"]]
        return hits, page >= (d.get("page_count") or 0), OFF_DELAY2
    except Exception:
        pass
    q = {"action": "process", "json": 1, "page_size": size, "page": page,
         "tagtype_0": "ingredients", "tag_contains_0": "contains", "tag_0": ingredient,
         "tagtype_1": "countries", "tag_contains_1": "contains", "tag_1": tag,
         "fields": "brands,brand_owner,product_name,categories_tags,manufacturing_places"}
    url = OFF_SEARCH + "?" + urllib.parse.urlencode(q)
    for wait in (20, 45, 0):  # meşgul sunucuda (503/429) bekleyip tekrar dene
        try:
            items = getter(url).get("products", [])
            return items, len(items) < size, OFF_DELAY
        except Exception as e:
            if not wait or not re.search(r"\b(429|50[234])\b|timed out", str(e)):
                raise
            sleep(wait)


GENERIC_CATS = re.compile(r"^en:(snacks|sweet-snacks|salty-snacks|plant-based-foods.*|cocoa-and-its-products|desserts|frozen-foods|foods?)$")


def categories(tags):
    out = {}
    for t in tags or []:
        if GENERIC_CATS.match(t):
            continue
        for k, rx in CAT_MAP:
            if re.search(rx, t):
                out[k] = out.get(k, 0) + 1
                break
    return out


def segment_of(cats):
    """En çok ürünün düştüğü kategori; eşitlikte CAT_SEGMENT sırası (sanayi alıcısı önce)."""
    best = max(CAT_SEGMENT, key=lambda ks: (cats.get(ks[0], 0), -CAT_SEGMENT.index(ks)))
    return best[1] if cats.get(best[0]) else "confectionery"


def aggregate(products_by_ing):
    """{ingredient: [ürün]} → {marka_anahtarı: kanıt} — market markaları ve çokuluslular hariç."""
    brands = {}
    for ing, products in products_by_ing.items():
        for p in products:
            raw = (p.get("brand_owner") or (p.get("brands") or "").split(",")[0]).strip()
            alt = [b.strip() for b in (p.get("brands") or "").split(",") if b.strip()]
            if excluded(raw) or any(excluded(b) and fold(b) in EXCLUDE for b in alt[:2]):
                continue
            key = fold(re.sub(r"\b(gmbh|ag|kg|bv|b\.v\.|srl|s\.r\.l\.|sas|sa|ltd|limited|spa|s\.p\.a\.|sp\. z o\.o\.|co)\b\.?", "", raw, flags=re.I))
            if len(key) < 3:
                continue
            e = brands.setdefault(key, {"brand": raw, "n": 0, "ingredients": [], "examples": [], "cats": {}, "names": set()})
            if p.get("product_name") and fold(p["product_name"]) not in e["names"]:
                e["names"].add(fold(p["product_name"]))
                e["n"] += 1
                if len(e["examples"]) < 4:
                    e["examples"].append(p["product_name"].strip()[:60])
            elif not p.get("product_name"):
                e["n"] += 1
            if ing not in e["ingredients"]:
                e["ingredients"].append(ing)
            for k, v in categories(p.get("categories_tags")).items():
                e["cats"][k] = e["cats"].get(k, 0) + v
    for e in brands.values():
        e.pop("names")
    return brands


# ------------------------------------------------------------------ web sitesi bulma
PARKED = re.compile(r"domainname|domain (is )?for sale|buy this domain|domain kaufen|parked|this domain|sedo|godaddy|hugedomains|dan\.com|under construction|coming soon", re.I)


def slug_variants(brand):
    out = []
    for v in (_slugs(brand) + _slugs(umlaut(brand))):
        if v not in out:
            out.append(v)
    return out[:4]


def _slugs(brand):
    b = fold(brand).replace("&", " und ").replace("'", "")
    words = re.findall(r"[a-z0-9]+", b)
    words = [w for w in words if w not in ("gmbh", "ag", "kg", "co", "bv", "srl", "sa", "sas", "ltd", "spa", "und", "the")] or words
    out = []
    for s in ("".join(words), "-".join(words), words[0] if words else ""):
        if len(s) >= 3 and s not in out:
            out.append(s)
    return out[:3]


# Metin fold() edilmiş (aksansız, küçük harf) aranır. "cookie" yok: her sitenin çerez uyarısında geçer.
FOOD = re.compile(r"\b(food|lebensmittel|voeding|aliment\w*|nutrition|recipes?|rezepte?|recettes?|ricett\w*|recetas?|snacks?|chocolat\w*|schokolade|czekolad\w*|"
                  r"cacao|kakao|cocoa|biscuits?|kekse?|koek\w*|ciastk\w*|cakes?|kuchen|desserts?|dairy|molkerei|zuivel|ice ?cream|gelato|speiseeis|lody|"
                  r"cereals?|musli|muesli|granola|bakery|backerei|bakkerij|piekarni\w*|confectionery|su(?:ß|ss)waren|snoep|dolci|pasticceria|gateaux?|wafers?|waffeln)\b")


def food_terms(html):
    """Sayfanın görünen metninde geçen farklı gıda terimleri (en az 2 tane = gıda firması sitesi)."""
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "")
    return set(FOOD.findall(fold(re.sub(r"<[^>]+>", " ", text)[:200000])))


def page_matches(brand, final_url, html):
    title = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    t = fold(title.group(1) if title else "")
    head = fold((html or "")[:20000])
    if PARKED.search(t) or PARKED.search(head[:3000]):
        return False
    return (bool(tokens_of(brand)) and host_matches(brand, final_url) and any(w in t for w in tokens_of(brand)[:2])
            and len(food_terms(html)) >= 2)


def umlaut(s):
    return (s or "").lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))


def tokens_of(brand):
    return [w for w in re.findall(r"[a-z0-9]{3,}", fold(brand)) if w not in ("gmbh", "und", "the", "and", "sas", "srl", "spa", "ltd")]


# "Bakery" → bakery.com gibi genel kelime alan adları marka sitesi değildir.
GENERIC_HOSTS = {"food", "foods", "bakery", "chocolate", "chocolates", "snack", "snacks", "protein", "proteinbar", "cookies", "cake", "cakes",
                 "candy", "sweets", "dessert", "icecream", "cereal", "muesli", "organic", "bio", "vegan", "healthy", "nutrition", "shop", "store"}


def host_matches(brand, url):
    """Alan adı marka adıyla başlamalı (park edilmiş, genel ya da alakasız siteleri eler)."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    name = crawler.sld(host).replace("-", "")
    if PARKED.search(host) or name in GENERIC_HOSTS:
        return False
    for toks in {tuple(tokens_of(brand)), tuple(tokens_of(umlaut(brand)))}:
        if toks and (name.startswith(toks[0]) or "".join(toks) in name or (len(name) >= 4 and name in "".join(toks))):
            return True
    return False


def guess_site(brand, cc, fetcher=crawler.fetch):
    tlds = [CCTLD.get(cc, (cc or "com").lower()), "com", "eu"]
    for s in slug_variants(brand):
        for tld in dict.fromkeys(tlds):
            url = f"https://www.{s}.{tld}/"
            try:
                final, html = fetcher(url, timeout=8)
            except Exception:
                continue
            if page_matches(brand, final, html):
                return final
    return None


COMPANY_DESC = re.compile(r"compan|brand|manufactur|producer|food|confection|biscuit|chocolate|dairy|bakery|ice cream|cereal|business|enterprise|"
                          r"unternehmen|hersteller|marque|entreprise|azienda|bedrijf|firma|empresa", re.I)


def wikidata_site(brand, getter=_get_json):
    try:
        r = getter("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbsearchentities", "search": brand, "language": "en", "type": "item", "limit": 5, "format": "json"}), timeout=20)
        ids = [x["id"] for x in r.get("search", []) if COMPANY_DESC.search(x.get("description", ""))][:3]
        if not ids:
            return None
        ents = getter("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbgetentities", "ids": "|".join(ids), "props": "claims", "format": "json"}), timeout=20).get("entities", {})
        for i in ids:
            for cl in ents.get(i, {}).get("claims", {}).get("P856", []):
                v = cl.get("mainsnak", {}).get("datavalue", {}).get("value")
                if v and host_matches(brand, v) and is_food_site(v):
                    return v
    except Exception:
        return None
    return None


def is_food_site(url, fetcher=crawler.fetch):
    """Gıda firması sitesi mi? (Wikidata'daki aynı adlı bisiklet/tenis markalarını eler.)"""
    try:
        _, html = fetcher(url, timeout=15)
    except Exception:
        return False
    return len(food_terms(html)) >= 2


def find_site(brand, cc):
    return wikidata_site(brand) or guess_site(brand, cc)


def evidence_text(ev):
    ings = " ve ".join(INGREDIENTS[i][0] for i in ev["ingredients"] if i in INGREDIENTS) or "kakao"
    ex = f" (ör. {', '.join(chr(8220) + x + chr(8221) for x in ev['examples'][:2])})" if ev.get("examples") else ""
    return f"{ev['n']} ürününde {ings} var{ex}"


def harvest(countries, log=print, cancel=None, pages=8, min_products=1, max_single=80, workers=12, sleep=time.sleep, getter=_get_json, site_finder=find_site):
    """Ülke başına kakaolu ürünleri çekip marka listesini (kanıt + web sitesi) döner: [(cc, kanıt)]."""
    found = []
    for cc in countries:
        if cancel and cancel.is_set():
            break
        by_ing = {}
        for ing in INGREDIENTS:
            for page in range(1, pages + 1):
                if cancel and cancel.is_set():
                    break
                try:
                    items, last, wait = search_products(cc, ing, page, getter=getter, sleep=sleep)
                except Exception as e:
                    log(f"  {cc} {INGREDIENTS[ing][0]}: veri alınamadı ({str(e)[:80]}), atlanıyor")
                    items, last, wait = [], True, OFF_DELAY
                by_ing.setdefault(ing, []).extend(items)
                sleep(wait)
                if last:
                    break
        brands = [e for e in aggregate(by_ing).values() if e["n"] >= min_products]
        brands.sort(key=lambda e: -e["n"])
        total = len(brands)
        brands = [e for e in brands if e["n"] >= 2] + [e for e in brands if e["n"] < 2][:max_single]  # tek ürünlü uzun kuyruk sınırlı
        log(f"  {cc}: {sum(len(v) for v in by_ing.values())} kakaolu ürün → {total} aday marka (market markaları ve dev gruplar elendi). "
            f"En güçlü {len(brands)} markanın web sitesi aranıyor…")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            sites = list(ex.map(lambda e: None if (cancel and cancel.is_set()) else site_finder(e["brand"], cc), brands))
        for e, site in zip(brands, sites):
            e["website"] = site
            e["segment"] = segment_of(e["cats"])
            found.append((cc, e))
        log(f"  {cc}: {sum(1 for s in sites if s)} markanın web sitesi bulundu.")
    return found
