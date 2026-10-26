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
from pathlib import Path
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
THREADS = 16          # 16.10. (GitHub-Minuten): 8 -> 16, das Marktarchiv läuft seit 15.10. fehlerfrei mit 16

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
          "spurs": "tottenham", "sheff": "sheffield", "nottm": "nottingham", "athletico": "athletic",
          # 18.10. (Lucio, ❓-Zeilen vom Wochenende)
          "jjk": "jyvaskyla", "jrs": "juniors", "jr": "junior", "akademia": "academy", "akademie": "academy",
          # 19.10. (Lucio, ❓ Al Qadisiya Al Khubar U21 – Al Hazm U21): arabische Umschrift
          "khubar": "khobar", "hazm": "hazem", "qadisiya": "qadisiyah",
          # 23.10. (Lucio, ❓ Maccabi Bnei Jadeidi-Makr – Bnei HaGolan VeHaGalil = BL Maccabi Bnei Jadida – Bnei Mamba Golan)
          "jadeidi": "jadida", "hagolan": "golan",
          # 25.10. (Lucio, ❓ Hapoel Rishon Letzion U19 = BL Hapoel Rishon Lezion Yehuda U19)
          "letzion": "lezion"}
# ganze Namen, die BetLabel anders führt (Reserveteams mit eigenem Namen)
_NAME_ERSATZ = {"recreativo granada": "granada ii",
               # 23.10. (Lucio, ❓ CD Pioneros Junior = BL Pioneros de Cancun II, Mexiko Liga TDP)
               "pioneros junior": "pioneros de cancun ii",
               # 24.10. (Lucio, ❓): russische "M"-Teams (Reserve) führt BetLabel als "(Youth)"
               "chayka m": "chayka youth",
               # 25.10. (Lucio, Sonntags-Check: "das mit der Zuordnung geht gar nicht")
               "cadiz mirandilla": "cadiz ii",              # Cádiz Mirandilla = Cádiz II (Tercera)
               "olimpo b blanca": "olimpo bahia blanca",    # "B Blanca" = Bahía Blanca, kein Reserveteam
               "vejgaard b": "vejgaard",                    # Vejgaard B(oldspilklub) = Vereinsname, kein Reserveteam
               "barcelona guayaquil": "barcelona sporting guayaquil",   # BL "Barcelona Sporting Club"
               "slavia prague iii": "slavia prague u20"}    # BL "Slavia Prague III" = Scanner "Slavia Prague U20"
_YOUTH = {"u17", "u18", "u19", "u20", "u21", "u22", "u23"}
_WOMEN = {"w", "women", "frauen", "damen", "fem", "femenino", "feminine", "feminino", "ladies", "dames", "zene", "kobiety"}
_RES = {"ii", "b", "2", "reserves", "res", "reserve", "amateure",
        "promesas", "akatemia",
        "amateur"}   # 24.10.: BetLabel "First Vienna (Amateur)" = First Vienna II   # 18.10.: Valladolid Promesas = Real Valladolid II, SJK Akatemia = SJK II
_YOUTH_WORT = {"youth", "jugend", "juvenil", "juveniles"}   # 18.10.: "academy"/"junior(s)" raus – Teil echter Vereinsnamen (Puskás Akadémia, Argentinos Juniors)   # 16.10.: BetLabel "(Youth)" = U19

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
    for alt, neu in _NAME_ERSATZ.items():
        # 25.10.: nur ganze Wörter ersetzen ("vejgaard b" darf "vejgaard boldklub" nicht treffen)
        n = re.sub(r"(?<![a-z0-9])" + re.escape(alt) + r"(?![a-z0-9])", neu, n)
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
        elif t in _YOUTH_WORT:
            marks.add("Y")
        elif t in _WOMEN:
            marks.add("W")
        elif t in _RES:
            marks.add("R")
        elif t not in _GENERIC and len(t) >= 2:
            core.append(t)
    if not core:                       # nur Allerweltswörter -> doch nehmen
        core = [t for t in toks if t not in _YOUTH and t not in _WOMEN and t not in _RES
                and t not in _YOUTH_WORT]
    return core, frozenset(marks)


