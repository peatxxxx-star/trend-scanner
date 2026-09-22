#!/usr/bin/env python3
"""Handball-Erkundung — Schritt 1: WAS liefert die Datenquelle überhaupt?

Eigenes Skript, bewusst getrennt vom Fußball-Scanner: scan.py läuft und soll
nicht durch ein Experiment destabilisiert werden.

Anlass (17.09., Lucio): seit dem Zuschnitt auf Über-Märkte und drei Ligen für
Einwürfe/Abstöße sind es unter der Woche 7 bis 10 Signale statt 25. Handball
als Lückenfüller: spielt Donnerstag und mitten in der Woche, Tore-Totals sind
die eine dominante Zählgröße, und Handballmannschaften sind in ihrem Tempo
sehr berechenbar.

Dieses Skript entscheidet NICHTS. Es beantwortet vier Fragen:
  1. Welche Handball-Ligen liefert die API, und wie viele Spiele je Woche?
  2. Kommt je Spiel ein Endstand — und ein Halbzeitstand?
  3. Gibt es überhaupt einen Statistikblock (Siebenmeter, Zeitstrafen, ...)?
  4. Wie sehen Mittelwert, Streuung und Grundraten der Tore-Totals aus —
     je Liga, damit wir wissen, wo sinnvolle Linien liegen.

Erst wenn das steht, reden wir über eine Serienregel.

Schritt 2 (17.09., derselbe Lauf): der Zugang ist ein Eintages-Test für 1 $,
also holt der Lauf gleich die Historien nach — für jedes Team aus jeder Liga
mit mindestens 20 Spielen im Fenster die letzten 50 beendeten Spiele, samt
Endstand und Halbzeitstand. Eine Anfrage je Team. Ergebnis liegt danach im
Repo und reicht für einen kompletten Offline-Backtest, ohne dass das
Monatspaket gekauft sein muss.

Schritt 3 (17.09., Lucio: "nur Märkte, die sich wirklich qualifizieren"):
    python3 handball.py scan
Meldet für die Spiele der nächsten 3 Tage die Tore-Signale — NUR ÜBER,
Lucios Regel vom 17.09. gilt hier genauso (eine Unter-Wette stirbt 60 Minuten
lang vor den Augen). Ganze Spielzeit und 1. Halbzeit. Serienregel und Rechenweg sind EXAKT die
des Fußball-Scanners (importiert aus scan.py): beide Teams im Trend,
mindestens ein Anker, gewichtete Historie + Normalmodell, Schrumpfung zur
Grundrate, Ampel. Keine Leiter — nur die strengste Linie je Richtung, die
sich qualifiziert. Kalibrierung: noch keine (kein echter Preisvergleich).

Aufruf:  python3 handball.py [wochen]      (Vorgabe: 4)
Umgebung: BETSAPI_TOKEN, optional TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
"""
import json
import math
import os
import re
import statistics as st
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

API = "https://api.b365api.com"
TOKEN = os.environ.get("BETSAPI_TOKEN", "")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
# Sportarten laut BetsAPI-Glossar. 17.09. (Lucio): "wenn wir die API schon
# gekauft haben, können wir sie bis morgen auch vollwertig nutzen" — deshalb
# ist das Skript sportartfähig: SPORT=basketball python3 handball.py
# "abschnitt" = welche Perioden den ersten Spielabschnitt bilden (Halbzeit,
# 1. Drittel, 1.+2. Viertel = Halbzeit, 1. Satz), "punkte" = ob das Ergebnis
# aus den Satzständen summiert werden muss (Volleyball: "ss" sind Sätze).
SPORTS = {
    "handball":   {"id": 78, "name": "Handball",   "abschnitt": ["1"],      "punkte": False,
                   "abschnitt_name": "HZ"},
    # Basketball-Falle (17.09. beim Auswerten gefunden): die Abschnitte der API
    # sind 1 = Q1, 2 = Q2, 3 = HALBZEITSTAND (Q1+Q2), 4 = Q3, 5 = Q4, danach OT.
    # "perioden" speichert das so roh; wer Viertel summiert, muss Schlüssel 3
    # überspringen (Q4 = perioden[4], reguläre Punkte = [0]+[1]+[3]+[4]).
    "basketball": {"id": 18, "name": "Basketball", "abschnitt": ["1", "2"], "punkte": False,
                   "abschnitt_name": "HZ"},
    "eishockey":  {"id": 17, "name": "Eishockey",  "abschnitt": ["1"],      "punkte": False,
                   "abschnitt_name": "1.Dr"},
    "volleyball": {"id": 91, "name": "Volleyball", "abschnitt": ["1"],      "punkte": True,
                   "abschnitt_name": "Satz1"},
}
SPORT_KEY = os.environ.get("SPORT", "handball").strip().lower()
if SPORT_KEY not in SPORTS:
    sys.exit(f"unbekannte Sportart '{SPORT_KEY}' — bekannt: {', '.join(SPORTS)}")
SPORT = SPORTS[SPORT_KEY]
SPORT_HANDBALL = SPORT["id"]     # Name aus historischen Gründen; ist die aktive Sportart
WORKERS = 48                 # 17.09. (Lucio): "zügig" — die API drosselt nicht
                             # pro Sekunde, nur pro Stunde; also breit parallel
# 17.09.: Der Zugang läuft über den "Everything API One Day Trial" (2 $) —
# der hat nur 1.800 Anfragen je Stunde, nicht 3.600. Ob sich Test und
# Fußball-Paket das Limit teilen, wissen wir nicht; deshalb vorsichtig.
# Reicht es nicht in einer Stunde, sichert der Lauf, was da ist, und ein
# zweiter Lauf eine Stunde später holt den Rest (der Test gilt einen Tag).
HOURLY_BUDGET = int(os.environ.get("HANDBALL_BUDGET", "1700"))
OUT = Path("runs")

_requests = 0
_lock = Lock()


class BudgetExhausted(Exception):
    pass


def api_get(path: str, **params) -> dict:
    """Eine API-Abfrage mit Wiederholungen. Bewusst dieselbe Mechanik wie im
    Fußball-Scanner, inklusive HTTP 429: das Stundenlimit gilt über ALLE Läufe
    zusammen, der eigene Zähler kann das nicht wissen."""
    global _requests
    with _lock:
        if _requests >= HOURLY_BUDGET:
            raise BudgetExhausted()
    params["token"] = params.pop("_token", None) or TOKEN
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    last = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                data = json.loads(r.read().decode("utf-8"))
            with _lock:
                _requests += 1
            if data.get("success") != 1:
                raise RuntimeError(f"API-Fehler {data.get('error')} bei {path}")
            return data
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # Stundenlimit voll. EINMAL kurz warten (vielleicht war es nur
                # der Fußball-Scanner in derselben Minute), danach nicht ewig
                # hängen, sondern sauber abbrechen und sichern, was da ist.
                if attempt == 0:
                    print("HTTP 429 – Stundenlimit, warte 60 s", flush=True)
                    time.sleep(60)
                    last = exc
                    continue
                with _lock:
                    _requests = HOURLY_BUDGET      # alle wartenden Aufrufe scheitern sofort
                raise BudgetExhausted()
            last = exc
            if exc.code in (401, 403, 404):
                raise                       # kein Paket / falscher Pfad — Wiederholen bringt nichts
            if attempt == 4:
                raise
            time.sleep(min(3 * 2 ** attempt, 30))
        except Exception as exc:
            last = exc
            if attempt == 4:
                raise
            time.sleep(min(3 * 2 ** attempt, 30))
    raise last if last else RuntimeError("unreachable")


# 17.09.: Basketball-Lauf bestand zu zwei Dritteln aus "Ebasketball" —
# Videospiel-Simulationen (4x5 Minuten), keine Mannschaften. Dazu 3x3 ohne
# Halbzeit. Beides fliegt raus, bevor es in eine Historie wandert.
JUNK = ("ebasketball", "esoccer", "ehockey", "evolleyball", "esports", "e-sports", "cyber", "3x3", "simulated", "srl", "virtual")


def is_junk(ev) -> bool:
    name = ((ev.get("league") or {}).get("name") or "").lower()
    return any(k in name for k in JUNK)


def ended_day(day: str) -> list:
    """Alle beendeten Spiele der Sportart an einem Tag (Format YYYYMMDD)."""
    out, page = [], 1
    while True:
        d = api_get("/v3/events/ended", sport_id=SPORT_HANDBALL, day=day, page=page)
        res = d.get("results") or []
        out += [e for e in res if not is_junk(e)]
        pager = d.get("pager") or {}
        if len(out) >= int(pager.get("total", 0)) or not res or page >= 40:
            break
        page += 1
    return out


def split_score(ss):
    """'28-26' -> (28, 26); None bei allem, was nicht passt."""
    if not ss or "-" not in str(ss):
        return None
    try:
        a, b = str(ss).split("-", 1)
        return int(a.strip()), int(b.strip())
    except ValueError:
        return None


def _period(sc, key):
    if not isinstance(sc, dict):
        return None
    p = sc.get(key)
    if p is None and key.isdigit():
        p = sc.get(int(key))
    if isinstance(p, dict) and p.get("home") is not None:
        try:
            return int(p["home"]), int(p["away"])
        except (TypeError, ValueError):
            return None
    return None


def final_score(ev):
    """Endstand als (heim, gast). Volleyball: Punkte über alle Sätze summiert,
    weil "ss" dort nur die Sätze zählt."""
    if SPORT["punkte"]:
        sc = ev.get("scores") or {}
        h = a = n = 0
        for k in ("1", "2", "3", "4", "5"):
            p = _period(sc, k)
            if p:
                h += p[0]; a += p[1]; n += 1
        return (h, a) if n >= 3 else None       # unter 3 Sätzen ist es kein Ergebnis
    return split_score(ev.get("ss"))


def perioden(ev):
    """Alle Spielabschnitte als Liste [[heim, gast], ...] — 17.09. (Lucio):
    "bevor wir abbrechen noch 2. und 3. Drittel". Leer, wenn keine da sind."""
    sc = ev.get("scores") or {}
    out = []
    for k in ("1", "2", "3", "4", "5", "6", "7"):
        p = _period(sc, k)
        if not p:
            break
        out.append([p[0], p[1]])
    return out


def half_time(ev):
    """Erster Spielabschnitt (Halbzeit / 1. Drittel / 1. Satz) als (heim, gast)."""
    sc = ev.get("scores") or {}
    h = a = 0
    for k in SPORT["abschnitt"]:
        p = _period(sc, k)
        if not p:
            return None
        h += p[0]; a += p[1]
    return h, a


def team_history(team_id: str, depth: int = 50) -> list:
    """Die letzten `depth` beendeten Spiele eines Teams, kompakt. Der Endpunkt
    liefert Endstand und Halbzeitstand direkt mit — keine zweite Abfrage nötig."""
    out, page = [], 1
    while len(out) < depth and page <= 2:
        d = api_get("/v3/events/ended", sport_id=SPORT_HANDBALL, team_id=team_id,
                    per_page=50, page=page)
        res = d.get("results") or []
        out += [e for e in res if not is_junk(e)]
        total = int((d.get("pager") or {}).get("total", 0))
        if page * 50 >= total or not res:
            break
        page += 1
    slim = []
    for ev in out[:depth]:
        sc = final_score(ev)
        ht = half_time(ev)
        home, away = ev.get("home") or {}, ev.get("away") or {}
        slim.append({"id": ev.get("id"), "time": ev.get("time"),
                     "liga": (ev.get("league") or {}).get("name"),
                     "h": str(home.get("id")) == str(team_id),
                     "heim": home.get("name"), "gast": away.get("name"),
                     "heim_id": home.get("id"), "gast_id": away.get("id"),
                     "tore": list(sc) if sc else None,
                     "hz": list(ht) if ht else None,
                     "perioden": perioden(ev)})
    return slim


def wochen_aus_argv() -> int:
    """Das Workflow-Feld heißt 'datum' und wird hier als WOCHENZAHL benutzt.
    Steht etwas anderes drin (z. B. ein Datum), nicht abstürzen, sondern die
    Vorgabe nehmen und es sagen."""
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        return 4
    roh = sys.argv[1].strip()
    try:
        w = int(roh)
    except ValueError:
        print(f"'{roh}' ist keine Wochenzahl — nehme 4 Wochen.", flush=True)
        return 4
    if not 1 <= w <= 26:
        print(f"{w} Wochen sind außerhalb von 1–26 — nehme 4.", flush=True)
        return 4
    return w


# ---------------------------------------------------------------------------
# Schritt 3: SCAN — Signale für die nächsten Tage, Rechenweg aus scan.py
# ---------------------------------------------------------------------------
SCAN_TAGE = 3
LINIEN = {"goals": [x + 0.5 for x in range(43, 72, 2)],      # 43,5 … 71,5
          "ht_goals": [x + 0.5 for x in range(19, 37)]}       # 19,5 … 36,5
MARKT_NAME = {"goals": "Tore", "ht_goals": "1. HZ Tore"}
RICHTUNGEN = ("über",)       # 17.09. (Lucio): keine Unter-Märkte — auch hier nicht
MIN_LIGA_SPIELE = 150        # Ligen mit weniger Spielen in der Historie: nicht melden


def upcoming(day: str) -> list:
    out, page = [], 1
    while True:
        d = api_get("/v3/events/upcoming", sport_id=SPORT_HANDBALL, day=day, page=page)
        res = d.get("results") or []
        out += res
        if len(out) >= int((d.get("pager") or {}).get("total", 0)) or not res or page >= 20:
            break
        page += 1
    return out


def inplay() -> list:
    """Gerade laufende Spiele der Sportart — 17.09. (Lucio): "ich möchte, dass
    auch heute bereits stattfindende Spiele angezeigt werden". Der Endpunkt
    /v3/events/upcoming kennt nur noch nicht angepfiffene Spiele."""
    out, page = [], 1
    while True:
        d = api_get("/v3/events/inplay", sport_id=SPORT_HANDBALL, page=page)
        res = d.get("results") or []
        out += res
        if len(out) >= int((d.get("pager") or {}).get("total", 0)) or not res or page >= 10:
            break
        page += 1
    for m in out:
        m["_live"] = True
    return out


def as_scan_history(events: list) -> list:
    """Historie im Format, das scan.py erwartet: [{"stats": {...}, "is_home": bool}]."""
    out = []
    for e in events:
        if not e.get("tore"):
            continue
        stats = {"goals": e["tore"]}
        if e.get("hz"):
            stats["ht_goals"] = e["hz"]
        out.append({"stats": stats, "is_home": bool(e.get("h")), "label": e.get("liga") or ""})
    return out


def league_base_rates(hist: dict, liga: str) -> dict:
    """Grundraten je Linie NUR aus Spielen dieser Liga — Handball-Ligen liegen
    im Schnitt zwischen 44 und 67 Toren, ein globaler Wert wäre Unsinn."""
    seen, tot, ht = set(), [], []
    for t in hist.values():
        for e in t["events"]:
            if e.get("liga") != liga or e["id"] in seen or not e.get("tore"):
                continue
            seen.add(e["id"]); tot.append(e["tore"][0] + e["tore"][1])
            if e.get("hz"):
                ht.append(e["hz"][0] + e["hz"][1])
    rates = {}
    for metric, werte in (("goals", tot), ("ht_goals", ht)):
        for L in LINIEN[metric]:
            over = sum(1 for x in werte if x > L) / len(werte) if werte else 0.5
            rates[(metric, L, "über")] = over
            rates[(metric, L, "unter")] = 1 - over
    return rates, len(tot)


