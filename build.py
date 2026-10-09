#!/usr/bin/env python3
"""We Speak Sustainability — static site builder.

Reads data/*.json and writes a complete static site to _site/.
No third-party dependencies: runs on any Python 3.9+.
Usage:  python3 build.py
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "_site")
SITE = json.load(open(os.path.join(ROOT, "data/site.json"), encoding="utf-8"))
ALL_STORIES = json.load(open(os.path.join(ROOT, "data/stories.json"), encoding="utf-8"))
ALL_LEGACY = json.load(open(os.path.join(ROOT, "data/legacy.json"), encoding="utf-8"))

# Only content an editor has marked published reaches the public site.
STORIES = [s for s in ALL_STORIES if s.get("editorial_status", "published") in ("published", "updated")]
LEGACY = [m for m in ALL_LEGACY if m.get("editorial_status", "published") in ("published", "updated")]
STORIES.sort(key=lambda s: s["title"])
BASE = SITE["base_url"].rstrip("/")
TODAY = dt.date.today()
WEEK = TODAY.isocalendar()[1] + TODAY.year * 53
TOPICS = SITE["topics"]
PROBLEMS = SITE["problems"]
EVID = SITE["evidence"]
SDGS = SITE["sdgs"]

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def e(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def slugify(x):
    return re.sub(r"[^a-z0-9]+", "-", x.lower().replace("'", "")).strip("-")


def fmt_date(d):
    if not d:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(d))
    if m:
        return f"{int(m.group(3))} {MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    m = re.match(r"^(\d{4})-(\d{2})$", str(d))
    if m:
        return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    return str(d)


def year(d):
    m = re.search(r"\d{4}", str(d or ""))
    return m.group(0) if m else str(d or "")


def paras(text):
    if not text:
        return ""
    return "".join(f"<p>{e(p.strip())}</p>" for p in str(text).split("\n\n") if p.strip())


def initials(name):
    parts = [p for p in re.split(r"[\s\-]+", name) if p and p[0].isalpha()]
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def first_name(s):
    if s.get("display_name"):
        return s["display_name"]
    p = s["person"]
    if s.get("actor_type") in ("community", "organisation") or " and " in p or "," in p:
        return p
    return p.split()[0]


# ---------- generative art (no stock photos: every story gets its own contour drawing) ----------
PALETTES = {
    "plastic-waste": ("#2c6784", "#e8dcc4"), "food-waste": ("#8c3a20", "#efd9b0"),
    "water-scarcity": ("#1f5f80", "#d6e4e6"), "deforestation": ("#4c6a35", "#e6e0c3"),
    "biodiversity-loss": ("#6b4f1d", "#efe0b4"), "soil-degradation": ("#8a5a24", "#f0dcb8"),
    "air-pollution": ("#555a66", "#e3e1dc"), "energy": ("#b9871f", "#f4e6c0"),
    "agricultural-waste": ("#7a6a2a", "#ece2bd"), "ocean-pollution": ("#255b73", "#d5e3e2"),
    "fast-fashion": ("#7b3a4f", "#efd9d9"), "urban-waste": ("#a8492a", "#efdcc8"),
    "climate-adaptation": ("#3d5f6e", "#e2e3d6"),
}


def art(seed, problem="urban-waste", label=""):
    ink, bg = PALETTES.get(problem, ("#a8492a", "#efe3cf"))
    h = hashlib.sha256(seed.encode()).digest()
    cx, cy = 120 + h[0] * 2.4, 60 + h[1] * 0.9
    lines = []
    for i in range(14):
        r = 18 + i * 26 + (h[i % 32] % 9)
        rx, ry = r * (1.25 + h[2] / 600), r * (0.78 + h[3] / 900)
        rot = (h[4] % 60) - 30
        op = 0.85 - i * 0.05
        lines.append(f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{rx:.0f}" ry="{ry:.0f}" transform="rotate({rot} {cx:.0f} {cy:.0f})" fill="none" stroke="{ink}" stroke-width="{1.6 if i % 4 else 2.6}" opacity="{max(op, .18):.2f}"/>')
    dots = "".join(f'<circle cx="{(h[i] * 3.1) % 800:.0f}" cy="{(h[i + 8] * 1.7) % 400:.0f}" r="{2 + h[i] % 3}" fill="{ink}" opacity=".35"/>' for i in range(8, 20))
    return (f'<svg class="art" viewBox="0 0 800 400" preserveAspectRatio="xMidYMid slice" role="img" aria-label="{e(label or "Decorative contour drawing")}">'
            f'<rect width="800" height="400" fill="{bg}"/>{"".join(lines)}{dots}'
            f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="7" fill="{ink}"/></svg>')


from urllib.parse import quote as _q


PHOTO_WIDTHS = (500, 960, 1280)
PHOTO_CACHE = os.path.join(ROOT, ".photo-cache")
LOCAL_PHOTOS = {}  # (file, width) -> site path


def remote_photo_url(file, w=960):
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{_q(file)}?width={w}"


def photo_url(file, w=960):
    """Self-hosted copy when the build fetched one; otherwise the Wikimedia Commons original."""
    return LOCAL_PHOTOS.get((file, w)) or remote_photo_url(file, w)


def fetch_photos():
    """Download every credited photo once (cached between builds) and serve it from our own domain.
    Runs on GitHub Actions; if a download fails the page falls back to the Commons URL."""
    import time
    import urllib.request
    files = sorted({im["file"] for x in ALL_STORIES + ALL_LEGACY for im in x.get("images", [])})
    os.makedirs(PHOTO_CACHE, exist_ok=True)
    ok = fail = 0
    for f in files:
        key = hashlib.sha1(f.encode()).hexdigest()[:12]
        for w in PHOTO_WIDTHS:
            cached = [n for n in os.listdir(PHOTO_CACHE) if n.startswith(f"{key}-{w}.")]
            if not cached:
                try:
                    req = urllib.request.Request(remote_photo_url(f, w), headers={
                        "User-Agent": "WeSpeakSustainabilitySiteBuilder/1.0 (https://wespeaksustainability.com)"})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        ctype = r.headers.get("Content-Type", "")
                        data = r.read()
                    ext = "png" if "png" in ctype else "webp" if "webp" in ctype else "jpg"
                    if not ctype.startswith("image/") or len(data) < 1000:
                        raise ValueError(f"unexpected response {ctype}")
                    with open(os.path.join(PHOTO_CACHE, f"{key}-{w}.{ext}"), "wb") as fh:
                        fh.write(data)
                    cached = [f"{key}-{w}.{ext}"]
                    time.sleep(0.4)
                except Exception as ex:  # keep building; hotlink instead
                    print(f"  photo fetch failed: {f} @{w}: {ex}")
                    fail += 1
                    continue
            os.makedirs(os.path.join(OUT, "photos"), exist_ok=True)
            shutil.copy(os.path.join(PHOTO_CACHE, cached[0]), os.path.join(OUT, "photos", cached[0]))
            LOCAL_PHOTOS[(f, w)] = f"/photos/{cached[0]}"
            ok += 1
    print(f"Photos: {ok} self-hosted, {fail} falling back to Wikimedia Commons")


def hero_of(x):
    return next((i for i in x.get("images", []) if i.get("role") == "hero"), None)


def credit(im):
    lic = f'<a href="{e(im["license_url"])}" rel="license noopener">{e(im["license"])}</a>' if im.get("license_url") else e(im["license"])
    return f'<span class="credit">Photo: {e(im["author"])} · {lic} · <a href="{e(im["source_url"])}" rel="noopener">{e(im["source"])}</a></span>'


def figure(im, cls="photo", sizes="(max-width: 900px) 100vw, 800px", eager=False):
    cls += " o-" + im.get("orientation", "landscape")
    return (f'<figure class="{cls}"><img src="{photo_url(im["file"], 960)}" srcset="{photo_url(im["file"], 500)} 500w, {photo_url(im["file"], 960)} 960w, {photo_url(im["file"], 1280)} 1280w" '
            f'sizes="{sizes}" alt="{e(im["alt"])}" style="object-position:{e(im.get("focus", "50% 30%"))}" {"fetchpriority=high" if eager else "loading=lazy"} decoding="async">'
            f'<figcaption>{e(im["caption"])} {credit(im)}</figcaption></figure>')


def card_visual(x, problem):
    im = hero_of(x)
    if im:
        return f'<img class="art" src="{photo_url(im["file"], 500)}" alt="{e(im["alt"])}" style="object-position:{e(im.get("focus", "50% 30%"))}" loading="lazy" decoding="async" width="500" height="250">'
    return art(x["slug"], problem)


LOGO = ('<svg class="brand-mark" viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="18" fill="none" stroke="currentColor" stroke-width="2"/>'
        '<path d="M9 22c4-1 6-6 11-6s7 5 11 6" fill="none" stroke="#a8492a" stroke-width="2.4" stroke-linecap="round"/>'
        '<circle cx="20" cy="12" r="2.6" fill="#b9871f"/><path d="M12 28c3 2 13 2 16 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>')

NAV = [("/stories/", "Stories"), ("/map/", "Map"), ("/copy-this/", "Copy This"),
       ("/solutions/", "Solutions"), ("/legacy/", "Legacy"), ("/insights/", "Insights"), ("/about/", "About")]


def _asset_version():
    h = hashlib.sha1()
    for fn in sorted(os.listdir(os.path.join(ROOT, "assets"))):
        h.update(open(os.path.join(ROOT, "assets", fn), "rb").read())
    return h.hexdigest()[:8]


AV = _asset_version()


def av(u):
    return f"{u}?v={AV}" if u.startswith("/assets/") else u


GC = (f'<script src="https://gc.zgo.at/count.js" data-goatcounter="https://{SITE["goatcounter"]}.goatcounter.com/count" async></script>' if SITE.get("goatcounter") else "")


def layout(path, title, desc, body, *, jsonld=None, head_extra="", scripts=None, og_type="website", zone="", og_image=None):
    full_title = title if title == SITE["name"] else f"{title} · {SITE['name']}"
    nav = "".join(f'<a href="{u}"{" aria-current=\"page\"" if path.startswith(u) else ""}>{t}</a>' for u, t in NAV)
    ld = ""
    if jsonld:
        ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>'
    js = "".join(f'<script src="{av(s)}" defer></script>' for s in (scripts or []))
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(full_title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{BASE}{path}">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{BASE}{path}">
<meta property="og:image" content="{e((BASE + og_image) if (og_image or '').startswith('/') else (og_image or BASE + '/assets/og.png'))}">
<meta property="og:site_name" content="{SITE['name']}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#f7f2e8">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,600;1,9..144,500&family=Inter:wght@400;600&display=swap">
<link rel="stylesheet" href="/assets/style.css?v={AV}">
<script>try{{var t=localStorage.getItem('wss-theme');if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
{head_extra}{ld}
{GC}
</head>
<body class="{zone}">
<a class="skip" href="#main">Skip to content</a>
<header class="site-head">
 <div class="wrap head-in">
  <a class="brand" href="/">{LOGO}<span>We Speak Sustainability</span></a>
  <button class="menu-btn" aria-expanded="false" aria-controls="nav">Menu</button>
  <nav class="nav" id="nav" aria-label="Main">
   {nav}
   <a href="/search/" class="search-link"{" aria-current=\"page\"" if path.startswith("/search/") else ""}><svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="m15 15 6 6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>Search</a>
   <a href="/submit/" class="btn">Tell your story</a>
  </nav>
 </div>
</header>
<main id="main">
{body}
</main>
{footer()}
<script src="/assets/app.js?v={AV}" defer></script>
{js}
</body>
</html>"""


def footer():
    return f"""<footer class="site-foot">
 <div class="wrap">
  <div class="foot-grid">
   <div>
    <a class="brand" href="/">{LOGO}<span>We Speak Sustainability</span></a>
    <p class="muted" style="margin-top:12px;max-width:30ch">{e(SITE['tagline'])} A living archive of people making the world more sustainable.</p>
   </div>
   <div><h4>Explore</h4><ul>
    <li><a href="/stories/">All stories</a></li><li><a href="/map/">World map</a></li>
    <li><a href="/solutions/">One problem, many solutions</a></li><li><a href="/copy-this/">Copy This</a></li>
    <li><a href="/what-didnt-work/">What didn't work?</a></li><li><a href="/people/">People</a></li></ul>
    <h4 style="margin-top:18px">Research</h4><ul><li><a href="/insights/">Insights</a></li><li><a href="/data/">Open data</a></li><li><a href="/methodology/">Methodology</a></li><li><a href="/for-institutions/">For institutions</a></li></ul></div>
   <div><h4>Remember</h4><ul>
    <li><a href="/legacy/">Legacy</a></li><li><a href="/environmental-defenders/">Environmental defenders</a></li>
    <li><a href="/footprints/">They left a footprint</a></li><li><a href="/1000-small-things/">The 1,000 Small Things Project</a></li></ul></div>
   <div><h4>Take part</h4><ul>
    <li><a href="/submit/">Tell your story</a></li><li><a href="/corrections/">Report a correction</a></li>
    <li><a href="/editorial-policy/">Editorial &amp; verification policy</a></li><li><a href="/about/">About</a></li><li><a href="/founder/">Founder &amp; talks</a></li></ul></div>
  </div>
  <div class="foot-note">
   <span>Stories are published with sources. Spotted an error? <a href="/corrections/">Tell us</a>.</span>
   <button class="theme-toggle" type="button" data-theme-toggle>Toggle dark mode</button>
  </div>
 </div>
</footer>"""


