import json, glob, gzip, sys, time
from collections import defaultdict
sys.path.insert(0, "/home/claude/trend-scanner")
import scan
cache = scan.load_cache()
erg = {}
for f in sorted(glob.glob("runs/ergebnisse_*.json")):
    for k, v in json.load(open(f)).items():
        if str(v.get("time_status")) == "3": erg[str(k)] = v["slim"]
for f in sorted(glob.glob("runs/archiv/bl_*.json.gz")):
    for g in json.load(gzip.open(f))["spiele"]:
        if g.get("erg") and g.get("ev") and str(g["ev"]) not in erg: erg[str(g["ev"])] = g["erg"]
tipps = {}
for f in sorted(glob.glob("runs/2026-10-[12][0-9]_*.json")):
    if "ergeb" in f or "dump" in f or "prewarm" in f: continue
    try: d = json.load(open(f))
    except Exception: continue
    try: lauf_ts = time.mktime(time.strptime(f[5:20], "%Y-%m-%d_%H%M")) - time.timezone
    except Exception: continue
    q = {t[0]: t[2] for t in (d.get("betlabel") or {}).get("tipps") or [] if t[2]}
    for h in d.get("hits") or []:
        m = h["match"]
        if m.get("kickoff_ts", 0) <= lauf_ts: continue
        for s in h["signals"]:
            if not s["metric_key"].startswith("team_corners") or s["direction"] != "unter": continue
            k = f'{m["id"]}|{s["metric_key"]}|{s["direction"]}|{s["line"]}'
            if k in q: tipps[k] = (m, s, q[k])
rows = []
for k, (m, s, quote) in tipps.items():
    st = erg.get(str(m["id"])) or cache.get(m["id"])
    if not st or not st.get("corners") or st["corners"][0] is None: continue
    seite = s["metric_key"].split("_")[-1]
    v = st["corners"][0] if seite == "heim" else st["corners"][1]
    hit = v < s["line"]
    try: mn, _ = scan.play_min(s)
    except Exception: mn = None
    spielbar = bool(mn) and quote >= mn - 1e-9 and 1.30 <= quote <= 2.00
    x = s.get("vp_1x2")
    own = None
    try: own = float(x[0] if seite == "heim" else x[2])
    except Exception: pass
    rows.append(dict(seite=seite, own=own, q=quote, hit=hit, spielbar=spielbar))
def line(lbl, rs):
    if not rs: print(f"   {lbl:34s} n=0"); return
    n = len(rs); h = sum(r["hit"] for r in rs); ret = sum(r["q"] for r in rs if r["hit"]); aq = sum(r["q"] for r in rs) / n
    print(f"   {lbl:34s} {h:3d}/{n:<3d} = {100*h/n:3.0f}%  Ø {aq:.2f} nötig {100/aq:3.0f}%  ROI {100*(ret/n-1):+4.0f}%")
def bucket(o):
    if o is None: return "unbekannt"
    return "klarer Fav. (<1,60)" if o < 1.6 else "Favorit (1,60–1,99)" if o < 2.0 else "leicht/ausgegl. (2,00–2,79)" if o < 2.8 else "Außenseiter (≥2,80)"
for lbl, sel in (("BL-Liste (spielbar)", lambda r: r["spielbar"]), ("alle mit BL-Quote", lambda r: True)):
    print(f"\n== Team-Ecken unter, {lbl}")
    for seite in ("heim", "gast"):
        rs = [r for r in rows if sel(r) and r["seite"] == seite]
        line(f"{seite.upper()} gesamt", rs)
        g = defaultdict(list)
        for r in rs: g[bucket(r["own"])].append(r)
        for b in ("klarer Fav. (<1,60)", "Favorit (1,60–1,99)", "leicht/ausgegl. (2,00–2,79)", "Außenseiter (≥2,80)", "unbekannt"):
            line("  " + b, g.get(b, []))
