"""Karten-Modell (26.10.2026, Lucio: "nur noch das spielen und den Rest erstmal rausnehmen").

Erwartete Gelbe Karten je Team aus einem Boosting- und einem Poisson-Modell
(trainiert auf ~200.000 Team-Spielen, Datei modelle/karten_modell.json, reines
JSON, kein scikit-learn nötig). Merkmale wie im Training (auswertung/muster/
karten_voll_feat.py): eigene und gegnerische Werte bei Ecken, Gelben, Toren,
SaT, Torschüssen, Fouls, HZ-Ecken über 3/5/10/15 Spiele (gesamt) und 5/10
(Rolle), Liga-Schnitt Gelbe/Fouls, Heim, Pokal/Europa/Jugend, Monat, Pause,
Europacup in den letzten 5 Tagen.

Gespielt wird (Backtest 15.–25.10.: 266 Tipps, 68 %, +13 %): BL-Linien Gelbe
gesamt / Heim / Gast fürs ganze Spiel, x.5-Linien, Quote 1,30–2,00, Vorteil
(Modell-Wahrscheinlichkeit × Quote − 1) > 5 %, je Spiel der Tipp mit dem
größten Vorteil. Wahrscheinlichkeit = Mittel aus beiden Modellen.
"""
import json, math, re, time, gzip, glob, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

MODELL_DATEI = Path(__file__).parent / "modelle" / "karten_modell.json"
ARCHIV = Path(__file__).parent / "runs" / "archiv"
V = ("corners", "yellowcards", "goals", "on_target", "shots_total", "fouls", "offsides", "ht_corners")
MIN_EDGE = 0.05
# 26.10.: Vorteil über 20 % = Modell übersieht vermutlich etwas (Derby, Abstiegskampf …).
# Backtest je Vorteil: 5–20 % → 190 Tipps, 70 %, +17,7 % (beide Zeiträume im Plus);
# über 20 % → 76 Tipps, Treffer 58 % statt erwarteter 73 %, ROI ±0. Solche Spiele fliegen raus.
MAX_EDGE = 0.20
Q_MIN, Q_MAX = 1.30, 2.00
_M = None
_RM = None          # Schiri-Modell (Gelbe gesamt), modelle/karten_schiri_modell.json
_REF = {}           # Schiri-ID -> [Gelbe gesamt je früherem Spiel]
SCHIRI_DATEI = Path(__file__).parent / "modelle" / "karten_schiri_modell.json"
_LG = {}
_MU = {}            # match_id -> dict
_lock = threading.Lock()
CUP_RE = re.compile(r"cup|pokal|copa|coupe|coppa|ta[cç]a|beker|trophy|shield|knock|play-?off|super ?cup|supercopa|supercoppa")
UEFA_RE = re.compile(r"uefa|champions|europa|conference|libertadores|sudamericana|concacaf|afc|caf ")
YOUTH_RE = re.compile(r"u1\d|u2\d|youth|reserve|primavera|junior|jugend|juvenil")

# 26.10. abends (Lucio: "Bau solange bis sie heute schon mit reinkönnen"): TORE ÜBER 3.5 bei
# torreichen Teams aus der Massensuche (auswertung/muster/bulk_*.py). Erwartete Tore aus der
# Tor-Historie beider Teams (für/gegen, je 10 Spiele) ≥ 3,75, keine Jugend/Reserve/Frauen,
# BL-Quote Über 3.5 zwischen 1,30 und 2,10. Backtest 15.–25.10. (Regel dort gefunden) mit der
# Live-Berechnung (alle Pflichtspiele, ohne Testspiele): 353 Tipps, 62 %, Ø 1,79, +9,5 %
# (15.–20. +11 %, 21.–25. +8 %); Schwelle 3,5 / 4,0: +7 %. Über 2.5 im selben Topf ±0 → nur 3.5.
TORE_XG_MIN = 3.75
TORE_LINIE = 3.5
TORE_Q_MIN, TORE_Q_MAX = 1.30, 2.10
TORE_JUGEND_RE = re.compile(r"u1\d|u2\d|youth|junior|reserve|primavera|juvenil|\bii\b|women|frauen|femen|\(w\)")
_TORE = {}          # match_id -> {"x_goals", "match"}


