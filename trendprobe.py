"""Erkundung: JSON der letzten Spiele auf der scores24-H2H-Seite (ändert nichts am Scanner)."""
import json, re
from pathlib import Path
from s24liste import get
out = {}
url = "https://scores24.live/de/soccer/m-21-11-2026-radnicki-nis-zemun-h2h"
try:
    h = get(url)
except Exception as e:
    h = ""
    out["err"] = str(e)[:200]
u = h.replace('\\"', '"')
out["len"] = len(h)
keys = {}
for k in re.findall(r'"([A-Za-z_]{3,40})":', u):
    keys[k] = keys.get(k, 0) + 1
out["keys"] = sorted(keys.items(), key=lambda x: -x[1])[:250]
for kw in ['"resultScore"', '"corners"', '"yellowCards"', '"statistic', '"lastMatches"', '"teamLastMatches"', '"stats"']:
    idx = [m.start() for m in re.finditer(re.escape(kw), u)][:2]
    out[kw] = [u[max(0, i - 1500): i + 2500] for i in idx]
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("ok", len(h))
