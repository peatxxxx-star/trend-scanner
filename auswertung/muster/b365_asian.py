"""Konvertierungsfrei: bet365-Asian-Linie (x.0, x.25, x.75) gegen dieselbe Wette bei BL (Viertel = halber Einsatz auf
jede der beiden BL-Linien). Faire Über-Quote beider Seiten (Marge proportional raus), Wette bei BL in Richtung bet365."""
import json, glob, gzip, re, time, math
import pandas as pd, numpy as np
from scipy.optimize import brentq
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
def lk(L): return f"{L:g}"
def settle(L, tot, over):
    """Gewinnanteil je Einheit bei Quote q: liefert (win, push) für eine Einzellinie"""
    if abs(L % 1) < 1e-9 and tot == L: return "push"
    return "win" if ((tot > L) == over) else "loss"
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
            hcs = [float(p) for p in x["handicap"].split(",")]
            if len(hcs) == 1 and abs(hcs[0] % 1 - .5) < 1e-9: continue      # exakte x.5 schon getestet
            bo, bu = float(x["over_od"]), float(x["under_od"])
            if bo <= 1 or bu <= 1: continue
            qs = []
            for L in hcs:
                qo, qu = lad.get("o" + lk(L)), lad.get("u" + lk(L))
                if not qo or not qu: break
                qs.append((L, qo, qu))
            if len(qs) != len(hcs): continue
            # Wahrscheinlichkeitsmaß "fair" je Seite: bet365 -> Anteil Über = (1/bo)/(1/bo+1/bu); BL-Kombi analog:
            # effektive Kombi-Quote über halbe Einsätze ≈ Mittel der Einzelquoten (Näherung nur für den Vergleich)
            bl_o = np.mean([q[1] for q in qs]); bl_u = np.mean([q[2] for q in qs])
            p_bl = (1 / bl_o) / (1 / bl_o + 1 / bl_u); p_b = (1 / bo) / (1 / bo + 1 / bu)
            # echte Abrechnung der BL-Kombi
            res = {}
            for side in (True, False):
                r = 0
                for L, qo, qu in qs:
                    s = settle(L, tot, side); q = qo if side else qu
                    r += (q - 1 if s == "win" else 0 if s == "push" else -1) / len(qs)
                res[side] = r
            rows.append(dict(ev=ev, mk=key, tag=tag, hc=x["handicap"], p_bl=p_bl, p_b365=p_b, bl_o=bl_o, bl_u=bl_u, bo=bo, bu=bu,
                             r_over=res[True], r_under=res[False], alter_h=(az - int(x["add_time"])) / 3600))
R = pd.DataFrame(rows); R["diff"] = R.p_b365 - R.p_bl
R.to_csv(f"{SP}/bulk/b365_asian.csv", index=False)
print(len(R), "Spiel×Markt mit Viertel-/Ganzzahl-Linie bei beiden")
print("blind: Über", R.r_over.mean().round(3), "Unter", R.r_under.mean().round(3), "| Ø |diff|", R["diff"].abs().mean().round(3))
for thr in (0.005, 0.01, 0.015, 0.02, 0.03):
    out = []
    for a, b in (("2026-10-15", "2026-10-20"), ("2026-10-21", "2026-10-26"), ("2026-10-15", "2026-10-26")):
        y = R[(R.tag >= a) & (R.tag <= b)]
        r = pd.concat([y[y["diff"] >= thr].r_over, y[y["diff"] <= -thr].r_under])
        out.append(f"n={len(r):4d} {r.mean():+6.1%}")
    for mk in ("goals", "goals_h1"):
        y = R[R.mk == mk]; r = pd.concat([y[y["diff"] >= thr].r_over, y[y["diff"] <= -thr].r_under]); out.append(f"{mk} n={len(r)} {r.mean():+.1%}")
    print(f"≥{thr:.3f}  15–20 {out[0]} | 21–25 {out[1]} | gesamt {out[2]} | {out[3]} | {out[4]}")
