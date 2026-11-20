"""Erkundung: wo stehen die letzten Spiele (mit Ergebnis) im HTML von scores24?"""
import json, re
from pathlib import Path
from s24liste import get

slug = "20-11-2026-annecy-clermont"
h = get(f"https://scores24.live/de/soccer/m-{slug}")
out = {"len": len(h)}
# Match-Links der Seite
links = re.findall(r'/de/soccer/m-(\d{2}-\d{2}-\d{4}-[a-z0-9\-]+)', h)
out["links"] = list(dict.fromkeys(links))[:80]
# JSON-Fundstellen mit Ergebnissen
for kw in ['"homeScore"', '"awayScore"', '"scores"', '"score":', '"result"', '"winner"', '"teamAScore"', '"ft"', '"fullTime"', '"matchResult"', '"finished"']:
    idx = [m.start() for m in re.finditer(re.escape(kw), h)][:3]
    out[kw] = [h[max(0, i-500): i+700] for i in idx]
# Script-Tags mit State
st = re.findall(r'<script[^>]*>(.{0,200})', h)
out["scripts"] = st[:30]
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("ok")
