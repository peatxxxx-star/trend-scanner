"""Massensuche: je Marktgruppe (Basis|HZ|Seite|Richtung) alle Einzel- und Paar-Bedingungen über ~26 Merkmale.
Suche 15.–20.10., Gegenprobe 21.–25.10. Jedes Spiel zählt je Gruppe 1x (Gewicht 1/Linien).
Nullmodell: Anteil Suche-bestanden × Anteil Gegenprobe-bestanden (= erwartete Überlebende, wenn
Muster nicht von einem Zeitraum in den nächsten tragen)."""
import sys, json
import pandas as pd, numpy as np
from scipy.stats import spearmanr
SP = "/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad"
d = pd.read_parquet(f"{SP}/bulk/bulk.parquet")
PERM = int(sys.argv[2]) if len(sys.argv) > 2 else -1
MIN_TR, MIN_TE, ROI_MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 40, 30, 0.05
CONT = ["p_nv", "q", "p_team", "p_draw", "overround", "staerke", "line", "mdev", "d3", "d5", "d10", "d15",
        "dv5", "dv10", "trend", "lgd", "dom", "x_sot", "x_goals", "x_corn", "x_fouls", "streu"]
BINSETS = {"Q1": [0], "Q2": [1], "Q3": [2], "Q4": [3], "Q5": [4], "Q1-2": [0, 1], "Q4-5": [3, 4]}
d["tr"] = d.tag <= "2026-10-20"
d["te"] = (d.tag >= "2026-10-21") & (d.tag <= "2026-10-25")
d["w"] = 1 / d.groupby(["grp", "ev"]).roi.transform("size")
if PERM >= 0:
    rng = np.random.default_rng(PERM)
    d["pdec"] = d.groupby(["grp", "line"]).p_nv.transform(lambda v: pd.qcut(v.rank(method="first"), min(10, len(v)), labels=False) if len(v) > 1 else 0)
    te = d[d.te]
    hp = te.groupby(["grp", "line", "pdec"]).hit.transform(lambda h: rng.permutation(h.values))
    d.loc[d.te, "hit"] = hp
    d["roi"] = d.hit * d.q - 1
res, stat = [], []
for grp, x in d.groupby("grp"):
    x = x.reset_index(drop=True)
    if x[x.tr].ev.nunique() < 2 * MIN_TR:
        continue
    conds, names = [], []
    for f in CONT:
        v = x[f]
        if v.notna().mean() < 0.3 or v[x.tr].nunique() < 5:
            continue
        qs = np.nanquantile(v[x.tr], [.2, .4, .6, .8])
        b = np.digitize(v, qs)
        b = np.where(v.isna(), -1, b)
        for nm, bs in BINSETS.items():
            conds.append(np.isin(b, bs)); names.append(f"{f}:{nm}[{'|'.join(f'{qs[i]:.3g}' if 0 <= i < 4 else '' for i in (bs[0] - 1, bs[-1]))}]")
    for nm, m in (("früh<15h", x.stunde < 15), ("15-18h", (x.stunde >= 15) & (x.stunde < 18)), ("18-21h", (x.stunde >= 18) & (x.stunde < 21)),
                  ("spät≥21h", x.stunde >= 21), ("Wochenende", x.wochenende == 1), ("unter der Woche", x.wochenende == 0),
                  ("Jugend/Frauen/II", x.jugend == 1), ("keine Jugend", x.jugend == 0), ("Pokal", x.pokal == 1), ("Liga", x.pokal == 0)):
        conds.append(m.values); names.append(nm)
    C = np.column_stack(conds).astype(np.float64)
    feat_of = [n.split(":")[0] for n in names]
    out = {}
    for per in ("tr", "te"):
        msk = x[per].values.astype(float)
        w = x.w.values * msk
        wr = w * x.roi.values
        Nn = C.T @ (C * w[:, None])          # Paar: Summe Gewichte
        Rr = C.T @ (C * wr[:, None])
        out[per] = (Nn, Rr)
    k = len(names)
    iu = np.triu_indices(k)               # inkl. Diagonale = Einzelbedingung
    ntr, rtr = out["tr"][0][iu], out["tr"][1][iu]
    nte, rte = out["te"][0][iu], out["te"][1][iu]
    same = np.array([feat_of[i] == feat_of[j] and i != j for i, j in zip(*iu)])
    ok = (~same) & (ntr >= MIN_TR) & (nte >= MIN_TE)
    roi_tr = np.divide(rtr, ntr, out=np.zeros_like(rtr), where=ntr > 0)
    roi_te = np.divide(rte, nte, out=np.zeros_like(rte), where=nte > 0)
    a = (roi_tr[ok] >= ROI_MIN); b = (roi_te[ok] >= ROI_MIN)
    surv = a & b
    n_ok = ok.sum()
    rho = spearmanr(roi_tr[ok], roi_te[ok]).correlation if n_ok > 10 else np.nan
    stat.append(dict(grp=grp, segmente=int(n_ok), such_ok=int(a.sum()), gegen_ok=int(b.sum()), ueberlebt=int(surv.sum()),
                     erwartet_zufall=round(a.sum() * b.sum() / max(n_ok, 1), 1), rho=round(rho, 3),
                     roi_gruppe_tr=round(x[x.tr].roi.mul(x[x.tr].w).sum() / x[x.tr].w.sum(), 3),
                     roi_gruppe_te=round(x[x.te].roi.mul(x[x.te].w).sum() / x[x.te].w.sum(), 3)))
    I, J = iu[0][ok][surv], iu[1][ok][surv]
    for i, j, a1, a2, b1, b2 in zip(I, J, ntr[ok][surv], roi_tr[ok][surv], nte[ok][surv], roi_te[ok][surv]):
        res.append(dict(grp=grp, c1=names[i], c2=names[j] if i != j else "", n_tr=round(a1), roi_tr=round(a2, 3), n_te=round(b1), roi_te=round(b2, 3)))
S = pd.DataFrame(stat)
pd.set_option("display.width", 250)
print(S.to_string())
print("\nSUMME: Segmente", S.segmente.sum(), "| überlebt", S.ueberlebt.sum(), "| erwartet durch Zufall", round(S.erwartet_zufall.sum(), 1))
R = pd.DataFrame(res)
R.to_csv(f"{SP}/bulk/ueberlebende.csv" if PERM < 0 else f"{SP}/bulk/perm_{PERM}.csv", index=False)
S.to_csv(f"{SP}/bulk/stat_{PERM}.csv", index=False)
if len(R):
    R["min_roi"] = R[["roi_tr", "roi_te"]].min(axis=1)
    print(R.sort_values("min_roi", ascending=False).head(60).to_string())