# ---------- components ----------
def ev_badge(level):
    lab = EVID.get(level, EVID["self-reported"])["label"]
    return f'<a class="ev {e(level)}" href="/editorial-policy/#evidence" title="{e(EVID.get(level, {}).get("text", ""))}">{e(lab)}</a>'


def topic_chips(topics, link=True, limit=None):
    items = topics[:limit] if limit else topics
    out = []
    for t in items:
        if t not in TOPICS:
            continue
        out.append(f'<li><a class="chip" href="/stories/{t}/">{e(TOPICS[t])}</a></li>' if link and t in TOPIC_COUNTS else f'<li><span class="chip">{e(TOPICS[t])}</span></li>')
    return f'<ul class="chips">{"".join(out)}</ul>'


def place(s):
    return f'{s["city"]}, {s["country"]}'


def story_card(s, show_summary=True):
    data = (f'data-country="{e(slugify(s["country"]))}" data-region="{e(s["region"])}" data-topics="{e(" ".join(s["topics"]))}" '
            f'data-problem="{e(s["problem"])}" data-evidence="{e(s["evidence"])}" data-pillar="{e(s["pillar"])}" '
            f'data-scale="{e(s["scale"])}" data-actor="{e(s["actor_type"])}" data-status="{e(s["status"])}" '
            f'data-sdgs="{e(" ".join(str(x) for x in s.get("sdgs", [])))}"')
    return f"""<article class="card story-card" {data}>
 <a href="/stories/{s['slug']}/" tabindex="-1" aria-hidden="true">{card_visual(s, s['problem'])}</a>
 <div class="body">
  <div class="meta"><span class="place">{e(place(s))}</span><span>Since {e(s['started_year'])}</span></div>
  <h3><a href="/stories/{s['slug']}/">{e(s['title'])}</a></h3>
  {f"<p>{e(s['summary'])}</p>" if show_summary else ""}
  <div class="meta" style="margin-top:auto;padding-top:8px">{ev_badge(s['evidence'])}<span>{e(PROBLEMS[s['problem']]['label'])}</span></div>
 </div>
</article>"""


def portrait(m, big=False):
    im = hero_of(m)
    if im and im.get("use_as_portrait", True):
        return f'<img class="portrait" src="{photo_url(im["file"], 500)}" alt="" style="object-position:{e(im.get("focus", "50% 25%"))}" loading="lazy" decoding="async">'
    return f'<div class="portrait" aria-hidden="true">{e(initials(m["name"]))}</div>'


def mem_card(m):
    return f"""<article class="card">
 {portrait(m)}
 <div class="body">
  <div class="meta"><span class="place">{e(m['country'])}</span><span class="dates">{e(year(m['born']))}–{e(year(m['died']))}</span></div>
  <h3><a href="/legacy/{m['slug']}/">{e(m['name'])}</a></h3>
  <p>{e(m['summary'])}</p>
 </div>
</article>"""


def sources_list(sources):
    items = []
    for i, src in enumerate(sources):
        bits = [f'<a href="{e(src["url"])}" rel="noopener">{e(src["title"])}</a>' if src.get("url") else e(src["title"])]
        by = ", ".join(x for x in [src.get("author"), src.get("publisher"), fmt_date(src.get("date"))] if x)
        items.append(f'<li id="src-{i + 1}"><span class="src-type">{e(src.get("type", "").replace("-", " "))}</span><br>{bits[0]}'
                     f'{f" — {e(by)}" if by else ""}<span class="claim">Supports: {e(src.get("claim", ""))}</span></li>')
    return f'<ol>{"".join(items)}</ol>'


def sdg_list(sdgs):
    if not sdgs:
        return '<p class="muted">No SDG label: we only add goals that clearly fit.</p>'
    return '<ul class="chips">' + "".join(f'<li class="chip sdg"><b>{n}</b>{e(SDGS[str(n)])}</li>' for n in sdgs) + "</ul>"


def write(path, content):
    is_file = "." in path.rstrip("/").split("/")[-1]
    fp = os.path.join(OUT, path.strip("/")) if is_file else os.path.join(OUT, path.strip("/"), "index.html")
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(content)
    if path.endswith("/") or "." not in path.split("/")[-1]:
        PAGES.append(path)


PAGES = []
TOPIC_COUNTS = Counter(t for s in STORIES for t in s["topics"])
COUNTRY_STORIES = defaultdict(list)
for s in STORIES:
    COUNTRY_STORIES[s["country"]].append(s)
PROBLEM_STORIES = defaultdict(list)
for s in STORIES:
    PROBLEM_STORIES[s["problem"]].append(s)


def pick(items, offset=0):
    return items[(WEEK + offset) % len(items)] if items else None


def head(eyebrow, title, lede="", crumbs=None):
    bc = ""
    if crumbs:
        bc = '<nav class="breadcrumb" aria-label="Breadcrumb">' + " / ".join(f'<a href="{u}">{e(t)}</a>' for u, t in crumbs) + "</nav>"
    return f'<div class="wrap story-head">{bc}<span class="eyebrow">{e(eyebrow)}</span><h1>{e(title)}</h1>{f"<p class=lede>{e(lede)}</p>" if lede else ""}</div>'


def stats():
    return {
        "stories": len(STORIES),
        "countries": len({s["country"] for s in STORIES}),
        "communities": len({(s["city"], s["country"]) for s in STORIES}),
        "people": len({s["person"] for s in STORIES}),
        "actions": len({t for s in STORIES for t in s["topics"]}),
        "copy": sum(1 for s in STORIES if s.get("copy_this")),
        "memorials": len(LEGACY),
        "defenders": sum(1 for m in LEGACY if m["category"] == "defender"),
        "footprints": sum(1 for m in LEGACY if m["category"] == "footprint"),
    }


ST = stats()


def worldmap(include_memorials=True):
    def xy(lat, lng):
        return (lng + 180) / 360 * 1000, (84 - lat) / 144 * 420
    pts = []
    for s in STORIES:
        x, y = xy(s["lat"], s["lng"])
        pts.append(f'<a href="/stories/{s["slug"]}/"><title>{e(s["person"])} — {e(place(s))}</title><circle class="dot" cx="{x:.0f}" cy="{y:.0f}" r="7"/></a>')
    if include_memorials:
        for m in LEGACY:
            x, y = xy(m["lat"], m["lng"])
            pts.append(f'<a href="/legacy/{m["slug"]}/"><title>{e(m["name"])} (remembered) — {e(m["country"])}</title><circle class="dot memorial" cx="{x:.0f}" cy="{y:.0f}" r="5.5"/></a>')
    return f"""<div class="worldmap"><div class="land" aria-hidden="true"></div>
<svg class="dots" viewBox="0 0 1000 420" role="group" aria-label="Map of {len(STORIES)} stories and {len(LEGACY)} legacy profiles. Each point is a link.">{"".join(pts)}</svg></div>
<div class="map-legend"><span>Active story</span>{"<span class=m>Legacy profile</span>" if include_memorials else ""}<a href="/map/">Open the interactive map</a><a href="/stories/">Prefer a list? See all stories</a></div>"""


# ---------- pages ----------
def page_home():
    small = [s for s in STORIES if s["pillar"] == "small-things"] or STORIES
    feat = pick(small)
    copy = pick([s for s in STORIES if s.get("copy_this") and s is not feat], 3)
    foot = pick([m for m in LEGACY if m["category"] == "footprint"])
    setback = pick([s for s in STORIES if s.get("setbacks")], 5)
    prob, plist = max(PROBLEM_STORIES.items(), key=lambda kv: (len({s["country"] for s in kv[1]}), len(kv[1])))
    q = feat.get("quote") or {}
    quote_html = ""
    if q.get("text"):
        src = feat["sources"][q.get("source", 0)] if feat["sources"] else {}
        quote_html = f'<blockquote>“{e(q["text"])}”<cite>{e(q.get("speaker") or feat["person"])}, quoted by {e(src.get("publisher", ""))}</cite></blockquote>'
    body = f"""
<section class="hero"><div class="wrap">
 <span class="eyebrow">A living archive of grassroots action</span>
 <h1>Small actions. <em>Real people.</em> A better world.</h1>
 <p class="lede">Around the world, ordinary people are doing extraordinary things for the places they call home. We find them, listen to them, check what they did, and show you how to try it too.</p>
 <div class="cta-row"><a class="btn" href="/stories/">Explore stories</a><a class="btn ghost" href="/submit/">Tell your story</a></div>
 <div class="hero-stats" aria-label="Archive so far">
  <div><b>{ST['stories']}</b>stories</div><div><b>{ST['countries']}</b>countries</div><div><b>{ST['memorials']}</b>lives remembered</div><div><b>{ST['copy']}</b>ideas to copy</div>
 </div>
</div></section>

<section class="block"><div class="wrap">
 <div class="block-head"><div><span class="eyebrow">The world is speaking</span><h2>Every point is a person, a place, a start</h2></div><p>Tap a point to read the story. Every story on the map is also in the <a href="/stories/">full list</a>.</p></div>
 {worldmap()}
</div></section>

<section class="block"><div class="wrap feature">
 <a href="/stories/{feat['slug']}/" class="art" tabindex="-1" aria-hidden="true">{card_visual(feat, feat['problem'])}</a>
 <div>
  <span class="eyebrow">This week's small thing</span>
  <h2><a href="/stories/{feat['slug']}/" style="color:inherit;text-decoration:none">{e(feat['title'])}</a></h2>
  <div class="meta" style="margin-bottom:12px"><span class="place">{e(place(feat))}</span>{ev_badge(feat['evidence'])}</div>
  <p>{e(feat['small_thing'])}</p>
  {quote_html}
  <a class="more" href="/stories/{feat['slug']}/">Meet {e(first_name(feat))} →</a>
 </div>
</div></section>

<section class="block"><div class="wrap">
 <div class="copy">
  <span class="eyebrow">Copy this</span>
  <h2>{e(copy['copy_this']['what'][:1].upper() + copy['copy_this']['what'][1:120].rstrip('. ') + ('…' if len(copy['copy_this']['what']) > 120 else ''))}</h2>
  <div class="pill-row"><span class="pill"><b>Difficulty</b>{e(copy['copy_this']['difficulty'])}</span><span class="pill"><b>Cost</b>{e(copy['copy_this']['cost'])}</span><span class="pill"><b>Inspired by</b>{e(copy['person'])}, {e(copy['country'])}</span></div>
  <p class="narrow">{e(copy['copy_this']['problem'])}</p>
  <a class="btn" href="/stories/{copy['slug']}/#copy-this">Learn how to try it</a> <a class="more" href="/copy-this/" style="margin-left:12px">All ideas to copy →</a>
 </div>
</div></section>

<div class="memorial-zone"><section class="block" style="border-top:0"><div class="wrap feature">
 <div>
  <span class="eyebrow">They left a footprint</span>
  <h2>{e(foot['name'])}</h2>
  <p class="dates">{e(fmt_date(foot['born']))} – {e(fmt_date(foot['died']))} · {e(foot['country'])}</p>
  <p class="lede">{e(foot['summary'])}</p>
  <a class="btn ghost" href="/legacy/{foot['slug']}/">The footprint {e(foot['name'].split()[0])} left</a> <a class="more" href="/legacy/" style="margin-left:12px">Legacy archive →</a>
 </div>
 <p style="font:italic 500 1.5rem/1.4 var(--serif);color:var(--candle);margin:0">Some footprints disappear in the sand. Others change the direction of history.</p>
</div></section></div>

<section class="block"><div class="wrap">
 <div class="block-head"><div><span class="eyebrow">One problem. Many solutions.</span><h2>{e(PROBLEMS[prob]['label'])}</h2></div><p>{e(PROBLEMS[prob]['q'])} {len(plist)} stories from {len({s['country'] for s in plist})} countries.</p></div>
 <div class="grid">{"".join(story_card(s) for s in plist[:3])}</div>
 <p style="margin-top:20px"><a class="more" href="/solutions/{prob}/">Compare all {len(plist)} approaches →</a> · <a class="more" href="/solutions/">Browse all problems</a></p>
</div></section>

<section class="block"><div class="wrap feature">
 <div><span class="eyebrow">What didn't work?</span><h2>Failure is evidence too</h2>
 <p class="lede">From <a href="/stories/{setback['slug']}/">{e(setback['person'])}</a> in {e(setback['country'])}:</p></div>
 <div class="note" style="font-size:1rem">{e(setback['setbacks'])}<p style="margin:10px 0 0"><a class="more" href="/what-didnt-work/">More lessons from setbacks →</a></p></div>
</div></section>

<section class="block"><div class="wrap">
 <div class="block-head"><div><span class="eyebrow">Our global archive</span><h2>From one person to a global movement</h2></div><p>Counted automatically from published stories. <a href="/1000-small-things/">Follow the 1,000 Small Things Project</a>.</p></div>
 <div class="stats">
  <div class="stat"><b>{ST['stories']}</b><span>stories published</span></div>
  <div class="stat"><b>{ST['countries']}</b><span>countries</span></div>
  <div class="stat"><b>{ST['communities']}</b><span>towns and communities</span></div>
  <div class="stat"><b>{ST['actions']}</b><span>kinds of action</span></div>
 </div>
</div></section>

<section class="block"><div class="wrap">
 <div class="block-head"><div><span class="eyebrow">For researchers and policymakers</span><h2>The missing evidence on community action</h2></div>
 <p>Global sustainability data rarely sees what households, farmers, fishers and neighbourhoods actually do. This archive makes it searchable, citable and open.</p></div>
 <div class="grid">
  <a class="problem" href="/insights/"><h3>Insights</h3><p style="margin:0">What {ST['stories']} documented actions show about scale, cost, setbacks and gaps.</p></a>
  <a class="problem" href="/data/"><h3>Open data</h3><p style="margin:0">Download the archive as CSV or JSON under CC BY 4.0.</p></a>
  <a class="problem" href="/methodology/"><h3>Methodology</h3><p style="margin:0">Inclusion rules, evidence levels, classification and limitations.</p></a>
  <a class="problem" href="/for-institutions/"><h3>For institutions</h3><p style="margin:0">How governments, UN agencies and NGOs can use and contribute.</p></a>
 </div>
</div></section>

<section class="block" style="background:var(--paper-2)"><div class="wrap narrow" style="text-align:center">
 <span class="eyebrow">Join the movement</span>
 <h2>Are you doing something small to make your community better?</h2>
 <p class="lede" style="margin:0 auto 1.4em">We want to hear from you. No action is too small, and you never have to invent numbers.</p>
 <a class="btn" href="/submit/">Tell your story</a>
</div></section>"""
    ld = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE["name"], "url": BASE + "/",
          "description": SITE["tagline"],
          "potentialAction": {"@type": "SearchAction", "target": BASE + "/search/?q={q}", "query-input": "required name=q"}}
    write("/", layout("/", SITE["name"], "A living global archive of grassroots sustainability: real people, small actions, sourced stories and ideas you can copy.", body, jsonld=ld))


