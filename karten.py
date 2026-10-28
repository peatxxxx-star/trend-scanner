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
import json, math, os, re, time, gzip, glob, threading
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
# 27.10. (Lucio: „bei Continental Cups kannst du die Leistung gar nicht aneinander skalieren“): Europa-/
# Kontinentalcups fliegen aus Tore 3.5 und Außenseiter-Ecken. Backtest 15.–25.10.: Tore 3.5 Kontinentalcup
# 31 Tipps −11 % (Liga +11 %, nationaler Pokal +24 %); Außenseiter-Ecken Kontinentalcup 26 Tipps +3 % (Liga +25 %).
# Bewusst eng gefasst – „Championship“ (England, Aruba …) ist eine Liga und bleibt drin.
KONTINENTAL_RE = re.compile(r"uefa|champions league|europa league|conference league|libertadores|sudamericana|"
                            r"concacaf|\bafc\b|\bcaf\b|club world cup|recopa|leagues cup")


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


def kontinental(m, bl_liga=""):
    return bool(KONTINENTAL_RE.search((str(m.get("league") or "") + " " + str(bl_liga or "")).lower()))


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
        if mid in gemischt or (m.get("kickoff_ts") or 0) < jetzt + 300 or tore_jugend(m) or kontinental(m):
            continue
        g, swap = betlabel.finde_spiel(spiele, m["home"], m["away"], m.get("kickoff_ts"))
        if not g or tore_jugend(m, g.get("L")) or kontinental(m, g.get("L")):
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


# 26.10. abends (Lucio: „das Offensichtliche – der Favorit macht mehr Ecken“): BL setzt Team-Ecken-Linien
# auch bei haushohen Favoriten auf ~57 % Treffer. Backtest 15.–25.10. (auswertung/muster/favorit.py):
# Außenseiter Team-Ecken UNTER bei Favorit ≥ 75 % (BL-1X2 ohne Marge), Linie mit Quote am nächsten an 1,60
# (1,30–2,10): 79 Tipps, 75 % (BL 58 %), Ø 1,61, +19 % (15.–20. +24 %, 21.–25. +13,5 %), 90 %-Spanne +6…+32 %;
# ohne Jugend/Frauen 67 Tipps +19 %. Stufenweise: Fav 60–70 % ±0, 75–80 % +14 %, 80–85 % +28 %, > 85 % +29 %.
ECKEN_FAV_MIN = 0.75
# 28.10. (Lucio): nur Auswärts-Außenseiter. Heim-Außenseiter holen deutlich mehr Ecken:
# BL-Archiv 15.–25.10. auswärts 33/40 (83 %, +32 %) vs. heim 4/6 (±0 %); live 26.–27.10. auswärts 4/5 (+20 %)
# vs. heim 5/10 (−22 %); bet365 2000–2026 auswärts 76 % (n 3.530) vs. heim 68 % (n 597).
ECKEN_NUR_AUSWAERTS = True
ECKEN_Q_MIN, ECKEN_Q_MAX, ECKEN_Q_ZIEL = 1.30, 2.10, 1.60
VIRTUELL_RE = re.compile(r"virtual|esoccer|e-?sport|cyber|fifa")


def _p12(x12):
    try:
        q1, qx, q2 = float(x12["1"]), float(x12["2"]), float(x12["3"])
        s = 1 / q1 + 1 / qx + 1 / q2
        return (1 / q1) / s, (1 / q2) / s
    except Exception:
        return None