def bewerte(scan, hh, ha, metric, line, direction):
    """Faire Quote und Ampel — dieselben Bausteine wie assess_signal in scan.py,
    ohne Schiedsrichter, ohne bet365, ohne Kalibrierung."""
    fair = scan.fair_odds(hh, ha, metric, line, direction)
    if not fair:
        return None
    p_emp = 1 / fair
    _, _, avg_h = scan.weighted_stats(hh, metric, line, direction, "home")
    _, _, avg_a = scan.weighted_stats(ha, metric, line, direction, "away")
    if avg_h is None:
        _, _, avg_h = scan.weighted_stats(hh, metric, line, direction)
    if avg_a is None:
        _, _, avg_a = scan.weighted_stats(ha, metric, line, direction)
    if avg_h is None or avg_a is None:
        return None
    expect = (avg_h + avg_a) / 2
    mu = scan.matchup_expectation(hh, ha, metric)
    if mu:
        expect = (expect + mu[0]) / 2
    sd = scan.pooled_sd(hh, ha, metric)
    p_mod = scan.model_prob(expect, sd, line, direction)
    p = 0.5 * p_emp + 0.5 * p_mod
    buffer = expect - line if direction == "über" else line - expect
    agree = abs(p_emp - p_mod)
    if p >= scan.GREEN_MIN_P and agree <= scan.AGREE_OK and buffer >= 0:
        light = "🟢"
    elif p < scan.RED_MAX_P or buffer < -2 or agree > 0.25:
        light = "🔴"
    else:
        light = "🟡"
    return {"p": p, "fair": round(1 / p, 2), "p_emp": p_emp, "p_mod": p_mod,
            "expect": round(expect, 1), "sd": round(sd, 2), "buffer": round(buffer, 1),
            "light": light}


def scan_modus():
    import importlib.util
    spec = importlib.util.spec_from_file_location("scan", Path(__file__).parent / "scan.py")
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)

    hfiles = sorted(OUT.glob(f"{SPORT_KEY}_historie_*.json"))
    if not hfiles:
        sys.exit("keine Historie gefunden — erst den Abdeckungslauf machen")
    hist = json.loads(hfiles[-1].read_text(encoding="utf-8"))
    print(f"Historie: {hfiles[-1].name}, {len(hist)} Teams", flush=True)

    # Ligen mit genug Substanz
    liga_n = Counter()
    seen = set()
    for t in hist.values():
        for e in t["events"]:
            if e["id"] not in seen and e.get("tore"):
                seen.add(e["id"]); liga_n[e.get("liga")] += 1
    ok_ligen = {L for L, n in liga_n.items() if n >= MIN_LIGA_SPIELE}
    print(f"{len(ok_ligen)} Ligen mit >= {MIN_LIGA_SPIELE} Spielen", flush=True)

    heute = datetime.now(timezone.utc).date()
    tage = [(heute + timedelta(days=i)).strftime("%Y%m%d") for i in range(SCAN_TAGE)]
    spiele = []
    for d in tage:
        try:
            spiele += upcoming(d)
        except Exception as exc:
            print(f"  upcoming {d}: {exc}", flush=True)
    spiele = [m for m in spiele if ((m.get("league") or {}).get("name") in ok_ligen)]
    print(f"{len(spiele)} anstehende Spiele in den Ziel-Ligen", flush=True)

    # Historien der beteiligten Teams frisch holen (1 Anfrage je Team)
    ids = {}
    for m in spiele:
        for side in ("home", "away"):
            t = m.get(side) or {}
            if t.get("id"):
                ids[str(t["id"])] = t.get("name") or "?"
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(team_history, tid): tid for tid in ids}
        for f in as_completed(futs):
            tid = futs[f]
            try:
                hist[tid] = {"name": ids[tid], "events": f.result()}
            except Exception as exc:
                print(f"  Team {ids[tid]}: {exc}", flush=True)
    print(f"Historien aktualisiert ({_requests} Anfragen)", flush=True)

    rates_cache = {}
    treffer = []
    for m in spiele:
        home, away = m.get("home") or {}, m.get("away") or {}
        hid, aid = str(home.get("id")), str(away.get("id"))
        if hid not in hist or aid not in hist:
            continue
        liga = (m.get("league") or {}).get("name") or "?"
        if liga not in rates_cache:
            rates_cache[liga] = league_base_rates(hist, liga)
        scan._base_rates.clear()
        scan._base_rates.update(rates_cache[liga][0])
        hh = as_scan_history(hist[hid]["events"])
        ha = as_scan_history(hist[aid]["events"])
        if len(hh) < scan.MIN_VALID_MATCHES or len(ha) < scan.MIN_VALID_MATCHES:
            continue
        sigs = []
        for metric, lines in LINIEN.items():
            for direction in RICHTUNGEN:
                order = sorted(lines, reverse=(direction == "über"))
                for L in order:              # strengste Linie zuerst, EIN Signal je Richtung
                    a_h, o_h, v_h = scan.team_qualifies(hh, metric, L, direction, "home")
                    a_a, o_a, v_a = scan.team_qualifies(ha, metric, L, direction, "away")
                    if (a_h or o_h) and (a_a or o_a) and (a_h or a_a):
                        b = bewerte(scan, hh, ha, metric, L, direction)
                        if b:
                            b.update({"metric": metric, "line": L, "direction": direction,
                                      "home_series": a_h or o_h, "away_series": a_a or o_a,
                                      "home_is_anchor": bool(a_h), "away_is_anchor": bool(a_a),
                                      "valid": (v_h, v_a)})
                            sigs.append(b)
                        break
        if sigs:
            treffer.append((m, liga, sigs))

    # --- Nachricht: Zeit zuerst, gleiche Zeit nach Liga (wie im Fußball) --------
    def ts(m):
        return int(m.get("time") or 0)
    treffer.sort(key=lambda x: (ts(x[0]), x[1].lower(), (x[0].get("home") or {}).get("name", "")))
    berlin = timezone(timedelta(hours=2))
    WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    lines_out = ["🤾 <b>HANDBALL-SCAN</b> · nächste 3 Tage · <i>Test, noch ohne Kalibrierung</i>", ""]
    n_sig = 0
    for m, liga, sigs in treffer:
        t = datetime.fromtimestamp(ts(m), berlin)
        home = (m.get("home") or {}).get("name", "?"); away = (m.get("away") or {}).get("name", "?")
        block = [f"🤾 <b>{scan.esc(home)} – {scan.esc(away)}</b>",
                 f"🕒 {WD[t.weekday()]} {t:%H:%M} · {scan.esc(liga)}"]
        for sg in sorted(sigs, key=lambda x: (x["metric"], x["direction"])):
            if sg["light"] == "🔴":
                continue
            n_sig += 1
            mark = "✅" if sg["light"] == "🟢" else "⚪"
            block.append("")
            block.append(f"{mark} <b>{MARKT_NAME[sg['metric']]} {sg['direction']} {sg['line']}</b>"
                         f" · Fair {sg['fair']:.2f} · <i>Quote selbst prüfen</i>")
            block.append(f"   {scan.esc(home)} {scan.fmt_series(sg['home_series'], sg['home_is_anchor'])}"
                         f" · {scan.esc(away)} {scan.fmt_series(sg['away_series'], sg['away_is_anchor'])}")
            block.append(f"   🎯 Erwartung {sg['expect']} · Puffer {sg['buffer']:+.1f}"
                         f" · 📊 {sg['valid'][0]}/{sg['valid'][1]} Spiele")
        if len(block) > 2:
            lines_out += block + [""]
    if n_sig == 0:
        lines_out.append("keine Signale in den nächsten 3 Tagen")
    text = "\n".join(lines_out)
    print("\n" + text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    OUT.mkdir(exist_ok=True)
    (OUT / f"handball_scan_{heute:%Y-%m-%d}.txt").write_text(text, encoding="utf-8")
    print(f"\n{n_sig} Signale in {len(treffer)} Spielen · {_requests} Anfragen")
    if TG_TOKEN and TG_CHAT:
        for stueck in scan.split_message(text):
            scan.send_telegram(stueck)


# ---------------------------------------------------------------------------
# STATS — Statistikblock je Spiel nachladen (17.09.)
# Die Team-Historie liefert nur Spielstände. Nebenmärkte (Schüsse, Strafen,
# Paraden …) stehen im Statistikblock der Einzelspiel-Abfrage, die zehn Spiele
# auf einmal nimmt. Für die Spiele der großen Ligen aus der Historie: bei
# 3.000 Spielen 300 Anfragen. Aufruf: SPORT=eishockey python3 handball.py stats
# Ergebnis: runs/<sport>_stats_<datum>.json  {spiel_id: {feld: [heim, gast]}}
# ---------------------------------------------------------------------------
STATS_MIN_LIGA = int(os.environ.get("STATS_MIN_LIGA", "150"))   # Spiele je Liga in der Historie
STATS_MAX = int(os.environ.get("STATS_MAX", "12000"))            # Obergrenze Spiele je Lauf


def _num_pair(v):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        try:
            return [int(float(v[0])), int(float(v[1]))]
        except (TypeError, ValueError):
            return None
    return None


def stats_modus():
    hfiles = sorted(OUT.glob(f"{SPORT_KEY}_historie_*.json"))
    if not hfiles:
        sys.exit("keine Historie gefunden — erst den Abdeckungslauf machen")
    hist = json.loads(hfiles[-1].read_text(encoding="utf-8"))
    heute = datetime.now(timezone.utc).date()
    spfad = OUT / f"{SPORT_KEY}_stats_{heute:%Y-%m-%d}.json"
    stats = {}
    if spfad.exists():
        try:
            stats = json.loads(spfad.read_text(encoding="utf-8"))
            print(f"Wiederaufnahme: {len(stats)} Spiele schon mit Statistik", flush=True)
        except Exception:
            stats = {}
    # Spiele der großen Ligen, neueste zuerst
    liga_n = Counter(); spiele = {}
    for t in hist.values():
        for e in t["events"]:
            if e["id"] not in spiele and e.get("tore"):
                spiele[e["id"]] = e; liga_n[e.get("liga")] += 1
    ok_ligen = {L for L, n in liga_n.items() if n >= STATS_MIN_LIGA}
    todo = [eid for eid, e in sorted(spiele.items(), key=lambda x: -int(x[1].get("time") or 0))
            if e.get("liga") in ok_ligen and eid not in stats][:STATS_MAX]
    print(f"{len(spiele)} Spiele in der Historie · {len(ok_ligen)} Ligen mit >= {STATS_MIN_LIGA} · "
          f"{len(todo)} Spiele zu laden ({(len(todo) + 9) // 10} Anfragen)", flush=True)
    chunks = [todo[i:i + 10] for i in range(0, len(todo), 10)]
    felder = Counter(); knapp = 0
    def _view(chunk):
        d = api_get("/v1/event/view", event_id=",".join(chunk))
        out = {}
        for ev in d.get("results") or []:
            st_ = ev.get("stats") or {}
            slim = {}
            for k, v in st_.items():
                p = _num_pair(v)
                if p is not None:
                    slim[k] = p
            out[str(ev.get("id"))] = slim
        return out
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(_view, c) for c in chunks]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                got = f.result()
                stats.update(got)
                for slim in got.values():
                    felder.update(slim.keys())
            except BudgetExhausted:
                knapp += 1
            except Exception as exc:
                print(f"  Block: {exc}", flush=True)
            if i % 50 == 0:
                print(f"  ... {i}/{len(chunks)} Blöcke, {_requests} Anfragen", flush=True)
                spfad.write_text(json.dumps(stats), encoding="utf-8")
    spfad.write_text(json.dumps(stats), encoding="utf-8")
    if knapp:
        print(f"Stundenlimit: {knapp} Blöcke fehlen — nächste Stunde nochmal starten", flush=True)
    print(f"gespeichert: {spfad} — {len(stats)} Spiele mit Statistik, {_requests} Anfragen")
    print("Felder (Anzahl Spiele, in denen sie vorkommen):")
    for k, c in felder.most_common(30):
        print(f"   {k}: {c}")
    if TG_TOKEN and TG_CHAT:
        txt = (f"<b>{SPORT['name'].upper()} — Statistiken</b>\n{len(stats)} Spiele · "
               + " · ".join(f"{k} {c}" for k, c in felder.most_common(12)))
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                data=urllib.parse.urlencode({"chat_id": TG_CHAT, "text": txt,
                                             "parse_mode": "HTML"}).encode(), method="POST")
            urllib.request.urlopen(req, timeout=30).read()
        except Exception as exc:
            print(f"Telegram: {exc}")


# ---------------------------------------------------------------------------
# LIGA — ganze Ligen am Stück (17.09., für Basketball)
# Die Tag-für-Tag-Abfrage erstickt bei 26 Wochen an tausenden Ebasketball-
# Spielen (werden zwar verworfen, kosten aber Seiten). Stattdessen: Ligenliste
# holen, Zielligen per Schlüsselwort wählen, je Liga die beendeten Spiele
# (neueste zuerst) bis zum Stichtag. Die Saison einer Liga IST die Historie
# aller ihrer Teams — daraus wird dieselbe historie-Datei gebaut wie sonst,
# damit Backtest und stats-Modus unverändert laufen.
# Aufruf: SPORT=basketball python3 handball.py liga
# ---------------------------------------------------------------------------
LIGA_KEYS = {
    "basketball": ["nba", "euroleague", "eurocup", "acb", "bbl", "lega a", "pro a",
                   "vtb", "champions league", "bsl", "greece a1", "adriatic", "aba league",
                   "australia nbl", "b league", "b.league", "china cba", "kbl", "pba",
                   "lkl", "argentina lnb", "nbb", "israel super league", "energa",
                   "serbia kls", "bsn", "lnbp", "fiba europe cup", "basketligaen",
                   "bnxt", "lnb pro", "liga endesa", "betclic elite"],
    "handball":   ["bundesliga", "handboldligaen", "asobal", "eliteserien", "starligue",
                   "handbollsligan", "champions league", "european league"],
    "eishockey":  ["nhl", "khl", "del", "shl", "liiga", "extraliga", "nla", "ice hockey league"],
    "volleyball": ["superlega", "plusliga", "bundesliga", "super league", "champions league"],
}
LIGA_TAGE = int(os.environ.get("LIGA_TAGE", "400"))       # Stichtag: so weit zurück
LIGA_SEITEN = int(os.environ.get("LIGA_SEITEN", "30"))    # je Liga höchstens (à 50 Spiele)
AUSSCHLUSS = ("u16", "u17", "u18", "u19", "u20", "u21", "u23", "youth", "junior",
              "reserve", "college", "ncaa", "summer league", "preseason", "pre-season",
              "friendl", "all-star", "all star")


def alle_ligen():
    """Alle Ligen der Sportart über /v3/league (Blättern über max_id)."""
    out, max_id, guard = [], None, 0
    while guard < 80:
        guard += 1
        params = {"sport_id": SPORT_HANDBALL}
        if max_id:
            params["max_id"] = max_id
        d = api_get("/v3/league", **params)
        res = d.get("results") or []
        out += res
        mn = (d.get("pager") or {}).get("min_id")
        if not res or not mn or int(mn) <= 0:
            break
        max_id = int(mn)
    return out


def liga_spiele(league_id, cutoff_ts):
    """Beendete Spiele einer Liga, neueste zuerst, bis zum Stichtag."""
    out, page = [], 1
    while page <= LIGA_SEITEN:
        d = api_get("/v3/events/ended", sport_id=SPORT_HANDBALL, league_id=league_id,
                    per_page=50, page=page)
        res = d.get("results") or []
        if not res:
            break
        out += res
        if int(res[-1].get("time") or 0) < cutoff_ts:
            break
        total = int((d.get("pager") or {}).get("total", 0))
        if page * 50 >= total:
            break
        page += 1
    return [e for e in out if int(e.get("time") or 0) >= cutoff_ts and not is_junk(e)]