def modell():
    global _M
    if _M is None:
        _M = json.loads(MODELL_DATEI.read_text())
        _M["_parsed"] = [_parse(f) for f in _M["features"]]
    return _M


def schiri_modell():
    global _RM
    if _RM is None:
        _RM = json.loads(SCHIRI_DATEI.read_text())
    return _RM


def _parse(name):
    if name.startswith(("own_", "opp_")):
        side, rest = name[:3], name[4:]
        kind = rest.rsplit("_", 1)[1]
        var = rest[:-(len(kind) + 1)]
        m = re.match(r"^(fv|av|f|a)(\d+)$", kind)
        return ("team", side, var, m.group(1), int(m.group(2)))
    return ("x", name)


def _ok(p):
    return p is not None and len(p) >= 2 and p[0] is not None and p[1] is not None and min(p[0], p[1]) >= 0


def liga_init(cache, hcache):
    """Liga-Schnitte (Summe beider Teams) der letzten 400 Spiele je Liga für Gelbe und Fouls."""
    ev = {}
    for v in (hcache or {}).values():
        for e in v.get("events") or []:
            if e.get("id") and e.get("lg"):
                ev[e["id"]] = (e.get("t") or 0, e["lg"])
    per = {}
    for eid, (t, lg) in ev.items():
        s = cache.get(eid)
        if s:
            per.setdefault(lg, []).append((t, s))
    _LG.clear()
    for lg, lst in per.items():
        lst.sort(key=lambda x: x[0])
        out = {}
        for var in ("yellowcards", "fouls"):
            vals = [s[var][0] + s[var][1] for _, s in lst if _ok(s.get(var))][-400:]
            out[var] = sum(vals) / len(vals) if len(vals) >= 30 else None
        _LG[lg] = out
    # 26.10. abends: Schiri-Historie für das Schiri-Modell (Gelbe gesamt je Spiel)
    _REF.clear()
    for eid, sl in cache.items():
        r = sl.get("ref") if isinstance(sl, dict) else None
        if r and _ok(sl.get("yellowcards")):
            _REF.setdefault(str(r[0]), []).append(sl["yellowcards"][0] + sl["yellowcards"][1])


def _profil(hist):
    """Letzte 15 Spiele mit Statistik (neueste zuerst): [(is_home, {var: (für, gegen)})]."""
    out = []
    for h in hist or []:
        s = h.get("stats") or {}
        o = 0 if h.get("is_home") else 1
        d = {}
        for var in V:
            p = s.get(var)
            if _ok(p):
                d[var] = (p[o], p[1 - o])
        if d:
            out.append((bool(h.get("is_home")), d))
        if len(out) >= 15:
            break
    return out


def _mean_fa(prof, var, n, venue=None):
    f, a = [], []
    for ih, d in prof:
        if venue is not None and ih != venue:
            continue
        x = d.get(var)
        if x is None:
            continue
        f.append(x[0]); a.append(x[1])
        if len(f) >= n:
            break
    if len(f) < max(3, int(n * 0.6)):
        return None, None
    return sum(f) / len(f), sum(a) / len(a)


def _rest_eu(hist, t0):
    ts = [h.get("t") or 0 for h in hist or [] if (h.get("t") or 0) < t0]
    rest = min((t0 - max(ts)) / 86400, 14) if ts else 14.0
    eu = 0
    for h in hist or []:
        lg = str(h.get("lg") or "")
        if ("UEFA" in lg or "Champions" in lg) and (h.get("t") or 0) > t0 - 5 * 86400 and (h.get("t") or 0) < t0:
            eu = 1
            break
    return rest, eu


def _features(own_prof, opp_prof, own_ven, opp_ven, home, ctx):
    M = modell()
    x = []
    for p in M["_parsed"]:
        if p[0] == "team":
            _, side, var, kind, n = p
            prof, ven = (own_prof, own_ven) if side == "own" else (opp_prof, opp_ven)
            if kind in ("f", "a"):
                fm, am = _mean_fa(prof, var, n)
            else:
                fm, am = _mean_fa(prof, var, n, ven)
            x.append(fm if kind in ("f", "fv") else am)
        else:
            name = p[1]
            if name == "home":
                x.append(float(home))
            elif name in ("rest_own", "rest_opp", "eu_own", "eu_opp"):
                x.append(ctx[name if home else name.replace("own", "X").replace("opp", "own").replace("X", "opp")])
            else:
                x.append(ctx.get(name))
    return x