def page_story(s):
    ct = s.get("copy_this") or {}
    q = s.get("quote") or {}
    quote_html = ""
    if q.get("text"):
        idx = q.get("source", 0)
        src = s["sources"][idx] if idx < len(s["sources"]) else {}
        quote_html = f'<blockquote>“{e(q["text"])}”<cite>{e(q.get("speaker") or s["person"])}, as quoted by <a href="#src-{idx + 1}">{e(src.get("publisher", "source"))}</a></cite></blockquote>'
    copy_html = ""
    if ct:
        rows = [("Problem addressed", ct.get("problem")), ("What to do", ct.get("what")), ("Materials and resources", ct.get("materials")),
                ("Approximate cost", ct.get("cost")), ("Skills", ct.get("skills")), ("Time", ct.get("time")), ("People needed", ct.get("people")),
                ("Difficulty", ct.get("difficulty")), ("Risks and limitations", ct.get("risks")), ("How to adapt it", ct.get("adapt")), ("Lessons learned", ct.get("lessons"))]
        copy_html = f"""<section id="copy-this" class="copy"><h2>Copy this idea</h2>
<p class="muted" style="font-size:.9rem">Practical guidance written by our editors from the sources below. Adapt it to your place, and check local rules and safety first.</p>
<dl class="copy-grid">{"".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in rows if v)}</dl></section>"""
    related = [x for x in STORIES if x is not s and (x["problem"] == s["problem"] or set(x["topics"]) & set(s["topics"]))]
    related.sort(key=lambda x: (x["problem"] != s["problem"], -len(set(x["topics"]) & set(s["topics"]))))
    body = f"""
<article>
<div class="wrap story-head">
 <nav class="breadcrumb" aria-label="Breadcrumb"><a href="/stories/">Stories</a> / <a href="/stories/{slugify(s['country'])}/">{e(s['country'])}</a></nav>
 <span class="eyebrow">Meet {e(first_name(s))} · {e(place(s))}</span>
 <h1>{e(s['title'])}</h1>
 <p class="lede">{e(s['summary'])}</p>
 <div class="meta" style="margin-top:14px">{ev_badge(s['evidence'])}<span>{e(PROBLEMS[s['problem']]['label'])}</span><span>{"Ongoing" if s['status'] == "ongoing" else "Completed"} · since {e(s['started_year'])}</span></div>
 {figure(hero_of(s), "photo hero", "(max-width: 1180px) 100vw, 1150px", True) if hero_of(s) else '<div class="story-art">' + art(s['slug'], s['problem'], "Decorative contour drawing for this story") + '</div>'}
</div>
<div class="wrap story-layout">
 <div class="story-body">
  <section class="small-thing"><h2>The small thing</h2><p>{e(s['small_thing'])}</p></section>
  <section><h2>The problem</h2>{paras(s['problem_text'])}</section>
  <section><h2>Why {e(first_name(s))} started</h2>{paras(s['why_started'])}</section>
  <section><h2>What they did</h2>{paras(s['what_they_did'])}</section>
  <section><h2>What changed</h2>{paras(s['what_changed'])}{"".join(figure(i) for i in s.get("images", []) if i.get("role") == "inline")}</section>
  <section><h2>What they learned</h2>{paras(s['what_they_learned'])}{quote_html}</section>
  {copy_html}
  <section style="margin-top:34px"><h2>Why it matters</h2><div class="why">{paras(s['why_it_matters'])}</div></section>
  {frameworks_html(s['problem'])}
  {f'<section id="setbacks"><h2>What didn\'t work</h2>{paras(s["setbacks"])}</section>' if s.get("setbacks") else ""}
  {f'<section><h2>Editor\'s note</h2><p class="note">{e(s["status_note"])}</p></section>' if s.get("status_note") else ""}
  <section class="sources" id="sources"><h2>Sources: how do we know?</h2>
   <p class="note"><strong>Evidence level: {e(EVID[s['evidence']]['label'])}.</strong> {e(EVID[s['evidence']]['text'])} What the person says and what independent sources establish are attributed separately in the text.</p>
   {sources_list(s['sources'])}
   <p><a href="/corrections/?page=/stories/{s['slug']}/">Report an error or update on this story</a></p>
  </section>
 </div>
 <aside>
  <div class="sticky">
   <div class="aside-box"><h3>At a glance</h3><dl>
    <dt>Who</dt><dd>{e(s['person'])}</dd><dt>Role</dt><dd>{e(s['occupation'])}</dd>
    <dt>Where</dt><dd>{e(place(s))}</dd><dt>Since</dt><dd>{e(s['started_year'])}</dd>
    <dt>Scale</dt><dd>{e(s['scale'].title())}</dd><dt>Type</dt><dd>{e(s['actor_type'].title())}</dd></dl></div>
   <div class="aside-box"><h3>Sustainability connection</h3>{topic_chips(s['topics'])}</div>
   <div class="aside-box"><h3>Sustainable Development Goals</h3>{sdg_list(s.get('sdgs', []))}</div>
   {cite_box(s['title'], BASE + '/stories/' + s['slug'] + '/')}
   <div class="aside-box"><h3>Share</h3><p style="margin:0">
    <a href="https://www.linkedin.com/sharing/share-offsite/?url={BASE}/stories/{s['slug']}/" rel="noopener">LinkedIn</a> ·
    <a href="https://www.facebook.com/sharer/sharer.php?u={BASE}/stories/{s['slug']}/" rel="noopener">Facebook</a> ·
    <a href="https://x.com/intent/post?url={BASE}/stories/{s['slug']}/" rel="noopener">X</a> ·
    <a href="https://wa.me/?text={BASE}/stories/{s['slug']}/" rel="noopener">WhatsApp</a></p></div>
  </div>
 </aside>
</div>
</article>
<section class="block"><div class="wrap"><div class="block-head"><div><span class="eyebrow">Related</span><h2>Similar actions elsewhere</h2></div></div>
<div class="grid">{"".join(story_card(x) for x in related[:3])}</div></div></section>"""
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": s["title"], "description": s["summary"],
          "url": f"{BASE}/stories/{s['slug']}/", "image": BASE + "/assets/og.png",
          "datePublished": s.get("published", "2026-10-08"), "dateModified": s.get("updated", s.get("published", "2026-10-08")),
          "publisher": {"@type": "Organization", "name": SITE["name"], "url": BASE + "/"},
          "about": {"@type": "Person" if s["actor_type"] == "individual" else "Organization", "name": s["person"]},
          "contentLocation": {"@type": "Place", "name": place(s), "address": {"@type": "PostalAddress", "addressLocality": s["city"], "addressCountry": s["country_code"]},
                              "geo": {"@type": "GeoCoordinates", "latitude": s["lat"], "longitude": s["lng"]}},
          "keywords": ", ".join(TOPICS.get(t, t) for t in s["topics"]),
          "citation": [x.get("url") for x in s["sources"] if x.get("url")]}
    hi = hero_of(s)
    if hi:
        ld["image"] = (BASE if photo_url(hi["file"], 1280).startswith("/") else "") + photo_url(hi["file"], 1280)
    write(f"/stories/{s['slug']}/", layout(f"/stories/{s['slug']}/", s["title"], s["summary"], body, jsonld=ld, og_type="article", og_image=photo_url(hi["file"], 1280) if hi else None))


def filter_bar(items):
    countries = sorted({s["country"] for s in items})
    topics = sorted({t for s in items for t in s["topics"]}, key=lambda t: TOPICS.get(t, t))
    probs = sorted({s["problem"] for s in items}, key=lambda p: PROBLEMS[p]["label"])
    regions = sorted({s["region"] for s in items})
    sdg = sorted({n for s in items for n in s.get("sdgs", [])})

    def sel(name, label, opts):
        return f'<label>{label}<select name="{name}"><option value="">All</option>{"".join(f"<option value={chr(34)}{e(v)}{chr(34)}>{e(t)}</option>" for v, t in opts)}</select></label>'
    return f"""<form class="filters" data-filter-for=".story-card" role="search" aria-label="Filter stories">
 {sel("region", "Region", [(r, r) for r in regions])}
 {sel("country", "Country", [(slugify(c), c) for c in countries])}
 {sel("problem", "Problem", [(p, PROBLEMS[p]["label"]) for p in probs])}
 {sel("topics", "Topic", [(t, TOPICS.get(t, t)) for t in topics])}
 {sel("sdgs", "SDG", [(str(n), f"SDG {n}: {SDGS[str(n)]}") for n in sdg])}
 {sel("pillar", "Type of story", [("small-things", "Small things"), ("people-making-change", "People making change")])}
 {sel("scale", "Scale", [(x, x.title()) for x in ["household", "neighbourhood", "community", "city", "regional", "national", "international"] if any(s["scale"] == x for s in items)])}
 {sel("evidence", "Evidence", [(k, v["label"]) for k, v in EVID.items() if any(s["evidence"] == k for s in items)])}
 <p class="count" aria-live="polite"><span data-count>{len(items)}</span> stories shown <button type="reset" class="reset">Clear filters</button></p>
</form>"""


