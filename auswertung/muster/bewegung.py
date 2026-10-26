"""Quotenbewegung: BL-Quote im Marktarchiv (Tagesabzug ~11 Uhr) vs. stündliche BL-Quoten der Scanner-Läufe
(betlabel.tipps) bis Anstoß. Nur Gesamtmärkte (keine Heim/Gast-Orientierungsfragen)."""
import json, glob, gzip, re, time
import pandas as pd, numpy as np
REPO = "/home/claude/trend-scanner"
SP = "/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad"
ARCH, ERG, KO, AZ = {}, {}, {}, {}
for f in sorted(glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz")):
    D = json.load(gzip.open(f, "rt"))
    try:
        az = time.mktime(time.strptime(D["info"]["zeit"], "%Y-%m-%d %H:%M UTC")) - time.timezone
    except Exception:
        az = None
    for g in D["spiele"]:
        ev = str(g.get("ev") or "")
        if not ev: continue
        ARCH[ev] = g["m"]; KO[ev] = int(g["S"]); AZ[ev] = az
        if g.get("erg"): ERG[ev] = g["erg"]
for f in sorted(glob.glob(f"{REPO}/runs/ergebnisse_*.json")):
    for k, v in json.load(open(f)).items():
        if str(v.get("time_status")) == "3": ERG.setdefault(str(k), v.get("slim") or {})
MK = {"corners": "corners", "goals": "goals", "yellowcards": "yellowcards", "on_target": "on_target", "offsides": "offsides"}
obs = {}
for f in sorted(glob.glob(f"{REPO}/runs/2026-10-*_*.json")):
    nm = f.split("/")[-1]
    if not re.match(r"2026-10-\d\d_\d{4}\.json$", nm) or nm < "2026-10-14": continue
    try: d = json.load(open(f))
    except Exception: continue
    ts = time.mktime(time.strptime(nm[:15], "%Y-%m-%d_%H%M")) - time.timezone
    for t in (d.get("betlabel") or {}).get("tipps") or []:
        if not t[2]: continue
        ev, met, rich, L = t[0].split("|")
        if met not in MK: continue
        obs.setdefault(t[0], []).append((ts, float(t[2])))
rows = []
for k, lst in obs.items():
    ev, met, rich, L = k.split("|")
    ko = KO.get(ev)
    if not ko: continue
    lst = sorted(x for x in lst if x[0] < ko)
    if not lst: continue
    lad = (ARCH.get(ev) or {}).get(MK[met]) or {}
    lk = ("o" if rich == "über" else "u") + (L[:-2] if L.endswith(".0") else L)
    qa = lad.get(lk); qo = lad.get(("u" if rich == "über" else "o") + lk[1:])
    e = ERG.get(ev) or {}
    v = e.get(met)
    if not v or v[0] is None or min(v) < 0 or e.get("len") not in (None, 90): continue
    val = v[0] + v[1]; Lf = float(L)
    hit = val > Lf if rich == "über" else val < Lf
    if Lf == int(Lf) and val == Lf: continue   # Push raus
    az = AZ.get(ev)
    rows.append(dict(key=k, ev=ev, met=met, dir=rich, line=Lf, ko=ko, q_arch=qa, q_opp=qo, az=az,
                     q_first=lst[0][1], t_first=lst[0][0], q_last=lst[-1][1], t_last=lst[-1][0], n=len(lst),
                     q_max=max(x[1] for x in lst), q_min=min(x[1] for x in lst), hit=int(hit)))
R = pd.DataFrame(rows)
R["h_vor_ko_last"] = (R.ko - R.t_last) / 3600
R["h_vor_ko_first"] = (R.ko - R.t_first) / 3600
R.to_csv(f"{SP}/bulk/bewegung.csv", index=False)
print(len(R), "Tipps mit Ergebnis;", R.q_arch.notna().sum(), "auch im Archiv")
pd.set_option("display.width", 220)


def roi(q, h): return (h * q - 1).mean()


X = R[(R.n >= 2)].copy()
X["mv"] = X.q_last / X.q_first - 1
print(f"\nErste vs. letzte Scanner-Quote (≥2 Läufe): {len(X)} | Ø Stunden zwischen: {(X.t_last - X.t_first).mean() / 3600:.1f}")
print(f"  gefallen {(X.mv < -0.005).mean():.0%}, gleich {(X.mv.abs() <= 0.005).mean():.0%}, gestiegen {(X.mv > 0.005).mean():.0%}")
print(f"  ROI zur ersten Quote {roi(X.q_first, X.hit):+.1%} | zur letzten {roi(X.q_last, X.hit):+.1%} | zur besten {roi(X.q_max, X.hit):+.1%}")
for lab, m in (("gefallen", X.mv < -0.005), ("gleich", X.mv.abs() <= 0.005), ("gestiegen", X.mv > 0.005)):
    y = X[m]
    if len(y): print(f"  {lab:9s} n={len(y):4d} Treffer {y.hit.mean():.0%} | nötig (1/q erste) {np.mean(1 / y.q_first):.0%} | ROI erste {roi(y.q_first, y.hit):+.1%} letzte {roi(y.q_last, y.hit):+.1%}")
print("\nje Markt:")
for (met, di), y in X.groupby(["met", "dir"]):
    if len(y) >= 30:
        print(f"  {met:12s} {di:5s} n={len(y):4d} ROI erste {roi(y.q_first, y.hit):+.1%} letzte {roi(y.q_last, y.hit):+.1%} | gefallen {(y.mv < -0.005).mean():.0%} gestiegen {(y.mv > 0.005).mean():.0%}")
A = R[R.q_arch.notna()].copy()
A["mv"] = A.q_last / A.q_arch - 1
A = A[A.t_last > A.az]           # letzte Scanner-Quote nach dem Archivabzug
print(f"\nArchiv (Vormittag) vs. letzte Quote vor Anstoß: {len(A)} | Ø Stunden Archiv→letzte {(A.t_last - A.az).mean() / 3600:.1f}")
print(f"  gefallen {(A.mv < -0.005).mean():.0%}, gleich {(A.mv.abs() <= 0.005).mean():.0%}, gestiegen {(A.mv > 0.005).mean():.0%}")
print(f"  ROI Archivquote {roi(A.q_arch, A.hit):+.1%} | letzte {roi(A.q_last, A.hit):+.1%}")
for lab, m in (("gefallen", A.mv < -0.005), ("gleich", A.mv.abs() <= 0.005), ("gestiegen", A.mv > 0.005)):
    y = A[m]
    if len(y): print(f"  {lab:9s} n={len(y):4d} Treffer {y.hit.mean():.0%} | nötig {np.mean(1 / y.q_arch):.0%} | ROI Archiv {roi(y.q_arch, y.hit):+.1%} letzte {roi(y.q_last, y.hit):+.1%}")
for (met, di), y in A.groupby(["met", "dir"]):
    if len(y) >= 30:
        print(f"  {met:12s} {di:5s} n={len(y):4d} ROI Archiv {roi(y.q_arch, y.hit):+.1%} letzte {roi(y.q_last, y.hit):+.1%} | gefallen {(y.mv < -0.005).mean():.0%} gestiegen {(y.mv > 0.005).mean():.0%}")
