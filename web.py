#!/usr/bin/env python3
"""Imesta Food lead sistemi – web arayüzü (sadece standart kütüphane).

Çalıştır:  python3 web.py            → http://127.0.0.1:8765
İnternete açacaksanız WEB_PASSWORD ortam değişkeni belirleyin (HTTP Basic şifre, kullanıcı adı: imesta).
Renkler/logo: config.json içindeki "theme" bölümü.
"""
import argparse
import base64
import contextlib
import hmac
import html
import io
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import leads
from leads import STATUSES, SEGMENTS, FOLLOWUP_DAYS

esc = html.escape
STATUS_TR = {"new": "Yeni", "contacted": "İletişime geçildi", "replied": "Yanıt verdi", "sample": "Numune",
             "negotiation": "Pazarlık", "won": "Kazanıldı", "lost": "Kaybedildi", "nurture": "Beklemede"}
SEGMENT_TR = {"chocolate_maker": "Çikolata üreticisi", "confectionery": "Şekerleme / bisküvi", "distributor": "Distribütör",
              "bakery_ingredient": "Pastane / fırın malzemesi", "ice_cream": "Dondurma", "dairy_beverage": "Süt / içecek",
              "retail_craft": "Butik / perakende", "other": "Diğer"}
KIND_TR = {"email": "E-posta", "call": "Arama", "sample": "Numune", "meeting": "Görüşme", "note": "Not"}

JOB = {"running": False, "name": "", "log": ""}
JOB_LOCK = threading.Lock()


def css():
    t = {"brand": "#3B2418", "accent": "#C8963E", "cream": "#F6EFE6", "cocoa": "#6F4E37", **leads.config().get("theme", {})}
    return f"""
:root{{--brand:{t['brand']};--accent:{t['accent']};--cream:{t['cream']};--cocoa:{t['cocoa']};--ink:#2b1d14;--line:#e3d6c6;--card:#fffdf9}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--cream);color:var(--ink);font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}}
a{{color:var(--cocoa)}}h1,h2,h3{{font-family:Georgia,'Times New Roman',serif;color:var(--brand);margin:.2em 0 .5em}}
header{{background:var(--brand);color:#fff;padding:0 24px;display:flex;align-items:center;gap:28px;flex-wrap:wrap;border-bottom:4px solid var(--accent)}}
header .logo{{font:700 22px Georgia,serif;letter-spacing:.5px;padding:14px 0;color:#fff;text-decoration:none;display:flex;align-items:center;gap:10px}}
header .logo img{{height:34px}}header .logo b{{color:var(--accent)}}
nav a{{color:#e9dccb;text-decoration:none;padding:18px 12px;display:inline-block}}nav a.on,nav a:hover{{color:#fff;box-shadow:inset 0 -3px var(--accent)}}
main{{max-width:1200px;margin:24px auto;padding:0 16px}}
.grid{{display:grid;gap:14px}}.kpis{{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;box-shadow:0 1px 2px rgba(59,36,24,.06)}}
.kpi b{{display:block;font:700 30px Georgia,serif;color:var(--brand)}}.kpi span{{color:var(--cocoa);font-size:13px}}
.kanban{{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(210px,1fr);gap:12px;overflow-x:auto;padding-bottom:8px}}
.col{{background:#efe4d4;border-radius:10px;padding:10px;min-height:120px}}.col h4{{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.5px;color:var(--cocoa);display:flex;justify-content:space-between}}
.lead{{display:block;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;padding:8px 10px;margin-bottom:8px;text-decoration:none;color:var(--ink)}}
.lead small{{color:var(--cocoa);display:block}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
th{{background:var(--brand);color:#fff;text-align:left;padding:9px 10px;font-size:13px}}td{{padding:8px 10px;border-top:1px solid var(--line);vertical-align:top}}tr:hover td{{background:#faf3e8}}
.badge{{display:inline-block;min-width:34px;text-align:center;border-radius:99px;padding:1px 8px;font-weight:700;color:#fff;background:var(--cocoa)}}
.badge.hi{{background:#2e7d32}}.badge.mid{{background:var(--accent);color:#2b1d14}}
.pill{{display:inline-block;padding:1px 9px;border-radius:99px;background:#efe4d4;color:var(--brand);font-size:12px}}
form.inline{{display:flex;gap:8px;flex-wrap:wrap;align-items:end}}label{{font-size:12px;color:var(--cocoa);display:block}}
input,select,textarea{{font:inherit;padding:7px 9px;border:1px solid #cdbba5;border-radius:7px;background:#fff;max-width:100%}}textarea{{width:100%}}
button,.btn{{font:inherit;font-weight:600;padding:8px 14px;border:0;border-radius:7px;background:var(--brand);color:#fff;cursor:pointer;text-decoration:none;display:inline-block}}
button.alt,.btn.alt{{background:var(--accent);color:#2b1d14}}button.ghost{{background:#efe4d4;color:var(--brand)}}
.two{{grid-template-columns:2fr 1fr}}@media(max-width:850px){{.two{{grid-template-columns:1fr}}}}
.flash{{background:#fff3d6;border:1px solid var(--accent);padding:10px 14px;border-radius:8px;margin-bottom:14px}}
.tl li{{margin:0 0 8px;list-style:none;padding-left:12px;border-left:3px solid var(--accent)}}.tl{{padding:0}}.muted{{color:var(--cocoa)}}
pre.mail{{white-space:pre-wrap;background:#fff;border:1px dashed #cdbba5;border-radius:8px;padding:12px;font:13px/1.5 ui-monospace,Menlo,monospace}}
"""


