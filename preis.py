"""26.11. (Lucio): Preisvergleich BetLabel gegen Pinnacle (PinnFeed, Gratis-Tarif) – Testwoche, nur mitschreiben.
Pinnacle-Hauptlinien (1X2, Gesamttore, je ganzes Spiel) -> faire Wahrscheinlichkeiten; über ein angepasstes
Poisson-Modell (lambda Heim/Gast) faire Preise für alle BL-Torlinien (gesamt, Heim, Gast).
Speichert je Lauf alle zugeordneten Spiele mit BL-Quote, fairer Wahrscheinlichkeit und Vorteil (EV)."""
import gzip, json, os, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import betlabel

KEY = os.environ.get("PINNFEED_KEY", "")
OUT = Path("runs/preis")
H = 30 * 3600                                     # Spiele der nächsten 30 h


def pf_get(path):
    req = urllib.request.Request("https://pinnfeed.io" + path,
                                 headers={"x-api-key": KEY, "Accept": "application/json", "User-Agent": "trend-scanner"})
    for versuch in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(e.headers.get("Retry-After") or 2)); continue
            raise
        except Exception:
            time.sleep(2)
    raise RuntimeError("PinnFeed nicht erreichbar")


def pinnacle():
    ev, off = [], 0
    while True:
        d = pf_get(f"/v1/odds?sport=soccer&main=true&live=false&limit=200&offset={off}")
        teil = d.get("events") or []
        ev += teil
        off += len(teil)
        if not teil or off >= int(d.get("count") or 0):
            break
        time.sleep(1.2)
    return ev


# ---------------------------------------------------------------- Poisson-Raster
LAM = np.arange(0.05, 4.001, 0.025)
K = np.arange(0, 13)
_fact = np.array([float(np.prod(np.arange(1, k + 1))) for k in K])
PMF = np.exp(-LAM[:, None]) * LAM[:, None] ** K[None, :] / _fact[None, :]          # (n, 13)
J = PMF[:, None, :, None] * PMF[None, :, None, :]                                    # (n, n, 13, 13)
I_, J_ = np.meshgrid(K, K, indexing="ij")
P1 = (J * (I_ > J_)).sum((2, 3)); PX = (J * (I_ == J_)).sum((2, 3)); P2 = (J * (I_ < J_)).sum((2, 3))
G = np.zeros(J.shape[:2] + (25,))
for i in K:
    for j in K:
        G[:, :, i + j] += J[:, :, i, j]


def over_fair(dist, L):
    """faire Dezimalquote für 'über L' (asiatische Linien mit Push/Halbwetten) aus einer Torverteilung (..., k)."""
    teile = [L - 0.25, L + 0.25] if abs(L * 4 - round(L * 4)) < 1e-9 and abs(L * 2 - round(L * 2)) > 1e-9 else [L]
    k = np.arange(dist.shape[-1])
    w = sum((dist * (k > t)).sum(-1) for t in teile) / len(teile)
    p = sum((dist * (k == t)).sum(-1) for t in teile) / len(teile)
    return (1 - p) / np.maximum(w, 1e-9)


def fit(p1, px, p2, tot_line, tot_over_fair):
    err = (P1 - p1) ** 2 + (PX - px) ** 2 + (P2 - p2) ** 2
    if tot_line is not None and tot_over_fair:
        err = err + (1 / over_fair(G, tot_line) - 1 / tot_over_fair) ** 2
    a, b = np.unravel_index(np.argmin(err), err.shape)
    return LAM[a], LAM[b], float(np.sqrt(err[a, b]))


def pois(lam):
    return np.exp(-lam) * lam ** K / _fact