def ecken_fuellen(matches, gemischt=frozenset()):
    """Nach dem Scan: gescannte Spiele mit klarem Favoriten (≥ 75 %) → Außenseiter Team-Ecken unter."""
    import betlabel
    t0 = time.time()
    proto = {"spiele": len(matches), "zugeordnet": 0, "fav_klar": 0, "abgefragt": 0, "fehler": 0, "ohne_linie": 0}
    try:
        spiele = betlabel.lade_spiele()
    except Exception as exc:
        proto["fehler_liste"] = str(exc)
        return [], proto
    jetzt = time.time()
    auftr, gesehen = [], set()
    for m in matches:
        mid = str(m.get("id"))
        if mid in gemischt or (m.get("kickoff_ts") or 0) < jetzt + 300:
            continue
        g, swap = betlabel.finde_spiel(spiele, m["home"], m["away"], m.get("kickoff_ts"))
        if not g or g["I"] in gesehen:
            continue
        gesehen.add(g["I"])
        proto["zugeordnet"] += 1
        if VIRTUELL_RE.search(str(g.get("L") or "").lower()) or tore_jugend(m, g.get("L")) or kontinental(m, g.get("L")) \
                or tore_jugend({"home": g.get("O1"), "away": g.get("O2")}):
            continue
        p = _p12(g.get("x12") or {})
        if not p or max(p) < ECKEN_FAV_MIN:
            continue
        proto["fav_klar"] += 1
        if ECKEN_NUR_AUSWAERTS and p[1] > p[0]:      # Favorit auswärts → Außenseiter spielt zu Hause
            proto["heim_aussenseiter"] = proto.get("heim_aussenseiter", 0) + 1
            continue
        auftr.append((mid, m, g, p))

    def eins(a):
        try:
            return a, betlabel.ecken_leitern(a[2]["I"])
        except Exception:
            return a, None

    tipps = []
    with ThreadPoolExecutor(8) as ex:
        for (mid, m, g, p), lad in ex.map(eins, auftr):
            proto["abgefragt"] += 1
            if lad is None:
                proto["fehler"] += 1
                continue
            fav_heim = p[0] >= p[1]
            key = "corners_gast" if fav_heim else "corners_heim"        # Außenseiter (BL-Orientierung)
            best = None
            for lk, q in (lad.get(key) or {}).items():
                if lk[0] != "u":
                    continue
                L = float(lk[1:])
                if abs(L - int(L) - 0.5) > 1e-9 or not (ECKEN_Q_MIN <= q <= ECKEN_Q_MAX):
                    continue
                if best is None or abs(q - ECKEN_Q_ZIEL) < abs(best[1] - ECKEN_Q_ZIEL):
                    best = (L, q)
            if not best:
                proto["ohne_linie"] += 1
                continue
            team = g["O2"] if fav_heim else g["O1"]
            fav = g["O1"] if fav_heim else g["O2"]
            tipps.append(dict(match_id=mid, bl_id=g["I"], seite="gast" if fav_heim else "heim", team=team, favorit=fav,
                              p_fav=round(max(p), 3), linie=best[0], richtung="unter", q=best[1],
                              spiel=f"{g['O1']} – {g['O2']}", liga=g.get("L"), kickoff_ts=g.get("S")))
    tipps.sort(key=lambda t: t.get("kickoff_ts") or 0)
    proto["tipps"] = len(tipps)
    proto["sekunden"] = round(time.time() - t0, 1)
    return tipps, proto


def ecken_block(tipps, esc=lambda s: s):
    import datetime as _dt
    from zoneinfo import ZoneInfo
    B = ZoneInfo("Europe/Berlin")
    kopf = "🟧 <b>AUSSENSEITER-ECKEN UNTER</b> · klarer Favorit ≥ 75 % · nur Außenseiter auswärts"
    if not tipps:
        return kopf + "\n<i>gerade kein Spiel mit Favorit ≥ 75 % (Heimteam) und Außenseiter-Ecken-Linie 1,30–2,10</i>"
    z = [kopf, f"<i>{len(tipps)} Tipps · Team-Ecken des Außenseiters unter · Siegchance aus der BL-1X2-Quote</i>", ""]
    for t in tipps:
        ko = _dt.datetime.fromtimestamp(t["kickoff_ts"], B).strftime("%H:%M") if t.get("kickoff_ts") else "?"
        z.append(f"{ko} {esc(t['spiel'])} <i>({esc(t.get('liga') or '')})</i>")
        z.append(f"   Ecken {esc(t['team'])} unter {t['linie']:g} @{t['q']:.2f} · {esc(t['favorit'])} Siegchance {t['p_fav']:.0%}")
    # 28.10. (Lucio): keine eigenen 2er-Listen mehr – Paare nur noch im 🎫 SCHEINE-Block
    return "\n".join(z)


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
    # 28.10. (Lucio): keine eigenen 2er-Listen mehr – Paare nur noch im 🎫 SCHEINE-Block
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
        if kontinental(m, g.get("L")):              # 28.10. (Lucio): AFC/Kontinental raus (26.–27.10. 2/4, −16 %)
            proto["kontinental"] = proto.get("kontinental", 0) + 1
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
    # 28.10. (Lucio): keine eigenen 2er-Listen mehr – Paare nur noch im 🎫 SCHEINE-Block
    return "\n".join(z)


# 28.10. (Lucio: „genau diese Logik … im Scanner drin, 1:1“): fertige 2er-Scheine.
# Regel wie im Strategie-Backtest 15.–27.10. (269 Scheine, +34 %): je Block 2er in Anstoß-Reihenfolge,
# je Berliner Tag, 10 € je Schein; jedes Spiel nur einmal (Priorität Außenseiter-Ecken > Tore 3.5 > Karten).
SCHEIN_PRIO = ("ecken", "tore", "karten")