def layout(title, body, active="", flash=""):
    cfg = leads.config()
    logo = cfg.get("theme", {}).get("logo_url")
    brand = f'<img src="{esc(logo)}" alt="">' if logo else ""
    nav = [("/", "Panel"), ("/leads", "Firmalar"), ("/add", "Firma ekle"), ("/import", "İçe aktar"),
           ("/markets", "Pazarlar"), ("/tools", "Araçlar")]
    links = "".join(f'<a href="{u}" class="{"on" if u == active else ""}">{n}</a>' for u, n in nav)
    fl = f'<div class="flash">{esc(flash)}</div>' if flash else ""
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · {esc(cfg['company_name'])} Lead</title><style>{css()}</style></head><body>
<header><a class="logo" href="/">{brand}<span>IMESTA <b>COCOA</b></span></a><nav>{links}</nav></header>
<main>{fl}{body}</main></body></html>"""


def badge(score):
    return f'<span class="badge {"hi" if score >= 70 else "mid" if score >= 45 else ""}">{score}</span>'


def lead_table(rows):
    if not rows:
        return '<p class="muted">Kayıt yok.</p>'
    out = "<table><tr><th>Puan</th><th>Firma</th><th>Ülke</th><th>Segment</th><th>Durum</th><th>Site</th><th>Takip</th></tr>"
    for r in rows:
        site = leads.get_domain(r["website"])
        link = f'<a href="{esc(r["website"])}" target=_blank rel=noopener>{esc(site)}</a>' if site else ""
        out += (f'<tr><td>{badge(r["score"])}</td><td><a href="/lead/{r["id"]}"><b>{esc(r["name"])}</b></a></td>'
                f'<td>{esc(r["country"] or "-")}</td><td>{SEGMENT_TR.get(r["segment"], r["segment"])}</td>'
                f'<td><span class="pill">{STATUS_TR.get(r["status"], r["status"])}</span></td>'
                f'<td>{link}</td>'
                f'<td>{esc(r["next_followup"] or "")}</td></tr>')
    return out + "</table>"


def opts(items, sel=None, blank=None):
    h = f'<option value="">{blank}</option>' if blank is not None else ""
    for v, n in items:
        h += f'<option value="{esc(v)}"{" selected" if v == sel else ""}>{esc(n)}</option>'
    return h


# ------------------------------------------------------------------ sayfalar
def page_dashboard(con, q):
    n = lambda sql, *p: con.execute(sql, p).fetchone()[0]  # noqa: E731
    td = leads.today()
    kp = [("Toplam firma", n("SELECT COUNT(*) FROM companies")),
          ("E-postalı", n("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE email_ok=1")),
          ("Yazılmamış", n("SELECT COUNT(*) FROM companies WHERE status='new'")),
          ("Süreçte", n("SELECT COUNT(*) FROM companies WHERE status IN ('replied','sample','negotiation')")),
          ("Kazanılan", n("SELECT COUNT(*) FROM companies WHERE status='won'")),
          ("Bugün takip", n("SELECT COUNT(*) FROM companies WHERE next_followup<=? AND status NOT IN ('won','lost')", td))]
    h = '<h1>Panel</h1><div class="grid kpis">' + "".join(
        f'<div class="card kpi"><b>{v}</b><span>{k}</span></div>' for k, v in kp) + "</div><h2>Satış hattı</h2><div class='kanban'>"
    for st in ["new", "contacted", "replied", "sample", "negotiation", "won", "nurture"]:
        rows = con.execute("SELECT * FROM companies WHERE status=? ORDER BY score DESC LIMIT 12", (st,)).fetchall()
        cnt = n("SELECT COUNT(*) FROM companies WHERE status=?", st)
        h += f'<div class="col"><h4>{STATUS_TR[st]}<span>{cnt}</span></h4>'
        for r in rows:
            h += (f'<a class="lead" href="/lead/{r["id"]}"><b>{esc(r["name"])}</b>'
                  f'<small>{esc(r["country"] or "-")} · {SEGMENT_TR.get(r["segment"], "")} · {r["score"]}</small></a>')
        if cnt > len(rows):
            h += f'<a href="/leads?status={st}">+{cnt - len(rows)} daha…</a>'
        h += "</div>"
    h += "</div><div class='grid two' style='margin-top:20px'><div><h2>Bugün takip edilecekler</h2>"
    due = con.execute("SELECT * FROM companies WHERE next_followup<=? AND status NOT IN ('won','lost') ORDER BY next_followup LIMIT 20", (td,)).fetchall()
    h += lead_table(due) + "</div><div><h2>İlk yazılacak 10 firma</h2>"
    top = con.execute("SELECT * FROM companies WHERE status='new' AND id IN (SELECT company_id FROM contacts WHERE email_ok=1) "
                      "ORDER BY score DESC LIMIT 10").fetchall()
    h += "".join(f'<div class="card" style="margin-bottom:8px">{badge(r["score"])} <a href="/lead/{r["id"]}"><b>{esc(r["name"])}</b></a> '
                 f'<span class="muted">{esc(r["country"] or "")}</span></div>' for r in top) or '<p class="muted">Henüz e-postalı firma yok. Araçlar → E-posta topla.</p>'
    return "Panel", h + "</div>", "/"


def page_leads(con, q):
    g = lambda k: (q.get(k) or [""])[0].strip()  # noqa: E731
    w, p = ["1=1"], []
    if g("q"):
        w.append("(name LIKE ? OR domain LIKE ? OR city LIKE ?)")
        p += [f"%{g('q')}%"] * 3
    for col in ("status", "country", "segment"):
        if g(col):
            w.append(f"{col}=?")
            p.append(g(col).upper() if col == "country" else g(col))
    if g("min_score").isdigit():
        w.append("score>=?")
        p.append(int(g("min_score")))
    if g("with_email"):
        w.append("id IN (SELECT company_id FROM contacts WHERE email_ok=1)")
    rows = con.execute(f"SELECT * FROM companies WHERE {' AND '.join(w)} ORDER BY score DESC, id DESC LIMIT 200", p).fetchall()
    form = f"""<form class="inline card" method="get"><div><label>Ara</label><input name="q" value="{esc(g('q'))}" placeholder="firma, site, şehir"></div>
