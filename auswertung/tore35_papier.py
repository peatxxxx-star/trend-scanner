"""Papier-Auswertung Tore über 3.5 bei torreichen Teams (ab 26.10.2026, Protokoll `tore35`).

Je Spiel zählt der Tipp aus dem LETZTEN Lauf vor Anstoß (so wie er zum Spielen
dagestanden hätte). Ergebnis aus dem Marktarchiv (erg) oder runs/ergebnisse_*.json.
Ausgabe: Einzel, 2er und 3er in Anstoß-Reihenfolge je Tag (10 € je Schein).
Aufruf:  python3 auswertung/tore35_papier.py [ab-Datum]   (Standard 2026-10-26)
Fehlende Ergebnisse: Event-IDs werden ausgegeben -> "Ergebnis-Abruf: id,id" auslösen.
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
gesehen_ts = {}   # Tipp-Schlüssel -> Zeit des Laufs, in dem er zuletzt stand
laeufe = []       # Laufzeiten mit diesem Block
erst_q = {}          # erste angezeigte Quote je Spiel+Tipp (Quotenbewegung bis Anstoß)
for f in sorted(glob.glob(str(REPO / "runs" / "2026-*_*.json"))):
    name = Path(f).name
    if any(x in name for x in ("prewarm", "ergeb", "dump", "h2h", "archiv")) or name[:10] < AB:
        continue
    try:
        d = json.load(open(f))
    except Exception:
        continue
    lauf = d.get("run_utc", "")
    try:
        lauf_ts = datetime.fromisoformat(lauf).timestamp()
    except Exception:
        lauf_ts = 0
    if isinstance(d.get("tore35"), dict) and "tipps" in d["tore35"]:
        laeufe.append(lauf_ts)
    for t in (d.get("tore35") or {}).get("tipps") or []:
        ko = t.get("kickoff_ts") or 0
        if lauf_ts and lauf_ts > ko:
            continue
        tipps[t["match_id"]] = t          # späterer Lauf überschreibt früheren
        gesehen_ts[t["match_id"]] = lauf_ts
        erst_q.setdefault((t["match_id"], "tot", t["richtung"], t["linie"]), t["q"])

# 27.10.: Tipps, die vor Anstoß aus dem Block gefallen sind (z. B. Regel verschärft, Vorteil weg),
# zählen nicht – maßgeblich ist der letzte Lauf vor Anstoß.
for _k in list(tipps):
    _ko = tipps[_k].get("kickoff_ts") or 0
    _letzter = max((l for l in laeufe if l <= _ko), default=0)
    if gesehen_ts.get(_k, 0) < _letzter:
        del tipps[_k]

erg = {}
for f in glob.glob(str(REPO / "runs" / "archiv" / "bl_*.json.gz")):
    for g in json.load(gzip.open(f, "rt", encoding="utf-8"))["spiele"]:
        if g.get("ev") and g.get("erg"):
            erg[g["ev"]] = g["erg"]
for f in sorted(glob.glob(str(REPO / "runs" / "ergebnisse_*.json"))):
    for k, v in json.load(open(f)).items():
        if str(v.get("time_status")) == "3":
            erg.setdefault(str(k), v.get("slim") or {})

def wert(t, e):
    y = e.get("goals")
    if not y or y[0] is None or min(y) < 0 or e.get("len") not in (None, 90):
        return None
    return y[0] + y[1]

zeilen, fehlt = [], []
for mid, t in tipps.items():
    e = erg.get(str(mid))
    v = wert(t, e) if e else None
    if v is None:
        fehlt.append(mid)
        continue
    hit = v > t["linie"] if t["richtung"] == "über" else v < t["linie"]
    zeilen.append(dict(t, wert=v, hit=hit, tag=datetime.fromtimestamp(t["kickoff_ts"], B).strftime("%Y-%m-%d")))

zeilen.sort(key=lambda z: z["kickoff_ts"])
if not zeilen:
    print("Noch keine ausgewerteten Tipps."); print("Ohne Ergebnis:", ",".join(fehlt)); sys.exit()
n = len(zeilen); g = sum(z["hit"] for z in zeilen)
roi = sum((z["q"] if z["hit"] else 0) - 1 for z in zeilen) / n
print(f"TORE ÜBER 3.5 Papier ab {AB}: {n} Tipps, {g} Treffer ({g / n:.0%}), Ø Quote {sum(z['q'] for z in zeilen) / n:.2f}, ROI {roi:+.1%}")
for k in (2, 3):
    tot = cnt = win = 0
    tage = defaultdict(list)
    for z in zeilen:
        tage[z["tag"]].append(z)
    for tag, x in sorted(tage.items()):
        for i in range(len(x) // k):
            s = x[k * i:k * i + k]; q = 1
            for z in s:
                q *= z["q"]
            w = all(z["hit"] for z in s)
            cnt += 1; win += w; tot += (10 * q if w else 0) - 10
    if cnt:
        print(f"  {k}er: {cnt} Scheine, {win} gewonnen ({win / cnt:.0%}), Saldo {tot:+.2f} € bei {cnt * 10} € Einsatz")
print("\nje Tag:")
for tag in sorted({z["tag"] for z in zeilen}):
    x = [z for z in zeilen if z["tag"] == tag]
    print(f"  {tag}: {len(x)} Tipps, {sum(z['hit'] for z in x)} Treffer, ROI {sum((z['q'] if z['hit'] else 0) - 1 for z in x) / len(x):+.1%}")
# Quotenbewegung: sinkt die BL-Quote zwischen erster Anzeige und Anstoß, hat der Markt
# sich in unsere Richtung bewegt (gutes Zeichen, unabhängig vom Ergebnis).
bew = []
for mid, t in tipps.items():
    q0 = erst_q.get((mid, "tot", t["richtung"], t["linie"]))
    if q0:
        bew.append(t["q"] / q0 - 1)
if bew:
    print(f"\nQuotenbewegung erste Anzeige → letzter Lauf vor Anstoß: Ø {sum(bew) / len(bew):+.1%} "
          f"(gefallen {sum(1 for b in bew if b < 0)}, gleich {sum(1 for b in bew if b == 0)}, gestiegen {sum(1 for b in bew if b > 0)})")
if fehlt:
    print("\nOhne Ergebnis (Ergebnis-Abruf):", ",".join(fehlt))
