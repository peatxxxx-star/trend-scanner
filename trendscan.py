"""Trend-Scanner für die Spaßscheine (20.11.2026, Lucio).

Stündlich: scores24 für die nächsten 14 Stunden auslesen, Serien-Trends sammeln,
bei BetLabel das Spiel suchen, 1X2-Quote und die Quote genau dieses Markts holen,
dann nur die verbleibenden neuen Signale ins Telegram schicken.

Lucios Vorgaben (20.11.):
- KEINE Wettbewerbs-Filter (Pokal/Länderspiel/„Championship“ usw. prüft er selbst –
  viele normale Ligen heißen auch „Championship“).
- Schwache Serien raus.
- Favoriten-Regeln erst NACH der BetLabel-Abfrage (scores24 liefert nur Quoten zu
  den angezeigten Serien, nicht die 1X2-Quote).
- Nur Signale mit aktueller BetLabel-Quote zwischen 1,20 und 1,50.
Marktregeln aus dem Spaßschein-Check:
- Team-Unter nur, wenn das Team auswärts spielt oder laut 1X2 Außenseiter ist
  (Heim-Favorit nur bis Quote 1,30, mit Hinweis „Gegner hinten prüfen“).
- Ecken gesamt unter nur, wenn beide 1X2-Quoten >= 2,0.
- Ecken gesamt über nur mit Favorit <= 1,5.
- Tore gesamt unter mit Favorit < 1,60: nur Hinweis, nicht raus.
Nicht gescannt (spielt er nicht): Siegwetten (1X2, auch Halbzeit), genaues Ergebnis,
beide treffen.
"""
import gzip
import html as htmlmod
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import betlabel
import teamstats
from s24liste import get as s24_get

TZ = ZoneInfo("Europe/Berlin")
ROOT = Path(__file__).parent
CACHE = ROOT / ".tscache"                       # über actions/cache, nicht im Repo
S24_CACHE = CACHE / "s24.json.gz"
TM_CACHE = CACHE / "tm.json.gz"          # 21.11.: letzte Spiele für eigene Teamwerte
DATEN_FILTER = os.environ.get("TS_DATENFILTER", "1") == "1"   # 🔴 im Gegencheck -> raus
GESENDET = ROOT / "state" / "trendscan_gesendet.json"
LOGDIR = ROOT / "runs" / "trendscan"

FENSTER_H = float(os.environ.get("TS_FENSTER_H", "14"))
TABV = 4                         # Version des Tabellen-Parsers (neu laden bei Änderung)
TAB_MIN_SP = 8                   # 20.11.: weniger Tabellenspiele -> raus
Q_MIN, Q_MAX = 1.20, 1.50
TREND_MAX_ALTER = 6 * 3600    # Trends je Spiel höchstens 6 h wiederverwenden

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
TROCKEN = os.environ.get("TS_TROCKEN", "") == "1"   # 1 = nichts senden, nur Log
# 20.11.: Telegram erst scharf, wenn Lucio die Serien-Schwelle bestätigt hat (Datei state/trendscan_live)
if not (ROOT / "state" / "trendscan_live").exists():
    TROCKEN = True
try:   # Start per Push auf trendscan_now mit Inhalt "trocken" = Probelauf ohne Telegram
    if os.environ.get("GITHUB_EVENT_NAME") == "push" and (ROOT / "trendscan_now").read_text().strip().startswith("trocken"):
        TROCKEN = True
except OSError:
    pass


# ------------------------------------------------------------------ scores24
def _links_fuer_tage(tage):
    links = []
    for tag in sorted(tage):
        dd = datetime.strptime(tag, "%d-%m-%Y").strftime("%Y-%m-%d")
        for url in (f"https://scores24.live/de/soccer/{dd}", f"https://scores24.live/de/soccer?date={dd}"):
            try:
                links += re.findall(r"/de/soccer/(m-\d{2}-\d{2}-\d{4}-[^\"?#<>\s]+)", s24_get(url))
            except Exception as e:
                print("Tagesseite", url, e)
    for i in range(30):
        try:
            xml = s24_get(f"https://scores24.live/sitemaps/sitemap-de-soccer-upcoming-matches-{i}.xml")
        except Exception:
            break
        f = re.findall(r"/de/soccer/(m-[^<\"?#]+)", xml)
        if not f:
            break
        links += f
    return sorted({l[2:] for l in links if l[2:12] in tage})


def _norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower()
                  .replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss"))


