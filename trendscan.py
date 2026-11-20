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
from s24liste import get as s24_get

TZ = ZoneInfo("Europe/Berlin")
ROOT = Path(__file__).parent
CACHE = ROOT / ".tscache"                       # über actions/cache, nicht im Repo
S24_CACHE = CACHE / "s24.json.gz"
GESENDET = ROOT / "state" / "trendscan_gesendet.json"
LOGDIR = ROOT / "runs" / "trendscan"

FENSTER_H = float(os.environ.get("TS_FENSTER_H", "14"))
Q_MIN, Q_MAX = 1.20, 1.50
SERIE_MIN_QUOTE = 0.80        # schwache Serie: bester Team-Fakt unter 80 % ...
SERIE_MIN_SPIELE = 6          # ... oder weniger als 6 Spiele
TREND_MAX_ALTER = 6 * 3600    # Trends je Spiel höchstens 6 h wiederverwenden

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
TROCKEN = os.environ.get("TS_TROCKEN", "") == "1"   # 1 = nichts senden, nur Log
# 20.11.: Telegram erst scharf, wenn Lucio die Serien-Schwelle bestätigt hat (Datei state/trendscan_live)
if not (ROOT / "state" / "trendscan_live").exists():
    TROCKEN = True
try:   # Start per Push auf trendscan_now mit Inhalt "trocken" = Probelauf ohne Telegram
    if os.environ.get("GITHUB_EVENT_NAME") == "push" and (ROOT / "trendscan_now").read_text().strip() == "trocken":
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
        if r and "trends" in r and jetzt - r.get("t", 0) < TREND_MAX_ALTER:
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
                                       "text": (f.get("fact") or "").strip(),
                                       "team": ((f.get("team") or {}).get("name"))})
            # Head-to-Head zählt nur als Bestätigung, entscheidend ist die Team-Serie mit >= 6 Spielen
            team = [f for f in fakten if f["typ"] != "h2h" and f["n"] >= SERIE_MIN_SPIELE]
            if not team:
                continue
            team.sort(key=lambda f: (-(f["x"] / f["n"]), -f["n"]))
            if team[0]["x"] / team[0]["n"] < SERIE_MIN_QUOTE:
                continue
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
    if not x12:
        return True, "1X2 fehlt – Favoritenrolle selbst prüfen"
    h, _, a = x12
    if k["art"] == "ou" and k["seite"] and k["richtung"] == "unter":
        eigen, gegner = (h, a) if k["seite"] == "heim" else (a, h)
        if k["seite"] == "gast" or eigen > gegner:
            return True, ""
        if q <= 1.30:
            return True, "Heim-Favorit – Gegner hinten prüfen"
        return False, "Team-Unter beim Heim-Favoriten"
    if k["art"] == "ou" and k["metric"] == "corners" and not k["seite"]:
        if k["richtung"] == "unter" and not (h >= 2.0 and a >= 2.0):
            return False, "Ecken unter, aber Favorit im Spiel"
        if k["richtung"] == "über" and min(h, a) > 1.5:
            return False, "Ecken über ohne Favorit <= 1,5"
    if k["art"] == "ou" and k["metric"] == "goals" and not k["seite"] and k["richtung"] == "unter" and min(h, a) < 1.60:
        return True, f"Favorit {min(h, a):.2f} – Unter mit Vorsicht"
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
def tg(text):
    if TROCKEN or not (TG_TOKEN and TG_CHAT):
        print("— Telegram (nicht gesendet) —\n" + text, flush=True)
        return True
    body = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=body), timeout=30) as r:
                if json.loads(r.read().decode()).get("ok"):
                    return True
        except Exception as e:
            print("Telegram-Fehler:", e, file=sys.stderr)
        time.sleep(3)
    return False


def _q(x):
    return f"{x:.2f}".replace(".", ",")


# ------------------------------------------------------------------ Hauptlauf
def main():
    jetzt = time.time()
    t0 = time.time()
    gesendet = {}
    try:
        gesendet = json.loads(GESENDET.read_text())
    except Exception:
        pass
    gesendet = {k: v for k, v in gesendet.items() if jetzt - v < 48 * 3600}

    spiele = s24_laden(jetzt)
    kand = []
    for sp in spiele:
        ks = [k for k in kandidaten(sp) if k["key"] not in gesendet]
        if ks:
            kand.append((sp, ks))
    print(f"Spiele mit neuen starken Serien: {len(kand)} ({sum(len(k) for _, k in kand)} Trends)", flush=True)

    log = {"stand": datetime.fromtimestamp(jetzt, TZ).isoformat(), "spiele_s24": len(spiele), "signale": [],
           "raus": [], "nicht_bei_bl": [], "gruppen_test": None}
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

    treffer = []
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
                           "x12": x12, "hinweis": hinweis, "key": k["key"],
                           "serie": [f"{f['team']}: {f['text']}" for f in k["fakten"]],
                           "h2h": [f["text"] for f in k["h2h"]]}
                if ok:
                    treffer.append(eintrag)
                else:
                    log["raus"].append(eintrag)
    log["signale"] = treffer
    print(f"Signale nach BetLabel und Regeln: {len(treffer)}, raus: {len(log['raus'])}, "
          f"nicht bei BL: {len(log['nicht_bei_bl'])}", flush=True)

    if treffer:
        nach_spiel = {}
        for t in sorted(treffer, key=lambda t: (t["anstoss"], t["spiel"])):
            nach_spiel.setdefault((t["anstoss"], t["spiel"]), []).append(t)
        bloecke = []
        for (ko, spiel), ts in nach_spiel.items():
            x12 = ts[0]["x12"]
            kopf = (f"<b>{datetime.fromtimestamp(ko, TZ):%a %H:%M}</b> {htmlmod.escape(spiel)}\n"
                    f"<i>{htmlmod.escape(ts[0]['liga'] or '')}</i>"
                    + (f" · 1X2 {_q(x12[0])} / {_q(x12[1])} / {_q(x12[2])}" if x12 else ""))
            zeilen = []
            for t in ts:
                z = f"• {htmlmod.escape(t['markt'])} @ <b>{_q(t['quote'])}</b>"
                if t["serie"]:
                    z += f"\n   {htmlmod.escape(t['serie'][0])}"
                if t["hinweis"]:
                    z += f"\n   ⚠️ {htmlmod.escape(t['hinweis'])}"
                zeilen.append(z)
            bloecke.append(kopf + "\n" + "\n".join(zeilen))
        kopfzeile = f"🔎 <b>Neue Serien</b> (bis {datetime.fromtimestamp(jetzt + FENSTER_H * 3600, TZ):%H:%M})\n\n"
        teil, ok_alle = kopfzeile, True
        for b in bloecke:
            if len(teil) + len(b) > 3800:
                ok_alle &= tg(teil.rstrip())
                teil = ""
            teil += b + "\n\n"
        ok_alle &= tg(teil.rstrip())
        if ok_alle:
            for t in treffer:
                gesendet[t["key"]] = jetzt
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