<div><label>Durum</label><select name="status">{opts([(s, STATUS_TR[s]) for s in STATUSES], g('status'), 'Hepsi')}</select></div>
<div><label>Segment</label><select name="segment">{opts(list(SEGMENT_TR.items()), g('segment'), 'Hepsi')}</select></div>
<div><label>Ülke (ISO2)</label><input name="country" size="4" value="{esc(g('country'))}"></div>
<div><label>Min. puan</label><input name="min_score" size="3" value="{esc(g('min_score'))}"></div>
<div><label><input type="checkbox" name="with_email" value="1"{" checked" if g('with_email') else ""}> sadece e-postalı</label></div>
<button>Filtrele</button><a class="btn ghost" href="/export.csv">Tümünü CSV indir</a></form>"""
    return "Firmalar", f"<h1>Firmalar <small class='muted'>({len(rows)})</small></h1>{form}<br>{lead_table(rows)}", "/leads"


def page_lead(con, cid, q):
    c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    if not c:
        return "Bulunamadı", "<h1>Firma bulunamadı</h1>", "/leads"
    lang = (q.get("lang") or ["en"])[0]
    tpl = (q.get("tpl") or ["cold"])[0]
    h = f'<h1>{esc(c["name"])} {badge(c["score"])}</h1><p class="muted">{esc(c["city"] or "")} {esc(c["country"] or "")} · ' \
        f'{SEGMENT_TR.get(c["segment"], "")} · kaynak: {esc(c["source"] or "-")}'
    if c["website"]:
        h += f' · <a href="{esc(c["website"])}" target=_blank rel=noopener>{esc(leads.get_domain(c["website"]))}</a>'
    h += "</p><div class='grid two'><div>"
    # kişiler
    h += "<div class='card'><h3>Kişiler</h3><table><tr><th>Ad</th><th>Görev</th><th>E-posta</th><th>Telefon</th></tr>"
    for k in con.execute("SELECT * FROM contacts WHERE company_id=?", (cid,)):
        h += (f'<tr><td>{esc(k["name"] or "-")}</td><td>{esc(k["role"] or "-")}</td>'
              f'<td>{esc(k["email"] or "-")} {"✔" if k["email_ok"] else ("✖" if k["email"] else "")}</td><td>{esc(k["phone"] or "-")}</td></tr>')
    h += f"""</table><form class="inline" method="post" action="/lead/{cid}/contact" style="margin-top:10px">
