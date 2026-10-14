"""BetLabel-Quoten je Tipp (14.10., Lucio: "Ich brauche zu jedem meiner Märkte
eine Quote dazu. Direkt im Telegram.").

BetLabel läuft auf der 1xBet-Plattform. Deren Quoten-Feed antwortet ohne
Anmeldung unter https://betlabel.com/service-api/LineFeed/ :
  GetChampsZip   – alle Fußball-Ligen mit Vor-Spiel-Angebot
  Get1x2_VZip    – Spiele einer Liga (Id, Teams, Anstoß)
  GetGameZip     – alle Märkte eines Spiels; Sondermärkte (Ecken, Karten,
                   Schüsse aufs Tor, Abseits, Fouls, Halbzeiten) hängen als
                   eigene Unterspiele (SG) mit eigener Id daran.
Gesamt-Über/Unter: Gruppe 17 (T 9 = über, T 10 = unter, P = Linie).
Team-Über/Unter: Gruppe 15 = Heim (T 11/12), Gruppe 62 = Gast (T 13/14).
"""
import gzip
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor

BASE = "https://betlabel.com/service-api/LineFeed/"
UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36")
THREADS = 8

# Unterspiel je Markt: (Titel TG, Abschnitt PN). "" = Hauptspiel/ganzes Spiel.
SUB = {
    "goals": (None, ""),
    "ht_goals": ("", "1. Halbzeit"),
    "h2_goals": ("", "2. Halbzeit"),
    "corners": ("Eckstöße", ""),
    "ht_corners": ("Eckstöße", "1. Halbzeit"),
    "yellowcards": ("Gelbe Karten", ""),
    "ht_yellowcards": ("Gelbe Karten", "1. Halbzeit"),
    "on_target": ("Schüsse auf das Tor", ""),
    "offsides": ("Abseitsstellungen", ""),
    "fouls": ("Fouls", ""),
    "shots_total": ("Torschüsse", ""),
    "throwins": ("Einwürfe", ""),
    "goalkicks": ("Abstöße", ""),
    "freekicks": ("Freistöße", ""),
}
# Ligen, die keine echten Spiele sind
CHAMP_SKIP = ("alternative", "gegen spieler", "spezial", "langfristig", "statistik",
              "sieger", "torschütze", "torschutze", "fantasy", "cyber", "esport", "simul")

_GENERIC = {"fc", "fk", "sk", "sc", "cf", "ac", "as", "cd", "ud", "sd", "ca", "club", "de", "la",
            "le", "the", "afc", "bk", "if", "ik", "ks", "nk", "ofk", "mfk", "msk", "tj", "sv", "vfl",
            "vfb", "tsg", "fsv", "cs", "ssd", "asd", "gd", "sl", "fcm", "rc", "calcio", "1", "us", "ss",
            "spvgg", "tsv", "sg", "jk", "fbk", "ff", "gif", "aik", "cfr", "csm", "acs", "nd",
            "hnk", "gnk", "rnk", "nk", "fsc", "ksc", "kv", "krc", "rsc", "sco", "esp", "ec", "se",
            "cr", "kf", "fci", "pae", "ae"}
_ALIAS = {"man": "manchester", "psg": "paris", "utd": "united", "st": "saint", "sankt": "saint",
          "spb": "petersburg", "moskva": "moscow", "moskau": "moscow", "munchen": "munich",
          "koln": "cologne", "dinamo": "dynamo", "inter": "internazionale", "wolves": "wolverhampton",
          "spurs": "tottenham", "sheff": "sheffield", "nottm": "nottingham", "athletico": "athletic"}
_YOUTH = {"u17", "u18", "u19", "u20", "u21", "u22", "u23"}
_WOMEN = {"w", "women", "frauen", "damen", "fem", "femenino", "feminine", "feminino", "ladies", "dames", "zene", "kobiety"}
_RES = {"ii", "b", "2", "reserves", "res", "reserve", "amateure"}

_lock = threading.Lock()
_stats = {"anfragen": 0, "fehler": 0}


def _get(pfad, timeout=25, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = BASE + pfad + ("?" + q if q else "")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip, deflate"})
    for versuch in range(2):
        try:
            with _lock:
                _stats["anfragen"] += 1
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                enc = r.headers.get("Content-Encoding", "")
                if enc == "gzip":
                    raw = gzip.decompress(raw)
                elif enc == "deflate":
                    raw = zlib.decompress(raw)
                return json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            if versuch:
                with _lock:
                    _stats["fehler"] += 1
                raise
            time.sleep(1.5)


# ---------------------------------------------------------------- Namen
def _norm_tokens(name):
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c)).lower()
    n = n.replace("ø", "o").replace("æ", "ae").replace("ß", "ss").replace("ł", "l").replace("đ", "d")
    n = re.sub(r"\(([^)]*)\)", r" \1 ", n)
    return [t for t in re.split(r"[^a-z0-9]+", n) if t]