def _marks_ok(ma, mb):
    """Merkmale passen. 16.10.: "Youth" (ohne Alter) passt zu jeder U17-U20."""
    if ma == mb:
        return True
    jung = lambda m: frozenset("Y" if x in ("u17", "u18", "u19", "u20") else x for x in m)
    return ("Y" in ma or "Y" in mb) and jung(ma) == jung(mb)


def _tok_eq(a, b):
    """Gleiches Wort, Wort ist Anfang des anderen (Bayer/Bayern) oder fast
    gleich (Sevilla/Seville). 15.10.: vorher reichten 4 gleiche Anfangs-
    buchstaben – dadurch war "Paris" = "Parikrma"."""
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    if a.startswith(b) or b.startswith(a):
        return True
    k = 0
    for x, y in zip(a, b):
        if x != y:
            break
        k += 1
    return k >= 0.8 * max(len(a), len(b))


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
    if not _marks_ok(ma, mb):
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
_SPIELE_CACHE = {"t": 0, "v": None}


LISTE_DATEI = Path(__file__).parent / "cache" / "bl_spiele.json.gz"
LISTE_NACHLADEN_AB = 100 * 60   # 16.10.: fehlende Spiele lösen frühestens nach 100 min ein Neuladen aus
LISTE_MAX_ALTER = 3 * 3600     # 15.10. (GitHub-Minuten): Spielliste nur alle 3 h neu


def lade_spiele(frisch=False):
    """Alle Vor-Spiel-Fußballspiele: [{I, L, O1, O2, S, x12}].
    15.10.: Die komplette Liste kostet ~380 Abfragen (~2 min Laufzeit). Sie wird
    deshalb in cache/ gespeichert und nur alle 3 h neu geladen; Spiele, die
    nicht in der gespeicherten Liste stehen, lösen eine frische Liste aus
    (hole_alle). Innerhalb eines Laufs immer nur einmal laden."""
    if not frisch and _SPIELE_CACHE["v"] is not None:
        return _SPIELE_CACHE["v"]
    if not frisch:
        try:
            with gzip.open(LISTE_DATEI, "rt", encoding="utf-8") as f:
                d = json.load(f)
            if time.time() - d["t"] < LISTE_MAX_ALTER:
                jetzt = time.time()
                v = [g for g in d["v"] if g["S"] > jetzt - 3 * 3600]
                _SPIELE_CACHE.update(t=d["t"], v=v, aus_datei=True, misses=d.get("misses") or [])
                return v
        except Exception:
            pass
    v = _lade_spiele_neu()
    _SPIELE_CACHE.update(t=time.time(), v=v, aus_datei=False, misses=[])
    _liste_speichern()
    return v


def _liste_speichern():
    try:
        LISTE_DATEI.parent.mkdir(exist_ok=True)
        with gzip.open(LISTE_DATEI, "wt", encoding="utf-8") as f:
            json.dump({"t": _SPIELE_CACHE["t"], "v": _SPIELE_CACHE["v"],
                       "misses": _SPIELE_CACHE.get("misses") or []},
                      f, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        pass


def _lade_spiele_neu():
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
                 "S": int(g.get("S") or 0),
                 "x12": {str(e.get("T")): e.get("C") for e in g.get("E") or [] if e.get("G") == 1}}
                for g in v if g.get("I") and g.get("O1") and g.get("O2")]

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