<input name="name" placeholder="Ad Soyad"><input name="role" placeholder="Görev"><input name="email" placeholder="e-posta"><input name="phone" placeholder="telefon">
<button class="ghost">Kişi ekle</button></form></div>"""
    # geçmiş + kayıt
    h += f"""<div class="card" style="margin-top:14px"><h3>Geçmiş & takip</h3>
<form class="inline" method="post" action="/lead/{cid}/log"><div><label>Tür</label><select name="kind">{opts(list(KIND_TR.items()))}</select></div>
<div style="flex:1"><label>Özet</label><input name="summary" required style="width:100%" placeholder="Ne konuşuldu / ne gönderildi?"></div>
<div><label>Durum</label><select name="status">{opts([(s, STATUS_TR[s]) for s in STATUSES], None, 'Değişmesin')}</select></div>
<div><label>Takip (gün)</label><input name="followup" size="3" placeholder="oto"></div><button>Kaydet</button></form><ul class="tl" style="margin-top:12px">"""
    for x in con.execute("SELECT * FROM activities WHERE company_id=? ORDER BY ts DESC", (cid,)):
        h += f'<li><b>{KIND_TR.get(x["kind"], x["kind"])}</b> <span class="muted">{esc(x["ts"][:16])}</span><br>{esc(x["summary"])}</li>'
    h += "</ul></div></div><div>"
    # durum + notlar
    h += f"""<div class="card"><h3>Durum</h3><p><span class="pill">{STATUS_TR.get(c['status'])}</span> sonraki takip: <b>{esc(c['next_followup'] or '-')}</b></p>
<form method="post" action="/lead/{cid}/edit"><label>Segment</label><select name="segment">{opts(list(SEGMENT_TR.items()), c['segment'])}</select>
<label>Notlar</label><textarea name="notes" rows="4">{esc(c['notes'] or '')}</textarea><br><br><button class="ghost">Güncelle</button></form>
<form method="post" action="/suppress" onsubmit="return confirm('Bu firmaya bir daha yazılmayacak. Emin misiniz?')" style="margin-top:12px">
<input type="hidden" name="value" value="{esc(c['domain'] or '')}"><input type="hidden" name="back" value="/lead/{cid}">
<button class="ghost" {"disabled" if not c['domain'] else ""}>Abonelikten çıktı / engelle</button></form></div>"""
    # e-posta
    try:
        to, text = leads.render_email(con, cid, lang, tpl)
        lines = text.split("\n")
        subject = lines[0].split(":", 1)[1].strip() if ":" in lines[0] else ""
        body = "\n".join(lines[1:]).strip()
        mailto = f"mailto:{to or ''}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
        mail = (f'<p class="muted">Alıcı: <b>{esc(to or "geçerli e-posta yok – Araçlar → E-posta topla")}</b></p>'
                f'<pre class="mail" id="mail">{esc(text)}</pre><a class="btn alt" href="{esc(mailto)}">Mail uygulamasında aç</a> '
                f'<button type="button" class="ghost" onclick="navigator.clipboard.writeText(document.getElementById(\'mail\').innerText)">Kopyala</button>')
    except ValueError as e:
        mail = f'<p class="muted">{esc(str(e))}</p>'
    langs = sorted({f.split("_")[0] for f in os.listdir(os.path.join(leads.HERE, "templates"))})
    tpls = sorted({f.split("_", 1)[1][:-4] for f in os.listdir(os.path.join(leads.HERE, "templates"))})
    h += f"""<div class="card" style="margin-top:14px"><h3>E-posta taslağı</h3><form class="inline" method="get">