def name_info(name):
    toks = _norm_tokens(name)
    marks = set()
    core = []
    for t in toks:
        t = _ALIAS.get(t, t)
        if t in ("u21", "u23"):
            marks.add("R")             # Reserveteams heißen mal "II", mal "U21"/"U23"
        elif t in _YOUTH:
            marks.add(t)
        elif t in _WOMEN:
            marks.add("W")
        elif t in _RES:
            marks.add("R")
        elif t not in _GENERIC and len(t) >= 2:
            core.append(t)
    if not core:                       # nur Allerweltswörter -> doch nehmen
        core = [t for t in toks if t not in _YOUTH and t not in _WOMEN and t not in _RES]
    return core, frozenset(marks)


def _tok_eq(a, b):
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b[:4]) and b.startswith(a[:4])):
        return True
    return False


def _lose(a, b):
    """Wie name_score, aber ohne Jugend/Frauen/Reserve-Prüfung (nur für
    Verdachtsmeldungen, nie für die Zuordnung)."""
    ca, _ = name_info(a)
    cb, _ = name_info(b)
    if not ca or not cb:
        return 0.0
    short, long_ = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    return sum(1 for t in short if any(_tok_eq(t, u) for u in long_)) / len(short)


def name_score(a, b):
    """0..1: Anteil der Kernwörter des kürzeren Namens, die im anderen stehen.
    -1, wenn Jugend/Frauen/Reserve-Merkmale nicht passen."""
    ca, ma = name_info(a)
    cb, mb = name_info(b)
    if ma != mb:
        return -1.0
    if not ca or not cb:
        return 0.0
    if "".join(ca) == "".join(cb):
        return 1.0
    short, long_ = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    hit = sum(1 for t in short if any(_tok_eq(t, u) for u in long_))
    sc = hit / len(short)
    # zusammengeschriebene Namen ("Slovanbratislava")
    if sc < 1 and ("".join(ca) in "".join(cb) or "".join(cb) in "".join(ca)):
        sc = max(sc, 0.9)
    return sc


# ---------------------------------------------------------------- Spielliste
def lade_spiele():
    """Alle Vor-Spiel-Fußballspiele: [{I, L, O1, O2, S}]."""
    champs = _get("GetChampsZip", sport=1, lng="de", country=1).get("Value") or []
    champs = [c for c in champs
              if c.get("LI") and not any(w in (c.get("L") or "").lower() for w in CHAMP_SKIP)]

    def eine(c):
        try:
            # Namen auf Englisch (näher an den Namen im Scanner als "Moskau", "Grosny")
            v = _get("Get1x2_VZip", sports=1, champs=c["LI"], count=50, lng="en", mode=4,
                     country=1, getEmpty="true").get("Value") or []
        except Exception:
            return []
        return [{"I": g.get("I"), "L": g.get("L"), "O1": g.get("O1"), "O2": g.get("O2"),
                 "S": int(g.get("S") or 0)} for g in v if g.get("I") and g.get("O1") and g.get("O2")]

    spiele = []
    with ThreadPoolExecutor(THREADS) as ex:
        for teil in ex.map(eine, champs):
            spiele += teil
    seen, out = set(), []
    for g in spiele:
        if g["I"] not in seen:
            seen.add(g["I"])
            out.append(g)
    return out


def finde_spiel(spiele, home, away, kickoff_ts):
    """(Spiel, vertauscht) oder (None, None)."""
    best, best_sc, swap = None, 0.0, False
    for g in spiele:
        dt = abs(g["S"] - int(kickoff_ts or 0)) if kickoff_ts else 0
        if dt > 3 * 3600:
            continue
        for sw in (False, True):
            o1, o2 = (g["O2"], g["O1"]) if sw else (g["O1"], g["O2"])
            sh, sa = name_score(home, o1), name_score(away, o2)
            if sh < 0 or sa < 0:
                continue
            # beide Namen ordentlich ODER einer sicher + Anstoß exakt
            # Ein Team sicher erkannt + Anstoß auf 5 min gleich: Das ist das
            # Spiel, auch wenn BetLabel den Gegner ganz anders nennt (ein Team
            # spielt nie zwei Spiele gleichzeitig).
            ok = (sh >= 0.6 and sa >= 0.6) or (max(sh, sa) >= 0.99 and min(sh, sa) >= 0.3 and dt <= 600) \
                or (max(sh, sa) >= 0.99 and dt <= 300)
            if not ok:
                continue
            sc = sh + sa - (dt / 3600) * 0.3 - (0.2 if sw else 0)
            if sc > best_sc:
                best, best_sc, swap = g, sc, sw
    return (best, swap) if best else (None, None)


