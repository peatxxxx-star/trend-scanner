"""Erkundung: queryKeys der H2H-Seite (Endpunkte für letzte Spiele)."""
import json, re
from pathlib import Path
from s24liste import get
out = {}
url = "https://scores24.live/de/soccer/m-21-11-2026-radnicki-nis-zemun-h2h"
h = get(url)
u = h.replace('\\"', '"')
qk = []
for m in re.finditer(r'"queryKey":(\[\{.*?\}\])\s*,\s*"queryHash"', u):
    qk.append(m.group(1)[:600])
out["queryKeys"] = qk
# Kandidaten-Endpunkte mit mehr Spielen ausprobieren
for q in qk:
    if "atches" in q and ("first" in q or "cursor" in q or "team" in q.lower()):
        out.setdefault("kand", []).append(q)
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("ok")