def _tabelle(h, home, away, slug):
    """Ligatabelle aus dem eingebetteten JSON der Spielseite: Zeilen der beiden Teams.
    {} = keine Tabelle gefunden (Pokal/K.-o./Turnier ohne Tabelle)."""
    h = h.replace('\\"', '"')
    zeilen = []
    for m in re.finditer(r'"leagueTableRound":', h):
        ende = h.find('"promotionIdLive"', m.start())
        if ende < 0 or ende - m.start() > 200000:
            continue
        seg = h[m.start():ende]
        w = seg.find('"winTotal"')
        if w < 0:
            continue
        kopf = seg[:w]
        c = kopf.rfind('"country":{')
        vor = kopf[:c] if c > 0 else kopf
        namen = re.findall(r'"name":"([^"]+)"', vor)
        slugs = re.findall(r'"slug":"([^"]+)"', vor)

        def zahl(k):
            mm = re.search(r'"%s":(\d+)' % k, seg)
            return int(mm.group(1)) if mm else None
        rnd = re.match(r'"leagueTableRound":(null|"([^"]*)")', seg)
        tid = re.search(r'"leagueTableId":"([^"]+)"', seg)
        tname = re.search(r'"leagueTableName":"([^"]+)"', seg)
        def dek(t):
            try:
                return json.loads('"%s"' % t) if t and "\\u" in t else t
            except Exception:
                return t
        zeilen.append({"team": dek(namen[-1]) if namen else None, "slug": slugs[-1] if slugs else None,
                       "tid": tid.group(1) if tid else None, "tab": dek(tname.group(1)) if tname else None,
                       "runde": dek(rnd.group(2)) if rnd and rnd.group(2) else None,
                       "pos": zahl("sortPositionTotal"), "sp": zahl("matchesTotal"), "s": zahl("winTotal"),
                       "u": zahl("drawTotal"), "n": zahl("lossTotal"), "tore": zahl("goalsForTotal"),
                       "gegen": zahl("goalsAgainstTotal"), "pkt": zahl("pointsTotal")})

    rest = slug[11:] if slug and len(slug) > 11 else ""

    def passt(z, name, seite):
        zs = z.get("slug") or ""
        if zs and rest and ((seite == "h" and rest.startswith(zs + "-"))
                            or (seite == "g" and rest.endswith("-" + zs))):
            return True
        a, b = _norm(z["team"]), _norm(name)
        if a and b and (a == b or (len(a) > 3 and a in b) or (len(b) > 3 and b in a)):
            return True
        return False

    _tabelle.zuletzt = [z["team"] for z in zeilen][:8]
    hz = [z for z in zeilen if z["sp"] is not None and passt(z, home, "h")]
    gz = [z for z in zeilen if z["sp"] is not None and passt(z, away, "g")]
    if not zeilen:
        return {}                                              # gar keine Tabelle auf der Seite
    if bool(hz) != bool(gz):                                   # eine Seite gefunden: ähnlichsten Namen
        from difflib import SequenceMatcher                    # aus derselben Tabelle nehmen
        fest = (hz or gz)[0]
        name = away if hz else home
        kand = [z for z in zeilen if z["tid"] == fest["tid"] and z is not fest and z["sp"] is not None]
        best = max(kand, key=lambda z: SequenceMatcher(None, _norm(z["team"]), _norm(name)).ratio(), default=None)
        if best and SequenceMatcher(None, _norm(best["team"]), _norm(name)).ratio() >= 0.5:
            (gz if hz else hz).append(best)
    if not hz or not gz:
        return {"unklar": True}                                # Tabelle da, Teams nicht zugeordnet
    # Beide Teams können in mehreren Tabellen stehen (z. B. Hauptrunde + 4er-Play-off-Gruppe).
    # Die kleinste gemeinsame Tabelle ist die aktuelle Phase (Kolumbien: Cuadrangular statt Liga).
    groesse = {}
    for z in zeilen:
        groesse[z["tid"]] = groesse.get(z["tid"], 0) + 1
    paare = [(a, b) for a in hz for b in gz if a["tid"] and a["tid"] == b["tid"]]
    if not paare:
        return {"fremd": True, "heim": hz[0], "gast": gz[0]}     # verschiedene Tabellen
    paare.sort(key=lambda p: groesse.get(p[0]["tid"], 99))
    a, b = paare[0]
    alle = [{"name": x["tab"], "runde": x["runde"], "teams": groesse.get(x["tid"]), "sp": [x["sp"], y["sp"]]}
            for x, y in paare]
    return {"name": a["tab"], "runde": a["runde"], "teams": groesse.get(a["tid"]), "heim": a, "gast": b,
            "alle": alle if len(alle) > 1 else None}


def _spiel_s24(slug):
    rec = {"slug": slug, "t": time.time()}
    try:
        h = s24_get(f"https://scores24.live/de/soccer/m-{slug}")
        names = re.findall(r'"name"\s*:\s*"([^"]{3,120})"', h)
        paar = next((n for n in names if " - " in n), None)
        if paar:
            rec["home"], rec["away"] = [x.strip() for x in paar.split(" - ", 1)]
        try:
            i = names.index("Fußball")
            rec["liga"] = names[i + 2] if len(names) > i + 2 else None
        except ValueError:
            rec["liga"] = None
        try:
            rec["tab"] = _tabelle(h, rec.get("home"), rec.get("away"), slug)
            rec["tabv"] = TABV
            if not rec["tab"]:
                rec["tab_teams"] = getattr(_tabelle, "zuletzt", None)
        except Exception as e:
            rec["tab_fehler"] = str(e)[:80]
        tag = datetime.strptime(slug[:10], "%d-%m-%Y").date()
        for sd in re.findall(r'"startDate"\s*:\s*"([^"]+)"', h):
            try:
                dt = datetime.fromisoformat(sd.replace("Z", "+00:00"))
            except ValueError:
                continue
            if abs((dt.astimezone(TZ).date() - tag).days) <= 1:
                rec["start"] = int(dt.timestamp())
                break
    except Exception as e:
        rec["fehler"] = f"html: {str(e)[:80]}"
        return rec
    url = f"https://scores24.live/rapi/localized/matches/soccer/{slug}/trends?lang=de&audience=de"
    for _ in range(2):
        try:
            rec["trends"] = (json.loads(s24_get(url)) or {}).get("data") or []
            rec.pop("fehler", None)
            break
        except Exception as e:
            rec["fehler"] = f"trends: {str(e)[:80]}"
            time.sleep(1)
    return rec