def _gbr(x):
    M = modell()["gbr"]
    raw = M["baseline"]
    for t in M["trees"]:
        i = 0
        while True:
            f, th, mgl, le, ri, leaf, val = t[i]
            if leaf:
                raw += val
                break
            v = x[f]
            i = (le if mgl else ri) if v is None else (le if v <= th else ri)
    return math.exp(raw)


def _glm(x):
    M = modell()["glm"]
    z = M["intercept"]
    for v, c, med in zip(x, M["coef"], M["median"]):
        z += c * (med if v is None else v)
    return math.exp(z)


def merke(match, hist_home, hist_away):
    """Im Scan je Spiel aufrufen (billig, keine Abfragen): erwartete Gelbe je Team."""
    t0 = int(match.get("kickoff_ts") or time.time())
    lg = str(match.get("league") or "")
    lgl = lg.lower()
    lgm = _LG.get(lg) or {}
    rh, eh = _rest_eu(hist_home, t0)
    ra, ea = _rest_eu(hist_away, t0)
    import datetime as _dt
    ctx = {"lg_yellowcards": lgm.get("yellowcards"), "lg_fouls": lgm.get("fouls"),
           "cup": int(bool(CUP_RE.search(lgl))), "uefa": int(bool(UEFA_RE.search(lgl))),
           "youth": int(bool(YOUTH_RE.search(lgl))),
           "monat": _dt.datetime.fromtimestamp(t0, _dt.timezone.utc).month,
           "rest_own": rh, "rest_opp": ra, "eu_own": eh, "eu_opp": ea}
    ph, pa = _profil(hist_home), _profil(hist_away)
    try:
        xg = x_goals(ph, pa)
        if xg is not None:
            with _lock:
                _TORE[str(match["id"])] = {"x_goals": xg, "match": {k: match.get(k) for k in
                                           ("id", "home", "away", "league", "kickoff", "kickoff_ts")}}
    except Exception:
        pass
    if len(ph) < 5 or len(pa) < 5:
        return None
    xh = _features(ph, pa, True, False, 1, ctx)
    xa = _features(pa, ph, False, True, 0, ctx)
    r = {"g_h": _gbr(xh), "g_a": _gbr(xa), "l_h": _glm(xh), "l_a": _glm(xa),
         "match": {k: match.get(k) for k in ("id", "home", "away", "league", "kickoff", "kickoff_ts")}}
    try:
        r["sb"] = _schiri_basis(hist_home, hist_away, lgm.get("yellowcards"), rh, ra, eh, ea)
    except Exception:
        r["sb"] = None
    with _lock:
        _MU[str(match["id"])] = r
    return r


def x_goals(ph, pa):
    """Erwartete Tore wie im Training (netz.parquet): (Heim für + Gast gegen)/2 + (Gast für + Heim gegen)/2,
    je Mittel der letzten 10 Spiele (mind. 6 mit Toren)."""
    hf, ha = _mean_fa(ph, "goals", 10)
    af, aa = _mean_fa(pa, "goals", 10)
    if hf is None or af is None:
        return None
    return (hf + aa) / 2 + (af + ha) / 2


TORE_RESERVE_RE = re.compile(r"\s(2|3|b|c|ii|iii)$")      # Teamname-Endung: Sogndal 2, Celtic B, Brann II


def tore_jugend(m, bl_liga=""):
    """Jugend/Reserve/II/Frauen (Liga- oder Teamname). 26.10.: auch Reserve-Teams wie „Brann 2“ –
    Backtest ohne sie unverändert +9,5 % (326 Tipps)."""
    txt = " ".join(str(m.get(k) or "") for k in ("league", "home", "away")) + " " + str(bl_liga or "")
    if TORE_JUGEND_RE.search(txt.lower()):
        return True
    return any(TORE_RESERVE_RE.search(str(m.get(k) or "").strip().lower()) for k in ("home", "away"))


