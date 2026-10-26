"""Datensatz B: Datensatz A (verlässliche Märkte) + Vorab-Merkmale aus Team-Historien (nur Spiele VOR Anstoß)."""
import json, glob, gzip, re, sys
import pandas as pd, numpy as np
REPO = "/home/claude/trend-scanner"; SP = "/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad"
st = {}
for f in glob.glob(f"{REPO}/cache/stats/s*.txt"):
    for l in open(f):
        i, _, j = l.partition("\t")
        try: st[i] = json.loads(j)
        except Exception: pass
H = json.load(open(f"{SP}/hist_merged.json"))
try: H2 = json.load(open(f"{REPO}/cache/history.json"))
except Exception: H2 = {}
for tid, v in H2.items():
    d = {e["id"]: e for e in H.get(tid, {}).get("events", [])}
    for e in v["events"]: d[e["id"]] = e
    H[tid] = {"events": sorted(d.values(), key=lambda e: -(e.get("t") or 0))}
teams = json.load(open(f"{REPO}/runs/archiv_teams.json"))
S = {}
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f, "rt"))["spiele"]:
        if g.get("ev"): S[g["ev"]] = (g["S"], bool(g.get("swap")))
N = 10
def prof(tid, t0, venue=None):
    """letzte N Spiele vor t0: Listen je Metrik (für, gegen)."""
    out = {"n": 0}
    rows = []
    for e in H.get(str(tid), {}).get("events", []):
        if (e.get("t") or 0) >= t0 - 3600 or "riendl" in e.get("lg", ""): continue
        if venue is not None and e["h"] != venue: continue
        s = st.get(e["id"])
        if not s: continue
        rows.append((s, 0 if e["h"] else 1))
        if len(rows) >= N: break
    out["n"] = len(rows)
    for m in ("corners", "yellowcards", "goals", "on_target", "ht_corners"):
        f_, a_ = [], []
        for s, o in rows:
            p = s.get(m)
            if p and p[0] is not None and p[1] is not None and min(p) >= 0:
                f_.append(p[o]); a_.append(p[1 - o])
        out[m] = (f_, a_)
    return out
feat = {}
for ev, (t0, sw) in S.items():
    tm = teams.get(ev)
    if not tm: continue
    h, a = tm[0], tm[1]
    feat[ev] = {"H": prof(h, t0), "A": prof(a, t0), "Hv": prof(h, t0, True), "Av": prof(a, t0, False), "swap": sw}
print("Spiele mit Teams:", len(feat), file=sys.stderr)
d = pd.read_csv("ds_a.csv", dtype={"ev": str})
ok = ((d.base == 'corners') | ((d.base == 'goals') & ((d.half == 'ft') | ((d.half == '_h1') & (d.side != '_gast')))) |
      ((d.base == 'yellowcards') & (d.half != '_h2') & ~((d.half == 'ft') & (d.side == '_gast'))))
d = d[ok & d.p_nv.notna() & d.ev.isin(feat.keys())].copy()
MK = {("corners", "ft"): "corners", ("corners", "_h1"): "ht_corners", ("goals", "ft"): "goals",
      ("yellowcards", "ft"): "yellowcards"}
def kennz(r):
    m = MK.get((r.base, r.half))
    if not m: return [np.nan] * 8
    F = feat[r.ev]
    # BL heim/gast -> BetsAPI-Seite
    if r.side == "tot":
        hp, ap = F["H"][m], F["A"][m]
        ex_vals = None
        def comb(fh, aa, fa, ah):
            if min(len(fh), len(aa), len(fa), len(ah)) < 5: return None
            return (np.mean(fh) + np.mean(ah)) / 2 + (np.mean(fa) + np.mean(aa)) / 2
        e_all = comb(hp[0], ap[1], ap[0], hp[1])
        hv, av = F["Hv"][m], F["Av"][m]
        e_ven = comb(hv[0], av[1], av[0], hv[1])
        # empirische Trefferquote: Summen in den eigenen Spielen
        sums_h = [x + y for x, y in zip(*hp)]; sums_a = [x + y for x, y in zip(*ap)]
        vals = sums_h + sums_a
        own = vals; opp = []
    else:
        heim_bl = r.side == "_heim"
        team_is_h = heim_bl != F["swap"]
        T, O = ("H", "A") if team_is_h else ("A", "H")
        Tv, Ov = ("Hv", "Av") if team_is_h else ("Av", "Hv")
        tp, op = F[T][m], F[O][m]
        if min(len(tp[0]), len(op[1])) < 5: return [np.nan] * 8
        e_all = (np.mean(tp[0]) + np.mean(op[1])) / 2
        tv, ov = F[Tv][m], F[Ov][m]
        e_ven = (np.mean(tv[0]) + np.mean(ov[1])) / 2 if min(len(tv[0]), len(ov[1])) >= 3 else None
        own, opp = tp[0], op[1]
    if e_all is None: return [np.nan] * 8
    L = r.line; o = r.dir == "o"
    hr_own = np.mean([(v > L) if o else (v < L) for v in own]) if own else np.nan
    hr_opp = np.mean([(v > L) if o else (v < L) for v in opp]) if opp else np.nan
    if r.base == "yellowcards" or r.base == "goals":
        lam = e_all
        from math import exp, factorial
        k = int(np.floor(L))
        cdf = sum(exp(-lam) * lam ** i / factorial(i) for i in range(k + 1))
        p_pois = (1 - cdf) if o else cdf
    else:
        # Ecken: Negativ-Binomial-artig über Normalnäherung mit Varianz 1.6*mu
        from math import erf, sqrt
        mu = e_all; sd = sqrt(max(1.6 * mu, 0.5))
        z = (L - mu) / sd
        cdf = 0.5 * (1 + erf(z / sqrt(2)))
        p_pois = (1 - cdf) if o else cdf
    sgn = 1 if o else -1
    return [e_all, e_ven if e_ven is not None else np.nan, sgn * (e_all - L), hr_own, hr_opp, p_pois,
            F["H"]["n"], F["A"]["n"]]
cols = ["e_all", "e_ven", "marg", "hr_own", "hr_opp", "p_mod", "nH", "nA"]
K = np.array([kennz(r) for r in d.itertuples()], dtype=float)
for i, c in enumerate(cols): d[c] = K[:, i]
d = d[d.p_mod.notna()]
d.to_csv("ds_b.csv", index=False)
print(len(d), "Zeilen", d.ev.nunique(), "Spiele", file=sys.stderr)