def page_stories():
    body = head("Stories", "Stories of people making a difference",
                "Real people, real places, and sources for every claim. Filter by country, problem or topic, or browse them all.")
    body += f'<div class="wrap" style="padding-bottom:72px">{filter_bar(STORIES)}<div class="grid">{"".join(story_card(s) for s in STORIES)}</div>'
    body += '<p class="empty" data-empty hidden>No stories match these filters yet. <a href="/submit/">Know one? Tell us.</a></p>'
    body += '<h2 style="margin-top:48px;font-size:1.3rem">Browse by country</h2><ul class="chips">' + "".join(f'<li><a class="chip" href="/stories/{slugify(c)}/">{e(c)} ({len(v)})</a></li>' for c, v in sorted(COUNTRY_STORIES.items()))
    body += '</ul><h2 style="margin-top:28px;font-size:1.3rem">Browse by topic</h2><ul class="chips">' + "".join(f'<li><a class="chip" href="/stories/{t}/">{e(TOPICS[t])} ({n})</a></li>' for t, n in sorted(TOPIC_COUNTS.items(), key=lambda kv: TOPICS.get(kv[0], kv[0])) if t in TOPICS)
    body += "</ul></div>"
    write("/stories/", layout("/stories/", "Stories", "Browse sourced stories of grassroots sustainability action from around the world.", body, scripts=["/assets/filters.js"]))
    for c, items in COUNTRY_STORIES.items():
        p = f"/stories/{slugify(c)}/"
        b = head("Stories from " + c, f"Sustainability stories from {c}", f"{len(items)} sourced {'story' if len(items) == 1 else 'stories'} of people taking action in {c}.", [("/stories/", "Stories")])
        b += f'<div class="wrap" style="padding-bottom:72px"><div class="grid">{"".join(story_card(s) for s in items)}</div><p style="margin-top:28px">Know someone in {e(c)} who should be here? <a href="/submit/">Tell us their story</a>.</p></div>'
        write(p, layout(p, f"Stories from {c}", f"Grassroots sustainability stories from {c}, with sources.", b))
    for t, n in TOPIC_COUNTS.items():
        if t not in TOPICS:
            continue
        items = [s for s in STORIES if t in s["topics"]]
        p = f"/stories/{t}/"
        b = head("Topic", TOPICS[t], f"{n} {'story' if n == 1 else 'stories'} tagged {TOPICS[t].lower()}.", [("/stories/", "Stories")])
        b += f'<div class="wrap" style="padding-bottom:72px"><div class="grid">{"".join(story_card(s) for s in items)}</div></div>'
        write(p, layout(p, f"{TOPICS[t]} stories", f"Grassroots {TOPICS[t].lower()} stories from around the world, with sources.", b))


def page_people():
    rows = "".join(f'<tr><td><a href="/stories/{s["slug"]}/">{e(s["person"])}</a></td><td>{e(s["occupation"])}</td><td>{e(place(s))}</td><td>{e(PROBLEMS[s["problem"]]["label"])}</td></tr>' for s in sorted(STORIES, key=lambda s: s["person"]))
    mrows = "".join(f'<tr><td><a href="/legacy/{m["slug"]}/">{e(m["name"])}</a></td><td>{e(m["occupation"])}</td><td>{e(m["country"])}</td><td>{year(m["born"])}–{year(m["died"])}</td></tr>' for m in sorted(LEGACY, key=lambda m: m["name"]))
    body = head("People", "The people behind the stories", "Farmers, students, lawyers, mothers, engineers, waste pickers, beekeepers. Sustainability belongs to everyone.")
    body += f"""<div class="wrap" style="padding-bottom:72px">
<h2>Making change now</h2><div class="table-wrap"><table><caption class="sr-only">People featured in active stories</caption><thead><tr><th scope="col">Person or group</th><th scope="col">Role</th><th scope="col">Place</th><th scope="col">Problem</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2 style="margin-top:48px">Remembered</h2><div class="table-wrap"><table><caption class="sr-only">People remembered in the Legacy archive</caption><thead><tr><th scope="col">Name</th><th scope="col">Work</th><th scope="col">Country</th><th scope="col">Life</th></tr></thead><tbody>{mrows}</tbody></table></div></div>"""
    write("/people/", layout("/people/", "People", "The people and groups featured in We Speak Sustainability's stories and Legacy archive.", body))


def page_copy():
    items = [s for s in STORIES if s.get("copy_this")]
    order = {"Easy": 0, "Moderate": 1, "Hard": 2}
    items.sort(key=lambda s: (order.get(s["copy_this"].get("difficulty"), 3), s["title"]))
    cards = "".join(f"""<article class="card story-card" data-difficulty="{e(s['copy_this'].get('difficulty'))}"><div class="body">
<div class="meta"><span class="place">{e(place(s))}</span></div>
<h3><a href="/stories/{s['slug']}/#copy-this">{e(s['copy_this']['what'][:110].rstrip('. ') + ('…' if len(s['copy_this']['what']) > 110 else ''))}</a></h3>
<p>{e(s['copy_this'].get('problem', ''))}</p>
<div class="pill-row" style="margin-top:auto"><span class="pill"><b>Difficulty</b>{e(s['copy_this'].get('difficulty'))}</span><span class="pill"><b>Cost</b>{e(s['copy_this'].get('cost'))}</span></div>
<p class="muted" style="font-size:.85rem">Inspired by {e(s['person'])}</p></div></article>""" for s in items)
    body = head("Copy This", "Don't just read the story. Try the idea.",
                "Every idea here comes from a real story. Each one lists what you need, what it costs, the risks, and how to adapt it to your own place.")
    body += f'<div class="wrap" style="padding-bottom:72px"><p class="note narrow">Ideas are sorted from easiest to hardest. Costs are rough guides (very low to high), not prices.</p><div class="grid" style="margin-top:20px">{cards}</div></div>'
    write("/copy-this/", layout("/copy-this/", "Copy This", "Practical, replicable sustainability ideas drawn from real grassroots stories.", body))


def page_solutions():
    blocks = []
    for p, info in sorted(PROBLEMS.items(), key=lambda kv: -len(PROBLEM_STORIES.get(kv[0], []))):
        items = PROBLEM_STORIES.get(p, [])
        countries = sorted({s["country"] for s in items})
        blocks.append(f'<a class="problem" href="/solutions/{p}/"><h3>{e(info["label"])}</h3><p style="margin:0">{e(info["q"])}</p>'
                      f'<div class="n">{len(items)} {"story" if len(items) == 1 else "stories"}</div>'
                      f'{f"<div class=flags>{e(", ".join(countries))}</div>" if countries else "<div class=flags>No stories yet. Could yours be the first?</div>"}</a>')
        b = head("One problem. Many solutions.", info["label"], info["q"], [("/solutions/", "Solutions")])
        if items:
            rows = "".join(f'<tr><td><a href="/stories/{s["slug"]}/">{e(s["person"])}</a></td><td>{e(place(s))}</td><td>{e(s["small_thing"])}</td><td>{e(s["scale"].title())}</td><td>{ev_badge(s["evidence"])}</td></tr>' for s in items)
            b += f"""<div class="wrap" style="padding-bottom:72px">
<p class="narrow">Different communities face the same problem and find different answers, shaped by their own resources, knowledge and context. No approach here is presented as the right one for everywhere.</p>
<h2 style="font-size:1.3rem;margin-top:28px">Side by side</h2>
<div class="table-wrap"><table><caption class="sr-only">Approaches to {e(info['label'])}</caption><thead><tr><th scope="col">Who</th><th scope="col">Where</th><th scope="col">How it started</th><th scope="col">Scale</th><th scope="col">Evidence</th></tr></thead><tbody>{rows}</tbody></table></div>
<div class="grid" style="margin-top:32px">{"".join(story_card(s) for s in items)}</div>
<p style="margin-top:28px"><strong>What can they learn from one another?</strong> Read the "Copy this" section of each story to compare materials, costs and risks.</p>
<div class="narrow story-body" style="margin-top:28px">{frameworks_html(p)}</div></div>"""
        else:
            b += '<div class="wrap" style="padding-bottom:72px"><p class="empty">No stories on this problem yet. <a href="/submit/">If you are working on it, tell us your story.</a></p></div>'
        write(f"/solutions/{p}/", layout(f"/solutions/{p}/", f"{info['label']}: many solutions", f"How people in different countries are tackling {info['label'].lower()}.", b))
    body = head("One problem. Many solutions.", "Same problem, different answers",
                "Communities around the world face similar problems and solve them in different ways. Compare approaches across countries.")
    body += f'<div class="wrap" style="padding-bottom:72px"><div class="problems">{"".join(blocks)}</div></div>'
    write("/solutions/", layout("/solutions/", "One problem, many solutions", "Grassroots sustainability solutions grouped by the problem they tackle.", body))


def mem_page(m):
    is_def = m["category"] == "defender"
    death = ""
    if is_def:
        death = f"""<section><h2>CIRCUMSTANCES</h2><div><p><span class="mem-label">{e(m.get('death_label', ''))}</span></p>{paras(m.get('death_note'))}
<p class="muted" style="font-size:.88rem">We use careful labels for deaths connected with environmental defence. <a href="/editorial-policy/#memorials">How we classify them</a>.</p></div></section>"""
    tl = "".join(f'<li><b>{e(t["year"])}</b>{e(t["event"])}</li>' for t in m.get("timeline", []))
    section = ("/environmental-defenders/", "Environmental defenders") if is_def else ("/footprints/", "They left a footprint")
    body = f"""
<article>
<div class="wrap story-head">
 <nav class="breadcrumb" aria-label="Breadcrumb"><a href="/legacy/">Legacy</a> / <a href="{section[0]}">{section[1]}</a></nav>
 <div style="display:flex;gap:22px;align-items:center;flex-wrap:wrap">
  {portrait(m, True)}
  <div><span class="eyebrow">{"Remembering an environmental defender" if is_def else "The footprint they left"}</span>
  <h1 style="margin:0">{e(m['name'])}</h1>
  <p class="dates" style="margin:.3em 0 0">{e(fmt_date(m['born']))} – {e(fmt_date(m['died']))} · {e(m['place'])}, {e(m['country'])}</p></div>
 </div>
 <p class="lede" style="margin-top:22px">{e(m['summary'])}</p>
 {figure(hero_of(m), "photo mem-photo", "(max-width: 760px) 100vw, 720px") if hero_of(m) else ""}
</div>
<div class="wrap story-layout">
 <div class="lwe">
  <section><h2>LIFE</h2><div>{paras(m['life'])}</div></section>
  <section><h2>WORK</h2><div>{paras(m['work'])}</div></section>
  <section><h2>EARTH</h2><div><p>{e(m['earth'])}</p></div></section>
  <section><h2>IMPACT</h2><div>{paras(m['impact'])}</div></section>
  {death}
  <section><h2>LEGACY</h2><div>{paras(m['legacy'])}</div></section>
  {f'<section><h2>TIMELINE</h2><div><ol class="timeline">{tl}</ol></div></section>' if tl else ""}
  <section class="sources" id="sources"><h2>SOURCES</h2><div>{sources_list(m['sources'])}
   <p><a href="/corrections/?page=/legacy/{m['slug']}/">Report an error in this profile</a></p></div></section>
 </div>
 <aside><div class="sticky">
  <div class="aside-box"><h3>Life</h3><dl><dt>Born</dt><dd>{e(fmt_date(m['born']))}</dd><dt>Died</dt><dd>{e(fmt_date(m['died']))}</dd><dt>Country</dt><dd>{e(m['country'])}</dd><dt>Work</dt><dd>{e(m['occupation'])}</dd></dl></div>
  {cite_box(m['name'], BASE + '/legacy/' + m['slug'] + '/', 'profile')}
  <div class="aside-box"><h3>Connected topics</h3><ul class="chips">{"".join(f'<li><span class="chip">{e(TOPICS.get(t, t))}</span></li>' for t in m.get('topics', []) if t in TOPICS)}</ul></div>
 </div></aside>
</div>
</article>"""
    ld = {"@context": "https://schema.org", "@type": "Person", "name": m["name"], "birthDate": m["born"], "deathDate": m["died"],
          "nationality": m["country"], "jobTitle": m["occupation"], "description": m["summary"], "url": f"{BASE}/legacy/{m['slug']}/"}
    hi = hero_of(m)
    if hi:
        ld["image"] = (BASE if photo_url(hi["file"], 1280).startswith("/") else "") + photo_url(hi["file"], 1280)
    write(f"/legacy/{m['slug']}/", layout(f"/legacy/{m['slug']}/", f"{m['name']} ({year(m['born'])}–{year(m['died'])})", m["summary"], body, jsonld=ld, og_type="profile", zone="memorial-zone", og_image=photo_url(hi["file"], 1280) if hi else None))