def tore_fuellen(gemischt=frozenset()):
    """Nach dem Scan: für Spiele mit erwarteten Toren ≥ TORE_XG_MIN die BL-Torlinie Über 3.5 holen."""
    import betlabel
    t0 = time.time()
    kand = [(mid, r) for mid, r in list(_TORE.items()) if r["x_goals"] >= TORE_XG_MIN]
    proto = {"spiele_xg": len(_TORE), "xg_hoch": len(kand), "abgefragt": 0, "fehler": 0, "ohne_linie": 0, "quote_raus": 0}
    try:
        spiele = betlabel.lade_spiele()
    except Exception as exc:
        proto["fehler_liste"] = str(exc)
        return [], proto
    jetzt = time.time()
    auftr = []
    for mid, r in kand:
        m = r["match"]
        if mid in gemischt or (m.get("kickoff_ts") or 0) < jetzt + 300 or tore_jugend(m):
            continue
        g, swap = betlabel.finde_spiel(spiele, m["home"], m["away"], m.get("kickoff_ts"))
        if not g or tore_jugend(m, g.get("L")):
            continue
        auftr.append((mid, r, g, swap))

    def eins(a):
        try:
            return a, betlabel.tore_leitern(a[2]["I"])
        except Exception:
            return a, None

    tipps = []
    with ThreadPoolExecutor(8) as ex:
        for (mid, r, g, swap), lad in ex.map(eins, auftr):
            proto["abgefragt"] += 1
            if lad is None:
                proto["fehler"] += 1
                continue
            q = (lad.get("goals") or {}).get(f"o{TORE_LINIE:g}")
            if not q:
                proto["ohne_linie"] += 1
                continue
            if not (TORE_Q_MIN <= q <= TORE_Q_MAX):
                proto["quote_raus"] += 1
                continue
            m = r["match"]
            tipps.append(dict(match_id=mid, bl_id=g["I"], swap=bool(swap), linie=TORE_LINIE, richtung="über", q=q,
                              x_goals=round(r["x_goals"], 2), spiel=f"{m['home']} – {m['away']}", liga=m.get("league"),
                              kickoff_ts=m.get("kickoff_ts"), kickoff=m.get("kickoff")))
    tipps.sort(key=lambda t: t.get("kickoff_ts") or 0)
    proto["tipps"] = len(tipps)
    proto["sekunden"] = round(time.time() - t0, 1)
    return tipps, proto


