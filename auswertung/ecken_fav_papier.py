"""Papier-Auswertung Außenseiter-Ecken unter (ab 26.10.2026, Protokoll `ecken_fav`).

Je Spiel zählt der Tipp aus dem LETZTEN Lauf vor Anstoß. Ergebnis aus dem Marktarchiv (über die BL-ID,
BL-Orientierung → BetsAPI über `swap`) oder runs/ergebnisse_*.json (über die BetsAPI-ID).
Aufruf:  python3 auswertung/ecken_fav_papier.py [ab-Datum]   (Standard 2026-10-26)
"""
import json, glob, gzip, sys
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
B = ZoneInfo("Europe/Berlin")
AB = sys.argv[1] if len(sys.argv) > 1 else "2026-10-26"

tipps = {}
for f in sorted(glob.glob(str(REPO / "runs" / "2026-*_*.json"))):
    name = Path(f).name
    if any(x in name for x in ("prewarm", "ergeb", "dump", "h2h", "archiv")) or name[:10] < AB:
        continue
    try:
        d = json.load(open(f))
        lauf_ts = datetime.fromisoformat(d.get("run_utc", "")).timestamp()
    except Exception:
        continue
    for t in (d.get("ecken_fav") or {}).get("tipps") or []:
        if lauf_ts > (t.get("kickoff_ts") or 0):
            continue
        tipps[str(t["bl_id"])] = t

erg_bl, swap_bl, erg_ev = {}, {}, {}
for f in glob.glob(str(REPO / "runs" / "archiv" / "bl_*.json.gz")):
    for g in json.load(gzip.open(f, "rt", encoding="utf-8"))["spiele"]:
        swap_bl[str(g["I"])] = bool(g.get("swap"))
        if g.get("erg"):
            erg_bl[str(g["I"])] = g["erg"]
for f in sorted(glob.glob(str(REPO / "runs" / "ergebnisse_*.json"))):
    for k, v in json.load(open(f)).items():
        if str(v.get("time_status")) == "3":
            erg_ev[str(k)] = v.get("slim") or {}


def wert(t):
    e = erg_bl.get(str(t["bl_id"])) or erg_ev.get(str(t.get("match_id")))
    if not e:
        return None
    c = e.get("corners")
    if not c or c[0] is None or min(c) < 0 or e.get("len") not in (None, 90):
        return None
    heim = (t["seite"] == "heim") != swap_bl.get(str(t["bl_id"]), False)
    return c[0] if heim else c[1]


zeilen, fehlt = [], []
for bid, t in tipps.items():
    v = wert(t)
    if v is None:
        fehlt.append(str(t.get("match_id")))
        continue
    zeilen.append(dict(t, wert=v, hit=v < t["linie"], tag=datetime.fromtimestamp(t["kickoff_ts"], B).strftime("%Y-%m-%d")))
zeilen.sort(key=lambda z: z["kickoff_ts"])
if not zeilen:
    print("Noch keine ausgewerteten Tipps."); print("Ohne Ergebnis:", ",".join(fehlt)); sys.exit()
n = len(zeilen); g = sum(z["hit"] for z in zeilen)
print(f"AUSSENSEITER-ECKEN UNTER Papier ab {AB}: {n} Tipps, {g} Treffer ({g / n:.0%}), Ø Quote {sum(z['q'] for z in zeilen) / n:.2f}, "
      f"ROI {sum((z['q'] if z['hit'] else 0) - 1 for z in zeilen) / n:+.1%}")
tage = defaultdict(list)
for z in zeilen:
    tage[z["tag"]].append(z)
tot = cnt = win = 0
for tag, x in sorted(tage.items()):
    for i in range(len(x) // 2):
        s = x[2 * i:2 * i + 2]
        w = all(z["hit"] for z in s)
        cnt += 1; win += w; tot += (10 * s[0]["q"] * s[1]["q"] if w else 0) - 10
    print(f"  {tag}: {len(x)} Tipps, {sum(z['hit'] for z in x)} Treffer")
if cnt:
    print(f"  2er: {cnt} Scheine, {win} gewonnen, Saldo {tot:+.2f} €")
if fehlt:
    print("\nOhne Ergebnis (Ergebnis-Abruf):", ",".join(fehlt))
