"""Erkundung: team-matches komplett sichern (Parser-Entwicklung)."""
import json, gzip
from pathlib import Path
from s24liste import get
out = {}
for slug in ["21-11-2026-radnicki-nis-zemun", "21-11-2026-ostersunds-fk-varbergs-bois-fc"]:
    for tt in ("home", "away"):
        u = (f"https://scores24.live/rapi/matches/soccer/{slug}/team-matches?teamType={tt}&first=40"
             f"&lang=de&sort=desc&status=finished&withStatistics=true")
        try:
            out[f"{slug}|{tt}"] = json.loads(get(u))
        except Exception as e:
            out[f"{slug}|{tt}"] = {"err": str(e)[:200]}
with gzip.open("runs/trendscan/probe_tm.json.gz", "wt") as f:
    json.dump(out, f, ensure_ascii=False)
Path("runs/trendscan/probe.json").write_text(json.dumps({k: (len(v.get("data", {}).get("edges", [])) if "data" in v else v) for k, v in out.items()}))
print("ok")