def _markt(art, t):
    if art == "tore":
        return f"Tore gesamt Über {t['linie']:g}"
    if art == "ecken":
        return f"Eckstöße {t.get('team') or t.get('seite')} Unter {t['linie']:g} ({'Auswärts' if t.get('seite') == 'gast' else 'Heim'})"
    wer = "gesamt" if t.get("seite") == "tot" else f"{t.get('team') or t.get('seite')} ({'Heim' if t.get('seite') == 'heim' else 'Auswärts'})"
    return f"Gelbe Karten {wer} {str(t.get('richtung', '')).capitalize()} {t['linie']:g}"


SCHEIN_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "scheine.json")
WETTLOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "karten_wetten.csv")
_STOP = {"city", "town", "united", "sporting", "real", "club", "athletic", "atletico", "deportivo", "rangers",
         "sport", "calcio", "football", "futbol", "united", "borussia", "olympique", "dynamo", "dinamo", "racing"}


def _tok(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]+", s) if len(w) >= 4 and w not in _STOP}


def gespielt_laden(tage, pfad=None):
    """28.10.: echte Scheine aus dem Wettlog, deren Spiele an einem der Tage (Berlin, YYYY-MM-DD) liegen."""
    import csv
    pfad = pfad or WETTLOG
    out = {}
    try:
        for r in csv.DictReader(open(pfad, encoding="utf-8")):
            if str(r.get("anstoss", ""))[:10] in tage or r.get("datum") in tage:
                out.setdefault(r["schein"], []).append(r)
    except Exception:
        pass
    return out