def _voll(a, b):
    """Beide Namen decken sich vollständig (jedes Kernwort des einen steht im anderen)."""
    ca, _ = name_info(a)
    cb, _ = name_info(b)
    if not ca or not cb:
        return False
    if "".join(ca) == "".join(cb):
        return True
    return all(any(_tok_eq(t, u) for u in cb) for t in ca) and all(any(_tok_eq(t, u) for u in ca) for t in cb)


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
            # 24.10. (Lucio, "Go"): Fall 3 nur noch, wenn das sichere Team in BEIDE
            # Richtungen voll passt. Vorher reichte "Pribram" ⊂ "Spartak Pribram", und
            # Spartak Pribram – Sobeslav landete bei Arsenal Ceska Lipa – 1. Pribram
            # (anderer Verein, anderes Spiel, falsche Quote in der BL-Liste).
            voll = (sh >= 0.99 and _voll(home, o1)) or (sa >= 0.99 and _voll(away, o2))
            ok = (sh >= 0.6 and sa >= 0.6) or (max(sh, sa) >= 0.99 and min(sh, sa) >= 0.3 and dt <= 600) \
                or (voll and dt <= 300)
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

    # Fehlt ein Spiel in der gespeicherten Liste, einmal frisch laden – aber
    # nicht wegen Spielen, die schon bei der letzten frischen Liste fehlten
    # (die hat BetLabel schlicht nicht im Angebot).
    def _schluessel(h, a, ko):
        return f"{h}|{a}|{ko}"
    fehlt = {_schluessel(h, a, ko) for k, (h, a, ko, _) in auftraege.items()
             if not finde_spiel(spiele, h, a, ko)[0]}
    # 16.10. (GitHub-Minuten): frisch laden nur, wenn die gespeicherte Liste
    # mindestens LISTE_NACHLADEN_AB alt ist – sonst kostete fast jeder zweite
    # Lauf ~2-4 min für Spiele, die BetLabel ohnehin (noch) nicht anbietet.
    alt_genug = time.time() - (_SPIELE_CACHE.get("t") or 0) >= LISTE_NACHLADEN_AB
    if _SPIELE_CACHE.get("aus_datei") and alt_genug and fehlt - set(_SPIELE_CACHE.get("misses") or []):
        spiele = lade_spiele(frisch=True)
        proto["liste_neu"] = len(fehlt)
        proto["spiele_bl"] = len(spiele)
        fehlt = {_schluessel(h, a, ko) for k, (h, a, ko, _) in auftraege.items()
                 if not finde_spiel(spiele, h, a, ko)[0]}
    if not _SPIELE_CACHE.get("aus_datei"):
        _SPIELE_CACHE["misses"] = sorted(fehlt)
        _liste_speichern()
    proto["liste_aus_datei"] = bool(_SPIELE_CACHE.get("aus_datei"))
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
                    # 18.10.: nur, wenn BEIDE Teams wiederzuerkennen sind (sonst
                    # Fehlalarme wie Gallos – San Pedro vs. San Pedro – Nouadhibou)
                    gerade = min(_lose(home, g2["O1"]), _lose(away, g2["O2"]))
                    quer = min(_lose(home, g2["O2"]), _lose(away, g2["O1"]))
                    if max(_lose(home, g2["O1"]), _lose(away, g2["O2"]),
                           _lose(home, g2["O2"]), _lose(away, g2["O1"])) >= 0.6 and max(gerade, quer) >= 0.3:
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
        # 23.10.: ❓-Fälle (Pioneros Junior = Pioneros de Cancun II, nicht die erste Mannschaft)
        (("CD Pioneros Junior", "Pioneros de Cancun II"), True),
        (("First Vienna II", "First Vienna (Amateur)"), True),
        (("First Vienna", "First Vienna (Amateur)"), False),
        (("Chayka M", "Chayka Peschanokopskoye (Youth)"), True),
        (("CD Pioneros Junior", "Pioneros de Cancun"), False),
        (("Maccabi Bnei Jadeidi-Makr", "Maccabi Bnei Jadida"), True),
        # 25.10.: ❓-Fälle aus dem Sonntags-Check
        (("Cadiz Mirandilla", "Cadiz II"), True),
        (("Cadiz Mirandilla", "Cadiz"), False),
        (("Olimpo B Blanca", "Club Olimpo"), True),
        (("Vejgaard B", "Vejgaard"), True),
        (("Barcelona Guayaquil", "Barcelona Sporting Club"), True),
        (("Slavia Prague U20", "Slavia Prague III"), True),
        (("Slavia Prague U20", "Slavia Prague"), False),
        (("Hapoel Rishon Letzion U19", "Hapoel Rishon Lezion Yehuda U19"), True),
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
        (("PSG", "Parikrma FC"), False),
        (("Sevilla", "Seville"), True),
        (("Bayer Leverkusen", "Bayer 04 Leverkusen"), True),
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
    # 24.10.: Teilname reicht nicht mehr für "sicheres Team" (Spartak Pribram ≠ 1. Pribram)
    sp2 = [{"I": 7, "L": "x", "O1": "Arsenal Ceska Lipa", "O2": "1. Pribram", "S": 5000}]
    if finde_spiel(sp2, "Spartak Pribram", "Spartak Sobeslav", 5000)[0]:
        print("BetLabel: Spartak Pribram – Sobeslav falsch zugeordnet"); ok = False
    sp3 = [{"I": 8, "L": "x", "O1": "Hapoel Tel Aviv", "O2": "Bnei Lol", "S": 6000}]
    if not finde_spiel(sp3, "Hapoel Tel Aviv", "Maccabi Xyz", 6000)[0]:
        print("BetLabel: sicheres Team + gleiche Zeit muss weiter reichen"); ok = False
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


