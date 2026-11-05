"""Odak pazarlar: İmesta'nın sattığı ülkeler ve her biri için ihracatçı notları.

Notlar satıcının masasındaki kopya kâğıdı gibidir: hangi dilde yazılır, mal nereden gider, para nasıl gelir, hangi belge sorulur.
Mevzuat ve yaptırımlar değişir; sevkiyat öncesi bankanız ve gümrük müşavirinizle teyit edin.
"""

DEFAULT_FOCUS = ["RU", "BY", "AZ", "IR", "IQ", "SY", "JO", "EG", "MA", "DZ"]

# lang: e-posta dili (templates/<lang>_*.txt) · route: lojistik · pay: ödeme · deal: Türkiye ile ticaret anlaşması · docs/tips: belge ve satış ipuçları
PROFILE = {
    "RU": {"lang": "ru", "route": "Deniz: Ambarlı/Mersin → Novorossiysk; kara: Gürcistan (Yukarı Lars) üzerinden",
           "pay": "Batılı bankalar üzerinden zor; TL/RUB/CNY ile çalışan bankalar ya da peşin ödeme. Her ödemede yaptırım kontrolü",
           "deal": "Serbest ticaret anlaşması yok (Avrasya Ekonomik Birliği tarifesi)",
           "docs": "EAC uygunluk beyanı, Rusça etiket, analiz sertifikası (COA)",
           "tips": "Rusça yazın. Sanayi alıcısı tedarikçi değiştirmeden önce numune ve uzun deneme ister; Avrupa'dan gelen ürünün yerine geçen, Türkiye'den hızlı teslim edilen kakao ilgisini çeker."},
    "BY": {"lang": "ru", "route": "Kara: Rusya ya da Gürcistan–Rusya üzerinden; deniz + kara: Novorossiysk",
           "pay": "Rusya'ya benzer kısıtlar; peşin ya da TL/RUB ile çalışan bankalar. Her ödemede yaptırım kontrolü",
           "deal": "Serbest ticaret anlaşması yok (Avrasya Ekonomik Birliği tarifesi)",
           "docs": "EAC uygunluk beyanı, Rusça etiket, COA",
           "tips": "Rusça yazın. Kommunarka, Spartak gibi devlet ağırlıklı fabrikalar ihale/teklif usulüyle alır: resmi fiyat teklifi ve spesifikasyon şart."},
    "AZ": {"lang": "tr", "route": "Kara: Gürcistan üzerinden (Sarp–Batum–Tiflis–Bakü) 4–6 gün; Nahçıvan'a doğrudan",
           "pay": "Banka transferi sorunsuz; yeni alıcıda peşin ya da akreditif",
           "deal": "Türkiye–Azerbaycan Tercihli Ticaret Anlaşması (bazı ürünlerde gümrük indirimi; kakao kapsamını teyit edin)",
           "docs": "Menşe şahadetnamesi, sağlık sertifikası, COA",
           "tips": "Türkçe yazın, telefonda Türkçe konuşun: en büyük avantajınız. Azersun gibi holdingler toplu ve düzenli alır."},
    "IR": {"lang": "en", "route": "Kara: Gürbulak/Kapıköy sınır kapıları, Tebriz'e 2–3 gün",
           "pay": "ABD yaptırımları nedeniyle bankalar çekingen; gıda insani istisnada ama ödeme kanalı (TL, döviz bürosu, mahsuplaşma) önceden netleşmeli",
           "deal": "Türkiye–İran Tercihli Ticaret Anlaşması (sınırlı ürün listesi; kakaoyu teyit edin)",
           "docs": "İran Gıda ve İlaç Kurumu (IFDA) kaydı alıcı tarafında, menşe şahadetnamesi, helal sertifikası, COA",
           "tips": "İngilizce yazın; teknik müdürler iyi İngilizce bilir. Kalleh, Minoo, Shirin Asal gibi büyükler sabit kalite ve sürekli stok ister."},
    "IQ": {"lang": "ar", "route": "Kara: Habur kapısı, Erbil/Duhok 1–2, Bağdat 3–4 gün",
           "pay": "Peşin ya da akreditif; Kuzey Irak'ta banka transferi daha kolay",
           "deal": "Serbest ticaret anlaşması yok",
           "docs": "Irak Uygunluk Belgesi (COC / VoC programı), menşe şahadetnamesi, helal sertifikası",
           "tips": "Arapça yazın; Kuzey Irak'ta Türkçe de çok işe yarar. Toptancılar Türkiye malını tanır, fiyat ve hızlı teslimle kazanılır."},
    "SY": {"lang": "ar", "route": "Kara: Cilvegözü/Öncüpınar, Halep 1 gün",
           "pay": "Yaptırım durumu son dönemde değişti; ödeme öncesi bankanızla mutlaka teyit edin, ilk işlerde peşin çalışın",
           "deal": "Serbest ticaret anlaşması askıda (2011'den beri)",
           "docs": "Menşe şahadetnamesi, sağlık sertifikası, helal sertifikası",
           "tips": "Arapça yazın. Yeniden kurulan şekerleme ve bisküvi atölyeleri küçük ama hızlı büyüyen alıcılar; 25 kg çuvalla küçük partiler önerin."},
    "JO": {"lang": "ar", "route": "Deniz: Mersin → Akabe; kara: Suriye üzerinden",
           "pay": "Banka transferi ve akreditif sorunsuz",
           "deal": "Serbest ticaret anlaşması 2018'de feshedildi (genel tarife)",
           "docs": "Ürdün Gıda ve İlaç Kurumu (JFDA) uygunluğu, menşe şahadetnamesi, helal sertifikası, COA",
           "tips": "Arapça ya da İngilizce yazın. Helva, tatlı ve süt sanayi kakao tozu ve kakao yağı kullanır; Körfez'e de satan üreticiler hacimli."},
    "EG": {"lang": "ar", "route": "Deniz: Mersin/Ambarlı → İskenderiye/Port Said, 3–5 gün",
           "pay": "Döviz kıtlığı dönemlerinde akreditif açılması gecikebilir; ödeme şartını baştan netleştirin",
           "deal": "Türkiye–Mısır Serbest Ticaret Anlaşması (EUR.1 ile gümrük avantajı olabilir)",
           "docs": "EUR.1 dolaşım belgesi, NFSA kaydı (alıcı), helal sertifikası, COA",
           "tips": "Arapça ya da İngilizce yazın. Edita, Bisco Misr, Juhayna gibi büyükler ihale usulü alır; numune ve TDS ile başvurun."},
    "MA": {"lang": "fr", "route": "Deniz: Ambarlı/Mersin → Kazablanka/Tanca Med, 7–10 gün",
           "pay": "Banka transferi ve vesaik mukabili yaygın",
           "deal": "Türkiye–Fas Serbest Ticaret Anlaşması (EUR.1 ile gümrük avantajı olabilir)",
           "docs": "EUR.1 dolaşım belgesi, ONSSA uygunluğu, helal sertifikası, COA",
           "tips": "Fransızca yazın. Bisküvi, çikolata ve süt sanayi gelişmiş; Avrupa fiyatının altında, kısa teslimli tedarik ilgi görür."},
    "DZ": {"lang": "fr", "route": "Deniz: Ambarlı/Mersin → Cezayir/Oran/Annaba, 7–10 gün",
           "pay": "İthalatta akreditif ya da vesaik mukabili ödeme zorunlu; ithalat lisansı/izin dönemlerini takip edin",
           "deal": "Serbest ticaret anlaşması yok",
           "docs": "Menşe şahadetnamesi, sağlık sertifikası, helal sertifikası, COA",
           "tips": "Fransızca yazın. İthalat kuralları sık değişir; alıcının ithalat iznini sorun. Süt (çikolatalı süt) ve bisküvi sanayi büyük kakao tozu alıcısı."},
}

FLAG = {cc: "".join(chr(0x1F1E6 + ord(ch) - 65) for ch in cc) for cc in PROFILE}


def flag(cc):
    cc = (cc or "").upper()
    return FLAG.get(cc) or ("".join(chr(0x1F1E6 + ord(ch) - 65) for ch in cc) if len(cc) == 2 and cc.isalpha() else "")


def email_lang(cc, available):
    lang = PROFILE.get((cc or "").upper(), {}).get("lang", "en")
    return lang if lang in available else "en"
