"""Auswertung „trifft“: Ergebnisse + Spielhistorie beider Teams für alle bisherigen trifft-Signale."""
import json, gzip
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import teamstats as T
sig = json.loads(Path("runs/trendscan/trifft_signale.json").read_text())
slugs = sorted({k.split("|")[0] for k in sig})

def eins(a):
    slug, tt = a
    try:
        nodes = T._abrufen(slug, tt)
    except Exception as e:
        return a, {"err": str(e)[:100]}
    res = None
    for n in nodes:
        if n.get("slug") == slug:
            rs = {r.get("type"): r.get("value") for r in n.get("result_scores") or []}
            res = {"FT": rs.get("FT") or n.get("result_score"), "HT": rs.get("HT")}
    team, sp = T._spiele(nodes)
    return a, {"team": team, "res": res, "spiele": sp}

out = {}
with ThreadPoolExecutor(8) as ex:
    for (slug, tt), r in ex.map(eins, [(s, t) for s in slugs for t in ("home", "away")]):
        out.setdefault(slug, {})[tt] = r
with gzip.open("runs/trendscan/trifft_daten.json.gz", "wt") as f:
    json.dump(out, f, ensure_ascii=False)
ok = sum(1 for v in out.values() if (v.get("home") or {}).get("res"))
Path("runs/trendscan/probe.json").write_text(json.dumps({"slugs": len(slugs), "mit_ergebnis": ok}))
print(len(slugs), ok)