def main():
    t0 = time.time()
    jetzt = time.time()
    pe = [e for e in pinnacle() if not e.get("live") and e.get("status") in (None, "pending")]
    bl = betlabel.lade_spiele(frisch=True)
    paare = []
    for e in pe:
        try:
            ko = datetime.fromisoformat(e["startTime"].replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if not (jetzt < ko < jetzt + H):
            continue
        mk = {(m["type"], m.get("period")): m for m in e.get("markets") or [] if m.get("main")}
        ml = mk.get(("moneyline", 0))
        if not ml:
            continue
        g, swap = betlabel.finde_spiel(bl, e["home"], e["away"], ko)
        if g:
            paare.append((e, g, bool(swap), ko, mk))

    def leitern(p):
        try:
            return betlabel.tore_leitern(p[1]["I"])
        except Exception:
            return {}
    with ThreadPoolExecutor(12) as ex:
        lads = list(ex.map(leitern, paare))
    rows = []
    for (e, g, swap, ko, mk), lad in zip(paare, lads):
        o = {x["name"]: x for x in mk[("moneyline", 0)]["outcomes"]}
        try:
            p1, px, p2 = o["home"]["fairProb"], o["draw"]["fairProb"], o["away"]["fairProb"]
        except KeyError:
            continue
        tl = tof = None
        tm = mk.get(("total", 0))
        if tm:
            ov = next((x for x in tm["outcomes"] if x["name"] == "over"), None)
            if ov: tl, tof = float(tm["line"]), float(ov["fair"])
        lh, la, ferr = fit(p1, px, p2, tl, tof)
        # BL-Orientierung: bei swap ist BL-Heim = Pinnacle-Gast
        bh, ba = (la, lh) if swap else (lh, la)
        q1, q2 = (p2, p1) if swap else (p1, p2)
        dh, da = pois(bh), pois(ba)
        dt = np.convolve(dh, da)
        ev = []
        x12 = g.get("x12") or {}
        for key, p in (("1", q1), ("2", px), ("3", q2)):
            q = x12.get(key)
            if q:
                ev.append(["1x2", key, None, float(q), round(p, 4), round(p * float(q) - 1, 4)])
        for mkey, dist in (("goals", dt), ("goals_heim", dh), ("goals_gast", da)):
            for lk, q in (lad.get(mkey) or {}).items():
                L = float(lk[1:])
                if abs(L - int(L) - 0.5) > 1e-9:
                    continue
                k = np.arange(len(dist))
                pu = float(dist[k < L].sum())
                p = pu if lk[0] == "u" else 1 - pu
                ev.append([mkey, lk[0], L, float(q), round(p, 4), round(p * float(q) - 1, 4)])
        rows.append({"pin": e["id"], "bl": g["I"], "liga": e["league"]["name"], "bl_liga": g.get("L"),
                     "spiel": f"{g['O1']} – {g['O2']}", "pin_spiel": f"{e['home']} – {e['away']}", "swap": swap,
                     "ko": int(ko), "p": [p1, px, p2],
                     "roh": [o["home"]["decimal"], o["draw"]["decimal"], o["away"]["decimal"]],
                     "tot_roh": [x["decimal"] for x in tm["outcomes"]] if tm else None, "marge_1x2": mk[("moneyline", 0)].get("margin"),
                     "tot": [tl, tof], "lam": [round(float(bh), 3), round(float(ba), 3)], "fitfehler": round(ferr, 4),
                     "max": mk[("moneyline", 0)].get("maxStake"), "ev": ev})
    ts = datetime.now(timezone.utc)
    d = OUT / ts.strftime("%Y-%m-%d"); d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / (ts.strftime("%H%M") + ".json.gz"), "wt", encoding="utf-8") as f:
        json.dump({"t": int(ts.timestamp()), "spiele": rows}, f, ensure_ascii=False, separators=(",", ":"))
    alle = [x for r in rows for x in r["ev"]]
    info = {"zeit": ts.strftime("%Y-%m-%d %H:%M UTC"), "pinnacle": len(pe), "bl": len(bl), "zugeordnet": len(rows),
            "linien": len(alle), "ev>0": sum(1 for x in alle if x[5] > 0), "ev>3%": sum(1 for x in alle if x[5] > 0.03),
            "ev>3% Quote 1,2-1,6": sum(1 for x in alle if x[5] > 0.03 and 1.2 <= x[3] <= 1.6),
            "sekunden": round(time.time() - t0)}
    (OUT / "letzter.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    print(info)


if __name__ == "__main__":
    main()
