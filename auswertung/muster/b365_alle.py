"""Wie b365_vergleich, aber auch Viertel-/Ganzzahl-Linien: bet365-Asian-Linie -> Poisson-λ -> faire P(Über x.5)
für die BL-x.5-Linie(n) direkt neben der bet365-Linie. Eine Zeile je Spiel×Markt (BL-Linie am nächsten an 50 %)."""
import json, glob, gzip, re, time, math
import pandas as pd, numpy as np
from scipy.optimize import brentq
from scipy.stats import poisson
REPO = "/home/claude/trend-scanner"; SP = "/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad"
OD = {}
for f in sorted(glob.glob(f"{REPO}/runs/2026-10-*_*.json")):
    nm = f.split("/")[-1]
    if not re.match(r"2026-10-\d\d_\d{4}\.json$", nm) or nm < "2026-10-14": continue
    try: d = json.load(open(f))
    except Exception: continue
    for sec in ("hits", "team_totals"):
        for h in d.get(sec) or []:
            m = h.get("match") or {}
            o = ((m.get("_vp_odds") or {}).get("results") or {}).get("odds") or {}
            for mk in ("1_3", "1_6"):
                for e in o.get(mk) or []:
                    OD.setdefault((str(m.get("id")), mk), {})[e["id"]] = e
def ev_over(lam, parts):
    """erwarteter Gewinn je 1 € auf Über (faire Quote o) als Funktion – gibt P-Anteile zurück"""
    pass
def solve(hc, fo, fu):
    parts = [float(p) for p in hc.split(",")]
    def f(lam):
        tot = 0
        for L in parts:
            if abs(L % 1 - .5) < 1e-9:
                pw = 1 - poisson.cdf(math.floor(L), lam); tot += pw * fo - 1
            else:
                pw = 1 - poisson.cdf(L, lam); pp = poisson.pmf(L, lam); pl = 1 - pw - pp
                tot += pw * (fo - 1) - pl
        return tot / len(parts)
    try: return brentq(f, 0.05, 12)
    except Exception: return None
rows = []
for f in sorted(glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz")):
    D = json.load(gzip.open(f, "rt")); tag = re.search(r"bl_(\S+)\.json", f).group(1)
    az = time.mktime(time.strptime(D["info"]["zeit"], "%Y-%m-%d %H:%M UTC")) - time.timezone
    for g in D["spiele"]:
        ev = str(g.get("ev") or ""); e = g.get("erg") or {}
        if not ev or not e or e.get("len") not in (None, 90): continue
        for mk, key, ek in (("1_3", "goals", "goals"), ("1_6", "goals_h1", "ht_goals")):
            hist = OD.get((ev, mk)); lad = (g.get("m") or {}).get(key) or {}
            if not hist or not lad: continue
            v = e.get(ek)
            if not v or v[0] is None: continue
            tot = v[0] if (ek == "ht_goals" and v[1] == -1) else (v[0] + v[1] if min(v) >= 0 else None)
            if tot is None: continue
            vor = [x for x in hist.values() if int(x.get("add_time") or 0) <= az + 600 and x.get("over_od") not in (None, "-")]
            if not vor: continue
            x = max(vor, key=lambda x: int(x["add_time"]))
            bo, bu = float(x["over_od"]), float(x["under_od"])
            if bo <= 1 or bu <= 1: continue
            s = 1 / bo + 1 / bu; fo, fu = bo * s, bu * s
            lam = solve(x["handicap"], fo, fu)
            if not lam: continue
            best = None
            for lk, qo in lad.items():
                if lk[0] != "o": continue
                L = float(lk[1:])
                if abs(L % 1 - .5) > 1e-9: continue
                qu = lad.get("u" + lk[1:])
                if not qu: continue
                p_bl = (1 / qo) / (1 / qo + 1 / qu)
                if best is None or abs(p_bl - .5) < abs(best[3] - .5):
                    best = (L, qo, qu, p_bl)
            if not best: continue
            L, qo, qu, p_bl = best
            hcs = [float(p) for p in x["handicap"].split(",")]
            if min(abs(L - h) for h in hcs) > 0.5: continue        # nur direkt benachbarte Linien
            p_b = 1 - poisson.cdf(math.floor(L), lam)
            rows.append(dict(ev=ev, mk=key, tag=tag, L=L, hc=x["handicap"], exakt=int(len(hcs) == 1 and abs(hcs[0] % 1 - .5) < 1e-9 and hcs[0] == L),
                             qo=qo, qu=qu, p_bl=p_bl, p_b365=p_b, alter_h=(az - int(x["add_time"])) / 3600, over=int(tot > L)))
R = pd.DataFrame(rows); R.to_csv(f"{SP}/bulk/b365_alle.csv", index=False)
R["diff"] = R.p_b365 - R.p_bl
print(len(R), "Spiel×Markt;", R.exakt.sum(), "exakte Linie")
print("Poisson-Kalibrierung (Viertel): Ø p_b365", R[R.exakt == 0].p_b365.mean().round(3), "Ø p_bl", R[R.exakt == 0].p_bl.mean().round(3), "Über", R[R.exakt == 0].over.mean().round(3))
for thr in (0.01, 0.015, 0.02, 0.03):
    for nm, x in (("exakt", R[R.exakt == 1]), ("Viertel/ganz", R[R.exakt == 0]), ("alle", R)):
        out = []
        for a, b in (("2026-10-15", "2026-10-20"), ("2026-10-21", "2026-10-26"), ("2026-10-15", "2026-10-26")):
            y = x[(x.tag >= a) & (x.tag <= b)]
            o = y[y["diff"] >= thr]; u = y[y["diff"] <= -thr]
            r = pd.concat([o.over * o.qo - 1, (1 - u.over) * u.qu - 1])
            out.append(f"n={len(r):3d} {r.mean():+6.1%}")
        print(f"≥{thr:.3f} {nm:12s} 15–20 {out[0]} | 21–25 {out[1]} | gesamt {out[2]}")