# ---------------------------------------------------------------- Quoten
def _leiter(value, gruppe, t_over, t_under):
    out = {}
    for g in (value or {}).get("GE") or []:
        if g.get("G") != gruppe:
            continue
        for col in g.get("E") or []:
            for e in col:
                t, p, c = e.get("T"), e.get("P"), e.get("C")
                if p is None or c is None:
                    continue
                if t == t_over:
                    out[("über", float(p))] = float(c)
                elif t == t_under:
                    out[("unter", float(p))] = float(c)
    return out


def _unterspiel(haupt, titel, abschnitt):
    for sg in (haupt or {}).get("SG") or []:
        tg = (sg.get("TG") or "").strip()
        pn = (sg.get("PN") or "").strip()
        if tg == titel and pn == abschnitt:
            return sg
    return None


def _spiel_detail(gid):
    return _get("GetGameZip", id=gid, lng="de", isSubGames="true", GroupEvents="true",
                countevents=500, grMode=4, partner=1, topGroups="", marketType=1).get("Value") or {}


def quoten_fuer_spiel(gid, bedarf, swap=False):
    """bedarf: Menge von (metric_key_basis, seite) mit seite None/'heim'/'gast'.
    Liefert {(metric, seite): {"leiter": {(richtung, linie): quote}} | {"fehlt": grund}}."""
    haupt = _spiel_detail(gid)
    sub_cache = {}
    out = {"_titel": sorted({(sg.get("TG") or "") for sg in haupt.get("SG") or []})}
    for metric, seite in bedarf:
        if metric not in SUB:
            out[(metric, seite)] = {"fehlt": "Markt unbekannt"}
            continue
        titel, abschnitt = SUB[metric]
        if titel is None:
            val = haupt
        else:
            sg = _unterspiel(haupt, titel, abschnitt)
            if not sg:
                out[(metric, seite)] = {"fehlt": "Markt nicht im Angebot"}
                continue
            sid = sg.get("CI") or sg.get("I")
            if sid not in sub_cache:
                try:
                    sub_cache[sid] = _spiel_detail(sid)
                except Exception as exc:
                    sub_cache[sid] = {"_fehler": str(exc)}
            val = sub_cache[sid]
        if seite is None:
            leiter = _leiter(val, 17, 9, 10)
        else:
            heim = (seite == "heim") != bool(swap)
            leiter = _leiter(val, 15, 11, 12) if heim else _leiter(val, 62, 13, 14)
        out[(metric, seite)] = {"leiter": leiter} if leiter else {"fehlt": "keine Linien"}
    return out


def basis_und_seite(metric_key):
    """team_corners_heim -> ('corners', 'heim'); corners -> ('corners', None)."""
    m = re.match(r"team_(.+)_(heim|gast)$", metric_key or "")
    if m:
        return m.group(1), m.group(2)
    return metric_key, None


def bewerte(leiter, richtung, linie):
    """{'q': Quote an genau dieser Linie} oder {'q': None, 'nah': (Linie, Quote)}."""
    try:
        linie = float(linie)
    except (TypeError, ValueError):
        return {"q": None}
    q = leiter.get((richtung, linie))
    if q:
        return {"q": q}
    nah = [(L, c) for (d, L), c in leiter.items() if d == richtung and abs(L - round(L)) > 0.01]
    if not nah:
        return {"q": None}
    L, c = min(nah, key=lambda x: (abs(x[0] - linie), x[0]))
    return {"q": None, "nah": (L, c)}