def page_legacy():
    defs = [m for m in LEGACY if m["category"] == "defender"]
    foots = [m for m in LEGACY if m["category"] == "footprint"]
    for m in LEGACY:
        mem_page(m)
    body = f"""<div class="wrap story-head"><span class="eyebrow">Legacy</span><h1>They left a footprint</h1>
<p class="lede">Remembering those whose lives changed our relationship with Earth. This is a place for remembrance and learning, not celebrity: every profile asks what each person left behind, and how we know.</p>
<p style="font:italic 500 1.3rem/1.4 var(--serif);color:var(--candle);max-width:36rem">Some footprints disappear in the sand. Others change the direction of history.</p></div>
<section class="block"><div class="wrap"><div class="block-head"><div><span class="eyebrow">Environmental defenders</span><h2>Those who lost their lives defending people, places and the living world</h2></div><p><a href="/environmental-defenders/">About this section and how we label deaths →</a></p></div>
<div class="grid">{"".join(mem_card(m) for m in defs)}</div></div></section>
<section class="block"><div class="wrap"><div class="block-head"><div><span class="eyebrow">Those who left their footprint</span><h2>Lives whose work still shapes how we understand and protect Earth</h2></div><p><a href="/footprints/">See all footprints →</a></p></div>
<div class="grid">{"".join(mem_card(m) for m in foots)}</div></div></section>
<section class="block"><div class="wrap narrow"><h2>How we research these profiles</h2><p>Every profile uses at least three sources, including at least one from an institution such as a UN body, an award foundation or a government archive. We separate what courts have established from what is alleged. If you knew one of these people, or can correct a detail, <a href="/corrections/">please tell us</a>.</p>
<p>Know someone whose environmental legacy should be remembered? <a href="/submit/">Suggest a profile</a>.</p></div></section>"""
    write("/legacy/", layout("/legacy/", "Legacy: they left a footprint", "A respectful, sourced memorial archive of environmental defenders and people whose work changed our relationship with Earth.", body, zone="memorial-zone"))
    labels = ["Confirmed killing", "Alleged killing", "Death during environmental conflict", "Death while engaged in environmental defence", "Cause of death disputed", "Circumstances under investigation", "Executed by the state"]
    b = f"""<div class="wrap story-head"><nav class="breadcrumb"><a href="/legacy/">Legacy</a></nav><span class="eyebrow">Environmental defenders</span><h1>Remembering those who lost their lives defending people, places and the living world</h1>
<p class="lede">These profiles honour people who died in connection with defending land, forests, rivers, communities and environmental justice. We do not sensationalise their deaths, and we only state what reliable sources establish.</p></div>
<div class="wrap" style="padding-bottom:40px"><div class="grid">{"".join(mem_card(m) for m in defs)}</div></div>
<section class="block"><div class="wrap narrow" id="labels"><h2>How we describe how someone died</h2><p>Each profile carries exactly one label, chosen from what the sources support, with legal outcomes described in the text:</p>
<ul>{"".join(f"<li><strong>{e(l)}</strong></li>" for l in labels)}</ul>
<p>We never say someone was "killed for environmental activism" unless reliable sources substantiate it. Labels are reviewed when new court rulings or investigations are published.</p>
<h2>The protections that exist</h2><ul>{"".join(f"<li><strong>{e(a)}</strong>: {e(b)}</li>" for a, b in DEFENDER_FRAMEWORKS)}</ul></div></section>"""
    write("/environmental-defenders/", layout("/environmental-defenders/", "Environmental defenders", "Respectful, sourced profiles of environmental defenders who lost their lives, with careful labels for how they died.", b, zone="memorial-zone"))
    b = f"""<div class="wrap story-head"><nav class="breadcrumb"><a href="/legacy/">Legacy</a></nav><span class="eyebrow">Those who left their footprint</span><h1>What did they leave behind?</h1>
<p class="lede">People who died of natural or other causes, whose science, teaching, farming, writing or organising still influences how humanity understands and protects Earth.</p></div>
<div class="wrap" style="padding-bottom:72px"><div class="grid">{"".join(mem_card(m) for m in foots)}</div></div>"""
    write("/footprints/", layout("/footprints/", "They left a footprint", "Sourced memorial profiles of people whose environmental legacy endures.", b, zone="memorial-zone"))


def page_map():
    rows = "".join(f'<tr data-kind="story"><td><a href="/stories/{s["slug"]}/">{e(s["person"])}</a></td><td>{e(s["city"])}</td><td>{e(s["country"])}</td><td>{e(s["region"])}</td><td>{e(PROBLEMS[s["problem"]]["label"])}</td><td>{e(s["started_year"])}</td><td>{e(EVID[s["evidence"]]["label"])}</td></tr>' for s in sorted(STORIES, key=lambda s: (s["region"], s["country"])))
    rows += "".join(f'<tr data-kind="memorial"><td><a href="/legacy/{m["slug"]}/">{e(m["name"])}</a> (remembered)</td><td>{e(m["place"])}</td><td>{e(m["country"])}</td><td>{e(m["region"])}</td><td>{e(m["earth"])}</td><td>{year(m["born"])}–{year(m["died"])}</td><td>Legacy profile</td></tr>' for m in LEGACY)
    regions = sorted({s["region"] for s in STORIES} | {m["region"] for m in LEGACY})
    probs = sorted({s["problem"] for s in STORIES}, key=lambda p: PROBLEMS[p]["label"])
    topics = sorted({t for s in STORIES for t in s["topics"]}, key=lambda t: TOPICS.get(t, t))
    sdg = sorted({n for s in STORIES for n in s.get("sdgs", [])})

    def opts(pairs):
        return '<option value="">All</option>' + "".join(f'<option value="{e(v)}">{e(t)}</option>' for v, t in pairs)
    body = head("The world is speaking", "World map of small actions", "Every point is a person or group taking action, or a life we remember. Use the filters, or skip to the table below. The map is never the only way in.")
    body += f"""<div class="wrap" style="padding-bottom:72px">
<form class="filters" id="map-filters" aria-label="Filter the map">
 <label>Show<select name="kind"><option value="">Stories and legacy</option><option value="story">Active stories</option><option value="memorial">Legacy profiles</option></select></label>
 <label>Region<select name="region">{opts([(r, r) for r in regions])}</select></label>
 <label>Problem<select name="problem">{opts([(p, PROBLEMS[p]["label"]) for p in probs])}</select></label>
 <label>Topic<select name="topic">{opts([(t, TOPICS.get(t, t)) for t in topics])}</select></label>
 <label>SDG<select name="sdg">{opts([(str(n), f"SDG {n}") for n in sdg])}</select></label>
 <label>Status<select name="status">{opts([("ongoing", "Ongoing"), ("completed", "Completed")])}</select></label>
 <p class="count" aria-live="polite"><span data-count></span> <a href="#map-table">Skip to table</a></p>
</form>
<div id="map" role="region" aria-label="Interactive map. A table with the same information follows.">{worldmap()}</div>
<h2 id="map-table" style="margin-top:40px;font-size:1.4rem">All locations as a table</h2>
<div class="table-wrap"><table><caption class="sr-only">Every story and legacy profile with its location</caption><thead><tr><th scope="col">Who</th><th scope="col">Town or place</th><th scope="col">Country</th><th scope="col">Region</th><th scope="col">Issue</th><th scope="col">Year</th><th scope="col">Evidence</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted" style="margin-top:12px;font-size:.88rem">Locations are shown at town or regional level only, never homes or sensitive sites.</p></div>"""
    head_extra = ('<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">'
                  '<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">'
                  '<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">')
    write("/map/", layout("/map/", "World map", "An interactive world map of grassroots sustainability stories and legacy profiles, with an accessible table.", body,
                          head_extra=head_extra, scripts=["https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", "https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js", "/assets/map.js"]))
    data = [{"k": "story", "n": s["person"], "t": s["title"], "u": f"/stories/{s['slug']}/", "p": place(s), "la": s["lat"], "lo": s["lng"], "r": s["region"],
             "pr": s["problem"], "pl": PROBLEMS[s["problem"]]["label"], "tp": s["topics"], "sd": s.get("sdgs", []), "st": s["status"], "s": s["summary"], "ev": EVID[s["evidence"]]["label"]} for s in STORIES]
    data += [{"k": "memorial", "n": m["name"], "t": f"{year(m['born'])}–{year(m['died'])}", "u": f"/legacy/{m['slug']}/", "p": f"{m['place']}, {m['country']}",
              "la": m["lat"], "lo": m["lng"], "r": m["region"], "pr": "", "pl": m["earth"], "tp": m.get("topics", []), "sd": m.get("sdgs", []), "st": "", "s": m["summary"], "ev": "Legacy profile"} for m in LEGACY]
    write("/map-data.json", json.dumps(data, ensure_ascii=False))


def page_search():
    idx = [{"k": "Story", "t": s["title"], "u": f"/stories/{s['slug']}/", "s": s["summary"], "p": place(s),
            "x": " ".join([s["person"], s["city"], s["country"], s["region"], s["occupation"], PROBLEMS[s["problem"]]["label"], s["small_thing"],
                           " ".join(TOPICS.get(t, t) for t in s["topics"]), (s.get("copy_this") or {}).get("what", "")])} for s in STORIES]
    idx += [{"k": "Defender" if m["category"] == "defender" else "Footprint", "t": m["name"], "u": f"/legacy/{m['slug']}/", "s": m["summary"], "p": m["country"],
             "x": " ".join([m["place"], m["country"], m["occupation"], m["earth"], " ".join(TOPICS.get(t, t) for t in m.get("topics", []))])} for m in LEGACY]
    idx += [{"k": "Solutions", "t": v["label"], "u": f"/solutions/{k}/", "s": v["q"], "p": "", "x": k.replace("-", " ")} for k, v in PROBLEMS.items() if PROBLEM_STORIES.get(k)]
    idx += [{"k": "Topic", "t": TOPICS[t], "u": f"/stories/{t}/", "s": f"{n} stories", "p": "", "x": t.replace("-", " ")} for t, n in TOPIC_COUNTS.items() if t in TOPICS]
    idx += [{"k": "Country", "t": c, "u": f"/stories/{slugify(c)}/", "s": f"{len(v)} stories", "p": "", "x": c} for c, v in COUNTRY_STORIES.items()]
    write("/search-index.json", json.dumps(idx, ensure_ascii=False))
    body = head("Search", "Search the archive", "People, places, problems, practices and memorial profiles. Try “composting”, “plastic”, “Kenya” or “water”.")
    body += """<div class="wrap narrow" style="padding-bottom:72px">
<form class="search-box" action="/search/" role="search"><label for="q" class="sr-only">Search</label><input type="search" id="q" name="q" placeholder="Search stories, people, places…" autocomplete="off"><button class="btn" type="submit">Search</button></form>
<p class="muted" aria-live="polite" id="search-status" style="margin-top:14px"></p><div id="results"></div>
<noscript><p>Search needs JavaScript. You can still <a href="/stories/">browse all stories</a> or <a href="/people/">all people</a>.</p></noscript></div>"""
    write("/search/", layout("/search/", "Search", "Search grassroots sustainability stories, people, places and memorial profiles.", body, scripts=["/assets/search.js"]))


def tally_embed(form_id, title):
    if not form_id:
        return ""
    return (f'<div class="form-embed"><iframe data-tally-src="https://tally.so/embed/{e(form_id)}?alignLeft=1&hideTitle=1&transparentBackground=1&dynamicHeight=1" '
            f'loading="lazy" title="{e(title)}"></iframe></div><script async src="https://tally.so/widgets/embed.js"></script>'
            f'<p class="muted" style="font-size:.88rem;margin-top:10px">Form not loading? <a href="https://tally.so/r/{e(form_id)}">Open it in a new page</a>.</p>')


def page_submit():
    form = tally_embed(SITE.get("tally_story_form"), "Tell your story form")
    if not form:
        form = '<p class="note">Our story form is being set up. In the meantime you can read the questions below and prepare your answers.</p>'
    qs = ["What are you doing?", "When did you start?", "What problem were you trying to solve?", "Why did you start?", "How did you begin?",
          "Who helped you?", "What has happened since?", "What have you learned?", "What would you tell someone who wants to try this?"]
    body = head("Tell your story", "Are you doing something small to make your community, environment or future better?", "We want to hear from you. It takes about 10 minutes on a phone.")
    body += f"""<div class="wrap narrow" style="padding-bottom:72px">
<div class="note" style="margin-bottom:24px"><strong>Before you start:</strong> nothing is published automatically. An editor reads every story, may contact you with questions, and checks what we can before publishing. You choose how your name appears: full name, first name only, or anonymous. If numbers like waste diverted or trees planted have not been measured, just say "unknown". We never want you to guess.</div>
{form}
<h2 style="margin-top:40px;font-size:1.4rem">What we'll ask</h2>
<ol class="qlist">{"".join(f"<li>{e(q)}</li>" for q in qs)}</ol>
<p>We also ask where you are (country, region and town, never your exact address), any impact you have measured, and photos, videos or links if you have them. Only send photos you took or have permission to share.</p>
<h2 style="font-size:1.4rem">What happens next</h2>
<ol><li>Submitted</li><li>Initial review</li><li>We check facts and may ask for evidence or a short interview</li><li>Approved and published with an evidence label</li></ol>
<p>Read our <a href="/editorial-policy/">editorial &amp; verification policy</a> and how we protect contributors' privacy.</p></div>"""
    write("/submit/", layout("/submit/", "Tell your story", "Share your sustainability action, however small. Every submission is reviewed by an editor before publication.", body))


