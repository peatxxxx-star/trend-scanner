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
    params["token"] = TOKEN
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
# Aufruf: SPORT=eishockey python3 handball.py scan
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


def hockey_backtest(games: dict) -> dict:
    """Trefferquote der Regel je Stufe aus der Historie: {'A': (n, quote), 'B': …, 'alle': …}."""
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


def eishockey_scan():
    import importlib.util
    spec = importlib.util.spec_from_file_location("scan", Path(__file__).parent / "scan.py")
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)

    hfiles = sorted(OUT.glob("eishockey_historie_*.json"))
    if not hfiles:
        sys.exit("keine Eishockey-Historie gefunden — erst den Erkundungslauf machen")
    hist = json.loads(hfiles[-1].read_text(encoding="utf-8"))
    print(f"Historie: {hfiles[-1].name}, {len(hist)} Teams", flush=True)

    # 1) Regel auf der Historie nachrechnen — daraus kommen die fairen Quoten
    games = hockey_spiele(hist)
    quoten = hockey_backtest(games)
    print(f"Regel-Backtest auf {len(games)} Spielen:", flush=True)
    for k in ("A", "B", "alle"):
        n, q = quoten.get(k, (0, 0.0))
        print(f"   Stufe {k}: n={n}  {100 * q:.1f} %", flush=True)
    if quoten.get("alle", (0, 0))[0] < 200:
        sys.exit("zu wenig Spiele für die Regel — Historie zu dünn")

    # 2) anstehende Spiele
    heute = datetime.now(timezone.utc).date()
    tage = [(heute + timedelta(days=i)).strftime("%Y%m%d") for i in range(SCAN_TAGE)]
    spiele = []
    for d in tage:
        try:
            spiele += upcoming(d)
        except Exception as exc:
            print(f"  upcoming {d}: {exc}", flush=True)
    jetzt = int(time.time())
    spiele = [m for m in spiele if not is_junk(m) and int(m.get("time") or 0) > jetzt
              and not any(k in ((m.get("league") or {}).get("name") or "").lower() for k in HOCKEY_LIGA_RAUS)]
    print(f"{len(spiele)} anstehende Spiele (ohne Testspiele/E-Sport)", flush=True)

    # 3) Historien nur für Teams holen, die noch fehlen (die Datei ist von heute)
    ids = {}
    for m in spiele:
        for side in ("home", "away"):
            t = m.get(side) or {}
            if t.get("id"):
                ids[str(t["id"])] = t.get("name") or "?"
    fehlt = [tid for tid in ids if tid not in hist]
    print(f"{len(ids)} Teams beteiligt, {len(fehlt)} ohne Historie → werden geholt", flush=True)
    if fehlt:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = {pool.submit(team_history, tid): tid for tid in fehlt}
            for f in as_completed(futs):
                tid = futs[f]
                try:
                    hist[tid] = {"name": ids[tid], "events": f.result()}
                except BudgetExhausted:
                    print("  Stundenbudget erschöpft — Rest ohne Historie", flush=True)
                except Exception as exc:
                    print(f"  Team {ids[tid]}: {exc}", flush=True)
        print(f"Historien geholt ({_requests} Anfragen)", flush=True)

    def letzte(tid: str):
        """Reguläre Endstände der letzten HOCKEY_N Spiele eines Teams als
        (eigene, kassiert), neueste zuerst — nur Spiele vor jetzt."""
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

    # 4) Regel anwenden
    treffer = []
    for m in spiele:
        home, away = m.get("home") or {}, m.get("away") or {}
        hid, aid = str(home.get("id")), str(away.get("id"))
        h_eig, _ = letzte(hid)
        _, a_kas = letzte(aid)
        stufe = hockey_stufe(h_eig, a_kas)
        if not stufe:
            continue
        n, q = quoten.get(stufe, (0, 0.0))
        if n < 80:
            n, q = quoten["alle"]
        p = q * HOCKEY_SICHERHEIT
        treffer.append({"m": m, "liga": (m.get("league") or {}).get("name") or "?",
                        "stufe": stufe, "n": n, "q": q, "fair": 1 / p if p else 0.0,
                        "mu_s": st.mean(h_eig[:HOCKEY_N]), "mu_d": st.mean(a_kas[:HOCKEY_N]),
                        "r10": sum(c > HOCKEY_LINIE for c in a_kas[:10]),
                        "top": hockey_top((m.get("league") or {}).get("name"))})

    # 5) Nachricht: Zeit zuerst, gleiche Zeit nach Liga, dann Heimteam
    def ts(m):
        return int(m.get("time") or 0)
    treffer.sort(key=lambda x: (ts(x["m"]), x["liga"].lower(), (x["m"].get("home") or {}).get("name", "")))
    berlin = timezone(timedelta(hours=2))
    WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    n_a, q_a = quoten.get("A", (0, 0.0)); n_b, q_b = quoten.get("B", (0, 0.0))
    lines_out = ["🏒 <b>EISHOCKEY-SCAN</b> · nächste 3 Tage · 🧪 <i>Test</i>",
                 f"<i>Regel: Heim über {HOCKEY_LINIE} eigene Tore (reguläre Zeit) gegen löchrige Gast-Abwehr · "
                 f"Backtest A {100 * q_a:.0f} % ({n_a}) · B {100 * q_b:.0f} % ({n_b})</i>", ""]
    for x in treffer:
        m = x["m"]
        t = datetime.fromtimestamp(ts(m), berlin)
        home = (m.get("home") or {}).get("name", "?"); away = (m.get("away") or {}).get("name", "?")
        lines_out += [f"🏒 <b>{scan.esc(home)} – {scan.esc(away)}</b>",
                      f"🕒 {WD[t.weekday()]} {t:%H:%M} · {scan.esc(x['liga'])}{' · ⭐ Topliga' if x['top'] else ''}",
                      f"✅ <b>{scan.esc(home)} über {HOCKEY_LINIE} Tore</b> · Fair {x['fair']:.2f}"
                      f" · Stufe {x['stufe']} · <i>Quote selbst prüfen</i>",
                      f"   Gast kassiert Ø {x['mu_d']:.1f} (letzte {HOCKEY_N}), {x['r10']}/10 mit 3+"
                      f" · Heim schießt Ø {x['mu_s']:.1f}",
                      ""]
    if not treffer:
        lines_out.append("keine Signale in den nächsten 3 Tagen")
    text = "\n".join(lines_out)
    print("\n" + text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    OUT.mkdir(exist_ok=True)
    (OUT / f"eishockey_scan_{heute:%Y-%m-%d}.txt").write_text(text, encoding="utf-8")
    print(f"\n{len(treffer)} Signale in {len(spiele)} Spielen · {_requests} Anfragen")
    if TG_TOKEN and TG_CHAT:
        for stueck in scan.split_message(text):
            scan.send_telegram(stueck)


def main():
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
        if SPORT_KEY == "eishockey":
            eishockey_scan()
            return
        if SPORT_KEY != "handball":
            sys.exit("der Scan-Modus gibt es bisher nur für Handball und Eishockey")
        scan_modus()
        return
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