def hole_alle(auftraege):
    """auftraege: {key: (home, away, kickoff_ts, {(metric, seite): [(richtung, linie, sigkey), ...]})}
    Ergebnis: {sigkey: dict(q=..., nah=..., fehlt=..., spiel=...)} und Protokoll."""
    t0 = time.time()
    proto = {"spiele_bl": 0, "gefunden": 0, "nicht_gefunden": [], "titel": {}}
    try:
        spiele = lade_spiele()
    except Exception as exc:
        proto["fehler"] = f"Spielliste: {type(exc).__name__}: {exc}"
        return {}, proto
    proto["spiele_bl"] = len(spiele)
    ergebnis = {}

    def eins(item):
        key, (home, away, ko, bedarf) = item
        g, swap = finde_spiel(spiele, home, away, ko)
        res = {}
        if not g:
            for lst in bedarf.values():
                for _, _, sk in lst:
                    res[sk] = {"fehlt": "Spiel nicht bei BetLabel"}
            return key, None, res, None
        try:
            q = quoten_fuer_spiel(g["I"], set(bedarf), swap)
        except Exception as exc:
            for lst in bedarf.values():
                for _, _, sk in lst:
                    res[sk] = {"fehlt": f"Abruf fehlgeschlagen ({type(exc).__name__})"}
            return key, g, res, None
        for mk, lst in bedarf.items():
            info = q.get(mk) or {"fehlt": "?"}
            for richtung, linie, sk in lst:
                if "leiter" in info:
                    r = bewerte(info["leiter"], richtung, linie)
                    if r.get("q") is None and not r.get("nah"):
                        r["fehlt"] = f"keine {richtung}-Linie"
                else:
                    r = {"q": None, "fehlt": info["fehlt"]}
                r["spiel"] = f"{g['O1']} - {g['O2']}"
                res[sk] = r
        return key, g, res, q.get("_titel")

    with ThreadPoolExecutor(THREADS) as ex:
        for key, g, res, titel in ex.map(eins, list(auftraege.items())):
            ergebnis.update(res)
            for sk, r in res.items():
                proto.setdefault("tipps", []).append(
                    [sk, r.get("spiel"), r.get("q"), r.get("nah"), r.get("fehlt")])
            if g:
                proto["gefunden"] += 1
                for t in titel or []:
                    proto["titel"][t] = proto["titel"].get(t, 0) + 1
            else:
                home, away, ko, _ = auftraege[key]
                nah = sorted((g2 for g2 in spiele if ko and abs(g2["S"] - ko) <= 900),
                             key=lambda g2: -(max(name_score(home, g2["O1"]), 0) + max(name_score(away, g2["O2"]), 0)))[:3]
                proto["nicht_gefunden"].append(
                    f"{home} – {away} | BL zur selben Zeit: " + "; ".join(f"{g2['O1']} - {g2['O2']}" for g2 in nah))
                # Verdacht: BetLabel hat zur selben Zeit ein Spiel, in dem eines
                # der Teams (ohne U19/II/Frauen-Merkmal) wiederzuerkennen ist ->
                # wahrscheinlich nur anders benannt. Wird im Telegram gemeldet.
                for g2 in nah:
                    if max(_lose(home, g2["O1"]), _lose(away, g2["O2"]),
                           _lose(home, g2["O2"]), _lose(away, g2["O1"])) >= 0.6:
                        proto.setdefault("verdacht", []).append(
                            {"spiel": f"{home} – {away}", "bl": f"{g2['O1']} - {g2['O2']}"})
                        break
    proto["anfragen"] = _stats["anfragen"]
    proto["fehler_anfragen"] = _stats["fehler"]
    proto["sekunden"] = round(time.time() - t0, 1)
    return ergebnis, proto