# ----------------------------------------------------------------------------
# 15.10. (Lucio): Marktarchiv – einmal täglich das komplette BetLabel-Angebot
# (alle Über/Unter-Linien, Halbzeiten, Team-Märkte, 1X2) der nächsten 24 h
# sichern; die Ergebnisse kommen am nächsten Morgen dazu. Grundlage für die
# Strategie-Auswertung nach 3–4 Wochen. Gebremst + Notbremse bei Fehlern,
# damit die Live-Quoten im Telegram nie gefährdet werden.
ARCHIV_TITEL = {"Eckstöße": "corners", "Gelbe Karten": "yellowcards", "Schüsse auf das Tor": "on_target",
                "Abseitsstellungen": "offsides", "Fouls": "fouls", "Torschüsse": "shots_total",
                "Einwürfe": "throwins", "Abstöße": "goalkicks", "": "goals"}
ARCHIV_TEIL = {"": "", "1. Halbzeit": "_h1", "2. Halbzeit": "_h2"}


def _leitern_kompakt(val, basis):
    out = {}
    for name, gr, a, b in ((basis, 17, 9, 10), (basis + "_heim", 15, 11, 12), (basis + "_gast", 62, 13, 14)):
        lad = _leiter(val, gr, a, b)
        if lad:
            out[name] = {("o" if d == "über" else "u") + f"{L:g}": q for (d, L), q in sorted(lad.items())}
    return out


def karten_leitern(gid):
    """26.10.: Gelbe-Karten-Linien (ganzes Spiel) eines BL-Spiels für das Karten-Modell:
    {"yellowcards": {"o3.5": q, "u3.5": q, ...}, "yellowcards_heim": {...}, "yellowcards_gast": {...}}
    in BL-Orientierung (heim = O1). Leer, wenn BL keine Karten anbietet. 1–2 Abfragen."""
    haupt = _spiel_detail(gid)
    for sg in haupt.get("SG") or []:
        if (sg.get("TG") or "").strip() == "Gelbe Karten" and (sg.get("PN") or "").strip() == "":
            return _leitern_kompakt(_spiel_detail(sg.get("CI") or sg.get("I")), "yellowcards")
    return {}