def liga_modus():
    heute = datetime.now(timezone.utc).date()
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=LIGA_TAGE)).timestamp())
    keys = [k.strip().lower() for k in os.environ.get("LIGEN", "").split(",") if k.strip()] \
        or LIGA_KEYS.get(SPORT_KEY, [])
    ligen = alle_ligen()
    print(f"{len(ligen)} Ligen für {SPORT['name']} gelistet ({_requests} Anfragen)", flush=True)
    ziel = []
    for lg in ligen:
        name = (lg.get("name") or "").lower()
        if any(k in name for k in keys) and not any(a in name for a in AUSSCHLUSS) \
                and not is_junk({"league": lg}):
            ziel.append(lg)
    print(f"{len(ziel)} Zielligen:", flush=True)
    for lg in ziel:
        print(f"   {lg.get('id')}  {lg.get('name')}  ({lg.get('cc')})", flush=True)

    spiele = {}
    with ThreadPoolExecutor(max_workers=min(WORKERS, 12)) as pool:
        futs = {pool.submit(liga_spiele, lg["id"], cutoff): lg for lg in ziel}
        for f in as_completed(futs):
            lg = futs[f]
            try:
                res = f.result()
            except BudgetExhausted:
                print("Stundenlimit — Ligen unvollständig", flush=True)
                continue
            except Exception as exc:
                print(f"  {lg.get('name')}: {exc}", flush=True)
                continue
            for ev in res:
                spiele[str(ev.get("id"))] = ev
            print(f"  {lg.get('name'):40s} {len(res):5d} Spiele", flush=True)
    print(f"{len(spiele)} Spiele aus {len(ziel)} Ligen ({_requests} Anfragen)", flush=True)

    # historie-Datei aus den Ligaspielen bauen (Team -> Spiele, neueste zuerst)
    hist = {}
    for ev in spiele.values():
        sc = final_score(ev); ht = half_time(ev)
        home, away = ev.get("home") or {}, ev.get("away") or {}
        slim = {"id": ev.get("id"), "time": ev.get("time"),
                "liga": (ev.get("league") or {}).get("name"),
                "heim": home.get("name"), "gast": away.get("name"),
                "heim_id": home.get("id"), "gast_id": away.get("id"),
                "tore": list(sc) if sc else None, "hz": list(ht) if ht else None,
                "perioden": perioden(ev)}
        for tid, name in ((str(home.get("id")), home.get("name")),
                          (str(away.get("id")), away.get("name"))):
            if tid == "None":
                continue
            hist.setdefault(tid, {"name": name, "events": []})
            hist[tid]["events"].append(dict(slim, h=(tid == str(home.get("id")))))
    for t in hist.values():
        t["events"].sort(key=lambda e: -int(e.get("time") or 0))
    OUT.mkdir(exist_ok=True)
    hpfad = OUT / f"{SPORT_KEY}_historie_{heute:%Y-%m-%d}.json"
    hpfad.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    mit_p = sum(1 for e in spiele.values() if len(perioden(e)) >= 2)
    print(f"gespeichert: {hpfad} — {len(hist)} Teams, {len(spiele)} Spiele, "
          f"{mit_p} mit Abschnittsständen, {_requests} Anfragen")
    if TG_TOKEN and TG_CHAT:
        txt = (f"<b>{SPORT['name'].upper()} — Ligen</b>\n{len(ziel)} Ligen · {len(spiele)} Spiele · "
               f"{len(hist)} Teams · {_requests} Anfragen\n"
               + "\n".join(f"{lg.get('name')}" for lg in ziel[:40]))
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                data=urllib.parse.urlencode({"chat_id": TG_CHAT, "text": txt,
                                             "parse_mode": "HTML"}).encode(), method="POST")
            urllib.request.urlopen(req, timeout=30).read()
        except Exception as exc:
            print(f"Telegram: {exc}")
    # direkt weiter mit den Statistikblöcken, solange Budget da ist
    stats_modus()


# ---------------------------------------------------------------------------
# EISHOCKEY-SCAN (17.09.) — "Heim über 2,5 eigene Tore" (reguläre Zeit, ohne OT)
#
# Lucios Auftrag: "du drehst solange, bis du was gebaut hast mit min. 75 %".
# Ergebnis der Suche über 59 Märkte × 7 Regeln auf 589 Teams (eine Saison):
# Tor-Serien des Heimteams selbst sagen nichts (Rückkehr zum Mittel), die
# LÖCHRIGKEIT DES GASTES sagt alles — und eine schwache Abwehr ist auswärts
# noch schwächer (Spiegelregel "Gast über 2,5" bringt gegenüber dem
# Matchup-Modell genau null, die Heim-Fassung +7 Punkte).
#
# Regel (alle Werte aus den letzten 15 Spielen, nur reguläre Zeit = 3 Drittel):
#   Heim schießt selbst Ø >= 2,6                       (darunter nur 70 %)
#   und  Stufe A: Gast kassiert Ø >= 4,5
#   oder Stufe B: Gast kassiert Ø >= 4,0 ODER 9 der letzten 10 Spiele 3+
#                 Gegentore, dann aber Heim Ø >= 3,2   (sonst nur 70 %)
# Backtest: 575 Signale, 84,9 % (Zeit-Split 86,4 / 83,3), Topligen 57 → 94,7 %;
# Poisson-Matchup-Modell sagt 77,7 %, reiner Team-Schnitt 69,2 %.
# In der Saison rund 19 Signale je Woche, davon ~2 in Topligen — der Rest ist
# Kazakhstan MHL, Sweden U20, British Elite League, NLB, Norway, Slovakia 1.
# Testspiele fliegen raus (69,7 %), sonst keine Liga-Feinjustierung.
# Faire Quote = 1 / (Trefferquote der Stufe × 0,97 Sicherheitsabschlag, weil
# die Regel auf denselben Daten gefunden wurde). Die Trefferquoten werden
# bei jedem Lauf frisch aus der Historie-Datei gerechnet (kein API-Aufwand).
# Läuft seit 17.09. abends als Zusatzsignal im Serien-Scan (serien_scan).
# ---------------------------------------------------------------------------
HOCKEY_N = 15                # Spiele je Team für die Schnitte
HOCKEY_MIN_HEIM = 2.6        # Heim schießt selbst mindestens Ø 2,6
HOCKEY_GAST_A = 4.5          # Stufe A: Gast kassiert Ø >= 4,5
HOCKEY_GAST_B = 4.0          # Stufe B: Gast kassiert Ø >= 4,0 ODER 9/10 mit 3+ …
HOCKEY_HEIM_B = 3.2          # … und Heim schießt Ø >= 3,2
HOCKEY_LINIE = 2.5
HOCKEY_SICHERHEIT = 0.97
HOCKEY_LIGA_RAUS = ("friendl", "test")
HOCKEY_TOP = ("khl", "nhl", "shl", "liiga", "del", "extraliga", "nla", "national league",
              "elite league", "eliteserien", "allsvenskan", "vhl", "ice hockey league",
              "ebel", "ehl", "metal ligaen", "tipos")


def hockey_top(liga: str) -> bool:
    """Nur ganze Wörter vergleichen — "nla" steckt sonst auch in "Finland"."""
    l = (liga or "").lower()
    toks = set(re.findall(r"[a-z]+", l))
    hit = any((k in l) if " " in k else (k in toks) for k in HOCKEY_TOP)
    return hit and not any(j in l for j in ("u20", "u18", "u16", "junior", "women", "mhl"))


def hockey_reg(e):
    """Regulärer Endstand (heim, gast) = Summe der ersten drei Drittel. None,
    wenn keine drei Drittel gespeichert sind (dann auch kein OT-Wissen)."""
    p = e.get("perioden") or []
    if len(p) < 3:
        return None
    return sum(int(x[0]) for x in p[:3]), sum(int(x[1]) for x in p[:3])


def hockey_stufe(heim_eigene: list, gast_kassiert: list):
    """Stufe 'A' / 'B' oder None. Listen: neueste zuerst, mindestens HOCKEY_N Werte."""
    if len(heim_eigene) < HOCKEY_N or len(gast_kassiert) < HOCKEY_N:
        return None
    mu_s = st.mean(heim_eigene[:HOCKEY_N])
    mu_d = st.mean(gast_kassiert[:HOCKEY_N])
    r9 = sum(c > HOCKEY_LINIE for c in gast_kassiert[:10]) >= 9
    if mu_s < HOCKEY_MIN_HEIM:
        return None
    if mu_d >= HOCKEY_GAST_A:
        return "A"
    if (mu_d >= HOCKEY_GAST_B or r9) and mu_s >= HOCKEY_HEIM_B:
        return "B"
    return None


def hockey_spiele(hist: dict) -> dict:
    """Alle Spiele der Historie mit drei Dritteln und beiden Team-IDs, dedupliziert."""
    games = {}
    for t in hist.values():
        for e in t.get("events") or []:
            r = hockey_reg(e)
            if r and e.get("heim_id") and e.get("gast_id") and e.get("id"):
                games[e["id"]] = {"t": int(e.get("time") or 0), "liga": e.get("liga") or "",
                                  "hid": str(e["heim_id"]), "aid": str(e["gast_id"]),
                                  "h": r[0], "a": r[1]}
    return games


def hockey_faelle(games: dict) -> list:
    """Alle Spiele, auf die die Regel zutrifft, als Liste
    [{"t": Zeit, "stufe": "A"/"B", "hit": 0/1, "liga": …}].
    WICHTIG: immer über ALLE Spiele rechnen — wer vorher filtert, nimmt den
    Teams ihre Vorgeschichte und bekommt keine Fälle mehr (22.09.)."""
    per_team = defaultdict(list)
    for g in games.values():
        per_team[g["hid"]].append(g); per_team[g["aid"]].append(g)
    for v in per_team.values():
        v.sort(key=lambda g: g["t"])
    out = []
    for g in games.values():
        H, A = per_team[g["hid"]], per_team[g["aid"]]
        hi = next(i for i, x in enumerate(H) if x is g)
        ai = next(i for i, x in enumerate(A) if x is g)
        if hi < HOCKEY_N or ai < HOCKEY_N or any(k in g["liga"].lower() for k in HOCKEY_LIGA_RAUS):
            continue
        eigene = [(x["h"] if x["hid"] == g["hid"] else x["a"]) for x in H[hi - HOCKEY_N:hi][::-1]]
        kass = [(x["a"] if x["hid"] == g["aid"] else x["h"]) for x in A[ai - HOCKEY_N:ai][::-1]]
        stufe = hockey_stufe(eigene, kass)
        if not stufe:
            continue
        out.append({"t": g["t"], "stufe": stufe, "liga": g["liga"],
                    "hit": int(g["h"] > HOCKEY_LINIE)})
    return out


def hockey_quoten(faelle: list) -> dict:
    """Aus Fällen die Trefferquote je Stufe: {'A': (n, quote), 'B': …, 'alle': …}."""
    t = defaultdict(lambda: [0, 0])
    for f in faelle:
        for k in (f["stufe"], "alle"):
            t[k][0] += 1; t[k][1] += f["hit"]
    return {k: (n, (h / n if n else 0.0)) for k, (n, h) in t.items()}


def hockey_backtest(games: dict) -> dict:
    """Trefferquote der Regel je Stufe aus der Historie: {'A': (n, quote), 'B': …, 'alle': …}."""
    return hockey_quoten(hockey_faelle(games))


def _hockey_backtest_alt(games: dict) -> dict:
    per_team = defaultdict(list)
    for g in games.values():
        per_team[g["hid"]].append(g); per_team[g["aid"]].append(g)
    for v in per_team.values():
        v.sort(key=lambda g: g["t"])
    treffer = defaultdict(lambda: [0, 0])
    for g in games.values():
        H, A = per_team[g["hid"]], per_team[g["aid"]]
        hi = next(i for i, x in enumerate(H) if x is g)
        ai = next(i for i, x in enumerate(A) if x is g)
        if hi < HOCKEY_N or ai < HOCKEY_N or any(k in g["liga"].lower() for k in HOCKEY_LIGA_RAUS):
            continue
        eigene = [(x["h"] if x["hid"] == g["hid"] else x["a"]) for x in H[hi - HOCKEY_N:hi][::-1]]
        kass = [(x["a"] if x["hid"] == g["aid"] else x["h"]) for x in A[ai - HOCKEY_N:ai][::-1]]
        stufe = hockey_stufe(eigene, kass)
        if not stufe:
            continue
        y = int(g["h"] > HOCKEY_LINIE)
        for k in (stufe, "alle"):
            treffer[k][0] += 1; treffer[k][1] += y
    return {k: (n, (h / n if n else 0.0)) for k, (n, h) in treffer.items()}


# ---------------------------------------------------------------------------
# SERIEN-SCAN (17.09.) — Lucios Serien-Regel, reine Trefferquote, alle Sportarten
#
# Lucio: "ich guck mir sowieso jedes einzelne Spiel und jeden einzelnen Markt
# an, dann kann ich das gleich mitchecken" — also keine Modell-Vorauswahl,
# sondern seine Regel auf alle erfassten Über-Märkte, mit der gemessenen
# Trefferquote als faire Quote. Nachjustieren (Ligen/Märkte ohne Quoten)
# kommt später über seine Rückmeldung. Gilt für Basketball, Handball und
# Eishockey gleich ("für die anderen Sportarten genau dasselbe, Modell aus").
#   Summen-Märkte (beide Teams zusammen): beide Teams lagen in 9 (Stufe A)
#   bzw. 8 (Stufe B) ihrer letzten 10 Spiele über der Linie.
#   Team-Märkte: das Team selbst in 9 seiner letzten 10.
#   Nur "über", je Markt nur die strengste Linie, die die Regel erfüllt
#   (keine Leiter). Fair = 1 / Trefferquote genau dieser Linie+Regel aus der
#   Historie (mindestens 100 Fälle, sonst eine Linie tiefer). Gemeldet wird
#   das Fenster Trefferquote >= 75 % (Lucio: "mindestens 75 %") und Fair
#   >= 1,15 ("das können wir so beibehalten, aber mehr dann auch nicht").
# Basketball: Statistikfelder (3er, Fouls, Freiwürfe) aus dem Statistikblock
# der Einzelspiel-Abfrage (zehn Spiele je Anfrage); Punkte/Halbzeit/Viertel
# aus den Abschnitten (1=Q1, 2=Q2, 3=Halbzeitstand, 4=Q3, 5=Q4).
# Eishockey: nur reguläre Zeit (drei Drittel), dazu die Gast-Abwehr-Regel.
# Aufruf: SPORT=<sportart> python3 handball.py scan
# ---------------------------------------------------------------------------
def _lines(a, b, step):
    return [x + 0.5 for x in range(a, b + 1, step)]