def selbsttest():
    ok = True
    pruef = [
        (("Slovan Bratislava U19", "ŠK Slovan Bratislava U19"), True),
        (("Slovan Bratislava U19", "ŠK Slovan Bratislava"), False),
        (("MSK Povazska Bystrica", "Povazska Bystrica"), True),
        (("FC Kosice", "FC Košice"), True),
        (("Bodo/Glimt", "FK Bodø-Glimt"), True),
        (("Bayern Munich (W)", "Bayern München"), False),
        (("Manchester City", "Manchester United"), False),
        (("Spartak Trnava", "Spartak Moskau"), False),
        (("Man City U19", "Manchester City U19"), True),
        (("Dinamo Moscow", "Dynamo Moscow"), True),
        (("JK Nomme Kalju II", "Nomme Kalju U21"), True),
        (("Nomme Kalju U19", "Nomme Kalju U21"), False),
        (("TJ Slavoj Boleraz", "Boleraz"), True),
        (("Paris Saint Germain", "Paris SG"), True),
    ]
    for (a, b), soll in pruef:
        sc = name_score(a, b)
        ist = sc >= 0.6
        if ist != soll:
            print(f"BetLabel-Namen: {a!r} vs {b!r} -> {sc:.2f}, erwartet {'gleich' if soll else 'verschieden'}")
            ok = False
    spiele = [{"I": 1, "L": "x", "O1": "Feyenoord Rotterdam", "O2": "Como Calcio", "S": 1000},
              {"I": 2, "L": "x", "O1": "Manchester City", "O2": "Paris SG", "S": 1000}]
    g, sw = finde_spiel(spiele, "Feyenoord", "Como", 1000)
    if not g or g["I"] != 1 or sw:
        print("BetLabel: Feyenoord–Como nicht gefunden"); ok = False
    g, sw = finde_spiel(spiele, "Feyenoord", "Como 1907 Lario", 1100)
    if not g or g["I"] != 1:
        print("BetLabel: anders benannter Gegner nicht aufgefangen"); ok = False
    g, sw = finde_spiel(spiele, "Paris Saint Germain", "Manchester City", 1000)
    if not g or g["I"] != 2 or not sw:
        print("BetLabel: vertauschtes Spiel nicht erkannt"); ok = False
    val = {"GE": [{"G": 17, "E": [[{"T": 9, "P": 5.5, "C": 2.22}], [{"T": 10, "P": 5.5, "C": 1.58}, {"T": 10, "P": 6.5, "C": 1.3}]]},
                  {"G": 15, "E": [[{"T": 11, "P": 4.5, "C": 1.9}], [{"T": 12, "P": 4.5, "C": 1.8}]]},
                  {"G": 62, "E": [[{"T": 13, "P": 3.5, "C": 2.0}], [{"T": 14, "P": 3.5, "C": 1.7}]]}]}
    L = _leiter(val, 17, 9, 10)
    if bewerte(L, "unter", 5.5).get("q") != 1.58 or bewerte(L, "unter", 4.5).get("nah") != (5.5, 1.58):
        print("BetLabel: Leiter falsch gelesen"); ok = False
    if _leiter(val, 62, 13, 14).get(("unter", 3.5)) != 1.7:
        print("BetLabel: Team-Linie falsch gelesen"); ok = False
    if basis_und_seite("team_corners_gast") != ("corners", "gast") or basis_und_seite("goals") != ("goals", None):
        print("BetLabel: Team-Schlüssel falsch"); ok = False
    return ok


if __name__ == "__main__":
    print("OK" if selbsttest() else "FEHLER")


def dump_liga(stichwort, pfad):
    """14.10.: Alle Linien aller Spiele einer Liga (z. B. 'Champions League')
    in eine Datei schreiben — für Einzelanalysen (Spaßscheine)."""
    champs = _get("GetChampsZip", sport=1, lng="de", country=1).get("Value") or []
    champs = [c for c in champs if stichwort.lower() in (c.get("L") or "").lower()
              and not any(w in (c.get("L") or "").lower() for w in CHAMP_SKIP)]
    out = []
    for c in champs:
        v = _get("Get1x2_VZip", sports=1, champs=c["LI"], count=50, lng="en", mode=4,
                 country=1, getEmpty="true").get("Value") or []
        for g in v:
            haupt = _spiel_detail(g["I"])
            e = {"spiel": f"{g.get('O1')} - {g.get('O2')}", "S": g.get("S"), "liga": c.get("L"),
                 "1x2": {str(x.get("T")): x.get("C") for x in g.get("E") or [] if x.get("G") == 1},
                 "maerkte": {}}
            e["maerkte"]["Tore"] = {f"{d} {L:g}": q for (d, L), q in sorted(_leiter(haupt, 17, 9, 10).items())}
            e["maerkte"]["Tore Heim"] = {f"{d} {L:g}": q for (d, L), q in sorted(_leiter(haupt, 15, 11, 12).items())}
            e["maerkte"]["Tore Gast"] = {f"{d} {L:g}": q for (d, L), q in sorted(_leiter(haupt, 62, 13, 14).items())}
            for sg in haupt.get("SG") or []:
                tg, pn = (sg.get("TG") or "").strip(), (sg.get("PN") or "").strip()
                if not tg or tg not in ("Eckstöße", "Gelbe Karten", "Schüsse auf das Tor", "Abseitsstellungen",
                                        "Fouls", "Torschüsse", "Einwürfe", "Abstöße"):
                    continue
                name = tg + (f" {pn}" if pn else "")
                try:
                    val = _spiel_detail(sg.get("CI") or sg.get("I"))
                except Exception:
                    continue
                for lab, gr, a, b in (("", 17, 9, 10), (" Heim", 15, 11, 12), (" Gast", 62, 13, 14)):
                    lad = _leiter(val, gr, a, b)
                    if lad:
                        e["maerkte"][name + lab] = {f"{d} {L:g}": q for (d, L), q in sorted(lad.items())}
            out.append(e)
    import pathlib
    pathlib.Path(pfad).write_text(json.dumps(out, ensure_ascii=False, indent=0))
    print(f"BetLabel-Dump {stichwort}: {len(out)} Spiele")
