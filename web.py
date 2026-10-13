#!/usr/bin/env python3
"""Imesta Food lead sistemi – web arayüzü (sadece standart kütüphane).

Çalıştır:  python3 web.py            → http://127.0.0.1:8765
İnternete açacaksanız WEB_PASSWORD ortam değişkeni belirleyin (HTTP Basic şifre, kullanıcı adı: imesta).
Renkler/logo: config.json içindeki "theme" bölümü.
"""
import argparse
import base64
import contextlib
import datetime as dt
import hmac
import html
import os
import sqlite3
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import leads
from leads import STATUSES, SEGMENTS, COUNTRIES

esc = html.escape
STATUS_TR = {"new": "Yeni", "contacted": "İletişimde", "replied": "Yanıt verdi", "sample": "Numune",
             "negotiation": "Pazarlık", "won": "Kazanıldı", "lost": "Kaybedildi", "nurture": "Beklemede"}
STATUS_COLOR = {"new": "#9a8470", "contacted": "#3b82c4", "replied": "#8b5cf6", "sample": "#d98324",
                "negotiation": "#b8863b", "won": "#2e7d32", "lost": "#b04a3a", "nurture": "#6b7f8c"}
OPEN_STATUSES = ("contacted", "replied", "sample", "negotiation")
SEGMENT_TR = {"chocolate_maker": "Çikolata üreticisi", "confectionery": "Şekerleme / bisküvi", "distributor": "Distribütör",
              "bakery_ingredient": "Pastane / fırın malzemesi", "ice_cream": "Dondurma", "dairy_beverage": "Süt / içecek",
              "retail_craft": "Butik / perakende", "other": "Diğer"}
KIND_TR = {"email": "E-posta", "call": "Arama", "sample": "Numune", "meeting": "Görüşme", "note": "Not"}
DEPT_TR = {"purchasing": "Satın alma", "export": "İhracat", "sales": "Satış", "management": "Yönetim", "person": "Kişi", "info": "Genel",
           "marketing": "Pazarlama", "quality": "Kalite", "logistics": "Lojistik", "support": "Destek", "accounting": "Muhasebe", "hr": "İK",
           "personal": "Kişisel posta", "other": "Diğer", "phone": "Telefon"}
BTYPE_TR = {"manufacturer": "Üretici", "wholesale": "Toptancı / distribütör", "retail": "Perakende", "unknown": "Belirsiz"}
PRODUCTS = [("1805", "Kakao tozu"), ("1804", "Kakao yağı (butter)"), ("1803", "Kakao hamuru (liquor)"),
            ("1801", "Kakao çekirdeği"), ("1806", "Çikolata ve kakaolu ürünler")]
DEFAULT_FIND = ["DE", "NL", "BE", "FR", "GB", "PL", "IT", "AE"]
ISO3_TO_ISO2 = {v[1]: k for k, v in COUNTRIES.items()}
PAGE_SIZE = 50
SORTS = {  # url anahtarı: (sql ifadesi, boş değerler sona mı)
    "score": ("score", False), "name": ("name COLLATE NOCASE", False), "country": ("country", True),
    "segment": ("segment", False), "status": ("CASE status WHEN 'negotiation' THEN 0 WHEN 'sample' THEN 1 WHEN 'replied' THEN 2 "
                                              "WHEN 'contacted' THEN 3 WHEN 'new' THEN 4 WHEN 'nurture' THEN 5 WHEN 'won' THEN 6 ELSE 7 END", False),
    "data": ("data_score", False), "last": ("last_contacted", True), "next": ("next_followup", True), "value": ("value_usd", True), "new": ("id", False),
}
DE_COUNTRIES = {"DE", "AT", "CH"}

JOB = {"running": False, "name": "", "log": "", "summary": ""}
JOB_LOCK = threading.Lock()

ICONS = {
    "today": '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "board": '<rect x="3" y="3" width="7" height="18" rx="1.5"/><rect x="14" y="3" width="7" height="11" rx="1.5"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "mail": '<path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    "phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "trash": '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    "star": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "reply": '<polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>',
    "box": '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>',
    "x": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
}