def page_1000():
    pct = ST["stories"] / SITE["goal"] * 100
    by_region = Counter(s["region"] for s in STORIES)
    by_problem = Counter(PROBLEMS[s["problem"]]["label"] for s in STORIES)
    mx = max(by_problem.values())

    def bars(c, m):
        return '<div class="bars">' + "".join(f'<div class="bar"><span>{e(k)}</span><i style="width:{v / m * 100:.0f}%" aria-hidden="true"></i><b>{v}</b></div>' for k, v in c.most_common()) + "</div>"
    body = head("The 1,000 Small Things Project", "1,000 people. 1,000 places. 1,000 things.", "Our mission is to document 1,000 people, in 1,000 places, doing things that make the world more sustainable. Here is how far we have come.")
    body += f"""<div class="wrap" style="padding-bottom:72px">
<p style="font:600 clamp(2.4rem,7vw,4rem)/1 var(--serif);margin:0">{ST['stories']} <span class="muted" style="font-size:.5em">/ {SITE['goal']:,} stories</span></p>
<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="{SITE['goal']}" aria-valuenow="{ST['stories']}" aria-label="Stories documented" style="margin:18px 0 28px"><span style="width:{max(pct, 1):.1f}%"></span></div>
<div class="stats">
 <div class="stat"><b>{ST['countries']}</b><span>countries</span></div><div class="stat"><b>{ST['communities']}</b><span>towns and communities</span></div>
 <div class="stat"><b>{ST['people']}</b><span>people and groups featured</span></div><div class="stat"><b>{ST['actions']}</b><span>kinds of action</span></div>
 <div class="stat"><b>{ST['copy']}</b><span>ideas to copy</span></div><div class="stat"><b>{ST['memorials']}</b><span>lives remembered</span></div>
</div>
<div class="story-layout" style="padding-top:40px">
 <div><h2 style="font-size:1.4rem">Stories by problem</h2>{bars(by_problem, mx)}</div>
 <div><h2 style="font-size:1.4rem">Stories by region</h2>{bars(by_region, max(by_region.values()))}</div>
</div>
<p class="note">These numbers update automatically every time a story is approved and published. They count stories, not environmental impact: we only report impact where a source has measured it.</p>
<h2 style="margin-top:36px">Help us reach 1,000</h2><p>Do something small? Know someone who does? <a href="/submit/">Tell us the story</a>.</p></div>"""
    write("/1000-small-things/", layout("/1000-small-things/", "The 1,000 Small Things Project", "Documenting 1,000 people, in 1,000 places, doing 1,000 things that make the world more sustainable.", body))


def page_failures():
    items = [s for s in STORIES if s.get("setbacks")]
    cards = "".join(f'<article class="result"><span class="kind">{e(place(s))}</span><h3><a href="/stories/{s["slug"]}/#setbacks">{e(s["title"])}</a></h3><p>{e(s["setbacks"])}</p></article>' for s in items)
    body = head("What didn't work?", "Failure is evidence too", "Setbacks, abandoned approaches and unexpected consequences, documented in the sources behind our stories. Useful for anyone trying something similar.")
    body += f'<div class="wrap narrow" style="padding-bottom:72px">{cards}<p style="margin-top:28px">Tried something that didn\'t work? Your lessons can save someone else months. <a href="/submit/">Share what you learned</a>.</p></div>'
    write("/what-didnt-work/", layout("/what-didnt-work/", "What didn't work?", "Lessons from setbacks and failures in grassroots sustainability action.", body))


def page_about():
    body = head("About", "Sustainability belongs to everyone", "")
    body += """<div class="wrap narrow prose" style="padding-bottom:72px">
<p class="lede">We Speak Sustainability is a living global archive of grassroots action. We discover, document and share the stories of people making the world more sustainable through large and very small actions, and we remember those whose work changed our relationship with Earth.</p>
<h2>What we believe</h2>
<p>We do not believe that only spectacular actions deserve attention. Humanity's ability to build a sustainable future is also hidden in ordinary acts repeated by ordinary people. Our job is to find those acts, listen to the people behind them, document what they have learned, and make their experience visible to the world.</p>
<p>So we don't only ask how much impact someone has made. We ask <strong>what they started</strong>.</p>
<h2>Who we look for</h2>
<p>Farmers, students, teachers, children and young people, parents, fishers, waste pickers, mechanics, shopkeepers, engineers, scientists, Indigenous and community knowledge holders, artists, gardeners, organisers, informal workers, volunteers, neighbours, families. Sustainability is not only something professionals do.</p>
<h2>How a story becomes part of the archive</h2>
<ol><li><strong>Discover.</strong> Someone submits a story, or our editors find one.</li><li><strong>Listen.</strong> We read, ask questions and interview where we can.</li><li><strong>Check.</strong> We look for independent evidence and label every story with its <a href="/editorial-policy/#evidence">evidence level</a>.</li><li><strong>Share.</strong> We publish the story with its sources and, where it fits, a practical <a href="/copy-this/">Copy This</a> guide.</li></ol>
<h2>What we hope you feel</h2>
<p><strong>Inspired:</strong> “I didn't know people were doing this.” <strong>Capable:</strong> “I could do something like this.” <strong>Connected:</strong> “I'm not the only one trying.”</p>
<h2>Images</h2>
<p>We only publish photographs we have permission to use. Photos currently come from Wikimedia Commons under free licences or the public domain, and each one is credited with its photographer, licence and source. We never use stock images of people who are not in the story. Where no freely licensed photo exists, the story is shown with its own contour drawing until the people in it share their own.</p>
<h2>Contact</h2>
<p>To share a story, use <a href="/submit/">Tell your story</a>. To correct something, use <a href="/corrections/">Report a correction</a>.</p>
</div>"""
    write("/about/", layout("/about/", "About", "Why We Speak Sustainability exists and how stories become part of the archive.", body))


def page_policy():
    ev = "".join(f'<li>{ev_badge(k)} {e(v["text"])}</li>' for k, v in EVID.items())
    body = head("Policy", "Editorial & verification policy", "How we choose, check, label and correct what we publish.")
    body += f"""<div class="wrap narrow prose" style="padding-bottom:72px">
<h2 id="selection">How stories are selected</h2><p>We look for real actions by real people, with priority for those who are often overlooked. Scale is not the test: a household project can matter as much as a large programme if it shows meaningful action, learning, participation or a replicable idea. We aim for diversity of geography, age, gender, occupation, income and issue.</p>
<h2 id="evidence">Evidence levels</h2><ul style="list-style:none;padding:0">{ev}</ul>
<p>We never manufacture verification. Within each story we separate what the person says from what independent sources establish, and we attribute numbers to whoever measured them. Where sources disagree (for example on a start date), we say so in an editor's note.</p>
<h2 id="fact-checking">How facts are checked</h2><p>Every published story lists its sources with the publisher, date and the specific claim each one supports. Stories need at least two sources independent of the person or their organisation. We avoid relying on unsourced social media posts for serious claims.</p>
<h2 id="workflow">Editorial workflow</h2><p>Submissions are never published automatically. Each moves through: submitted → initial review → verification required → interview requested → fact-checking → approved → published → updated → archived. Editors flag unsupported claims, missing evidence, safety issues, potential defamation, political claims, environmental misinformation, copyright and privacy concerns.</p>
<h2 id="memorials">Memorial profiles</h2><p>Legacy profiles use at least three sources, including at least one institutional source. For environmental defenders who died, we use exactly one label: confirmed killing; alleged killing; death during environmental conflict; death while engaged in environmental defence; cause of death disputed; circumstances under investigation; or executed by the state. We describe court outcomes precisely and never imply causation beyond what sources show.</p>
<h2 id="anonymity">Anonymity, privacy and safety</h2><p>Contributors can publish under their full name, first name only, or anonymously. We take extra care with activists, environmental defenders, Indigenous communities, children, land disputes and corporate conflicts. We never publish precise locations where that could create a risk; the map shows town or regional level only. Contributor contact details are never published.</p>
<h2 id="greenwashing">Anti-greenwashing policy</h2><p>We are not a promotional channel. If we publish a story involving a business, we separate marketing claims from verified facts, identify any sponsorship or conflict of interest, avoid unsupported “eco-friendly” or “carbon neutral” claims, and ask for evidence.</p>
<h2 id="sponsorship">Sponsorship and conflicts of interest</h2><p>We currently publish no sponsored content. If that changes, sponsored material will be clearly labelled. Editors declare any personal connection to a story and step back from editing it.</p>
<h2 id="images">Images and copyright</h2><p>We do not scrape or republish photographs without permission. For every image we record the photographer, copyright holder, licence, permission status and attribution.</p>
<h2 id="corrections">Corrections</h2><p>Anyone can <a href="/corrections/">report an error</a>. We review reports promptly, correct the story, and add a dated note describing what changed.</p>
</div>"""
    write("/editorial-policy/", layout("/editorial-policy/", "Editorial & verification policy", "How We Speak Sustainability selects, verifies, labels and corrects stories, and protects contributors.", body))


def page_corrections():
    form = tally_embed(SITE.get("tally_correction_form"), "Report a correction form")
    body = head("Corrections", "Report a correction", "Accuracy matters to us. If something in a story or profile is wrong, out of date or missing, please tell us.")
    body += f"""<div class="wrap narrow" style="padding-bottom:72px">
{form or f'<p>Open a correction request on our public <a href="{SITE["repo_url"]}/issues/new?title=Correction%3A%20&labels=correction">corrections tracker</a> (free GitHub account needed). Include the page address, what is wrong, and a source if you have one.</p>'}
<h2 style="font-size:1.3rem;margin-top:32px">What happens next</h2><p>An editor reviews every report. If we change a story, we add a dated editor's note explaining the correction. See our <a href="/editorial-policy/#corrections">corrections policy</a>.</p></div>"""
    write("/corrections/", layout("/corrections/", "Report a correction", "Tell us about an error in a We Speak Sustainability story or profile.", body))


def page_404():
    body = head("Not found", "This page has wandered off", "It may have moved. Try searching, or start from the stories.")
    body += '<div class="wrap" style="padding-bottom:72px"><a class="btn" href="/stories/">Explore stories</a> <a class="btn ghost" href="/search/">Search</a></div>'
    with open(os.path.join(OUT, "404.html"), "w", encoding="utf-8") as f:
        f.write(layout("/404.html", "Page not found", "Page not found.", body))


def extras():
    urls = "".join(f"<url><loc>{BASE}{p}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>" for p in PAGES)
    write("/sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    write("/robots.txt", f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n")
    with open(os.path.join(OUT, "CNAME"), "w") as f:
        f.write(BASE.split("//")[1] + "\n")
    # Open dataset (no private contributor data): Phase 3 research use.
    ds = [{"id": s["slug"], "country": s["country"], "location": s["city"], "region": s["region"], "topics": s["topics"], "problem": s["problem"],
           "started": s["started_year"], "scale": s["scale"], "actor_type": s["actor_type"], "evidence": s["evidence"], "sdgs": s.get("sdgs", []),
           "url": f"{BASE}/stories/{s['slug']}/"} for s in STORIES]
    write("/data/stories.json", json.dumps(ds, ensure_ascii=False, indent=1))


