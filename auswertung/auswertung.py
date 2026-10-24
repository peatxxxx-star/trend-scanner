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
for f in sorted(glob.glob("runs/2026-10-1[5-9]_*.json")):
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
def tab(titel, keyf, nur=lambda r: True, min_n=5):
    g = defaultdict(list)
    for r in rows:
        if nur(r): g[keyf(r)].append(r)
    print(f"\n== {titel}")
    print(f"   {'':32s}{'n':>5s}{'Treffer':>9s}{'Ø Quote':>9s}{'nötig':>7s}{'ROI':>8s}")
    for key, rs in sorted(g.items(), key=lambda x: -len(x[1])):
        if len(rs) < min_n: continue
        n = len(rs); h = sum(r["hit"] for r in rs); ret = sum(r["q"] for r in rs if r["hit"])
        avgq = sum(r["q"] for r in rs) / n
        print(f"   {str(key)[:32]:32s}{n:5d}{100*h/n:8.0f}%{avgq:9.2f}{100/avgq:6.0f}%{100*(ret/n-1):+7.0f}%")
sp = lambda r: r["spielbar"]
print("Tipps mit BL-Quote gesamt:", len(tipps))
print("Tipps mit BL-Quote und Ergebnis:", len(rows), "· davon spielbar (BL-Liste):", sum(sp(r) for r in rows))
tab("GESAMT", lambda r: "spielbar (BL-Liste)" if r["spielbar"] else "nicht spielbar (unter ab)", min_n=1)
tab("Spielbar nach Markt", lambda r: r["markt"], sp)
def qb(q): return "<1.30" if q < 1.3 else "1.30-1.49" if q < 1.5 else "1.50-1.79" if q < 1.8 else "≥1.80"
tab("Spielbar nach Quote", lambda r: qb(r["q"]), sp, 1)
tab("Spielbar nach Hinweis", lambda r: {"ok": "✅ ohne Hinweis", "warn": "⚠️ mit Hinweis"}.get(r["stat"], r["stat"]), sp, 1)
tab("Spielbar nach Tag", lambda r: r["tag"], sp, 1)
tab("Spielbar Jugend/Reserve", lambda r: "Jugend/Reserve" if r["youth"] else "Profi", sp, 1)
tab("Spielbar nach Liga (n≥8)", lambda r: r["liga"], sp, 8)
tab("Spielbar nach Markt (alle)", lambda r: r["markt"], sp, 2)
def ab(r):
    x = r["q"] / r["fair"] if r["fair"] else 0
    return "bis +10 % über fair" if x < 1.10 else "+10 bis +25 %" if x < 1.25 else "über +25 %"
tab("Spielbar nach Abstand zur fairen Quote", ab, sp, 1)
tab("ALLE Tipps mit BL-Quote nach Markt (Trefferquote-Check)", lambda r: r["markt"], min_n=15)