def icon(name, size=16):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def tr_key(s):  # Türkçe harflere göre sıralama (Ç→C, İ→I ...)
    return s.translate(str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")).lower()


def cname(cc):
    return COUNTRIES.get((cc or "").upper(), (cc or "-",))[0]


def days_from_today(d):
    """'2026-10-13' → bugünden kaç gün önce (pozitif) / sonra (negatif). Boşsa None."""
    try:
        return (dt.date.today() - dt.date.fromisoformat(d[:10])).days
    except Exception:
        return None


def ago(d):
    n = days_from_today(d)
    if n is None:
        return "—"
    return "bugün" if n == 0 else f"{n} gün önce" if n > 0 else f"{-n} gün sonra"


def money(v):
    return "—" if not v else "$" + f"{v:,.0f}".replace(",", ".")


def num(s):
    try:
        return float(str(s).replace(".", "").replace(",", ".").replace("$", "").strip()) if str(s).strip() else None
    except ValueError:
        return None


CSS = """
:root{--brand:__BRAND__;--accent:__ACCENT__;--bg:__CREAM__;--cocoa:__COCOA__;--ink:#2a2018;--muted:#8b7b6b;--line:#ece4d8;--card:#fff;--soft:#f5efe5;--ok:#2e7d32;--bad:#b04a3a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14.5px/1.55 "Inter","Segoe UI",system-ui,-apple-system,Roboto,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--cocoa);text-underline-offset:2px}
h1,h2,h3{font-family:Georgia,"Times New Roman",serif;color:var(--brand);margin:0;font-weight:600;line-height:1.25}
h1{font-size:27px}h2{font-size:18px;margin-bottom:10px}h3{font-size:16px;margin-bottom:8px}
.muted{color:var(--muted)}small,.sm{font-size:12.5px}
header.top{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
header.top .in{max-width:1220px;margin:0 auto;padding:0 20px;display:flex;align-items:center;gap:28px;flex-wrap:wrap}
.logo{display:flex;align-items:center;gap:9px;padding:14px 0;color:var(--brand);text-decoration:none;font:700 19px Georgia,serif;letter-spacing:.5px}
.logo img{height:30px}.logo b{color:var(--accent)}.logo svg{color:var(--accent)}
nav{display:flex;gap:2px;flex-wrap:wrap}
nav a{color:#6f5f50;text-decoration:none;padding:17px 13px 15px;display:flex;align-items:center;gap:7px;font-weight:500;border-bottom:2px solid transparent}
nav a:hover{color:var(--brand)}nav a.on{color:var(--brand);font-weight:600;border-bottom-color:var(--accent)}
nav .cnt{background:var(--bad);color:#fff;border-radius:99px;font-size:11.5px;font-weight:700;padding:0 7px;line-height:18px}
main{max-width:1220px;margin:26px auto 70px;padding:0 20px}
.pagehead{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:20px}
.pagehead p{margin:4px 0 0;color:var(--muted)}.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.grid{display:grid;gap:16px}.two{grid-template-columns:1.7fr 1fr}@media(max-width:920px){.two{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}
.card.flat{background:transparent;border-style:dashed}
.stats{display:flex;gap:0;background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:22px;overflow:hidden;flex-wrap:wrap}
.stat{flex:1;min-width:130px;padding:14px 18px;border-right:1px solid var(--line)}.stat:last-child{border:0}
.stat b{display:block;font:600 24px Georgia,serif;color:var(--brand)}.stat span{color:var(--muted);font-size:12.5px}
.sec{margin-bottom:26px}.sec>.sh{display:flex;align-items:baseline;gap:10px;margin-bottom:8px}.sec>.sh h2{margin:0}
.count{background:var(--soft);color:var(--cocoa);border-radius:99px;padding:0 9px;font-size:12.5px;font-weight:600}
.count.bad{background:#f7e1dd;color:var(--bad)}
.task{display:flex;align-items:center;gap:14px;padding:11px 14px;background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:7px;flex-wrap:wrap}
.task:hover{border-color:#d9ccb7}.task .who{flex:1;min-width:220px}.task .who a{font-weight:600;color:var(--brand);text-decoration:none}.task .who a:hover{text-decoration:underline}
.task .who small{display:block;color:var(--muted)}.task .hint{font-size:12.5px;color:var(--muted);min-width:130px}.hint.bad{color:var(--bad);font-weight:600}
.task .act{display:flex;gap:6px;flex-wrap:wrap}
.banner{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;padding:14px 18px;margin-bottom:22px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.banner .st{display:flex;gap:6px;align-items:center;font-size:13.5px;text-decoration:none;color:var(--ink);padding:5px 10px;border-radius:99px;background:var(--soft)}
.banner .st.done{color:var(--ok);background:#e6f3e7}.banner .st b{width:18px;height:18px;border-radius:50%;background:var(--accent);color:#fff;font-size:11px;display:grid;place-items:center}
.banner .st.done b{background:var(--ok)}
.funnel{display:flex;height:10px;border-radius:99px;overflow:hidden;background:var(--soft);margin:12px 0 10px}.funnel i{display:block}
.legend{display:flex;gap:4px 16px;flex-wrap:wrap;font-size:13px;color:#6f5f50}.legend span:before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--c);margin-right:6px}
.kanban{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(230px,1fr);gap:12px;overflow-x:auto;padding-bottom:12px;align-items:start}
.col{background:var(--soft);border-radius:12px;padding:10px;min-height:160px;border-top:3px solid var(--c,#999);transition:.12s}
.col.over{background:#efe2c9;outline:2px dashed var(--accent)}
.col h4{margin:2px 2px 10px;font:600 12px "Segoe UI",sans-serif;text-transform:uppercase;letter-spacing:.6px;color:#6f5f50;display:flex;justify-content:space-between}
.col h4 span{color:var(--muted)}
.lead{display:block;background:#fff;border:1px solid var(--line);border-radius:9px;padding:9px 11px;margin-bottom:8px;text-decoration:none;color:var(--ink);cursor:grab}
.lead:hover{border-color:#d4c4a8}.lead.drag{opacity:.4}.lead small{color:var(--muted);display:block}.lead b{font-weight:600}
.lead .cold{color:var(--bad);font-weight:600}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th{background:#faf6ee;color:var(--muted);text-align:left;padding:10px 12px;font-size:11.5px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;font-weight:600}
th a{color:inherit;text-decoration:none}th a:hover{color:var(--brand)}th a.on{color:var(--brand)}
td{padding:10px 12px;border-top:1px solid #f3ece0;vertical-align:middle}tr:hover td{background:#fcfaf5}
td a.name{font-weight:600;text-decoration:none;color:var(--brand)}td a.name:hover{text-decoration:underline}td small{display:block;color:var(--muted)}
.tw{overflow-x:auto;border-radius:12px}
.score{display:inline-block;min-width:34px;text-align:center;border-radius:6px;padding:1px 7px;font-weight:700;font-size:13px;background:#efe8dc;color:#6f5f50}
.score.hi{background:#e1f1e2;color:var(--ok)}.score.mid{background:#f8ecd3;color:#8a5f14}
.pill{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12px;font-weight:600;background:color-mix(in srgb,var(--c,#999) 14%,#fff);color:var(--c,#555);white-space:nowrap}
.bar{height:6px;border-radius:99px;background:var(--soft);min-width:110px;overflow:hidden}.bar i{display:block;height:100%;background:var(--accent);border-radius:99px}
.late{color:var(--bad);font-weight:600}
form.inline{display:flex;gap:10px;flex-wrap:wrap;align-items:end}form.pl{display:inline}
label{font-size:12.5px;color:var(--muted);display:block;margin-bottom:3px;font-weight:600}
input,select,textarea{font:inherit;padding:8px 10px;border:1px solid #ddd2c0;border-radius:8px;background:#fff;max-width:100%;color:var(--ink)}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--accent);box-shadow:0 0 0 3px rgba(184,134,59,.18)}textarea{width:100%}
input[type=checkbox]{accent-color:var(--brand);width:16px;height:16px;padding:0}
button,.btn{font:inherit;font-weight:600;padding:8px 14px;border:1px solid var(--brand);border-radius:8px;background:var(--brand);color:#fff;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:.12s;white-space:nowrap}
button:hover,.btn:hover{filter:brightness(1.18)}
button.alt,.btn.alt{background:var(--accent);border-color:var(--accent);color:#fff}
button.ghost,.btn.ghost{background:#fff;color:var(--brand);border-color:#ddd2c0}button.ghost:hover,.btn.ghost:hover{background:var(--soft);filter:none}
button.sm,.btn.sm{padding:4px 10px;font-size:12.5px;border-radius:7px}
button.danger,.btn.danger{background:#fff;color:var(--bad);border-color:#ecc9c3}button.danger:hover{background:#fbeeec;filter:none}
button:disabled{opacity:.45;cursor:not-allowed}
.star{background:none;border:0;padding:2px;color:#cdbfaa;cursor:pointer}.star.on{color:#d9a21b}.star.on svg{fill:#d9a21b}.star:hover{filter:none;color:#d9a21b}
.flash{background:#fff8e6;border:1px solid #ecd596;padding:10px 14px;border-radius:10px;margin-bottom:16px;display:flex;gap:10px;align-items:center}
.tl{padding:0;margin:14px 0 0}.tl li{list-style:none;margin:0 0 10px;padding:1px 0 1px 12px;border-left:2px solid var(--accent)}
pre.mail{white-space:pre-wrap;background:#fffcf6;border:1px dashed #d6c8b0;border-radius:10px;padding:14px;font:13px/1.55 ui-monospace,Menlo,Consolas,monospace;max-height:420px;overflow:auto;margin:0 0 12px}
.chips{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin:10px 0 14px}
.chip{display:flex;align-items:center;gap:8px;margin:0;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:#fff;cursor:pointer;font-weight:500;font-size:14px;color:var(--ink)}
.chip:has(input:checked){border-color:var(--accent);background:#fff8e8}
.tool{display:flex;flex-direction:column;gap:6px}.tool .no{font:700 11.5px "Segoe UI";color:var(--accent);letter-spacing:.8px}
.empty{text-align:center;padding:40px 20px;color:var(--muted)}
.spin{width:16px;height:16px;border:3px solid #ecd596;border-top-color:var(--brand);border-radius:50%;animation:sp 1s linear infinite;flex:none}@keyframes sp{to{transform:rotate(360deg)}}
.result{background:#e8f5e9;border:1px solid #b5d9b8;border-radius:10px;padding:11px 15px;margin-bottom:14px;color:#1f5a23;font-weight:600}
details summary{cursor:pointer;color:var(--muted);font-weight:600;margin:6px 0}
#bulkbar{display:none;position:sticky;bottom:14px;z-index:10;margin-top:12px;background:var(--brand);color:#fff;border-radius:12px;padding:10px 14px;gap:10px;align-items:center;flex-wrap:wrap;box-shadow:0 8px 24px rgba(0,0,0,.25)}
#bulkbar.show{display:flex}#bulkbar select{padding:6px 8px}#bulkbar button{background:var(--accent);border-color:var(--accent)}
.pager{display:flex;gap:6px;align-items:center;justify-content:center;margin-top:16px;flex-wrap:wrap}.pager a,.pager span{padding:5px 11px;border:1px solid var(--line);border-radius:7px;text-decoration:none;background:#fff;color:var(--brand)}.pager span.cur{background:var(--brand);color:#fff;border-color:var(--brand)}
.next{background:#fff8e8;border:1px solid #ecd596;border-radius:10px;padding:11px 14px;margin-bottom:14px}
.kv{display:grid;grid-template-columns:110px 1fr;gap:6px 12px;margin:0}.kv dt{color:var(--muted);font-size:12.5px;padding-top:2px}.kv dd{margin:0;word-break:break-word}
.tag{display:inline-block;font-size:11.5px;font-weight:600;padding:0 7px;border-radius:5px;background:var(--soft);color:var(--cocoa);margin-left:4px}.tag.warn{background:#fff1cf;color:#8a5f14}
.soc a{margin-right:10px;white-space:nowrap}.meter{height:6px;border-radius:99px;background:var(--soft);overflow:hidden;margin-top:4px}.meter i{display:block;height:100%;background:var(--accent)}
.cover{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:18px}.cover b{font:600 20px Georgia,serif;color:var(--brand)}.cover span{display:block;font-size:12.5px;color:var(--muted)}
.row2{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
"""

SCRIPT = """
function star(id,btn){fetch('/lead/'+id+'/star',{method:'POST'}).then(function(){btn.classList.toggle('on')})}
function selAll(cb){document.querySelectorAll('input.rowchk').forEach(function(c){c.checked=cb.checked});updBulk()}
function updBulk(){var n=document.querySelectorAll('input.rowchk:checked').length,b=document.getElementById('bulkbar');
 if(b){b.classList.toggle('show',n>0);document.getElementById('bulkn').textContent=n}}
function bulkGo(f){var v=f.elements['do'].value;if(!v){alert('Önce bir işlem seçin');return false}
 if(v==='delete'){return confirm('Seçili firmalar silinecek (kişileri ve geçmişleriyle). Aynı firmalar sonraki taramalarda tekrar eklenmez. Silinsin mi?')}return true}
document.querySelectorAll('.lead[draggable]').forEach(function(c){
 c.addEventListener('dragstart',function(e){e.dataTransfer.setData('text/plain',c.dataset.id);c.classList.add('drag')});
 c.addEventListener('dragend',function(){c.classList.remove('drag')})});
document.querySelectorAll('.col[data-status]').forEach(function(col){
 col.addEventListener('dragover',function(e){e.preventDefault();col.classList.add('over')});
 col.addEventListener('dragleave',function(){col.classList.remove('over')});
 col.addEventListener('drop',function(e){e.preventDefault();var id=e.dataTransfer.getData('text/plain'),body='status='+col.dataset.status;
  if(col.dataset.status==='lost'){var r=prompt('Kaybetme nedeni (isteğe bağlı):');body+='&reason='+encodeURIComponent(r||'')}
  fetch('/lead/'+id+'/status',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:body}).then(function(){location.reload()})})});
"""


def css():
    t = {"brand": "#3B2418", "accent": "#B8863B", "cream": "#FAF8F4", "cocoa": "#6F4E37", **leads.config().get("theme", {})}
    out = CSS
    for k, v in (("__BRAND__", t["brand"]), ("__ACCENT__", t["accent"]), ("__CREAM__", t["cream"]), ("__COCOA__", t["cocoa"])):
        out = out.replace(k, v)
    return out


def layout(title, body, active="", flash="", due=0):
    cfg = leads.config()
    logo = cfg.get("theme", {}).get("logo_url")
    mark = f'<img src="{esc(logo)}" alt="">' if logo else icon("zap", 20)
    nav = [("/", "Bugün", "today"), ("/pipeline", "Satış hattı", "board"), ("/leads", "Firmalar", "users"),
           ("/markets", "Pazarlar", "globe"), ("/tools", "Firma bul", "search")]
    links = "".join(
        f'<a href="{u}" class="{"on" if u == active else ""}">{icon(i)}{n}'
        f'{f"<span class=cnt>{due}</span>" if u == "/" and due else ""}</a>' for u, n, i in nav)
    fl = f'<div class="flash">{icon("check")} {esc(flash)}</div>' if flash else ""
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · {esc(cfg['company_name'])}</title><style>{css()}</style></head><body>
<header class="top"><div class="in"><a class="logo" href="/">{mark}<span>IMESTA <b>COCOA</b></span></a><nav>{links}</nav></div></header>
<main>{fl}{body}</main><script>{SCRIPT}</script></body></html>"""


def head(title, sub="", action=""):
    return f'<div class="pagehead"><div><h1>{title}</h1><p>{sub}</p></div><div class="actions">{action}</div></div>'


def score_badge(score):
    return f'<span class="score {"hi" if score >= 70 else "mid" if score >= 45 else ""}" title="Potansiyel puanı (0-100)">{score}</span>'


def pill(status):
    return f'<span class="pill" style="--c:{STATUS_COLOR.get(status, "#999")}">{STATUS_TR.get(status, status)}</span>'


def star_btn(cid, on):
    return f'<button type="button" class="star{" on" if on else ""}" onclick="star({cid},this)" title="Öne çıkar">{icon("star", 17)}</button>'


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


def due_count(con):
    return con.execute("SELECT COUNT(*) FROM companies WHERE next_followup<=? AND status NOT IN ('won','lost')", (leads.today(),)).fetchone()[0]


# ------------------------------------------------------------------ Bugün
def quick_form(cid, do, label, ic, back, cls="ghost sm", title=""):
    return (f'<form class="pl" method="post" action="/lead/{cid}/quick"><input type="hidden" name="do" value="{do}">'
            f'<input type="hidden" name="back" value="{esc(back)}"><button class="{cls}" title="{esc(title or label)}">{icon(ic, 14)} {label}</button></form>')


def task_row(r, hint, bad=False, kind="follow"):
    cid = r["id"]
    acts = ""
    if kind == "new":
        acts += f'<a class="btn ghost sm" href="/lead/{cid}">{icon("mail", 14)} Taslağı aç</a>'
        acts += quick_form(cid, "sent", "Gönderdim", "check", "/", "sm", "E-posta gönderildi olarak kaydet")
    else:
        acts += quick_form(cid, "sent", "Mail attım", "mail", "/")
        acts += quick_form(cid, "called", "Aradım", "phone", "/")
        acts += quick_form(cid, "replied", "Cevap geldi", "reply", "/")
        acts += quick_form(cid, "snooze", "3 gün ertele", "clock", "/")
        acts += f'<a class="btn ghost sm" href="/lead/{cid}">Aç</a>'
    return (f'<div class="task"><div class="who"><a href="/lead/{cid}">{esc(r["name"])}</a>'
            f'<small>{esc(cname(r["country"]))} · {SEGMENT_TR.get(r["segment"], "")}'
            f'{" · ☎ <a href=tel:" + esc(r["phone"]) + ">" + esc(r["phone"]) + "</a>" if r["phone"] else ""}</small></div>'
            f'<div>{score_badge(r["score"])}</div><div>{pill(r["status"])}</div>'
            f'<div class="hint{" bad" if bad else ""}">{esc(hint)}</div><div class="act">{acts}</div></div>')


def section(title, rows, hint_fn, bad=False, kind="follow", empty_msg=""):
    if not rows and not empty_msg:
        return ""
    h = f'<div class="sec"><div class="sh"><h2>{title}</h2><span class="count{" bad" if bad and rows else ""}">{len(rows)}</span></div>'
    h += "".join(task_row(r, hint_fn(r), bad, kind) for r in rows) if rows else f'<div class="card flat muted">{empty_msg}</div>'
    return h + "</div>"


def page_today(con, q):
    td = leads.today()
    n = lambda sql, *p: con.execute(sql, p).fetchone()[0]  # noqa: E731
    total = n("SELECT COUNT(*) FROM companies")
    emails = n("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE email_ok=1")
    has_market = n("SELECT COUNT(*) FROM trade_flows") > 0
    sent = n("SELECT COUNT(*) FROM activities WHERE kind='email'")
    h = head("Bugün", dt.date.today().strftime("%d.%m.%Y") + " — kimseyi kaçırma: önce gecikenler, sonra bugünküler.",
             f'<a class="btn ghost" href="/add">{icon("plus")} Firma ekle</a><a class="btn" href="/tools">{icon("search")} Firma bul</a>')
    steps = [(has_market, "/tools", "Pazar verisini çek"), (total > 0, "/tools", "Firma bul"),
             (emails > 0, "/leads?with_email=1", "E-postalı firmaları incele"), (sent > 0, "/", "İlk maili gönder")]
    if not all(s[0] for s in steps):
        h += '<div class="banner"><b>Başlangıç</b>' + "".join(
            f'<a class="st {"done" if d else ""}" href="{u}"><b>{icon("check", 11) if d else i}</b>{t}</a>' for i, (d, u, t) in enumerate(steps, 1)) + "</div>"
    pipe = n("SELECT IFNULL(SUM(value_usd),0) FROM companies WHERE status IN ('contacted','replied','sample','negotiation')")
    won, lost = n("SELECT COUNT(*) FROM companies WHERE status='won'"), n("SELECT COUNT(*) FROM companies WHERE status='lost'")
    h += ('<div class="stats">' +
          "".join(f'<div class="stat"><b>{v}</b><span>{k}</span></div>' for k, v in [
              ("Toplam firma", total), ("E-postası olan", emails), ("Süreçte", n("SELECT COUNT(*) FROM companies WHERE status IN ('contacted','replied','sample','negotiation')")),
              ("Açık fırsat değeri", money(pipe)), ("Kazanılan", won), ("Kazanma oranı", f"%{100 * won // (won + lost)}" if won + lost else "—")]) + "</div>")
    base = "SELECT c.*, (SELECT 1 FROM contacts k WHERE k.company_id=c.id AND k.email_ok=1 LIMIT 1) has_email FROM companies c "
    overdue = con.execute(base + "WHERE next_followup<? AND status NOT IN ('won','lost') ORDER BY next_followup, score DESC", (td,)).fetchall()
    today_rows = con.execute(base + "WHERE next_followup=? AND status NOT IN ('won','lost') ORDER BY score DESC", (td,)).fetchall()
    taken = {r["id"] for r in overdue + today_rows}
    waiting = [r for r in con.execute(base + "WHERE status IN ('replied','sample','negotiation') ORDER BY last_contacted", ()).fetchall()
               if r["id"] not in taken and (days_from_today(r["last_contacted"]) or 0) >= 3]
    taken |= {r["id"] for r in waiting}
    cooling = [r for r in con.execute(base + "WHERE status='contacted' ORDER BY last_contacted", ()).fetchall()
               if r["id"] not in taken and (days_from_today(r["last_contacted"]) or 0) >= 14]
    fresh = con.execute(base + "WHERE status='new' AND id IN (SELECT company_id FROM contacts WHERE email_ok=1) ORDER BY score DESC LIMIT 10").fetchall()
    h += section("Geciken takipler", overdue, lambda r: f"{days_from_today(r['next_followup'])} gün gecikti", bad=True)
    h += section("Bugün yapılacaklar", today_rows, lambda r: "Takip günü bugün", empty_msg="Bugün için planlı takip yok." if not overdue else "")
    h += section("Cevap bekleyen sıcak müşteriler", waiting, lambda r: f"Son temas {ago(r['last_contacted'])} — dönüş yapılmalı", bad=True)
    h += section("Soğuyan müşteriler", cooling, lambda r: f"{days_from_today(r['last_contacted'])} gündür ses yok", bad=True)
    h += section("Yazılmayı bekleyen en iyi firmalar", fresh, lambda r: f"Puan {r['score']} · e-postası var", kind="new",
                 empty_msg='E-postası bulunan yeni firma yok. <a href="/tools">Firma bul</a> sayfasından başla.')
    if not (overdue or today_rows or waiting or cooling) and total:
        h += '<div class="card flat muted" style="text-align:center">Her şey güncel. Yeni firmalara yazarak devam edebilirsin.</div>'
    return "Bugün", h, "/"


# ------------------------------------------------------------------ Satış hattı
def page_pipeline(con, q):
    n = lambda sql, *p: con.execute(sql, p).fetchone()[0]  # noqa: E731
    total = n("SELECT COUNT(*) FROM companies")
    counts = {st: n("SELECT COUNT(*) FROM companies WHERE status=?", st) for st in STATUSES}
    vals = {st: n("SELECT IFNULL(SUM(value_usd),0) FROM companies WHERE status=?", st) for st in STATUSES}
    h = head("Satış hattı", "Kartı sürükleyip başka sütuna bırakarak durumunu değiştir.")
    if not total:
        return "Satış hattı", h + '<div class="card empty">Henüz firma yok. <a href="/tools">Firma bul</a> ile başla.</div>', "/pipeline"
    bar = "".join(f'<i style="width:{100 * counts[s] / total:.2f}%;background:{STATUS_COLOR[s]}" title="{STATUS_TR[s]}: {counts[s]}"></i>' for s in STATUSES if counts[s])
    lg = "".join(f'<span style="--c:{STATUS_COLOR[s]}">{STATUS_TR[s]} <b>{counts[s]}</b></span>' for s in STATUSES if counts[s])
    h += f'<div class="card" style="margin-bottom:18px"><div class="funnel">{bar}</div><div class="legend">{lg}</div></div><div class="kanban">'
    for st in ["new", "contacted", "replied", "sample", "negotiation", "won", "lost", "nurture"]:
        rows = con.execute("SELECT * FROM companies WHERE status=? ORDER BY starred DESC, score DESC LIMIT 25", (st,)).fetchall()
        h += (f'<div class="col" data-status="{st}" style="--c:{STATUS_COLOR[st]}"><h4>{STATUS_TR[st]}'
              f'<span>{counts[st]}{" · " + money(vals[st]) if vals[st] else ""}</span></h4>')
        for r in rows:
            d = days_from_today(r["last_contacted"])
            cold = d is not None and d >= 14 and st in OPEN_STATUSES
            h += (f'<a class="lead" draggable="true" data-id="{r["id"]}" href="/lead/{r["id"]}"><b>{"★ " if r["starred"] else ""}{esc(r["name"])}</b>'
                  f'<small>{esc(cname(r["country"]))} · {r["score"]} puan{" · " + money(r["value_usd"]) if r["value_usd"] else ""}</small>'
                  f'{f"<small class=cold>{d} gündür ses yok</small>" if cold else ""}</a>')
        if counts[st] > len(rows):
            h += f'<a href="/leads?status={st}">+{counts[st] - len(rows)} daha…</a>'
        h += "</div>"
    return "Satış hattı", h + "</div>", "/pipeline"


# ------------------------------------------------------------------ Firmalar
def build_qs(q, **over):
    d = {k: v[0] for k, v in q.items() if v and v[0] and k != "msg"}
    for k, v in over.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    return "?" + urllib.parse.urlencode(d) if d else "?"


def page_leads(con, q):
    g = lambda k: (q.get(k) or [""])[0].strip()  # noqa: E731
    w, p = ["1=1"], []
    if g("q"):
        w.append("(name LIKE ? OR domain LIKE ? OR city LIKE ? OR notes LIKE ?)")
        p += [f"%{g('q')}%"] * 4
    for col in ("status", "country", "segment"):
        if g(col):
            w.append(f"{col}=?")
            p.append(g(col).upper() if col == "country" else g(col))
    if g("min_score").isdigit():
        w.append("score>=?")
        p.append(int(g("min_score")))
    if g("with_email"):
        w.append("id IN (SELECT company_id FROM contacts WHERE email_ok=1)")
    if g("with_phone"):
        w.append("((phone IS NOT NULL AND phone<>'') OR id IN (SELECT company_id FROM contacts WHERE phone IS NOT NULL AND phone<>''))")
    if g("with_person"):
        w.append("id IN (SELECT company_id FROM contacts WHERE name IS NOT NULL AND name<>'')")
    if g("with_buyer"):
        w.append("id IN (SELECT company_id FROM contacts WHERE dept IN ('purchasing','export','sales'))")
    if g("starred"):
        w.append("starred=1")
    where = " AND ".join(w)
    sort = g("sort") if g("sort") in SORTS else "score"
    dr = "ASC" if g("dir") == "asc" else "DESC"
    expr, nulls_last = SORTS[sort]
    order = (f"({expr} IS NULL), " if nulls_last else "") + f"{expr} {dr}, score DESC, id DESC"
    total = con.execute(f"SELECT COUNT(*) FROM companies WHERE {where}", p).fetchone()[0]
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(int(g("page")) if g("page").isdigit() else 1, 1), pages)
    rows = con.execute(f"SELECT c.*, (SELECT 1 FROM contacts k WHERE k.company_id=c.id AND k.email_ok=1 LIMIT 1) has_email, "
                       f"(SELECT 1 FROM contacts k WHERE k.company_id=c.id AND k.name IS NOT NULL AND k.name<>'' LIMIT 1) has_person FROM companies c "
                       f"WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?", p + [PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
    ctry = [r[0] for r in con.execute("SELECT DISTINCT country FROM companies WHERE country IS NOT NULL")]
    ctry.sort(key=lambda c: tr_key(cname(c)))
    actions = (f'<a class="btn ghost" href="/import">{icon("upload")} Liste yükle</a><a class="btn ghost" href="/export.csv">{icon("download")} Firmalar</a><a class="btn ghost" href="/contacts.csv" title="Her satır bir kişi/e-posta: toplu posta için">{icon("download")} Kişiler</a>'
               f'<a class="btn" href="/add">{icon("plus")} Firma ekle</a>')
    h = head("Firmalar", f"{total} firma" + (" (filtreli)" if any(g(k) for k in ("q", "status", "country", "segment", "min_score", "with_email", "with_phone", "with_person", "with_buyer", "starred")) else ""), actions)
    h += f"""<form class="inline card" method="get" style="margin-bottom:14px"><div><label>Ara</label><input name="q" value="{esc(g('q'))}" placeholder="firma, site, şehir, not" style="width:200px"></div>
<div><label>Durum</label><select name="status">{opts([(s, STATUS_TR[s]) for s in STATUSES], g('status'), 'Hepsi')}</select></div>
<div><label>Segment</label><select name="segment">{opts(list(SEGMENT_TR.items()), g('segment'), 'Hepsi')}</select></div>
<div><label>Ülke</label><select name="country">{opts([(c, cname(c)) for c in ctry], g('country').upper(), 'Hepsi')}</select></div>
<div><label>Min. puan</label><input name="min_score" value="{esc(g('min_score'))}" style="width:64px"></div>
<div><label class="chip" style="margin:0"><input type="checkbox" name="with_email" value="1"{" checked" if g('with_email') else ""}> ✉ e-postalı</label></div>
<div><label class="chip" style="margin:0"><input type="checkbox" name="with_phone" value="1"{" checked" if g('with_phone') else ""}> ☎ telefonlu</label></div>
<div><label class="chip" style="margin:0"><input type="checkbox" name="with_person" value="1"{" checked" if g('with_person') else ""}> 👤 kişi adı var</label></div>
<div><label class="chip" style="margin:0"><input type="checkbox" name="with_buyer" value="1"{" checked" if g('with_buyer') else ""}> 🎯 satın alma/ihracat/satış</label></div>
<div><label class="chip" style="margin:0"><input type="checkbox" name="starred" value="1"{" checked" if g('starred') else ""}> ★ yıldızlı</label></div>
<input type="hidden" name="sort" value="{esc(sort)}"><input type="hidden" name="dir" value="{dr.lower()}">
<button>{icon('search')} Filtrele</button><a class="btn ghost" href="/leads">Temizle</a></form>"""
    if not rows:
        return "Firmalar", h + '<div class="card empty">Gösterilecek firma yok.</div>', "/leads"

    def th(label, key):
        on = sort == key
        nd = "asc" if on and dr == "DESC" else "desc"
        arrow = (" ↓" if dr == "DESC" else " ↑") if on else ""
        return f'<th><a class="{"on" if on else ""}" href="{build_qs(q, sort=key, dir=nd, page=None)}">{label}{arrow}</a></th>'
    back = "/leads" + build_qs(q)
    h += (f'<form method="post" action="/bulk" onsubmit="return bulkGo(this)"><input type="hidden" name="back" value="{esc(back)}">'
          f'<div class="tw"><table><tr><th><input type="checkbox" onclick="selAll(this)" title="Hepsini seç"></th><th></th>'
          f'{th("Puan", "score")}{th("Firma", "name")}{th("Ülke", "country")}{th("Segment", "segment")}{th("Durum", "status")}'
          f'{th("Veri", "data")}{th("Son temas", "last")}{th("Takip", "next")}{th("Değer", "value")}</tr>')
    td = leads.today()
    for r in rows:
        nf = r["next_followup"]
        late = nf and nf < td and r["status"] not in ("won", "lost")
        h += (f'<tr><td><input type="checkbox" class="rowchk" name="ids" value="{r["id"]}" onchange="updBulk()"></td><td>{star_btn(r["id"], r["starred"])}</td>'
              f'<td>{score_badge(r["score"])}</td><td><a class="name" href="/lead/{r["id"]}">{esc(r["name"])}</a>'
              f'<small>{esc(leads.get_domain(r["website"]) if r["website"] else "web sitesi yok")}'
              f'{" · ✉" if r["has_email"] else ""}{" · ☎" if r["phone"] else ""}{" · 👤" if r["has_person"] else ""}</small></td>'
              f'<td>{esc(cname(r["country"]))}</td><td>{SEGMENT_TR.get(r["segment"], r["segment"])}</td><td>{pill(r["status"])}</td>'
              f'<td title="Veri doluluğu: iletişim bilgisi ne kadar tamam"><div class="meter" style="width:54px"><i style="width:{r["data_score"] or 0}%"></i></div><small>%{r["data_score"] or 0}</small></td>'
              f'<td>{esc(ago(r["last_contacted"])) if r["last_contacted"] else "—"}</td>'
              f'<td class="{"late" if late else ""}">{esc(nf) if nf else "—"}</td><td>{money(r["value_usd"])}</td></tr>')
    h += "</table></div>"
    bulk_ops = ('<option value="">Toplu işlem seç…</option><option value="star">★ Yıldızla</option><option value="unstar">Yıldızı kaldır</option>' +
                "".join(f'<option value="status:{s}">Durum → {STATUS_TR[s]}</option>' for s in STATUSES) +
                "".join(f'<option value="segment:{k}">Segment → {v}</option>' for k, v in SEGMENT_TR.items()) +
                '<option value="delete">🗑 Sil</option>')
    h += (f'<div id="bulkbar"><b><span id="bulkn">0</span> firma seçili</b><select name="do">{bulk_ops}</select><button>Uygula</button></div></form>')
    if pages > 1:
        nums = [i for i in range(1, pages + 1) if i in (1, pages) or abs(i - page) <= 2]
        pg, last = "", 0
        for i in nums:
            if i - last > 1:
                pg += "<span>…</span>"
            pg += f'<span class="cur">{i}</span>' if i == page else f'<a href="{build_qs(q, page=str(i))}">{i}</a>'
            last = i
        h += f'<div class="pager">{pg}</div>'
    h += (f'<p class="muted sm" style="margin-top:18px">Veriler otomatik yedeklenir (günde bir, son 14 gün). '
          f'<a href="/backup.db">Şimdi yedek indir</a></p>')
    return "Firmalar", h, "/leads"


# ------------------------------------------------------------------ Firma detayı
def next_step(con, c):
    n = leads.email_count(con, c["id"])
    has_mail = con.execute("SELECT 1 FROM contacts WHERE company_id=? AND email_ok=1", (c["id"],)).fetchone()
    if c["status"] in ("won", "lost"):
        return None, None
    if c["status"] in ("replied", "sample", "negotiation"):
        return "Cevap/numune aşamasında: bu hafta bir görüşme ya da net teklif planla.", "cold"
    if n == 0:
        return ("İlk e-postayı gönder." if has_mail else "Önce bir e-posta adresi bul (Firma bul → E-posta ara) ya da kişi ekle."), "cold"
    if n < 3:
        return f"{n}. e-posta gönderildi. Sıradaki: {n + 1}. e-posta ({['', 'ilk takip', 'son hatırlatma'][n]}).", leads.NEXT_TEMPLATE[min(n, 2)]
    return "3 e-posta gitti, cevap yok. Arama dene ya da 'Beklemede'ye al.", "followup2"


def profile_card(con, c):
    """Taramadan toplanan firma bilgileri."""
    rows = []
    if c["business_type"] or c["cocoa_signal"] is not None:
        sig = c["cocoa_signal"] or 0
        rows.append(("Tip", f'{BTYPE_TR.get(c["business_type"] or "unknown", "Belirsiz")} <span class="tag" title="Sitede kakao/çikolata ile ilgili ifadelerin yoğunluğu">'
                            f'kakao ilgisi {sig}/100</span>'))
    if c["description"]:
        rows.append(("Hakkında", esc(c["description"])))
    if c["address"] or c["lat"]:
        q = f'{c["lat"]},{c["lon"]}' if c["lat"] and c["lon"] else urllib.parse.quote(f'{c["address"] or ""} {c["name"]}')
        rows.append(("Adres", f'{esc(c["address"] or "")} <a href="https://www.google.com/maps/search/?api=1&query={q}" target=_blank rel=noopener>haritada aç ↗</a>'))
    if c["phone"]:
        rows.append(("Telefon", f'<a href="tel:{esc(c["phone"])}">{esc(c["phone"])}</a>'))
    if c["whatsapp"]:
        rows.append(("WhatsApp", f'<a href="https://wa.me/{esc(c["whatsapp"].lstrip("+"))}" target=_blank rel=noopener>{esc(c["whatsapp"])} ↗</a>'))
    soc = [(l, c[k]) for l, k in (("LinkedIn", "linkedin"), ("Facebook", "facebook"), ("Instagram", "instagram"), ("X", "twitter"), ("YouTube", "youtube")) if c[k]]
    if soc:
        rows.append(("Sosyal medya", '<span class="soc">' + "".join(f'<a href="{esc(u)}" target=_blank rel=noopener>{l} ↗</a>' for l, u in soc) + "</span>"))
    facts = " · ".join(x for x in (f'{c["employees"]} çalışan' if c["employees"] else "", f'{c["founded"]}\'te kuruldu' if c["founded"] else "") if x)
    if facts:
        rows.append(("Firma", esc(facts)))
    if c["legal_id"]:
        rows.append(("Yasal", esc(c["legal_id"])))
    ds = c["data_score"] or 0
    last = f'Son tarama: {esc(c["enriched_at"])} · {c["enrich_pages"] or 0} sayfa' if c["enriched_at"] else "Henüz taranmadı"
    err = f'<br><span class="late sm">Siteye ulaşılamadı: {esc((c["enrich_error"] or "")[:120])}</span>' if c["enrich_error"] else ""
    scan = (f'<form class="pl" method="post" action="/lead/{c["id"]}/enrich"><button class="ghost sm" {"disabled" if not c["website"] else ""} '
            f'title="Sitedeki iletişim, impressum ve ekip sayfalarını tarar (10-20 sn)">{icon("search", 14)} Siteyi tara</button></form>')
    body = "<dl class='kv'>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>" if rows else '<p class="muted">Henüz toplanmış firma bilgisi yok.</p>'
    return (f'<div class="card" style="margin-bottom:16px"><div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px">'
            f'<h3 style="margin:0">Firma profili</h3>{scan}</div>{body}'
            f'<div style="margin-top:12px"><small class="muted">Veri doluluğu %{ds} · {last}</small><div class="meter"><i style="width:{ds}%"></i></div>{err}</div></div>')


def page_lead(con, cid, q):
    c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    if not c:
        return "Bulunamadı", head("Firma bulunamadı"), "/leads"
    advice, sugg_tpl = next_step(con, c)
    tdir = os.path.join(leads.HERE, "templates")
    langs = sorted({f.split("_")[0] for f in os.listdir(tdir)})
    tpls = sorted({f.split("_", 1)[1][:-4] for f in os.listdir(tdir)})
    lang = (q.get("lang") or ["de" if (c["country"] or "") in DE_COUNTRIES and "de" in langs else "en"])[0]
    tpl = (q.get("tpl") or [sugg_tpl or "cold"])[0]
    back = f"/lead/{cid}"
    sub = f'{esc(c["city"] or "")} {esc(cname(c["country"]))} · {SEGMENT_TR.get(c["segment"], "")} · kaynak: {esc(c["source"] or "-")}'
    if c["website"]:
        sub += f' · <a href="{esc(c["website"])}" target=_blank rel=noopener>{esc(leads.get_domain(c["website"]))}</a>'
    status_form = (f'<form class="pl" method="post" action="/lead/{cid}/status"><input type="hidden" name="reason" value="">'
                   f'<select name="status" onchange="if(this.value===\'lost\'){{var r=prompt(\'Kaybetme nedeni (isteğe bağlı):\');this.form.reason.value=r||\'\'}}this.form.submit()">'
                   f'{opts([(s, STATUS_TR[s]) for s in STATUSES], c["status"])}</select></form>')
    del_form = (f'<form class="pl" method="post" action="/lead/{cid}/delete" onsubmit="return confirm(\'Bu firma kişileri ve geçmişiyle birlikte silinecek '
                f've sonraki taramalarda tekrar eklenmeyecek. Silinsin mi?\')"><button class="danger">{icon("trash")} Sil</button></form>')
    h = head(f'{star_btn(cid, c["starred"])} {esc(c["name"])} {score_badge(c["score"])}', sub, status_form + del_form)
    h += "<div class='grid two'><div>"
    # sonraki adım + hızlı işlemler
    nf = c["next_followup"]
    late = nf and nf < leads.today() and c["status"] not in ("won", "lost")
    h += '<div class="card" style="margin-bottom:16px">'
    if advice:
        h += f'<div class="next"><b>Sıradaki adım:</b> {esc(advice)}</div>'
    h += ('<div class="actions">' + quick_form(cid, "sent", "E-posta gönderdim", "mail", back, "") + quick_form(cid, "called", "Aradım", "phone", back, "ghost")
          + quick_form(cid, "replied", "Cevap geldi", "reply", back, "ghost") + quick_form(cid, "sample", "Numune gönderdim", "box", back, "ghost")
          + quick_form(cid, "snooze", "3 gün ertele", "clock", back, "ghost") + "</div>")
    h += (f'<p class="muted sm" style="margin:12px 0 0">Son temas: <b>{esc(ago(c["last_contacted"]))}</b> · Sonraki takip: '
          f'<b class="{"late" if late else ""}">{esc(nf or "planlı değil")}</b> · Gönderilen e-posta: <b>{leads.email_count(con, cid)}</b></p></div>')
    # firma profili (taramadan gelen veriler)
    h += profile_card(con, c)
    # kişiler
    h += "<div class='card' style='margin-bottom:16px'><h3>Kişiler ve iletişim</h3>"
    ks = sorted(con.execute("SELECT * FROM contacts WHERE company_id=?", (cid,)).fetchall(),
                key=lambda k: (k["kind"] == "guess", leads.crawler.DEPT_PRIORITY.get(k["dept"] or "other", 12), -(k["confidence"] or 0), k["id"]))
    if ks:
        h += "<div class='tw'><table><tr><th>Ad / görev</th><th>Departman</th><th>E-posta</th><th>Telefon</th><th></th></tr>"
        for k in ks:
            mark = ('<span title="Alan adı e-posta alabiliyor (MX kaydı var)" style="color:var(--ok)">✔</span>' if k["email_ok"]
                    else ('<span title="Alan adı e-posta almıyor olabilir" style="color:var(--bad)">✖</span>' if k["email"] else ""))
            guess = '<span class="tag warn" title="Sitedeki e-posta kalıbından tahmin edildi; göndermeden önce doğrulayın">tahmin</span>' if k["kind"] == "guess" else ""
            src = f' <a href="{esc(k["source_url"])}" target=_blank rel=noopener title="Bulunduğu sayfa" class="muted">↗</a>' if k["source_url"] else ""
            who = f'<b>{esc(k["name"])}</b><small>{esc(k["role"] or "")}</small>' if k["name"] else '<span class="muted">—</span>'
            em = f'<a href="mailto:{esc(k["email"])}">{esc(k["email"])}</a> {mark}{guess}{src}' if k["email"] else '<span class="muted">—</span>'
            ph = f'<a href="tel:{esc(k["phone"])}">{esc(k["phone"])}</a>' if k["phone"] else '<span class="muted">—</span>'
            h += (f'<tr><td>{who}</td><td>{DEPT_TR.get(k["dept"] or "", "—") if k["dept"] else "—"}</td><td>{em}</td><td>{ph}</td>'
                  f'<td><form class="pl" method="post" action="/contact/{k["id"]}/delete" onsubmit="return confirm(\'Kişi silinsin mi?\')">'
                  f'<input type="hidden" name="back" value="{back}"><button class="danger sm" title="Sil">{icon("x", 13)}</button></form></td></tr>')
        h += "</table></div>"
    else:
        h += '<p class="muted">Henüz kişi yok. Sağ üstteki "Siteyi tara" ile bulmayı deneyebilirsin.</p>'
    h += f"""<form class="inline" method="post" action="/lead/{cid}/contact" style="margin-top:12px"><input name="name" placeholder="Ad Soyad"><input name="role" placeholder="Görev">
<input name="email" placeholder="e-posta"><input name="phone" placeholder="telefon"><button class="ghost">{icon('plus', 14)} Ekle</button></form></div>"""
    # geçmiş
    h += f"""<div class="card"><h3>Geçmiş</h3><form class="inline" method="post" action="/lead/{cid}/log"><div><label>Tür</label><select name="kind">{opts(list(KIND_TR.items()), "note")}</select></div>
<div style="flex:1;min-width:200px"><label>Not</label><input name="summary" required style="width:100%" placeholder="Ne konuşuldu / ne gönderildi?"></div>
<div><label>Takip (gün)</label><input name="followup" placeholder="oto" style="width:64px"></div><button class="ghost">Kaydet</button></form><ul class="tl">"""
    for x in con.execute("SELECT * FROM activities WHERE company_id=? ORDER BY ts DESC, id DESC", (cid,)):
        h += f'<li><b>{KIND_TR.get(x["kind"], x["kind"])}</b> <span class="muted sm">{esc(x["ts"][:16])}</span><br>{esc(x["summary"])}</li>'
    h += "</ul></div></div><div>"
    # e-posta taslağı
    try:
        to, text = leads.render_email(con, cid, lang, tpl)
        lines = text.split("\n")
        subject = lines[0].split(":", 1)[1].strip() if ":" in lines[0] else ""
        body = "\n".join(lines[1:]).strip()
        mailto = f"mailto:{to or ''}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
        mail = (f'<p class="muted sm">Alıcı: <b>{esc(to or "geçerli e-posta yok")}</b></p><pre class="mail" id="mail">{esc(text)}</pre>'
                f'<div class="actions"><a class="btn alt" href="{esc(mailto)}">{icon("mail")} Mail uygulamasında aç</a>'
                f'<button type="button" class="ghost" onclick="navigator.clipboard.writeText(document.getElementById(\'mail\').innerText);this.textContent=\'Kopyalandı ✔\'">Kopyala</button></div>'
                f'<p class="muted sm" style="margin-top:10px">Gönderdikten sonra soldan <b>"E-posta gönderdim"</b>e bas; takip tarihi otomatik kurulur.</p>')
    except ValueError as e:
        mail = f'<p class="muted">{esc(str(e))}</p>'
    h += f"""<div class="card" style="margin-bottom:16px"><h3>E-posta taslağı</h3><form class="inline" method="get" style="margin-bottom:12px">
<select name="lang">{opts([(x, x.upper()) for x in langs], lang)}</select><select name="tpl">{opts([(x, x) for x in tpls], tpl)}</select><button class="ghost">Göster</button></form>{mail}</div>"""
    # düzenle
    h += f"""<div class="card"><h3>Firma bilgileri</h3><form method="post" action="/lead/{cid}/update" class="grid" style="gap:10px">
<div><label>Firma adı</label><input name="name" value="{esc(c['name'])}" required style="width:100%"></div>
<div><label>Web sitesi</label><input name="website" value="{esc(c['website'] or '')}" style="width:100%"></div>
<div class="row2"><div><label>Ülke</label><select name="country" style="width:100%">{opts([(k, v[0]) for k, v in sorted(COUNTRIES.items(), key=lambda x: tr_key(x[1][0]))], c['country'], '—')}</select></div>
<div><label>Şehir</label><input name="city" value="{esc(c['city'] or '')}" style="width:100%"></div></div>
<div><label>Segment</label><select name="segment" style="width:100%">{opts(list(SEGMENT_TR.items()), c['segment'])}</select></div>
<div class="row2"><div><label>Fırsat değeri ($)</label><input name="value_usd" value="{esc(f"{c['value_usd']:.0f}" if c['value_usd'] else '')}" style="width:100%" placeholder="örn. 25000"></div>
<div><label>İlgilendiği ürün</label><input name="product" value="{esc(c['product'] or '')}" style="width:100%" placeholder="kakao tozu, 10 ton/ay"></div></div>
{f'<div><label>Kaybetme nedeni</label><input name="lost_reason" value="{esc(c["lost_reason"] or "")}" style="width:100%"></div>' if c['status'] == 'lost' else ''}
<div><label>Notlar</label><textarea name="notes" rows="4">{esc(c['notes'] or '')}</textarea></div>
<div class="actions"><button>Kaydet</button></div></form>
<form method="post" action="/suppress" onsubmit="return confirm('Bu firmaya bir daha yazılmayacak. Emin misiniz?')" style="margin-top:12px">
<input type="hidden" name="value" value="{esc(c['domain'] or '')}"><input type="hidden" name="back" value="{back}">
<button class="ghost sm" {"disabled" if not c['domain'] else ""}>Abonelikten çıktı / bir daha yazma</button></form></div></div></div>"""
    return c["name"], h, "/leads"


def page_add(con, q):
    return "Firma ekle", head("Firma ekle", "Tek bir firmayı elle kaydet.") + f"""<form class="card" method="post" action="/add" style="max-width:820px"><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(230px,1fr))">
