"""Diagnose: Ligen ohne Tabelle (englischer Amateurbereich) + Abruf-Test mit neuem laden()."""
import json, tempfile
from collections import Counter
from pathlib import Path
import teamstats as T
slugs = ["24-11-2026-mickleover-sports-bedworth-united", "21-11-2026-stocksbridge-park-steels-consett-a-f-c-",
         "25-11-2026-southall-fc-newmarket-town", "25-11-2026-guisborough-town-beverley-town"]
out = {}
for s in slugs:
    r = {}
    for tt in ("home", "away"):
        try:
            nodes = T._abrufen(s, tt)
        except Exception as e:
            r[tt] = {"err": str(e)[:150]}; continue
        team, sp = T._spiele(nodes)
        sa = T._saison(sp, None)
        r[tt] = {"nodes": len(nodes), "team": team, "spiele": len(sp),
                 "ligen": Counter((g["liga"], g["tab"]) for g in sp).most_common(5),
                 "saison": len(sa), "liga": sa[0]["liga"] if sa else None,
                 "erste": [(g["d"][:10], g["liga"]) for g in sp[:4]]}
    out[s] = r
cf = Path(tempfile.mkdtemp()) / "tm.json.gz"
st = T.laden([(s, None, None) for s in slugs], cf)
out["_laden"] = {s: {k: (len(v) if isinstance(v, list) else v) for k, v in x.items()} for s, x in st.items()}
out["_fehler"] = T.ABRUF_FEHLER
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
