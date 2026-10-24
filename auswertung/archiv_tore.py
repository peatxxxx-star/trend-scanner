import json, sys, gzip, glob, time
from collections import defaultdict
sys.path.insert(0, "/home/claude/trend-scanner")
import scan
cache = scan.load_cache()
H = json.load(open("auswertung/hist_merged.json"))
arch = {}
for f in sorted(glob.glob("runs/archiv/bl_*.json.gz")):
    tag = f[-18:-8]
    for g in json.load(gzip.open(f))["spiele"]:
        if g.get("ev") and g.get("erg"): arch[str(g["ev"])] = (tag, g)
pos = defaultdict(list)
for tid, v in H.items():
    evs = scan.drop_friendlies(v["events"])
    for i, e in enumerate(evs):
        if e["id"] in arch: pos[e["id"]].append((tid, e, evs[i+1:]))
WANT = {("goals","über",1.5): "o1.5", ("goals","unter",3.5): "u3.5", ("goals","über",2.5): "o2.5"}
rows = []; n_spiele = 0
for eid, lst in pos.items():
    if len(lst) != 2: continue
    (ta, ea, oa), (tb, eb, ob) = lst
    if not ea["h"]: (ta, ea, oa), (tb, eb, ob) = (tb, eb, ob), (ta, ea, oa)
    tag, g = arch[eid]
    tore = g["erg"].get("goals")
    if not tore or min(tore) < 0: continue
    n_spiele += 1
    mk = lambda older: [{"stats": cache.get(e["id"], {}), "is_home": e["h"], "label": e["l"]} for e in older]
    match = {"id": eid, "league": g.get("liga") or ea.get("lg",""), "home": g["O1"], "away": g["O2"], "home_id": ta, "away_id": tb,
             "kickoff": "", "kickoff_ts": g["S"]}
    for s in scan.evaluate_match(match, mk(oa), mk(ob)):
        k = (s["metric_key"], s["direction"], s["line"])
        if k not in WANT: continue
        scan.assess_signal(s)
        if s.get("light") != "🟢": continue
        q = ((g.get("m") or {}).get("goals") or {}).get(WANT[k])
        mn = scan.play_min(s)[0]
        tot = sum(tore); hit = tot > s["line"] if s["direction"] == "über" else tot < s["line"]
        rows.append(dict(k=f"{s['direction']} {s['line']}", tag=tag, q=q, ab=mn, fair=s.get("fair_fin"), hit=hit, spiel=f"{g['O1']} - {g['O2']}", tore=tore))
json.dump(rows, open("auswertung/archiv_tore_rows.json","w"), ensure_ascii=False)
print("Archivspiele mit Ergebnis:", len(arch), "· davon mit Historie beider Teams:", n_spiele)
def line(lbl, rs):
    if not rs: print(f"   {lbl:26s} n=0"); return
    n=len(rs); h=sum(r["hit"] for r in rs); ret=sum(r["q"] for r in rs if r["hit"]); aq=sum(r["q"] for r in rs)/n
    print(f"   {lbl:26s} {h:3d}/{n:<3d} {100*h/n:3.0f}%  Ø Quote {aq:.2f}  nötig {100/aq:3.0f}%  ROI {100*(ret/n-1):+4.0f}%  (10 €/Tipp: {10*(ret-n):+.0f} €)")
for k in ("über 1.5", "unter 3.5", "über 2.5"):
    rs = [r for r in rows if r["k"] == k]
    mq = [r for r in rs if r["q"]]
    print(f"Tore {k}: Signale {len(rs)}, mit BL-Quote {len(mq)}, Ø fair {sum(r['fair'] for r in rs)/max(len(rs),1):.2f}")
    line("alle mit BL-Quote", mq)
    line("über ab", [r for r in mq if r["ab"] and r["q"] >= r["ab"] - 1e-9])
    line("über ab, 1,30–2,00", [r for r in mq if r["ab"] and r["q"] >= r["ab"] - 1e-9 and 1.30 <= r["q"] <= 2.00])