<div><label>Firma adı *</label><input name="name" required style="width:100%"></div><div><label>Web sitesi</label><input name="website" style="width:100%" placeholder="firma.com"></div>
<div><label>Ülke</label><select name="country" style="width:100%">{opts([(k, v[0]) for k, v in sorted(COUNTRIES.items(), key=lambda x: tr_key(x[1][0]))], None, 'Seç…')}</select></div>
<div><label>Şehir</label><input name="city" style="width:100%"></div>
<div><label>Segment</label><select name="segment" style="width:100%">{opts(list(SEGMENT_TR.items()))}</select></div>
<div><label>E-posta</label><input name="email" style="width:100%"></div><div><label>Telefon</label><input name="phone" style="width:100%"></div>
<div><label>Kaynak</label><input name="source" value="manuel" style="width:100%"></div></div><br><label>Notlar</label><textarea name="notes" rows="3"></textarea><br><br><button>{icon('plus')} Ekle</button></form>""", "/leads"


def page_import(con, q):
    return "İçe aktar", head("Liste yükle", "Fuar katılımcı listesi, ImportYeti sonucu ya da Excel'deki bir listeyi toplu ekle.") + f"""<form class="card" method="post" action="/import" style="max-width:820px">
<p class="muted">Excel'de <b>"CSV olarak kaydet"</b> yapıp buraya yükle. Sütun adları: <code>name, country, website, segment, city, email, phone, notes</code> (sadece <b>name</b> zorunlu).
Aynı firma ikinci kez eklenmez; daha önce sildiklerin de geri gelmez.</p>
<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr))"><div><label>Kaynak adı (nereden aldın?)</label><input name="source" value="Fuar-2026" required style="width:100%"></div>
<div><label>CSV dosyası seç</label><input type="file" accept=".csv,.txt" onchange="const f=this.files[0];if(f)f.text().then(t=>document.getElementById('csv').value=t)"></div></div><br>
<label>veya buraya yapıştır</label><textarea id="csv" name="csv" rows="12" required></textarea><br><br><button>{icon('upload')} İçe aktar</button></form>""", "/leads"


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
    h += (f'<form class="inline card" method="get" style="margin-bottom:14px"><div><label>Ürün</label><select name="hs">{sel}</select></div><button class="ghost">Göster</button>'
          f'<span class="muted sm" style="margin-left:auto;max-width:520px">Küçük Türkiye payı = rakiplerin hâkim olduğu ama girilebilecek bir pazar demektir; '
          f'çoğu zaman fiyat ve lojistikte rekabet gerektirir.</span></form>')
    if note:
        h += f'<div class="flash">{esc(note)}</div>'
    if not rows:
        return "Pazarlar", h + '<div class="card empty">Henüz pazar verisi yok. <a href="/tools">Pazar verisini çek</a></div>', "/markets"
    top = max(r["total"] for r in rows) or 1
    h += '<form method="post" action="/job/find"><div class="tw"><table><tr><th></th><th>#</th><th>Ülke</th><th>Yıllık ithalat</th><th></th><th>Türkiye payı</th><th>Sistemdeki firma</th><th></th></tr>'
    for i, r in enumerate(rows, 1):
        cc = ISO3_TO_ISO2.get(r["iso"])
        cnt = con.execute("SELECT COUNT(*) FROM companies WHERE country=?", (cc,)).fetchone()[0] if cc else 0
        share = 100 * r["from_tr"] / r["total"] if r["total"] else 0
        action = (f'<button class="sm alt" name="country" value="{cc}" title="Bu ülkedeki işletmeleri otomatik bul">{icon("search", 13)} Firma bul</button>' if cc
                  else '<span class="muted" title="Bu ülke için otomatik arama tanımlı değil">–</span>')
        h += (f'<tr><td>{f"<input type=checkbox name=c value={cc}>" if cc else ""}</td><td>{i}</td><td><b>{esc(cname(cc) if cc else r["importer"])}</b></td>'
              f'<td>{fmt_money(r["total"])}</td><td style="width:22%"><div class="bar"><i style="width:{100 * r["total"] / top:.0f}%"></i></div></td>'
              f'<td>%{share:.1f}</td><td>{f"<a href=/leads?country={cc}><b>{cnt}</b></a>" if cnt else "0"}</td><td>{action}</td></tr>')
    h += f'</table></div><p style="margin-top:14px"><button>{icon("zap")} Seçili ülkelerde firma bul</button> <span class="muted sm">Kutucukları işaretleyip birden fazla ülkeyi tek seferde tarayabilirsin.</span></p></form>'
    return "Pazarlar", h, "/markets"


def coverage(con):
    """Firmaların yüzde kaçında hangi veri var?"""
    n = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    tot = n("SELECT COUNT(*) FROM companies")
    if not tot:
        return tot, []
    items = [("Web sitesi", n("SELECT COUNT(*) FROM companies WHERE website IS NOT NULL AND website<>''")),
             ("E-posta", n("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE email_ok=1")),
             ("Telefon", n("SELECT COUNT(*) FROM companies c WHERE (phone IS NOT NULL AND phone<>'') OR EXISTS(SELECT 1 FROM contacts k WHERE k.company_id=c.id AND k.phone IS NOT NULL)")),
             ("Kişi adı", n("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE name IS NOT NULL AND name<>''")),
             ("Satın alma/ihracat/satış", n("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE dept IN ('purchasing','export','sales')")),
             ("Adres", n("SELECT COUNT(*) FROM companies WHERE address IS NOT NULL AND address<>''")),
             ("Sosyal medya", n("SELECT COUNT(*) FROM companies WHERE linkedin IS NOT NULL OR facebook IS NOT NULL OR instagram IS NOT NULL OR twitter IS NOT NULL")),
             ("Taranmış site", n("SELECT COUNT(*) FROM companies WHERE enrich_v>=2 AND enrich_error IS NULL"))]
    return tot, items


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
    tot, cov = coverage(con)
    pending = con.execute("SELECT COUNT(*) FROM companies WHERE website IS NOT NULL AND website<>'' AND IFNULL(enrich_v,0)<2").fetchone()[0]
    cov_html = ""
    if tot:
        cov_html = (f'<div class="card" style="margin-bottom:16px"><h3>Veri durumu <span class="muted sm">({tot} firma)</span></h3><div class="cover">' +
                    "".join(f'<div><b>%{100 * v // tot}</b><span>{k} <small>({v})</small></span><div class="meter"><i style="width:{100 * v // tot}%"></i></div></div>' for k, v in cov) +
                    "</div></div>")
    dis = "disabled" if JOB["running"] else ""
    h = head("Firma bul", "Önce firmaları bul, sonra sitelerini tarayıp iletişim bilgilerini topla.") + status + cov_html
    h += f"""<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">
