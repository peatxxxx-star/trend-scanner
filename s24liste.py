"""scores24-Tagesliste (05.11.2026, Lucio): alle Spiele eines Zeitfensters
aus der scores24-Sitemap, je Spiel Match-JSON + Trends-JSON. Ohne BetsAPI.
Ergebnis als gzip-JSON in out/ (wird als Workflow-Artefakt hochgeladen)."""
import gzip, json, os, re, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HDRS = ({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
         "Accept-Language": "de-DE,de;q=0.9", "Accept-Encoding": "gzip",
         "Referer": "https://scores24.live/de/soccer/", "Origin": "https://scores24.live",
         "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"},
        {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "de"})
TZ = ZoneInfo("Europe/Berlin")


def get(url):
    last = None
    for h in HDRS:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
                raw = r.read()
                if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (403, 406, 429):
                raise
        except Exception as e:
            last = e
    raise last


def main():
    now = datetime.now(TZ)
    bis_h = int(os.environ.get("S24_BIS", "20"))
    tage = {now.strftime("%d-%m-%Y")}
    if bis_h > 24:
        tage.add((now + timedelta(days=1)).strftime("%d-%m-%Y"))
    links = []
    for i in range(20):
        try:
            xml = get(f"https://scores24.live/sitemaps/sitemap-de-soccer-upcoming-matches-{i}.xml")
        except Exception as e:
            print("sitemap", i, e); break
        f = re.findall(r"/de/soccer/(m-[^<\"?#]+)", xml)
        if not f:
            break
        links += f
    links = sorted({l for l in links if l[2:12] in tage})
    print("Sitemap-Spiele im Datum:", len(links))
    out = []

    def one(link):
        slug = link[2:]
        rec = {"slug": slug}
        for key, url in (("match", f"https://scores24.live/rapi/localized/matches/soccer/{slug}?lang=de&audience=de"),
                         ("trends", f"https://scores24.live/rapi/localized/matches/soccer/{slug}/trends?lang=de&audience=de")):
            for a in range(2):
                try:
                    rec[key] = json.loads(get(url)); break
                except Exception as e:
                    rec[key + "_err"] = str(e)[:120]; time.sleep(1)
        return rec

    with ThreadPoolExecutor(8) as ex:
        for rec in ex.map(one, links):
            out.append(rec)
    os.makedirs("out", exist_ok=True)
    fn = f"out/s24_{now.strftime('%Y-%m-%d_%H%M')}.json.gz"
    with gzip.open(fn, "wt") as f:
        json.dump({"stand": now.isoformat(), "bis_h": bis_h, "spiele": out}, f, ensure_ascii=False)
    ok = sum(1 for r in out if "trends" in r)
    print("gespeichert", fn, "Spiele", len(out), "mit Trends", ok, "Größe", os.path.getsize(fn))


if __name__ == "__main__":
    main()