# ---------- institutional & research layer ----------
FRAMEWORKS = {
    "plastic-waste": [("SDG 12.5", "Substantially reduce waste generation through prevention, reduction, recycling and reuse."),
                      ("SDG 14.1", "Prevent and significantly reduce marine pollution of all kinds."),
                      ("UNEA Resolution 5/14 (2022)", "Launched negotiations on an international legally binding instrument on plastic pollution.")],
    "food-waste": [("SDG 12.3", "Halve per capita global food waste at the retail and consumer levels and reduce food losses.")],
    "water-scarcity": [("SDG 6.1 and 6.4", "Safe and affordable drinking water for all; increase water-use efficiency and address scarcity."),
                       ("Paris Agreement, Article 7", "Enhancing adaptive capacity, strengthening resilience and reducing vulnerability to climate change.")],
    "deforestation": [("SDG 15.2", "Halt deforestation, restore degraded forests and increase afforestation and reforestation."),
                      ("Kunming-Montreal Global Biodiversity Framework, Targets 2 and 3", "Restore at least 30% of degraded ecosystems and conserve 30% of land and sea by 2030.")],
    "biodiversity-loss": [("Kunming-Montreal Global Biodiversity Framework, Targets 2, 3 and 22", "Restoration, area-based conservation, and full participation of Indigenous peoples and local communities, including protection of environmental human rights defenders."),
                          ("SDG 14 and SDG 15", "Life below water and life on land.")],
    "soil-degradation": [("SDG 15.3", "Combat desertification, restore degraded land and soil, and strive for a land-degradation-neutral world."),
                         ("UNCCD Land Degradation Neutrality", "The framework countries use to set voluntary land restoration targets.")],
    "air-pollution": [("SDG 3.9 and 11.6", "Reduce deaths and illnesses from air pollution; reduce the environmental impact of cities, including air quality.")],
    "energy": [("SDG 7.1 and 7.2", "Universal access to affordable, reliable and modern energy; increase the share of renewable energy.")],
    "agricultural-waste": [("SDG 12.5", "Reduce waste through prevention, reduction, recycling and reuse.")],
    "ocean-pollution": [("SDG 14.1", "Prevent and significantly reduce marine pollution of all kinds.")],
    "fast-fashion": [("SDG 12", "Sustainable consumption and production patterns.")],
    "urban-waste": [("SDG 11.6 and 12.5", "Improve municipal waste management; reduce waste through prevention, recycling and reuse."),
                    ("SDG 8.3", "Support decent job creation, including formalisation of informal work.")],
    "climate-adaptation": [("Paris Agreement, Article 7", "The global goal on adaptation: enhancing adaptive capacity and resilience."),
                           ("SDG 13.1", "Strengthen resilience and adaptive capacity to climate-related hazards and natural disasters.")],
}
DEFENDER_FRAMEWORKS = [("Escazú Agreement, Article 9", "Latin America and the Caribbean's regional treaty obliging states to guarantee a safe environment for human rights defenders in environmental matters."),
                       ("Kunming-Montreal Global Biodiversity Framework, Target 22", "Includes full protection for environmental human rights defenders."),
                       ("UN Declaration on Human Rights Defenders (1998)", "Recognises everyone's right to promote and strive for the protection of human rights; the UN applies it to environmental human rights defenders.")]

FOUNDER = {
    "name": "Shagbaor Hycent Amool",
    "role": "Founder and editor",
    "bio": [
        "Shagbaor Hycent Amool is an environmental engineer and doctoral researcher in Environmental Engineering at the University of Northern British Columbia (UNBC), Canada. His research studies aerobic granular sludge treating brewery wastewater, and whether valuable biopolymers such as curdlan can be recovered from it, turning a waste stream into a resource.",
        "He holds an MSc in Global Sustainability Engineering (Distinction) from Heriot-Watt University, UK, funded by a Petroleum Technology Development Fund (PTDF) Overseas Scholarship, and a first-class BEng in Agricultural and Environmental Engineering from the University of Agriculture Makurdi (now Joseph Sarwuan Tarka University Makurdi), Nigeria.",
        "He is a Lecturer at the Federal Polytechnic Wannune, Nigeria (on study leave), where he has taught agricultural technology, sustainable design and engineering materials, and the founder of Via Scholaris, an online learning platform. He is a member of the Council for the Regulation of Engineering in Nigeria (COREN), the Nigerian Society of Engineers and the International Association of Engineers.",
        "He started We Speak Sustainability because the people doing the most practical sustainability work are often the least visible in the evidence that shapes policy.",
    ],
    "topics": [
        ("What grassroots action can teach climate and development policy", "Evidence from the archive on what communities actually do, what it costs, and what makes ideas travel."),
        ("Replication, not just inspiration", "How small, documented actions can be adapted across countries, and what gets lost when they are scaled carelessly."),
        ("Remembering environmental defenders responsibly", "How to document lives lost in environmental defence with care, evidence and respect."),
        ("Wastewater as a resource", "Circular-economy engineering: recovering value from industrial wastewater."),
    ],
}


def cite_box(title, url, kind="story"):
    yr = TODAY.year
    return (f'<div class="aside-box cite"><h3>Cite this {kind}</h3>'
            f'<p style="margin:0;font-size:.88rem">We Speak Sustainability ({yr}). <em>{e(title)}</em>. {e(url)} (accessed {TODAY.day} {MONTHS[TODAY.month - 1]} {yr}).</p>'
            f'<p style="margin:.6em 0 0"><button type="button" class="linkbtn" data-copy="We Speak Sustainability ({yr}). {e(title)}. {e(url)}">Copy citation</button> · '
            f'<button type="button" class="linkbtn" data-print>Print or save as PDF</button></p></div>')


def frameworks_html(problem):
    fw = FRAMEWORKS.get(problem, [])
    if not fw:
        return ""
    items = "".join(f"<li><strong>{e(a)}</strong>: {e(b)}</li>" for a, b in fw)
    return (f'<section class="policy"><h2>Policy connection</h2><p class="muted" style="font-size:.9rem">International commitments this kind of action contributes to. '
            f'Listing a framework does not mean the person or group was working towards it.</p><ul>{items}</ul></section>')


