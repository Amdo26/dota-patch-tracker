"""Dota 2 Patch Tracker builder.
Reads Valve's official patch data and writes dota2-patch-tracker.html next to this script.
Usage:  python update_patches.py [how_many_patches]   (default 10)
No extra packages needed (Python 3.8+)."""
import json, re, sys, html, os, urllib.request
from datetime import datetime, timezone

BASE = "https://www.dota2.com/datafeed/"
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 10

def get(path):
    req = urllib.request.Request(path if path.startswith("http") else BASE + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def clean(t):
    return html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()

def collect(o, out):
    """Find every {'note': ...} anywhere inside a hero/item entry."""
    if isinstance(o, dict):
        if "note" in o:
            t = clean(o["note"])
            if t:
                out.append((int(o.get("indent_level", 0) or 0), t))
        for v in o.values():
            if isinstance(v, (dict, list)):
                collect(v, out)
    elif isinstance(o, list):
        for v in o:
            collect(v, out)

UP = ("increased", "improved", "added", "gained")
DOWN = ("decreased", "reduced", "lowered", "removed")
FLIP = ("cooldown", "mana cost", "cast point", "backswing", "delay", "gold cost",
        "recipe cost", "health cost", "cast animation", "channel time", "turn rate penalty")

def direction(text):
    m = re.search(r"\b(increased|decreased|reduced|improved|lowered|removed|added|gained)\b", text.lower())
    if not m:
        return 0
    d = 1 if m.group(1) in UP else -1
    if any(k in text.lower() for k in FLIP):
        d = -d
    return d

def build(section, names, prefix):
    cards = []
    for e in section or []:
        eid = e.get("hero_id", e.get("ability_id"))
        raw = names.get(eid)
        if not raw:
            continue
        notes = []
        collect(e, notes)
        if not notes:
            continue
        ns = [{"i": i, "t": t, "c": direction(t), "w": explain(t, direction(t))} for i, t in notes]
        pos = sum(1 for n in ns if n["c"] > 0)
        neg = sum(1 for n in ns if n["c"] < 0)
        tag = "Buff" if pos and not neg else "Nerf" if neg and not pos else "Adjust"
        cards.append({"n": raw[1], "img": raw[0].replace(prefix, "", 1), "tag": tag, "notes": ns})
    return sorted(cards, key=lambda c: c["n"].lower())

CACHE = {"heroes": {}}
AMAP = {}
REFRESHED = set()
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hero_abilities.json")

def rebuild_amap():
    AMAP.clear()
    for ab in CACHE["heroes"].values():
        AMAP.update(ab)

def load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            CACHE.update(json.load(f))
    except Exception:
        pass
    rebuild_amap()

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(CACHE, f, ensure_ascii=False)

def walk_abilities(o, out):
    if isinstance(o, dict):
        if "id" in o and "name" in o and "name_loc" in o:
            out[str(o["id"])] = [o["name"], o["name_loc"]]
        for v in o.values():
            if isinstance(v, (dict, list)):
                walk_abilities(v, out)
    elif isinstance(o, list):
        for v in o:
            walk_abilities(v, out)

def fetch_hero(hid):
    try:
        d = get("herodata?language=english&hero_id=%s" % hid)
        h = d["result"]["data"]["heroes"][0]
        ab = {}
        walk_abilities(h.get("abilities"), ab)
        walk_abilities(h.get("facet_abilities"), ab)
        CACHE["heroes"][str(hid)] = ab
        AMAP.update(ab)
    except Exception as ex:
        print("  could not read hero", hid, ex)

# (pattern, text if the number went UP, text if it went DOWN)
RULES = [
    (r"cooldown", "Longer cooldown: it can be used less often, so fewer fights and ganks.", "Shorter cooldown: it can be used more often, so more fights and ganks."),
    (r"mana cost|manacost", "Costs more mana, so it is harder to spam.", "Costs less mana, so it is easier to spam in lane and fights."),
    (r"gold cost|recipe|\bcost\b", "Costs more gold, so it comes later in the game.", "Costs less gold, so it comes earlier in the game."),
    (r"cast range", "Reaches farther, so it is safer and easier to land.", "Shorter reach, so you need to get closer and take more risk."),
    (r"cast point|cast animation|backswing|delay", "Takes longer, so enemies get more time to react.", "Faster, so enemies get less time to react."),
    (r"movement speed|move speed", "Faster movement, so it is easier to chase or escape.", "Slower movement, so it is easier to catch or kite."),
    (r"attack speed", "Attacks faster, so more damage in fights.", "Attacks slower, so less damage in fights."),
    (r"magic resist", "Takes less magic damage.", "Takes more magic damage."),
    (r"armor", "Takes less physical damage.", "Takes more physical damage."),
    (r"lifesteal", "Heals more from hitting, so it survives longer in fights.", "Heals less from hitting, so it is easier to burst down."),
    (r"regen", "Recovers faster, so it can stay in lane longer.", "Recovers slower, so it must go back to base sooner."),
    (r"damage", "Hits harder, so trades and kills are faster.", "Hits softer, so trades and kills take longer."),
    (r"duration", "The effect lasts longer.", "The effect ends sooner."),
    (r"radius|aoe|area", "Covers a bigger area, so it is easier to hit several enemies.", "Covers a smaller area, so it is harder to hit several enemies."),
    (r"\bhealth\b|\bhp\b", "Tougher, with more health to chew through.", "More fragile, with less health."),
    (r"\bmana\b", "More mana to cast with.", "Less mana to cast with."),
    (r"\brange\b", "Longer reach.", "Shorter reach."),
    (r"strength|agility|intelligence|all stats|attribute", "Stronger stats, so a bit more power at every level.", "Weaker stats, so a bit less power at every level."),
    (r"gold|xp|experience|bounty", "More reward, so faster farming or snowballing.", "Less reward, so slower farming or snowballing."),
    (r"charge", "More uses available.", "Fewer uses available."),
]

def explain(text, c, talent=False):
    low = text.lower()
    if low.startswith("fixed"):
        return "A bug fix: it now works the way it was meant to."
    m = re.search(r"\b(increased|decreased|reduced|improved|lowered|removed|added|gained)\b", low)
    if m:
        up = m.group(1) in UP
        for pat, u, d in RULES:
            if re.search(pat, low):
                return u if up else d
    if talent:
        if c > 0:
            return "This talent becomes a more attractive pick."
        if c < 0:
            return "This talent becomes a less attractive pick."
        return "A talent change. Check if it still fits your build."
    if c > 0:
        return "A small power boost."
    if c < 0:
        return "A small power reduction."
    return "A behavior change. Read the note and test it in a game."

def build_heroes(section, heroes):
    cards = []
    for e in section or []:
        hid = e.get("hero_id")
        raw = heroes.get(hid)
        if not raw:
            continue
        groups = []

        def add(name, icon, kind, src, talent=False):
            notes = []
            collect(src, notes)
            if notes:
                ns = [{"i": i, "t": t, "c": direction(t), "w": explain(t, direction(t), talent)} for i, t in notes]
                groups.append({"name": name, "icon": icon, "kind": kind, "notes": ns})

        for ab in e.get("abilities") or []:
            aid = str(ab.get("ability_id"))
            if aid not in AMAP and hid not in REFRESHED:
                REFRESHED.add(hid)
                fetch_hero(hid)
            info = AMAP.get(aid)
            add(info[1] if info else "Ability", info[0] if info else "", "ability", ab)
        add("Hero", "", "hero", e.get("hero_notes"))
        add("Talents", "", "talent", e.get("talent_notes"), True)
        allns = [n for g in groups for n in g["notes"]]
        if not allns:
            continue
        pos = sum(1 for n in allns if n["c"] > 0)
        neg = sum(1 for n in allns if n["c"] < 0)
        tag = "Buff" if pos and not neg else "Nerf" if neg and not pos else "Adjust"
        cards.append({"n": raw[1], "img": raw[0].replace("npc_dota_hero_", "", 1), "tag": tag, "groups": groups})
    return sorted(cards, key=lambda c: c["n"].lower())

STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats_history.json")

def build_stats():
    """Meta stats from OpenDota heroStats (free, no key). Saves a daily snapshot so real trends can build up."""
    try:
        raw = get("https://api.opendota.com/api/heroStats")
        assert isinstance(raw, list) and len(raw) > 50 and "1_pick" in raw[0]
    except Exception as ex:
        print("Meta stats unavailable:", ex)
        return None
    now = datetime.now(timezone.utc)
    iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    heroes, snap = [], {}
    for h in raw:
        b = [[h.get("%d_pick" % i, 0) or 0, h.get("%d_win" % i, 0) or 0] for i in range(1, 9)]
        pub = [h.get("pub_pick", 0) or 0, h.get("pub_win", 0) or 0]
        heroes.append({
            "id": h["id"], "n": h.get("localized_name", ""), "img": h["name"].replace("npc_dota_hero_", "", 1),
            "attr": h.get("primary_attr"), "b": b, "pub": pub,
            "pro": [h.get("pro_pick", 0) or 0, h.get("pro_win", 0) or 0, h.get("pro_ban", 0) or 0],
            "tp": h.get("pub_pick_trend") or [], "tw": h.get("pub_win_trend") or [],
        })
        snap[str(h["id"])] = pub + [x for pair in b for x in pair]
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = {}
    hist[now.strftime("%Y-%m-%d")] = {"t": iso, "d": snap}
    for k in sorted(hist)[:-90]:
        del hist[k]
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f)
    recent = {k: hist[k] for k in sorted(hist)[-30:]}
    return {"retrieved": iso, "heroes": heroes, "history": recent}

