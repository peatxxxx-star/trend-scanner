"""Regressionstest _saison alt vs. neu (Liga aus den letzten 120 Tagen)."""
import json
from collections import Counter
from pathlib import Path
import teamstats as T

def alt(spiele, n_tab):
    liga = Counter(s["liga"] for s in spiele if s["tab"] and not s["freund"]).most_common(1)
    if not liga:
        liga = Counter(s["liga"] for s in spiele if s["liga"] and not any(w in s["liga"].lower() for w in T._POKAL)).most_common(1)
    if not liga:
        return []
    ls = [s for s in spiele if s["liga"] == liga[0][0]]
    return ls[:n_tab] if n_tab else ls  # nur Liga-Vergleich

slugs = ["24-11-2026-mickleover-sports-bedworth-united", "21-11-2026-stocksbridge-park-steels-consett-a-f-c-",
         "25-11-2026-southall-fc-newmarket-town", "25-11-2026-guisborough-town-beverley-town",
         "25-11-2026-bolton-wanderers-west-bromwich-albion", "25-11-2026-stoke-city-millwall",
         "25-11-2026-hartlepool-solihull-moors", "25-11-2026-harrogate-town-kidderminster-harriers",
         "24-11-2026-padova-sampdoria", "22-11-2026-sparta-az-alkmaar", "22-11-2026-atletico-mineiro-corinthians",
         "25-11-2026-enppi-club-ceramica-cleopatra", "22-11-2026-soroksar-szeged-csanad-grosics-akademia",
         "26-11-2026-persika-karanganyar-persipa-pati", "25-11-2026-cascada-banha", "25-11-2026-apr-fc-musanze-fc",
         "24-11-2026-blacks-power-entebbe-uppc", "22-11-2026-lks-lodz-ii-wigry-suwalki",
         "22-11-2026-alessandria-acsd-saluzzo", "22-11-2026-udi-19-fc-lisse"]
out = {}
for s in slugs:
    for tt in ("home", "away"):
        try:
            team, sp = T._spiele(T._abrufen(s, tt))
        except Exception as e:
            out[f"{s}|{tt}"] = str(e)[:100]; continue
        a, n = alt(sp, None), T._saison(sp, None)
        out[f"{s}|{tt}"] = {"team": team, "alt_liga": a[0]["liga"] if a else None,
                            "neu_liga": n[0]["liga"] if n else None, "neu_n": len(n)}
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
