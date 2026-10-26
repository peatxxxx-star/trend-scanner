"""BL vs. bet365 (BetsAPI-Quotenhistorie aus den Scanner-Läufen): Tore-Hauptlinie (1_3) und 1. HZ (1_6).
Nur exakte x.5-Linien (keine Viertel-Linien). bet365-Stand: letzter Eintrag VOR dem BL-Archivabzug."""
import json, glob, gzip, re, time
import pandas as pd, numpy as np
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
rows = []
for f in sorted(glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz")):
    D = json.load(gzip.open(f, "rt"))
    az = time.mktime(time.strptime(D["info"]["zeit"], "%Y-%m-%d %H:%M UTC")) - time.timezone
    for g in D["spiele"]:
        ev = str(g.get("ev") or ""); e = g.get("erg") or {}
        if not ev or not e or e.get("len") not in (None, 90): continue
        for mk, key, ek in (("1_3", "goals", "goals"), ("1_6", "goals_h1", "ht_goals")):
            hist = OD.get((ev, mk))
            lad = (g.get("m") or {}).get(key) or {}
            if not hist or not lad: continue
            v = e.get(ek)
            if not v or v[0] is None: continue
            tot = v[0] if (ek == "ht_goals" and v[1] == -1) else (v[0] + v[1] if min(v) >= 0 else None)
            if tot is None: continue
            vor = [x for x in hist.values() if int(x.get("add_time") or 0) <= az + 600 and x.get("over_od") not in (None, "-")]
            if not vor: continue
            for x in sorted(vor, key=lambda x: -int(x["add_time"]))[:1]:
                hc = x["handicap"]
                if "," in hc or abs(float(hc) % 1 - 0.5) > 1e-9: continue
                L = float(hc); lk = f"{L:g}"
                qo, qu = lad.get("o" + lk), lad.get("u" + lk)
                bo, bu = float(x["over_od"]), float(x["under_od"])
                if not qo or not qu or bo <= 1 or bu <= 1: continue
                p_bl = (1 / qo) / (1 / qo + 1 / qu); p_b = (1 / bo) / (1 / bo + 1 / bu)
                rows.append(dict(ev=ev, mk=key, L=L, tag=f[-16:-8], qo=qo, qu=qu, bo=bo, bu=bu, p_bl=p_bl, p_b365=p_b,
                                 alter_h=(az - int(x["add_time"])) / 3600, over=int(tot > L)))
R = pd.DataFrame(rows); R.to_csv(f"{SP}/bulk/b365.csv", index=False)
print(len(R), "Spiel-Linien mit BL + bet365 am selben Stand;", R.ev.nunique(), "Spiele")
print(R.groupby("mk").agg(n=("ev", "size"), over=("over", "mean"), p_bl=("p_bl", "mean"), p_b365=("p_b365", "mean")).round(3))
br = lambda p, y: np.mean((p - y) ** 2)
for mk, x in R.groupby("mk"):
    print(f"\n{mk}: Brier BL {br(x.p_bl, x.over):.4f} | bet365 {br(x.p_b365, x.over):.4f} | Mittel {br((x.p_bl + x.p_b365) / 2, x.over):.4f}")
    x = x.assign(diff=x.p_b365 - x.p_bl)
    for lo, hi in ((-1, -.06), (-.06, -.03), (-.03, -.01), (-.01, .01), (.01, .03), (.03, .06), (.06, 1)):
        y = x[(x["diff"] >= lo) & (x["diff"] < hi)]
        if len(y) < 10: continue
        ro = (y.over * y.qo - 1).mean(); ru = ((1 - y.over) * y.qu - 1).mean()
        print(f"  bet365 − BL (Über) {lo:+.2f}…{hi:+.2f}: n={len(y):4d} Über tatsächlich {y.over.mean():.0%} | BL {y.p_bl.mean():.0%} bet365 {y.p_b365.mean():.0%} | ROI BL-Über {ro:+.1%} BL-Unter {ru:+.1%}")
    # Wette bei BL, wenn BL-Quote über dem bet365-Fairpreis liegt (Value gegen bet365)
    for thr in (0.0, 0.02, 0.04, 0.06):
        vo = x.qo * x.p_b365 - 1; vu = x.qu * (1 - x.p_b365) - 1
        so = x[vo > thr]; su = x[vu > thr]
        roi = pd.concat([so.over * so.qo - 1, (1 - su.over) * su.qu - 1])
        print(f"  Value gegen bet365-Fair > {thr:.0%}: n={len(roi):4d} ROI {roi.mean():+.1%}  (Über {len(so)}, Unter {len(su)})")
