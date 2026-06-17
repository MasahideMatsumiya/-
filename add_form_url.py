#!/usr/bin/env python3
import csv, os, re
from urllib.parse import urlparse
BASE="/home/user/-"
src=os.path.join(BASE,"/tmp/sales_backup.csv")
rows=list(csv.DictReader(open(src,encoding="utf-8")))

EXTERNAL=["petlife.asia","salon-de-one.com","yoyaku-beauty.jp","reserva.be","coubic","book-online",
          "lit.link","web-story.biz","shop-pro.jp","power-k.jp","pos-s.net","forms.gle","tol-app",
          "EPARK","E-PARK","Airリザーブ"]

# explicit domain (optionally with path) inside the note
dom_re=re.compile(r'([A-Za-z0-9][A-Za-z0-9\-]*\.)+(?:com|co\.jp|jp|net|biz|info|dog|pet|style|me|xyz|in|org)(?:/[A-Za-z0-9_\-./]*)?')
path_re=re.compile(r'/[A-Za-z0-9_\-./]+')
file_re=re.compile(r'[A-Za-z0-9_\-]+\.(?:html?|php|aspx|cgi)')
CKEY=("contact","inquiry","inquery","form","toiawase","otoiawase","ask","serviceform",
      "inqfm","reserve","reservation","blank","information","pageask","pages/")

def root(url):
    p=urlparse(url); return f"{p.scheme}://{p.netloc}"
def basedir(url):
    p=urlparse(url); path=p.path
    if not path.endswith("/"): path=path.rsplit("/",1)[0]+"/"
    return f"{p.scheme}://{p.netloc}{path}"

def near404(note,end): return "404" in note[end:end+6]

def extract(note,url):
    host=urlparse(url).netloc.lower()
    # 1) explicit external/other-domain URL with contact-ish path
    for m in dom_re.finditer(note):
        tok=m.group(0).rstrip('.')
        if near404(note,m.end()): continue
        if "/" in tok and any(k in tok.lower() for k in CKEY) and not tok.lower().startswith(host):
            return "https://"+tok, "確定(別ドメイン明記)"
    # 2) same-site absolute path
    paths=[]
    for m in path_re.finditer(note):
        if near404(note,m.end()): continue
        paths.append(m.group(0).rstrip('.'))
    pref=[p for p in paths if any(k in p.lower() for k in CKEY)]
    if pref: return root(url)+pref[0], "確定(サイト内パス)"
    # 3) filename (join with site's base directory)
    files=[]
    for m in file_re.finditer(note):
        if near404(note,m.end()): continue
        files.append(m.group(0))
    fpref=[f for f in files if any(k in f.lower() for k in CKEY)] or files
    if fpref: return basedir(url)+fpref[0], "確定(サイト内ページ)"
    # 4) any same-site path even if not contact-ish
    if paths: return root(url)+paths[0], "推定(サイト内パス)"
    return "", ""

for r in rows:
    note=r["備考"]; url=r["公式サイトURL"]
    if r["連絡手段"]=="メール":
        r["フォームURL"]=""; r["フォーム備考"]="（フォームなし／メールのみ）"; continue
    furl,conf=extract(note,url)
    ext=[e for e in EXTERNAL if e.lower() in note.lower()]
    if furl:
        r["フォームURL"]=furl
        r["フォーム備考"]=conf+(f"／予約は外部:{ext[0]}" if ext else "")
    elif ext:
        r["フォームURL"]=url; r["フォーム備考"]=f"外部予約システム({ext[0]})経由・トップから遷移"
    else:
        r["フォームURL"]=url; r["フォーム備考"]="トップページ上のフォーム/リンクから"

cols=["営業No","連絡手段","メールアドレス","フォームURL","エリア","店舗名","業種","公式サイトURL","電話","フォーム備考","元リスト","元No","備考"]
out=os.path.join(BASE,"buddybuddy_petshop_contactable_sales.csv")
with open(out,"w",encoding="utf-8",newline="") as fp:
    w=csv.DictWriter(fp,fieldnames=cols); w.writeheader()
    for r in rows: w.writerow({c:r.get(c,"") for c in cols})

res=[r for r in rows if r["連絡手段"]!="メール"]
conf=sum(1 for r in res if r["フォーム備考"].startswith("確定"))
est=sum(1 for r in res if r["フォーム備考"].startswith("推定"))
top=len(res)-conf-est
print(f"フォーム保有 {len(res)}件 | 直URL確定 {conf} / 推定 {est} / 外部・トップ {top}")
print("Joli:", [r["フォームURL"] for r in rows if "Joli" in r["店舗名"]])
print("HAMA:", [(r["フォームURL"],r["フォーム備考"]) for r in rows if "HAMA" in r["店舗名"]])
print("ビースパ:", [r["フォームURL"] for r in rows if "ビースパ" in r["店舗名"]])
