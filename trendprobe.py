"""20.11.2026: Erkundung – liefert scores24 Tabellen (Spielzahl, Tore, Heim/Auswärts) pro Spiel?
Schreibt Rohfunde nach runs/trendscan/probe.json. Ändert nichts am Scanner."""
import json, re, time
from pathlib import Path
from s24liste import get

log = json.load(open("runs/trendscan/letzter_lauf.json"))
slugs = []
for s in log["signale"]:
    sl = s["key"].split("|")[0]
    if sl not in slugs:
        slugs.append(sl)
out = {"slugs": slugs[:3], "funde": []}
for slug in slugs[:3]:
    f = {"slug": slug}
    try:
        h = get(f"https://scores24.live/de/soccer/m-{slug}")
        f["html_len"] = len(h)
        f["rapi"] = sorted(set(re.findall(r'/rapi/[A-Za-z0-9_/\-\.\?=&]+', h)))[:60]
        f["keys"] = sorted(set(re.findall(r'"(standings?[A-Za-z_]*|table[A-Za-z_]*|tournament[A-Za-z_]*|season[A-Za-z_]*|stage[A-Za-z_]*)"', h)))[:60]
        for kw in ("standing", "Tabelle", "table"):
            i = h.find(kw)
            f[f"ctx_{kw}"] = h[max(0, i-300): i+600] if i >= 0 else None
    except Exception as e:
        f["fehler"] = str(e)[:200]
    for ep in ("standings", "table", "tournament-table", "standing"):
        url = f"https://scores24.live/rapi/localized/matches/soccer/{slug}/{ep}?lang=de&audience=de"
        try:
            t = get(url)
            f[f"ep_{ep}"] = t[:3000]
        except Exception as e:
            f[f"ep_{ep}"] = "ERR " + str(e)[:120]
        time.sleep(0.5)
    out["funde"].append(f)
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("ok")