SERIEN = {
    "basketball": {
        "emoji": "🏀",
        "sum": {"Punkte": ("pts", _lines(150, 235, 5)),
                "1. HZ Punkte": ("h1", _lines(70, 115, 3)),
                "Q1 Punkte": ("q1", _lines(36, 58, 2)),
                "3er": ("t3", _lines(14, 30, 2)),
                "Fouls": ("f", _lines(26, 44, 3)),
                "Freiwürfe": ("ft", _lines(24, 56, 4))},
        "team": {"Punkte": ("pts", _lines(75, 125, 5)),
                 "1. HZ Punkte": ("h1", _lines(36, 60, 3)),
                 "3er": ("t3", _lines(6, 15, 1))},
        "stats": {"t3": "3points", "f": "fouls", "ft": "free_throws"},
    },
    "handball": {
        "emoji": "🤾",
        "sum": {"Tore": ("pts", _lines(43, 71, 2)),
                "1. HZ Tore": ("h1", _lines(19, 36, 1)),
                "2. HZ Tore": ("h2", _lines(19, 36, 1))},
        "team": {"Tore": ("pts", _lines(20, 38, 1)),
                 "1. HZ Tore": ("h1", _lines(9, 19, 1))},
        "stats": {},
    },
    "eishockey": {
        "emoji": "🏒",
        "sum": {"Tore (regulär)": ("reg", _lines(3, 8, 1)),
                "1. Drittel Tore": ("p1", _lines(0, 3, 1)),
                "2. Drittel Tore": ("p2", _lines(0, 3, 1)),
                "3. Drittel Tore": ("p3", _lines(0, 3, 1))},
        "team": {"Tore (regulär)": ("reg", _lines(1, 5, 1))},
        "stats": {},
    },
}
SR_N = 10            # Serienfenster
SR_MIN_BT = 100      # Mindestfälle in der Historie für eine faire Quote
SR_MIN_HIT = 0.75    # Lucio: nur Märkte/Linien mit mindestens 75 % Trefferquote
# Anzeige-Untergrenze: die strengste Serien-Linie liegt oft noch weit unter dem
# Schnitt (95 %+, Fair 1,05) — das kann kein Bookie zu 1,30 geben. Ab Fair
# 1,15 wird gemeldet (Lucio 17.09.: "passt, beibehalten, aber mehr nicht").
SR_MIN_FAIR = float(os.environ.get("BB_MIN_FAIR", os.environ.get("SR_MIN_FAIR", "1.15")))
# 18.09. (Lucio, Rückblick auf den Testtag): "extreme Exoten dabei — der Bookie
# führt den Markt oder gleich das ganze Spiel nicht". Deshalb: nur Spiele, die
# bet365 im Programm hat (führt bet365 ein Spiel, hat BetLabel es fast sicher
# auch). Und beim Eishockey nur die eine gefundene Regel (Gast-Abwehr), keine
# Serien-Leiter dazu — "wenn man irgendwas hat, das funktioniert".
NUR_B365 = os.environ.get("NUR_B365", "1") == "1"
NUR_REGEL = os.environ.get("NUR_REGEL", "1") == "1"      # gilt nur für Eishockey


def flat_game(e, stats):
    """Ein Spiel der Historie als flache Werte je Seite; fehlende Felder fehlen."""
    if not (e.get("tore") and e.get("heim_id") and e.get("gast_id") and e.get("time") and e.get("id")):
        return None
    g = {"id": e["id"], "t": int(e["time"]), "liga": e.get("liga") or "",
         "hid": str(e["heim_id"]), "aid": str(e["gast_id"]),
         "pts_h": int(e["tore"][0]), "pts_a": int(e["tore"][1])}
    p = e.get("perioden") or []
    if SPORT_KEY == "basketball" and len(p) >= 5:
        g["q1_h"], g["q1_a"] = int(p[0][0]), int(p[0][1])
        g["h1_h"], g["h1_a"] = int(p[0][0]) + int(p[1][0]), int(p[0][1]) + int(p[1][1])
    elif SPORT_KEY == "handball" and e.get("hz"):
        g["h1_h"], g["h1_a"] = int(e["hz"][0]), int(e["hz"][1])
        g["h2_h"], g["h2_a"] = g["pts_h"] - g["h1_h"], g["pts_a"] - g["h1_a"]
    elif SPORT_KEY == "eishockey" and len(p) >= 3:
        for i in range(3):
            g[f"p{i + 1}_h"], g[f"p{i + 1}_a"] = int(p[i][0]), int(p[i][1])
        g["reg_h"] = sum(int(p[i][0]) for i in range(3)); g["reg_a"] = sum(int(p[i][1]) for i in range(3))
    s = stats.get(str(e["id"])) or {}
    for k, feld in SERIEN[SPORT_KEY]["stats"].items():
        v = s.get(feld)
        if v and len(v) == 2:
            g[k + "_h"], g[k + "_a"] = int(v[0]), int(v[1])
    return g


def flat_games(hist, stats):
    games = {}
    for t in hist.values():
        for e in t.get("events") or []:
            g = flat_game(e, stats)
            if g:
                games[g["id"]] = g
    return games


def sr_letzte(per_team, tid, feld, vor_ts, n=SR_N, side_of=None):
    """Die letzten n Werte eines Teams vor vor_ts: Spielsumme (side_of=None)
    oder eigener Wert (side_of='own'). Neueste zuerst."""
    out = []
    for g in reversed(per_team.get(tid) or []):
        if g["t"] >= vor_ts or feld + "_h" not in g:
            continue
        if side_of == "own":
            out.append(g[feld + "_h"] if g["hid"] == tid else g[feld + "_a"])
        else:
            out.append(g[feld + "_h"] + g[feld + "_a"])
        if len(out) >= n:
            break
    return out


def sr_backtest(games, cfg):
    """Trefferquoten je (Markt, Linie, Regel) aus der Historie: {key: [n, treffer]}."""
    per_team = defaultdict(list)
    for g in games.values():
        per_team[g["hid"]].append(g); per_team[g["aid"]].append(g)
    for v in per_team.values():
        v.sort(key=lambda g: g["t"])
    bt = defaultdict(lambda: [0, 0])
    for g in games.values():
        for mk, (feld, lines) in cfg["sum"].items():
            if feld + "_h" not in g:
                continue
            H = sr_letzte(per_team, g["hid"], feld, g["t"]); A = sr_letzte(per_team, g["aid"], feld, g["t"])
            if len(H) < SR_N or len(A) < SR_N:
                continue
            y = g[feld + "_h"] + g[feld + "_a"]
            for L in lines:
                ch = sum(v > L for v in H); ca = sum(v > L for v in A)
                for rule, k in (("9/10", 9), ("8/10", 8)):
                    if ch >= k and ca >= k:
                        bt[(mk, L, rule)][0] += 1; bt[(mk, L, rule)][1] += int(y > L)
        for mk, (feld, lines) in cfg["team"].items():
            if feld + "_h" not in g:
                continue
            for side, tid in (("Heim", g["hid"]), ("Gast", g["aid"])):
                O = sr_letzte(per_team, tid, feld, g["t"], side_of="own")
                if len(O) < SR_N:
                    continue
                y = g[feld + ("_h" if side == "Heim" else "_a")]
                for L in lines:
                    if sum(v > L for v in O) >= 9:
                        key = (side + "-Team " + mk, L, "eigene 9/10")
                        bt[key][0] += 1; bt[key][1] += int(y > L)
    return per_team, bt


def sr_quote(bt, key):
    """(n, Trefferquote) — None, wenn zu wenig Fälle, unter 75 % oder Fair unter
    der Anzeige-Grenze (dann lohnt auch keine tiefere Linie: die wäre noch
    sicherer und noch billiger)."""
    n, h = bt.get(key, [0, 0])
    if n < SR_MIN_BT or not h:
        return n, None
    q = h / n
    return (n, q) if (q >= SR_MIN_HIT and 1 / q >= SR_MIN_FAIR) else (n, None)


def sr_signale(per_team, bt, cfg, m, esc):
    """Signale eines anstehenden Spiels: je Markt die strengste Linie, die die
    Regel erfüllt und im Fenster liegt. Liste von (Markt, Linie, Regel, n, Quote, Detail)."""
    home, away = m.get("home") or {}, m.get("away") or {}
    hid, aid = str(home.get("id")), str(away.get("id"))
    ts_ = int(m.get("time") or 0)
    sigs = []
    for mk, (feld, lines) in cfg["sum"].items():
        H = sr_letzte(per_team, hid, feld, ts_); A = sr_letzte(per_team, aid, feld, ts_)
        if len(H) < SR_N or len(A) < SR_N:
            continue
        for rule, k in (("9/10", 9), ("8/10", 8)):
            found = None
            for L in sorted(lines, reverse=True):
                ch = sum(v > L for v in H); ca = sum(v > L for v in A)
                if ch >= k and ca >= k:
                    n, q = sr_quote(bt, (mk, L, rule))
                    if q:
                        found = (mk, L, rule, n, q, f"Heim {ch}/10 (Ø {st.mean(H):.1f}) · Gast {ca}/10 (Ø {st.mean(A):.1f})", "sum", mk)
                        break
                    if n >= SR_MIN_BT and (bt[(mk, L, rule)][1] / n) > SR_MIN_HIT:
                        break                    # Fair unter der Grenze — tiefer wird es nur billiger
            if found:
                sigs.append(found); break        # 9/10 gefunden → 8/10 nicht mehr nötig
    for mk, (feld, lines) in cfg["team"].items():
        for side, tid, name in (("Heim", hid, home.get("name", "?")), ("Gast", aid, away.get("name", "?"))):
            O = sr_letzte(per_team, tid, feld, ts_, side_of="own")
            if len(O) < SR_N:
                continue
            for L in sorted(lines, reverse=True):
                c = sum(v > L for v in O)
                if c >= 9:
                    key = (side + "-Team " + mk, L, "eigene 9/10")
                    n, q = sr_quote(bt, key)
                    if q:
                        sigs.append((f"{esc(name)} {mk}", L, "eigene 9/10", n, q, f"{c}/10 (Ø {st.mean(O):.1f})", side, mk))
                        break
                    if n >= SR_MIN_BT and (bt[key][1] / n) > SR_MIN_HIT:
                        break
    return sigs


def sr_stats_view(chunk):
    d = api_get("/v1/event/view", event_id=",".join(chunk))
    out = {}
    for ev in d.get("results") or []:
        slim = {}
        for k, v in (ev.get("stats") or {}).items():
            p = _num_pair(v)
            if p is not None:
                slim[k] = p
        out[str(ev.get("id"))] = slim
    return out


# --- bet365-Quoten für die Serien-Signale (17.09. abends) ------------------
# US-Aufbau des bet365-Katalogs bei Basketball/Eishockey/Handball: "game_lines",
# "1st_half", "1st_quarter" … mit Zeilen (Teamnamen) und Spalten Spread/Total/
# Money Line — beim Total sind je Linie zwei Einträge: erst Over, dann Under.
# "team_totals" (auch 1st_half_/1st_quarter_): header = Teamname, handicap =
# Linie, wieder Over vor Under. Eishockey-Totals bei bet365 sind inkl.
# Verlängerung — unsere Regeln laufen auf reguläre Zeit; die Quote wird
# trotzdem gezeigt (Über-Wetten profitieren von OT), mit Hinweis.
B365_TOKEN = os.environ.get("BETSAPI_TOKEN_B365") or TOKEN
# 17.09. abends (Lucio): 1xBet zusätzlich (Totals + Team-Totals mit voller
# Leiter, keine Halbzeiten/Drittel/Viertel) — um zu sehen, ob die Abdeckung
# dort besser ist. 1xBet-Sportkennungen laut BetsAPI-Doku: 1 Fußball,
# 2 Eishockey, 3 Basketball, 6 Volleyball; Handball ist nicht dokumentiert
# (Versuch mit 8, sonst bleibt 1xBet dort leer).
XB_TOKEN = os.environ.get("BETSAPI_TOKEN_1XBET") or TOKEN
# 17.09. abends (Lucio): 1xBet "total nutzlos" (nur Gesamtspiel-Märkte) — aus,
# nur noch bet365. Code bleibt; XB_ENABLED=1 in der Umgebung schaltet es wieder an.
XB_ENABLED = os.environ.get("XB_ENABLED", "0") == "1"
XB_SPORT_ID = {"basketball": 3, "eishockey": 2, "handball": 8, "volleyball": 6}
# Zeitfenster (Lucio 17.09.): nur bis morgen früh 06:00 deutscher Zeit
FENSTER_ENDE_STUNDE = 6
PLAY_MIN_ODDS = 1.30
PLAY_FAIR_FACTOR = 1.05
B365_PART = {"Punkte": "", "1. HZ Punkte": "1. HZ", "Q1 Punkte": "Q1",
             "Tore": "", "1. HZ Tore": "1. HZ",
             "Tore (regulär)": "", "1. Drittel Tore": "P1", "2. Drittel Tore": "P2", "3. Drittel Tore": "P3"}
_b365_tot = False


def _part_of(key: str):
    k = key.lower()
    if "1st_half" in k or k == "1st_half":
        return "1. HZ"
    if "1st_quarter" in k:
        return "Q1"
    if "1st_period" in k:
        return "P1"
    if "2nd_period" in k:
        return "P2"
    if "3rd_period" in k:
        return "P3"
    if k in ("game_lines", "game_total", "totals", "total", "game_totals") or "alternative" in k and "total" in k:
        return ""
    return None


def _norm_team(n: str) -> set:
    import unicodedata
    n = unicodedata.normalize("NFKD", str(n or "")).encode("ascii", "ignore").decode().lower()
    for junk in ("(w)", "(women)", "women", "(m)", " bk", " sc", " fc", " ic", " hc", "-", "."):
        n = n.replace(junk, " ")
    return {t for t in n.split() if len(t) >= 3}


def _side_of(team: str, home: str, away: str, order_idx: int):
    """'Heim'/'Gast' per Namensabgleich (Token-Überschneidung), sonst nach Reihenfolge."""
    t, h, a = _norm_team(team), _norm_team(home), _norm_team(away)
    sh, sa = len(t & h), len(t & a)
    if sh != sa:
        return "Heim" if sh > sa else "Gast"
    return "Heim" if order_idx == 0 else "Gast"


# Plausible Linienbereiche je Sportart — alles außerhalb ist ein Fremdmarkt
# (17.09.: "player_goals" mit Linie 6,5 landete als Handball-Gesamtzahl → ✔ falsch)
RANGE_TAB = {"basketball": {("", "sum"): (100, 320), ("1. HZ", "sum"): (50, 160), ("Q1", "sum"): (20, 90),
                            ("", "team"): (40, 160), ("1. HZ", "team"): (20, 90), ("Q1", "team"): (8, 45)},
             "handball":   {("", "sum"): (38, 95), ("1. HZ", "sum"): (16, 48), ("", "team"): (16, 48), ("1. HZ", "team"): (7, 26)},
             "eishockey":  {("", "sum"): (2, 12), ("P1", "sum"): (0.4, 5), ("P2", "sum"): (0.4, 5), ("P3", "sum"): (0.4, 5),
                            ("", "team"): (0.4, 7)}}
B365_SECTIONS_OK = ("main", "game", "half", "quarter", "team", "main_props", "totals", "goals", "period")


def _plausibel(part, side, L):
    lo, hi = RANGE_TAB.get(SPORT_KEY, {}).get((part, "sum" if side == "sum" else "team"), (0, 1e9))
    return lo <= L <= hi