<select name="lang">{opts([(x, x.upper()) for x in langs], lang)}</select><select name="tpl">{opts([(x, x) for x in tpls], tpl)}</select>
<button class="ghost">Göster</button></form>{mail}</div></div></div>"""
    return c["name"], h, "/leads"


def page_add(con, q):
    return "Firma ekle", f"""<h1>Firma ekle</h1><form class="card" method="post" action="/add"><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">
<div><label>Firma adı *</label><input name="name" required style="width:100%"></div><div><label>Web sitesi</label><input name="website" style="width:100%"></div>
<div><label>Ülke (ISO2: DE, AE…)</label><input name="country" maxlength="2" style="width:100%"></div><div><label>Şehir</label><input name="city" style="width:100%"></div>
<div><label>Segment</label><select name="segment" style="width:100%">{opts(list(SEGMENT_TR.items()))}</select></div>
<div><label>E-posta</label><input name="email" style="width:100%"></div><div><label>Telefon</label><input name="phone" style="width:100%"></div>
<div><label>Kaynak</label><input name="source" value="manuel" style="width:100%"></div></div><br><label>Notlar</label><textarea name="notes" rows="3"></textarea><br><br><button>Ekle</button></form>""", "/add"


def page_import(con, q):
    return "İçe aktar", f"""<h1>Toplu içe aktar (CSV)</h1><form class="card" method="post" action="/import">
<p class="muted">Sütunlar: <code>name,country,website,segment,city,email,phone,notes</code> (sadece <b>name</b> zorunlu). Fuar katılımcı listesi, ImportYeti sonucu, Excel'den "CSV olarak kaydet" dosyaları olur. Aynı site/firma tekrar eklenmez.</p>
<div><label>Kaynak adı</label><input name="source" value="Fuar-2026" required></div><br>
<div><label>CSV dosyası seç</label><input type="file" accept=".csv,.txt" onchange="const f=this.files[0];if(f)f.text().then(t=>document.getElementById('csv').value=t)"></div><br>
<label>veya buraya yapıştırın</label><textarea id="csv" name="csv" rows="12" required></textarea><br><br><button>İçe aktar</button></form>""", "/import"


def page_markets(con, q):
    hs = (q.get("hs") or [""])[0] or None
    rows = leads.market_rows(con, hs, None, 40)
    sel = opts([("1801", "1801 Kakao çekirdeği"), ("1803", "1803 Kakao hamuru"), ("1804", "1804 Kakao yağı"),
                ("1805", "1805 Kakao tozu"), ("1806", "1806 Çikolata")], hs, "Tüm kakao kodları")
    h = f'<h1>Hedef pazarlar</h1><form class="inline"><select name="hs">{sel}</select><button class="ghost">Göster</button></form><br>'
    if not rows:
        return "Pazarlar", h + '<p class="muted">Veri yok. Araçlar → "Pazar verisi çek (Comtrade)" ile yükleyin.</p>', "/markets"
    h += "<table><tr><th>#</th><th>Ülke</th><th>Toplam ithalat (USD)</th><th>Türkiye payı</th><th>Sistemdeki firma</th></tr>"
    iso3 = {v: k for k, v in leads.ISO2_TO_ISO3.items()}
    for i, r in enumerate(rows, 1):
        cc = iso3.get(r["iso"])
        cnt = con.execute("SELECT COUNT(*) FROM companies WHERE country=?", (cc,)).fetchone()[0] if cc else 0
        link = f'<a href="/leads?country={cc}">{cnt}</a>' if cc else "-"
        h += (f'<tr><td>{i}</td><td>{esc(r["importer"])}</td><td>{r["total"]:,.0f}</td>'
              f'<td>{100 * r["from_tr"] / r["total"] if r["total"] else 0:.1f}%</td><td>{link}</td></tr>')
    return "Pazarlar", h + "</table>", "/markets"


def page_tools(con, q):
    refresh = '<script>setTimeout(()=>location.reload(),5000)</script>' if JOB["running"] else ""
    run = '<p class="muted">Çalışan iş yok.</p>' if not JOB["running"] else f'<p class="flash">Çalışıyor: {esc(JOB["name"])} … (sayfa 5 saniyede bir yenilenir)</p>'
    log = f'<pre class="mail">{esc(JOB["log"])}</pre>' if JOB["log"] else ""
    log += refresh
    return "Araçlar", f"""<h1>Araçlar</h1>{run}{log}<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