def tore_block(tipps, esc=lambda s: s, max_zeilen=15):
    import datetime as _dt
    from zoneinfo import ZoneInfo
    B = ZoneInfo("Europe/Berlin")
    kopf = "🟥 <b>TORE ÜBER 3.5 · torreiche Teams</b> · NEU, Test-Phase"
    if not tipps:
        return kopf + "\n<i>gerade kein Spiel mit erwarteten Toren ≥ 3,75 und Über-3.5-Quote 1,30–2,10</i>"
    zeige = tipps
    if len(tipps) > max_zeilen:     # nur Anzeige kürzen: die torreichsten, wieder nach Anstoß
        zeige = sorted(sorted(tipps, key=lambda t: -t["x_goals"])[:max_zeilen], key=lambda t: t.get("kickoff_ts") or 0)
    z = [kopf, f"<i>{len(tipps)} Tipps · erwartete Tore aus den letzten 10 Spielen beider Teams ≥ 3,75 · ohne Jugend"
               + (f" · gezeigt die {max_zeilen} torreichsten" if len(zeige) < len(tipps) else "") + "</i>", ""]
    for t in zeige:
        ko = _dt.datetime.fromtimestamp(t["kickoff_ts"], B).strftime("%H:%M") if t.get("kickoff_ts") else "?"
        z.append(f"{ko} {esc(t['spiel'])} <i>({esc(t.get('liga') or '')})</i>")
        z.append(f"   Tore über 3.5 @{t['q']:.2f} · erwartet {t['x_goals']:.2f} Tore")
    if len(zeige) >= 2:
        z.append("")
        z.append("<b>2er nach Anstoß</b>")
        for i in range(len(zeige) // 2):
            a, b = zeige[2 * i], zeige[2 * i + 1]
            z.append(f"{i + 1}) {esc(a['spiel'].split(' – ')[0])} + {esc(b['spiel'].split(' – ')[0])} @{a['q'] * b['q']:.2f}")
    return "\n".join(z)


def _team10(hist):
    """Letzte 10 Spiele mit gültigen Gelben (neueste zuerst): (für, gegen, Fouls-für-Schnitt) wie im Training."""
    f, a, fo = [], [], []
    for h in hist or []:
        s = h.get("stats") or {}
        y = s.get("yellowcards")
        if not _ok(y):
            continue
        o = 0 if h.get("is_home") else 1
        f.append(y[o]); a.append(y[1 - o])
        p = s.get("fouls")
        if _ok(p):
            fo.append(p[o])
        if len(f) >= 10:
            break
    if len(f) < 5:
        return None
    return sum(f) / len(f), sum(a) / len(a), (sum(fo) / len(fo) if fo else None)


def _schiri_basis(hist_home, hist_away, lgm, rh, ra, eh, ea):
    th, ta = _team10(hist_home), _team10(hist_away)
    if not th or not ta:
        return None
    RM = schiri_modell()
    lgm = lgm or RM["lgm_fallback"]
    exp_team = (th[0] + ta[1]) / 2 + (ta[0] + th[1]) / 2
    fo_known = th[2] is not None and ta[2] is not None
    fo = math.log(max((th[2] + ta[2]) / 2, 3)) if fo_known else math.log(11)
    return {"lgm": lgm, "l_lg": math.log(max(lgm, 0.5)), "l_team": math.log(max(exp_team, 0.5)),
            "fo": fo, "fo_known": int(fo_known), "rest_min": min(rh, ra), "eu": eh + ea}


def schiri_mu(sb, ref_id):
    """Erwartete Gelbe gesamt aus dem Schiri-Modell; ref_id None = Schiri unbekannt."""
    RM = schiri_modell()
    lst = _REF.get(str(ref_id)) if ref_id else None
    k = RM.get("shrink_k", 6)
    if lst:
        ref_s = (sum(lst) + k * sb["lgm"]) / (len(lst) + k)
        ref_rel, known = math.log(max(ref_s, 0.5) / max(sb["lgm"], 0.5)), 1
    else:
        ref_rel, known = 0.0, 0
    x = {"l_lg": sb["l_lg"], "l_team": sb["l_team"], "ref_rel": ref_rel, "ref_known": known,
         "fo": sb["fo"], "fo_known": sb["fo_known"], "rest_min": sb["rest_min"], "eu": sb["eu"]}
    z = RM["intercept"] + sum(c * x[f] for f, c in zip(RM["features"], RM["coef"]))
    return math.exp(z), known


def _nb_over(mu, L, disp):
    """P(X > L) für negativ-binomial (disp = Varianz/Mittel, mind. 1,01 ≈ Poisson)."""
    disp = max(disp, 1.01)
    r = mu / (disp - 1)
    p = r / (r + mu)
    k = int(math.floor(L))
    pmf = p ** r
    cdf = pmf
    for i in range(k):
        pmf = pmf * (i + r) / (i + 1) * (1 - p)
        cdf += pmf
    return max(0.0, min(1.0, 1 - cdf))


def p_linie(r, seite, richtung, L, swap=False):
    """Mittel aus Boosting und GLM. seite: tot/heim/gast in BetLabel-Orientierung."""
    M = modell()
    ps = []
    for mk, mod in (("g", "gbr"), ("l", "glm")):
        h, a = r[mk + "_h"], r[mk + "_a"]
        if swap:
            h, a = a, h
        if seite == "tot":
            po = _nb_over(h + a, L, M[mod]["disp_tot"])
        else:
            po = _nb_over(h if seite == "heim" else a, L, M[mod]["disp_team"])
        ps.append(po if richtung == "über" else 1 - po)
    p = sum(ps) / len(ps)
    # 26.10. abends: Gelbe gesamt = Mittel aus Team-Ensemble und Schiri-Modell
    # (Backtest Vorteil 5–20 %: +17,7 % → +20,8 %, gesamt-Tipps +27,6 % → +38,2 %)
    if seite == "tot" and r.get("ref_mu"):
        po = _nb_over(r["ref_mu"], L, schiri_modell()["disp"])
        p = (p + (po if richtung == "über" else 1 - po)) / 2
    return p


def karten_ligen():
    """BL-Ligen, in denen BetLabel laut Marktarchiv Karten-Linien anbietet."""
    out = set()
    for f in sorted(glob.glob(str(ARCHIV / "bl_*.json.gz")))[-14:]:
        try:
            for g in json.load(gzip.open(f, "rt", encoding="utf-8"))["spiele"]:
                if "yellowcards" in (g.get("m") or {}):
                    out.add(g.get("L"))
        except Exception:
            pass
    return out


def _schiri_holen(ids, api_get):
    out = {}
    for i in range(0, len(ids), 10):
        try:
            v = api_get("/v1/event/view", event_id=",".join(ids[i:i + 10]))
        except Exception:
            continue
        for ev in v.get("results", []):
            ref = ((ev.get("extra") or {}).get("referee") or {})
            if ref.get("id"):
                out[str(ev["id"])] = (str(ref["id"]), ref.get("name"))
    return out


def fuellen(gemischt=frozenset(), api_get=None):
    """Nach dem Scan: BL-Kartenlinien holen, Tipps auswählen. Liefert (tipps, protokoll)."""
    import betlabel
    t0 = time.time()
    proto = {"spiele_modell": len(_MU), "abgefragt": 0, "mit_linien": 0, "fehler": 0}
    try:
        spiele = betlabel.lade_spiele()
    except Exception as exc:
        proto["fehler_liste"] = str(exc)
        return [], proto
    ligen = karten_ligen()
    proto["karten_ligen"] = len(ligen)
    jetzt = time.time()
    auftr = []
    for mid, r in list(_MU.items()):
        m = r["match"]
        if mid in gemischt or (m.get("kickoff_ts") or 0) < jetzt + 300:
            continue
        g, swap = betlabel.finde_spiel(spiele, m["home"], m["away"], m.get("kickoff_ts"))
        if not g or (ligen and g.get("L") not in ligen):
            continue
        auftr.append((mid, r, g, swap))

    schiri = _schiri_holen([a[0] for a in auftr], api_get) if (api_get and auftr) else {}
    proto["schiri_bekannt"] = len(schiri)
    for mid, r, g, swap in auftr:
        if r.get("sb"):
            ref = schiri.get(str(mid))
            r["ref_mu"], r["ref_known"] = schiri_mu(r["sb"], ref[0] if ref else None)
            r["schiri"] = ref[1] if ref else None

    def eins(a):
        mid, r, g, swap = a
        try:
            return a, betlabel.karten_leitern(g["I"])
        except Exception:
            return a, None

    tipps = []
    with ThreadPoolExecutor(8) as ex:
        for (mid, r, g, swap), lad in ex.map(eins, auftr):
            proto["abgefragt"] += 1
            if lad is None:
                proto["fehler"] += 1
                continue
            if not lad:
                continue
            proto["mit_linien"] += 1
            kand = []
            for key, seite in (("yellowcards", "tot"), ("yellowcards_heim", "heim"), ("yellowcards_gast", "gast")):
                for lk, q in (lad.get(key) or {}).items():
                    L = float(lk[1:])
                    if abs(L - int(L) - 0.5) > 1e-9 or not (Q_MIN <= q <= Q_MAX):
                        continue
                    richt = "über" if lk[0] == "o" else "unter"
                    p = p_linie(r, seite, richt, L, swap)
                    edge = p * q - 1
                    if edge > MIN_EDGE:
                        kand.append({"seite": seite, "richtung": richt, "linie": L, "q": q,
                                     "p": round(p, 4), "edge": round(edge, 4)})
            if kand:
                best = max(kand, key=lambda k: k["edge"])
                if best["edge"] > MAX_EDGE:
                    proto["zu_hoch"] = proto.get("zu_hoch", 0) + 1
                    continue
                m = r["match"]
                team = None
                if best["seite"] != "tot":
                    bl_heim = g["O1"] if best["seite"] == "heim" else g["O2"]
                    team = bl_heim
                tipps.append(dict(best, match_id=mid, bl_id=g["I"], swap=bool(swap), team=team,
                                  spiel=f"{m['home']} – {m['away']}", liga=m.get("league"),
                                  kickoff_ts=m.get("kickoff_ts"), kickoff=m.get("kickoff"),
                                  schiri=r.get("schiri"),
                                  mu={k: round(v, 3) for k, v in r.items() if isinstance(v, (int, float))}))
    tipps.sort(key=lambda t: t.get("kickoff_ts") or 0)
    proto["tipps"] = len(tipps)
    proto["sekunden"] = round(time.time() - t0, 1)
    return tipps, proto


def block(tipps, stand=None, esc=lambda s: s):
    """Telegram-Text: alle Tipps nach Anstoß + 2er-Vorschläge in Anstoß-Reihenfolge."""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    B = ZoneInfo("Europe/Berlin")
    kopf = f"🟨 <b>KARTEN-MODELL</b> · Papier-Phase" + (f" · Stand {stand}" if stand else "")
    if not tipps:
        return kopf + "\n<i>gerade keine Karten-Linie mit Vorteil > 5 %</i>"
    z = [kopf, f"<i>{len(tipps)} Tipps · Gelbe Karten (ganzes Spiel) · Vorteil = Modell × Quote − 1</i>", ""]
    for t in tipps:
        ko = _dt.datetime.fromtimestamp(t["kickoff_ts"], B).strftime("%H:%M") if t.get("kickoff_ts") else "?"
        wer = "gesamt" if t["seite"] == "tot" else esc(t["team"] or t["seite"])
        z.append(f"{ko} {esc(t['spiel'])} <i>({esc(t.get('liga') or '')})</i>")
        z.append(f"   Gelbe {wer} {t['richtung']} {t['linie']:g} @{t['q']:.2f} · Modell {t['p']:.0%} · Vorteil +{t['edge']:.0%}")
    if len(tipps) >= 2:
        z.append("")
        z.append("<b>2er nach Anstoß</b>")
        for i in range(len(tipps) // 2):
            a, b = tipps[2 * i], tipps[2 * i + 1]
            z.append(f"{i + 1}) {esc(a['spiel'].split(' – ')[0])} + {esc(b['spiel'].split(' – ')[0])} @{a['q'] * b['q']:.2f}")
    return "\n".join(z)


def selbsttest():
    ok = True
    if abs(_nb_over(3.0, 3.5, 1.01) - 0.3528) > 0.01:          # ~Poisson(3): P(X>=4)=0.3528
        print("Karten: NB/Poisson falsch", _nb_over(3.0, 3.5, 1.01)); ok = False
    try:
        M = modell()
        x = [None] * len(M["features"])
        g, l = _gbr(x), _glm(x)
        if not (0.5 < g < 5 and 0.5 < l < 5):
            print("Karten: Modell liefert unplausible Werte", g, l); ok = False
    except Exception as exc:
        print("Karten: Modell nicht ladbar", exc); ok = False
    r = {"g_h": 2.0, "g_a": 2.5, "l_h": 2.1, "l_a": 2.4}
    if not (p_linie(r, "tot", "über", 3.5) > 0.5 > p_linie(r, "tot", "unter", 3.5)):
        print("Karten: Linien-Wahrscheinlichkeit falsch"); ok = False
    if abs(p_linie(r, "heim", "über", 1.5, swap=True) - p_linie(r, "gast", "über", 1.5)) > 1e-9:
        print("Karten: Seitentausch falsch"); ok = False
    # Tore über 3.5: erwartete Tore wie im Training
    ph = [(True, {"goals": (3, 1)})] * 10
    pa = [(False, {"goals": (2, 2)})] * 10
    if x_goals(ph, pa) is None or abs(x_goals(ph, pa) - ((3 + 2) / 2 + (2 + 1) / 2)) > 1e-9 or x_goals(ph[:5], pa) is not None:
        print("Tore 3.5: erwartete Tore falsch"); ok = False
    if not tore_jugend({"league": "Germany Bundesliga U19"}) or tore_jugend({"league": "England Premier League", "home": "Brentford", "away": "Liverpool"}) \
            or not tore_jugend({"league": "Norway Division 2", "home": "Brann II", "away": "Fana"}) \
            or not tore_jugend({"league": "Norway Division 3 Group 3", "home": "Sogndal 2", "away": "Brann 2"}) \
            or tore_jugend({"league": "Norway Division 2", "home": "Fana", "away": "Brattvag"}):
        print("Tore 3.5: Jugend-Erkennung falsch"); ok = False
    return ok