def s24_laden(jetzt):
    cache = {}
    try:
        with gzip.open(S24_CACHE, "rt", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        pass
    heute = datetime.fromtimestamp(jetzt, TZ)
    tage = {heute.strftime("%d-%m-%Y"), (heute + timedelta(days=1)).strftime("%d-%m-%Y")}
    links = _links_fuer_tage(tage)
    bis = jetzt + FENSTER_H * 3600
    neu = []
    for slug in links:
        r = cache.get(slug)
        if r and r.get("start") and (r["start"] < jetzt or r["start"] > bis):
            continue                                   # außerhalb des Fensters, Anstoß bekannt
        if r and "trends" in r and r.get("tabv") == TABV and jetzt - r.get("t", 0) < TREND_MAX_ALTER:
            continue
        neu.append(slug)
    print(f"scores24: {len(links)} Spiele heute/morgen, {len(neu)} neu abzurufen", flush=True)
    with ThreadPoolExecutor(8) as ex:
        for rec in ex.map(_spiel_s24, neu):
            alt = cache.get(rec["slug"]) or {}
            if "trends" not in rec and "trends" in alt:
                rec["trends"] = alt["trends"]
            cache[rec["slug"]] = {**alt, **rec}
    # aufräumen: nur heute/morgen behalten
    cache = {k: v for k, v in cache.items() if k[:10] in tage}
    CACHE.mkdir(exist_ok=True)
    with gzip.open(S24_CACHE, "wt", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    return [v for v in cache.values()
            if v.get("trends") and v.get("home") and (not v.get("start") or jetzt < v["start"] < bis)]


# ------------------------------------------------------------------ Trends
_METRIK = {"total": "goals", "corners_total": "corners", "yellow_cards_total": "yellowcards",
           "offsides_total": "offsides", "shots_on_target_total": "on_target", "fouls_total": "fouls"}
_NAME = {"goals": "Tore", "corners": "Ecken", "yellowcards": "Gelbe Karten", "offsides": "Abseits",
         "on_target": "Schüsse aufs Tor", "fouls": "Fouls"}


def _zahl(x):
    try:
        return float(str(x).replace("_", "."))
    except (TypeError, ValueError):
        return None


def markt_aus_typ(typ):
    """scores24-Prognosetyp -> dict(art, metric, seite, richtung, linie) oder None."""
    if not typ or len(typ) < 2:
        return None
    a, w = typ[0], typ[1]
    if a == "double_chance":
        return {"art": "dc", "wahl": str(w)} if str(w) in ("x1", "x2", "12") else None
    if a in ("handicap1", "handicap2"):
        L = _zahl(w)
        return {"art": "hc", "seite": "heim" if a == "handicap1" else "gast", "linie": L} if L is not None else None
    m = re.fullmatch(r"(total|corners_total|yellow_cards_total|offsides_total|shots_on_target_total|fouls_total)"
                     r"(?:_(t1|t2))?_(over|under)(?:_(half1|half2))?", a)
    if not m:
        return None
    basis, team, ou, halb = m.groups()
    metric = _METRIK[basis]
    if halb:
        if metric != "goals" or not team:
            return None            # z. B. total_over_half1 = „Tor erzielt und kassiert“ – unklar, raus
        metric = "ht_goals" if halb == "half1" else "h2_goals"
    L = _zahl(w)
    if L is None:
        return None
    return {"art": "ou", "metric": metric, "seite": {"t1": "heim", "t2": "gast"}.get(team),
            "richtung": "über" if ou == "over" else "unter", "linie": L}


_RX_X = re.compile(r"in (\d+) der letzten (\d+)")
_RX_ALLE = re.compile(r"in (?:den )?letzten (\d+)")


def serie(fakt):
    m = _RX_X.search(fakt or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _RX_ALLE.search(fakt or "")
    if m:
        return int(m.group(1)), int(m.group(1))
    return None


def _luecken_ok(f):
    fehl = f["n"] - f["x"]
    return fehl <= 1 or (f["x"] > 20 and fehl <= 2)


def _anker(f):
    t = (f.get("text") or "").lower()
    zyklus = "zu hause" not in t and "auswärts" not in t
    return zyklus and f["x"] >= 10 and _luecken_ok(f)


def _zweiseitig(mk):
    """20.11. (Lucio): Märkte, bei denen scores24 Serien beider Teams liefert -> beide Pflicht:
    Gesamtmärkte, „trifft“ (auch 1./2. HZ: A trifft / B kassiert) und Doppelte Chance
    (A nicht verloren / B nicht gewonnen). Übrige Teammärkte: ein Anker genügt."""
    if mk["art"] == "dc":
        return True
    if mk["art"] != "ou":
        return False
    if not mk["seite"]:
        return True
    return mk["metric"] in ("goals", "ht_goals", "h2_goals") and mk["richtung"] == "über" and mk["linie"] == 0.5


def kandidaten(spiel):
    out = []
    for grp in spiel.get("trends") or []:
        if grp.get("name") in ("results", "correctscore", "btts"):
            continue
        for tr in grp.get("trends") or []:
            mk = markt_aus_typ((tr.get("prediction") or {}).get("type"))
            if not mk:
                continue
            fakten = []
            for gf in tr.get("grouped_facts") or []:
                for f in gf.get("facts") or []:
                    s = serie(f.get("fact"))
                    if s:
                        fakten.append({"typ": f.get("type"), "x": s[0], "n": s[1],
                                       "text": (f.get("text") or f.get("fact") or "").strip(),
                                       "team": ((f.get("team") or {}).get("name")),
                                       "tid": ((f.get("team") or {}).get("id"))})
            # 20.11. (Lucio, Serienregeln wie damals, vorerst ohne Head-to-Head):
            # Anker = Serie im normalen Spielzyklus (ohne Heim/Auswärts), >= 10 Treffer,
            # höchstens 1 Lücke (10/11 ja, 9/10 nein, 12/14 nein); 2 Lücken erst ab über 20 (22/24 ja, 19/21 nein).
            # Gesamtmärkte: beide Teams brauchen eine Serie, mindestens eine davon Anker;
            # das zweite Team >= 5 Treffer mit derselben Lückenregel (Heim/Auswärts erlaubt).
            # „trifft“ und Doppelte Chance wie Gesamtmärkte (beide Teams). Übrige Teammärkte: ein Anker genügt.
            team = [f for f in fakten if f["typ"] != "h2h"]
            anker = [f for f in team if _anker(f)]
            if not anker:
                continue
            if _zweiseitig(mk):
                ids = {f["tid"] for f in team if f["tid"]}
                ok = False
                for a in anker:
                    if any(f["tid"] and f["tid"] != a["tid"] and f["x"] >= 5 and _luecken_ok(f) for f in team):
                        ok = True
                        break
                if not ok or len(ids) < 2:
                    continue
            team.sort(key=lambda f: (not _anker(f), -(f["x"] / f["n"]), -f["n"]))
            if _zweiseitig(mk):     # je Team eine Serie zeigen
                zweit = next((f for f in team[1:] if f["tid"] != team[0]["tid"]), None)
                team = [team[0]] + ([zweit] if zweit else [])
            titel = ((tr.get("grouped_facts") or [{}])[0]).get("title") or ""
            out.append({**mk, "titel": titel, "fakten": team[:2],
                        "h2h": [f for f in fakten if f["typ"] == "h2h"][:1],
                        "key": f"{spiel['slug']}|{'|'.join(map(str, (tr.get('prediction') or {}).get('type')))}"})
    # gleiche Märkte (mehrfach geliefert) zusammenfassen
    seen, uniq = set(), []
    for k in out:
        if k["key"] not in seen:
            seen.add(k["key"])
            uniq.append(k)
    return uniq


# ------------------------------------------------------------------ BetLabel
def _gruppe(val, gid):
    for g in (val or {}).get("GE") or []:
        if g.get("G") == gid:
            return [e for col in g.get("E") or [] for e in col]
    return []


def _x12(haupt, liste_x12, swap):
    q = {}
    for e in _gruppe(haupt, 1):
        if e.get("T") in (1, 2, 3) and e.get("C"):
            q[e["T"]] = float(e["C"])
    if len(q) < 3 and liste_x12:
        q = {int(k): float(v) for k, v in liste_x12.items() if v}
    if len(q) < 3:
        return None
    h, x, a = q[1], q[2], q[3]
    return (a, x, h) if swap else (h, x, a)


def bl_quote(haupt, k, swap, sub_cache):
    """Quote genau dieses Markts bei BetLabel (Orientierung scores24) oder None."""
    if k["art"] == "dc":
        # 1xBet-Feed: Gruppe 8 Doppelte Chance, T4 = 1X, T5 = 12, T6 = X2
        wahl = k["wahl"]
        if swap and wahl in ("x1", "x2"):
            wahl = "x2" if wahl == "x1" else "x1"
        t = {"x1": 4, "12": 5, "x2": 6}[wahl]
        for e in _gruppe(haupt, 8):
            if e.get("T") == t and e.get("C"):
                return float(e["C"])
        return None
    if k["art"] == "hc":
        # 1xBet-Feed: Gruppe 2 Handicap, T7 = Heim (P = Heim-Handicap), T8 = Gast
        heim = (k["seite"] == "heim") != bool(swap)
        t = 7 if heim else 8
        for e in _gruppe(haupt, 2):
            if e.get("T") == t and e.get("P") is not None and abs(float(e["P"]) - k["linie"]) < 0.01 and e.get("C"):
                return float(e["C"])
        return None
    titel, abschnitt = betlabel.SUB[k["metric"]]
    if titel is None:
        val = haupt
    else:
        sg = betlabel._unterspiel(haupt, titel, abschnitt)
        if not sg:
            return None
        sid = sg.get("CI") or sg.get("I")
        if sid not in sub_cache:
            try:
                sub_cache[sid] = betlabel._spiel_detail(sid)
            except Exception:
                sub_cache[sid] = {}
        val = sub_cache[sid]
    if k["seite"] is None:
        leiter = betlabel._leiter(val, 17, 9, 10)
    else:
        heim = (k["seite"] == "heim") != bool(swap)
        leiter = betlabel._leiter(val, 15, 11, 12) if heim else betlabel._leiter(val, 62, 13, 14)
    return leiter.get((k["richtung"], float(k["linie"])))


# ------------------------------------------------------------------ Regeln
def regeln(k, x12, q):
    """(behalten, hinweis)"""
    if q is None:
        return False, "keine BL-Quote"
    if not (Q_MIN <= q <= Q_MAX):
        return False, f"Quote {q:.2f} außerhalb 1,20–1,50"
    # 21.11. (Lucio): Abseits und Schüsse aufs Tor komplett raus (keine Spieldaten zum Gegencheck)
    if k["art"] == "ou" and k["metric"] in ("offsides", "on_target"):
        return False, "Abseits/Schüsse aufs Tor gestrichen"
    if not x12:
        return True, "1X2 fehlt – Favoritenrolle selbst prüfen"
    h, x, a = x12
    fav = min(h, a)
    # 20.11. (Lucio): 1X2-Filter greifen direkt (statt nur Hinweis), damit nur noch Kandidaten kommen,
    # die nach dem Spaßschein-Check überhaupt Grün werden können.
    if k["art"] == "dc":
        s_ = 1 / h + 1 / x + 1 / a
        fair = {"x1": (1 / h + 1 / x), "x2": (1 / x + 1 / a), "12": (1 / h + 1 / a)}[k["wahl"]] / s_
        if fair < 1 / q:
            return False, f"DC laut 1X2 nur {fair:.0%}, nötig {1 / q:.0%}"
        return True, ""
    if k["seite"]:
        eigen, gegner = (h, a) if k["seite"] == "heim" else (a, h)
    if k["art"] == "hc":
        if k["linie"] > 0 and gegner < 1.60:
            return False, f"Handicap beim Außenseiter, Gegner Favorit {gegner:.2f}"
        return True, ""
    if k["art"] == "ou" and k["seite"] and k["richtung"] == "unter":
        if eigen >= gegner:                               # Außenseiter oder ausgeglichen
            return True, ""
        if q <= 1.30:
            return True, "Favorit – Gegner hinten prüfen"
        return False, "Team-Unter beim Favoriten"
    # 21.11. (Lucio): „trifft“ (auch 1./2. HZ) komplett gestrichen – 3 von 6 bei den Grün
    if (k["art"] == "ou" and k["seite"] and k["richtung"] == "über"
            and k["metric"] in ("goals", "ht_goals", "h2_goals") and k["linie"] == 0.5):
        return False, "trifft gestrichen"
    if (k["art"] == "ou" and k["seite"] and k["richtung"] == "über"
            and k["metric"] in ("goals", "ht_goals", "h2_goals") and gegner < 1.60):
        return False, f"Team-Tor beim Außenseiter, Gegner Favorit {gegner:.2f}"
    if k["art"] == "ou" and k["metric"] == "corners" and not k["seite"]:
        if k["richtung"] == "unter" and not (h >= 2.0 and a >= 2.0):
            return False, "Ecken unter, aber Favorit im Spiel"
        if k["richtung"] == "über" and fav > 1.5:
            return False, "Ecken über ohne Favorit <= 1,5"
    if k["art"] == "ou" and k["metric"] == "goals" and not k["seite"] and k["richtung"] == "unter" and fav < 1.60:
        return False, f"Tore unter mit Favorit {fav:.2f}"
    return True, ""


def label(k, home, away):
    if k["art"] == "dc":
        return {"x1": f"{home} verliert nicht (1X)", "x2": f"{away} verliert nicht (X2)",
                "12": "kein Unentschieden (12)"}[k["wahl"]]
    if k["art"] == "hc":
        team = home if k["seite"] == "heim" else away
        return f"{team} {k['linie']:+g}".replace(".", ",")
    L = f"{k['linie']:g}".replace(".", ",")
    halb = {"ht_goals": " in der 1. HZ", "h2_goals": " in der 2. HZ"}.get(k["metric"], "")
    metric = "goals" if k["metric"] in ("ht_goals", "h2_goals") else k["metric"]
    if k["seite"]:
        team = home if k["seite"] == "heim" else away
        if metric == "goals" and k["richtung"] == "über" and k["linie"] == 0.5:
            return f"{team} trifft{halb}"
        return f"{team} {_NAME[metric]} {k['richtung']} {L}{halb}"
    return f"{_NAME[metric]} gesamt {k['richtung']} {L}{halb}"


# ------------------------------------------------------------------ Telegram
_MSG_IDS = []
MSG_DATEI = ROOT / "state" / "trendscan_nachrichten.json"
LOESCHEN = ROOT / "state" / "trendscan_loeschen"
LISTE = ROOT / "state" / "trendscan_liste.json"


def _tg_api(methode, **daten):
    body = urllib.parse.urlencode(daten).encode()
    with urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{TG_TOKEN}/{methode}", data=body), timeout=30) as r:
        return json.loads(r.read().decode())


def alte_nachrichten_loeschen():
    """20.11. (Lucio): bisherige Scanner-Nachrichten löschen, danach nur noch die finalen Signale.
    Gespeicherte IDs zuerst; für den Lauf vom 20.11. früh (IDs nicht gespeichert) die letzten
    20 IDs vor einer Probe-Nachricht. Telegram lässt Bots nur Nachrichten der letzten 48 h löschen."""
    if not LOESCHEN.exists() or TROCKEN or not (TG_TOKEN and TG_CHAT):
        return None
    ids = set()
    try:
        ids |= {int(i) for i in json.loads(MSG_DATEI.read_text()) if i}
    except Exception:
        pass
    try:
        probe = _tg_api("sendMessage", chat_id=TG_CHAT, text="…")
        n = probe["result"]["message_id"]
        ids |= set(range(n - 20, n + 1))
    except Exception as e:
        print("Probe fehlgeschlagen:", e)
    geloescht = 0
    for i in sorted(ids):
        try:
            if _tg_api("deleteMessage", chat_id=TG_CHAT, message_id=i).get("ok"):
                geloescht += 1
        except Exception:
            pass
    LOESCHEN.unlink()
    MSG_DATEI.write_text("[]")
    print("alte Nachrichten gelöscht:", geloescht)
    return geloescht


def tg(text, leise=False):
    if TROCKEN or not (TG_TOKEN and TG_CHAT):
        print("— Telegram (nicht gesendet) —\n" + text, flush=True)
        return True
    body = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true",
                                   "disable_notification": "true" if leise else "false"}).encode()
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=body), timeout=30) as r:
                antwort = json.loads(r.read().decode())
                if antwort.get("ok"):
                    _MSG_IDS.append((antwort.get("result") or {}).get("message_id"))
                    return True
        except Exception as e:
            print("Telegram-Fehler:", e, file=sys.stderr)
        time.sleep(3)
    return False


