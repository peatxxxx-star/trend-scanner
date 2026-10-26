"""Massensuche – Datensatz: jede spielbare BL-Linie (Quote 1,30–2,10) in Ecken/Tore/Abseits (+Gelb als Referenz)
mit ~25 Vorab-Merkmalen (BL-Preis, Team-Historie aus netz.parquet, Modellabweichung, Zeit, Wettbewerb)."""
import json, gzip, glob, re
import pandas as pd, numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
REPO = "/home/claude/trend-scanner"
SP = "/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad"
B = ZoneInfo("Europe/Berlin")

d = pd.read_csv(f"{SP}/bulk/ds_a.csv", dtype={"ev": str})
ok = (((d.base == "corners")) |
      ((d.base == "goals") & ((d.half == "ft") | ((d.half == "_h1") & (d.side == "tot")))) |
      ((d.base == "offsides") & (d.half == "ft")) |
      ((d.base == "yellowcards") & (d.half == "ft")))
d = d[ok & d.p_nv.notna() & (d.q >= 1.30) & (d.q <= 2.10)].copy()

# Anstoß + swap aus dem Archiv
S = {}
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f, "rt"))["spiele"]:
        if g.get("ev"):
            S[str(g["ev"])] = (int(g["S"]), bool(g.get("swap")))
d["ko"] = d.ev.map(lambda e: S.get(e, (0, 0))[0])
d["swap"] = d.ev.map(lambda e: S.get(e, (0, 0))[1])
dt = d.ko.map(lambda t: datetime.fromtimestamp(t, B))
d["stunde"] = dt.map(lambda x: x.hour)
d["wochenende"] = dt.map(lambda x: int(x.weekday() >= 5))
L = d.bl_liga.fillna("").str.lower()
d["jugend"] = L.str.contains(r"u1\d|u2\d|youth|junior|reserve| ii\b|women|frauen|\(w\)").astype(int)
d["pokal"] = L.str.contains(r"cup|pokal|copa|coupe|coppa|taça|beker").astype(int)

# BL-Preis-Merkmale
d["p_draw"] = 1 - d.p1 - d.p2
d["overround"] = 1 / d.q + 1 / pd.to_numeric(d.q_opp, errors="coerce")
d["staerke"] = (d.p1 - d.p2).abs()          # wie einseitig
d["p_team"] = pd.to_numeric(d.p_team, errors="coerce")

# Modellabweichung (Modelle trainiert vor 15.10.)
ek = pd.read_csv(f"{SP}/muster/ek_pred_netz+neu+wettb_gbr.csv", dtype={"ev": str},
                 usecols=["ev", "half", "side", "dir", "line", "p_m"])
ek["base"] = "corners"
tr = pd.read_csv(f"{SP}/muster/tr_pred_alles_gbr.csv", dtype={"ev": str},
                 usecols=["ev", "half", "side", "dir", "line", "p_m"])
tr["base"] = "goals"
pm = pd.concat([ek, tr]).drop_duplicates(["ev", "base", "half", "side", "dir", "line"])
d = d.merge(pm, on=["ev", "base", "half", "side", "dir", "line"], how="left")
d["mdev"] = d.p_m - d.p_nv

# Team-Historie (BetsAPI-Orientierung h/a)
N = pd.read_parquet(f"{SP}/muster/netz.parquet")
N["id"] = N.id.astype(str)
N = N[N.id.isin(set(d.ev))].set_index("id")
MET = {("corners", "ft"): "corners", ("corners", "_h1"): "ht_corners", ("corners", "_h2"): "corners",
       ("goals", "ft"): "goals", ("goals", "_h1"): "goals", ("offsides", "ft"): "offsides",
       ("yellowcards", "ft"): "yellowcards"}
FAK = {("corners", "_h2"): 0.55, ("goals", "_h1"): 0.45}   # grobe Halbzeit-Anteile
out = {k: [] for k in ("d3", "d5", "d10", "d15", "dv5", "dv10", "trend", "lgd", "dom", "x_sot", "x_goals", "x_corn", "x_fouls", "streu")}


def g(row, c):
    v = row.get(c)
    return np.nan if v is None or pd.isna(v) else float(v)


for r in d.itertuples(index=False):
    if r.ev not in N.index:
        for k in out: out[k].append(np.nan)
        continue
    n = N.loc[r.ev]
    if isinstance(n, pd.DataFrame): n = n.iloc[0]
    n = n.to_dict()
    m = MET[(r.base, r.half)]; fk = FAK.get((r.base, r.half), 1.0)
    side = r.side
    if side == "tot":
        T = O = None
    else:
        heim = (side == "_heim") != bool(r.swap)
        T, O = ("h", "a") if heim else ("a", "h")

    def ex(w, ven=False):
        fs, as_ = ("fv", "av") if ven else ("f", "a")
        if T is None:
            x = (g(n, f"h_{m}_{fs}{w}") + g(n, f"a_{m}_{as_}{w}")) / 2 + (g(n, f"a_{m}_{fs}{w}") + g(n, f"h_{m}_{as_}{w}")) / 2
        else:
            x = (g(n, f"{T}_{m}_{fs}{w}") + g(n, f"{O}_{m}_{as_}{w}")) / 2
        return x * fk
    e = {w: ex(w) for w in (3, 5, 10, 15)}
    for w in (3, 5, 10, 15): out[f"d{w}"].append(e[w] - r.line)
    out["dv5"].append(ex(5, True) - r.line); out["dv10"].append(ex(10, True) - r.line)
    out["trend"].append(e[3] - e[15])
    lg = g(n, f"lg_{m}") if f"lg_{m}" in n else np.nan
    out["lgd"].append((lg * fk if T is None else lg * fk / 2) - r.line)
    dh = g(n, "h_shots_total_f10") - g(n, "h_shots_total_a10"); da = g(n, "a_shots_total_f10") - g(n, "a_shots_total_a10")
    out["dom"].append(abs(dh - da) if T is None else (dh - da if T == "h" else da - dh))

    def x2(mm):
        if T is None:
            return (g(n, f"h_{mm}_f10") + g(n, f"a_{mm}_a10")) / 2 + (g(n, f"a_{mm}_f10") + g(n, f"h_{mm}_a10")) / 2
        return (g(n, f"{T}_{mm}_f10") + g(n, f"{O}_{mm}_a10")) / 2
    out["x_sot"].append(x2("on_target")); out["x_goals"].append(x2("goals"))
    out["x_corn"].append(x2("corners")); out["x_fouls"].append(x2("fouls"))
    out["streu"].append(abs(e[3] - e[10]))
for k, v in out.items():
    d[k] = v
d["roi"] = d.hit * d.q - 1
d["grp"] = d.base + "|" + d.half + "|" + d.side + "|" + d.dir
d.to_parquet(f"{SP}/bulk/bulk.parquet")
print(d.shape, d.ev.nunique(), "Spiele")
print(d.groupby("grp").agg(zeilen=("roi", "size"), spiele=("ev", "nunique"), roi=("roi", "mean")).to_string())
print(d[list(out) + ["mdev"]].notna().mean().round(2).to_string())