def b365_sport_quotes(pm, home="", away="") -> dict:
    """{(Abschnitt, 'sum'|'Heim'|'Gast', Linie): Über-Quote} aus einer Prematch-Antwort."""
    res = pm.get("results") if isinstance(pm, dict) else None
    res = res[0] if isinstance(res, list) and res else (res if isinstance(res, dict) else {})
    raw = {}
    for sec, node in res.items():
        if not (isinstance(node, dict) and isinstance(node.get("sp"), dict)):
            continue
        if str(sec).lower() not in B365_SECTIONS_OK:
            continue                                   # Spieler-Wetten u. ä. (player, assists, rebounds …)
        for mk, mv in node["sp"].items():
            lst = mv if isinstance(mv, list) else (mv.get("odds") if isinstance(mv, dict) else None)
            if not lst:
                continue
            key = mk.lower()
            if "player" in key or "margin" in key or "race" in key or "odd_even" in key or "to_score" in key:
                continue
            out = raw   # alle Zweige unten schreiben in dieselbe Sammlung
            # Handball-Aufbau: Zeilen "Handicap / Total / To Win", dann je Team ein Block in Zeilenreihenfolge
            zeilen = [e.get("name") for e in lst if (e.get("header") or " ").strip() == "" and e.get("name")]
            if "Total" in zeilen and not any((e.get("header") or "").strip() == "Total" for e in lst):
                part = _part_of(key) if _part_of(key) is not None else ("1. HZ" if "1st_half" in key else "")
                idx = zeilen.index("Total")
                bloecke = {}
                for e in lst:
                    h = (e.get("header") or "").strip()
                    if h and e.get("name") is None:
                        bloecke.setdefault(h, []).append(e)
                teams = list(bloecke)
                if teams:
                    ers = bloecke[teams[0]]
                    if idx < len(ers) and ers[idx].get("handicap") not in (None, ""):
                        try:
                            out.setdefault((part, "sum", float(ers[idx]["handicap"])), float(ers[idx].get("odds") or 0))
                        except (TypeError, ValueError):
                            pass
                continue
            if "team_total" in key and "odd" not in key:
                part = "1. HZ" if "half" in key else ("Q1" if "1st_quarter" in key else "")
                if "alternative" in key or any(e.get("name") not in (None, "") and (e.get("header") or "").strip() not in ("", "Over", "Under") for e in lst):
                    # Blockleiter: je Team Zeilen (name = Linie, header = Team), dann Over-, dann Under-Spalte
                    teams, blocks, cur = [], [], None
                    for e in lst:
                        h = (e.get("header") or "").strip()
                        if e.get("name") not in (None, "") and h not in ("Over", "Under"):
                            if cur is None or cur["team"] != h or cur["overs"]:
                                cur = {"team": h, "rows": [], "overs": []}; blocks.append(cur)
                                if h not in teams:
                                    teams.append(h)
                            cur["rows"].append(e.get("name"))
                        elif h == "Over" and cur is not None:
                            cur["overs"].append(e.get("odds"))
                    for b in blocks:
                        side = _side_of(b["team"], home, away, teams.index(b["team"]) if b["team"] in teams else 1)
                        for L, q in zip(b["rows"], b["overs"]):
                            try:
                                if float(q) > 1.0:
                                    out.setdefault((part, side, float(str(L).replace(",", "."))), float(q))
                            except (TypeError, ValueError):
                                pass
                    continue
                teams, by = [], {}
                for e in lst:
                    h, hc = e.get("header"), e.get("handicap")
                    if not h or hc in (None, "") or not str(h).strip():
                        continue
                    if h not in teams:
                        teams.append(h)
                    by.setdefault((h, str(hc)), []).append(e)
                for (h, hc), es in by.items():
                    if len(es) < 2 or h not in teams[:2]:
                        continue
                    side = _side_of(h, home, away, teams.index(h))
                    try:
                        out.setdefault((part, side, float(hc)), float(es[0].get("odds")))
                    except (TypeError, ValueError):
                        pass
                continue
            part = _part_of(key)
            if part is None and ("over_under" in key or "goals" in key or "points" in key):
                part = "1. HZ" if "1st_half" in key else ("" if "2nd_half" not in key and "quarter" not in key else None)
            if part is None:
                continue
            tot = [e for e in lst if (e.get("header") or "").strip() == "Total" and e.get("handicap") not in (None, "")]
            for i in range(0, len(tot) - 1, 2):
                try:
                    out.setdefault((part, "sum", float(tot[i]["handicap"])), float(tot[i]["odds"]))
                except (TypeError, ValueError):
                    continue
            if not tot:
                # Zeilen/Spalten-Aufbau wie im Fußball: Zeilen = Linien, Spalte "Over"
                rows = [e for e in lst if (e.get("header") or " ").strip() == "" and e.get("name") is not None]
                overs = [e for e in lst if (e.get("header") or "").strip() == "Over"]
                for i, e in enumerate(overs):
                    hc = e.get("handicap")
                    try:
                        L = float(str(hc).replace(",", ".")) if hc not in (None, "") else float(str(rows[i].get("name")).replace(",", "."))
                        q = float(e.get("odds") or 0)
                    except (TypeError, ValueError, IndexError):
                        continue
                    if q > 1.0:
                        out.setdefault((part, "sum", L), q)
    return {k: v for k, v in raw.items() if v and v > 1.0 and _plausibel(k[0], k[1], k[2])}


def b365_tail(q, fair, checked, near=None, label="b365", schaetz=None):
    """Anzeige nach Lucios Regel: ✔ ab Fair × 1,05 und ≥ 1,30, sonst ✘; ohne
    Quote '<label> –'. Nachbarlinie (Linie, Quote, Lage) mit sicherer Aussage:
    lockerere Linie schon spielbar → ✔, strengere Linie schon zu billig → ✘;
    sonst die aus den bet365-Linien GESCHÄTZTE Quote an unserer Linie (≈)."""
    if q:
        ok = q >= fair * PLAY_FAIR_FACTOR and q >= PLAY_MIN_ODDS
        return f" · 💰 {label} {q:.2f} {'✔' if ok else '✘'}"
    if near:
        L, nq, lage = near
        ok = nq >= fair * PLAY_FAIR_FACTOR and nq >= PLAY_MIN_ODDS
        if lage == "unter" and ok:
            return f" · 💰 {label} ({L:g}) {nq:.2f} ✔"
        if lage == "über" and not ok:
            return f" · 💰 {label} ({L:g}) {nq:.2f} ✘"
        if schaetz:
            est, sicher = schaetz
            ok2 = est >= fair * PLAY_FAIR_FACTOR and est >= PLAY_MIN_ODDS
            return f" · 💰 {label} ({L:g}) {nq:.2f} → ≈{est:.2f} {('✔' if ok2 else '✘') if sicher else '?'}"
        return f" · 💰 {label} ({L:g}) {nq:.2f} ?"
    return ""                                   # 18.09.: kein "b365 –"-Rauschen mehr


def xb_quotes(ev) -> dict:
    """1xBet-Event (Value.GE) → {(Abschnitt '', 'sum'|'Heim'|'Gast', Linie): Über-Quote}.
    Nur halbe Linien (X,5) — ganze Linien sind Asian-Totals mit Rückzahlung."""
    out = {}
    for g in (ev.get("Value") or {}).get("GE") or []:
        G = str(g.get("G"))
        if G not in ("17", "15", "62"):
            continue
        side = {"17": "sum", "15": "Heim", "62": "Gast"}[G]
        want = {"17": 9, "15": 11, "62": 13}[G]
        for row in g.get("E") or []:
            for x in row:
                if x.get("T") != want or x.get("P") is None:
                    continue
                try:
                    L = float(x["P"]); q = float(x.get("C") or 0)
                except (TypeError, ValueError):
                    continue
                if abs(L - int(L) - 0.5) > 1e-9 or q <= 1.0:
                    continue
                out.setdefault(("", side, L), q)
    return out


# Streuung je Markt (Punkte/Tore), um aus bet365-Linien den Preis an UNSERER
# Linie zu schätzen: bet365 setzt die Hauptlinie etwa auf den Median, die
# Quote sagt, wie weit die Linie vom Median liegt. Daraus Median schätzen,
# dann die Wahrscheinlichkeit für unsere Linie, plus 5 % Marge → "≈ Quote".
SD_TAB = {"basketball": {("", "sum"): 16.0, ("1. HZ", "sum"): 10.0, ("Q1", "sum"): 6.0,
                         ("", "team"): 11.0, ("1. HZ", "team"): 7.0, ("Q1", "team"): 4.5},
          "handball":   {("", "sum"): 6.0, ("1. HZ", "sum"): 4.0, ("", "team"): 4.0, ("1. HZ", "team"): 3.0},
          "eishockey":  {("", "sum"): 1.9, ("P1", "sum"): 1.0, ("P2", "sum"): 1.0, ("P3", "sum"): 1.0, ("", "team"): 1.5}}


def _phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _phi_inv(p):
    # Näherung (Acklam) reicht hier völlig
    p = min(max(p, 1e-6), 1 - 1e-6)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - 0.02425:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5; r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def _schaetz_mit_sd(qb, part, side, line, sd):
    mus, quoten = [], []
    for (pt, sdx, L), q in qb.items():
        if pt != part or sdx != side or not q or q <= 1.0:
            continue
        p = min(0.98, (1.0 / q) / 1.05)          # Marge (~5 %) raus
        mus.append(L + sd * _phi_inv(p))         # P(X > L) = p  →  μ = L + sd·Φ⁻¹(p)
        quoten.append(q)
    if not mus:
        return None, quoten
    mu = sum(mus) / len(mus)
    p_ours = _phi((mu - line) / sd)
    if p_ours <= 0.02:
        return 30.0, quoten
    return max(1.01, (1.0 / p_ours) / 1.05), quoten     # Marge wieder drauf


def b365_schaetzung(qb, part, side, line, fair=None):
    """Geschätzte bet365-Quote an unserer Linie aus allen bet365-Linien desselben
    Markts (Median-Schätzung über die Normalverteilung). Liefert (Quote, sicher):
    'sicher' ist False, wenn das Urteil bei ±30 % Streuung kippt oder nur
    Linien weit weg vom Median (Quoten < 1,25) als Stütze da sind.
    Geprüft 17.09. an 56 echten bet365-Linien (Basketball, Leave-one-out):
    Median-Fehler 5,7 %, kein einziges verdrehtes ✔/✘ an der 1,30-Grenze."""
    sd = SD_TAB.get(SPORT_KEY, {}).get((part, "sum" if side == "sum" else "team"))
    if not sd:
        return None
    est, quoten = _schaetz_mit_sd(qb, part, side, line, sd)
    if est is None:
        return None
    sicher = any(q >= 1.25 for q in quoten)
    if fair:
        def urteil(x):
            return x >= fair * PLAY_FAIR_FACTOR and x >= PLAY_MIN_ODDS
        lo, _ = _schaetz_mit_sd(qb, part, side, line, sd * 0.7)
        hi, _ = _schaetz_mit_sd(qb, part, side, line, sd * 1.3)
        if lo is not None and hi is not None and not (urteil(lo) == urteil(hi) == urteil(est)):
            sicher = False
    return est, sicher


def b365_near(qb, part, side, line):
    """Nächste bet365-Linie mit Lage — ohne Abstandsgrenze: die Schlüsse
    (lockerere Linie schon spielbar → ✔, strengere schon zu billig → ✘) gelten
    in jeder Entfernung; nur das '?' wird mit dem Abstand unschärfer."""
    cands = [(L, q) for (pt, sd, L), q in qb.items() if pt == part and sd == side]
    if not cands:
        return None
    L, q = min(cands, key=lambda x: (abs(x[0] - line), x[0]))
    if abs(L - line) < 1e-9:
        return None
    return (L, q, "unter" if L < line else "über")


