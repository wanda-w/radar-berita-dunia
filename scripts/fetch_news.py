#!/usr/bin/env python3
"""
Radar Berita Dunia - pengambil berita jalur gratis.

Sumber: RSS media resmi, RSS lembaga (WHO, GDACS), Google News RSS,
GDELT DOC API, dan Reddit RSS. Tidak butuh API key, hanya library standar Python.

Hasil ditulis ke folder output (default: _site/):
  data.json   -> dibaca dashboard
  state.json  -> status kumulatif (hash item yang sudah pernah diambil)

Pemakaian:
  python scripts/fetch_news.py                       # output ke _site/
  python scripts/fetch_news.py --prev-url https://user.github.io/repo/
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
WINDOW_HOURS = 48          # berita lebih tua dari ini dibuang
MAX_ITEMS = 900            # batas jumlah berita di dashboard
MAX_SEEN = 25000           # batas hash yang diingat untuk hitungan kumulatif
MAX_RUNS = 336             # riwayat update (336 x 30 menit = 7 hari)
UA = "Mozilla/5.0 (compatible; RadarBeritaDunia/1.0; open-source news dashboard)"
NOW = dt.datetime.now(dt.timezone.utc)


def gnews(query, lang="en"):
    loc = "hl=id&gl=ID&ceid=ID:id" if lang == "id" else "hl=en-US&gl=US&ceid=US:en"
    return f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&{loc}"


# type: media | lembaga | agregator | gdelt | reddit
# hint: topik default untuk semua item dari feed itu (opsional)
FEEDS = [
    # --- Media resmi ---
    dict(id="bbc-world", name="BBC World", outlet="BBC", type="media", url="https://feeds.bbci.co.uk/news/world/rss.xml"),
    dict(id="bbc-business", name="BBC Business", outlet="BBC", type="media", hint="ekonomi", url="https://feeds.bbci.co.uk/news/business/rss.xml"),
    dict(id="bbc-tech", name="BBC Technology", outlet="BBC", type="media", hint="teknologi", url="https://feeds.bbci.co.uk/news/technology/rss.xml"),
    dict(id="bbc-science", name="BBC Science & Environment", outlet="BBC", type="media", url="https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    dict(id="bbc-health", name="BBC Health", outlet="BBC", type="media", url="https://feeds.bbci.co.uk/news/health/rss.xml"),
    dict(id="aljazeera", name="Al Jazeera", type="media", url="https://www.aljazeera.com/xml/rss/all.xml"),
    dict(id="guardian-world", name="The Guardian World", outlet="The Guardian", type="media", url="https://www.theguardian.com/world/rss"),
    dict(id="guardian-business", name="The Guardian Business", outlet="The Guardian", type="media", hint="ekonomi", url="https://www.theguardian.com/uk/business/rss"),
    dict(id="guardian-tech", name="The Guardian Technology", outlet="The Guardian", type="media", hint="teknologi", url="https://www.theguardian.com/uk/technology/rss"),
    dict(id="guardian-env", name="The Guardian Environment", outlet="The Guardian", type="media", url="https://www.theguardian.com/environment/rss"),
    dict(id="dw", name="DW", type="media", url="https://rss.dw.com/rdf/rss-en-all"),
    dict(id="npr", name="NPR News", type="media", url="https://feeds.npr.org/1001/rss.xml"),
    dict(id="cnbc-top", name="CNBC Top News", outlet="CNBC", type="media", hint="ekonomi", url="https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    dict(id="cnbc-finance", name="CNBC Finance", outlet="CNBC", type="media", hint="ekonomi", url="https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    dict(id="cnbc-tech", name="CNBC Technology", outlet="CNBC", type="media", hint="teknologi", url="https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    dict(id="cnbcid-market", name="CNBC Indonesia Market", outlet="CNBC Indonesia", type="media", hint="ekonomi", url="https://www.cnbcindonesia.com/market/rss"),
    dict(id="techcrunch", name="TechCrunch", type="media", hint="teknologi", url="https://techcrunch.com/feed/"),
    dict(id="verge", name="The Verge", type="media", hint="teknologi", url="https://www.theverge.com/rss/index.xml"),
    dict(id="ars", name="Ars Technica", type="media", hint="teknologi", url="https://feeds.arstechnica.com/arstechnica/index"),
    # --- Lembaga resmi ---
    dict(id="who", name="WHO News", type="lembaga", url="https://www.who.int/rss-feeds/news-english.xml"),
    dict(id="gdacs", name="GDACS (bencana global)", type="lembaga", hint="cuaca", url="https://www.gdacs.org/xml/rss.xml"),
    # --- Google News (agregator; outlet asli tetap ditampilkan) ---
    dict(id="gn-reuters", name="Reuters (via Google News)", type="agregator", url=gnews("when:24h site:reuters.com")),
    dict(id="gn-ap", name="AP News (via Google News)", type="agregator", url=gnews("when:24h site:apnews.com")),
    dict(id="gn-wallstreet", name="Google News: Wall Street", type="agregator", hint="ekonomi",
         url=gnews('("Wall Street" OR "S&P 500" OR Nasdaq OR "Dow Jones") when:1d')),
    dict(id="gn-ihsg", name="Google News: IHSG & Bursa Indonesia", type="agregator", hint="ekonomi",
         url=gnews('(IHSG OR "Bursa Efek Indonesia" OR "saham") when:1d', lang="id")),
    dict(id="gn-outbreak", name="Google News: Wabah & Penyakit", type="agregator", hint="cuaca",
         url=gnews('(outbreak OR epidemic OR "bird flu" OR cholera OR mpox OR dengue OR measles) when:2d')),
    dict(id="gn-ai", name="Google News: AI", type="agregator", hint="teknologi",
         url=gnews('("artificial intelligence" OR OpenAI OR Anthropic OR "Google DeepMind") when:1d')),
    dict(id="gn-energy", name="Google News: Energi", type="agregator", hint="teknologi",
         url=gnews('("renewable energy" OR "nuclear power" OR "battery storage" OR "solar power") when:2d')),
    # --- Reddit (sinyal sosial, belum terverifikasi) ---
    dict(id="r-worldnews", name="Reddit r/worldnews", type="reddit", url="https://www.reddit.com/r/worldnews/.rss?limit=50"),
    dict(id="r-economics", name="Reddit r/Economics", type="reddit", url="https://www.reddit.com/r/Economics/.rss?limit=50"),
    dict(id="r-technology", name="Reddit r/technology", type="reddit", url="https://www.reddit.com/r/technology/.rss?limit=50"),
    dict(id="r-artificial", name="Reddit r/artificial", type="reddit", hint="teknologi", url="https://www.reddit.com/r/artificial/.rss?limit=50"),
]

GDELT_QUERIES = [
    dict(id="gdelt-ekonomi", name="GDELT: Saham & Ekonomi", hint="ekonomi",
         query='("stock market" OR "wall street" OR nasdaq OR IHSG OR "Indonesia stocks" OR "federal reserve") sourcelang:english'),
    dict(id="gdelt-cuaca", name="GDELT: Cuaca & Wabah", hint="cuaca",
         query='(hurricane OR typhoon OR cyclone OR flood OR earthquake OR heatwave OR outbreak OR epidemic OR cholera OR dengue) sourcelang:english'),
    dict(id="gdelt-teknologi", name="GDELT: Teknologi", hint="teknologi",
         query='("artificial intelligence" OR OpenAI OR Anthropic OR "renewable energy" OR "nuclear power" OR semiconductor) sourcelang:english'),
]

# ---------------- Topik & subtopik ----------------
# kw: kata kunci (tidak peka huruf besar); cs: peka huruf besar (singkatan)
TAGS = {
    "ekonomi": {
        "Saham AS": dict(kw=["wall street", "s&p 500", "s&p", "nasdaq", "dow jones", "nyse", "federal reserve",
                             "the fed", "fed's", "us stocks", "u.s. stocks", "treasury yields", "powell"], cs=[]),
        "Saham Indonesia": dict(kw=["ihsg", "bursa efek indonesia", "jakarta composite", "rupiah", "bank indonesia",
                                    "indonesia", "indonesian", "saham", "ojk", "danantara"], cs=["IDX", "BEI"]),
        "Komoditas": dict(kw=["oil price", "oil prices", "crude", "brent", "gold price", "gold", "harga emas",
                              "minyak", "coal", "batu bara", "nickel", "nikel", "palm oil", "cpo", "copper"], cs=[]),
        "Makro": dict(kw=["inflation", "gdp", "recession", "tariff", "tariffs", "interest rate", "interest rates",
                          "central bank", "inflasi", "suku bunga", "unemployment", "jobs report", "trade war"], cs=[]),
    },
    "cuaca": {
        "Cuaca & Iklim": dict(kw=["storm", "hurricane", "typhoon", "cyclone", "tornado", "heatwave", "heat wave",
                                  "monsoon", "heavy rain", "blizzard", "el nino", "el niño", "la nina", "la niña",
                                  "drought", "weather", "climate", "cuaca", "badai", "extreme heat"], cs=[]),
        "Bencana": dict(kw=["flood", "floods", "flooding", "earthquake", "quake", "tsunami", "volcano", "eruption",
                            "wildfire", "wildfires", "landslide", "gempa", "banjir", "longsor", "disaster"], cs=[]),
        "Wabah & Penyakit": dict(kw=["outbreak", "epidemic", "pandemic", "virus", "cholera", "measles", "mpox",
                                     "dengue", "malaria", "ebola", "marburg", "bird flu", "avian flu", "h5n1",
                                     "covid", "influenza", "polio", "tuberculosis", "nipah", "zika", "wabah",
                                     "demam berdarah", "world health organization", "disease", "infections"],
                                 cs=["WHO"]),
    },
    "teknologi": {
        "AI": dict(kw=["artificial intelligence", "openai", "anthropic", "chatgpt", "deepmind", "generative ai",
                       "llm", "chatbot", "chatbots", "machine learning", "kecerdasan buatan"], cs=["AI", "A.I.", "AGI"]),
        "Energi": dict(kw=["renewable", "renewables", "solar", "wind power", "wind farm", "offshore wind", "nuclear power",
                           "nuclear reactor", "battery", "batteries", "electric vehicle", "electric vehicles", "hydrogen",
                           "fusion", "power grid", "clean energy", "energy transition", "lithium", "energi"], cs=["EV", "EVs"]),
        "Chip & Hardware": dict(kw=["semiconductor", "semiconductors", "chip", "chips", "chipmaker", "nvidia", "tsmc",
                                    "intel", "amd", "quantum computing", "quantum"], cs=[]),
        "Antariksa": dict(kw=["spacex", "nasa", "rocket", "satellite", "satellites", "space station", "moon mission"], cs=[]),
        "Siber": dict(kw=["cyberattack", "cyber attack", "hackers", "hacked", "ransomware", "data breach",
                          "cybersecurity", "malware"], cs=[]),
    },
}
TOPIC_EXTRA = {
    "ekonomi": ["stock", "stocks", "shares", "markets", "investors", "earnings", "economy", "economic",
                "bank", "banks", "bond", "bonds", "currency", "dollar", "ipo", "merger", "profit", "revenue",
                "ekonomi", "bursa", "trade deal", "exports", "imports"],
    "cuaca": ["health emergency", "infection", "vaccine", "vaccines"],
    "teknologi": ["tech", "technology", "software", "startup", "apple", "google", "microsoft", "meta", "amazon",
                  "tesla", "robot", "robots", "robotics", "smartphone", "iphone", "android", "teknologi"],
}


def _rx(words, ignore_case=True):
    if not words:
        return None
    pat = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))
    return re.compile(r"(?<![\w])(?:" + pat + r")(?![\w])", re.I if ignore_case else 0)


TAG_RX = {t: {name: (_rx(d["kw"]), _rx(d["cs"], False)) for name, d in tags.items()} for t, tags in TAGS.items()}
EXTRA_RX = {t: _rx(w) for t, w in TOPIC_EXTRA.items()}


def classify(text, hint=None):
    scores, tags = {}, []
    for topic, tagmap in TAG_RX.items():
        s = 0
        for tag, (rx_i, rx_c) in tagmap.items():
            n = (len(rx_i.findall(text)) if rx_i else 0) + (len(rx_c.findall(text)) if rx_c else 0)
            if n:
                s += n * 2
                tags.append(tag)
        if EXTRA_RX.get(topic):
            s += len(EXTRA_RX[topic].findall(text))
        if hint == topic:
            s += 2
        if s:
            scores[topic] = s
    if not scores:
        return ["lainnya"], "lainnya", []
    top = max(scores.values())
    topics = sorted([t for t, s in scores.items() if s >= max(2, top * 0.5)], key=lambda t: -scores[t])
    if not topics:
        topics = [max(scores, key=scores.get)]
    keep_tags = [t for t in tags if any(t in TAGS[tp] for tp in topics)]
    return topics, topics[0], keep_tags


# ---------------- Parsing ----------------
TAG_RE = re.compile(r"<[^>]+>")


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def child(el, *names):
    for c in el:
        if local(c.tag) in names:
            return c
    return None


def txt(el):
    return (el.text or "").strip() if el is not None else ""


def clean(s, n=280):
    s = html.unescape(TAG_RE.sub(" ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    d = None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        pass
    if d is None:
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def safe_url(u):
    u = (u or "").strip()
    return u if u.startswith(("http://", "https://")) else ""


def parse_feed(feed, raw):
    root = ET.fromstring(raw)
    out = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        title = clean(txt(child(el, "title")), 300)
        # link: RSS <link>text</link>, Atom <link href=".."/>
        link = ""
        for c in el:
            if local(c.tag) == "link":
                if c.get("href") and c.get("rel", "alternate") == "alternate":
                    link = c.get("href")
                    break
                if (c.text or "").strip():
                    link = c.text.strip()
                    break
        if not link:
            link = txt(child(el, "guid"))
        link = safe_url(link)
        raw_sum = txt(child(el, "description", "summary", "content", "encoded"))
        date = parse_date(txt(child(el, "pubDate", "published", "updated", "date")))
        outlet = feed["name"]
        summary = clean(raw_sum)
        ext = ""
        if feed["type"] == "agregator":
            src = child(el, "source")
            if src is not None and txt(src):
                outlet = txt(src)
                title = re.sub(r"\s+-\s+" + re.escape(outlet) + r"$", "", title)
            summary = ""  # deskripsi Google News hanya daftar tautan
        elif feed["type"] == "reddit":
            m = re.search(r'<a href="([^"]+)">\[link\]</a>', raw_sum)
            ext = safe_url(html.unescape(m.group(1))) if m else ""
            if "reddit.com" in ext:
                ext = ""
            summary = ""
        if not title or not link:
            continue
        out.append(dict(title=title, link=link, ext=ext, summary=summary, published=date, source=outlet,
                        outlet=outlet if feed["type"] == "agregator" else feed.get("outlet", outlet),
                        feed=feed["id"], type=feed["type"], hint=feed.get("hint")))
    return out


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json;q=0.9, */*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_feed(feed):
    t0 = time.time()
    try:
        items = parse_feed(feed, http_get(feed["url"]))
        return feed, items, None, int((time.time() - t0) * 1000)
    except Exception as e:  # noqa: BLE001 - satu sumber gagal tidak boleh menghentikan semua
        return feed, [], f"{type(e).__name__}: {str(e)[:160]}", int((time.time() - t0) * 1000)


def fetch_gdelt(q):
    t0 = time.time()
    params = dict(query=q["query"], mode="artlist", format="json", maxrecords="60", timespan="12h", sort="datedesc")
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params)
    feed = dict(id=q["id"], name=q["name"], type="gdelt", hint=q["hint"], url=url)
    try:
        raw = http_get(url, timeout=40).decode("utf-8", "replace")
        try:
            data = json.loads(raw, strict=False)
        except json.JSONDecodeError:
            raise RuntimeError("GDELT: " + raw[:140].strip())
        items = []
        for a in data.get("articles", []):
            link = safe_url(a.get("url"))
            title = clean(a.get("title", ""), 300)
            if not link or not title:
                continue
            try:
                d = dt.datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
            except ValueError:
                d = None
            items.append(dict(title=title, link=link, ext="", summary="", published=d,
                              source=a.get("domain") or "GDELT", feed=q["id"], type="gdelt", hint=q["hint"]))
        return feed, items, None, int((time.time() - t0) * 1000)
    except Exception as e:  # noqa: BLE001
        return feed, [], f"{type(e).__name__}: {str(e)[:160]}", int((time.time() - t0) * 1000)


# ---------------- Dedup ----------------
STOP = set("""the and for with from that this have will been after over into about says said amid their more than
what when where which while would could should they them there these those just also against under first
says news live update updates report reports latest year years week today amid""".split())
TIER = {"lembaga": 0, "media": 1, "agregator": 1, "gdelt": 2, "reddit": 3}


def sig(title):
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) >= 4 and w not in STOP}


def outlet_of(it):
    o = it.get("outlet") or it["source"]
    return re.sub(r"^(www\.)", "", o.strip().lower())


def dedup(items):
    items = sorted(items, key=lambda i: (TIER[i["type"]], -(i["published"] or NOW).timestamp()))
    kept = []
    by_link = {}
    for it in items:
        key = it["link"].split("?")[0].rstrip("/")
        if key in by_link:
            k = by_link[key]
            if outlet_of(it) != outlet_of(k) and it["source"] not in k["also"]:
                k["also"].append(it["source"])
            if it["type"] != "reddit":
                k["_outlets"].add(outlet_of(it))
            continue
        toks = sig(it["title"])
        match = None
        if len(toks) >= 4:
            for k in kept:
                kt = k["_tok"]
                if len(kt) >= 4:
                    inter = len(toks & kt)
                    if inter and inter / len(toks | kt) >= 0.55:
                        match = k
                        break
        if match:
            if outlet_of(it) != outlet_of(match) and it["source"] not in match["also"]:
                match["also"].append(it["source"])
            if it["type"] != "reddit":
                match["_outlets"].add(outlet_of(it))
            continue
        it = dict(it, also=[], _tok=toks, _outlets={outlet_of(it)} if it["type"] != "reddit" else set())
        kept.append(it)
        by_link[key] = it
    return kept


def uid(link):
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:14]


def load_prev(prev_url, out_dir):
    """Ambil data.json & state.json versi sebelumnya (dari situs live, atau folder output lokal)."""
    prev_data, prev_state = None, None
    for name in ("data.json", "state.json"):
        obj = None
        if prev_url:
            try:
                obj = json.loads(http_get(prev_url.rstrip("/") + "/" + name + f"?t={int(time.time())}", 20))
            except Exception as e:  # noqa: BLE001
                print(f"  (tidak ada {name} sebelumnya di situs: {type(e).__name__})")
        if obj is None and (out_dir / name).exists():
            obj = json.loads((out_dir / name).read_text("utf-8"))
        if name == "data.json":
            prev_data = obj
        else:
            prev_state = obj
    return prev_data, prev_state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "_site"))
    ap.add_argument("--prev-url", default="")
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    prev_data, state = load_prev(args.prev_url, out_dir)
    state = state or {"started_at": NOW.isoformat(), "seen": [], "cumulative": {}, "runs": []}
    seen_order = list(state.get("seen", []))
    seen = set(seen_order)
    cumulative = state.get("cumulative", {})

    print(f"Mengambil {len(FEEDS)} feed RSS + {len(GDELT_QUERIES)} kueri GDELT …")
    results = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        results.extend(ex.map(fetch_feed, FEEDS))
    for i, q in enumerate(GDELT_QUERIES):
        if i:
            time.sleep(6)  # GDELT membatasi ~1 permintaan per 5 detik
        results.append(fetch_gdelt(q))

    # item lama dari sumber yang gagal dipakai ulang supaya dashboard tidak bolong
    prev_items = {}
    for p in (prev_data or {}).get("items", []):
        prev_items.setdefault(p.get("feed"), []).append(p)

    cutoff = NOW - dt.timedelta(hours=WINDOW_HOURS)
    all_items, sources, new_total, raw_total = [], [], 0, 0
    for feed, items, err, ms in results:
        reused = 0
        if err and feed["id"] in prev_items:
            for p in prev_items[feed["id"]]:
                d = parse_date(p.get("published") or "")
                if d and d >= cutoff:
                    items.append(dict(title=p["title"], link=p["link"], ext=p.get("ext", ""), summary=p.get("summary", ""),
                                      published=d, source=p["source"], outlet=p.get("outlet") or feed.get("outlet"),
                                      feed=feed["id"], type=feed["type"],
                                      hint=feed.get("hint"), _reused=True))
                    reused += 1
        fresh = [i for i in items if i["published"] is None or i["published"] >= cutoff]
        new = 0
        for it in fresh:
            if it.get("_reused"):
                continue
            h = uid(it["link"])
            if h not in seen:
                seen.add(h)
                seen_order.append(h)
                new += 1
        raw_total += len(items) - reused
        new_total += new
        cumulative[feed["id"]] = cumulative.get(feed["id"], 0) + new
        sources.append(dict(id=feed["id"], name=feed["name"], type=feed["type"],
                            url=feed["url"] if feed["type"] != "gdelt" else "https://api.gdeltproject.org/",
                            status="error" if err else "ok", error=err, reused=reused, ms=ms,
                            fetched=len(items) - reused, in_window=len(fresh), new=new,
                            cumulative=cumulative[feed["id"]]))
        all_items.extend(fresh)
        print(f"  {'GAGAL' if err else 'ok   '} {feed['name']:<38} {len(items) - reused:>4} item  {err or ''}")

    ok_count = sum(1 for s in sources if s["status"] == "ok")
    if ok_count == 0:
        print("Semua sumber gagal - data lama tidak ditimpa.", file=sys.stderr)
        sys.exit(1)

    kept = dedup(all_items)
    kept.sort(key=lambda i: (i["published"] or cutoff), reverse=True)
    kept = kept[:MAX_ITEMS]

    out_items, kept_per_feed = [], {}
    for it in kept:
        text = f"{it['title']} {it['summary']}"
        topics, primary, tags = classify(text, it.get("hint"))
        kept_per_feed[it["feed"]] = kept_per_feed.get(it["feed"], 0) + 1
        out_items.append(dict(
            id=uid(it["link"]), title=it["title"], link=it["link"], ext=it.get("ext", ""),
            source=it["source"], outlet=it.get("outlet") or it["source"], feed=it["feed"], type=it["type"],
            published=it["published"].isoformat() if it["published"] else None,
            summary=it["summary"], topics=topics, primary=primary, tags=tags,
            also=it["also"][:8], outlets=len(it["_outlets"]), confirmed=it["type"] != "reddit" and len(it["_outlets"]) >= 2,
        ))
    for s in sources:
        s["kept"] = kept_per_feed.get(s["id"], 0)

    runs = state.get("runs", [])
    runs.append(dict(t=NOW.isoformat(timespec="seconds"), fetched=raw_total, new=new_total,
                     kept=len(out_items), ok=ok_count, err=len(sources) - ok_count))
    runs = runs[-MAX_RUNS:]

    data = dict(
        generated_at=NOW.isoformat(timespec="seconds"),
        started_at=state.get("started_at"),
        window_hours=WINDOW_HOURS,
        totals=dict(fetched_now=raw_total, new_now=new_total, kept=len(out_items),
                    cumulative=sum(cumulative.values())),
        sources=sources, runs=runs[-96:], items=out_items,
    )
    seen_list = seen_order[-MAX_SEEN:]
    (out_dir / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")
    (out_dir / "state.json").write_text(json.dumps(dict(started_at=state.get("started_at"), seen=seen_list,
                                                        cumulative=cumulative, runs=runs), separators=(",", ":")), "utf-8")
    # salin halaman web
    if WEB_DIR.exists():
        for f in WEB_DIR.iterdir():
            if f.is_file():
                shutil.copy2(f, out_dir / f.name)
    print(f"Selesai: {len(out_items)} berita di dashboard, {new_total} item baru, "
          f"{ok_count}/{len(sources)} sumber ok -> {out_dir}")


if __name__ == "__main__":
    main()
