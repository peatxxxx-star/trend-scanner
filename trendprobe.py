"""Suche: wo stehen die Bundesliga-Spiele bei scores24?"""
import json, re
from pathlib import Path
from s24liste import get
out = {}
for u in ["https://scores24.live/de/soccer/2026-11-22", "https://scores24.live/de/soccer/l-germany-bundesliga",
          "https://scores24.live/de/soccer/l-germany-2-bundesliga", "https://scores24.live/de/soccer/l-germany-3-liga",
          "https://scores24.live/de/soccer/t-werder-bremen", "https://scores24.live/de/soccer/t-fc-augsburg",
          "https://scores24.live/de/soccer/m-22-11-2026-werder-bremen-hamburger-sv",
          "https://scores24.live/de/soccer/m-22-11-2026-fc-augsburg-1-fsv-mainz-05"]:
    try:
        h = get(u)
        out[u] = {"len": len(h), "m": sorted(set(re.findall(r"m-22-11-2026-[a-z0-9-]+", h)))[:60]}
    except Exception as e:
        out[u] = {"err": str(e)[:120]}
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