<form class="card" method="post" action="/job/comtrade"><h3>Pazar verisi çek</h3><p class="muted">UN Comtrade'den kakao ithalatı (ücretsiz).</p>
<label>Yıl</label><input name="year" value="{leads.config().get('comtrade_year', 2023)}" size="5"> <button>Çek</button></form>
<form class="card" method="post" action="/job/osm"><h3>OpenStreetMap'ten firma çek</h3><p class="muted">Çikolata/şekerleme/dondurma üreticileri.</p>
<label>Ülkeler (ISO2, virgülle)</label><input name="country" value="DE,NL,GB" required> <button>Çek</button></form>
<form class="card" method="post" action="/job/enrich"><h3>E-posta topla</h3><p class="muted">Site iletişim/impressum sayfalarından (robots.txt'e uyar, yavaştır).</p>
<label>Kaç firma</label><input name="limit" value="30" size="4"> <button>Başlat</button></form>
<form class="card" method="post" action="/job/score"><h3>Puanla</h3><p class="muted">Tüm firmaları yeniden puanlar.</p><button>Puanla</button></form></div>""", "/tools"


# ------------------------------------------------------------------ sunucu
def run_job(name, fn):
    with JOB_LOCK:
        if JOB["running"]:
            return False
        JOB.update(running=True, name=name, log="")

    class Live:  # çıktıyı iş sürerken sayfada gösterebilmek için anında JOB["log"]'a yazar
        def write(self, t):
            JOB["log"] += t
            return len(t)

        def flush(self):
            pass

    def work():
        try:
            with contextlib.redirect_stdout(Live()), contextlib.redirect_stderr(Live()):
                fn()
        except BaseException as e:  # SystemExit dahil
            JOB["log"] += f"\nHata: {e}"
        JOB["log"] += "\n[Bitti]"
        JOB["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return True


class H(BaseHTTPRequestHandler):
    server_version = "ImestaLeads"

    def log_message(self, *a):
        pass

    def _auth(self):
        pw = os.environ.get("WEB_PASSWORD")
        if not pw:
            return True
        got = self.headers.get("Authorization", "")
        try:
            user, _, given = base64.b64decode(got.split(" ", 1)[1]).decode().partition(":")
        except Exception:
            user = given = ""
        if user == "imesta" and hmac.compare_digest(given, pw):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Imesta Leads"')
        self.end_headers()
        return False

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to, flash=None):
        if flash:
            to += ("&" if "?" in to else "?") + "msg=" + urllib.parse.quote(flash)
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):
        if not self._auth():
            return
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        flash = (q.get("msg") or [""])[0]
        con = leads.db()
        try:
            if u.path == "/export.csv":
                return self._export(con, q)
            routes = {"/": page_dashboard, "/leads": page_leads, "/add": page_add, "/import": page_import,
                      "/markets": page_markets, "/tools": page_tools}
            if u.path in routes:
                title, body, act = routes[u.path](con, q)
            elif u.path.startswith("/lead/") and u.path[6:].isdigit():
                title, body, act = page_lead(con, int(u.path[6:]), q)
            else:
                return self._send(404, layout("404", "<h1>Sayfa yok</h1>"))
            self._send(200, layout(title, body, act, flash))
        finally:
            con.close()

    def _export(self, con, q):
        import tempfile
        with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False) as t:
            path = t.name
        try:
            leads.cmd_export(argparse.Namespace(file=path))
            data = open(path, "rb").read()
        finally:
            os.unlink(path)
        self._send(200, data, "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="imesta-leads.csv"'})

    def do_POST(self):
        if not self._auth():
            return
        host, origin = self.headers.get("Host", ""), self.headers.get("Origin") or self.headers.get("Referer") or ""
        if origin and urllib.parse.urlparse(origin).netloc != host:  # basit CSRF koruması
            return self._send(403, "Origin hatası")
        n = int(self.headers.get("Content-Length") or 0)
        if n > 8_000_000:
            return self._send(413, "Çok büyük")
        f = {k: v[0].strip() for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}
        path = urllib.parse.urlparse(self.path).path
        con = leads.db()
        try:
            if path == "/add":
                cid, new = leads.upsert_company(con, f.get("name"), f.get("country"), f.get("city"), f.get("website"),
                                                f.get("segment", "other"), f.get("source") or "manuel", f.get("notes"), f.get("email"), f.get("phone"))
                con.commit()
                return self._redirect(f"/lead/{cid}" if cid else "/add", "Eklendi" if new else "Bu firma zaten kayıtlıydı")
            if path == "/import":
                new, dup = leads.import_csv_text(con, f.get("csv", ""), f.get("source") or "csv")
                return self._redirect("/leads", f"{new} yeni firma eklendi, {dup} tekrar atlandı. Puanlamak için Araçlar → Puanla.")
            if path == "/suppress":
                if f.get("value"):
                    leads.cmd_suppress(argparse.Namespace(value=f["value"]))
                return self._redirect(f.get("back") or "/", "Engelleme listesine eklendi")
            if path.startswith("/job/"):
                kind = path[5:]
                jobs = {"comtrade": lambda: leads.cmd_harvest_comtrade(argparse.Namespace(hs=None, year=int(f.get("year") or 0) or None)),
                        "osm": lambda: leads.cmd_harvest_osm(argparse.Namespace(country=f.get("country", ""), segments=None)),
                        "enrich": lambda: leads.cmd_enrich(argparse.Namespace(limit=int(f.get("limit") or 30))),
                        "score": lambda: leads.cmd_score(argparse.Namespace())}
                if kind not in jobs:
                    return self._send(404, "yok")
                ok = run_job(kind, jobs[kind])
                return self._redirect("/tools", "İş başlatıldı" if ok else "Başka bir iş çalışıyor")
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "lead" and parts[1].isdigit():
                cid, act = int(parts[1]), parts[2]
                if act == "log":
                    fu = f.get("followup")
                    try:
                        leads.do_log(con, cid, f.get("kind", "note"), f.get("summary", ""), f.get("status") or None,
                                     int(fu) if fu and fu.isdigit() else None)
                    except ValueError as e:
                        return self._redirect(f"/lead/{cid}", str(e))
                    return self._redirect(f"/lead/{cid}", "Kaydedildi")
                if act == "contact":
                    leads.add_contact(con, cid, f.get("name") or None, f.get("role") or None, f.get("email") or None,
                                      f.get("phone") or None, None, "manuel")
                    con.commit()
                    return self._redirect(f"/lead/{cid}", "Kişi eklendi")
                if act == "edit":
                    seg = f.get("segment") if f.get("segment") in SEGMENTS else "other"
                    con.execute("UPDATE companies SET segment=?, notes=? WHERE id=?", (seg, f.get("notes"), cid))
                    con.commit()
                    return self._redirect(f"/lead/{cid}", "Güncellendi")
            self._send(404, "yok")
        finally:
            con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1", help="Başka cihazlardan erişim için 0.0.0.0 (WEB_PASSWORD ayarlayın!)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true", help="tarayıcıyı otomatik aç")
    a = p.parse_args()
    if a.host != "127.0.0.1" and not os.environ.get("WEB_PASSWORD"):
        raise SystemExit("Güvenlik: localhost dışına açmak için WEB_PASSWORD ortam değişkenini ayarlayın.")
    leads.db().close()
    srv = None
    for port in range(a.port, a.port + 20):  # port doluysa sıradakini dene
        try:
            srv = ThreadingHTTPServer((a.host, port), H)
            break
        except OSError:
            print(f"Port {port} dolu, sıradaki deneniyor...")
    if not srv:
        raise SystemExit("Boş port bulunamadı. --port ile başka bir port verin.")
    url = f"http://{a.host}:{srv.server_address[1]}"
    print(f"Imesta Lead paneli: {url}  (kapatmak için Ctrl+C)")
    if a.open:
        import webbrowser
        threading.Timer(1.0, webbrowser.open, [url]).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
