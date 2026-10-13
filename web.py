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
import os
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import leads
from leads import STATUSES, SEGMENTS, COUNTRIES

esc = html.escape
STATUS_TR = {"new": "Yeni", "contacted": "İletişime geçildi", "replied": "Yanıt verdi", "sample": "Numune",
             "negotiation": "Pazarlık", "won": "Kazanıldı", "lost": "Kaybedildi", "nurture": "Beklemede"}
STATUS_COLOR = {"new": "#9a8470", "contacted": "#3b82c4", "replied": "#8b5cf6", "sample": "#d98324",
                "negotiation": "#c8963e", "won": "#2e7d32", "lost": "#b04a3a", "nurture": "#6b7f8c"}
SEGMENT_TR = {"chocolate_maker": "Çikolata üreticisi", "confectionery": "Şekerleme / bisküvi", "distributor": "Distribütör",
              "bakery_ingredient": "Pastane / fırın malzemesi", "ice_cream": "Dondurma", "dairy_beverage": "Süt / içecek",
              "retail_craft": "Butik / perakende", "other": "Diğer"}
KIND_TR = {"email": "E-posta", "call": "Arama", "sample": "Numune", "meeting": "Görüşme", "note": "Not"}
PRODUCTS = [("1805", "Kakao tozu"), ("1804", "Kakao yağı (butter)"), ("1803", "Kakao hamuru (liquor)"),
            ("1801", "Kakao çekirdeği"), ("1806", "Çikolata ve kakaolu ürünler")]
DEFAULT_FIND = ["DE", "NL", "BE", "FR", "GB", "PL", "IT", "AE"]
ISO3_TO_ISO2 = {v[1]: k for k, v in COUNTRIES.items()}

JOB = {"running": False, "name": "", "log": "", "summary": ""}
JOB_LOCK = threading.Lock()

ICONS = {
    "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "mail": '<path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    "award": '<circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "building": '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01M16 6h.01M12 6h.01M12 10h.01M12 14h.01M16 10h.01M16 14h.01M8 10h.01M8 14h.01"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "trend": '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
}