<form class="card tool" method="post" action="/job/find" style="grid-column:1/-1"><span class="no">1 · FİRMA BUL</span><h3>Haritadan otomatik firma bul + derin tarama</h3>
<p class="muted" style="margin:0">Seçtiğin ülkelerdeki çikolatacı, şekerleme, dondurma ve gıda üreticilerini <b>harita verisinden</b> bulur, ardından sitelerine girip
<b>e-posta, telefon, yönetici/satın alma kişileri, sosyal medya, adres ve vergi/sicil no</b> toplar, <b>puanlar</b>. Silinmiş firmalar tekrar eklenmez.
Ülke başına ortalama 3–8 dakika sürer; ilk denemede 2–3 ülke seç.</p>
{country_chips(DEFAULT_FIND[:3])}<div><button {dis}>{icon('zap')} Seçili ülkelerde bul ve tara</button></div></form>
<form class="card tool" method="post" action="/job/wikidata"><span class="no">1 · FİRMA BUL (BÜYÜK FİRMALAR)</span><h3>Bilinen firmalar (Wikidata)</h3>
<p class="muted" style="margin:0">Açık veri tabanından çikolata, şekerleme, kakao, bisküvi ve fırın sektöründeki <b>bilinen şirketleri</b> web sitesi, çalışan sayısı, kuruluş yılı ve sosyal hesaplarıyla getirir. Büyük/orta alıcıları bulmak için iyi.</p>
<div><label>Ülkeler (ISO, ops.)</label><input name="country" placeholder="DE,IT,TR — boş = hepsi" style="width:190px"> <button class="ghost" {dis}>Büyük firmaları çek</button></div></form>
<form class="card tool" method="post" action="/job/enrich"><span class="no">2 · DERİN TARAMA</span><h3>Sitelerden iletişim bilgisi topla</h3>
<p class="muted" style="margin:0">Henüz taranmamış <b>{pending}</b> firmanın sitesinde iletişim, impressum, ekip ve hakkında sayfalarını gezer; e-posta (departman: satın alma, ihracat, satış…), telefon, WhatsApp,
yönetici adları, sosyal medya, adres, vergi no ve kakao ilgisini kaydeder. robots.txt'e uyar.</p>
<div class="actions"><div><label>Kaç firma</label><input name="limit" value="150" style="width:80px"></div>
<div><label>Paralel</label><select name="workers"><option>4</option><option selected>6</option><option>8</option><option>12</option></select></div>
<div><label class="chip" style="margin:0"><input type="checkbox" name="force" value="1"> taranmışları yeniden tara</label></div>
<button {dis}>{icon('search')} Taramayı başlat</button></div></form>
<form class="card tool" method="post" action="/job/comtrade"><span class="no">İSTEĞE BAĞLI · BİR KEZ</span><h3>Pazar verisi</h3>
<p class="muted" style="margin:0">Hangi ülkeler ne kadar kakao ithal ediyor? Resmi gümrük istatistiklerini çeker. {"✔ Veri yüklü." if has_market else "Henüz yüklenmedi."} Birkaç dakika sürer, yarıda kalırsa tekrar bas.</p>
<div><label>Yıl</label><input name="year" value="{leads.config().get('comtrade_year', 2023)}" style="width:90px"> <button class="ghost" {dis}>Pazar verisini çek</button></div></form>
<form class="card tool" method="post" action="/job/score"><span class="no">GEREKTİĞİNDE</span><h3>Puanları yenile</h3>
<p class="muted" style="margin:0">Elle firma ekledikten ya da liste yükledikten sonra puanların güncellenmesi için.</p><div><button class="ghost" {dis}>Puanla</button></div></form></div>
<details style="margin-top:18px"><summary>Neyi nereden alıyoruz?</summary><p class="muted">Firmalar OpenStreetMap ve Wikidata'dan (açık veri), pazar istatistikleri UN Comtrade'den, iletişim bilgileri firmaların <b>kendi sitelerindeki herkese açık</b>
sayfalardan (iletişim, impressum, ekip) gelir. Siteler robots.txt'e uygun ve yavaş taranır; LinkedIn gibi giriş gerektiren ya da taramayı yasaklayan platformlardan veri çekilmez.
Yönetici adları Almanya/Avusturya/İsviçre'de yasal zorunluluk olan Impressum sayfalarından gelir. <b>Tahmin</b> işaretli e-postalar sitedeki ad.soyad kalıbından türetilir; göndermeden önce doğrulayın.
Büyük fabrikalar için fuar listelerini <a href="/import">Liste yükle</a> sayfasından ekleyebilirsin.</p></details>"""
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
        print("\n--- Derin tarama: yeni firmaların siteleri (e-posta, telefon, kişi, sosyal medya) ---", flush=True)
        leads.cmd_enrich(argparse.Namespace(limit=200, workers=8, pages=8, force=False))
    leads.cmd_score(argparse.Namespace())
    a_firms, a_mail = stats()
    JOB["summary"] = f"{a_firms - b_firms} yeni firma bulundu, {a_mail - b_mail} firmaya e-posta eklendi; siteler tarandı ve hepsi puanlandı."


# ------------------------------------------------------------------ sunucu
QUICK = {
    "sent": ("email", "E-posta gönderildi", None), "called": ("call", "Arandı", None), "sample": ("sample", "Numune gönderildi", "sample"),
    "replied": ("note", "Müşteriden yanıt geldi", "replied"),
}


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
        if not to.startswith("/") or to.startswith("//"):  # açık yönlendirme koruması
            to = "/"
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
            if u.path == "/contacts.csv":
                return self._export(contacts=True)
            if u.path == "/backup.db":
                p = leads.backup_db(force=True)
                with open(p, "rb") as f:
                    return self._send(200, f.read(), "application/octet-stream", {"Content-Disposition": 'attachment; filename="imesta-leads-yedek.db"'})
            routes = {"/": page_today, "/pipeline": page_pipeline, "/leads": page_leads, "/add": page_add, "/import": page_import,
                      "/markets": page_markets, "/tools": page_tools}
            if u.path in routes:
                title, body, act = routes[u.path](con, q)
            elif u.path.startswith("/lead/") and u.path[6:].isdigit():
                title, body, act = page_lead(con, int(u.path[6:]), q)
            else:
                return self._send(404, layout("404", head("Sayfa yok")))
            self._send(200, layout(title, body, act, flash, due_count(con)))
        finally:
            con.close()

    def _export(self, contacts=False):
        with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False) as t:
            path = t.name
        try:
            (leads.cmd_export_contacts if contacts else leads.cmd_export)(argparse.Namespace(file=path))
            with open(path, "rb") as f:
                data = f.read()
        finally:
            os.unlink(path)
        self._send(200, data, "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="imesta-{"kisiler" if contacts else "firmalar"}.csv"'})

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
            self._post(con, path, f, multi)
        finally:
            con.close()

    def _post(self, con, path, f, multi):
        if path == "/add":
            cid, new = leads.upsert_company(con, f.get("name"), f.get("country"), f.get("city"), f.get("website"),
                                            f.get("segment", "other"), f.get("source") or "manuel", f.get("notes"), f.get("email"), f.get("phone"), manual=True)
            con.commit()
            return self._redirect(f"/lead/{cid}" if cid else "/add", "Eklendi" if new else "Bu firma zaten kayıtlıydı")
        if path == "/import":
            new, dup = leads.import_csv_text(con, f.get("csv", ""), f.get("source") or "csv")
            return self._redirect("/leads", f"{new} yeni firma eklendi, {dup} tekrar/silinmiş atlandı. Puanlamak için Firma bul → Puanla.")
        if path == "/suppress":
            if f.get("value"):
                leads.cmd_suppress(argparse.Namespace(value=f["value"]))
            return self._redirect(f.get("back") or "/", "Engelleme listesine eklendi")
        if path == "/bulk":
            ids = [int(i) for i in multi.get("ids", []) if i.isdigit()]
            op, back = f.get("do", ""), f.get("back") or "/leads"
            if not ids or not op:
                return self._redirect(back, "Hiçbir şey seçilmedi")
            if op == "delete":
                leads.backup_db(force=True)  # toplu silmeden önce güvenlik yedeği
                return self._redirect(back, f"{leads.delete_companies(con, ids)} firma silindi (yedek alındı)")
            q = ",".join("?" * len(ids))
            if op in ("star", "unstar"):
                con.execute(f"UPDATE companies SET starred=? WHERE id IN ({q})", [1 if op == "star" else 0] + ids)
            elif op.startswith("status:") and op[7:] in STATUSES:
                for i in ids:
                    leads.do_log(con, i, "note", f"Durum değiştirildi: {STATUS_TR[op[7:]]}", status=op[7:])
            elif op.startswith("segment:") and op[8:] in SEGMENTS:
                con.execute(f"UPDATE companies SET segment=? WHERE id IN ({q})", [op[8:]] + ids)
            else:
                return self._redirect(back, "Geçersiz işlem")
            con.commit()
            return self._redirect(back, f"{len(ids)} firma güncellendi")
        if path.startswith("/contact/") and path.endswith("/delete"):
            kid = path.split("/")[2]
            if kid.isdigit():
                con.execute("DELETE FROM contacts WHERE id=?", (int(kid),))
                con.commit()
            return self._redirect(f.get("back") or "/", "Kişi silindi")
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
                    "enrich": ("Siteler taranıyor", lambda: (leads.cmd_enrich(argparse.Namespace(
                        limit=int(f.get("limit") or 150), workers=int(f.get("workers") or 6), pages=8, force=bool(f.get("force")))), leads.cmd_score(argparse.Namespace()))),
                    "wikidata": ("Wikidata'dan firmalar çekiliyor", lambda: (leads.cmd_harvest_wikidata(argparse.Namespace(country=f.get("country", ""))),
                                                                              leads.cmd_score(argparse.Namespace()))),
                    "score": ("Puanlanıyor", lambda: leads.cmd_score(argparse.Namespace()))}
            if kind not in jobs:
                return self._send(404, "yok")
            ok = run_job(*jobs[kind])
            return self._redirect("/tools", "İş başlatıldı" if ok else "Başka bir iş çalışıyor")
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "lead" and parts[1].isdigit():
            cid, act = int(parts[1]), parts[2]
            here = f"/lead/{cid}"
            if not con.execute("SELECT 1 FROM companies WHERE id=?", (cid,)).fetchone():
                return self._redirect("/leads", "Firma bulunamadı")
            if act == "quick":
                back, do = f.get("back") or here, f.get("do")
                if do == "snooze":
                    return self._redirect(back, f"Takip {leads.snooze(con, cid, 3)} tarihine ertelendi")
                if do in QUICK:
                    kind, summary, status = QUICK[do]
                    nxt = leads.do_log(con, cid, kind, summary, status, 2 if do == "replied" else None)
                    return self._redirect(back, f"Kaydedildi · sonraki takip: {nxt or '—'}")
                return self._redirect(back)
            if act == "log":
                fu = f.get("followup")
                try:
                    leads.do_log(con, cid, f.get("kind", "note"), f.get("summary", ""), None, int(fu) if fu and fu.isdigit() else None)
                except ValueError as e:
                    return self._redirect(here, str(e))
                return self._redirect(here, "Kaydedildi")
            if act == "status":
                st = f.get("status")
                if st not in STATUSES:
                    return self._send(400, "Geçersiz durum")
                leads.do_log(con, cid, "note", f"Durum: {STATUS_TR[st]}" + (f" – {f['reason']}" if st == "lost" and f.get("reason") else ""), status=st)
                if st == "lost" and f.get("reason"):
                    con.execute("UPDATE companies SET lost_reason=? WHERE id=?", (f["reason"], cid))
                    con.commit()
                return self._redirect(here, f"Durum: {STATUS_TR[st]}")
            if act == "enrich":
                row = con.execute("SELECT website FROM companies WHERE id=?", (cid,)).fetchone()
                if not row["website"]:
                    return self._redirect(here, "Önce web sitesi ekleyin")
                res = leads.crawler.crawl_site(row["website"], max_pages=10, delay=0.8)
                st = leads.apply_enrichment(con, cid, res)
                leads.score_company(con, con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone(), leads.market_ranks(con))
                con.commit()
                if not res["ok"]:
                    return self._redirect(here, "Siteye ulaşılamadı: " + (res["errors"] or ["?"])[0][:100])
                return self._redirect(here, f"Tarandı: {st['emails']} e-posta, {st['phones']} telefon, {st['people']} kişi, {st['socials']} sosyal hesap")
            if act == "star":
                con.execute("UPDATE companies SET starred=1-IFNULL(starred,0) WHERE id=?", (cid,))
                con.commit()
                return self._send(204, b"")
            if act == "delete":
                leads.backup_db(force=True)
                leads.delete_companies(con, [cid])
                return self._redirect("/leads", "Firma silindi (yedek alındı)")
            if act == "contact":
                leads.add_contact(con, cid, f.get("name") or None, f.get("role") or None, f.get("email") or None, f.get("phone") or None, None, "manuel")
                con.commit()
                return self._redirect(here, "Kişi eklendi")
            if act == "update":
                if not f.get("name"):
                    return self._redirect(here, "Firma adı boş olamaz")
                website = leads.norm_url(f.get("website"))
                seg = f.get("segment") if f.get("segment") in SEGMENTS else "other"
                cc = f.get("country", "").upper() or None
                try:
                    con.execute("UPDATE companies SET name=?, website=?, domain=?, country=?, city=?, segment=?, value_usd=?, product=?, "
                                "lost_reason=COALESCE(?, lost_reason), notes=? WHERE id=?",
                                (f["name"], website or None, leads.get_domain(website) or None, cc if cc in COUNTRIES else None, f.get("city") or None, seg,
                                 num(f.get("value_usd")), f.get("product") or None, f.get("lost_reason"), f.get("notes"), cid))
                    con.commit()
                except sqlite3.IntegrityError:
                    return self._redirect(here, "Bu web sitesi başka bir firmada kayıtlı")
                return self._redirect(here, "Güncellendi")
        self._send(404, "yok")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1", help="Başka cihazlardan erişim için 0.0.0.0 (WEB_PASSWORD ayarlayın!)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true", help="tarayıcıyı otomatik aç")
    a = p.parse_args()
    if a.host != "127.0.0.1" and not os.environ.get("WEB_PASSWORD"):
        raise SystemExit("Güvenlik: localhost dışına açmak için WEB_PASSWORD ortam değişkenini ayarlayın.")
    leads.db().close()
    try:
        leads.backup_db()  # günlük otomatik yedek
    except Exception as e:
        print("Yedek alınamadı:", e)
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
