"""Serienfreie Suche (22.11., Lucio): für ausgewählte Spiele alle BetLabel-Märkte 1,20–1,50
nur mit unseren Regeln + eigenen Teamwerten bewerten (ohne scores24-Trendserien).

Aufruf: python ohneserie.py "<Regex auf BetLabel-Liganamen>" [Stunden voraus]
Schreibt runs/trendscan/ohneserie.json.
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import betlabel
import teamstats
import trendscan as T

LIGA_RX = re.compile(sys.argv[1] if len(sys.argv) > 1 else r"Deutschland", re.I)
STUNDEN = float(sys.argv[2]) if len(sys.argv) > 2 else 14
OUT = Path("runs/trendscan/ohneserie.json")
LINIEN = {"goals": [0.5, 1.5, 2.5, 3.5, 4.5], "corners": [x + 0.5 for x in range(1, 13)],
          "yellowcards": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]}


def maerkte():
    out = [{"art": "dc", "wahl": w} for w in ("x1", "x2", "12")]
    out += [{"art": "hc", "seite": s, "linie": L} for s in ("heim", "gast") for L in (0.5, 1.5, 2.5)]
    for m, ls in LINIEN.items():
        for seite in (None, "heim", "gast"):
            for L in ls:
                for r in ("über", "unter"):
                    out.append({"art": "ou", "metric": m, "seite": seite, "richtung": r, "linie": L})
    return out


def main():
    jetzt = time.time()
    bl = [g for g in betlabel.lade_spiele()
          if jetzt < g["S"] < jetzt + STUNDEN * 3600 and LIGA_RX.search(g.get("L") or "")]
    print(len(bl), "BetLabel-Spiele", flush=True)
    tage = {datetime.fromtimestamp(g["S"], T.TZ).strftime("%d-%m-%Y") for g in bl}
    links = T._links_fuer_tage(tage)

    def slug_fuer(g):
        best, sc = None, 0
        for s in links:
            if s[:10] != datetime.fromtimestamp(g["S"], T.TZ).strftime("%d-%m-%Y"):
                continue
            rest = s[11:]
            n1 = [w for w in re.split(r"[^a-z0-9]+", g["O1"].lower()) if len(w) > 2]
            n2 = [w for w in re.split(r"[^a-z0-9]+", g["O2"].lower()) if len(w) > 2]
            p = sum(1 for w in n1 if w in rest) + sum(1 for w in n2 if w in rest)
            if p > sc:
                best, sc = s, p
        return best if sc >= 2 else None

    paare = [(g, slug_fuer(g)) for g in bl]
    paare = [(g, s) for g, s in paare if s]
    print(len(paare), "mit scores24-Slug", flush=True)
    recs = {}
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(T._spiel_s24, [s for _, s in paare]):
            recs[r["slug"]] = r
    ein = []
    for g, s in paare:
        tab = recs.get(s, {}).get("tab") or {}
        ok = isinstance(tab, dict) and tab.get("heim") and not tab.get("unklar")
        ein.append((s, tab["heim"]["sp"] if ok else None, tab["gast"]["sp"] if ok else None))
    stats = teamstats.laden(ein, T.CACHE / "tm.json.gz")

    def eins(gs):
        g, s = gs
        rec = recs.get(s, {})
        home, away = rec.get("home") or g["O1"], rec.get("away") or g["O2"]
        _, swap = betlabel.finde_spiel([g], home, away, g["S"])
        swap = bool(swap)
        try:
            haupt = betlabel._spiel_detail(g["I"])
        except Exception as e:
            return []
        x12 = T._x12(haupt, g.get("x12"), swap)
        st = stats.get(s) or {}
        tab = rec.get("tab")
        mit_tab = isinstance(tab, dict) and bool(tab) and not tab.get("unklar") and not tab.get("fremd")
        if not mit_tab and st.get("liga_heim") and st.get("liga_heim") == st.get("liga_gast"):
            mit_tab = True
        po = bool(st.get("po_heim") and st.get("po_gast"))
        sub, res = {}, []
        for k in maerkte():
            try:
                q = T.bl_quote(haupt, k, swap, sub)
            except Exception:
                q = None
            ok, hinweis = T.regeln(k, x12, q)
            if not ok:
                continue
            c = teamstats.gegencheck(k, st, home, away, q, mit_tab, x12)
            if not c or c["sym"] == "🔴":
                continue
            try:
                puffer = min(a / b for a, b in c["alle"] if b) - 1 / q
            except ValueError:
                puffer = 0
            res.append({"spiel": f"{home} – {away}", "bl": f"{g['O1']} – {g['O2']}", "liga": g.get("L"),
                        "anstoss": g["S"], "markt": T.label(k, home, away), "quote": q, "x12": x12,
                        "sym": "🟡" if po else c["sym"], "check": c["zeilen"], "puffer": round(puffer, 3),
                        "hinweis": hinweis + ("; Play-off?" if po else "")})
        return res

    alle = []
    with ThreadPoolExecutor(betlabel.THREADS) as ex:
        for r in ex.map(eins, paare):
            alle += r
    alle.sort(key=lambda r: (r["anstoss"], r["spiel"], r["sym"] != "🟢", -r["puffer"]))
    OUT.write_text(json.dumps({"stand": datetime.now(T.TZ).isoformat(), "spiele": len(paare),
                               "liste": alle}, ensure_ascii=False, indent=1))
    print(len(alle), "Märkte ohne 🔴", sum(1 for r in alle if r["sym"] == "🟢"), "🟢", flush=True)


if __name__ == "__main__":
    main()
