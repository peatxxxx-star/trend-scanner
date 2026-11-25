"""Ergebnisse (FT/HT, Ecken, Gelbe) für alle Ampel-Signale seit 21.11."""
import json, gzip
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import teamstats as T
sig = json.loads(Path("runs/trendscan/ampel_signale.json").read_text())
slugs = sorted({k.split("|")[0] for k in sig})

def eins(slug):
    for tt in ("home", "away"):
        try:
            nodes = T._abrufen(slug, tt)
        except Exception:
            continue
        for n in nodes:
            if n.get("slug") == slug:
                rs = {r.get("type"): r.get("value") for r in n.get("result_scores") or []}
                st = {i.get("type"): [i.get("team1_value"), i.get("team2_value")]
                      for i in ((n.get("statistic") or {}).get("items") or [])}
                return slug, {"FT": rs.get("FT") or n.get("result_score"), "HT": rs.get("HT"), "stat": st}
    return slug, None

out = {}
with ThreadPoolExecutor(8) as ex:
    for s, r in ex.map(eins, slugs):
        out[s] = r
Path("runs/trendscan/ampel_ergebnisse.json").write_text(json.dumps(out, ensure_ascii=False))
Path("runs/trendscan/probe.json").write_text(json.dumps({"slugs": len(slugs), "mit": sum(1 for v in out.values() if v)}))
