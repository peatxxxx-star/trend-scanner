"""Diagnose: warum keine Teamwerte?"""
import json
from collections import Counter
from pathlib import Path
import teamstats as T
import trendscan as TS
slugs = ["25-11-2026-bolton-wanderers-west-bromwich-albion", "25-11-2026-stoke-city-millwall",
         "25-11-2026-watford-blackburn-rovers", "25-11-2026-hartlepool-solihull-moors",
         "25-11-2026-harrogate-town-kidderminster-harriers", "25-11-2026-boreham-aldershot-town",
         "24-11-2026-padova-sampdoria", "22-11-2026-sparta-az-alkmaar", "22-11-2026-atletico-mineiro-corinthians",
         "25-11-2026-enppi-club-ceramica-cleopatra", "22-11-2026-soroksar-szeged-csanad-grosics-akademia"]
out = {}
for s in slugs:
    r = {}
    try:
        rec = TS._spiel_s24(s)
        tab = rec.get("tab") or {}
        r["tab"] = {k: (tab.get(k) or {}).get("sp") for k in ("heim", "gast")} if isinstance(tab, dict) else str(tab)[:80]
        r["tab_teams"] = rec.get("tab_teams")
    except Exception as e:
        r["tab_err"] = str(e)[:120]
    for tt in ("home", "away"):
        try:
            nodes = T._abrufen(s, tt)
        except Exception as e:
            r[tt] = {"err": str(e)[:150]}
            continue
        team, sp = T._spiele(nodes)
        n = (r.get("tab") or {}).get("heim" if tt == "home" else "gast") if isinstance(r.get("tab"), dict) else None
        r[tt] = {"nodes": len(nodes), "team": team, "spiele": len(sp),
                 "ligen": Counter((g["liga"], g["tab"]) for g in sp).most_common(5),
                 "saison": len(T._saison(sp, n)), "n_tab": n,
                 "erste": [(g["d"][:10], g["liga"], g["tf"], g["tg"]) for g in sp[:3]]}
    out[s] = r
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
