"""Nachrechnung Machida – V-Varen (Gelbe V-Varen unter 2,5) mit Teamwerten, ohne das Spiel selbst."""
import json
from pathlib import Path
import teamstats as T
slug = "21-11-2026-machida-zelvia-v-varen-nagasaki"
out = {}
st = {}
for tt, seite in (("home", "heim"), ("away", "gast")):
    nodes = T._abrufen(slug, tt)
    _, sp = T._spiele(nodes)
    sp = [s for s in sp if s["d"] < "2026-11-21"]
    st[seite] = T._saison(sp, 14)
    out[seite] = [(s["d"][:10], s["ort"], s["tf"], s["tg"], s["gelb"], s["liga"]) for s in st[seite]]
k = {"art": "ou", "metric": "yellowcards", "seite": "gast", "richtung": "unter", "linie": 2.5}
out["check"] = T.gegencheck(k, st, "Machida Zelvia", "V-Varen Nagasaki", 1.28, True, [1.6, 3.6, 5.5])
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("ok")
