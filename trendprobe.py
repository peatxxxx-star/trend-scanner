"""Slug-Datum = Spieltagsbeginn? Welche Links liefern Tagesseite/Sitemap ohne Datumsfilter."""
import json, re
from pathlib import Path
from s24liste import get
out = {}
alle = []
for u in ["https://scores24.live/de/soccer/2026-11-22", "https://scores24.live/de/soccer?date=2026-11-22"]:
    h = get(u)
    alle += re.findall(r"/de/soccer/(m-\d{2}-\d{2}-\d{4}-[^\"?#<>\s]+)", h)
out["tag_links"] = len(set(alle))
from collections import Counter
out["tag_datum"] = Counter(l[2:12] for l in set(alle)).most_common(10)
sm = []
for i in range(40):
    try:
        xml = get(f"https://scores24.live/sitemaps/sitemap-de-soccer-upcoming-matches-{i}.xml")
    except Exception:
        break
    f = re.findall(r"/de/soccer/(m-[^<\"?#]+)", xml)
    if not f:
        break
    sm += f
out["sitemap"] = len(set(sm))
out["sitemap_datum"] = Counter(l[2:12] for l in set(sm)).most_common(15)
such = ("kaiserslautern", "cottbus", "karlsruh", "stuttgart-ii", "saarbr", "duisburg", "werder-bremen-hamburger", "augsburg-mainz")
out["treffer"] = sorted({l for l in set(alle) | set(sm) if any(x in l for x in such)})
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