def _bein_passt(t, r):
    import datetime as _dt
    from zoneinfo import ZoneInfo
    if r.get("match_id") and str(r["match_id"]) == str(t.get("match_id")):
        return True
    ko = _dt.datetime.fromtimestamp(t.get("kickoff_ts") or 0, ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M")
    if str(r.get("anstoss", ""))[:16] != ko:
        return False
    return bool(_tok(t.get("spiel")) & _tok(r.get("spiel")))


def scheine(karten_tipps, tore_tipps, ecken_tipps, jetzt=None, state_pfad=None, log_pfad=None, speichern=True):
    """28.10.: Scheine mit Gedächtnis. Liefert {tag: (scheine, ohne_partner, gespielt)}.
    - gespielt: echte Scheine aus karten_wetten.csv; deren Spiele kommen in keinen neuen Schein.
    - eingefroren: ein einmal gezeigter Schein behält Nummer und Spiele, bis das erste Spiel anfängt;
      fällt ein Tipp vor Anstoß aus dem Block oder wird eines der Spiele gespielt, löst er sich auf.
    - neue Tipps werden je Block in Anstoß-Reihenfolge zu neuen Scheinen mit neuen Nummern."""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    B = ZoneInfo("Europe/Berlin")
    jetzt = jetzt or time.time()
    state_pfad = state_pfad or SCHEIN_STATE
    tag_von = lambda t: _dt.datetime.fromtimestamp(t["kickoff_ts"], B).strftime("%Y-%m-%d")
    heute = _dt.datetime.fromtimestamp(jetzt, B).strftime("%Y-%m-%d")
    quellen = {"ecken": ecken_tipps or [], "tore": tore_tipps or [], "karten": karten_tipps or []}
    pool, vergeben = {}, set()
    for art in SCHEIN_PRIO:
        for t in sorted(quellen[art], key=lambda t: t.get("kickoff_ts") or 0):
            if (t.get("kickoff_ts") or 0) < jetzt + 120:
                continue
            key = str(t.get("match_id") or t.get("spiel"))
            if key in vergeben:
                continue
            vergeben.add(key)
            pool[key] = (art, t)
    tage = sorted({tag_von(t) for _, t in pool.values()} | {heute})
    gesp = gespielt_laden(set(tage), log_pfad)
    beine = [r for rs in gesp.values() for r in rs]
    gespielt_keys = {k for k, (_, t) in pool.items() if any(_bein_passt(t, r) for r in beine)}
    try:
        st = json.load(open(state_pfad, encoding="utf-8"))
    except Exception:
        st = {}
    st = {tg: v for tg, v in st.items() if tg >= heute}
    benutzt, out = set(gespielt_keys), {}
    for tg in tage:
        alt = st.get(tg, {"nr": 0, "scheine": []})
        nr, sch = alt.get("nr", 0), []
        for s in alt.get("scheine", []):
            keys = s["keys"]
            arts = s.get("arts") or [s.get("art")] * len(keys)
            if any(k not in pool or k in benutzt or pool[k][0] != a_ for k, a_ in zip(keys, arts)):
                continue                                    # Tipp weg / gespielt / angefangen → auflösen
            sch.append({"nr": s["nr"], "arts": arts, "keys": keys})
            benutzt.update(keys)
        # 28.10. (Lucio): strikt nach Uhrzeit, nicht nach Märkten getrennt – alle freien Tipps des Tages
        # nach Anstoß sortiert und der Reihe nach gepaart (Backtest gemischt: 274 Scheine, +31 %).
        frei = sorted([k for k, (art, t) in pool.items() if k not in benutzt and tag_von(t) == tg],
                      key=lambda k: (pool[k][1].get("kickoff_ts") or 0, SCHEIN_PRIO.index(pool[k][0])))
        rest = []
        for i in range(len(frei) // 2):
            keys = frei[2 * i:2 * i + 2]
            nr += 1
            sch.append({"nr": nr, "arts": [pool[k][0] for k in keys], "keys": keys})
            benutzt.update(keys)
        if len(frei) % 2:
            rest.append((pool[frei[-1]][0], pool[frei[-1]][1]))
        st[tg] = {"nr": nr, "scheine": sch}
        sch_out = sorted([(s["nr"], s["arts"], [pool[k][1] for k in s["keys"]]) for s in sch],
                         key=lambda s: (s[2][0].get("kickoff_ts") or 0, s[0]))
        g_out = [(sid, rs) for sid, rs in gesp.items()
                 if any(str(r.get("anstoss", ""))[:10] == tg for r in rs) or (tg == heute and any(r.get("datum") == tg for r in rs))]
        out[tg] = (sch_out, rest, g_out)
    if speichern:
        try:
            os.makedirs(os.path.dirname(state_pfad), exist_ok=True)
            json.dump(st, open(state_pfad, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            pass
    return out


def scheine_block(karten_tipps, tore_tipps, ecken_tipps, esc=lambda s: s, jetzt=None, tage=None):
    import datetime as _dt
    from zoneinfo import ZoneInfo
    B = ZoneInfo("Europe/Berlin")
    name = {"ecken": "🟧 AUSSENSEITER-ECKEN", "tore": "🟥 TORE 3.5", "karten": "🟨 KARTEN"}
    tage = tage if tage is not None else scheine(karten_tipps, tore_tipps, ecken_tipps, jetzt)
    z = ["🎫 <b>SCHEINE</b> · 2er strikt nach Uhrzeit · 10 € je Schein · kein Spiel doppelt",
         "<i>🟥 Tore 3.5 · 🟧 Außenseiter-Ecken · 🟨 Karten · Nummern bleiben fest · gespielte Spiele (Wettlog) kommen nicht mehr vor</i>"]
    sym = {"gewonnen": "✅", "verloren": "❌", "offen": "⏳"}
    for tag, (sch, rest, gesp) in tage.items():
        z.append("")
        z.append(f"<b>{_dt.date.fromisoformat(tag).strftime('%d.%m.')}</b> · {len(sch)} offene Scheine"
                 + (f" · {len(gesp)} gespielt" if gesp else ""))
        if gesp:
            z.append("<b>✅ GESPIELT</b>")
            for sid, rs in gesp:
                st_ = rs[0].get("schein_status") or "offen"
                teile = []
                for r in rs:
                    teile.append(f"{esc(str(r.get('spiel', '')).split(' – ')[0])} {sym.get(r.get('tipp_status') or 'offen', '⏳')}")
                z.append(f"   {sym.get(st_, '⏳')} {esc(sid.replace('-' + tag, ''))} @{float(rs[0].get('gesamtquote') or 0):.2f}: " + " + ".join(teile))
        for nr, arts, paar in sch:
            q = paar[0]["q"] * paar[1]["q"]
            z.append(f"<b>{nr}) {''.join(name[a_][:1] for a_ in arts)} @{q:.2f}</b> → {10 * q:.2f} €")
            for art, t in zip(arts, paar):
                ko = _dt.datetime.fromtimestamp(t["kickoff_ts"], B).strftime("%H:%M")
                z.append(f"   {ko} {esc(t['spiel'])} <i>({esc(t.get('liga') or '')})</i>")
                z.append(f"      {name[art][:1]} {esc(_markt(art, t))} @{t['q']:.2f}")
        for art, t in rest:
            ko = _dt.datetime.fromtimestamp(t["kickoff_ts"], B).strftime("%H:%M")
            z.append(f"   <i>ohne Partner: {ko} {esc(t['spiel'])} · {name[art][:1]} {esc(_markt(art, t))} @{t['q']:.2f}</i>")
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
    if not kontinental({"league": "AFC Champions League Elite"}) or not kontinental({"league": "UEFA Europa League"}) \
            or kontinental({"league": "England Championship"}) or kontinental({"league": "Germany DFB Pokal"}) \
            or kontinental({"league": "Aruba Championship"}):
        print("Kontinentalcup-Erkennung falsch"); ok = False
    p = _p12({"1": 1.20, "2": 6.0, "3": 13.0})
    if not p or not (0.75 < p[0] < 0.85 and p[1] < 0.1) or _p12({}) is not None:
        print("Außenseiter-Ecken: 1X2 ohne Marge falsch", p); ok = False
    return ok
