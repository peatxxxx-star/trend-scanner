"""Erkundung: Liguilla-Spiele bei scores24 (Morelia – La Paz)."""
import json
from pathlib import Path
import teamstats as T
out = {}
for slug in ["22-11-2026-atletico-morelia-club-atletico-la-paz"]:
    for tt in ("home", "away"):
        _, sp = T._spiele(T._abrufen(slug, tt))
        out[tt] = [(s["d"][:10], s["ort"], s["tf"], s["tg"], s["liga"], s["tab"]) for s in sp[:22]]
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