def _q(x):
    return f"{x:.2f}".replace(".", ",")


# ------------------------------------------------------------------ Hauptlauf
def _gespielt():
    try:
        return json.loads((ROOT / "state" / "trendscan_gespielt.json").read_text())
    except Exception:
        return []


def _ist_gespielt(t, gespielt):
    return any(g in t["key"].split("|")[0] for g in gespielt)


def scheine(liste, jetzt):
    """21.11. (Lucio): Scheinvorschläge aus allen 🟢 – nach Anstoß sortiert, ein Leg pro Spiel,
    je 3 Legs pro Schein (Rest als 2er; ein einzelnes übriges Leg -> letzte beiden Scheine 2+2)."""
    def puffer(t):
        try:
            import re as _re
            w = [int(a) / int(b) for a, b in _re.findall(r"(\d+)/(\d+)", (t.get("check") or [""])[0])[:2]]
            return min(w) - 1 / t["quote"]
        except Exception:
            return 0
    try:   # bereits gespielte Spiele (Slug-Teile), von Hand gepflegt
        gespielt = json.loads((ROOT / "state" / "trendscan_gespielt.json").read_text())
    except Exception:
        gespielt = []
    gruen = {}
    for t in liste.values():
        if t.get("sym") != "🟢" or t.get("anstoss", 0) <= jetzt + 300:
            continue
        if any(g in t["key"].split("|")[0] for g in gespielt):
            continue
        sp = t["key"].split("|")[0]
        if sp not in gruen or puffer(t) > puffer(gruen[sp]):
            gruen[sp] = t
    legs = sorted(gruen.values(), key=lambda t: (t["anstoss"], t["spiel"]))
    n = len(legs)
    if n < 2:
        return []
    groessen = [3] * (n // 3)
    rest = n % 3
    if rest == 2:
        groessen.append(2)
    elif rest == 1:
        groessen = groessen[:-1] + [2, 2]
    out, i = [], 0
    for g in groessen:
        out.append(legs[i:i + g])
        i += g
    return out


def schein_text(sch):
    if not sch:
        return ""
    z = ["🎫 <b>Scheinvorschläge</b> (alle 🟢, ein Leg pro Spiel)"]
    for nr, legs in enumerate(sch, 1):
        q = 1.0
        for t in legs:
            q *= t["quote"]
        bis = datetime.fromtimestamp(min(t["anstoss"] for t in legs), TZ)
        z.append(f"\n<b>Schein {nr}</b> · abgeben bis {bis:%a %H:%M} · Quote ≈ {_q(q)}")
        for t in legs:
            bl = t.get("bl")
            z.append(f"  {datetime.fromtimestamp(t['anstoss'], TZ):%H:%M} <b>{htmlmod.escape(t['spiel'])}</b>"
                     + (f" (BetLabel: {htmlmod.escape(bl)})" if bl and bl != t["spiel"] else "")
                     + f"\n     {htmlmod.escape(t['markt'])} @ {_q(t['quote'])}")
    z.append("\nQuote bei BetLabel vor Abgabe prüfen (Liste bis zu 1 h alt).")
    return "\n".join(z)


def _tab_zeile(tab, spiel):
    """📊 Heim 15. · 16 Sp. · 13:28 (0,8:1,8) | Gast …"""
    if not tab or tab.get("fremd") or tab.get("unklar"):
        return ""
    teile = []
    for z, name in ((tab["heim"], spiel.split(" – ")[0]), (tab["gast"], spiel.split(" – ")[-1])):
        sp_ = z.get("sp") or 0
        if not sp_:
            return ""
        a, b = (z.get("tore") or 0) / sp_, (z.get("gegen") or 0) / sp_
        schnitt = f"{a:.1f}:{b:.1f}".replace(".", ",")
        teile.append(f"{htmlmod.escape(name)} {z.get('pos') or '?'}. · {sp_} Sp. · "
                     f"{z.get('tore')}:{z.get('gegen')} ({schnitt})")
    r = f" [{htmlmod.escape(tab['runde'])}]" if tab.get("runde") else ""
    return "📊 " + " | ".join(teile) + r


def main():
    jetzt = time.time()
    t0 = time.time()
    gesendet = {}
    try:
        gesendet = json.loads(GESENDET.read_text())
    except Exception:
        pass
    gesendet = {k: v for k, v in gesendet.items() if jetzt - v < 48 * 3600}
    geloescht = alte_nachrichten_loeschen()
    if geloescht is not None:
        gesendet = {}          # nach dem Aufräumen alles Gültige im Fenster neu schicken

    spiele = s24_laden(jetzt)
    kand = []
    for sp in spiele:
        ks = kandidaten(sp)        # 20.11.: jedes Mal alles neu bewerten (vollständige Liste)
        if ks:
            kand.append((sp, ks))
    print(f"Spiele mit starken Serien: {len(kand)} ({sum(len(k) for _, k in kand)} Trends)", flush=True)

    log = {"stand": datetime.fromtimestamp(jetzt, TZ).isoformat(), "spiele_s24": len(spiele), "signale": [],
           "geloescht": geloescht,
           "raus": [], "nicht_bei_bl": [], "gruppen_test": None}
    # 20.11. (Lucio): Tabelle direkt als Filter – ohne Ligatabelle (Pokal/K.-o./Turnier) oder mit
    # weniger als TAB_MIN_SP Spielen (Saisonstart, Play-off-Gruppen) raus.
    mit_tab = [sp for sp, _ in kand if sp.get("tab") and not sp["tab"].get("unklar")]
    log["tabelle"] = {"spiele": len(kand), "mit_tabelle": len(mit_tab),
                      "ohne_beispiele": [{"spiel": f"{sp['home']} – {sp['away']}", "gefunden": sp.get("tab_teams")}
                                         for sp, _ in kand if sp.get("tab") == {} or (sp.get("tab") or {}).get("unklar")][:20]}
    if kand and len(mit_tab) < 0.2 * len(kand):
        log["tabelle"]["warnung"] = "Tabellen-Parser liefert kaum Treffer – Filter ausgesetzt"
        print("WARNUNG: Tabellen kaum gefunden – Tabellenfilter ausgesetzt", flush=True)
    else:
        bleibt = []
        for sp, ks in kand:
            tab = sp.get("tab")
            grund = None
            if tab is None:
                pass                                   # noch nicht geladen – kein Urteil
            elif tab.get("unklar"):
                pass                                   # Teams nicht zugeordnet – kein Urteil
            elif not tab:
                sp["tab_hinweis"] = "keine Tabelle bei scores24 – Pokal/K.-o.? selbst prüfen"
            elif tab.get("fremd"):
                sp["tab_hinweis"] = "Teams in verschiedenen Tabellen – Turnier/Play-off? selbst prüfen"
            else:
                n = min(tab["heim"]["sp"] or 0, tab["gast"]["sp"] or 0)
                if n < TAB_MIN_SP:
                    grund = f"nur {n} Spiele in der Tabelle ({tab.get('runde') or tab.get('name') or ''})".strip()
            if grund:
                for k in ks:
                    log["raus"].append({"spiel": f"{sp['home']} – {sp['away']}", "liga": sp.get("liga"),
                                        "markt": label(k, sp["home"], sp["away"]), "key": k["key"],
                                        "hinweis": grund})
            else:
                bleibt.append((sp, ks))
        log["tabelle"]["raus_spiele"] = len(kand) - len(bleibt)
        kand = bleibt
    print(f"Nach Tabellenfilter: {len(kand)} Spiele", flush=True)
    if not kand:
        _speichern(gesendet, log, t0)
        return

    bl = [g for g in betlabel.lade_spiele() if jetzt < g["S"] < jetzt + (FENSTER_H + 1) * 3600]
    print(f"BetLabel: {len(bl)} Spiele im Fenster", flush=True)

    def eins(item):
        sp, ks = item
        g, swap = betlabel.finde_spiel(bl, sp["home"], sp["away"], sp.get("start"))
        if not g:
            return sp, None, None, None, [(k, None, "Spiel nicht bei BetLabel") for k in ks], None
        try:
            haupt = betlabel._spiel_detail(g["I"])
        except Exception as e:
            return sp, g, swap, None, [(k, None, f"Abruf fehlgeschlagen ({type(e).__name__})") for k in ks], None
        x12 = _x12(haupt, g.get("x12"), swap)
        sub = {}
        res = []
        for k in ks:
            try:
                q = bl_quote(haupt, k, swap, sub)
            except Exception as e:
                q = None
            res.append((k, q, None))
        gruppen = sorted({(gr.get("G"), e.get("T")) for gr in haupt.get("GE") or []
                          for col in gr.get("E") or [] for e in col})
        return sp, g, swap, x12, res, gruppen

    treffer, paare = [], []
    with ThreadPoolExecutor(betlabel.THREADS) as ex:
        for sp, g, swap, x12, res, gruppen in ex.map(eins, kand):
            if gruppen and log["gruppen_test"] is None:
                log["gruppen_test"] = {"spiel": f"{g['O1']} - {g['O2']}", "G_T": gruppen[:80]}
            if not g:
                log["nicht_bei_bl"].append(f"{sp['home']} – {sp['away']}")
                continue
            for k, q, fehler in res:
                ok, hinweis = regeln(k, x12, q) if not fehler else (False, fehler)
                eintrag = {"spiel": f"{sp['home']} – {sp['away']}", "liga": g.get("L") or sp.get("liga"),
                           "anstoss": g["S"], "markt": label(k, sp["home"], sp["away"]), "quote": q,
                           "x12": x12, "hinweis": hinweis, "key": k["key"], "tab": sp.get("tab"),
                           "bl": f"{g.get('O1')} – {g.get('O2')}" if g.get("O1") else None,
                           "serie": [f["text"] for f in k["fakten"]],
                           "h2h": [f["text"] for f in k["h2h"]]}
                if sp.get("tab_hinweis"):
                    eintrag["hinweis"] = "; ".join(x for x in (hinweis, sp["tab_hinweis"]) if x)
                if ok:
                    treffer.append(eintrag)
                    paare.append((eintrag, k, sp))
                else:
                    log["raus"].append(eintrag)

    # 21.11. (Lucio): eigene Teamwerte aus den letzten Ligaspielen (scores24) statt FootyStats.
    # Pro Signal: Trefferquote beider Teams über alle Ligaspiele der Saison und in der Rolle,
    # mit Spielzahl und Break-even. 🔴 (eine Seite unter Break-even) fliegt raus.
    try:
        ein = {}
        for e, k, sp in paare:
            slug = e["key"].split("|")[0]
            tab = sp.get("tab") if isinstance(sp.get("tab"), dict) else {}
            nh = (tab.get("heim") or {}).get("sp") if tab and not tab.get("unklar") else None
            ng = (tab.get("gast") or {}).get("sp") if tab and not tab.get("unklar") else None
            ein[slug] = (slug, nh, ng)
        stats = teamstats.laden(list(ein.values()), TM_CACHE)
        bleibt, n_check = [], 0
        for e, k, sp in paare:
            st = stats.get(e["key"].split("|")[0]) or {}
            po = bool(st.get("po_heim") and st.get("po_gast"))
            tb = sp.get("tab")
            mit_tab = isinstance(tb, dict) and bool(tb) and not tb.get("unklar") and not tb.get("fremd")
            # ohne Tabelle bei scores24: echte Liga, wenn beide Teams in derselben Liga spielen
            if not mit_tab and st.get("liga_heim") and st.get("liga_heim") == st.get("liga_gast"):
                mit_tab = True
                if "keine Tabelle" in (e.get("hinweis") or ""):
                    e["hinweis"] = "; ".join(x for x in e["hinweis"].split("; ") if "keine Tabelle" not in x)
            g = teamstats.gegencheck(k, st, sp["home"], sp["away"], e["quote"], mit_tab, e.get("x12"))
            if po:
                # 21.11. (Lucio): reguläre Runde laut Tabelle vorbei -> Play-off/Meisterrunde/Finalphase = raus
                e["hinweis"] = "Play-off/Meisterrunde: reguläre Saison laut Tabelle beendet"
                log["raus"].append(e)
                continue
            if g:
                n_check += 1
                e["check"] = g["zeilen"]
                e["sym"] = g["sym"]
                if g["sym"] == "🔴" and DATEN_FILTER:
                    e["hinweis"] = "Daten: eine Seite unter Break-even"
                    log["raus"].append(e)
                    continue
                # 21.11. (Lucio, Preston bei West Ham): Lücken-Regel – Team-über (Tore/Ecken) eines
                # Außenseiters gegen Favorit <= 1,40 und Daten > 15 Punkte über Break-even -> raus
                x12 = e.get("x12")
                if (x12 and k["art"] == "ou" and k["seite"] and k["richtung"] == "über"
                        and k["metric"] in ("goals", "corners")):
                    gegner = x12[2] if k["seite"] == "heim" else x12[0]
                    try:
                        quote_min = min(a / b for a, b in g["alle"] if b)
                    except ValueError:
                        quote_min = 0
                    if gegner <= 1.40 and quote_min - 1 / e["quote"] > 0.15:
                        e["hinweis"] = (f"Lücke: Daten {quote_min:.0%} vs. BE {1 / e['quote']:.0%}, "
                                        f"Gegner Favorit {gegner:.2f}".replace(".", ","))
                        log["raus"].append(e)
                        continue
            bleibt.append(e)
        log["gegencheck"] = {"signale": len(paare), "mit_daten": n_check, "rot_raus": len(paare) - len(bleibt)}
        treffer = bleibt
    except Exception as ex:
        import traceback
        log["gegencheck"] = {"fehler": f"{type(ex).__name__}: {str(ex)[:200]}", "tb": traceback.format_exc()[-1500:]}
        print("Gegencheck-Fehler:", ex, flush=True)
    log["signale"] = treffer
    print(f"Signale nach BetLabel und Regeln: {len(treffer)}, raus: {len(log['raus'])}, "
          f"nicht bei BL: {len(log['nicht_bei_bl'])}", flush=True)

    # 20.11. (Lucio): immer EINE vollständige, aktuelle Liste statt nur neuer Signale.
    # Gestartete Spiele fliegen raus, neue Signale bekommen 🆕. Was einmal drin war, bleibt
    # bis zum Anpfiff drin (mit der zuletzt bekannten Quote). Die vorige Liste wird gelöscht.
    try:
        alte_liste = json.loads(LISTE.read_text())
    except Exception:
        alte_liste = {}
    liste = {t["key"]: t for t in treffer}
    # Alte Einträge, die im aktuellen Lauf an einer Regel scheitern, fliegen raus
    # (sonst bleiben Signale von vor einer Regeländerung bis zum Anpfiff stehen).
    jetzt_raus = {t["key"] for t in log["raus"]}
    entfernt = 0
    for key, t in alte_liste.items():
        if key in liste or t.get("anstoss", 0) <= jetzt:
            continue
        if key in jetzt_raus:
            entfernt += 1
            continue
        liste[key] = t
    log["entfernt"] = entfernt
    neu_keys = {k for k in liste if k not in gesendet}
    try:
        alte_ids = [int(i) for i in json.loads(MSG_DATEI.read_text()) if i]
    except Exception:
        alte_ids = []
    log["liste"] = len(liste)
    log["neu"] = len(neu_keys)
    erzwingen = (ROOT / "state" / "trendscan_liste_senden").exists()
    senden = bool(liste) and (bool(neu_keys) or not alte_ids or erzwingen or entfernt > 0)
    if senden:
        nach_spiel = {}
        for t in sorted(liste.values(), key=lambda t: (t["anstoss"], t["spiel"], t["markt"])):
            nach_spiel.setdefault((t["anstoss"], t["spiel"]), []).append(t)
        bloecke = []
        for (ko, spiel), ts in nach_spiel.items():
            x12 = ts[0]["x12"]
            kopf = (f"<b>{datetime.fromtimestamp(ko, TZ):%a %H:%M}</b> {htmlmod.escape(spiel)}\n"
                    f"<i>{htmlmod.escape(ts[0]['liga'] or '')}</i>"
                    + (f" · 1X2 {_q(x12[0])} / {_q(x12[1])} / {_q(x12[2])}" if x12 else ""))
            tz = _tab_zeile(ts[0].get("tab"), spiel)
            if tz:
                kopf += "\n" + tz
            zeilen = []
            for t in ts:
                z = (f"{'🆕' if t['key'] in neu_keys else '•'} {t.get('sym', '') + ' ' if t.get('sym') else ''}"
                     f"{htmlmod.escape(t['markt'])} @ <b>{_q(t['quote'])}</b>"
                     + (" · 🎫 gespielt" if _ist_gespielt(t, _gespielt()) else ""))
                for sz in t["serie"][:2]:
                    z += f"\n   {htmlmod.escape(sz)}"
                for cz in t.get("check") or []:
                    z += f"\n   {htmlmod.escape(cz.strip())}" if cz.startswith(" ") else f"\n   📈 {htmlmod.escape(cz[2:])}"
                if t["hinweis"]:
                    z += f"\n   ⚠️ {htmlmod.escape(t['hinweis'])}"
                zeilen.append(z)
            bloecke.append(kopf + "\n" + "\n".join(zeilen))
        kopfzeile = (f"📋 <b>Aktuelle Liste</b> · Stand {datetime.fromtimestamp(jetzt, TZ):%H:%M} · "
                     f"{len(liste)} Signale aus {len(nach_spiel)} Spielen"
                     + (f" · 🆕 {len(neu_keys)} neu" if neu_keys and len(neu_keys) < len(liste) else "") + "\n\n")
        if not TROCKEN:
            for i in alte_ids:                    # vorige Liste löschen
                try:
                    _tg_api("deleteMessage", chat_id=TG_CHAT, message_id=i)
                except Exception:
                    pass
        teil, ok_alle, erste = kopfzeile, True, True
        for b in bloecke:
            if len(teil) + len(b) > 3800:
                ok_alle &= tg(teil.rstrip(), leise=not erste)
                erste = False
                teil = ""
            teil += b + "\n\n"
        ok_alle &= tg(teil.rstrip(), leise=not erste)
        sch = scheine(liste, jetzt)
        log["scheine"] = [[f"{t['spiel']}: {t['markt']} @ {t['quote']}" for t in legs] for legs in sch]
        if sch:
            ok_alle &= tg(schein_text(sch), leise=False)
        else:
            gsp = _gespielt()
            offen = sum(1 for t in liste.values() if t.get("sym") == "🟢" and t.get("anstoss", 0) > jetzt + 300
                        and not _ist_gespielt(t, gsp))
            ok_alle &= tg("🎫 Keine Scheinvorschläge – "
                          + ("alle 🟢 schon gespielt." if offen == 0 else "nur 1 🟢 offen, für einen Schein braucht es 2."),
                          leise=True)
        log["telegram"] = "trocken" if TROCKEN else ("ok" if ok_alle else "FEHLER")
        if not TROCKEN:
            MSG_DATEI.write_text(json.dumps([i for i in _MSG_IDS if i]))
            if erzwingen:
                (ROOT / "state" / "trendscan_liste_senden").unlink()
            if ok_alle:
                for key in liste:
                    gesendet.setdefault(key, jetzt)
    elif liste:
        # 21.11. (Lucio): jede Stunde ein Lebenszeichen – leise Kurznachricht, die vorige wird ersetzt
        status_datei = ROOT / "state" / "trendscan_status.json"
        gsp = _gespielt()
        n_gruen = sum(1 for t in liste.values() if t.get("sym") == "🟢" and t.get("anstoss", 0) > jetzt + 300
                      and not _ist_gespielt(t, gsp))
        text = (f"⏱ Lauf {datetime.fromtimestamp(jetzt, TZ):%H:%M} · nichts Neues · "
                + (f"{n_gruen} 🟢 noch nicht gespielt – siehe Liste oben" if n_gruen else "kein offenes 🟢"))
        if not TROCKEN and TG_TOKEN and TG_CHAT:
            try:
                for i in json.loads(status_datei.read_text()):
                    try:
                        _tg_api("deleteMessage", chat_id=TG_CHAT, message_id=i)
                    except Exception:
                        pass
            except Exception:
                pass
            vorher = len(_MSG_IDS)
            ok = tg(text, leise=True)
            status_datei.write_text(json.dumps([i for i in _MSG_IDS[vorher:] if i]))
            log["telegram"] = "status" if ok else "FEHLER"
        else:
            print(text, flush=True)
    if not TROCKEN:
        LISTE.write_text(json.dumps(liste, ensure_ascii=False))
    _speichern(gesendet, log, t0)


def _speichern(gesendet, log, t0):
    GESENDET.parent.mkdir(exist_ok=True)
    GESENDET.write_text(json.dumps(gesendet, ensure_ascii=False, indent=0))
    LOGDIR.mkdir(parents=True, exist_ok=True)
    log["sekunden"] = round(time.time() - t0, 1)
    log["bl_anfragen"] = betlabel._stats.get("anfragen")
    (LOGDIR / "letzter_lauf.json").write_text(json.dumps(log, ensure_ascii=False, indent=1, default=str))
    print("fertig in", log["sekunden"], "s", flush=True)


if __name__ == "__main__":
    main()