def serien_scan():
    import importlib.util
    spec = importlib.util.spec_from_file_location("scan", Path(__file__).parent / "scan.py")
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)
    cfg = SERIEN[SPORT_KEY]

    hfiles = sorted(OUT.glob(f"{SPORT_KEY}_historie_*.json"))
    sfiles = sorted(OUT.glob(f"{SPORT_KEY}_stats_*.json"))
    if not hfiles:
        sys.exit(f"keine {SPORT['name']}-Historie gefunden — erst den Erkundungs-/Liga-Lauf machen")
    hist = json.loads(hfiles[-1].read_text(encoding="utf-8"))
    stats = json.loads(sfiles[-1].read_text(encoding="utf-8")) if (sfiles and cfg["stats"]) else {}
    print(f"Historie: {hfiles[-1].name} ({len(hist)} Teams) · Statistik: {len(stats)} Spiele", flush=True)
    heute = datetime.now(timezone.utc).date()

    # 1) anstehende Spiele — bis morgen früh 06:00 deutscher Zeit (Lucio 17.09.)
    berlin = timezone(timedelta(hours=2))
    jetzt_dt = datetime.now(berlin)
    ende_dt = jetzt_dt.replace(hour=FENSTER_ENDE_STUNDE, minute=0, second=0, microsecond=0)
    if jetzt_dt.hour >= FENSTER_ENDE_STUNDE:
        ende_dt += timedelta(days=1)
    ende_ts = int(ende_dt.timestamp())
    tage = [(heute + timedelta(days=i)).strftime("%Y%m%d") for i in range(2)]
    spiele = []
    for d in tage:
        try:
            spiele += upcoming(d)
        except Exception as exc:
            print(f"  upcoming {d}: {exc}", flush=True)
    jetzt = int(time.time())
    try:
        live = inplay()
    except Exception as exc:
        print(f"  inplay: {exc}", flush=True); live = []
    raus = HOCKEY_LIGA_RAUS if SPORT_KEY == "eishockey" else ()
    spiele = [m for m in spiele + live if not is_junk(m)
              and (m.get("_live") or jetzt < int(m.get("time") or 0) <= ende_ts)
              and not any(k in ((m.get("league") or {}).get("name") or "").lower() for k in raus)]
    n_live = sum(1 for m in spiele if m.get("_live"))
    print(f"{len(spiele)} Spiele bis {ende_dt:%a %H:%M} (davon {n_live} gerade laufend; ohne E-Sport{'/Testspiele' if raus else ''})", flush=True)

    # 2) Historien aller beteiligten Teams auffrischen (neueste 50 Spiele) und
    #    mit der Datei zusammenführen (Vereinigung nach Spiel-ID)
    ids = {}
    for m in spiele:
        for side in ("home", "away"):
            t = m.get(side) or {}
            if t.get("id"):
                ids[str(t["id"])] = t.get("name") or "?"
    print(f"{len(ids)} Teams beteiligt → Historien auffrischen", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(team_history, tid): tid for tid in ids}
        for f in as_completed(futs):
            tid = futs[f]
            try:
                neu = f.result()
            except BudgetExhausted:
                print("  Stundenbudget erschöpft — Rest mit alter Historie", flush=True); continue
            except Exception as exc:
                print(f"  Team {ids[tid]}: {exc}", flush=True); continue
            alt = {e["id"]: e for e in (hist.get(tid) or {}).get("events") or [] if e.get("id")}
            for e in neu:
                if e.get("id"):
                    alt[e["id"]] = e
            hist[tid] = {"name": ids[tid], "events": sorted(alt.values(), key=lambda e: int(e.get("time") or 0))}
    print(f"Historien aktualisiert ({_requests} Anfragen)", flush=True)

    # 3) Statistikblöcke (nur Sportarten mit Statistik-Märkten)
    if cfg["stats"]:
        todo = set()
        for tid in ids:
            ev = sorted((hist.get(tid) or {}).get("events") or [], key=lambda e: -int(e.get("time") or 0))
            for e in [x for x in ev if x.get("tore")][:SR_N + 5]:
                if str(e["id"]) not in stats:
                    todo.add(str(e["id"]))
        todo = sorted(todo)
        print(f"{len(todo)} Spiele ohne Statistikblock → {(len(todo) + 9) // 10} Anfragen", flush=True)
        chunks = [todo[i:i + 10] for i in range(0, len(todo), 10)]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = [pool.submit(sr_stats_view, c) for c in chunks]
            for f in as_completed(futs):
                try:
                    stats.update(f.result())
                except BudgetExhausted:
                    pass
                except Exception as exc:
                    print(f"  Block: {exc}", flush=True)
    OUT.mkdir(exist_ok=True)
    (OUT / f"{SPORT_KEY}_historie_{heute:%Y-%m-%d}.json").write_text(json.dumps(hist), encoding="utf-8")
    if cfg["stats"]:
        (OUT / f"{SPORT_KEY}_stats_{heute:%Y-%m-%d}.json").write_text(json.dumps(stats), encoding="utf-8")

    # 4) Trefferquoten aus der (aufgefrischten) Historie
    games = flat_games(hist, stats)
    per_team, bt = sr_backtest(games, cfg)
    print(f"Trefferquoten aus {len(games)} Spielen gerechnet ({len(bt)} Markt/Linie/Regel-Kombinationen)", flush=True)
    hockey_q = {}
    if SPORT_KEY == "eishockey":
        hockey_q = hockey_backtest(hockey_spiele(hist))
        for k in ("A", "B", "alle"):
            n, q = hockey_q.get(k, (0, 0.0))
            print(f"   Gast-Abwehr-Regel Stufe {k}: n={n}  {100 * q:.1f} %", flush=True)

    # 5) Regel anwenden — je Markt die strengste Linie
    treffer = []
    for m in spiele:
        sigs = [] if (SPORT_KEY == "eishockey" and NUR_REGEL) else sr_signale(per_team, bt, cfg, m, scan.esc)
        if SPORT_KEY == "eishockey" and hockey_q:
            x = hockey_signal(hist, hockey_q, m, jetzt)
            if x:
                sigs.insert(0, x)
        if sigs:
            treffer.append((m, (m.get("league") or {}).get("name") or "?", sigs))

    # 5b) bet365-Quoten je Spiel mit Signalen (eine Anfrage je Spiel)
    global _b365_tot
    quoten_b365 = {}
    if treffer and not any(m.get("bet365_id") for m, _, _ in treffer):
        # Spielplan ohne bet365-Kennung → Brücke über den bet365-Spielplan (our_event_id)
        bruecke = {}
        try:
            for d in tage:
                for page in (1, 2, 3, 4):
                    r = api_get("/v1/bet365/upcoming", sport_id=SPORT_HANDBALL, day=d, page=page, _token=B365_TOKEN)
                    res = r.get("results") or []
                    for e in res:
                        if e.get("our_event_id"):
                            bruecke[str(e["our_event_id"])] = e.get("id")
                    if len(res) < 50:
                        break
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404):
                _b365_tot = True
                print(f"  bet365-Spielplan nicht verfügbar (HTTP {exc.code})", flush=True)
        except Exception as exc:
            print(f"  bet365-Spielplan: {exc}", flush=True)
        for m, _, _ in treffer:
            if bruecke.get(str(m.get("id"))):
                m["bet365_id"] = bruecke[str(m.get("id"))]
        print(f"bet365-Brücke: {len(bruecke)} Spiele, {sum(1 for m, _, _ in treffer if m.get('bet365_id'))} davon mit Signalen", flush=True)
    def _hole(m):
        global _b365_tot
        fi = m.get("bet365_id")
        if not fi or _b365_tot:
            return str(m.get("id")), ({} if fi else None)
        try:
            return str(m.get("id")), b365_sport_quotes(api_get("/v1/bet365/prematch", FI=fi, _token=B365_TOKEN),
                                                       (m.get("home") or {}).get("name", ""), (m.get("away") or {}).get("name", ""))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404):
                _b365_tot = True
                print(f"  bet365-Katalog nicht verfügbar (HTTP {exc.code}) — Quotenvergleich in diesem Lauf aus", flush=True)
            return str(m.get("id")), None
        except Exception as exc:
            print(f"  bet365 {(m.get('home') or {}).get('name')}: {exc}", flush=True)
            return str(m.get("id")), None
    with ThreadPoolExecutor(max_workers=min(WORKERS, 12)) as pool:
        for f in as_completed([pool.submit(_hole, m) for m, _, _ in treffer]):
            mid, q = f.result()
            quoten_b365[mid] = q
    n_b365 = sum(1 for v in quoten_b365.values() if v)
    print(f"bet365-Katalog für {n_b365} von {len(treffer)} Spielen mit Signalen geholt", flush=True)
    if NUR_B365 and not _b365_tot:
        vorher = len(treffer)
        treffer = [t for t in treffer if t[0].get("bet365_id")]
        print(f"Exoten-Filter: {vorher - len(treffer)} Spiele ohne bet365-Programm verworfen, {len(treffer)} bleiben", flush=True)
    # Rohkataloge von zwei Spielen ablegen, damit Marktschlüssel nachgeprüft werden können
    try:
        probe = {}
        for m, _, _ in treffer[:25]:
            if m.get("bet365_id") and not _b365_tot:
                pm_ = api_get("/v1/bet365/prematch", FI=m["bet365_id"], _token=B365_TOKEN)
                pm_["_spiel"] = f"{(m.get('home') or {}).get('name')} – {(m.get('away') or {}).get('name')} [{(m.get('league') or {}).get('name')}]"
                probe[str(m.get("id"))] = pm_
        if probe:
            (OUT / f"{SPORT_KEY}_b365_probe_{heute:%Y-%m-%d}.json").write_text(json.dumps(probe), encoding="utf-8")
    except Exception as exc:
        print(f"  bet365-Probe: {exc}", flush=True)

    # 5c) 1xBet: Brücke über den 1xBet-Spielplan (our_event_id), dann Events zu zehnt
    quoten_1x = {}
    xb_sid = XB_SPORT_ID.get(SPORT_KEY) if XB_ENABLED else None
    if treffer and xb_sid:
        bruecke_1x = {}
        try:
            for d in tage:
                for page in range(1, 12):
                    r = api_get("/v1/1xbet/upcoming", sport_id=xb_sid, day=d, page=page, _token=XB_TOKEN)
                    res = r.get("results") or []
                    for e in res:
                        if e.get("our_event_id"):
                            bruecke_1x[str(e["our_event_id"])] = str(e.get("id"))
                    if len(res) < 50:
                        break
            try:
                for e in api_get("/v1/1xbet/inplay", sport_id=xb_sid, _token=XB_TOKEN).get("results") or []:
                    if e.get("our_event_id"):
                        bruecke_1x[str(e["our_event_id"])] = str(e.get("id"))
            except Exception:
                pass
        except urllib.error.HTTPError as exc:
            print(f"  1xBet-Spielplan nicht verfügbar (HTTP {exc.code})", flush=True)
        except Exception as exc:
            print(f"  1xBet-Spielplan: {exc}", flush=True)
        if not bruecke_1x:
            # Welche Sportart steckt hinter der Kennung? Ligen der ersten Treffer ausgeben.
            try:
                r = api_get("/v1/1xbet/upcoming", sport_id=xb_sid, day=tage[0], _token=XB_TOKEN)
                ligen = sorted({(e.get("league") or {}).get("name") or "?" for e in (r.get("results") or [])[:50]})
                print(f"  1xBet sport_id {xb_sid}: {len(r.get('results') or [])} Einträge, Ligen z. B. {ligen[:8]}", flush=True)
            except Exception as exc:
                print(f"  1xBet sport_id {xb_sid}: {exc}", flush=True)
        ids_1x = {bruecke_1x[str(m.get("id"))]: str(m.get("id")) for m, _, _ in treffer if bruecke_1x.get(str(m.get("id")))}
        chunks = [list(ids_1x)[i:i + 10] for i in range(0, len(ids_1x), 10)]
        def _hole_1x(chunk):
            try:
                return api_get("/v1/1xbet/event", event_id=",".join(chunk), _token=XB_TOKEN).get("results") or []
            except Exception as exc:
                print(f"  1xBet-Events: {exc}", flush=True); return []
        with ThreadPoolExecutor(max_workers=8) as pool:
            for f in as_completed([pool.submit(_hole_1x, c) for c in chunks]):
                for ev in f.result():
                    mid = ids_1x.get(str(ev.get("id")))
                    if mid:
                        quoten_1x[mid] = xb_quotes(ev)
        for m, _, _ in treffer:
            quoten_1x.setdefault(str(m.get("id")), {} if bruecke_1x.get(str(m.get("id"))) else None)
        print(f"1xBet: Brücke {len(bruecke_1x)} Spiele, Märkte für {sum(1 for v in quoten_1x.values() if v)} von {len(treffer)} Spielen mit Signalen", flush=True)

    # 6) Nachricht: Zeit zuerst, gleiche Zeit nach Liga, dann Heimteam
    treffer.sort(key=lambda x: (int(x[0].get("time") or 0), x[1].lower(), (x[0].get("home") or {}).get("name", "")))
    berlin = timezone(timedelta(hours=2))
    WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    em = cfg["emoji"]
    n_x = sum(1 for v in quoten_1x.values() if v)
    regel_text = ("<i>Gast-Abwehr-Regel: Heim über 2,5 eigene Tore (reguläre Zeit), wenn der Gast Ø ≥ 4,5 kassiert (A) "
                  "oder Ø ≥ 4,0 bzw. 9/10 mit 3+ und Heim Ø ≥ 3,2 (B) · Fair = gemessene Trefferquote der Stufe</i>"
                  if (SPORT_KEY == "eishockey" and NUR_REGEL) else
                  "<i>Serien-Regel: beide Teams 9/10 (A) bzw. 8/10 (B) über der Linie, Team-Märkte 9/10 · "
                  f"Fair = gemessene Trefferquote dieser Linie · nur über · Fenster 75 % bis Fair {SR_MIN_FAIR:.2f}</i>")
    lines_out = [f"{em} <b>{SPORT['name'].upper()}-SCAN</b> · bis {ende_dt:%a %H:%M} (auch laufende Spiele) · 🧪 <i>Test</i>",
                 regel_text,
                 f"<i>Nur Spiele im bet365-Programm{' (Exoten raus)' if NUR_B365 else ''} · bet365-Quote bei {n_b365}/{len(treffer)} Spielen"
                 + (f" · 1xBet für {n_x}/{len(treffer)} (nur Gesamtspiel)" if XB_ENABLED else "") + "</i>", ""]
    n_sig = 0
    for m, liga, sigs in treffer:
        t = datetime.fromtimestamp(int(m.get("time") or 0), berlin)
        home = (m.get("home") or {}).get("name", "?"); away = (m.get("away") or {}).get("name", "?")
        top = " · ⭐ Topliga" if (SPORT_KEY == "eishockey" and hockey_top(liga)) else ""
        live = " · 🔴 läuft bereits" if m.get("_live") else ""
        block = [f"{em} <b>{scan.esc(home)} – {scan.esc(away)}</b>",
                 f"🕒 {WD[t.weekday()]} {t:%H:%M} · {scan.esc(liga)}{top}{live}"]
        qb = quoten_b365.get(str(m.get("id")))
        qx = quoten_1x.get(str(m.get("id")))
        for mk, L, rule, n, q, detail, side, base in sigs:
            n_sig += 1
            fair = 1 / q
            part = B365_PART.get(base)
            bq = qb.get((part, side, float(L))) if (qb and part is not None) else None
            near = b365_near(qb, part, side, float(L)) if (qb and part is not None and not bq) else None
            schaetz = b365_schaetzung(qb, part, side, float(L), fair) if near else None
            ot = " <i>(inkl. OT)</i>" if ((bq or near) and SPORT_KEY == "eishockey") else ""
            xq = xnear = None
            if qx is not None and part == "":            # 1xBet: nur Gesamtspiel (keine Unterspiele)
                xq = qx.get(("", side, float(L)))
                xnear = b365_near(qx, "", side, float(L)) if not xq else None
            block.append(f"✅ <b>{mk} über {L}</b> · Fair {fair:.2f} · {rule} ({100 * q:.0f} %, n={n})"
                         f"{b365_tail(bq, fair, qb is not None, near, schaetz=schaetz)}{ot}"
                         f"{b365_tail(xq, fair, qx is not None, xnear, label='1xBet') if XB_ENABLED else ''} · <i>Quote selbst prüfen</i>")
            block.append(f"   {detail}")
        lines_out += block + [""]
    if not treffer:
        lines_out.append("keine Signale in den nächsten 3 Tagen")
    text = "\n".join(lines_out)
    print("\n" + text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    (OUT / f"{SPORT_KEY}_scan_{heute:%Y-%m-%d}.txt").write_text(text, encoding="utf-8")
    print(f"\n{n_sig} Signale in {len(treffer)} Spielen · {_requests} Anfragen")
    if TG_TOKEN and TG_CHAT:
        for stueck in scan.split_message(text):
            scan.send_telegram(stueck)


def hockey_signal(hist, quoten, m, jetzt):
    """Die Gast-Abwehr-Regel als Signal im Serien-Format (oder None)."""
    home, away = m.get("home") or {}, m.get("away") or {}
    hid, aid = str(home.get("id")), str(away.get("id"))

    def letzte(tid):
        ev = [e for e in (hist.get(tid) or {}).get("events") or [] if int(e.get("time") or 0) < jetzt]
        ev.sort(key=lambda e: int(e.get("time") or 0), reverse=True)
        eigene, kass = [], []
        for e in ev:
            r = hockey_reg(e)
            if not r:
                continue
            if e.get("h"):
                eigene.append(r[0]); kass.append(r[1])
            else:
                eigene.append(r[1]); kass.append(r[0])
            if len(eigene) >= HOCKEY_N:
                break
        return eigene, kass
    h_eig, _ = letzte(hid); _, a_kas = letzte(aid)
    stufe = hockey_stufe(h_eig, a_kas)
    if not stufe:
        return None
    n, q = quoten.get(stufe, (0, 0.0))
    if n < 80:
        n, q = quoten["alle"]
    q = q * HOCKEY_SICHERHEIT
    r10 = sum(c > HOCKEY_LINIE for c in a_kas[:10])
    return (f"{home.get('name', '?')} Tore (regulär) — Gast-Abwehr-Regel", HOCKEY_LINIE, f"Stufe {stufe}", n, q,
            f"Gast kassiert Ø {st.mean(a_kas[:HOCKEY_N]):.1f} (letzte {HOCKEY_N}), {r10}/10 mit 3+ · Heim schießt Ø {st.mean(h_eig[:HOCKEY_N]):.1f}",
            "Heim", "Tore (regulär)")


# ---------------------------------------------------------------------------
# QUOTEN-PROBE (17.09.) — 1xBet-Quoten-API von BetsAPI erkunden
# Lucio: "wenn wir eine Odds-API hätten, könnten wir alle direkt vergleichen".
# BetLabel läuft auf der 1xBet-Plattform; BetsAPI liefert 1xBet-Quoten
# (/v1/1xbet/upcoming → Spiele mit our_event_id, /v1/1xbet/event → Märkte im
# 1xBet-Rohformat: Value.GE[].E[][] mit G=Gruppe, T=Wett-Typ, P=Linie,
# C=Quote; T 9/10 = Total über/unter, 11/12 bzw. 13/14 = Team-Total 1/2,
# 83/84 = 1. HZ Total). Unklar ist, wie Nebenmärkte (Ecken, Karten, Drittel,
# Viertel) auftauchen — bei 1xBet sind das eigene Unterspiele. Die Probe
# zieht deshalb Rohdaten und legt sie unter runs/ ab, damit sie hier
# ausgewertet werden können. Aufruf: python3 handball.py quoten
# ---------------------------------------------------------------------------
XB_SPORTS = {1: "Fußball", 2: "Eishockey", 3: "Basketball"}
GROSS = ("england. premier league", "germany. bundesliga", "spain. laliga", "spain. la liga", "italy. serie a",
         "france. ligue 1", "uefa champions league", "uefa europa league", "netherlands. eredivisie",
         "portugal. primeira", "turkey. super lig", "russia. premier league", "belgium. pro league",
         "scotland. premiership", "england. championship")
WUNSCH = ("corner", "yellow", "card", "1st half", "2nd half", "offside", "foul", "throw", "goal kick", "shot",
          "1st period", "2nd period", "3rd period", "1st quarter", "1 half", "2 half")


def _markt_kurz(val):
    """Kurzfassung der Total-/Team-Total-Gruppen eines 1xBet-Events."""
    out = {}
    for g in val.get("GE") or []:
        G = str(g.get("G"))
        if G in ("17", "15", "62", "6"):
            flat = [x for row in (g.get("E") or []) for x in row]
            out[G] = [(x.get("T"), x.get("P"), x.get("C")) for x in flat][:24]
    return out


def quoten_probe():
    """Stufe 2 (17.09. abends): Unterspiele (Ecken, Karten, Halbzeit, Drittel,
    Viertel) über ihre SG-Kennung abrufen — geht das über /v1/1xbet/event?"""
    heute = datetime.now(timezone.utc).date()
    tage = [(heute + timedelta(days=i)).strftime("%Y%m%d") for i in range(3)]
    raw = {"haupt": {}, "unter": {}}
    zf = []

    def upcoming_xb(sid, seiten=6):
        alle = []
        for d in tage:
            for page in range(1, seiten + 1):
                r = api_get("/v1/1xbet/upcoming", sport_id=sid, day=d, page=page)
                res = r.get("results") or []
                alle += res
                if len(res) < 50:
                    break
        return alle

    def event_xb(ids):
        return (api_get("/v1/1xbet/event", event_id=",".join(str(i) for i in ids)).get("results") or [])

    for sid, name in XB_SPORTS.items():
        try:
            alle = upcoming_xb(sid, 6 if sid == 1 else 3)
        except Exception as exc:
            zf.append(f"{name}: upcoming: {exc}"); continue
        alle = [e for e in alle if (e.get("home") or {}).get("name") not in ("Home", None)]
        if sid == 1:
            gross = [e for e in alle if any(k in ((e.get("league") or {}).get("name") or "").lower() for k in GROSS)]
            zf.append(f"{name}: {len(alle)} Spiele, davon {len(gross)} in großen Ligen: "
                      + "; ".join(f"{(e.get('home') or {}).get('name')}–{(e.get('away') or {}).get('name')} ({(e.get('league') or {}).get('name')})" for e in gross[:6]))
            kandidaten = (gross or alle)[:3]
        else:
            kandidaten = sorted(alle, key=lambda e: int(e.get("time") or 0))[:2]
        try:
            haupt = event_xb([e["id"] for e in kandidaten])
        except Exception as exc:
            zf.append(f"{name}: event: {exc}"); continue
        # our_event_id steht nur in der Spielplan-Liste, nicht in der Markt-Antwort
        bruecke = {str(e.get("id")): e.get("our_event_id") for e in alle}
        for r_ in haupt:
            r_["our_event_id"] = bruecke.get(str(r_.get("id")))
        raw["haupt"][sid] = haupt
        for r_ in haupt:
            val = r_.get("Value") or {}
            sg = val.get("SG") or []
            namen = [(x.get("PN") or "?", x.get("I")) for x in sg]
            zf.append(f"   {name} {(r_.get('home') or {}).get('name')} – {(r_.get('away') or {}).get('name')} "
                      f"[{(r_.get('league') or {}).get('name')}] our_event_id={r_.get('our_event_id')} · Unterspiele: {namen}")
            zf.append(f"      Hauptmärkte: {json.dumps(_markt_kurz(val))[:500]}")
            wahl = [x for x in sg if any(k in ((x.get("TG") or "") + " " + (x.get("PN") or "")).lower() for k in WUNSCH)][:8]
            if not wahl:
                continue
            try:
                unter = event_xb([x["I"] for x in wahl])
                if not unter:
                    zf.append("      Unterspiele über /v1/1xbet/event nicht abrufbar (0 Ergebnisse; "
                              "Zusatzparameter werden ignoriert — am 17.09. geprüft)")
            except Exception as exc:
                zf.append(f"      Unterspiel-Abruf: {exc}"); continue
            raw["unter"][str(r_.get("id"))] = unter
            for u in unter:
                uv = u.get("Value") or {}
                zf.append(f"      ↳ Unterspiel {u.get('id')} PN={uv.get('PN')!r} N={uv.get('N')} TG={uv.get('TG')!r} "
                          f"SN={uv.get('SN')!r} keys={sorted(uv.keys())[:12]}")
                zf.append(f"         Märkte: {json.dumps(_markt_kurz(uv))[:600]}")
    # Stufe 3: liefert die Sport-API selbst 1xBet-Quoten (odds_summary / event/odds)?
    raw["summary"] = {}; raw["odds"] = {}
    for sid, haupt in raw["haupt"].items():
        for r_ in haupt[:2]:
            oid = r_.get("our_event_id")
            if not oid:
                continue
            try:
                summ = api_get("/v1/event/odds_summary", event_id=oid)
                res = summ.get("results") or {}
                raw["summary"][str(oid)] = res
                bk = {b: sorted((n.get("odds") or {}).keys()) for b, n in res.items() if isinstance(n, dict)}
                zf.append(f"   odds_summary {oid} ({(r_.get('home') or {}).get('name')} – {(r_.get('away') or {}).get('name')}): "
                          + "; ".join(f"{b}: {', '.join(m)}" for b, m in bk.items()))
                for b, n in res.items():
                    if isinstance(n, dict) and ("1x" in b.lower() or "xbet" in b.lower()):
                        zf.append(f"      {b} Rohdaten: {json.dumps(n)[:700]}")
            except Exception as exc:
                zf.append(f"   odds_summary {oid}: {exc}")
            try:
                od = api_get("/v2/event/odds", event_id=oid)
                res = od.get("results") or {}
                raw["odds"][str(oid)] = res
                mk = {k: len(v) for k, v in (res.get("odds") or {}).items()}
                first = {k: v[0] for k, v in (res.get("odds") or {}).items() if v}
                zf.append(f"   event/odds {oid}: Märkte {mk} · Beispiel {json.dumps(first)[:500]}")
            except Exception as exc:
                zf.append(f"   event/odds {oid}: {exc}")
    # Stufe 4 (17.09., Lucio: "bet365 ist der Maßstab — wenn es da nichts gibt,
    # dann nirgendwo"): voller bet365-Marktkatalog je Spiel (/v1/bet365/prematch).
    raw["b365"] = {}
    B365_SPORT = {1: "Fußball", 17: "Eishockey", 18: "Basketball"}

    def walk(node, out, pfad="", depth=0):
        """Alle Märkte einer bet365-Prematch-Antwort: Abschnitt → Marktname → Beispiel-Quoten."""
        if depth > 8:
            return
        if isinstance(node, dict):
            sp = node.get("sp")
            if isinstance(sp, dict):
                for mk, mv in sp.items():
                    if isinstance(mv, dict):
                        odds = mv.get("odds") or []
                        bsp = [(o.get("name"), o.get("header"), o.get("handicap"), o.get("odds")) for o in odds[:6] if isinstance(o, dict)]
                        out.append((pfad, mv.get("name") or mk, len(odds), bsp))
                    elif isinstance(mv, list):
                        out.append((pfad, mk, len(mv), [(o.get("name"), o.get("header"), o.get("handicap"), o.get("odds")) for o in mv[:6] if isinstance(o, dict)]))
            for k, v in node.items():
                if k != "sp":
                    walk(v, out, f"{pfad}/{k}" if pfad else str(k), depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, out, pfad, depth + 1)

    for sid, name in B365_SPORT.items():
        try:
            alle = []
            for d in tage[:2]:
                for page in (1, 2, 3):
                    r = api_get("/v1/bet365/upcoming", sport_id=sid, day=d, page=page)
                    res = r.get("results") or []
                    alle += res
                    if len(res) < 50:
                        break
        except Exception as exc:
            zf.append(f"bet365 {name}: upcoming: {exc}"); continue
        if sid == 1:
            gross = [e for e in alle if any(k in ((e.get("league") or {}).get("name") or "").lower().replace(" - ", ". ")
                                             for k in ("premier league", "bundesliga", "laliga", "la liga", "serie a", "ligue 1", "champions league", "europa league", "eredivisie", "championship", "russia"))]
            kand = (gross or alle)[:3]
        else:
            kand = sorted(alle, key=lambda e: int(e.get("time") or 0))[:2]
        zf.append(f"bet365 {name}: {len(alle)} Spiele (2 Tage), {sum(1 for e in alle if e.get('our_event_id'))} mit our_event_id; Beispiele: "
                  + "; ".join(f"{(e.get('home') or {}).get('name')}–{(e.get('away') or {}).get('name')} [{(e.get('league') or {}).get('name')}] FI={e.get('id')} our={e.get('our_event_id')}" for e in kand))
        for e in kand:
            try:
                pm = api_get("/v1/bet365/prematch", FI=e.get("id"))
            except Exception as exc:
                zf.append(f"   prematch FI={e.get('id')}: {exc}"); continue
            raw["b365"][str(e.get("id"))] = pm
            maerkte = []
            walk(pm.get("results") or [], maerkte)
            zf.append(f"   {(e.get('home') or {}).get('name')} – {(e.get('away') or {}).get('name')}: {len(maerkte)} Märkte, Abschnitte: "
                      + ", ".join(sorted({m[0].split('/')[0] for m in maerkte})))
            for pfad, mname, n, bsp in maerkte:
                low = (str(pfad) + " " + str(mname)).lower()
                if any(k in low for k in ("corner", "card", "booking", "shot", "offside", "foul", "throw", "goal kick", "goal_kick", "total", "team")):
                    zf.append(f"      [{pfad}] {mname} ({n}): {bsp}")
    OUT.mkdir(exist_ok=True)
    (OUT / f"quoten_probe2_{heute:%Y-%m-%d}.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    text = "\n".join(zf)
    (OUT / f"quoten_probe2_{heute:%Y-%m-%d}.txt").write_text(text, encoding="utf-8")
    print(text)
    print(f"\n{_requests} Anfragen")


# ---------------------------------------------------------------------------
# SPORTARTEN-RUNDGANG (22.09.) — Lucio: "haben wir Quoten mit in der API, will
# dass du alle Sportarten mal abklapperst". Für JEDE Sportart von BetsAPI:
#   1) wie viele Spiele stehen morgen an?
#   2) führt bet365 sie (Brücke über /v1/bet365/upcoming)?
#   3) welche Marktfamilien liefert der bet365-Prematch-Katalog?
#   4) welche Statistikfelder liefert ein beendetes Spiel (= worauf könnte
#      eine Serien-Regel überhaupt aufsetzen)?
# Kostet rund 10 Anfragen je Sportart. Aufruf: python3 handball.py sportarten
# ---------------------------------------------------------------------------
ALLE_SPORTS = [(1, "Fußball"), (18, "Basketball"), (13, "Tennis"), (17, "Eishockey"),
               (16, "Baseball"), (12, "American Football"), (78, "Handball"),
               (91, "Volleyball"), (92, "Tischtennis"), (3, "Cricket"),
               (8, "Rugby Union"), (19, "Rugby League"), (36, "Aussie Rules"),
               (75, "Darts"), (14, "Snooker"), (94, "Badminton"),
               (95, "Beachvolleyball"), (107, "Wasserball"), (110, "Bowls"),
               (162, "MMA"), (151, "E-Sports"), (66, "Futsal")]


def sportarten_rundgang():
    # 22.09. (Lucio): HEUTE prüfen, nicht morgen — für morgige Spiele sind die
    # Nebenmärkte oft noch gar nicht veröffentlicht, die Abdeckung sähe dann
    # künstlich schlecht aus. Mit dem Feld "datum" lässt sich ein anderer Tag
    # setzen (JJJJMMTT).
    tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    for a in sys.argv[2:]:
        if re.fullmatch(r"\d{8}", a.strip()):
            tag = a.strip()
    zeilen = ["🔎 SPORTARTEN-RUNDGANG — was liefert die API je Sportart?",
              f"Stichtag {tag} · Quellen: /v3/events/upcoming, /v1/bet365/upcoming,"
              f" /v1/bet365/prematch, /v3/events/ended + /v1/event/view", ""]
    b365 = os.environ.get("BETSAPI_TOKEN_B365") or TOKEN
    for sid, name in ALLE_SPORTS:
        try:
            up = api_get("/v3/events/upcoming", sport_id=sid, day=tag, page=1)
            n_up = int((up.get("pager") or {}).get("total") or len(up.get("results") or []))
        except Exception as exc:
            zeilen.append(f"{name:18} — kein Zugriff ({str(exc)[:60]})"); continue
        if not n_up:
            zeilen.append(f"{name:18} — morgen keine Spiele"); continue
        # bet365-Brücke
        n_b365, maerkte = 0, Counter()
        try:
            bl = api_get("/v1/bet365/upcoming", sport_id=sid, day=tag, page=1, _token=b365)
            res = bl.get("results") or []
            n_b365 = int((bl.get("pager") or {}).get("total") or len(res))
            for ev in res[:3]:
                fi = ev.get("bet365_id") or ev.get("id")
                try:
                    pm = api_get("/v1/bet365/prematch", FI=fi, _token=b365)
                    for blk in (pm.get("results") or []):
                        for sec in (blk if isinstance(blk, list) else [blk]):
                            for k in (sec.get("sp") or {}):
                                maerkte[k] += 1
                except Exception:
                    pass
        except Exception as exc:
            zeilen.append(f"{name:18} {n_up:5} Spiele · bet365: kein Zugriff ({str(exc)[:40]})"); continue
        # Statistikfelder eines beendeten Spiels
        felder = set()
        try:
            gestern = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
            en = api_get("/v3/events/ended", sport_id=sid, day=gestern, page=1).get("results") or []
            for ev in en[:2]:
                v = api_get("/v1/event/view", event_id=ev.get("id")).get("results") or []
                for e in v:
                    felder |= set((e.get("stats") or {}).keys())
                    if e.get("scores"): felder.add("scores/Abschnitte")
        except Exception:
            pass
        top = ", ".join(k for k, _ in maerkte.most_common(12)) or "—"
        zeilen.append(f"{name:18} {n_up:5} Spiele · bet365 {n_b365:5}")
        zeilen.append(f"   Märkte: {top[:260]}")
        zeilen.append(f"   Statistik: {', '.join(sorted(felder)[:16]) or '—'}")
        zeilen.append("")
        print(zeilen[-4], flush=True)
    txt = "\n".join(zeilen)
    print(txt)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"sportarten_{datetime.now(timezone.utc):%Y-%m-%d}.txt").write_text(txt, encoding="utf-8")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("scan", Path(__file__).parent / "scan.py")
        scan = importlib.util.module_from_spec(spec); spec.loader.exec_module(scan)
        for teil in scan.split_message("<pre>" + scan.esc(txt) + "</pre>"):
            scan.send_telegram(teil)
    except Exception as exc:
        print("Telegram:", exc)


def regel_modus():
    """22.09.: Die Eishockey-Gast-Abwehr-Regel gegen echte Daten nachrechnen —
    einmal über das ganze geladene Fenster und einmal getrennt ab dem Stichtag,
    an dem die Regel festgelegt wurde (17.09.). Alles ab dem Stichtag ist
    echter Nachtest, davor ist es der Backtest, aus dem sie stammt.
    Aufruf: SPORT=eishockey python3 handball.py regel [stichtag JJJJ-MM-TT]
    Braucht eine Historie aus dem Erkundungs-Lauf (runs/eishockey_historie_*.json).
    """
    hfiles = sorted(OUT.glob("eishockey_historie_*.json"))
    if not hfiles:
        sys.exit("keine Eishockey-Historie in runs/ — erst den Modus 'eishockey' laufen lassen")
    hist = json.loads(hfiles[-1].read_text(encoding="utf-8"))
    stich = "2026-09-17"
    for a in sys.argv[2:]:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.strip()):
            stich = a.strip()
    grenze = int(datetime.strptime(stich, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    games = hockey_spiele(hist)
    faelle = hockey_faelle(games)
    zeiten = [g["t"] for g in games.values() if g["t"]]
    lines = [f"🏒 <b>EISHOCKEY — Gast-Abwehr-Regel nachgerechnet</b>",
             f"Quelle: {hfiles[-1].name} · {len(hist)} Teams · {len(games)} Spiele",
             (f"Zeitraum: {datetime.fromtimestamp(min(zeiten), timezone.utc):%d.%m.} – "
              f"{datetime.fromtimestamp(max(zeiten), timezone.utc):%d.%m.%Y}" if zeiten else ""),
             f"Regel: Heim über {HOCKEY_LINIE} eigene Tore (reguläre Zeit), "
             f"Stufe A = Gast kassiert Ø ≥ {HOCKEY_GAST_A}; Stufe B = Ø ≥ {HOCKEY_GAST_B} "
             f"bzw. 9/10 mit 3+ und Heim Ø ≥ {HOCKEY_HEIM_B}", ""]
    for label, teil in (("GESAMT", faelle),
                        (f"bis {stich} (Backtest)", [f for f in faelle if f["t"] < grenze]),
                        (f"ab {stich} (Nachtest)", [f for f in faelle if f["t"] >= grenze])):
        q = hockey_quoten(teil)
        lines.append(f"<b>{label}</b> · {len(teil)} Signale")
        for k in ("A", "B", "alle"):
            n, p = q.get(k, (0, 0.0))
            if n:
                fair = 1 / p if p else 0
                lines.append(f"   Stufe {k}: n={n}  {100 * p:.1f} %  → fair {fair:.2f}" if p
                             else f"   Stufe {k}: n={n}  0 %")
            else:
                lines.append(f"   Stufe {k}: keine Fälle")
        lines.append("")
    txt = "\n".join(lines)
    print(re.sub(r"<[^>]+>", "", txt))
    (OUT / f"eishockey_regel_{datetime.now(timezone.utc):%Y-%m-%d}.txt").write_text(
        re.sub(r"<[^>]+>", "", txt), encoding="utf-8")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("scan", Path(__file__).parent / "scan.py")
        scan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scan)
        scan.send_telegram(txt)
    except Exception as exc:
        print("Telegram:", exc)


def main():
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "sportarten":
        if not TOKEN:
            sys.exit("BETSAPI_TOKEN fehlt")
        sportarten_rundgang()
        return
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "regel":
        regel_modus()
        return
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "quoten":
        if not TOKEN:
            sys.exit("BETSAPI_TOKEN fehlt")
        quoten_probe()
        return
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "liga":
        if not TOKEN:
            sys.exit("BETSAPI_TOKEN fehlt")
        liga_modus()
        return
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "stats":
        if not TOKEN:
            sys.exit("BETSAPI_TOKEN fehlt")
        stats_modus()
        return
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "scan":
        if not TOKEN:
            sys.exit("BETSAPI_TOKEN fehlt")
        if SPORT_KEY in SERIEN:
            serien_scan()            # 17.09.: Serien-Regel, reine Trefferquote, alle drei Sportarten
            return
        sys.exit("der Scan-Modus gibt es für Handball, Eishockey und Basketball")
    if not TOKEN:
        sys.exit("BETSAPI_TOKEN fehlt — ist das Repository-Secret gesetzt?")
    wochen = wochen_aus_argv()
    tage = wochen * 7

    # Probelauf: liefert der Zugang Handball überhaupt? Lieber hier mit einer
    # klaren Meldung scheitern als 28-mal dieselbe Fehlerzeile drucken.
    probe_tag = (datetime.now(timezone.utc).date() - timedelta(days=1)).strftime("%Y%m%d")
    try:
        d = api_get("/v3/events/ended", sport_id=SPORT_HANDBALL, day=probe_tag, page=1)
        n = len(d.get("results") or [])
        print(f"Probelauf ok: {n} {SPORT['name']}-Spiele am {probe_tag}", flush=True)
        if n == 0:
            print("  (null Spiele an einem einzelnen Tag ist normal, weiter geht es)",
                  flush=True)
    except Exception as exc:
        print(f"\nProbelauf fehlgeschlagen: {exc}")
        print("Mögliche Ursachen:")
        print("  - der API-Zugang umfasst nur Fußball (BetsAPI verkauft je Sportart)")
        print("  - das Stundenlimit ist voll, weil der Fußball-Scanner gerade lief")
        sys.exit("Abbruch — ohne Handball-Daten hat der Lauf keinen Zweck.")
    heute = datetime.now(timezone.utc).date()
    days = [(heute - timedelta(days=i + 1)).strftime("%Y%m%d") for i in range(tage)]

    print(f"{SPORT['name']}-Abdeckung: {wochen} Wochen ({tage} Tage), {WORKERS} Worker", flush=True)
    events = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(ended_day, d): d for d in days}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                events += f.result()
            except BudgetExhausted:
                print("Budget erschöpft, breche das Einsammeln ab", flush=True)
                break
            except Exception as exc:
                print(f"  Tag {futs[f]}: {exc}", flush=True)
            if i % 7 == 0:
                print(f"  ... {i}/{len(days)} Tage, {len(events)} Spiele, "
                      f"{_requests} Anfragen", flush=True)
    print(f"{len(events)} beendete Spiele eingesammelt ({_requests} Anfragen)", flush=True)

    # --- je Liga auswerten -------------------------------------------------
    liga = defaultdict(lambda: {"n": 0, "mit_endstand": 0, "mit_hz": 0,
                                "totals": [], "hz_totals": [], "wochen": Counter(),
                                "id": None})
    for ev in events:
        lg = (ev.get("league") or {})
        key = lg.get("name") or "?"
        d = liga[key]
        d["id"] = lg.get("id")
        d["n"] += 1
        ts = int(ev.get("time") or 0)
        if ts:
            d["wochen"][datetime.fromtimestamp(ts, timezone.utc).isocalendar()[1]] += 1
        sc = final_score(ev)
        if sc:
            d["mit_endstand"] += 1
            d["totals"].append(sc[0] + sc[1])
        ht = half_time(ev)
        if ht:
            d["mit_hz"] += 1
            d["hz_totals"].append(ht[0] + ht[1])

    # --- Stichprobe: gibt es einen Statistikblock? --------------------------
    probe_ids = [ev["id"] for ev in events[:12] if ev.get("id")]
    stat_felder = Counter()
    beispiel = None
    def _view(eid):
        return (api_get("/v1/event/view", event_id=eid).get("results") or [None])[0]
    with ThreadPoolExecutor(max_workers=12) as pool:
        for f in as_completed([pool.submit(_view, e) for e in probe_ids]):
            try:
                r = f.result()
            except Exception:
                continue
            if not r:
                continue
            stats = r.get("stats") or {}
            for k in stats:
                stat_felder[k] += 1
            if stats and beispiel is None:
                beispiel = (r.get("league", {}).get("name"), dict(list(stats.items())[:12]))

    # --- Bericht -----------------------------------------------------------
    L = []
    L.append(f"{SPORT['name'].upper()}-ABDECKUNG · {wochen} Wochen · Stand {heute:%d.%m.%Y}")
    L.append(f"{len(events)} beendete Spiele · {len(liga)} Ligen · {_requests} API-Anfragen")
    L.append("")
    L.append("1) STATISTIKFELDER (Stichprobe aus 12 Spielen über /v1/event/view)")
    if stat_felder:
        for k, c in stat_felder.most_common():
            L.append(f"   {k}: {c}/{len(probe_ids)}")
        if beispiel:
            L.append(f"   Beispiel ({beispiel[0]}): {json.dumps(beispiel[1], ensure_ascii=False)[:300]}")
    else:
        L.append("   KEINE — Handball liefert nur Spielstände, keine Statistiken.")
        L.append("   Heißt: Tore-Totals sind die einzige Zählgröße. Mehr geht nicht.")
    L.append("")
    L.append("2) LIGEN mit mindestens 20 Spielen, nach Spielzahl")
    ab = SPORT["abschnitt_name"]
    L.append(f"   {'Liga':38s} {'Spiele':>6} {'Wo':>3} {'Endst.':>7} {ab:>6} "
             f"{'Ø Pkt':>7} {'SD':>5} {'Ø '+ab:>7}")
    gross = sorted((d for d in liga.items() if d[1]["n"] >= 20),
                   key=lambda x: -x[1]["n"])
    for name, d in gross:
        t = d["totals"]
        if not t:
            continue
        sd = st.pstdev(t) if len(t) > 1 else 0
        hz = f"{st.mean(d['hz_totals']):6.1f}" if d["hz_totals"] else "     –"
        L.append(f"   {name[:38]:38s} {d['n']:6d} {len(d['wochen']):3d} "
                 f"{100*d['mit_endstand']/d['n']:6.0f}% {100*d['mit_hz']/d['n']:5.0f}% "
                 f"{st.mean(t):7.1f} {sd:5.2f} {hz}")
    L.append("")
    L.append("3) GRUNDRATEN je Liga (Anteil der Spiele ÜBER der Linie)")
    L.append("   Nur Ligen mit mindestens 30 Spielen und Daten in allen Wochen.")
    for name, d in gross:
        t = d["totals"]
        if len(t) < 30 or len(d["wochen"]) < wochen:
            continue
        m = st.mean(t)
        sd = st.pstdev(t) if len(t) > 1 else 1.0
        # Linien rund um den Ligaschnitt, Schrittweite ~ ein Drittel Streuung
        step = max(1, round(sd / 3))
        basis = round(m / step) * step
        linien = [basis + k * step + 0.5 for k in range(-3, 4)]
        teile = " · ".join(f"{ln:.1f}: {100*sum(1 for x in t if x > ln)/len(t):.0f}%"
                           for ln in linien)
        L.append(f"   {name[:36]:36s} (n={len(t)}, Ø {m:.1f}) {teile}")
    L.append("")
    L.append("4) WOCHENVERTEILUNG — wann wird gespielt?")
    wd = Counter()
    for ev in events:
        ts = int(ev.get("time") or 0)
        if ts:
            wd[datetime.fromtimestamp(ts, timezone.utc).weekday()] += 1
    namen = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    ges = sum(wd.values()) or 1
    L.append("   " + " · ".join(f"{namen[i]} {wd.get(i,0)} ({100*wd.get(i,0)/ges:.0f}%)"
                                for i in range(7)))
    bericht = "\n".join(L)
    print("\n" + bericht)

    OUT.mkdir(exist_ok=True)
    pfad = OUT / f"{SPORT_KEY}_abdeckung_{heute:%Y-%m-%d}.txt"
    pfad.write_text(bericht, encoding="utf-8")
    print(f"\ngespeichert: {pfad}")

    # Rohdaten für die spätere Auswertung — je Spiel eine Zeile
    roh = OUT / f"{SPORT_KEY}_spiele_{heute:%Y-%m-%d}.json"
    schlank = []
    for ev in events:
        sc = final_score(ev)
        ht = half_time(ev)
        schlank.append({"id": ev.get("id"), "time": ev.get("time"),
                        "liga": (ev.get("league") or {}).get("name"),
                        "liga_id": (ev.get("league") or {}).get("id"),
                        "heim": (ev.get("home") or {}).get("name"),
                        "heim_id": (ev.get("home") or {}).get("id"),
                        "gast": (ev.get("away") or {}).get("name"),
                        "gast_id": (ev.get("away") or {}).get("id"),
                        "tore": list(sc) if sc else None,
                        "hz": list(ht) if ht else None})
    roh.write_text(json.dumps(schlank, ensure_ascii=False), encoding="utf-8")
    print(f"gespeichert: {roh} ({len(schlank)} Spiele)")

    # --- Schritt 2: Historien aller Teams der brauchbaren Ligen ----------------
    # "brauchbar" hier bewusst weit: mindestens 20 Spiele im Fenster. Die
    # strengere Abdeckungsregel (alle Wochen, Endstand) legen wir später
    # offline an — die Daten kosten jetzt einen Dollar, später zehn im Monat.
    ziel_ligen = {name for name, d in liga.items() if d["n"] >= 20}
    teams = {}
    for ev in events:
        if ((ev.get("league") or {}).get("name") or "?") not in ziel_ligen:
            continue
        for side in ("home", "away"):
            t = ev.get(side) or {}
            if t.get("id"):
                teams[str(t["id"])] = t.get("name") or "?"
    # Wiederaufnahme (17.09.): ist von heute schon eine Historie da, werden nur
    # die Teams geholt, die darin fehlen. So kostet ein zweiter Lauf nach dem
    # Stundenlimit nur den Rest — und nicht nochmal alles.
    hpfad = OUT / f"{SPORT_KEY}_historie_{heute:%Y-%m-%d}.json"
    hist = {}
    if hpfad.exists():
        try:
            hist = json.loads(hpfad.read_text(encoding="utf-8"))
            print(f"Wiederaufnahme: {len(hist)} Teams schon vorhanden aus {hpfad.name}", flush=True)
        except Exception:
            hist = {}
    def _komplett(tid):
        ev = (hist.get(tid) or {}).get("events") or []
        return bool(ev) and "perioden" in ev[0]
    fehlend = {tid: n for tid, n in teams.items() if not _komplett(tid)}
    print(f"\nSchritt 2: Historien für {len(fehlend)} von {len(teams)} Teams aus "
          f"{len(ziel_ligen)} Ligen (je 1–2 Anfragen)", flush=True)
    knapp = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(team_history, tid): tid for tid in fehlend}
        for i, f in enumerate(as_completed(futs), 1):
            tid = futs[f]
            try:
                hist[tid] = {"name": teams[tid], "events": f.result()}
            except BudgetExhausted:
                # NICHT abbrechen: die schon fertigen Ergebnisse weiter
                # einsammeln, die restlichen scheitern ohnehin sofort.
                knapp += 1
            except Exception as exc:
                print(f"  Team {teams[tid]}: {exc}", flush=True)
            if i % 100 == 0:
                print(f"  ... {i}/{len(teams)} Teams, {_requests} Anfragen", flush=True)
    if knapp:
        print(f"Stundenlimit erreicht: {knapp} Teams ohne Historie — gespeichert wird, "
              f"was da ist; ein zweiter Lauf in der nächsten Stunde holt den Rest.",
              flush=True)
    hpfad.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    n_ev = sum(len(v["events"]) for v in hist.values())
    mit_hz = sum(1 for v in hist.values() for e in v["events"] if e.get("hz"))
    print(f"gespeichert: {hpfad} — {len(hist)} Teams, {n_ev} Spiele, "
          f"{mit_hz} davon mit Halbzeitstand, {_requests} Anfragen gesamt")
    bericht += (f"\n\n5) HISTORIEN: {len(hist)} Teams · {n_ev} Spiele · "
                f"{mit_hz} mit Halbzeitstand · {_requests} Anfragen gesamt")

    if TG_TOKEN and TG_CHAT:
        kopf = f"<b>{SPORT['name'].upper()} — Abdeckung</b>\n<pre>"
        rest = bericht
        teile, grenze = [], 3500
        while rest:
            stueck, rest = rest[:grenze], rest[grenze:]
            teile.append(stueck)
        for i, stueck in enumerate(teile, 1):
            txt = (kopf if i == 1 else "<pre>") + stueck.replace("&", "&amp;") \
                .replace("<", "&lt;").replace(">", "&gt;") + "</pre>"
            try:
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                    data=urllib.parse.urlencode(
                        {"chat_id": TG_CHAT, "text": txt, "parse_mode": "HTML"}
                    ).encode(), method="POST")
                urllib.request.urlopen(req, timeout=30).read()
            except Exception as exc:
                print(f"Telegram: {exc}")


if __name__ == "__main__":
    main()
