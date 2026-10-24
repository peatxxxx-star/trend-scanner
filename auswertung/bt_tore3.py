import json, sys, time, gzip, glob
from collections import defaultdict
sys.path.insert(0, "/home/claude/trend-scanner")
import scan
cache = scan.load_cache()
H = json.load(open("/home/claude/trend-scanner/cache/history.json"))
scan.EXCLUDED_LINES = {x for x in scan.EXCLUDED_LINES if x[0] != "goals"}
scan.EXCLUDED_MARKETS = {x for x in scan.EXCLUDED_MARKETS if x[0] != "goals"}
ev = {}
for tid, v in H.items():
    evs = scan.drop_friendlies(v.get("events") or [])
    for i, e in enumerate(evs):
        ev.setdefault(e["id"], []).append((tid, e, evs[i+1:]))
rows = []
for eid, lst in ev.items():
    if len(lst) != 2: continue
    own = cache.get(eid)
    if not own or scan.metric_total({"stats": own}, "goals") is None: continue
    (ta, ea, oa), (tb, eb, ob) = lst
    if not ea["h"]: (ta, ea, oa), (tb, eb, ob) = (tb, eb, ob), (ta, ea, oa)
    mk = lambda older: [{"stats": cache.get(e["id"], {}), "is_home": e["h"], "label": e["l"]} for e in older]
    match = {"id": eid, "league": ea.get("lg", ""), "home": ea["l"].split(" - ")[0], "away": ea["l"].split(" - ")[-1],
             "home_id": ta, "away_id": tb, "kickoff": "", "kickoff_ts": ea.get("t", 0)}
    sigs = scan.evaluate_match(match, mk(oa), mk(ob))
    g = scan.metric_total({"stats": own}, "goals")
    for s in sigs:
        if s["metric_key"] != "goals": continue
        scan.assess_signal(s)
        L = s["line"]; hit = g > L if s["direction"] == "über" else g < L
        rows.append(dict(eid=eid, d=s["direction"], L=L, p=s.get("p_fin"), pm=s.get("p_mod"), fair=s.get("fair_fin"), hit=hit, t=ea.get("t", 0), lg=ea.get("lg","")))
json.dump(rows, open("auswertung/bt_tore_rows.json", "w"))
agg = defaultdict(list)
for r in rows: agg[(r["d"], r["L"])].append(r)
for k in sorted(agg):
    rs = [r for r in agg[k] if r["p"]]; n = len(rs)
    if n < 20: continue
    h = sum(r["hit"] for r in rs); pm = sum(r["p"] for r in rs)/n
    print(f"Tore {k[0]} {k[1]}: n={n:5d} Treffer {100*h/n:4.1f}%  angezeigt (p_fin) {100*pm:4.1f}%  Ø fair {sum(r['fair'] for r in rs)/n:.2f}")
    rs.sort(key=lambda r: r["p"]); q = n//4
    for i in range(4):
        t = rs[i*q:(i+1)*q] if i < 3 else rs[3*q:]
        print(f"     Quartil {i+1}: angezeigt {100*sum(r['p'] for r in t)/len(t):4.1f}%  echt {100*sum(r['hit'] for r in t)/len(t):4.1f}%  n={len(t)}")