def page_data():
    import csv
    import io
    cols = ["id", "title", "person_or_group", "actor_type", "country", "country_code", "region", "location", "latitude", "longitude",
            "started_year", "status", "scale", "pillar", "problem", "topics", "sdgs", "evidence_level", "copy_this_difficulty",
            "copy_this_cost", "has_documented_setbacks", "number_of_sources", "url"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for s in STORIES:
        ct = s.get("copy_this") or {}
        w.writerow([s["slug"], s["title"], s["person"], s["actor_type"], s["country"], s["country_code"], s["region"], s["city"], s["lat"], s["lng"],
                    s["started_year"], s["status"], s["scale"], s["pillar"], s["problem"], ";".join(s["topics"]), ";".join(str(x) for x in s.get("sdgs", [])),
                    s["evidence"], ct.get("difficulty", ""), ct.get("cost", ""), "yes" if s.get("setbacks") else "no", len(s["sources"]), f"{BASE}/stories/{s['slug']}/"])
    write("/data/stories.csv", buf.getvalue())
    mbuf = io.StringIO()
    mw = csv.writer(mbuf)
    mw.writerow(["id", "name", "category", "country", "born", "died", "death_label", "issue", "number_of_sources", "url"])
    for m in LEGACY:
        mw.writerow([m["slug"], m["name"], m["category"], m["country"], m["born"], m["died"], m.get("death_label", ""), m["earth"], len(m["sources"]), f"{BASE}/legacy/{m['slug']}/"])
    write("/data/legacy.csv", mbuf.getvalue())
    dictionary = [("id", "Permanent identifier, also the page address"), ("actor_type", "individual, group, community or organisation"),
                  ("location", "Town or community; never a home address"), ("latitude / longitude", "Town centre, rounded to two decimals for safety"),
                  ("started_year", "Year the action began, from sources (conflicts explained on the story page)"), ("scale", "household to international"),
                  ("problem", "One of 13 problems in our taxonomy"), ("topics", "Semicolon-separated tags from a controlled list of 33 topics"),
                  ("sdgs", "Only goals that clearly apply"), ("evidence_level", "verified, documented, self-reported or insufficient (see methodology)"),
                  ("copy_this_difficulty / cost", "Editorial judgement for someone replicating the idea; cost is qualitative"),
                  ("has_documented_setbacks", "Whether sources describe something that did not work"), ("number_of_sources", "Count of cited sources")]
    rows = "".join(f"<tr><th scope=row>{e(a)}</th><td>{e(b)}</td></tr>" for a, b in dictionary)
    body = head("Open data", "The archive as open data",
                "Every published story and profile, as structured data you can download, analyse and reuse. No private contributor information is ever included.")
    body += f"""<div class="wrap narrow prose" style="padding-bottom:72px">
<div class="stats" style="margin-bottom:28px"><div class="stat"><b>{ST['stories']}</b><span>stories</span></div><div class="stat"><b>{ST['countries']}</b><span>countries</span></div><div class="stat"><b>{ST['memorials']}</b><span>legacy profiles</span></div><div class="stat"><b>{sum(len(s['sources']) for s in STORIES) + sum(len(m['sources']) for m in LEGACY)}</b><span>cited sources</span></div></div>
<h2>Download</h2>
<ul class="downloads">
<li><a class="btn" href="/data/stories.csv" download>Stories (CSV)</a> <a class="btn ghost" href="/data/stories.json">Stories (JSON)</a></li>
<li><a class="btn ghost" href="/data/legacy.csv" download>Legacy profiles (CSV)</a> <a class="btn ghost" href="/map-data.json">Map points (JSON)</a></li>
</ul>
<p class="muted">Version {TODAY.isoformat()}. Updated automatically whenever a story is published or corrected.</p>
<h2>Licence and citation</h2>
<p>Our written summaries and the dataset are released under <a href="https://creativecommons.org/licenses/by/4.0/" rel="license">Creative Commons Attribution 4.0 (CC BY 4.0)</a>. Photographs keep their own licences, shown under each image. Please cite:</p>
<p class="note">Amool, S. H. (ed.) ({TODAY.year}). <em>We Speak Sustainability: a living archive of grassroots sustainability action</em> [Dataset, version {TODAY.isoformat()}]. {BASE}/data/</p>
<h2>Data dictionary</h2>
<div class="table-wrap"><table><caption class="sr-only">Fields in the stories dataset</caption><tbody>{rows}</tbody></table></div>
<h2>Limitations</h2>
<ul><li>The archive is small and not a random sample. It reflects what has been documented in reliable sources, which over-represents award winners and English-language coverage.</li>
<li>Impact figures are not included as fields, because most are self-reported or measured in incompatible ways. They are attributed in each story's text.</li>
<li>Coordinates are deliberately imprecise.</li></ul>
<p>Read the full <a href="/methodology/">methodology</a> or see what the data shows so far in <a href="/insights/">Insights</a>.</p>
</div>"""
    ld = {"@context": "https://schema.org", "@type": "Dataset", "name": "We Speak Sustainability: grassroots sustainability action archive",
          "description": "Structured records of documented grassroots sustainability actions worldwide, with location, problem, topics, SDGs, evidence level and replication attributes.",
          "url": f"{BASE}/data/", "license": "https://creativecommons.org/licenses/by/4.0/", "version": TODAY.isoformat(),
          "creator": {"@type": "Person", "name": FOUNDER["name"]}, "spatialCoverage": "Global",
          "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": f"{BASE}/data/stories.csv"},
                           {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": f"{BASE}/data/stories.json"}]}
    write("/data/", layout("/data/", "Open data", "Download the We Speak Sustainability archive as open data (CSV and JSON, CC BY 4.0).", body, jsonld=ld))


def page_methodology():
    body = head("Methodology", "How the archive is built",
                "A transparent account of what we include, how we check it, and how we classify it, so researchers and institutions can judge how far to rely on it.")
    body += f"""<div class="wrap narrow prose" style="padding-bottom:72px">
<h2>1. What counts as a story</h2>
<p>A story documents a real action, by identifiable people or a community, that addresses an environmental or sustainability problem in a specific place. We prioritise actions that began small, that are led by people outside large institutions, and that others could adapt. Scale is never the main test.</p>
<h2>2. Sources and evidence</h2>
<p>Each story needs at least two sources independent of the people involved: UN agencies, award foundations, government bodies, peer-reviewed research or reputable journalism. Organisations' own materials may be used, but claims drawn from them are attributed. Every source is listed with the specific claim it supports. Legacy profiles need at least three sources, including one institutional source.</p>
<h2>3. Evidence levels</h2>
<ul>{"".join(f"<li><strong>{e(v['label'])}</strong>: {e(v['text'])}</li>" for v in EVID.values())}</ul>
<p>At launch, stories are rated <em>Documented</em> or <em>Self-reported</em>. <em>Verified</em> is reserved for stories our editors have checked directly, usually through an interview and supporting evidence.</p>
<h2>4. Handling numbers</h2>
<p>We never estimate or aggregate environmental impact. Figures appear only when a source states them, with that source named. Where sources disagree, we give each figure and its source, and explain the conflict in an editor's note.</p>
<h2>5. Classification</h2>
<ul><li><strong>Problems:</strong> 13 recurring problems (for example plastic waste, water, soil degradation) so similar actions can be compared across countries.</li>
<li><strong>Topics:</strong> a controlled list of {len(TOPICS)} topics; stories can carry several.</li>
<li><strong>SDGs:</strong> added only where the link is direct. We do not label every story with every plausible goal.</li>
<li><strong>Scale and actor type:</strong> household to international; individual, group, community or organisation.</li></ul>
<h2>6. Replication guidance</h2>
<p>"Copy this" sections are editorial guidance written from the sources: materials, skills, time, people, difficulty, qualitative cost, risks and how to adapt. They are a starting point, not engineering advice.</p>
<h2>7. Memorial profiles</h2>
<p>Deaths connected with environmental defence carry exactly one label: confirmed killing, alleged killing, death during environmental conflict, death while engaged in environmental defence, cause of death disputed, circumstances under investigation, or executed by the state. Court findings are separated from allegations.</p>
<h2>8. Safety and privacy</h2>
<p>Locations are shown at town level only. Contributors may be anonymous. We take extra care with defenders, Indigenous communities, children and land disputes.</p>
<h2>9. Known limitations</h2>
<ul><li>Coverage is shaped by what reliable sources have already reported, which favours English-language media and award winners.</li>
<li>Some stories rely on sources several years old; current status is noted where it could not be confirmed.</li>
<li>Classification involves editorial judgement. The full data is open so others can check and re-code it.</li></ul>
<h2>10. Corrections and versions</h2>
<p>Anyone can <a href="/corrections/">report an error</a>. Corrections are noted on the story with a date. The <a href="/data/">dataset</a> is versioned by date.</p>
</div>"""
    write("/methodology/", layout("/methodology/", "Methodology", "Inclusion criteria, evidence standards, classification and limitations of the We Speak Sustainability archive.", body))


def page_insights():
    n = len(STORIES)

    def table(counter, label, total=n):
        mx = max(counter.values()) if counter else 1
        rows = "".join(f'<div class="bar"><span>{e(k)}</span><i style="width:{v / mx * 100:.0f}%" aria-hidden="true"></i><b>{v}</b></div>' for k, v in counter.most_common())
        return f'<figure class="chart"><figcaption>{e(label)}</figcaption><div class="bars">{rows}</div></figure>'
    region = Counter(s["region"] for s in STORIES)
    problem = Counter(PROBLEMS[s["problem"]]["label"] for s in STORIES)
    scale = Counter(s["scale"].title() for s in STORIES)
    actor = Counter(s["actor_type"].title() for s in STORIES)
    decade = Counter(f"{(int(year(s['started_year'])) // 10) * 10}s" for s in STORIES if year(s["started_year"]).isdigit())
    diff = Counter((s.get("copy_this") or {}).get("difficulty", "n/a") for s in STORIES)
    cost = Counter((s.get("copy_this") or {}).get("cost", "n/a") for s in STORIES)
    setb = sum(1 for s in STORIES if s.get("setbacks"))
    low_cost = sum(1 for s in STORIES if (s.get("copy_this") or {}).get("cost") in ("Very low", "Low"))
    ongoing = sum(1 for s in STORIES if s["status"] == "ongoing")
    small = sum(1 for s in STORIES if s["scale"] in ("household", "neighbourhood", "community"))
    sdg = Counter(f"SDG {x}" for s in STORIES for x in s.get("sdgs", []))
    srcs = Counter(src.get("type", "other").replace("-", " ") for s in STORIES for src in s["sources"])
    pct = lambda k: f"{k / n * 100:.0f}%"
    body = head("Insights · working paper", "What the archive shows so far",
                f"A descriptive analysis of the {n} published stories. These are patterns in a small, curated collection, not global estimates. The numbers update automatically as the archive grows.")
    body += f"""<div class="wrap" style="padding-bottom:72px">
<div class="stats" style="margin-bottom:32px">
 <div class="stat"><b>{pct(small)}</b><span>operate at household, neighbourhood or community scale</span></div>
 <div class="stat"><b>{pct(low_cost)}</b><span>rated very low or low cost to replicate</span></div>
 <div class="stat"><b>{pct(setb)}</b><span>have documented setbacks</span></div>
 <div class="stat"><b>{ST['countries']}</b><span>countries represented</span></div>
</div>
<div class="narrow prose">
<h2>Key observations</h2>
<ol>
<li><strong>Small beginnings, varied reach.</strong> {small} of {n} actions still operate at household, neighbourhood or community scale. Many of the others grew to city, regional or wider scale from a small first step, described in "The small thing" on each story.</li>
<li><strong>Replication rarely needs capital.</strong> {low_cost} of {n} ideas are rated very low or low cost to copy. Reading the stories, the scarce inputs are more often time, organisation and local knowledge than money.</li>
<li><strong>Setbacks are the norm, and informative.</strong> Sources describe setbacks for {setb} of {n} stories: funding gaps, conflict, climate shocks, regulation and the difficulty of selling recycled products. These are collected in <a href="/what-didnt-work/">What didn't work?</a></li>
<li><strong>The evidence base is thin where action is thickest.</strong> Few stories in the archive report independently measured impact; most figures come from the people or organisations involved. Investment in simple, community-owned monitoring would make local action far more visible to policy.</li>
<li><strong>Coverage is uneven.</strong> Some regions and problems are barely represented, which says more about where reporting happens than where action happens. See the gaps below.</li>
</ol>
</div>
<div class="charts">
{table(region, "Stories by region")}
{table(problem, "Stories by problem")}
{table(scale, "Scale at which the action operates")}
{table(actor, "Who leads the action")}
{table(decade, "Decade the action began")}
{table(sdg, "SDGs directly linked (stories can have several)")}
{table(diff, "Difficulty to replicate (editorial rating)")}
{table(cost, "Cost to replicate (qualitative)")}
{table(srcs, "Types of sources cited")}
</div>
<div class="narrow prose">
<h2>Gaps we are working to fill</h2>
<p>Problems with no stories yet: {e(", ".join(PROBLEMS[p]["label"] for p in PROBLEMS if not PROBLEM_STORIES.get(p)) or "none")}. Under-represented: actions led by children, informal workers in Asia, and the Middle East and Central Asia. <a href="/submit/">Know a story that fills a gap?</a></p>
<h2>Method and data</h2>
<p>All figures are computed directly from the <a href="/data/">open dataset</a> using the rules in the <a href="/methodology/">methodology</a>. Cite as: Amool, S. H. (ed.) ({TODAY.year}). <em>What the archive shows so far</em>. We Speak Sustainability. {BASE}/insights/</p>
</div></div>"""
    write("/insights/", layout("/insights/", "Insights: what the archive shows", f"Descriptive analysis of {n} documented grassroots sustainability actions: scale, cost to replicate, setbacks and gaps.", body))


def page_founder():
    form = tally_embed(SITE.get("tally_talk_form"), "Request a talk or briefing")
    topics = "".join(f"<li><strong>{e(a)}</strong>: {e(b)}</li>" for a, b in FOUNDER["topics"])
    body = head("Founder", FOUNDER["name"], "Founder and editor of We Speak Sustainability. Environmental engineer and doctoral researcher.")
    body += f"""<div class="wrap narrow prose" style="padding-bottom:72px">
{"".join(f"<p>{e(p)}</p>" for p in FOUNDER["bio"])}
<h2 id="talks">Talks and briefings</h2>
<p>Shagbaor is available to speak with governments, international organisations, universities and community groups about what grassroots sustainability action can teach policy and practice. Possible topics:</p>
<ul>{topics}</ul>
<h2 id="contact">Request a talk, briefing or interview</h2>
{form or '<p class="note">The request form is being connected. Please check back shortly.</p>'}
</div>"""
    ld = {"@context": "https://schema.org", "@type": "Person", "name": FOUNDER["name"], "jobTitle": "Founder and editor, We Speak Sustainability",
          "affiliation": {"@type": "CollegeOrUniversity", "name": "University of Northern British Columbia"},
          "alumniOf": [{"@type": "CollegeOrUniversity", "name": "Heriot-Watt University"}, {"@type": "CollegeOrUniversity", "name": "University of Agriculture Makurdi"}],
          "url": f"{BASE}/founder/"}
    write("/founder/", layout("/founder/", f"{FOUNDER['name']}, founder", "About the founder of We Speak Sustainability, and how to request a talk or briefing.", body, jsonld=ld))


def page_institutions():
    body = head("For institutions", "Using the archive in policy, programmes and research",
                "For governments, UN agencies, development banks, NGOs, universities and journalists.")
    body += f"""<div class="wrap narrow prose" style="padding-bottom:72px">
<h2>The gap this fills</h2>
<p>Global sustainability evidence is dominated by national statistics, large projects and peer-reviewed studies. The actions of households, farmers, fishers, waste pickers and community groups are mostly missing, or appear only as anecdotes. Solution databases tend to feature organisations and funded projects; award programmes celebrate individuals but rarely explain how to replicate their work, or what failed.</p>
<p>We Speak Sustainability brings these together in one open, sourced and structured archive. Each action is classified by problem, topic, SDG, scale and evidence level, and comes with a replication guide and documented setbacks.</p>
<h2>How institutions can use it</h2>
<ul>
<li><strong>Case studies and country evidence:</strong> filter <a href="/stories/">stories</a> by country, problem or SDG for reports, voluntary national reviews and programme design.</li>
<li><strong>Locally led adaptation and community engagement:</strong> see how communities organise, what they need, and what has failed, in their own context.</li>
<li><strong>Open data:</strong> <a href="/data/">download the dataset</a> under CC BY 4.0 and combine it with your own.</li>
<li><strong>Teaching and training:</strong> each story is a ready-made, cited case with a one-page printable brief.</li>
</ul>
<h2>How to contribute</h2>
<ul>
<li><strong>Refer stories:</strong> field staff and partners can <a href="/submit/">submit community actions</a> they know of. We verify and credit them.</li>
<li><strong>Share evidence:</strong> if you hold monitoring data or evaluations for an action in the archive, help us move it from <em>Documented</em> to <em>Verified</em>.</li>
<li><strong>Correct us:</strong> <a href="/corrections/">report errors</a>; corrections are logged publicly.</li>
<li><strong>Invite us:</strong> to present findings, run a workshop or brief a delegation, <a href="/founder/#contact">get in touch</a>.</li>
</ul>
<h2>Standards</h2>
<p>Read our <a href="/methodology/">methodology</a>, <a href="/editorial-policy/">editorial and verification policy</a> and anti-greenwashing rules. We publish no sponsored content.</p>
</div>"""
    write("/for-institutions/", layout("/for-institutions/", "For institutions", "How governments, UN agencies, NGOs and researchers can use and contribute to the We Speak Sustainability archive.", body))


def validate():
    errs = []
    for s in ALL_STORIES:
        for k in ["slug", "title", "person", "country", "city", "lat", "lng", "problem", "summary", "small_thing", "sources", "evidence"]:
            if not s.get(k) and s.get(k) != 0:
                errs.append(f"story {s.get('slug')}: missing {k}")
        if s.get("problem") not in PROBLEMS:
            errs.append(f"story {s.get('slug')}: unknown problem {s.get('problem')}")
        if s.get("evidence") not in EVID:
            errs.append(f"story {s.get('slug')}: unknown evidence {s.get('evidence')}")
        if len(s.get("sources", [])) < 2:
            errs.append(f"story {s.get('slug')}: needs at least 2 sources")
    for m in ALL_LEGACY:
        if len(m.get("sources", [])) < 3:
            errs.append(f"legacy {m.get('slug')}: needs at least 3 sources")
        if m.get("category") == "defender" and not m.get("death_label"):
            errs.append(f"legacy {m.get('slug')}: defender needs death_label")
    slugs = [s["slug"] for s in ALL_STORIES]
    if len(slugs) != len(set(slugs)):
        errs.append("duplicate story slugs")
    if errs:
        raise SystemExit("Content errors:\n" + "\n".join(errs))


def main():
    validate()
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(OUT, "assets"))
    if os.environ.get("WSS_FETCH_PHOTOS") == "1":
        fetch_photos()
    page_home()
    page_stories()
    for s in STORIES:
        page_story(s)
    page_people()
    page_copy()
    page_solutions()
    page_legacy()
    page_map()
    page_search()
    page_submit()
    page_1000()
    page_failures()
    page_about()
    page_policy()
    page_corrections()
    page_404()
    page_data()
    page_methodology()
    page_insights()
    page_founder()
    page_institutions()
    extras()
    print(f"Built {len(PAGES)} pages: {len(STORIES)} stories, {len(LEGACY)} legacy profiles -> {OUT}")


if __name__ == "__main__":
    main()