def main():
    print("Fetching name lists...")
    heroes = {h["id"]: (h["name"], h["name_english_loc"]) for h in get("herolist?language=english")["result"]["data"]["heroes"]}
    items = {i["id"]: (i["name"], i["name_english_loc"]) for i in get("itemlist?language=english")["result"]["data"]["itemabilities"]}
    plist = get("patchnoteslist?language=english")["patches"]
    plist.sort(key=lambda p: p["patch_timestamp"], reverse=True)
    load_cache()
    missing = [h for h in heroes if str(h) not in CACHE["heroes"]]
    if missing:
        print("First run: downloading skill names for %d heroes (1-2 minutes, one time only)..." % len(missing))
    for n, h in enumerate(missing, 1):
        fetch_hero(h)
        if n % 20 == 0:
            print("  ", n, "/", len(missing))
    save_cache()
    out = []
    for p in plist[:COUNT]:
        v = p["patch_number"]
        print("Fetching patch", v, "...")
        try:
            d = get("patchnotes?version=%s&language=english" % v)
        except Exception as ex:
            print("  skipped:", ex)
            continue
        out.append({
            "id": v,
            "date": datetime.fromtimestamp(p["patch_timestamp"], timezone.utc).strftime("%B %d, %Y"),
            "heroes": build_heroes(d.get("heroes"), heroes),
            "items": build(d.get("items"), items, "item_"),
            "neutral": build(d.get("neutral_items"), items, "item_"),
        })
    save_cache()
    print("Fetching meta stats (OpenDota)...")
    stats = build_stats()
    sdata = json.dumps(stats, ensure_ascii=False).replace("</", "<\\/") if stats else "null"
    data = json.dumps(out, ensure_ascii=False).replace("</", "<\\/")
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "dota2-patch-tracker.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.replace("__STATS__", sdata).replace("__BUILT__", datetime.now().strftime("%Y-%m-%d %H:%M")).replace("__DATA__", data))
    print("Done! Created:", path)
    print("Patches:", ", ".join(x["id"] for x in out))

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dota 2 Patch Tracker</title>
<meta name="description" content="Every Dota 2 hero and item change, explained. Patch notes, buffs and nerfs, hero meta. Updated automatically.">
<meta name="theme-color" content="#07080f">
<link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta property="og:type" content="website"><meta property="og:site_name" content="Dota 2 Patch Tracker">
<meta property="og:title" content="Dota 2 Patch Tracker"><meta property="og:description" content="Patch notes, buffs and nerfs, hero meta. Every hero and item change, explained.">
<meta property="og:url" content="https://dotapatchwatch.vercel.app/"><meta property="og:image" content="https://dotapatchwatch.vercel.app/og-image.jpg"><meta property="og:image:type" content="image/jpeg">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:alt" content="Dota 2 Patch Tracker">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="Dota 2 Patch Tracker"><meta name="twitter:image" content="https://dotapatchwatch.vercel.app/og-image.jpg">
<style>
:root{--bg:#07080f;--card:rgba(255,255,255,.045);--bd:rgba(140,170,255,.16);--tx:#e8ecf7;--mut:#98a2c0;--ac:#5B9DFF;--buff:#2fd18b;--nerf:#ff5a6a;--gold:#f2c14e;--adj:#b79cff}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:150px}
body{margin:0;font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--tx);background:radial-gradient(900px 500px at 10% -10%,#1b2a6b55,transparent),radial-gradient(800px 500px at 100% 0,#4a1d7a44,transparent),var(--bg);min-height:100vh}
header{position:sticky;top:0;z-index:20;backdrop-filter:blur(14px);background:rgba(7,8,15,.8);border-bottom:1px solid var(--bd);padding:10px 16px}
.hw{max-width:1100px;margin:auto;display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between}
h1{font-size:1.15rem;margin:0}h1 b{color:var(--ac)}.sub{font-size:.8rem;color:var(--mut)}
select,input{background:#101428;color:var(--tx);border:1px solid var(--bd);border-radius:12px;padding:12px 14px;font-size:1rem;min-height:44px}
select{min-width:150px}input{width:100%}
select:focus,input:focus,a:focus-visible{outline:2px solid var(--ac)}
main{max-width:1100px;margin:auto;padding:20px 16px 60px}
.hero{padding:26px 20px;border-radius:22px;border:1px solid var(--bd);background:linear-gradient(135deg,#16224d88,#2a124a66);box-shadow:0 20px 60px #0008}
.date{color:var(--gold);font-size:.85rem;letter-spacing:1.5px;text-transform:uppercase}
.hero h2{font-size:clamp(2.2rem,8vw,3.8rem);margin:4px 0 8px;line-height:1.05}.hero p{max-width:62ch;color:#cdd5ee;margin:0 0 14px}
.tags,.pills{display:flex;flex-wrap:wrap;gap:8px}.pills{margin-top:18px}
.tag{font-size:.72rem;font-weight:700;padding:3px 10px;border-radius:99px;border:1px solid;text-transform:uppercase;letter-spacing:.6px}
.Buff{color:var(--buff);border-color:#2fd18b66;background:#2fd18b18}.Nerf{color:var(--nerf);border-color:#ff5a6a66;background:#ff5a6a18}.Adjust{color:var(--adj);border-color:#b79cff66;background:#b79cff18}
.pill{color:var(--tx);text-decoration:none;padding:11px 16px;border-radius:99px;border:1px solid var(--bd);background:var(--card);min-height:44px;display:inline-flex;align-items:center;transition:.2s}
.pill:hover{border-color:var(--ac);box-shadow:0 0 18px #5B9DFF55}
section{margin-top:38px}section h3{font-size:1.4rem;margin:0 0 4px}.lead{color:var(--mut);margin:0 0 16px;font-size:.9rem}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.card{padding:14px;border-radius:18px;background:var(--card);border:1px solid var(--bd);backdrop-filter:blur(8px);transition:.22s;animation:in .4s both}
.card:hover{transform:translateY(-4px);border-color:var(--ac);box-shadow:0 10px 34px #5B9DFF33}
.top{display:flex;gap:12px;align-items:center;margin-bottom:8px}
.top img{width:84px;height:62px;object-fit:cover;border-radius:10px;box-shadow:0 6px 16px #000a;background:#10152e;flex:none}
.top h4{margin:0;font-size:1.02rem}
ul.n{list-style:none;margin:0;padding:0;font-size:.88rem}
ul.n li{padding:4px 0 4px 10px;border-left:2px solid var(--bd);color:#cfd6ee}
ul.n li.u{border-color:var(--buff)}ul.n li.d{border-color:var(--nerf)}
.in1{margin-left:14px}.in2{margin-left:28px}
.empty{color:var(--mut)}.vid{display:flex;padding:18px;border-radius:18px;border:1px dashed var(--bd);color:var(--tx);text-decoration:none;background:var(--card)}
.vid:hover{border-color:var(--ac)}
footer{text-align:center;color:var(--mut);font-size:.8rem;padding:30px 16px 50px;border-top:1px solid var(--bd)}footer a{color:var(--ac)}
@keyframes in{from{opacity:0;transform:translateY(10px)}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
.g{margin-top:10px;padding-top:8px;border-top:1px solid var(--bd)}.gh{display:flex;gap:10px;align-items:center;margin-bottom:4px}
.gh img{width:40px;height:40px;border-radius:8px;object-fit:cover;background:#10152e;box-shadow:0 4px 12px #000a}
.gi{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;border:1px solid var(--bd);color:var(--gold);flex:none}
.w{font-size:.8rem;color:var(--mut);margin-top:1px}.w b{color:var(--gold)}
.navb{display:flex;gap:6px}.nv{background:var(--card);color:var(--tx);border:1px solid var(--bd);border-radius:99px;padding:10px 16px;min-height:44px;font-size:.95rem;cursor:pointer}
.nv.on{border-color:var(--ac);box-shadow:0 0 16px #5B9DFF55}
.ctl{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}.ctl label{font-size:.8rem;color:var(--mut);display:grid;gap:4px}
.tw{overflow-x:auto;border:1px solid var(--bd);border-radius:18px;background:var(--card)}
table{border-collapse:collapse;width:100%;min-width:760px;font-size:.9rem}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--bd);white-space:nowrap}
th{color:var(--mut);font-size:.75rem;text-transform:uppercase;letter-spacing:.5px;cursor:pointer;user-select:none;position:sticky;top:0}
th.on{color:var(--ac)}tr:hover td{background:#5B9DFF10}
.hn{display:flex;align-items:center;gap:10px}.hn img{width:46px;height:27px;border-radius:6px;object-fit:cover;background:#10152e}
.bar{display:inline-block;width:60px;height:6px;border-radius:9px;background:#ffffff14;margin-left:8px;vertical-align:middle;overflow:hidden}.bar i{display:block;height:100%;background:var(--ac)}
.moe{color:var(--mut);font-size:.75rem}.up{color:var(--buff)}.dn{color:var(--nerf)}.st{color:var(--mut)}
.defs{font-size:.82rem;color:var(--mut);margin-top:14px;display:grid;gap:4px}
</style></head><body>
<header><div class="hw"><div><h1>Dota 2 <b>Patch Tracker</b></h1><div class="sub">No surprises. Every change explained.</div></div>
<nav class="navb"><button class="nv on" data-v="p">Patches</button><button class="nv" data-v="s">Meta &amp; Stats</button></nav>
<select id="sel" aria-label="Select patch"></select></div></header>
<main id="app"></main>
<footer>Images from official Steam CDN · Always verify on <a href="https://www.dota2.com/patches" target="_blank" rel="noopener">dota2.com/patches</a><br>Data from Valve's official patch notes · Built __BUILT__</footer>
<script>
const DATA=__DATA__;
const CDN="https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/";
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const sel=document.getElementById("sel"),app=document.getElementById("app");
const note=n=>`<li class="in${Math.min(n.i,2)} ${n.c>0?'u':n.c<0?'d':''}">${esc(n.t)}<div class="w"><b>Quick take:</b> ${esc(n.w||"")}</div></li>`;
const grp=g=>`<div class="g"><div class="gh">${g.icon?`<img loading="lazy" alt="${esc(g.name)}" src="${CDN}abilities/${g.icon}.png" onerror="this.style.visibility='hidden'">`:`<span class="gi">${g.kind==="talent"?"✦":"◆"}</span>`}<b>${esc(g.name)}</b></div><ul class="n">${g.notes.map(note).join("")}</ul></div>`;
const card=(x,kind)=>`<article class="card" data-s="${esc((x.n+" "+(x.groups||[]).map(g=>g.name).join(" ")).toLowerCase())}"><div class="top"><img loading="lazy" alt="${esc(x.n)}" src="${CDN}${kind}/${x.img}.png" onerror="this.style.visibility='hidden'"><div><h4>${esc(x.n)}</h4><span class="tag ${x.tag}">${x.tag}</span></div></div>${x.groups?x.groups.map(grp).join(""):`<ul class="n">${x.notes.map(note).join("")}</ul>`}</article>`;
const sec=(id,title,lead,arr,kind)=>`<section id="${id}"><h3>${title} <span class="sub">(${arr.length})</span></h3><p class="lead">${lead}</p>${arr.length?`<div class="grid">${arr.map(x=>card(x,kind)).join("")}</div>`:'<p class="empty">No changes listed.</p>'}</section>`;
function count(a,t){return a.filter(x=>x.tag===t).length}
function render(i){
  const p=DATA[i],all=[...p.heroes,...p.items,...p.neutral];
  const q=encodeURIComponent("Dota 2 "+p.id+" patch explained");
  app.innerHTML=`<div class="hero"><div class="date">Released ${esc(p.date)}</div><h2>${esc(p.id)}</h2>
  <p>${p.heroes.length} heroes, ${p.items.length} items and ${p.neutral.length} neutral items changed. Overall: ${count(all,"Buff")} buffed, ${count(all,"Nerf")} nerfed, ${count(all,"Adjust")} mixed.</p>
  <div class="tags"><span class="tag Buff">Buff ${count(all,"Buff")}</span><span class="tag Nerf">Nerf ${count(all,"Nerf")}</span><span class="tag Adjust">Mixed ${count(all,"Adjust")}</span></div>
  <nav class="pills"><a class="pill" href="#videos">▶ Videos</a><a class="pill" href="#items">Items</a><a class="pill" href="#neutral">Neutrals</a><a class="pill" href="#heroes">Heroes</a></nav>
  <p class="sub" style="margin-top:14px">Green line = buff, red line = nerf, no color = unclear. Colors and the "Quick take" lines are auto-written by simple rules, not by Valve, so check the notes.</p>
  <input id="q" type="search" placeholder="Search a hero or item..." aria-label="Search"></div>
  <section id="videos"><h3>Videos</h3><p class="lead">Community breakdowns.</p><a class="vid" href="https://www.youtube.com/results?search_query=${q}" target="_blank" rel="noopener">▶ Find ${esc(p.id)} videos on YouTube</a></section>
  ${sec("items","Items","Shop changes.",p.items,"items")}${sec("neutral","Neutral Items","Jungle item changes.",p.neutral,"items")}${sec("heroes","Heroes","Every hero change.",p.heroes,"heroes")}
  <section><a class="vid" href="https://www.dota2.com/patches/${esc(p.id)}" target="_blank" rel="noopener">Official notes for ${esc(p.id)} ↗</a></section>`;
  document.getElementById("q").oninput=e=>{const v=e.target.value.toLowerCase();document.querySelectorAll(".card").forEach(c=>c.style.display=c.dataset.s.includes(v)?"":"none")};
}
sel.innerHTML=DATA.map((p,i)=>`<option value="${i}">${esc(p.id)}</option>`).join("");
sel.onchange=()=>{render(+sel.value);scrollTo({top:0})};
if(DATA.length)render(0);else app.innerHTML="<p>No data. Run update_patches.py again.</p>";
const STATS=__STATS__;
const RN=["Herald","Guardian","Crusader","Archon","Legend","Ancient","Divine","Immortal"];
let S={rank:"all",min:1000,key:"wr",dir:-1,q:""};
const vals=(h,r)=>r==="all"?h.pub:h.b[r-1];
function findSnap(){const ds=Object.keys(STATS.history).sort(),lim=new Date(STATS.retrieved);lim.setUTCDate(lim.getUTCDate()-7);const ok=ds.filter(d=>new Date(STATS.history[d].t)<=lim);return ok.length?STATS.history[ok[ok.length-1]]:null}
function spark(h){const v=h.tp.map((p,i)=>p?h.tw[i]/p*100:null).filter(x=>x!==null);if(v.length<2)return"n/a";const m=v.reduce((a,b)=>a+b)/v.length;const pts=v.map((x,i)=>(i*(66/(v.length-1))+2).toFixed(1)+","+Math.max(2,Math.min(22,12-(x-m)/5*10)).toFixed(1)).join(" ");return`<svg width="70" height="24" role="img" aria-label="7-day win rate trend"><title>Daily win rate, oldest to newest: ${v.map(x=>x.toFixed(1)+"%").join(", ")}. Scale: mean ±5 points.</title><polyline fill="none" stroke="#5B9DFF" stroke-width="2" points="${pts}"/></svg>`}
const pp=n=>(n>0?"+":"")+n.toFixed(1)+" pp";
function drawTable(){
  const hs=STATS.heroes,r=S.rank,prev=findSnap();
  const tot=hs.reduce((a,h)=>a+vals(h,r)[0],0)/10;
  let rows=hs.map(h=>{const[p,w]=vals(h,r),wr=p?w/p*100:0,moe=p?1.96*Math.sqrt(wr/100*(1-wr/100)/p)*100:0;let d=null,lab="Collecting data";
    if(prev){const q=prev.d[h.id];if(q){const o=r==="all"?[q[0],q[1]]:[q[2+(r-1)*2],q[3+(r-1)*2]];if(o[0]>=S.min&&p>=S.min){const owr=o[1]/o[0]*100;d=wr-owr;const se=Math.sqrt(wr*(100-wr)/p+owr*(100-owr)/o[0]);lab=Math.abs(d)>=.5&&Math.abs(d)>1.96*se?(d>0?"Rising":"Falling"):"Stable"}else lab="Low sample"}}
    return{h,p,wr,moe,pr:tot?p/tot*100:0,d,lab}}).filter(x=>x.p>=S.min);
  const shown0=rows.length,hidden=hs.length-shown0;
  rows=rows.filter(x=>x.h.n.toLowerCase().includes(S.q));
  const kv={wr:x=>x.wr,pr:x=>x.pr,p:x=>x.p,pb:x=>x.h.pro[2],d:x=>x.d===null?(S.dir<0?-1e9:1e9):x.d};
  rows.sort((a,b)=>(kv[S.key](a)-kv[S.key](b))*S.dir);
  const th=(k,t,tip)=>`<th data-k="${k}" class="${S.key===k?'on':''}" title="${esc(tip)}">${t}${S.key===k?(S.dir<0?" ▼":" ▲"):""}</th>`;
  const lc={Rising:"up",Falling:"dn"},li={Rising:"▲ Rising",Falling:"▼ Falling",Stable:"● Stable"};
  document.getElementById("tb").innerHTML=`<div class="tw"><table><thead><tr><th>#</th><th>Hero</th>${th("wr","Win rate","Wins divided by matches for this hero in the selected rank. The ± is the 95% margin of error.")}${th("pr","Pick rate","Calculated here: hero picks divided by estimated matches (all hero picks in this rank divided by 10).")}${th("p","Matches","Number of matches this hero was picked in. More matches means a more reliable win rate.")}<th title="Daily win rate for the last 7 days, all ranks combined. Scale is the hero's mean ±5 points.">7-day trend</th>${th("d","Change vs last week","Win-rate change in percentage points versus a saved snapshot at least 7 days old.")}${th("pb","Pro bans*","Bans in professional matches only. Not available for normal matches.")}</tr></thead><tbody>${rows.map((x,i)=>`<tr><td>${i+1}</td><td><div class="hn"><img loading="lazy" alt="" src="${CDN}heroes/${x.h.img}.png" onerror="this.style.visibility='hidden'">${esc(x.h.n)}</div></td><td><b>${x.wr.toFixed(1)}%</b> <span class="moe">±${x.moe.toFixed(1)}</span><span class="bar"><i style="width:${Math.max(0,Math.min(100,(x.wr-40)*5))}%"></i></span></td><td>${x.pr.toFixed(1)}%</td><td>${x.p.toLocaleString()}</td><td>${spark(x.h)}</td><td>${x.d===null?`<span class="st">${x.lab}</span>`:`<span class="${lc[x.lab]||'st'}">${pp(x.d)} ${li[x.lab]||x.lab}</span>`}</td><td>${x.h.pro[2]}</td></tr>`).join("")}</tbody></table></div><p class="sub">${shown0} heroes meet the minimum of ${S.min.toLocaleString()} matches${hidden?`; ${hidden} hidden for having too few matches`:""}. Showing ${rows.length}.</p>`;
  document.querySelectorAll("#tb th[data-k]").forEach(e=>e.onclick=()=>{const k=e.dataset.k;S.dir=S.key===k?-S.dir:-1;S.key=k;drawTable()});
}
function renderStats(){
  if(!STATS){app.innerHTML=`<div class="hero"><h2>Meta &amp; Stats</h2><p>Data unavailable: OpenDota could not be reached when this page was built. The patch tracker still works.</p></div>`;return}
  const imm=STATS.heroes.some(h=>h.b[7][0]>0),hd=Object.keys(STATS.history).sort();
  const ret=new Date(STATS.retrieved).toLocaleString();
  app.innerHTML=`<div class="hero"><div class="date">Meta &amp; Stats</div><h2>Hero win rates by rank</h2><p>Real match data from OpenDota, covering about the last 7 days of public matches. Sorted by win rate by default.</p>
  <div class="ctl"><label>Rank<select id="rk"><option value="all">All ranks (public)</option>${RN.map((n,i)=>`<option value="${i+1}" ${i===7&&!imm?"disabled":""}>${n}${i===7&&!imm?" (data unavailable)":""}</option>`).join("")}</select></label>
  <label>Minimum matches<input id="mn" type="number" min="0" step="100" value="${S.min}"></label><label>Search hero<input id="sq" type="search" placeholder="Hero name"></label></div>
  <p class="sub">Data from OpenDota (free API) · retrieved ${esc(ret)} · history saved since ${esc(hd[0]||"today")}</p></div>
  <section id="tb"></section>
  <div class="defs"><div><b>Win rate:</b> wins ÷ matches for the hero in the selected rank. The ± is a 95% margin of error, so a small gap between two heroes may be noise.</div>
  <div><b>Pick rate:</b> calculated by this page as hero picks ÷ estimated matches (all picks ÷ 10). OpenDota does not provide it directly.</div>
  <div><b>Ban rate:</b> data unavailable for normal matches. *Pro bans are professional matches only, a small sample.</div>
  <div><b>Change vs last week:</b> needs a saved snapshot at least 7 days old, so it shows "Collecting data" until then. Rising/Falling is shown only when the change is at least 0.5 points and larger than random noise. Nothing here explains why a hero changed.</div>
  <div><b>Not available from this source:</b> Immortal ranks, role and lane stats, builds, and reliable matchups.</div></div>`;
  document.getElementById("rk").onchange=e=>{S.rank=e.target.value==="all"?"all":+e.target.value;drawTable()};
  document.getElementById("mn").oninput=e=>{S.min=Math.max(0,+e.target.value||0);drawTable()};
  document.getElementById("sq").oninput=e=>{S.q=e.target.value.toLowerCase();drawTable()};
  drawTable();
}
function setView(v){document.querySelectorAll(".nv").forEach(b=>b.classList.toggle("on",b.dataset.v===v));sel.style.display=v==="p"?"":"none";if(v==="p"){if(DATA.length)render(+sel.value)}else renderStats();scrollTo({top:0})}
document.querySelectorAll(".nv").forEach(b=>b.onclick=()=>setView(b.dataset.v));

</script></body></html>"""

if __name__ == "__main__":
    main()