def icon(name, size=18):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def tr_key(s):  # Türkçe harflere göre sıralama (Ç→C, İ→I ...)
    return s.translate(str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")).lower()


def cname(cc):
    return COUNTRIES.get((cc or "").upper(), (cc or "-",))[0]


def css():
    t = {"brand": "#3B2418", "accent": "#C8963E", "cream": "#F6EFE6", "cocoa": "#6F4E37", **leads.config().get("theme", {})}
    return """
:root{--brand:%(brand)s;--accent:%(accent)s;--cream:%(cream)s;--cocoa:%(cocoa)s;--ink:#2b1d14;--line:#e6d9c8;--card:#fff;--soft:#f1e7d8;--ok:#2e7d32;--bad:#b04a3a}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--cream);color:var(--ink);font:15px/1.55 "Inter","Segoe UI",system-ui,-apple-system,Roboto,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--cocoa)}h1,h2,h3,h4{font-family:Georgia,"Times New Roman",serif;color:var(--brand);margin:0 0 .4em;line-height:1.2}
h1{font-size:30px}h2{font-size:21px;margin-top:6px}h3{font-size:17px}
.muted{color:#8a7160}small.muted{font-size:12.5px}
header.top{position:sticky;top:0;z-index:20;background:linear-gradient(135deg,#2b1810,var(--brand) 55%%,#573523);color:#fff;box-shadow:0 2px 14px rgba(43,24,16,.35)}
header.top .in{max-width:1240px;margin:0 auto;padding:0 20px;display:flex;align-items:center;gap:26px;flex-wrap:wrap}
.logo{display:flex;align-items:center;gap:10px;padding:13px 0;color:#fff;text-decoration:none;font:700 21px Georgia,serif;letter-spacing:.6px}
.logo img{height:34px}.logo b{color:var(--accent)}.logo svg{color:var(--accent)}
nav{display:flex;gap:4px;flex-wrap:wrap}
nav a{color:#e9dccb;text-decoration:none;padding:9px 13px;border-radius:9px;display:flex;align-items:center;gap:7px;font-weight:500;transition:.15s}
nav a:hover{background:rgba(255,255,255,.1);color:#fff}nav a.on{background:var(--accent);color:#2b1810;font-weight:700}
main{max-width:1240px;margin:26px auto 60px;padding:0 20px}
.pagehead{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:18px}
.pagehead p{margin:0;color:#8a7160}
.grid{display:grid;gap:16px}.kpis{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 4px 18px rgba(59,36,24,.06)}
.card.flat{box-shadow:none;background:#fffdf9}
.kpi{display:flex;gap:14px;align-items:center;padding:16px 18px}
.kpi .ic{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;background:var(--soft);color:var(--cocoa);flex:none}
.kpi.a .ic{background:#fbeccb;color:#9a6a16}.kpi.g .ic{background:#dff0e0;color:var(--ok)}.kpi.r .ic{background:#f6dedb;color:var(--bad)}
.kpi b{display:block;font:700 28px/1 Georgia,serif;color:var(--brand)}.kpi span{color:#8a7160;font-size:13px}
.hero{background:linear-gradient(120deg,var(--brand),#6b4430);color:#fff;border-radius:18px;padding:26px 28px;margin-bottom:18px;box-shadow:0 8px 24px rgba(59,36,24,.25);position:relative;overflow:hidden}
.hero:after{content:"";position:absolute;right:-60px;top:-60px;width:240px;height:240px;border-radius:50%%;background:radial-gradient(circle,rgba(200,150,62,.35),transparent 70%%)}
.hero h2{color:#fff;font-size:24px;margin:0 0 4px}.hero p{margin:0 0 16px;color:#e9dccb;max-width:620px}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;position:relative;z-index:1}
.step{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.18);border-radius:13px;padding:13px 14px;display:flex;gap:11px;align-items:flex-start;color:#fff;text-decoration:none;transition:.15s}
.step:hover{background:rgba(255,255,255,.18);transform:translateY(-1px)}
.step .n{width:28px;height:28px;border-radius:50%%;display:grid;place-items:center;font-weight:700;background:var(--accent);color:#2b1810;flex:none}
.step.done .n{background:#4caf50;color:#fff}.step.done{opacity:.8}.step b{display:block;font-size:14px}.step span{font-size:12.5px;color:#e0d1be}
.funnel{display:flex;height:14px;border-radius:99px;overflow:hidden;background:var(--soft);margin:10px 0 8px}
.funnel i{display:block;height:100%%}.legend{display:flex;gap:6px 16px;flex-wrap:wrap;font-size:13px;color:#6f5848}.legend span:before{content:"";display:inline-block;width:9px;height:9px;border-radius:50%%;background:var(--c);margin-right:6px}
.kanban{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(220px,1fr);gap:12px;overflow-x:auto;padding-bottom:10px}
.col{background:var(--soft);border-radius:14px;padding:12px;min-height:130px;border-top:4px solid var(--c,#999)}
.col h4{margin:0 0 10px;font:600 12.5px "Segoe UI",sans-serif;text-transform:uppercase;letter-spacing:.6px;color:#6f5848;display:flex;justify-content:space-between}
.col h4 span{background:#fff;border-radius:99px;padding:0 8px}
.lead{display:block;background:#fff;border:1px solid var(--line);border-radius:10px;padding:9px 11px;margin-bottom:8px;text-decoration:none;color:var(--ink);transition:.15s}
.lead:hover{box-shadow:0 4px 12px rgba(59,36,24,.12);transform:translateY(-1px)}.lead small{color:#8a7160;display:block}
table{width:100%%;border-collapse:separate;border-spacing:0;background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:0 4px 18px rgba(59,36,24,.05)}
th{background:var(--soft);color:#6f5848;text-align:left;padding:11px 12px;font-size:12px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}
td{padding:11px 12px;border-top:1px solid #f0e6d8;vertical-align:middle}tr:hover td{background:#fcf7ee}
td a.name{font-weight:600;text-decoration:none;color:var(--brand)}td a.name:hover{text-decoration:underline}
.tw{overflow-x:auto;border-radius:14px}
.badge{display:inline-grid;place-items:center;min-width:36px;height:26px;border-radius:99px;padding:0 9px;font-weight:700;font-size:13px;color:#fff;background:#a89786}
.badge.hi{background:var(--ok)}.badge.mid{background:var(--accent);color:#2b1810}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:600;background:color-mix(in srgb,var(--c,#999) 16%%,#fff);color:var(--c,#555);white-space:nowrap}
.bar{height:8px;border-radius:99px;background:var(--soft);min-width:120px;overflow:hidden}.bar i{display:block;height:100%%;background:linear-gradient(90deg,var(--accent),#e0b363);border-radius:99px}
form.inline{display:flex;gap:10px;flex-wrap:wrap;align-items:end}label{font-size:12.5px;color:#7a6252;display:block;margin-bottom:3px;font-weight:600}
input,select,textarea{font:inherit;padding:9px 11px;border:1px solid #d6c5b0;border-radius:10px;background:#fff;max-width:100%%;transition:.15s}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--accent);box-shadow:0 0 0 3px rgba(200,150,62,.25)}textarea{width:100%%}
button,.btn{font:inherit;font-weight:600;padding:9px 16px;border:0;border-radius:10px;background:var(--brand);color:#fff;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:7px;transition:.15s}
button:hover,.btn:hover{filter:brightness(1.15);transform:translateY(-1px)}
button.alt,.btn.alt{background:var(--accent);color:#2b1810}button.ghost,.btn.ghost{background:var(--soft);color:var(--brand)}button.sm{padding:5px 11px;font-size:13px;border-radius:8px}
button:disabled{opacity:.45;cursor:not-allowed;transform:none}
.two{grid-template-columns:2fr 1fr}@media(max-width:900px){.two{grid-template-columns:1fr}}
.flash{background:#fff4d9;border:1px solid #e8c77a;padding:12px 16px;border-radius:12px;margin-bottom:16px;display:flex;gap:10px;align-items:center}
.tl{padding:0;margin:14px 0 0}.tl li{list-style:none;margin:0 0 12px;padding:2px 0 2px 14px;border-left:3px solid var(--accent)}
pre.mail{white-space:pre-wrap;background:#fffaf2;border:1px dashed #cdbba5;border-radius:12px;padding:14px;font:13px/1.55 ui-monospace,Menlo,Consolas,monospace;max-height:420px;overflow:auto}
.chips{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin:10px 0 14px}
.chip{display:flex;align-items:center;gap:8px;margin:0;padding:8px 11px;border:1px solid var(--line);border-radius:10px;background:#fff;cursor:pointer;font-weight:500;font-size:14px;color:var(--ink)}
.chip:has(input:checked){border-color:var(--accent);background:#fff4dc}.chip input{accent-color:var(--brand)}
.tool{display:flex;flex-direction:column;gap:6px}.tool .no{font:700 13px "Segoe UI";color:var(--accent);letter-spacing:.8px}
.empty{text-align:center;padding:38px 20px;color:#8a7160}.empty .ic{width:56px;height:56px;border-radius:50%%;background:var(--soft);display:grid;place-items:center;margin:0 auto 12px;color:var(--cocoa)}
.spin{width:18px;height:18px;border:3px solid #e8c77a;border-top-color:var(--brand);border-radius:50%%;animation:sp 1s linear infinite;flex:none}@keyframes sp{to{transform:rotate(360deg)}}
.result{background:#e8f5e9;border:1px solid #a9d3ac;border-radius:12px;padding:12px 16px;margin-bottom:14px;color:#1f5a23;font-weight:600}
details summary{cursor:pointer;color:#8a7160;font-weight:600;margin:6px 0}
""" % t


def layout(title, body, active="", flash=""):
    cfg = leads.config()
    logo = cfg.get("theme", {}).get("logo_url")
    mark = f'<img src="{esc(logo)}" alt="">' if logo else icon("zap", 22)
    nav = [("/", "Panel", "home"), ("/leads", "Firmalar", "users"), ("/markets", "Pazarlar", "globe"),
           ("/tools", "Firma bul", "search"), ("/add", "Firma ekle", "plus"), ("/import", "İçe aktar", "upload")]
    links = "".join(f'<a href="{u}" class="{"on" if u == active else ""}">{icon(i, 16)}{n}</a>' for u, n, i in nav)
    fl = f'<div class="flash">{icon("check")} {esc(flash)}</div>' if flash else ""
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · {esc(cfg['company_name'])}</title><style>{css()}</style></head><body>
<header class="top"><div class="in"><a class="logo" href="/">{mark}<span>IMESTA <b>COCOA</b></span></a><nav>{links}</nav></div></header>
<main>{fl}{body}</main></body></html>"""


def head(title, sub="", action=""):
    return f'<div class="pagehead"><div><h1>{title}</h1><p>{sub}</p></div><div>{action}</div></div>'


def badge(score):
    return f'<span class="badge {"hi" if score >= 70 else "mid" if score >= 45 else ""}" title="Potansiyel puanı (0-100)">{score}</span>'


def pill(status):
    return f'<span class="pill" style="--c:{STATUS_COLOR.get(status, "#999")}">{STATUS_TR.get(status, status)}</span>'


def empty(ic, text, cta=""):
    return f'<div class="card empty"><div class="ic">{icon(ic, 26)}</div><p>{text}</p>{cta}</div>'


def lead_table(rows):
    if not rows:
        return '<p class="muted">Kayıt yok.</p>'
    out = '<div class="tw"><table><tr><th>Puan</th><th>Firma</th><th>Ülke</th><th>Segment</th><th>Durum</th><th>Site</th><th>Takip</th></tr>'
    for r in rows:
        site = leads.get_domain(r["website"])
        link = f'<a href="{esc(r["website"])}" target=_blank rel=noopener>{esc(site)}</a>' if site else ""
        out += (f'<tr><td>{badge(r["score"])}</td><td><a class="name" href="/lead/{r["id"]}">{esc(r["name"])}</a></td>'
                f'<td>{esc(cname(r["country"]))}</td><td>{SEGMENT_TR.get(r["segment"], r["segment"])}</td>'
                f'<td>{pill(r["status"])}</td><td>{link}</td><td>{esc(r["next_followup"] or "")}</td></tr>')
    return out + "</table></div>"


def opts(items, sel=None, blank=None):
    h = f'<option value="">{blank}</option>' if blank is not None else ""
    for v, n in items:
        h += f'<option value="{esc(v)}"{" selected" if v == sel else ""}>{esc(n)}</option>'
    return h


def country_chips(selected, name="c"):
    keys = sorted(COUNTRIES, key=lambda k: (k not in selected, tr_key(COUNTRIES[k][0])))
    return '<div class="chips">' + "".join(
        f'<label class="chip"><input type="checkbox" name="{name}" value="{k}"{" checked" if k in selected else ""}>{esc(cname(k))}</label>'
        for k in keys) + "</div>"


# ------------------------------------------------------------------ sayfalar
def page_dashboard(con, q):
    n = lambda sql, *p: con.execute(sql, p).fetchone()[0]  # noqa: E731
    td = leads.today()
    total = n("SELECT COUNT(*) FROM companies")
    emails = n("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE email_ok=1")
    has_market = n("SELECT COUNT(*) FROM trade_flows") > 0
    sent = n("SELECT COUNT(*) FROM activities WHERE kind='email'")
    done = [has_market, total > 0, emails > 0, sent > 0]
    steps = [("/tools", "Pazar verisini çek", "Hangi ülkeler kakao alıyor?"), ("/tools", "Firmaları bul", "Seçtiğin ülkelerde otomatik"),
             ("/leads?with_email=1", "E-postası olanlara bak", "Puanı yüksekten başla"), ("/leads?with_email=1", "İlk maili gönder", "Taslak hazır, sen gönder")]
    h = head("Panel", "Kakao alıcılarını bul, takip et, sipariş al.")
    if not all(done):
        h += (f'<div class="hero"><h2>Hoş geldin 👋 Başlamak için 4 adım</h2><p>Sırayla ilerle, her adım bir öncekinin üzerine kurulu. '
              f'Hepsi ücretsiz; birkaç dakikada ilk firma listen hazır olur.</p><div class="steps">')
        for i, ((u, t, s), d) in enumerate(zip(steps, done), 1):
            h += f'<a class="step {"done" if d else ""}" href="{u}"><div class="n">{icon("check", 15) if d else i}</div><div><b>{t}</b><span>{s}</span></div></a>'
        h += "</div></div>"
    kp = [("", "building", "Toplam firma", total), ("a", "mail", "E-postası bulunan", emails),
          ("", "users", "Henüz yazılmamış", n("SELECT COUNT(*) FROM companies WHERE status='new'")),
          ("a", "trend", "Süreçte", n("SELECT COUNT(*) FROM companies WHERE status IN ('replied','sample','negotiation')")),
          ("g", "award", "Kazanılan", n("SELECT COUNT(*) FROM companies WHERE status='won'")),
          ("r", "clock", "Bugün takip", n("SELECT COUNT(*) FROM companies WHERE next_followup<=? AND status NOT IN ('won','lost')", td))]
    h += '<div class="grid kpis">' + "".join(
        f'<div class="card kpi {c}"><div class="ic">{icon(i, 22)}</div><div><b>{v}</b><span>{k}</span></div></div>' for c, i, k, v in kp) + "</div>"
    counts = {st: n("SELECT COUNT(*) FROM companies WHERE status=?", st) for st in STATUSES}
    if total:
        bar = "".join(f'<i style="width:{100 * counts[s] / total:.2f}%;background:{STATUS_COLOR[s]}" title="{STATUS_TR[s]}: {counts[s]}"></i>' for s in STATUSES if counts[s])
        lg = "".join(f'<span style="--c:{STATUS_COLOR[s]}">{STATUS_TR[s]} <b>{counts[s]}</b></span>' for s in STATUSES if counts[s])
        h += f'<div class="card" style="margin-top:16px"><h3>Satış hattı</h3><div class="funnel">{bar}</div><div class="legend">{lg}</div></div>'
        h += "<h2 style='margin-top:22px'>Müşteri adayları</h2><div class='kanban'>"
        for st in ["new", "contacted", "replied", "sample", "negotiation", "won", "nurture"]:
            rows = con.execute("SELECT * FROM companies WHERE status=? ORDER BY score DESC LIMIT 8", (st,)).fetchall()
            h += f'<div class="col" style="--c:{STATUS_COLOR[st]}"><h4>{STATUS_TR[st]}<span>{counts[st]}</span></h4>'
            for r in rows:
                h += (f'<a class="lead" href="/lead/{r["id"]}"><b>{esc(r["name"])}</b>'
                      f'<small>{esc(cname(r["country"]))} · {SEGMENT_TR.get(r["segment"], "")} · {r["score"]} puan</small></a>')
            if counts[st] > len(rows):
                h += f'<a href="/leads?status={st}">+{counts[st] - len(rows)} daha…</a>'
            h += "</div>"
        h += "</div>"
    h += "<div class='grid two' style='margin-top:22px'><div><h2>Bugün takip edilecekler</h2>"
    due = con.execute("SELECT * FROM companies WHERE next_followup<=? AND status NOT IN ('won','lost') ORDER BY next_followup LIMIT 20", (td,)).fetchall()
    h += (lead_table(due) if due else '<div class="card flat muted">Bugün takip edilecek firma yok. 🎉</div>') + "</div><div><h2>İlk yazılacak firmalar</h2>"
    top = con.execute("SELECT * FROM companies WHERE status='new' AND id IN (SELECT company_id FROM contacts WHERE email_ok=1) "
                      "ORDER BY score DESC LIMIT 8").fetchall()
    h += "".join(f'<a class="lead" href="/lead/{r["id"]}" style="display:flex;gap:10px;align-items:center">{badge(r["score"])}<span><b>{esc(r["name"])}</b>'
                 f'<small>{esc(cname(r["country"]))}</small></span></a>' for r in top) or \
        '<div class="card flat muted">E-postası bulunan firma henüz yok. <a href="/tools">Firma bul</a> sayfasından başla.</div>'
    return "Panel", h + "</div></div>", "/"


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
    ctry = [r[0] for r in con.execute("SELECT DISTINCT country FROM companies WHERE country IS NOT NULL ORDER BY 1")]
    form = f"""<form class="inline card" method="get"><div><label>Ara</label><input name="q" value="{esc(g('q'))}" placeholder="firma, site, şehir"></div>
<div><label>Durum</label><select name="status">{opts([(s, STATUS_TR[s]) for s in STATUSES], g('status'), 'Hepsi')}</select></div>
<div><label>Segment</label><select name="segment">{opts(list(SEGMENT_TR.items()), g('segment'), 'Hepsi')}</select></div>
<div><label>Ülke</label><select name="country">{opts([(c, cname(c)) for c in ctry], g('country').upper(), 'Hepsi')}</select></div>
<div><label>Min. puan</label><input name="min_score" size="3" value="{esc(g('min_score'))}" style="width:70px"></div>
<div><label>&nbsp;</label><label class="chip" style="padding:9px 11px"><input type="checkbox" name="with_email" value="1"{" checked" if g('with_email') else ""}> sadece e-postalı</label></div>
<button>{icon('search', 16)} Filtrele</button><a class="btn ghost" href="/export.csv">Excel'e aktar</a></form>"""
    body = lead_table(rows) if rows else empty("users", "Burada gösterilecek firma yok.",
                                              '<p><a class="btn" href="/tools">Firma bul</a> <a class="btn ghost" href="/import">Liste yükle</a></p>')
    return "Firmalar", head("Firmalar", f"{len(rows)} firma gösteriliyor, puanı yüksek olan üstte") + form + "<br>" + body, "/leads"


def page_lead(con, cid, q):
    c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    if not c:
        return "Bulunamadı", head("Firma bulunamadı"), "/leads"
    lang = (q.get("lang") or ["en"])[0]
    tpl = (q.get("tpl") or ["cold"])[0]
    sub = f'{esc(c["city"] or "")} {esc(cname(c["country"]))} · {SEGMENT_TR.get(c["segment"], "")} · kaynak: {esc(c["source"] or "-")}'
    if c["website"]:
        sub += f' · <a href="{esc(c["website"])}" target=_blank rel=noopener>{esc(leads.get_domain(c["website"]))}</a>'
    h = head(f'{esc(c["name"])} {badge(c["score"])}', sub, pill(c["status"])) + "<div class='grid two'><div>"
    h += "<div class='card'><h3>Kişiler</h3><div class='tw'><table><tr><th>Ad</th><th>Görev</th><th>E-posta</th><th>Telefon</th></tr>"
    for k in con.execute("SELECT * FROM contacts WHERE company_id=?", (cid,)):
        mark = ('<span title="Adres geçerli görünüyor" style="color:var(--ok)">✔</span>' if k["email_ok"]
                else ('<span title="Adres geçersiz olabilir" style="color:var(--bad)">✖</span>' if k["email"] else ""))
        h += (f'<tr><td>{esc(k["name"] or "-")}</td><td>{esc(k["role"] or "-")}</td>'
              f'<td>{esc(k["email"] or "-")} {mark}</td><td>{esc(k["phone"] or "-")}</td></tr>')
    h += f"""</table></div><form class="inline" method="post" action="/lead/{cid}/contact" style="margin-top:12px">
<input name="name" placeholder="Ad Soyad"><input name="role" placeholder="Görev"><input name="email" placeholder="e-posta"><input name="phone" placeholder="telefon">
<button class="ghost">{icon('plus', 15)} Kişi ekle</button></form></div>"""
    h += f"""<div class="card" style="margin-top:16px"><h3>Geçmiş ve takip</h3>
<form class="inline" method="post" action="/lead/{cid}/log"><div><label>Tür</label><select name="kind">{opts(list(KIND_TR.items()))}</select></div>
<div style="flex:1;min-width:200px"><label>Özet</label><input name="summary" required style="width:100%" placeholder="Ne konuşuldu / ne gönderildi?"></div>
<div><label>Durum</label><select name="status">{opts([(s, STATUS_TR[s]) for s in STATUSES], None, 'Değişmesin')}</select></div>
<div><label>Takip (gün)</label><input name="followup" placeholder="oto" style="width:70px"></div><button>Kaydet</button></form><ul class="tl">"""
    for x in con.execute("SELECT * FROM activities WHERE company_id=? ORDER BY ts DESC", (cid,)):
        h += f'<li><b>{KIND_TR.get(x["kind"], x["kind"])}</b> <span class="muted">{esc(x["ts"][:16])}</span><br>{esc(x["summary"])}</li>'
    h += "</ul></div></div><div>"
    h += f"""<div class="card"><h3>Durum</h3><p>{pill(c['status'])} &nbsp; sonraki takip: <b>{esc(c['next_followup'] or '-')}</b></p>
<form method="post" action="/lead/{cid}/edit"><label>Segment</label><select name="segment" style="width:100%">{opts(list(SEGMENT_TR.items()), c['segment'])}</select><br><br>
<label>Notlar</label><textarea name="notes" rows="4">{esc(c['notes'] or '')}</textarea><br><br><button class="ghost">Güncelle</button></form>
<form method="post" action="/suppress" onsubmit="return confirm('Bu firmaya bir daha yazılmayacak. Emin misiniz?')" style="margin-top:12px">
<input type="hidden" name="value" value="{esc(c['domain'] or '')}"><input type="hidden" name="back" value="/lead/{cid}">
<button class="ghost" {"disabled" if not c['domain'] else ""}>Abonelikten çıktı / engelle</button></form></div>"""
    try:
        to, text = leads.render_email(con, cid, lang, tpl)
        lines = text.split("\n")
        subject = lines[0].split(":", 1)[1].strip() if ":" in lines[0] else ""
        body = "\n".join(lines[1:]).strip()
        mailto = f"mailto:{to or ''}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
        mail = (f'<p class="muted">Alıcı: <b>{esc(to or "geçerli e-posta yok – Firma bul sayfasından e-posta toplayın")}</b></p>'
                f'<pre class="mail" id="mail">{esc(text)}</pre><p><a class="btn alt" href="{esc(mailto)}">{icon("mail", 16)} Mail uygulamasında aç</a> '
                f'<button type="button" class="ghost" onclick="navigator.clipboard.writeText(document.getElementById(\'mail\').innerText);this.textContent=\'Kopyalandı ✔\'">Kopyala</button></p>')
    except ValueError as e:
        mail = f'<p class="muted">{esc(str(e))}</p>'
    tdir = os.path.join(leads.HERE, "templates")
    langs = sorted({f.split("_")[0] for f in os.listdir(tdir)})
    tpls = sorted({f.split("_", 1)[1][:-4] for f in os.listdir(tdir)})
    h += f"""<div class="card" style="margin-top:16px"><h3>E-posta taslağı</h3><form class="inline" method="get">
<select name="lang">{opts([(x, x.upper()) for x in langs], lang)}</select><select name="tpl">{opts([(x, x) for x in tpls], tpl)}</select>
<button class="ghost">Göster</button></form><br>{mail}</div></div></div>"""
    return c["name"], h, "/leads"


def page_add(con, q):
    return "Firma ekle", head("Firma ekle", "Tek bir firmayı elle kaydet.") + f"""<form class="card" method="post" action="/add"><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(230px,1fr))">
<div><label>Firma adı *</label><input name="name" required style="width:100%"></div><div><label>Web sitesi</label><input name="website" style="width:100%" placeholder="firma.com"></div>
<div><label>Ülke</label><select name="country" style="width:100%">{opts([(k, v[0]) for k, v in sorted(COUNTRIES.items(), key=lambda x: tr_key(x[1][0]))], None, 'Seç…')}</select></div>
<div><label>Şehir</label><input name="city" style="width:100%"></div>
<div><label>Segment</label><select name="segment" style="width:100%">{opts(list(SEGMENT_TR.items()))}</select></div>
<div><label>E-posta</label><input name="email" style="width:100%"></div><div><label>Telefon</label><input name="phone" style="width:100%"></div>
<div><label>Kaynak</label><input name="source" value="manuel" style="width:100%"></div></div><br><label>Notlar</label><textarea name="notes" rows="3"></textarea><br><br><button>{icon('plus', 16)} Ekle</button></form>""", "/add"


def page_import(con, q):
    return "İçe aktar", head("Liste yükle", "Fuar katılımcı listesi, ImportYeti sonucu ya da Excel'deki bir listeyi toplu ekle.") + f"""<form class="card" method="post" action="/import">
<p class="muted">Excel'de <b>"CSV olarak kaydet"</b> yapıp buraya yükle. Sütun adları: <code>name, country, website, segment, city, email, phone, notes</code> (sadece <b>name</b> zorunlu).
Aynı firma ikinci kez eklenmez.</p>
<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr))"><div><label>Kaynak adı (nereden aldın?)</label><input name="source" value="Fuar-2026" required style="width:100%"></div>
<div><label>CSV dosyası seç</label><input type="file" accept=".csv,.txt" onchange="const f=this.files[0];if(f)f.text().then(t=>document.getElementById('csv').value=t)"></div></div><br>
<label>veya buraya yapıştır</label><textarea id="csv" name="csv" rows="12" required></textarea><br><br><button>{icon('upload', 16)} İçe aktar</button></form>""", "/import"


def fmt_money(v):
    return f"{v / 1e6:,.0f} M$".replace(",", ".")


def page_markets(con, q):
    hs = (q.get("hs") or ["1805"])[0]
    hs_arg = None if hs == "all" else hs
    rows = leads.market_rows(con, hs_arg, None, 40)
    note = ""
    if not rows and hs_arg:
        rows, hs, note = leads.market_rows(con, None, None, 40), "all", "Bu ürün için veri çekilmemiş, tüm kakao ürünlerinin toplamı gösteriliyor."
    sel = opts(PRODUCTS + [("all", "Hepsinin toplamı")], hs)
    h = head("Hedef pazarlar", "Hangi ülkeler ne kadar kakao ithal ediyor ve Türkiye'den ne kadarını alıyor? (UN Comtrade resmi gümrük verisi)")
    h += (f'<form class="inline card" method="get"><div><label>Ürün</label><select name="hs">{sel}</select></div><button class="ghost">Göster</button>'
          f'<span class="muted" style="margin-left:auto;max-width:520px">Küçük Türkiye payı = rakiplerin hâkim olduğu ama sizin girebileceğiniz pazar demektir; '
          f'ama çoğu zaman fiyat ve lojistikte rekabet gerektirir.</span></form><br>')
    if note:
        h += f'<div class="flash">{esc(note)}</div>'
    if not rows:
        return "Pazarlar", h + empty("globe", "Henüz pazar verisi yok.", '<p><a class="btn" href="/tools">Pazar verisini çek</a></p>'), "/markets"
    top = max(r["total"] for r in rows) or 1
    h += '<form method="post" action="/job/find"><div class="tw"><table><tr><th></th><th>#</th><th>Ülke</th><th>Yıllık ithalat</th><th></th><th>Türkiye payı</th><th>Sistemdeki firma</th><th></th></tr>'
    for i, r in enumerate(rows, 1):
        cc = ISO3_TO_ISO2.get(r["iso"])
        cnt = con.execute("SELECT COUNT(*) FROM companies WHERE country=?", (cc,)).fetchone()[0] if cc else 0
        share = 100 * r["from_tr"] / r["total"] if r["total"] else 0
        action = (f'<button class="sm alt" name="country" value="{cc}" title="Bu ülkedeki işletmeleri otomatik bul">{icon("search", 14)} Firma bul</button>' if cc
                  else '<span class="muted" title="Bu ülke için otomatik arama tanımlı değil">–</span>')
        h += (f'<tr><td>{f"<input type=checkbox name=c value={cc}>" if cc else ""}</td><td>{i}</td><td><b>{esc(cname(cc) if cc else r["importer"])}</b></td>'
              f'<td>{fmt_money(r["total"])}</td><td style="width:22%"><div class="bar"><i style="width:{100 * r["total"] / top:.0f}%"></i></div></td>'
              f'<td>%{share:.1f}</td><td>{f"<a href=/leads?country={cc}><b>{cnt}</b></a>" if cnt else "0"}</td><td>{action}</td></tr>')
    h += f'</table></div><p style="margin-top:14px"><button>{icon("zap", 16)} Seçili ülkelerde firma bul</button> <span class="muted">Kutucukları işaretleyip tek seferde birden fazla ülke tarayabilirsin.</span></p></form>'
    return "Pazarlar", h, "/markets"


def page_tools(con, q):
    if JOB["running"]:
        last = [l for l in JOB["log"].strip().split("\n") if l.strip()][-1:] or ["Başlıyor…"]
        status = (f'<div class="flash"><div class="spin"></div><div><b>Çalışıyor: {esc(JOB["name"])}</b><br>'
                  f'<small class="muted">{esc(last[0].strip())}</small></div>'
                  f'<form method="post" action="/job/cancel" style="margin-left:auto"><button class="ghost sm">Durdur</button></form></div>'
                  f'<script>setTimeout(()=>location.reload(),5000)</script>')
    else:
        status = ""
    if JOB["summary"] and not JOB["running"]:
        status += f'<div class="result">✔ {esc(JOB["summary"])} &nbsp; <a href="/leads?with_email=1">Firmaları gör →</a></div>'
    if JOB["log"]:
        status += f'<details {"open" if JOB["running"] else ""}><summary>Ayrıntılı kayıt</summary><pre class="mail">{esc(JOB["log"])}</pre></details><br>'
    has_market = con.execute("SELECT COUNT(*) FROM trade_flows").fetchone()[0] > 0
    dis = "disabled" if JOB["running"] else ""
    h = head("Firma bul", "Birkaç tıkla hedef ülkelerdeki kakao/çikolata/şekerleme işletmelerini listele.") + status
    h += f"""<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(340px,1fr))">
<form class="card tool" method="post" action="/job/find" style="grid-column:1/-1"><span class="no">ASIL İŞ</span><h3>Otomatik firma bul</h3>
<p class="muted" style="margin:0">Seçtiğin ülkelerdeki çikolatacı, şekerleme, dondurma ve gıda üreticilerini <b>harita verisinden</b> bulur;
web siteleri varsa <b>e-posta adreslerini</b> toplar ve <b>puanlar</b>. Hepsi tek tıkla, ücretsiz. Ülke başına ortalama 2–4 dakika sürer; bu sırada sayfayı kapatma.</p>
{country_chips(DEFAULT_FIND)}<div><button {dis}>{icon('zap', 16)} Seçili ülkelerde firma bul</button></div></form>
<form class="card tool" method="post" action="/job/comtrade"><span class="no">İSTEĞE BAĞLI · BİR KEZ</span><h3>Pazar verisi</h3>
<p class="muted" style="margin:0">Hangi ülkeler ne kadar kakao ithal ediyor? Resmi gümrük istatistiklerini çeker. {"✔ Veri yüklü." if has_market else "Henüz yüklenmedi."} Birkaç dakika sürer, yarıda kalırsa tekrar bas.</p>
<div><label>Yıl</label><input name="year" value="{leads.config().get('comtrade_year', 2023)}" style="width:90px"> <button {dis}>Pazar verisini çek</button></div></form>
<form class="card tool" method="post" action="/job/score"><span class="no">GEREKTİĞİNDE</span><h3>Puanları yenile</h3>
<p class="muted" style="margin:0">Elle firma ekledikten ya da liste yükledikten sonra puanların güncellenmesi için.</p><div><button class="ghost" {dis}>Puanla</button></div></form>
<form class="card tool" method="post" action="/job/enrich"><span class="no">GEREKTİĞİNDE</span><h3>Sadece e-posta ara</h3>
<p class="muted" style="margin:0">Elle eklediğin ya da yüklediğin firmaların web sitelerinden e-posta adresi toplar (en yüksek puanlılardan başlar).</p>
<div><label>Kaç firma</label><input name="limit" value="30" style="width:80px"> <button class="ghost" {dis}>E-posta ara</button></div></form></div>
<details style="margin-top:18px"><summary>Teknik bilgi</summary><p class="muted">Firmalar OpenStreetMap (açık harita) verisinden, pazar istatistikleri UN Comtrade'den, e-postalar firmaların kendi
sitelerindeki iletişim sayfalarından gelir. Siteler robots.txt'e uygun ve yavaş taranır. Bu yöntem küçük/orta işletmeleri iyi bulur; büyük fabrikalar için fuar listelerini
<a href="/import">İçe aktar</a> sayfasından yükle.</p></details>"""
    return "Firma bul", h, "/tools"


# ------------------------------------------------------------------ iş yürütme
def run_job(name, fn):
    with JOB_LOCK:
        if JOB["running"]:
            return False
        JOB.update(running=True, name=name, log="", summary="")
        leads.CANCEL.clear()

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


def find_firms(countries):
    """Harita verisinden firma bul → e-posta topla → puanla. Sonucu JOB['summary']'ye yazar."""
    def stats():
        c = leads.db()
        try:
            return (c.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
                    c.execute("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE email_ok=1").fetchone()[0])
        finally:
            c.close()
    b_firms, b_mail = stats()
    leads.cmd_harvest_osm(argparse.Namespace(country=",".join(countries), segments=None))
    if not leads.CANCEL.is_set():
        print("\n--- E-posta aranıyor (yeni firmaların siteleri) ---", flush=True)
        leads.cmd_enrich(argparse.Namespace(limit=60))
    leads.cmd_score(argparse.Namespace())
    a_firms, a_mail = stats()
    JOB["summary"] = f"{a_firms - b_firms} yeni firma bulundu, {a_mail - b_mail} firmanın e-postası eklendi ve hepsi puanlandı."


# ------------------------------------------------------------------ sunucu
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
                return self._export()
            routes = {"/": page_dashboard, "/leads": page_leads, "/add": page_add, "/import": page_import,
                      "/markets": page_markets, "/tools": page_tools}
            if u.path in routes:
                title, body, act = routes[u.path](con, q)
            elif u.path.startswith("/lead/") and u.path[6:].isdigit():
                title, body, act = page_lead(con, int(u.path[6:]), q)
            else:
                return self._send(404, layout("404", head("Sayfa yok")))
            self._send(200, layout(title, body, act, flash))
        finally:
            con.close()

    def _export(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False) as t:
            path = t.name
        try:
            leads.cmd_export(argparse.Namespace(file=path))
            with open(path, "rb") as f:
                data = f.read()
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
        multi = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True)
        f = {k: v[0].strip() for k, v in multi.items()}
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
                return self._redirect("/leads", f"{new} yeni firma eklendi, {dup} tekrar atlandı. Puanlamak için Firma bul → Puanla.")
            if path == "/suppress":
                if f.get("value"):
                    leads.cmd_suppress(argparse.Namespace(value=f["value"]))
                return self._redirect(f.get("back") or "/", "Engelleme listesine eklendi")
            if path.startswith("/job/"):
                kind = path[5:]
                if kind == "cancel":
                    leads.CANCEL.set()
                    return self._redirect("/tools", "Durduruluyor, birkaç saniye sürebilir")
                if kind == "find":
                    ccs = [c.upper() for c in multi.get("country", []) + multi.get("c", []) if c.upper() in COUNTRIES]
                    ccs = list(dict.fromkeys(ccs))
                    if multi.get("country"):  # satırdaki tekil "Firma bul" düğmesi: sadece o ülke
                        ccs = [c for c in ccs if c in [x.upper() for x in multi["country"]]]
                    if not ccs:
                        return self._redirect("/tools", "En az bir ülke seçin")
                    ok = run_job(f"{', '.join(cname(c) for c in ccs)} için firma bulunuyor", lambda: find_firms(ccs))
                    return self._redirect("/tools", "Başlatıldı, bu sayfada ilerlemeyi görebilirsiniz" if ok else "Başka bir iş çalışıyor")
                jobs = {"comtrade": ("Pazar verisi çekiliyor", lambda: leads.cmd_harvest_comtrade(argparse.Namespace(hs=None, year=int(f.get("year") or 0) or None))),
                        "enrich": ("E-posta aranıyor", lambda: leads.cmd_enrich(argparse.Namespace(limit=int(f.get("limit") or 30)))),
                        "score": ("Puanlanıyor", lambda: leads.cmd_score(argparse.Namespace()))}
                if kind not in jobs:
                    return self._send(404, "yok")
                ok = run_job(*jobs[kind])
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
