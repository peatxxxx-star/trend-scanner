"""Datensatz A: jede BL-Linie (x.5) mit Quote, No-Vig-Wahrscheinlichkeit, Ergebnis."""
import gzip, json, glob, csv, re
REPO = "/home/claude/trend-scanner"
BASES = ["corners", "yellowcards", "on_target", "offsides", "fouls", "goalkicks", "throwins", "shots_total", "goals"]
HT = {"corners": "ht_corners", "yellowcards": "ht_yellowcards", "goals": "ht_goals"}
rows = []
for f in sorted(glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz")):
    tag = re.search(r"bl_(\d{4}-\d{2}-\d{2})", f).group(1)
    for g in json.load(gzip.open(f, "rt"))["spiele"]:
        erg = g.get("erg")
        if not erg or not g.get("ev"):
            continue
        if erg.get("len") not in (None, 90):     # Verlängerung: BL wertet 90 min -> raus
            continue
        sw = bool(g.get("swap"))
        x = g.get("x12") or {}
        try:
            q1, qx, q2 = float(x["1"]), float(x["2"]), float(x["3"])
            s = 1 / q1 + 1 / qx + 1 / q2
            p1, p2 = (1 / q1) / s, (1 / q2) / s
        except Exception:
            p1 = p2 = None
        for key, lad in g["m"].items():
            m = re.match(r"^(%s)(_h1|_h2)?(_heim|_gast)?$" % "|".join(BASES), key)
            if not m:
                continue
            base, half, side = m.group(1), m.group(2) or "", m.group(3) or ""
            full = erg.get(base)
            def pair_for(h):
                if h == "":
                    return full
                ht = erg.get(HT.get(base, "")) if base in HT else None
                if not ht or ht[0] is None:
                    return None
                if h == "_h1":
                    return ht
                if not full or full[0] is None or ht[1] == -1:
                    return [None, None] if ht[1] == -1 and h == "_h2" else None
                return [full[0] - ht[0], full[1] - ht[1]]
            pr = pair_for(half)
            if pr is None:
                continue
            # Wert bestimmen (BL-Orientierung heim/gast; erg in BetsAPI-Orientierung)
            if side == "":
                if half == "_h1" and base == "goals" and pr[1] == -1:
                    val = pr[0]
                elif pr[0] is None or pr[1] is None or min(pr) < 0:
                    continue
                else:
                    val = pr[0] + pr[1]
            else:
                if pr[0] is None or pr[1] is None or min(pr) < 0:
                    continue
                idx = 0 if side == "_heim" else 1
                if sw:
                    idx = 1 - idx
                val = pr[idx]
            for lk, q in lad.items():
                L = float(lk[1:])
                if abs(L - int(L) - 0.5) > 1e-9:
                    continue
                d = "o" if lk[0] == "o" else "u"
                opp = lad.get(("u" if d == "o" else "o") + lk[1:])
                pnv = (1 / q) / ((1 / q) + (1 / opp)) if opp else None
                hit = (val > L) if d == "o" else (val < L)
                # Rolle des Teams bei Team-Märkten / Favorit
                fav = None
                if p1 is not None:
                    pt = p1 if side in ("", "_heim") else p2
                    po = p2 if side in ("", "_heim") else p1
                    fav = pt
                rows.append({"tag": tag, "ev": g["ev"], "liga": g.get("liga") or g.get("L"), "bl_liga": g.get("L"),
                             "base": base, "half": half or "ft", "side": side or "tot", "dir": d, "line": L,
                             "q": q, "q_opp": opp or "", "p_nv": round(pnv, 4) if pnv else "",
                             "p1": round(p1, 3) if p1 else "", "p2": round(p2, 3) if p2 else "",
                             "p_team": round(fav, 3) if fav is not None else "", "val": val, "hit": int(hit)})
with open("ds_a.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print(len(rows), "Zeilen", len({r['ev'] for r in rows}), "Spiele")