def tore_leitern(gid):
    """26.10. abends: Tor-Linien (ganzes Spiel) eines BL-Spiels aus dem Hauptmarkt, 1 Abfrage:
    {"goals": {"o3.5": q, ...}, "goals_heim": {...}, "goals_gast": {...}} in BL-Orientierung."""
    return _leitern_kompakt(_spiel_detail(gid), "goals")


def archiv_sammeln(scanner_spiele, pfad, deadline_ts, pause=0.0, max_fehler=25, threads=16):
    """scanner_spiele: [{id, home, away, kickoff_ts}] (BetsAPI) für die Zuordnung."""
    import gzip as _gz
    t0 = time.time()
    _stats["anfragen"] = 0
    _stats["fehler"] = 0
    spiele = lade_spiele()
    jetzt = time.time()
    spiele = [g for g in spiele if jetzt < g["S"] < jetzt + 24 * 3600]
    # BetsAPI-Zuordnung (für die Ergebnisse)
    zu = {}
    for m in scanner_spiele:
        g, swap = finde_spiel(spiele, m["home"], m["away"], m.get("kickoff_ts"))
        if g and g["I"] not in zu:
            zu[g["I"]] = {"ev": str(m["id"]), "swap": bool(swap), "liga": m.get("league")}
    # 15.10.: Spiele ohne Gegenstück in unserer Datenbank lassen sich nie
    # auswerten (kein Ergebnis) – gar nicht erst abfragen.
    alle_bl = len(spiele)
    spiele = [g for g in spiele if g["I"] in zu]
    ergebnis, stop = [], {"grund": None}
    lock = threading.Lock()

    def eins(g):
        if stop["grund"]:
            return None
        if time.time() > deadline_ts:
            stop["grund"] = "Zeitgrenze"
            return None
        if _stats["fehler"] >= max_fehler:
            stop["grund"] = "Notbremse (Fehler)"
            return None
        e = {"I": g["I"], "S": g["S"], "L": g["L"], "O1": g["O1"], "O2": g["O2"], "x12": g.get("x12"),
             **(zu.get(g["I"]) or {}), "m": {}}
        try:
            haupt = _spiel_detail(g["I"])
            time.sleep(pause)
        except Exception:
            return None
        e["m"].update(_leitern_kompakt(haupt, "goals"))
        for sg in haupt.get("SG") or []:
            tg, pn = (sg.get("TG") or "").strip(), (sg.get("PN") or "").strip()
            if tg not in ARCHIV_TITEL or pn not in ARCHIV_TEIL or (tg == "" and pn == ""):
                continue
            if stop["grund"] or time.time() > deadline_ts:
                break
            try:
                val = _spiel_detail(sg.get("CI") or sg.get("I"))
                time.sleep(pause)
            except Exception:
                continue
            e["m"].update(_leitern_kompakt(val, ARCHIV_TITEL[tg] + ARCHIV_TEIL[pn]))
        return e

    # 15.10. (Lucio: "lass einfach limitless holzen" – GitHub zahlt man nach
    # Minuten): volle Geschwindigkeit; die Notbremse bei Fehlern bleibt,
    # damit eine Sperre nie die Live-Quoten trifft.
    with ThreadPoolExecutor(threads) as ex:
        for e in ex.map(eins, spiele):
            if e and e["m"]:
                with lock:
                    ergebnis.append(e)
    info = {"zeit": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "spiele_bl": alle_bl,
            "abgefragt": len(spiele),
            "gesichert": len(ergebnis), "zugeordnet": sum(1 for e in ergebnis if e.get("ev")),
            "linien": sum(len(v) for e in ergebnis for v in e["m"].values()),
            "anfragen": _stats["anfragen"], "fehler": _stats["fehler"], "abbruch": stop["grund"],
            "sekunden": round(time.time() - t0)}
    with _gz.open(pfad, "wt", encoding="utf-8") as f:
        json.dump({"info": info, "spiele": ergebnis}, f, ensure_ascii=False, separators=(",", ":"))
    return info
