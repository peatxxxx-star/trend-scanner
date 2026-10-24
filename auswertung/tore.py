import json, glob, gzip, sys, time
from collections import defaultdict
sys.path.insert(0, "/home/claude/trend-scanner")
import scan
cache = scan.load_cache()
# --- Ergebnisse sammeln
erg = {}
for f in sorted(glob.glob("runs/ergebnisse_*.json")):
    for k, v in json.load(open(f)).items():
        if str(v.get("time_status")) == "3": erg[k] = v["slim"]
for f in sorted(glob.glob("runs/archiv/bl_*.json.gz")):
    d = json.load(gzip.open(f)); sp = d["spiele"] if isinstance(d, dict) else d
    for g in sp:
        if g.get("erg") and g.get("ev") and str(g["ev"]) not in erg: erg[str(g["ev"])] = g["erg"]
def result(eid):
    if eid in erg: return erg[eid]
    st = cache.get(eid)
    return st
# --- Tipps sammeln: letzter Lauf vor Anpfiff mit BL-Quote zählt
tipps = {}
for f in sorted(glob.glob("runs/2026-10-[12][0-9]_*.json")):
    if "ergeb" in f or "dump" in f: continue
    d = json.load(open(f))
    try: lauf_ts = time.mktime(time.strptime(f[5:20], "%Y-%m-%d_%H%M")) - time.timezone  # UTC
    except Exception: continue
    q = {t[0]: t[2] for t in (d.get("betlabel") or {}).get("tipps") or [] if t[2]}
    for h in d.get("hits") or []:
        m = h["match"]
        if m.get("kickoff_ts", 0) <= lauf_ts: continue
        for s in h["signals"]:
            k = f'{m["id"]}|{s["metric_key"]}|{s["direction"]}|{s["line"]}'
            if k not in q: continue
            tipps[k] = (m, s, q[k])
rows = []
for k, (m, s, quote) in tipps.items():
    st = result(m["id"])
    if not st: continue
    mk = s["metric_key"]
    if mk.startswith("team_"):
        base = "_".join(mk.split("_")[1:-1]); seite = mk.split("_")[-1]
        if scan.metric_total({"stats": st}, base) is None: continue
        p = st.get(base); v = p[0] if seite == "heim" else p[1]; grp = "Team-" + base
    else:
        v = scan.metric_total({"stats": st}, mk); grp = mk
        if v is None: continue
    hit = v > s["line"] if s["direction"] == "über" else v < s["line"]
    try: mn, _ = scan.play_min(s)
    except Exception: mn = None
    try:
        vp = scan.vp_bewertung(m, s, quote); stat = "stop" if any(x[1]=="stop" for x in vp) else ("warn" if any(x[1]=="warn" for x in vp) else "ok")
    except Exception: stat = "?"
    spielbar = bool(mn) and quote >= mn - 1e-9 and stat != "stop"
    lg = m.get("league", "")
    rows.append(dict(markt=f"{grp} {s['direction']}", q=quote, hit=hit, spielbar=spielbar, stat=stat,
                     fair=s.get("fair_fin") or s.get("fair"), liga=lg, youth=scan.youth_or_reserve(m),
                     tag=time.strftime("%d.%m", time.gmtime(m["kickoff_ts"] + 7200))))
json.dump(rows, open("auswertung/rows.json", "w"))
from collections import defaultdict
g=[r for r in rows if r["markt"]=="goals über"]
def line(lbl, rs):
    if not rs: print(f"{lbl:34s} n=0"); return
    n=len(rs); h=sum(r["hit"] for r in rs); ret=sum(r["q"] for r in rs if r["hit"]); aq=sum(r["q"] for r in rs)/n
    print(f"{lbl:34s} n={n:3d}  Treffer {100*h/n:3.0f}%  Ø Quote {aq:.2f}  nötig {100/aq:3.0f}%  ROI {100*(ret/n-1):+4.0f}%")
pl=lambda r: r["spielbar"] and 1.30<=r["q"]<=2.00
line("Tore über 2.5 – alle mit BL-Quote", g)
line("  davon BL-Liste (≥ab, 1.30–2.00)", [r for r in g if pl(r)])
d=lambda r: (int(r["tag"][3:5]),int(r["tag"][:2]))
line("  BL-Liste vor 18.10.", [r for r in g if pl(r) and d(r)<(10,18)])
line("  BL-Liste ab 18.10. (ausgeblendet)", [r for r in g if pl(r) and d(r)>=(10,18)])
print()
byd=defaultdict(list)
for r in g:
    if pl(r): byd[r["tag"]].append(r)
for t in sorted(byd, key=lambda x:(x[3:5],x[:2])): line("  "+t, byd[t])
