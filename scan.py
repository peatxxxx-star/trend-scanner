#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fußball-Trend-Scanner (BetsAPI Soccer API) — Regelwerk V2
=========================================================
Findet Spiele, bei denen BEIDE Teams denselben Gesamtmarkt-Trend zeigen
(Ecken, Gelbe Karten, Schüsse aufs Tor, Abseits, Fouls) und meldet
Treffer per Telegram.

REGELWERK (vollständig):

  Zeitfenster je Lauf (Läufe 6/8/10/.../22 Uhr deutscher Zeit):
    * normaler Lauf:  alle Spiele mit Anpfiff ab JETZT bis 24:00 Uhr
    * 22-Uhr-Lauf:    alle Spiele mit Anpfiff ab JETZT bis 06:00 Uhr früh

  Märkte: nur Gesamtmärkte (Summe beider Teams), nie teambezogen.
  Head-to-Head spielt keine Rolle. Seit 05.09. zusätzlich Halbzeit-Märkte:
  1. HZ Ecken (API-Feld corner_h) und 1. HZ Gelbe Karten (aus dem
  Ereignis-Verlauf); beide ohne Quoten-Nachweis (Bookie führt die Märkte).
  "unter Ecken" ist in beiden Varianten ausgeschlossen.

  Serien-Definition (vom jüngsten Spiel rückwärts gezählt, maximal
  2 Aussetzer — bei 3 Lücken ist die Serie gebrochen und zählt nicht):
    * ANKER gesamt:        >= 10 Treffer, max. 2 Aussetzer,
                           alle Wettbewerbe, ohne Heim/Auswärts-Filter
    * ANKER Heim/Auswärts: >= 15 Treffer, max. 2 Aussetzer, nur Spiele
                           in der HEUTIGEN Rolle des Teams (Heimteam ->
                           seine Heimspiele, Auswärtsteam -> Auswärtsspiele)
    * FRISCHE-REGEL (nur für Anker-Serien): liegt ein Aussetzer in den
      jüngsten 2 gewerteten Spielen der Serie, ist die Serie ungültig.
    * ZWEITES TEAM: >= 5 Treffer, max. 1 Aussetzer — wahlweise aus der
      Gesamt-Serie ODER der Serie seiner heutigen Rolle; die
      Frische-Regel gilt hier NICHT.

  Signal: beide Teams erfüllen dieselbe Linie in dieselbe Richtung und
  mindestens eines der beiden Teams hat eine Anker-Serie.
  Je Metrik/Richtung wird nur die strengste qualifizierende Linie
  gemeldet (über: höchste, unter: niedrigste).

  Gegenläufigkeits-Filter: hat auch nur EINES der beiden Teams in der
  Gegenrichtung eine Serie (kleine Serie reicht) an einer Linie im engen
  Korridor (Abstand <= CONTRA_GAP), wird das Signal verworfen. Breite
  Korridore (z.B. über 6,5 + unter 12,5) sind legitim.

  Datenqualität: fehlende Statistik -> Spiel zählt für die Metrik nicht
  (weder Treffer noch Aussetzer). Fouls 0:0 gilt als "nicht erfasst"
  und macht Fouls UND Abseits des Spiels ungültig; Schüsse aufs Tor 0:0
  ebenso für diese Metrik. Ein Team braucht je Metrik mindestens
  MIN_VALID_MATCHES saubere Spiele in der Gesamt-Historie, sonst gibt
  es für die Metrik kein Signal. Meldungen zeigen immer die Datenbasis.

  Beitrags-Modell (05.09.): Erwartung = Mittel aus Summen-Modell (Ø der
  Spielsummen beider Teams) und Angriff-x-Abwehr-Modell (Heim holt x Gast
  lässt zu + Gast holt x Heim lässt zu, bezogen auf den Ligaschnitt je
  Team) — erkennt, ob die Serien beider Teams vom selben "Erzeuger"
  stammen (z.B. beide lassen viel zu, holen selbst wenig).

  Kennzahlen je Signal (keine zusätzlichen Anfragen): 📈 Trefferquote der
  Linie über die Historie beider Teams (jüngere Spiele stärker gewichtet,
  Spiele mit Platzverweis halb), 🪜 faire Quote für die Linie und ihre
  Nachbarlinien (zur Grundrate aller gecachten Spiele hin gedämpft,
  PRIOR_WEIGHT), 🎯 erwartete Spielsumme (gewichteter Ø Heimspiele des
  Heimteams + Auswärtsspiele des Gastteams) mit Puffer zur Linie,
  ↔ eigene/Gegner-Durchschnitte. AMPEL (eine durchgehende Rechnung):
  p_hist aus gewichteten Treffern, p_modell aus Erwartung (mit Schiri) und
  Streuung (Normalverteilung), p = Mittel beider -> faire Quote je Linie;
  Markt = bet365 exakt / über die Leiter umgerechnet (scores24-Spanne wird
  nie gerechnet); EV = p x Markt - 1. Gemeldet werden nur Märkte mit
  fairer Quote >= MIN_FAIR (1,30). 🟢 p>=68 %, Historie/Modell einig, Puffer>=0, EV>=+3 %;
  🔴 p<58 % oder Erwartung klar auf der falschen Seite oder Historie/Modell
  widersprechen sich oder exakter Markt deutlich unter fair; sonst 🟡 mit
  Grund. Zusätzlich (je 1 Anfrage, nur bei
  Signalen): 🏷 bet365-Hauptlinie mit Quote bei Ecken-Signalen,
  🧑‍⚖️ angesetzter Schiedsrichter mit Karten-/Foul-Schnitt aus dem Cache bei
  Karten-/Foul-Signalen; die Erwartung wird dort zusätzlich mit dem
  Schiri-Faktor (sein Schnitt / Schnitt aller Spiele, gedämpft) skaliert. Spiele mit Verlängerung (120 Min.) zählen in den
  Kennzahlen halb. BACKFILL=1 lädt Zusatzdaten für alte Cache-Einträge nach.

  Lauf-Vergleich (state/reported.json): JEDE Telegram-Nachricht zeigt
  ALLE Signale des Tages (noch nicht angepfiffen), strikt nach
  Anstoßzeit; Signale, die seit dem letzten Lauf neu sind, tragen 🆕,
  alle anderen ▸. Aufgenommen wird nur, was zum Scan-Zeitpunkt eine echte
  Quoten-Spanne bei scores24 hat; einmal aufgenommen bleibt es bis zum
  Anpfiff in der Liste, auch wenn ein späterer Lauf keine Quoten mehr
  findet oder die Serie kippt. Geändert/weggefallen wird nur im
  Lauf-Protokoll (runs/) festgehalten. Angepfiffene Spiele fallen
  automatisch raus. Das Gedächtnis wird nur nach erfolgreicher
  Zustellung gespeichert.

Benötigte Umgebungsvariablen:
  BETSAPI_TOKEN      – BetsAPI-Token (Soccer API)
  TELEGRAM_BOT_TOKEN – Telegram-Bot-Token (optional; ohne = nur Konsole)
  TELEGRAM_CHAT_ID   – Telegram-Chat-ID  (optional; ohne = nur Konsole)

Aufruf:
  python scan.py               # normaler Lauf (vor 6 Uhr: Vorwärm-Lauf)
  PREWARM=1 python scan.py     # Vorwärm-Lauf erzwingen
  python scan.py --selftest    # Regelwerk-Test ohne API-Zugriff
"""

import gzip
import json
import math
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ----------------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------------

API = "https://api.b365api.com"
TOKEN = os.environ.get("BETSAPI_TOKEN", "")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

# Regelwerk-Parameter
ANCHOR_HITS_OVERALL = 10   # Anker ohne Heim/Auswärts-Filter
ANCHOR_HITS_VENUE = 15     # Anker mit Heim/Auswärts-Filter (heutige Rolle)
ANCHOR_MAX_MISSES = 2      # max. Aussetzer jeder Anker-Serie
FRESH_GAMES = 2            # Anker: jüngste N gewertete Spiele müssen Treffer sein
OTHER_HITS = 5             # zweites Team: Mindest-Treffer ...
OTHER_MAX_MISSES = 1       # ... bei max. so vielen Aussetzern
MIN_VALID_MATCHES = 7      # Mindest-Datenbasis je Team und Metrik (gesamt)
HISTORY_DEPTH = 50         # wie viele beendete Spiele pro Team geladen werden
                           # (muss genug Heim-/Auswärtsspiele für die
                           #  15er-Serie enthalten; 50 reicht praktisch immer)

# Trivial-Filter: bildet die Mindestquote (~1,30) statistisch nach.
# Eine Linie zählt nur, wenn sie über die GESAMTE Historie beider Teams
# in höchstens diesem Anteil der Spiele getroffen hätte — fast-immer-wahre
# Linien (z.B. unter 12,5 Ecken) bekommen beim Buchmacher nur Miniquoten
# und fliegen hier raus.
# QUOTEN-CHECK ueber scores24 (Multi-Buchmacher-Aggregator, kostenlos):
# Fuer jedes statistische Signal wird die scores24-Spielseite geoeffnet und
# geprueft, ob es fuer die Metrik ueberhaupt einen Quoten-Reiter gibt
# (locker, nicht linien-genau — Lucios Vorgabe). Reiter vorhanden ->
# Signal bleibt, Quoten-Spanne kommt mit in die Meldung. Reiter fehlt ->
# Signal faellt weg (kein Buchmacher kennt den Markt). Ganze Spanne unter
# MIN_ODDS -> ebenfalls weg. Spielseite nicht zuordenbar/erreichbar ->
# Signal bleibt mit Markierung, nichts geht verloren.
GATE_ENABLED = True
MIN_ODDS = 1.30
S24_BASE = "https://scores24.live/de/soccer"
S24_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# scores24-Gruppennamen (rapi-JSON) je Metrik
S24_GROUPS = {
    "corners": "corners",
    "yellowcards": "cards",
    "on_target": "shots",
    "shots_total": "shots",
    "offsides": "offsides",
    "fouls": "fouls",
    "ht_corners": "corners",          # Halbzeit -> Vollzeit-Reiter als Nachweis
    "ht_yellowcards": "cards",
}

# Gegenläufigkeits-Regel: Über- und Unter-Trends derselben Metrik sind nur
# dann ein Widerspruch, wenn ihr Korridor eng ist (z.B. über 8,5 UND
# unter 10,5). Breite Korridore (über 6,5 + unter 12,5) sind legitim —
# bewiesen durch Lucios Wycombe-Wettschein vom 01.09.
# Märkte, die grundsätzlich NICHT gemeldet werden (Lucios Vorgabe 05.09.:
# "alle unter-Ecken-Märkte raus"). Für die Gegenbewegungs-Prüfung zählen
# sie trotzdem weiter.
EXCLUDED_MARKETS = {("corners", "unter"), ("ht_corners", "unter")}

# Halbzeit-Märkte (05.09.): 1. HZ Ecken aus dem API-Feld corner_h, 1. HZ Gelbe
# Karten aus dem Ereignis-Verlauf (Minute + "Score After First Half"-Marker).
# Quoten-Nachweis: ein Markt bleibt, wenn scores24 die Marktfamilie des
# Spiels kennt (HZ-Ecken -> Ecken-Reiter, HZ-Karten -> Karten-Reiter; reine
# Verfügbarkeits-Näherung, keine Werte). Der bet365-Zweig (B365_AS_PROOF)
# ist aus. Cache-Version 2 nötig ("nachladen").
HT_METRICS = {"ht_corners", "ht_yellowcards"}
CACHE_VERSION = 3          # 3: + Schüsse gesamt (06.09.)

# Quoten-Nachweis über die bet365-Linie (Oder-Regel). Hinweis: bet365 führt
# Ecken bis in Randligen, die Lucios Bookie nicht hat — der Zweig kann
# unspielbare Signale bringen; auf False schalten, wenn das stört.
B365_AS_PROOF = False    # Lucio (06.09., final): nur scores24-Verifizierung —
                         # "die Odds weichen zu sehr ab, macht keinen Sinn"

CONTRA_GAP = 2.0                      # Standard (Ecken, Schüsse)
# Marktabhängig: enge Linienraster (Karten, Abseits) -> nur die direkt
# benachbarte Linie ist ein Widerspruch; Fouls (Raster 2) -> 4.
# Halbzeit-Märkte: Korridor 1 wie bei Karten/Abseits — Lucio will keine
# Halbzeit-Signale "auf Krampf"; die Gegenbewegungs-Regel gilt dort voll.
CONTRA_GAP_BY_METRIC = {"corners": 2.0, "on_target": 2.0, "ht_corners": 1.0, "ht_yellowcards": 1.0, "shots_total": 4.0,
                        "yellowcards": 1.0, "offsides": 1.0, "fouls": 4.0}


def contra_gap(metric):
    return CONTRA_GAP_BY_METRIC.get(metric, CONTRA_GAP)

# Anfragen-Wächter: BetsAPI erlaubt 3.600 Anfragen/Stunde. Wir bremsen
# rechtzeitig, statt in Fehler zu laufen.
HOURLY_BUDGET = 3300

# Parallele Verarbeitung: so viele Spiele werden gleichzeitig geprüft.
# 16 ist das sinnvolle Maximum: mehr bringt kaum Tempo, erhöht aber das
# Risiko, dass die API einzelne Anfragen abweist. Der Anfragen-Wächter
# bremst vor dem Stundenlimit (3.600/h) automatisch.
WORKERS = 24

# Metriken: BetsAPI-Feldname -> (Anzeigename, Linienbereich)
METRICS = {
    "corners":  ("Ecken",             [7.5, 8.5, 9.5, 10.5, 11.5, 12.5]),   # 6,5 raus (06.09.)
    "yellowcards": ("Gelbe Karten",   [2.5, 3.5, 4.5, 5.5, 6.5]),
    "on_target": ("Schüsse aufs Tor", [6.5, 7.5, 8.5, 9.5, 10.5, 11.5]),
    "offsides": ("Abseits",           [2.5, 3.5, 4.5, 5.5]),
    "fouls":    ("Fouls",             [18.5, 20.5, 22.5, 24.5, 26.5, 28.5]),
    "ht_corners": ("1. HZ Ecken",     [3.5, 4.5, 5.5, 6.5]),
    "ht_yellowcards": ("1. HZ Gelbe Karten", [0.5, 1.5, 2.5]),
    "shots_total": ("Schüsse gesamt",  [18.5, 20.5, 22.5, 24.5, 26.5, 28.5, 30.5]),
}

# Liga-Beschränkung je Markt (06.09.): "Schüsse gesamt" führt Lucios Bookie
# nur in großen Ligen / UEFA-Wettbewerben — Spiele anderer Ligen werden für
# diesen Markt gar nicht erst geprüft. Muster = Teil des Liganamens (ohne
# Groß/Klein). Bei Bedarf ergänzen.
METRIC_LEAGUES = {}        # 06.09.: keine Liga-Beschränkung (Lucio) — Nachweis
                           # läuft wie überall über den scores24-Reiter


def metric_allowed_for_league(metric: str, league: str) -> bool:
    pats = METRIC_LEAGUES.get(metric)
    if not pats:
        return True
    low = (league or "").lower()
    return any(pat in low for pat in pats)

# Zusätzlich gecachte Felder (nicht als Markt, nur für die Gewichtung)
EXTRA_STAT_FIELDS = ("redcards",)

CACHE_FILE = Path(__file__).parent / "cache" / "stats.json.gz"    # komprimiert (06.09.)
CACHE_FILE_LEGACY = Path(__file__).parent / "cache" / "stats.json"
CACHE_KEEP_DAYS = 30     # Spiele, die 30 Tage nicht gebraucht wurden, fliegen raus.
                         # (06.09. abends: 3 Tage waren zu knapp — ein Team, das
                         #  wöchentlich spielt, wäre jede Woche wieder "kalt" =
                         #  6 Anfragen statt 1. Größe bleibt bei ~50-100k Spielen.)
RUNS_DIR = Path(__file__).parent / "runs"

# Tages-Cache für die Spiellisten der Teams ("welche Spiele zuletzt?").
# Ein Team spielt höchstens einmal am Tag — die Liste, die der Morgenlauf
# holt, gilt für alle Läufe des Tages. Spart 1-2 Anfragen pro Team und Lauf.
HISTORY_CACHE_FILE = Path(__file__).parent / "cache" / "history.json"
HISTORY_TTL = 12 * 3600      # Sekunden, danach wird die Liste neu geholt

# Vorwärm-Lauf (Cron 05:17): lädt nur Statistiken für den Tag in den Cache,
# wertet nichts aus, meldet nichts, und hört ohne zu warten auf, sobald das
# Stundenlimit erreicht ist. Der 06:17-Lauf startet dann mit frischem
# Limit und warmem Cache, statt bis zu einer Stunde am Limit zu hängen
# (GitHub zählt Wartezeit als Laufzeit). Aktiv, wenn die Berliner Stunde
# < PREWARM_BEFORE_HOUR ist oder PREWARM=1 gesetzt wurde.
PREWARM_BEFORE_HOUR = 6

# Lauf-Gedächtnis: welche Signale wurden schon gemeldet (mit Linie und
# Quoten-Spanne des ERSTEN Laufs)? Damit trennt die Telegram-Nachricht
# sauber nach 🆕 neu / 🔄 geändert / 🔁 unverändert / ❌ weggefallen.
# Einträge verschwinden automatisch, sobald das Spiel angepfiffen ist.
STATE_FILE = Path(__file__).parent / "state" / "reported.json"
# Version des Tagesgedächtnisses: Einträge einer älteren Version werden beim
# Laden verworfen (einmaliger Reset nach Regeländerungen, z.B. 06.09.:
# Halbzeit-Märkte liefen kurz ohne Quoten-Nachweis). Hochzählen = Reset.
STATE_VERSION = 2

_DE_DAYS = {"Mon": "Mo", "Tue": "Di", "Wed": "Mi", "Thu": "Do",
            "Fri": "Fr", "Sat": "Sa", "Sun": "So"}


def fmt_day_time(dt) -> str:
    """'Di 18:30' — Wochentag deutsch, unabhängig von der System-Sprache."""
    return f"{_DE_DAYS.get(dt.strftime('%a'), dt.strftime('%a'))} {dt:%H:%M}"


# ----------------------------------------------------------------------------
# HTTP + Anfragen-Wächter + Cache
# ----------------------------------------------------------------------------

_request_count = 0
_hour_started = time.time()
_hour_requests = 0
_counter_lock = threading.Lock()
_cache_lock = threading.Lock()
_no_wait = False             # Vorwärm-Modus: am Limit abbrechen statt warten
_budget_exhausted = False


class BudgetExhausted(Exception):
    """Stundenlimit erreicht und Warten nicht erlaubt (Vorwärm-Lauf)."""


def _budget_guard():
    """Bleibt unter dem Stundenlimit: notfalls bis zur nächsten Stunde warten
    — außer im Vorwärm-Modus, dort wird sauber abgebrochen."""
    global _hour_started, _hour_requests, _budget_exhausted
    while True:
        with _counter_lock:
            now = time.time()
            if now - _hour_started >= 3600:
                _hour_started = now
                _hour_requests = 0
            if _hour_requests < HOURLY_BUDGET:
                return
            wait = 3600 - (now - _hour_started) + 5
            if _no_wait:
                _budget_exhausted = True
                raise BudgetExhausted()
        print(f"Stundenbudget erreicht – warte {int(wait)}s", flush=True)
        time.sleep(max(min(wait, 300), 1))


def api_get(path: str, **params) -> dict:
    global _request_count, _hour_requests
    _budget_guard()
    params["token"] = TOKEN
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            with _counter_lock:
                _request_count += 1
                _hour_requests += 1
            if data.get("success") != 1:
                raise RuntimeError(f"API-Fehler {data.get('error')} bei {path}")
            return data
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def _today_num() -> int:
    return int(time.time() // 86400)


def load_cache() -> dict:
    raw = {}
    try:
        if CACHE_FILE.exists():
            with gzip.open(CACHE_FILE, "rt", encoding="utf-8") as f:
                raw = json.load(f)
        elif CACHE_FILE_LEGACY.exists():                    # einmalige Migration
            raw = json.loads(CACHE_FILE_LEGACY.read_text())
    except Exception:
        raw = {}
    # Veraltete Einträge (ältere Cache-Version) sofort verwerfen: sie würden
    # bei Bedarf ohnehin neu geholt und machen den Cache nur groß/langsam.
    cache = {k: v for k, v in raw.items() if v.get("x") == CACHE_VERSION}
    if len(cache) != len(raw):
        print(f"Cache: {len(raw) - len(cache)} veraltete Einträge verworfen, {len(cache)} behalten")
    return cache


def save_cache(cache: dict) -> None:
    """Speichert komprimiert und wirft Spiele raus, die CACHE_KEEP_DAYS lang
    nicht mehr gebraucht wurden ("t" = Tag der letzten Nutzung). Die Sperre
    wird nur für die Kopie gehalten, nicht fürs Schreiben — die Arbeiter
    laufen währenddessen weiter."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cutoff = _today_num() - CACHE_KEEP_DAYS
    today = _today_num()
    with _cache_lock:
        items = list(cache.items())
    slim = {}
    for k, v in items:
        t_used = v.get("t")
        if t_used is None:                 # neue Einträge: heute als Nutzung setzen
            v["t"] = today
        elif t_used < cutoff:
            continue
        slim[k] = v
    tmp = CACHE_FILE.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(slim, f, separators=(",", ":"))
    tmp.replace(CACHE_FILE)
    if CACHE_FILE_LEGACY.exists():
        try:
            CACHE_FILE_LEGACY.unlink()
        except OSError:
            pass


def load_history_cache() -> dict:
    if HISTORY_CACHE_FILE.exists():
        try:
            return json.loads(HISTORY_CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_history_cache(hcache: dict) -> None:
    """Speichert die Spiellisten; abgelaufene Einträge fliegen raus, damit
    die Datei im Repo klein bleibt."""
    cutoff = time.time() - HISTORY_TTL
    with _cache_lock:
        items = list(hcache.items())
    slim = {k: v for k, v in items if v.get("ts", 0) >= cutoff}
    HISTORY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_CACHE_FILE.write_text(json.dumps(slim, separators=(",", ":")))


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


# ----------------------------------------------------------------------------
# Datenbeschaffung
# ----------------------------------------------------------------------------

def now_berlin():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Berlin"))


def scan_window():
    """Anfang/Ende des Prüffensters nach Regelwerk."""
    now = now_berlin()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                 microsecond=0)
    if now.hour >= 20:            # der 20:17-Lauf ist der letzte des Tages
        end = midnight + timedelta(hours=6)   # deckt die Nachtspiele bis 6 Uhr ab
    else:
        end = midnight
    return now, end


def prewarm_window():
    """Vorwärmen: ab 23 Uhr die Spiele des NÄCHSTEN Tages (bis dessen
    Mitternacht), sonst den Rest des heutigen Tages."""
    now = now_berlin()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                 microsecond=0)
    end = midnight + timedelta(days=1) if now.hour >= 23 else midnight
    return now, end


def fetch_matches_in_window(now=None, end=None):
    """Alle noch nicht gestarteten Spiele im Prüffenster."""
    if now is None or end is None:
        now, end = scan_window()
    matches = {}
    days = set()
    d = now
    while d < end:
        days.add(d.astimezone(timezone.utc).strftime("%Y%m%d"))
        d += timedelta(hours=12)
    days.add(end.astimezone(timezone.utc).strftime("%Y%m%d"))
    for day in sorted(days):
        page = 1
        while page <= 15:
            data = api_get("/v3/events/upcoming", sport_id=1, day=day,
                           per_page=100, page=page, skip_esports=1)
            results = data.get("results", [])
            if not results:
                break
            for e in results:
                league = (e.get("league") or {}).get("name", "")
                if "esoccer" in league.lower():
                    continue
                kickoff = datetime.fromtimestamp(int(e["time"]), tz=timezone.utc)
                kickoff_local = kickoff.astimezone(now.tzinfo)
                if not (now < kickoff_local < end):
                    continue
                matches[e["id"]] = {
                    "id": e["id"],
                    "league": league,
                    "home": (e.get("home") or {}).get("name", "?"),
                    "away": (e.get("away") or {}).get("name", "?"),
                    "home_id": str((e.get("home") or {}).get("id")),
                    "away_id": str((e.get("away") or {}).get("id")),
                    "kickoff": fmt_day_time(kickoff_local),
                    "kickoff_ts": int(e["time"]),
                    "bet365_id": e.get("bet365_id"),
                }
            total = int((data.get("pager") or {}).get("total", 0))
            if page * 100 >= total:
                break
            page += 1
    return list(matches.values())


def _fetch_ended_list(team_id: str):
    """Die letzten HISTORY_DEPTH beendeten Spiele eines Teams (nur die
    Liste, kompakt) — kostet 1-2 Anfragen."""
    events = []
    page = 1
    while len(events) < HISTORY_DEPTH and page <= 3:
        data = api_get("/v3/events/ended", sport_id=1, team_id=team_id,
                       per_page=50, page=page, skip_esports=1)
        results = [e for e in data.get("results", [])
                   if "esoccer" not in ((e.get("league") or {}).get("name", "").lower())]
        events.extend(results)
        total = int((data.get("pager") or {}).get("total", 0))
        if page * 50 >= total or not results:
            break
        page += 1
    slim = []
    for e in events[:HISTORY_DEPTH]:
        home, away = e.get("home") or {}, e.get("away") or {}
        slim.append({"id": e["id"], "h": str(home.get("id")) == str(team_id),
                     "l": f'{home.get("name", "?")} - {away.get("name", "?")}'})
    return slim


def parse_ht_cards(ev: dict):
    """Gelbe Karten der 1. Halbzeit [Heim, Gast] aus dem Ereignis-Verlauf;
    None, wenn kein Verlauf oder kein Halbzeit-Marker vorhanden."""
    evs = ev.get("events") or []
    if not evs:
        return None
    away = ((ev.get("away") or {}).get("name") or "").strip().lower()
    h = a = 0
    seen = False
    for x in evs:
        txt = (x.get("text") or "")
        if "Score After First Half" in txt:
            seen = True
            break
        if "Yellow Card" in txt:
            m = re.search(r"\(([^()]*)\)\s*$", txt)
            team = (m.group(1) if m else "").strip().lower()
            if team and team == away:
                a += 1
            else:
                h += 1
    return [h, a] if seen else None


def _pair(stats, key):
    pair = stats.get(key)
    try:
        return [int(pair[0]), int(pair[1])]
    except (TypeError, ValueError, IndexError):
        return None


def total_shots(stats: dict):
    """Schüsse gesamt [Heim, Gast]: API-Feld goalattempts, sonst Summe aus
    aufs Tor + daneben + geblockt (nur wenn alle drei vorhanden)."""
    ga = _pair(stats, "goalattempts")
    if ga:
        return ga
    on, off, bl = _pair(stats, "on_target"), _pair(stats, "off_target"), _pair(stats, "shots_blocked")
    if on and off and bl:
        return [on[0] + off[0] + bl[0], on[1] + off[1] + bl[1]]
    return None


def slim_event(ev: dict) -> dict:
    """Kompakte Cache-Form eines Spiels: Statistiken + Schiedsrichter +
    Spieldauer (90/120 -> Verlängerung erkennbar)."""
    stats = ev.get("stats") or {}
    slim = {}
    for key in list(METRICS) + list(EXTRA_STAT_FIELDS):
        src = "corner_h" if key == "ht_corners" else key
        pair = stats.get(src)
        try:
            slim[key] = [int(pair[0]), int(pair[1])]
        except (TypeError, ValueError, IndexError):
            slim[key] = None
    slim["ht_yellowcards"] = parse_ht_cards(ev)
    slim["shots_total"] = total_shots(stats)
    extra = ev.get("extra") or {}
    ref = extra.get("referee") or {}
    slim["ref"] = [str(ref["id"]), ref.get("name", "?")] if ref.get("id") else None
    try:
        slim["len"] = int(extra.get("length")) if extra.get("length") else None
    except (TypeError, ValueError):
        slim["len"] = None
    slim["x"] = CACHE_VERSION          # Zusatzdaten (Schiri/Dauer/Halbzeit) geholt
    return slim


def fetch_team_history(team_id: str, cache: dict, hcache: dict = None):
    """Letzte HISTORY_DEPTH beendete Spiele eines Teams inkl. Statistiken.

    Liefert Liste (jüngstes zuerst) von:
      {"stats": {...}, "is_home": bool, "label": str}
    Statistiken beendeter Spiele sind unveränderlich und werden dauerhaft
    gecacht — nur neue Spiele kosten Anfragen. Die Spielliste selbst wird
    für HISTORY_TTL Sekunden zwischengespeichert (ein Team spielt höchstens
    einmal am Tag).
    """
    events = None
    if hcache is not None:
        with _cache_lock:
            entry = hcache.get(str(team_id))
            if entry and time.time() - entry.get("ts", 0) < HISTORY_TTL:
                events = entry["events"]
    if events is None:
        events = _fetch_ended_list(team_id)
        if hcache is not None:
            with _cache_lock:
                hcache[str(team_id)] = {"ts": int(time.time()), "events": events}

    # fehlende UND veraltete (ältere Cache-Version) Spiele holen — so werden
    # neue Felder genau dort aufgefrischt, wo sie gebraucht werden
    with _cache_lock:
        need = [e["id"] for e in events
                if e["id"] not in cache or cache[e["id"]].get("x") != CACHE_VERSION]
        if need:
            _cold_teams[0] += 1
    for i in range(0, len(need), 10):
        chunk = need[i:i + 10]
        view = api_get("/v1/event/view", event_id=",".join(chunk))
        got = set()
        for ev in view.get("results", []):
            slim = slim_event(ev)
            with _cache_lock:
                cache[ev["id"]] = slim
            got.add(ev["id"])
        with _cache_lock:                  # nicht mehr abrufbar: nicht ewig neu versuchen
            for eid in chunk:
                if eid not in got and eid in cache:
                    cache[eid]["x"] = CACHE_VERSION

    today = _today_num()
    history = []
    with _cache_lock:
        for e in events:
            slim = cache.get(e["id"], {})
            if slim:
                slim["t"] = today              # Nutzung vermerken (Cache-Pflege)
            history.append({"stats": slim, "is_home": e["h"], "label": e["l"]})
    return history


# ----------------------------------------------------------------------------
# Datenqualität + Regelwerk
# ----------------------------------------------------------------------------

def metric_total(match: dict, metric: str):
    """Spielsumme einer Metrik – oder None bei fehlenden/verdächtigen Daten."""
    stats = match.get("stats") or {}
    pair = stats.get(metric)
    if pair is None:
        return None
    fouls = stats.get("fouls")
    fouls_suspect = fouls is not None and fouls[0] == 0 and fouls[1] == 0
    if metric in ("fouls", "offsides") and fouls_suspect:
        return None
    if metric in ("on_target", "shots_total") and pair[0] == 0 and pair[1] == 0:
        return None
    return pair[0] + pair[1]


def hit_sequence(history, metric, line, direction, venue=None):
    """Treffer/Aussetzer-Folge (jüngstes zuerst), Qualitätsfilter inklusive.

    venue: None = alle Spiele, "home"/"away" = nur Heim- bzw. Auswärtsspiele.
    """
    seq = []
    valid = 0
    for m in history:
        if venue == "home" and not m["is_home"]:
            continue
        if venue == "away" and m["is_home"]:
            continue
        total = metric_total(m, metric)
        if total is None:
            continue
        valid += 1
        seq.append((total > line) if direction == "über" else (total < line))
    return seq, valid


def series(seq, min_hits, max_misses, fresh=0):
    """Sucht vom jüngsten Spiel an eine Serie mit >= min_hits Treffern und
    <= max_misses Aussetzern. fresh > 0 verlangt zusätzlich, dass die
    jüngsten `fresh` gewerteten Spiele Treffer sind (Frische-Regel).

    Rückgabe (hits, window) oder None.
    """
    if fresh and any(not h for h in seq[:fresh]):
        return None
    hits = misses = 0
    for h in seq:
        if h:
            hits += 1
        else:
            misses += 1
            if misses > max_misses:
                break
        if hits >= min_hits:
            return hits, hits + misses
    return None


def team_qualifies(history, metric, line, direction, role):
    """Bewertet ein Team: liefert (anchor, other) — jeweils Beschreibung
    der besten gefundenen Serie oder None.

    role: "home"/"away" — heutige Rolle des Teams (für die Venue-Serien).
    """
    seq_all, valid_all = hit_sequence(history, metric, line, direction)
    seq_ven, valid_ven = hit_sequence(history, metric, line, direction, venue=role)

    if valid_all < MIN_VALID_MATCHES:
        return None, None, valid_all

    anchor = None
    s = series(seq_all, ANCHOR_HITS_OVERALL, ANCHOR_MAX_MISSES, fresh=FRESH_GAMES)
    if s:
        anchor = {"kind": "gesamt", "hits": s[0], "window": s[1]}
    else:
        s = series(seq_ven, ANCHOR_HITS_VENUE, ANCHOR_MAX_MISSES, fresh=FRESH_GAMES)
        if s:
            anchor = {"kind": "heim" if role == "home" else "auswärts",
                      "hits": s[0], "window": s[1]}

    # Nicht-Anker-Serie: gestaffelte Lücken-Erlaubnis — ab 5 Treffern
    # max. 1 Lücke, ab 10 Treffern max. 2 Lücken (nie 3). Die stärkere
    # Variante wird bevorzugt gemeldet.
    def other_series(seq):
        return (series(seq, ANCHOR_HITS_OVERALL, ANCHOR_MAX_MISSES)
                or series(seq, OTHER_HITS, OTHER_MAX_MISSES))

    other = None
    s = other_series(seq_all)
    if s:
        other = {"kind": "gesamt", "hits": s[0], "window": s[1]}
    else:
        s = other_series(seq_ven)
        if s:
            other = {"kind": "heim" if role == "home" else "auswärts",
                     "hits": s[0], "window": s[1]}

    return anchor, other, valid_all


import re
import unicodedata


def s24_slug(name: str) -> str:
    """Teamname -> URL-Baustein im scores24-Stil."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("ß", "ss")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


_s24_links = None
_s24_links_lock = threading.Lock()
_s24_stats = {"ok": 0, "no_link": 0, "fetch_fail": 0, "last_error": ""}


def _s24_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": S24_UA,
                                               "Accept-Language": "de"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "ignore")


def s24_day_links():
    """Alle anstehenden Spiel-Slugs aus der scores24-Sitemap (dafuer ist
    sie da), einmal pro Lauf geladen. Liefert Slugs wie
    'm-01-09-2026-sheffield-united-bolton-wanderers'."""
    global _s24_links
    with _s24_links_lock:
        if _s24_links is not None:
            return _s24_links
        links = []
        for i in range(5):
            url = (f"https://scores24.live/sitemaps/"
                   f"sitemap-de-soccer-upcoming-matches-{i}.xml")
            try:
                xml = _s24_get(url)
            except Exception as exc:
                if i == 0:
                    _s24_stats["last_error"] = f"{url} -> {exc}"[:160]
                break
            found = re.findall(r"/de/soccer/(m-[^<\"?#]+)", xml)
            if not found:
                break
            links += found
        _s24_links = sorted(set(links))
        return _s24_links


_s24_index = None
_cold_teams = [0]          # Teams, für die in diesem Lauf Spiele nachgeladen wurden


def s24_link_index():
    """Einmal pro Lauf: jeden Sitemap-Slug in Tokens + Mannschafts-Zusätze
    zerlegen. Vorher wurde das für jedes Spiel × jeden Slug neu gerechnet
    (mehrere tausend Regex/Unicode-Läufe je Spiel, alle Threads am GIL)."""
    global _s24_index
    with _s24_links_lock:
        if _s24_index is not None:
            return _s24_index
    links = s24_day_links()
    idx = []
    for link in links:
        body = re.sub(r"^m-\d{2}-\d{2}-\d{4}-", "", link)
        toks = tuple(t for t in body.split("-") if len(t) >= 3)
        idx.append((link, body, toks, frozenset(variant_tags(body))))
    with _s24_links_lock:
        _s24_index = idx
    return idx


def _name_tokens(name):
    return [_TOKEN_ALIASES.get(t, t) for t in s24_slug(name).split("-") if len(t) >= 3]


def _tokens_match(name_toks, slug_toks):
    score = 0
    for tok in name_toks:
        if any(st == tok or st.startswith(tok) or tok.startswith(st)
               or (len(tok) >= 4 and tok in st) or (len(st) >= 4 and st in tok)
               for st in slug_toks):
            score += 1
    return score


_TOKEN_ALIASES = {"utd": "united", "cnty": "county", "wed": "wednesday",
                  "ath": "athletic", "intl": "international"}

# Mannschafts-Zusätze, die bei der Seiten-Zuordnung ZWINGEND übereinstimmen
# müssen (06.09.: "FK Jablonec B" war auf die Seite von FK Jablonec gelandet
# und hat deren Ecken-Quoten als Nachweis bekommen). Gruppen: Reserve
# (B/II/2/Reserves), dritte Mannschaft, U-Teams, Frauen, Jugend.
_VARIANT_TAGS = {
    "b": "res", "ii": "res", "2": "res", "reserves": "res", "reserve": "res",
    "res": "res", "amateure": "res", "amateur": "res",
    "iii": "res3", "3": "res3",
    "u17": "u", "u18": "u", "u19": "u", "u20": "u", "u21": "u", "u23": "u",
    "w": "w", "women": "w", "frauen": "w", "ladies": "w", "femenino": "w",
    "feminino": "w", "feminin": "w",
    "youth": "y", "jugend": "y", "academy": "y",
}


def variant_tags(text: str) -> set:
    """Zusätze eines Teamnamens oder Slugs als Menge, z.B. {'res'}, {'w'}."""
    tags = set()
    for tok in s24_slug(text).split("-"):
        tag = _VARIANT_TAGS.get(tok)
        if tag:
            tags.add(tag)
    return tags


def _name_matches_slug(name, slug_part):
    """Wieviele Tokens (>=3 Zeichen) des Teamnamens im Slug vorkommen
    (auch als Prefix, damit 'sheff' auf 'sheffield' passt)."""
    return _tokens_match(_name_tokens(name),
                         [st for st in slug_part.split("-") if len(st) >= 3])


def s24_fetch_groups(match):
    """Holt die Trend-Gruppen samt Quoten-Spannen eines Spiels aus der
    scores24-JSON-Schnittstelle (dieselbe, die der Browser der Seite nutzt).

    Liefert {metrik: (anzahl, quote_min, quote_max)} oder None, wenn das
    Spiel nicht zuzuordnen/erreichbar ist.
    """
    candidates = []
    want_tags = frozenset(variant_tags(match["home"]) | variant_tags(match["away"]))
    home_toks, away_toks = _name_tokens(match["home"]), _name_tokens(match["away"])
    for link, body, toks, tags in s24_link_index():
        if tags != want_tags:
            continue
        h = _tokens_match(home_toks, toks)
        if h < 1:
            continue
        a = _tokens_match(away_toks, toks)
        if a >= 1:
            candidates.append((h + a, link))
    slugs = [link[2:] for _, link in sorted(candidates, reverse=True)[:2]]
    # Fallback: direkt geratener Slug (zwei Datumsvarianten)
    from zoneinfo import ZoneInfo
    kick = datetime.fromtimestamp(match["kickoff_ts"], tz=ZoneInfo("Europe/Berlin"))
    home, away = s24_slug(match["home"]), s24_slug(match["away"])
    for d in (kick, kick - timedelta(days=1)):
        slugs.append(f"{d.strftime('%d-%m-%Y')}-{home}-{away}")
    wanted_groups = set(S24_GROUPS.values())
    for slug in slugs:
        url = (f"https://scores24.live/rapi/localized/matches/soccer/"
               f"{slug}/trends?lang=de&audience=de")
        try:
            raw = _s24_get(url)
            data = json.loads(raw).get("data") or []
        except Exception as exc:
            _s24_stats["last_error"] = f"{url} -> {exc}"[:160]
            continue
        # Verifikation: mindestens ein Token jedes Teamnamens im JSON
        low = raw.lower()
        def in_json(name):
            toks = [_TOKEN_ALIASES.get(t, t)
                    for t in s24_slug(name).split("-") if len(t) >= 4]
            return (not toks) or any(t in low for t in toks)
        if not (in_json(match["home"]) and in_json(match["away"])):
            _s24_stats["last_error"] = f"{url} -> Teamnamen nicht im JSON"[:160]
            continue
        if variant_tags(slug) != want_tags:
            _s24_stats["last_error"] = f"{url} -> Mannschafts-Zusatz passt nicht"[:160]
            continue
        groups = {}                      # {reiter-name: (anzahl, min, max)}
        for g in data:
            name = g.get("name")
            if name not in wanted_groups:
                continue
            count = int(g.get("count") or 0)
            lo = float(g.get("min_odd") or 0)
            hi = float(g.get("max_odd") or lo)
            if count > 0:
                groups[name] = (count, lo, hi)
        _s24_stats["ok"] += 1
        return groups
    if candidates:
        _s24_stats["fetch_fail"] += 1
    else:
        _s24_stats["no_link"] += 1
    return None


def s24_market_groups(html: str):
    """Extrahiert die Quoten-Reiter der Spielseite:
    {metrik: (anzahl, quote_min, quote_max)}"""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    groups = {}
    for metric, label in S24_GROUPS.items():
        m = re.search(
            re.escape(label) +
            r"(?:\s+Vorhersagen)?\s*\(\s*(\d+)\s*\)\s*([\d]+[.,]\d+)"
            r"(?:\s*-\s*([\d]+[.,]\d+))?",
            text)
        if not m:
            continue
        count = int(m.group(1))
        lo = float(m.group(2).replace(",", "."))
        hi = float(m.group(3).replace(",", ".")) if m.group(3) else lo
        if count > 0:
            groups[metric] = (count, lo, hi)
    return groups


def apply_s24_gate(signals, groups):
    """Wendet den lockeren Quoten-Check an.

    groups None  -> Seite nicht zuordenbar: alles behalten, markieren.
    Reiter fehlt -> Signal verwerfen (kein Buchmacher kennt den Markt).
    Spanne komplett unter MIN_ODDS -> verwerfen.
    Sonst behalten und Quoten-Spanne anhaengen.
    """
    if groups is None:
        # Seite nicht zuordenbar: alles als "scores24 fehlt" markieren.
        # Ecken/HZ-Ecken können noch über die bet365-Linie bestehen
        # (Oder-Regel, Lucio 06.09.), der Rest fliegt danach.
        for s in signals:
            s["unchecked"] = True
        return signals
    kept = []
    for s in signals:
        # Halbzeit-Märkte: scores24 kennt keine HZ-Reiter. Nachweis = der
        # zugehörige Vollzeit-Reiter (Ecken bzw. Karten) muss Quoten haben —
        # wer Ecken anbietet, hat i.d.R. auch HZ-Ecken; wer keine Karten
        # anbietet, hat sicher keine HZ-Karten.
        g = groups.get(S24_GROUPS.get(s["metric_key"], ""))
        if not g:
            if B365_AS_PROOF and s["metric_key"] in ("corners", "ht_corners"):
                s["unchecked"] = True          # zweite Chance: bet365-Linie
                kept.append(s)
            continue
        count, lo, hi = g
        if hi < MIN_ODDS:
            continue
        s["range"] = (lo, hi)
        kept.append(s)
    return kept


def _seq_summary(seq, fresh_required):
    """Kurzbeschreibung einer Treffer/Aussetzer-Folge: Treffer bis zur
    3. Lücke, plus Hinweis auf die Frische-Regel."""
    hits = misses = 0
    for h in seq:
        if h:
            hits += 1
        else:
            misses += 1
            if misses > ANCHOR_MAX_MISSES:
                break
    window = hits + min(misses, ANCHOR_MAX_MISSES)
    txt = f"{hits}/{window}" if window > hits else f"{hits} in Folge"
    if misses > ANCHOR_MAX_MISSES:
        txt += " (3. Lücke)"
    elif fresh_required and any(not h for h in seq[:FRESH_GAMES]):
        txt += " (Aussetzer in den letzten 2)"
    return txt


def team_diag(history, metric, line, direction, role):
    """Warum erfüllt ein Team eine Linie (nicht)? Liefert (anchor, other, text)."""
    anchor, other, valid = team_qualifies(history, metric, line, direction, role)
    if valid < MIN_VALID_MATCHES:
        return anchor, other, f"nur {valid} Spiele mit Daten"
    seq_all, _ = hit_sequence(history, metric, line, direction)
    seq_ven, _ = hit_sequence(history, metric, line, direction, venue=role)
    txt = _seq_summary(seq_all, fresh_required=True)
    ven = _seq_summary(seq_ven, fresh_required=True)
    role_de = "heim" if role == "home" else "auswärts"
    return anchor, other, f"{txt} gesamt, {ven} {role_de}"


def next_line_note(match, hist_home, hist_away, metric, direction, line):
    """Erklärt, warum die nächststrengere Linie NICHT gemeldet wurde —
    damit Lucio sieht, wo die Serie abreißt (z.B. scores24 zeigt 7.5,
    wir melden 6.5)."""
    lines = METRICS[metric][1]
    stricter = [l for l in lines if (l > line if direction == "über" else l < line)]
    if not stricter:
        return None
    nxt = min(stricter) if direction == "über" else max(stricter)
    a_h, o_h, txt_h = team_diag(hist_home, metric, nxt, direction, "home")
    a_a, o_a, txt_a = team_diag(hist_away, metric, nxt, direction, "away")
    parts = []
    if not (a_h or o_h):
        parts.append(f"{match['home']} {txt_h}")
    if not (a_a or o_a):
        parts.append(f"{match['away']} {txt_a}")
    if not parts:                       # beide haben Serien, aber kein Anker
        parts.append(f"kein Anker — {match['home']} {txt_h}; {match['away']} {txt_a}")
    return nxt, "; ".join(parts)


def counter_trend(match, hist_home, hist_away, metric, direction, line):
    """Gegenbewegung: Hat EINES der beiden Teams in der Gegenrichtung eine
    Serie (kleine Serie reicht) an einer Linie im engen Korridor
    (Abstand <= CONTRA_GAP)? Dann widerspricht sich der Markt und wird
    verworfen — Lucios Vorgabe (Beispiel Palermo: unter 5,5 Abseits für
    beide, aber Palermo über 4,5 in 7 der letzten 8 -> raus).
    Liefert Beschreibung der Gegen-Serie oder None."""
    opp = "unter" if direction == "über" else "über"
    for L in METRICS[metric][1]:
        gap = (L - line) if direction == "über" else (line - L)
        if gap > contra_gap(metric):
            continue
        for hist, role, name in ((hist_home, "home", match["home"]),
                                 (hist_away, "away", match["away"])):
            a, o, _ = team_qualifies(hist, metric, L, opp, role)
            s = a or o
            if s:
                return f"{name} {opp} {L}: {fmt_series(s, bool(a))}"
    return None


# ----------------------------------------------------------------------------
# Kennzahlen je Signal (Optimierungsphase 1): Langzeitquote, faire Quote,
# Erwartung/Puffer, Für/Gegen-Profil — alles aus den ohnehin geladenen
# 50 Spielen je Team, keine zusätzlichen API-Anfragen.
# ----------------------------------------------------------------------------

PRIOR_WEIGHT = 20            # wie stark die faire Quote zur Grundrate gezogen wird
                             # (dämpft die Selbstüberschätzung ausgewählter Serien)
# Gewichtung der Historie für die Kennzahlen (NICHT für die Serienregeln):
# die jüngsten RECENT_FULL Spiele zählen voll, danach halbiert sich das
# Gewicht alle DECAY_HALF Spiele (Saisonwechsel, Trainerwechsel, Umbruch).
# Spiele mit Platzverweis zählen nur RED_CARD_WEIGHT (verzerrte Totals).
RECENT_FULL = 10
DECAY_HALF = 15
RED_CARD_WEIGHT = 0.5
_base_rates = {}             # {(metric, line, direction): p} aus dem Statistik-Cache


def compute_base_rates(cache):
    """Grundraten je Markt/Linie/Richtung über ALLE gecachten Spiele —
    der neutrale Vergleichsmaßstab für die faire Quote."""
    rates = {}
    for metric, (_, lines) in METRICS.items():
        totals = []
        for slim in cache.values():
            tot = metric_total({"stats": slim}, metric)
            if tot is not None:
                totals.append(tot)
        for line in lines:
            if totals:
                over = sum(1 for x in totals if x > line) / len(totals)
            else:
                over = 0.5
            rates[(metric, line, "über")] = over
            rates[(metric, line, "unter")] = 1 - over
    return rates


def game_weight(i, m):
    w = 1.0 if i < RECENT_FULL else 0.5 ** ((i - RECENT_FULL + 1) / DECAY_HALF)
    st = m.get("stats") or {}
    reds = st.get("redcards")
    if reds and (reds[0] + reds[1]) > 0:
        w *= RED_CARD_WEIGHT
    if st.get("len") and st["len"] > 100:          # Verlängerung: Totals aus 120 Min.
        w *= RED_CARD_WEIGHT
    return w


# --- Schiedsrichter-Profil aus dem Cache (Karten/Fouls je Schiri) ---------
_ref_stats = {}


def compute_referee_stats(cache):
    """{ref_id: {"name", "cards": [..], "fouls": [..]}} über alle gecachten
    Spiele mit bekanntem Schiedsrichter."""
    out = {}
    for slim in cache.values():
        ref = slim.get("ref")
        if not ref:
            continue
        d = out.setdefault(ref[0], {"name": ref[1], "cards": [], "fouls": []})
        m = {"stats": slim}
        c = metric_total(m, "yellowcards")
        f = metric_total(m, "fouls")
        if c is not None:
            d["cards"].append(c)
        if f is not None:
            d["fouls"].append(f)
    return out


REF_PRIOR_GAMES = 8          # so viele "neutrale" Spiele werden dem Schiri-Schnitt beigemischt
_base_means = {}             # {metric: Ø Spielsumme über alle gecachten Spiele}


def compute_base_means(cache):
    out = {}
    for metric in METRICS:
        vals = [metric_total({"stats": s}, metric) for s in cache.values()]
        vals = [v for v in vals if v is not None]
        if vals:
            out[metric] = sum(vals) / len(vals)
    return out


def referee_factor(ref_id, metric):
    """Faktor > 1 = dieser Schiri liegt über dem Schnitt aller Spiele.
    Bei wenigen Spielen zum Faktor 1 hin gedämpft. None = keine Daten."""
    d = _ref_stats.get(str(ref_id))
    key = ("cards" if metric in ("yellowcards", "ht_yellowcards")
           else "fouls" if metric == "fouls" else None)
    base = _base_means.get(metric)
    if not d or not key or not d[key] or not base:
        return None
    n = len(d[key])
    mean = sum(d[key]) / n
    shrunk = (mean * n + base * REF_PRIOR_GAMES) / (n + REF_PRIOR_GAMES)
    return shrunk / base


def referee_note(ref_id, ref_name):
    d = _ref_stats.get(str(ref_id))
    if not d or not (d["cards"] or d["fouls"]):
        return f"{ref_name} (noch keine Daten)"
    parts = []
    if d["cards"]:
        parts.append(f"Ø {sum(d['cards'])/len(d['cards']):.1f} Karten ({len(d['cards'])} Sp.)")
    if d["fouls"]:
        parts.append(f"Ø {sum(d['fouls'])/len(d['fouls']):.1f} Fouls ({len(d['fouls'])} Sp.)")
    return f"{ref_name}: " + " · ".join(parts)


def weighted_stats(history, metric, line, direction, venue=None):
    """Gewichtete Treffer, Gewichtssumme und gewichteter Ø der Spielsumme."""
    wh = ww = wt = 0.0
    for i, m in enumerate(history):
        if venue == "home" and not m["is_home"]:
            continue
        if venue == "away" and m["is_home"]:
            continue
        tot = metric_total(m, metric)
        if tot is None:
            continue
        w = game_weight(i, m)
        hit = (tot > line) if direction == "über" else (tot < line)
        wh += w * hit
        ww += w
        wt += w * tot
    return wh, ww, (wt / ww if ww else None)


def fair_odds(hist_home, hist_away, metric, line, direction):
    wh_h, ww_h, _ = weighted_stats(hist_home, metric, line, direction)
    wh_a, ww_a, _ = weighted_stats(hist_away, metric, line, direction)
    p0 = _base_rates.get((metric, line, direction), 0.5)
    p = (wh_h + wh_a + PRIOR_WEIGHT * p0) / max(ww_h + ww_a + PRIOR_WEIGHT, 1e-9)
    return round(1 / p, 2) if p > 0.02 else None


def team_totals(history, metric, venue=None):
    out = []
    for m in history:
        if venue == "home" and not m["is_home"]:
            continue
        if venue == "away" and m["is_home"]:
            continue
        tot = metric_total(m, metric)
        if tot is not None:
            out.append(tot)
    return out


def team_for_against(history, metric, venue=None, weighted=False):
    """Ø eigene Werte / Ø Werte des Gegners (aus [Heim, Gast] + Rolle);
    optional nur Heim-/Auswärtsspiele und mit Zeit-/Platzverweis-Gewichtung."""
    own = opp = ww = 0.0
    n = 0
    for i, m in enumerate(history):
        if venue == "home" and not m["is_home"]:
            continue
        if venue == "away" and m["is_home"]:
            continue
        if metric_total(m, metric) is None:
            continue
        pair = (m.get("stats") or {}).get(metric)
        if not pair:
            continue
        a, b = (pair[0], pair[1]) if m["is_home"] else (pair[1], pair[0])
        w = game_weight(i, m) if weighted else 1.0
        own += w * a
        opp += w * b
        ww += w
        n += 1
    if n < 3 or ww <= 0:
        return None
    return own / ww, opp / ww


def matchup_expectation(hist_home, hist_away, metric):
    """Beitrags-Modell (Angriff x Abwehr): Erwartung für HEUTE aus dem, was
    jedes Team selbst produziert und dem Gegner zugesteht — Heim-Rolle für
    das Heimteam, Auswärts-Rolle für das Gastteam (Fallback: alle Spiele),
    gewichtet, bezogen auf den Schnitt aller gecachten Spiele (je Team).
    Liefert (erwartung_gesamt, beitrag_heim, beitrag_gast) oder None."""
    fa_h = (team_for_against(hist_home, metric, "home", True)
            or team_for_against(hist_home, metric, None, True))
    fa_a = (team_for_against(hist_away, metric, "away", True)
            or team_for_against(hist_away, metric, None, True))
    if not fa_h or not fa_a:
        return None
    base = _base_means.get(metric)
    if not base:
        base = fa_h[0] + fa_h[1] + fa_a[0] + fa_a[1]     # Notbehelf ohne Cache
        base = base / 2
    per_team = base / 2                                  # Ligaschnitt je Team
    if per_team <= 0:
        return None
    home_today = fa_h[0] * fa_a[1] / per_team            # Heim holt x Gast lässt zu
    away_today = fa_a[0] * fa_h[1] / per_team            # Gast holt x Heim lässt zu
    return home_today + away_today, home_today, away_today


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def enrich_signal(s, hist_home, hist_away, metric, direction, line):
    """Hängt Kennzahlen ans Signal: longterm (Quote je Team über die ganze
    Historie), fair (faire Quote), expect/buffer (Erwartung, Puffer),
    fa (Für/Gegen je Team)."""
    wh_h, ww_h, _ = weighted_stats(hist_home, metric, line, direction)
    wh_a, ww_a, _ = weighted_stats(hist_away, metric, line, direction)
    s["longterm"] = (wh_h / ww_h if ww_h else None, wh_a / ww_a if ww_a else None)
    s["fair"] = fair_odds(hist_home, hist_away, metric, line, direction)
    # Fair-Leiter: Nachbarlinien gleich mit (Bookie-Leiter vergleichen)
    # Leiter: nur Linien, die das Regelwerk erfüllen — die gemeldete
    # (strengste qualifizierende) und die nächste LOCKERERE (die ist
    # automatisch erfüllt: jeder Treffer über 8,5 ist auch einer über 7,5).
    # Die strengere Nachbarlinie erfüllt das Regelwerk NICHT (sonst wäre sie
    # gemeldet worden) und wird deshalb nicht angezeigt — Lucios Vorgabe.
    lines = METRICS[metric][1]
    step = (lines[1] - lines[0]) if len(lines) > 1 else 1.0
    looser = line - step if direction == "über" else line + step
    ladder = []
    for L in sorted([looser, line]):
        if L < 0.5:
            continue
        ladder.append([round(L, 1), fair_odds(hist_home, hist_away, metric, L, direction)])
    s["ladder"] = ladder
    _, _, avg_h = weighted_stats(hist_home, metric, line, direction, "home")
    if avg_h is None:
        _, _, avg_h = weighted_stats(hist_home, metric, line, direction)
    _, _, avg_a = weighted_stats(hist_away, metric, line, direction, "away")
    if avg_a is None:
        _, _, avg_a = weighted_stats(hist_away, metric, line, direction)
    if avg_h is not None and avg_a is not None:
        expect_sum = (avg_h + avg_a) / 2                 # Summen-Modell (bisher)
        s["avg"] = (round(avg_h, 1), round(avg_a, 1))
        s["expect_sum"] = round(expect_sum, 1)
        mu = matchup_expectation(hist_home, hist_away, metric)
        if mu:
            s["expect_matchup"] = round(mu[0], 1)
            s["contrib"] = (round(mu[1], 1), round(mu[2], 1))
            expect = (expect_sum + mu[0]) / 2            # 50/50 mit Beitrags-Modell
        else:
            expect = expect_sum
        s["expect"] = round(expect, 1)
        s["buffer"] = round(expect - line if direction == "über" else line - expect, 1)
    fa_h = team_for_against(hist_home, metric)
    fa_a = team_for_against(hist_away, metric)
    if fa_h and fa_a:
        s["fa"] = ([round(fa_h[0], 1), round(fa_h[1], 1)], [round(fa_a[0], 1), round(fa_a[1], 1)])
    # Streuung der Spielsummen (gewichtet, beide Teams gepoolt) fürs Modell
    s["sd"] = round(pooled_sd(hist_home, hist_away, metric), 2)
    # empirische Wahrscheinlichkeiten je Leiter-Linie (aus den fairen Quoten)
    s["p_emp"] = {str(L): (1 / f if f else None) for L, f in ladder}
    return s


def pooled_sd(hist_home, hist_away, metric):
    xs, ws = [], []
    for hist in (hist_home, hist_away):
        for i, m in enumerate(hist):
            tot = metric_total(m, metric)
            if tot is None:
                continue
            xs.append(tot)
            ws.append(game_weight(i, m))
    if len(xs) < 5:
        return SD_FALLBACK.get(metric, 3.0)
    W = sum(ws)
    mean = sum(w * x for w, x in zip(ws, xs)) / W
    var = sum(w * (x - mean) ** 2 for w, x in zip(ws, xs)) / W
    return max(math.sqrt(var), 0.8)


SD_FALLBACK = {"corners": 3.0, "yellowcards": 1.9, "on_target": 2.6, "ht_corners": 1.8, "ht_yellowcards": 1.1, "shots_total": 6.0,
               "offsides": 1.8, "fouls": 5.0}


def _norm_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def model_prob(mean, sd, line, direction):
    """P(Spielsumme > line) bzw. < line aus Normalverteilung (Linie ist x.5)."""
    p_over = 1 - _norm_cdf((line - mean) / sd)
    return p_over if direction == "über" else 1 - p_over


# --- Die eine schlüssige Rechnung: Historie + Modell -> Fair -> Markt -> Ampel
MIN_FAIR = 1.0            # Mindest-Fair-Filter AUS (06.09., Lucio: "einmal alle wieder
                          # rein, ich checke es") — alle ✅-Märkte werden gemeldet, er
                          # spielt nur, wo der Bookie über fair UND >= 1,30 liegt.
                          # Zum Reaktivieren z.B. 1.20 setzen.
GREEN_MIN_P = 0.68        # Mindest-Wahrscheinlichkeit (kombiniert) für Grün
RED_MAX_P = 0.58          # darunter Rot
AGREE_OK = 0.12           # max. Abstand Historie/Modell für Grün
AGREE_BAD = 0.25          # darüber Rot ("Zahlen tragen die Serie nicht")
EV_GREEN = 0.03           # Erwartungswert (Markt x p - 1) ab dem es Grün gibt
EV_RED = -0.05            # darunter Rot (nur bei exakter/umgerechneter Quote)


def assess_signal(s):
    """Kombiniert alles zu EINER Bewertung. Setzt: p_mod, p_fin, fair_fin,
    ladder_fin, market, market_src, ev, light, reason."""
    line, direction, metric = s["line"], s["direction"], s["metric_key"]
    mean = s.get("expect_ref") if s.get("expect_ref") is not None else s.get("expect")
    sd = s.get("sd") or SD_FALLBACK.get(metric, 3.0)
    p_emp_map = s.get("p_emp") or {}
    p_emp = p_emp_map.get(str(line)) or (1 / s["fair"] if s.get("fair") else None)
    if mean is None or p_emp is None:
        s["light"], s["reason"] = "🟡", "zu wenig Daten für die Rechnung"
        return s
    p_mod = model_prob(mean, sd, line, direction)
    p_fin = 0.5 * p_emp + 0.5 * p_mod
    s["p_mod"], s["p_fin"] = round(p_mod, 3), round(p_fin, 3)
    s["fair_fin"] = round(1 / p_fin, 2) if p_fin > 0.02 else None
    # kombinierte Leiter
    lad = []
    for L, _ in (s.get("ladder") or []):
        pe = p_emp_map.get(str(L))
        pm = model_prob(mean, sd, L, direction)
        pf = 0.5 * pe + 0.5 * pm if pe else pm
        lad.append([L, round(1 / pf, 2) if pf > 0.02 else None])
    s["ladder_fin"] = lad
    # Markt-Referenz
    market, src = None, None
    if s.get("b365"):
        try:
            hc = float(s["b365"][0])
            od = float(s["b365"][1] if direction == "über" else s["b365"][2])
            if abs(hc - line) < 0.01:
                market, src = od, "bet365"
            else:
                f_line = dict((L, f) for L, f in lad).get(line)
                f_b = None
                for L, f in lad:
                    if abs(L - hc) < 0.01:
                        f_b = f
                if f_line and f_b:
                    market, src = round(od * f_line / f_b, 2), f"bet365 {hc:g} umgerechnet"
        except (TypeError, ValueError):
            pass
    # scores24-Spanne wird NICHT gerechnet (Lucio: nur Existenz-Check)
    s["market"], s["market_src"] = market, src
    ev = (p_fin * market - 1) if market else None
    s["ev"] = round(ev, 3) if ev is not None else None
    exact = src is not None and src.startswith("bet365")
    agree = abs(p_emp - p_mod)
    buf = s.get("buffer_ref") if s.get("buffer_ref") is not None else s.get("buffer", 0)
    # Ampel
    if p_fin < RED_MAX_P:
        light, reason = "🔴", f"nur {p_fin*100:.0f} % Wahrscheinlichkeit"
    elif buf is not None and buf < -0.5 * sd:
        light, reason = "🔴", "Erwartung auf der falschen Seite der Linie"
    elif agree > AGREE_BAD:
        light, reason = "🔴", f"Historie {p_emp*100:.0f} % und Modell {p_mod*100:.0f} % widersprechen sich"
    elif exact and ev is not None and ev < EV_RED:
        light, reason = "🔴", "Marktquote deutlich unter fair — Modell passt hier nicht"
    elif p_fin >= GREEN_MIN_P and agree <= AGREE_OK and (buf or 0) >= 0 and \
            (ev is None or ev >= EV_GREEN):
        light, reason = "🟢", f"fair {s['fair_fin']:.2f}"
    else:
        bits = []
        if p_fin < GREEN_MIN_P:
            bits.append(f"{p_fin*100:.0f} % knapp")
        if agree > AGREE_OK:
            bits.append(f"Historie {p_emp*100:.0f} % vs. Modell {p_mod*100:.0f} %")
        if (buf or 0) < 0:
            bits.append("Puffer negativ")
        if ev is not None and ev < EV_GREEN:
            bits.append("Marktquote nicht über fair")
        light, reason = "🟡", "; ".join(bits) or "prüfen"
    s["light"], s["reason"] = light, reason
    return s


def evaluate_match(match, hist_home, hist_away, market_odds=None):
    """Regelwerk + optionales Quoten-Gate.

    market_odds:
      None  -> reine Statistik (Gate aus): strengste qualifizierende Linie.
      dict  -> Gate an: nur Linien, die das Regelwerk erfuellen UND fuer
               die bet365 eine Quote >= MIN_ODDS stellt; Quote wird ans
               Signal geschrieben.
    """
    candidates = {}
    for metric, (label, lines) in METRICS.items():
        if not metric_allowed_for_league(metric, match.get("league", "")):
            continue
        for direction in ("über", "unter"):
            if (metric, direction) in EXCLUDED_MARKETS:
                continue
            for line in lines:
                a_home, o_home, v_home = team_qualifies(hist_home, metric, line, direction, "home")
                a_away, o_away, v_away = team_qualifies(hist_away, metric, line, direction, "away")
                if not ((a_home or o_home) and (a_away or o_away)):
                    continue
                if not (a_home or a_away):
                    continue
                candidates.setdefault((metric, direction), []).append({
                    "metric": label, "metric_key": metric,
                    "line": line, "direction": direction,
                    "home_series": a_home or o_home,
                    "away_series": a_away or o_away,
                    "home_is_anchor": bool(a_home),
                    "away_is_anchor": bool(a_away),
                    "valid": (v_home, v_away),
                })
    # Gegenläufigkeits-Filter: nur ENGE Korridore sind ein Widerspruch.
    # (über 8,5 + unter 10,5 -> Metrik raus; über 6,5 + unter 12,5 -> ok)
    contradicted = set()
    for metric in {m for (m, _) in candidates}:
        over_lines = [c["line"] for c in candidates.get((metric, "über"), [])]
        under_lines = [c["line"] for c in candidates.get((metric, "unter"), [])]
        if over_lines and under_lines and \
           min(under_lines) - max(over_lines) <= contra_gap(metric):
            contradicted.add(metric)
    signals = []
    for (metric, direction), cands in candidates.items():
        if metric in contradicted:
            continue
        if market_odds is not None:
            lines_odds = market_odds.get(metric, {})
            gated = []
            for c in cands:
                quote = lines_odds.get(c["line"], {}).get(direction)
                if quote and quote >= MIN_ODDS:
                    c = dict(c, quote=quote)
                    gated.append(c)
            cands = gated
        if not cands:
            continue
        best = max(cands, key=lambda c: c["line"]) if direction == "über" \
            else min(cands, key=lambda c: c["line"])
        contra = counter_trend(match, hist_home, hist_away, metric, direction, best["line"])
        if contra:
            match.setdefault("_contra", []).append(
                f"{METRICS[metric][0]} {direction} {best['line']} verworfen — Gegenbewegung {contra}")
            continue
        note = next_line_note(match, hist_home, hist_away, metric, direction, best["line"])
        if note:
            best["next_line"] = note[0]
            best["next_note"] = note[1]
        enrich_signal(best, hist_home, hist_away, metric, direction, best["line"])
        signals.append(best)
    return signals


# ----------------------------------------------------------------------------
# Lauf-Vergleich: neu / geändert / unverändert / weggefallen
# ----------------------------------------------------------------------------

def signal_key(match, s) -> str:
    """Identität eines Signals: Spiel + Markt + Richtung (die Linie darf
    sich verschieben — das wird dann als Änderung gemeldet)."""
    return f"{match['id']}|{s['metric_key']}|{s['direction']}"


def fmt_range(rng) -> str:
    if not rng:
        return "❓"
    lo, hi = rng
    return f"{lo:.2f}–{hi:.2f}" if hi > lo else f"{lo:.2f}"


def _cur_range(s):
    return list(s["range"]) if s.get("range") else None


_SNAPSHOT_KEYS = ("metric", "metric_key", "direction", "line", "home_series",
                  "away_series", "home_is_anchor", "away_is_anchor", "valid",
                  "next_line", "next_note", "longterm", "fair", "ladder", "avg",
                  "expect", "expect_sum", "expect_matchup", "contrib", "buffer", "fa",
                  "referee", "b365", "expect_ref", "buffer_ref",
                  "sd", "p_emp", "p_mod", "p_fin", "fair_fin", "ladder_fin", "market",
                  "market_src", "ev", "light", "reason")


def signal_snapshot(s):
    """Alles, was nötig ist, um ein Signal später erneut darzustellen —
    auch wenn ein späterer Lauf es nicht mehr liefert."""
    snap = {k: s.get(k) for k in _SNAPSHOT_KEYS}
    if snap.get("valid") is not None:
        snap["valid"] = list(snap["valid"])
    snap["range"] = _cur_range(s)
    return snap


def classify_signals(state, all_hits, checked_ids, window_ids, now_ts, run_label,
                     gate_dropped=frozenset(), unverifiable=frozenset()):
    """Vergleicht die Signale dieses Laufs mit dem Lauf-Gedächtnis.

    state       : {key: eintrag} aus state/reported.json
    all_hits    : [(match, [signal, ...]), ...] dieses Laufs
    checked_ids : Spiel-IDs, die in diesem Lauf fehlerfrei geprüft wurden
    window_ids  : Spiel-IDs, die im Prüffenster lagen (Spielplan)
    now_ts      : Unix-Zeit jetzt (Einträge angepfiffener Spiele fliegen raus)
    gate_dropped: Signal-Keys, die statistisch noch stehen, aber am
                  Quoten-Gate gescheitert sind (Markt bei scores24 weg)
    unverifiable: Signal-Keys, deren scores24-Seite nicht zuordenbar war
                  (nur relevant, wenn sie früher schon gemeldet wurden)

    Liefert (buckets, new_state) mit buckets = {"new","changed","same","dropped"};
    new/changed/same enthalten [(match, [signal, ...])], jedes Signal trägt
    ggf. s["change_note"]; dropped enthält [(eintrag, grund)].
    """
    new_state = {}
    seen_keys = set()
    buckets = {"new": [], "changed": [], "same": [], "dropped": []}

    for match, signals in all_hits:
        per = {"new": [], "changed": [], "same": []}
        for s in signals:
            key = signal_key(match, s)
            seen_keys.add(key)
            prev = state.get(key)
            cur_range = _cur_range(s)
            if prev is None:
                entry = {
                    "match_id": match["id"], "home": match["home"],
                    "away": match["away"], "kickoff": match["kickoff"],
                    "kickoff_ts": match.get("kickoff_ts", 0),
                    "league": match.get("league", ""),
                    "metric": s["metric"], "metric_key": s["metric_key"],
                    "direction": s["direction"],
                    "first_run": run_label, "first_line": s["line"],
                    "first_range": cur_range,
                    "last_run": run_label, "line": s["line"], "range": cur_range,
                    "signal": signal_snapshot(s), "v": STATE_VERSION,
                }
                per["new"].append(s)
            else:
                entry = dict(prev, last_run=run_label, line=s["line"],
                             range=cur_range, kickoff=match["kickoff"],
                             kickoff_ts=match.get("kickoff_ts", prev.get("kickoff_ts", 0)),
                             signal=signal_snapshot(s), v=STATE_VERSION)
                notes = []
                if prev.get("first_line") != s["line"]:
                    notes.append(f"Linie vorher {prev.get('first_line')}")
                first_range = prev.get("first_range")
                if first_range != cur_range:
                    if cur_range and not first_range:
                        notes.append("Quoten jetzt da, vorher keine")
                    elif first_range and not cur_range:
                        notes.append(f"Quoten vorher {fmt_range(first_range)}, jetzt nicht prüfbar")
                    else:
                        notes.append(f"Quoten vorher {fmt_range(first_range)}")
                s["first_run"] = prev.get("first_run", "?")
                if notes:
                    s["change_note"] = "; ".join(notes)
                    per["changed"].append(s)
                else:
                    per["same"].append(s)
            new_state[key] = entry
        for bucket, sigs in per.items():
            if sigs:
                buckets[bucket].append((match, sigs))

    for key, prev in state.items():
        if key in seen_keys:
            continue
        if int(prev.get("kickoff_ts", 0)) <= now_ts:
            continue                                   # angepfiffen -> vergessen
        mid = prev.get("match_id")
        if mid in checked_ids:
            if key in gate_dropped:
                reason = "Quote rausgenommen — kein Quoten-Markt mehr bei scores24"
            elif key in unverifiable:
                reason = "Quoten nicht mehr prüfbar (scores24-Seite nicht zuordenbar)"
            else:
                reason = "Serie erfüllt das Regelwerk nicht mehr"
            buckets["dropped"].append((prev, reason))
        elif mid not in window_ids and int(prev.get("kickoff_ts", 0)) < now_ts + 36 * 3600:
            buckets["dropped"].append((prev, "Spiel nicht mehr im Spielplan (verschoben/abgesagt?)"))
        # Lucios Vorgabe: Was an dem Tag einmal mit Quoten gemeldet wurde,
        # bleibt bis zum Anpfiff gemerkt — auch wenn ein späterer Lauf keine
        # Quoten mehr findet oder die Serie kippt. So taucht es nie wieder
        # als "neu" auf. (Der Wegfall steht nur im Lauf-Protokoll.)
        new_state[key] = prev
    return buckets, new_state


# ----------------------------------------------------------------------------
# Ausgabe
# ----------------------------------------------------------------------------

def esc(text) -> str:
    """HTML-Sonderzeichen für Telegram (parse_mode=HTML) entschärfen."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def fmt_series(s, is_anchor):
    base = f'{s["hits"]}/{s["window"]}' if s["window"] > s["hits"] else f'{s["hits"]} in Folge'
    scope = "" if s["kind"] == "gesamt" else f' {s["kind"]}'
    star = " ⚓" if is_anchor else ""
    return f"{base}{scope}{star}"


def fmt_odds_tail(s) -> str:
    if s.get("range"):
        return f"💰 {fmt_range(s['range'])}"
    if s.get("quote"):
        return f"💰 {s['quote']:.2f}"
    if s.get("unchecked"):
        return "❓ Quoten nicht prüfbar, selbst nachsehen"
    return ""


SEP = "─────────────────"
BANNER = "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩"   # Nachrichten-Anfang, weithin sichtbar
FOOTER = "🔻🔻🔻"                        # Nachrichten-Ende


STATUS_ICON = {"new": "🆕", "known": "▸", "changed": "🔄", "same": "🔁", "dropped": "❌"}

# Kompakte Darstellung (Lucios Vorgabe: schnell entscheiden, nur das
# Relevante): Serien, Quoten, Fair-Leiter, Erwartung/Puffer. Langzeitquote,
# eigene/Gegner, Datenbasis und "nächste Linie" stehen nur im Protokoll
# (runs/). COMPACT=0 in der Umgebung zeigt wieder alles.
COMPACT = os.environ.get("COMPACT", "1") != "0"


def build_match_block(match, entries):
    """Ein Spiel mit allen Signalen (jedes mit Status-Symbol) — für
    Handy-Lesbarkeit kurze Zeilen, Wichtiges fett, jede Info auf eigener
    Zeile. entries: [(status, signal_oder_eintrag, grund), ...]"""
    lines = [f"⚽ <b>{esc(match['home'])} – {esc(match['away'])}</b>",
             f"🕒 {match['kickoff']} · {esc(match.get('league', ''))}"]
    for status, s, reason in entries:
        icon = STATUS_ICON[status]
        lines.append("")
        if status == "same":
            odds = (f" · 💰 {fmt_range(s['range'])}" if s.get("range")
                    else " · ❓ Quoten nicht prüfbar")
            lines.append(f"{icon} {esc(s['metric'])} {s['direction']} {s['line']}{odds}"
                         f" · seit {s.get('first_run', '?')}")
            continue
        if status == "dropped":
            odds = f" · 💰 {fmt_range(s['range'])}" if s.get("range") else ""
            lines.append(f"{icon} <s>{esc(s['metric'])} {s['direction']} {s['line']}</s>{odds}"
                         f" · gemeldet {s.get('first_run', '?')}")
            lines.append(f"   <i>{esc(reason)}</i>")
            continue
        lines.append(f"{icon} <b>{esc(s['metric'])} {s['direction']} {s['line']}</b>")
        if not s.get("home_series"):            # alter Eintrag ohne Details
            tail = fmt_odds_tail(s)
            if tail:
                lines.append(f"   {tail}")
            continue
        if COMPACT:
            lines.pop()                       # Kopfzeile neu mit Entscheidung aufbauen
            light = s.get("light") or "⚪"
            new_tag = " 🆕" if status == "new" else ""
            play = light == "🟢"
            mark = "✅" if play else ("❌" if light in ("🟡", "🔴") else "⚪")
            head = f"{mark} <b>{esc(s['metric'])} {s['direction']} {s['line']}</b>{new_tag}"
            if not play and light != "⚪":
                lines.append(head + f" — <i>{esc(s.get('reason', ''))}</i>")
                continue
            fair = s.get("fair_fin") or s.get("fair")
            check = " · <i>Quote selbst prüfen</i>" if s.get("no_odds_check") else ""
            lines.append(head + (f" · Fair {fair:.2f}" if fair else "") + check)
            lines.append(f"   {esc(match['home'])} {fmt_series(s['home_series'], s['home_is_anchor'])}"
                         f" · {esc(match['away'])} {fmt_series(s['away_series'], s['away_is_anchor'])}")
            continue                          # keine Leiter mehr (Lucio, 05.09.)
        lines.append(f"   {esc(match['home'])}: {fmt_series(s['home_series'], s['home_is_anchor'])}")
        lines.append(f"   {esc(match['away'])}: {fmt_series(s['away_series'], s['away_is_anchor'])}")
        tail = fmt_odds_tail(s)
        base = f"📊 {s['valid'][0]}/{s['valid'][1]}" if s.get("valid") else ""
        lines.append(f"   {tail} · {base}" if (tail and base) else f"   {tail or base}")
        lt = s.get("longterm")
        if lt and lt[0] is not None and lt[1] is not None:
            lines.append(f"   📈 Langzeit {lt[0]*100:.0f} % / {lt[1]*100:.0f} %")
        if s.get("ladder"):
            steps = []
            for L, f in s["ladder"]:
                txt = f"{L} {f:.2f}" if f else f"{L} –"
                steps.append(f"<b>{txt}</b>" if L == s["line"] else txt)
            lines.append("   🪜 Fair " + " · ".join(steps))
        elif s.get("fair"):
            lines.append(f"   🪜 Fair ≈ {s['fair']:.2f}")
        if s.get("expect") is not None:
            buf = s["buffer"]
            if s.get("expect_ref") is not None:
                lines.append(f"   🎯 Erwartung {s['expect']} (Ø {s['avg'][0]} / {s['avg'][1]})"
                             f" · mit Schiri <b>{s['expect_ref']}</b> · Puffer {s['buffer_ref']:+.1f}")
            else:
                lines.append(f"   🎯 Erwartung {s['expect']} (Ø {s['avg'][0]} / {s['avg'][1]})"
                             f" · Puffer {buf:+.1f}")
        if s.get("fa"):
            (h1, h2), (a1, a2) = s["fa"]
            lines.append(f"   ↔ {esc(match['home'])} {h1}/{h2} · {esc(match['away'])} {a1}/{a2}")
        if s.get("b365"):
            hc, ov, un = s["b365"]
            lines.append(f"   🏷 bet365 Hauptlinie {hc}: über {ov} / unter {un}")
        if s.get("referee"):
            lines.append(f"   🧑‍⚖️ Schiri {esc(s['referee'])}")
        if s.get("next_line") is not None:
            lines.append(f"   ↳ {s['next_line']} nicht: <i>{esc(s['next_note'])}</i>")
        # Änderungs-Hinweise (change_note) bewusst nicht angezeigt — Lucio
        # will nur die Tagesliste mit 🆕-Markierung; Details stehen in runs/.
    return "\n".join(lines)


def merge_by_kickoff(buckets):
    """Alle vier Blöcke zu EINER Liste je Spiel zusammenführen, strikt nach
    Anstoßzeit sortiert (Lucios Vorgabe: keine Extra-Sektionen)."""
    per_match = {}
    for status in ("new", "changed", "same"):
        for match, sigs in buckets[status]:
            slot = per_match.setdefault(match["id"], {"match": match, "entries": []})
            slot["entries"] += [(status, s, "") for s in sigs]
    for entry, reason in buckets["dropped"]:
        pseudo = {"id": entry["match_id"], "home": entry["home"], "away": entry["away"],
                  "kickoff": entry.get("kickoff", "?"), "league": entry.get("league", ""),
                  "kickoff_ts": entry.get("kickoff_ts", 0)}
        slot = per_match.setdefault(entry["match_id"], {"match": pseudo, "entries": []})
        slot["entries"].append(("dropped", entry, reason))
    order = {"new": 0, "changed": 1, "same": 2, "dropped": 3}
    result = []
    for slot in sorted(per_match.values(),
                       key=lambda x: (x["match"].get("kickoff_ts", 0), x["match"]["home"])):
        slot["entries"].sort(key=lambda e: (order[e[0]], e[1].get("metric", "")))
        result.append((slot["match"], slot["entries"]))
    return result


def day_list(buckets, new_state):
    """Alle Signale des Tages (aus dem Gedächtnis) als
    [(match, [(status, signal, ""), ...])] — neue zuerst markiert, strikt
    nach Anstoßzeit. Aktuelle Daten haben Vorrang vor gespeicherten."""
    current = {}
    for status in ("new", "changed", "same"):
        for match, sigs in buckets[status]:
            for s in sigs:
                current[signal_key(match, s)] = (status, match, s)
    per_match = {}
    for key, entry in new_state.items():
        if key in current:
            status, match, s = current[key]
            status = "new" if status == "new" else "known"
        else:
            match = {"id": entry["match_id"], "home": entry["home"], "away": entry["away"],
                     "kickoff": entry.get("kickoff", "?"), "league": entry.get("league", ""),
                     "kickoff_ts": entry.get("kickoff_ts", 0)}
            s = dict(entry.get("signal") or {})
            s.setdefault("metric", entry.get("metric", "?"))
            s.setdefault("direction", entry.get("direction", "?"))
            s.setdefault("line", entry.get("line", "?"))
            if s.get("range") is None and entry.get("range"):
                s["range"] = entry["range"]
            status = "known"
        slot = per_match.setdefault(match["id"], {"match": match, "entries": []})
        slot["entries"].append((status, s, ""))
    order = {"new": 0, "known": 1}
    lorder = {"🟢": 0, "🟡": 1, "🔴": 2}
    result = []
    for slot in sorted(per_match.values(),
                       key=lambda x: (x["match"].get("kickoff_ts", 0), x["match"]["home"])):
        slot["entries"].sort(key=lambda e: (lorder.get(e[1].get("light"), 1),
                                            order[e[0]], e[1].get("metric", "")))
        result.append((slot["match"], slot["entries"]))
    return result


def build_recommendations(items):
    """Abschlussliste: nur die 🟢-Märkte, nach Anstoßzeit."""
    rows = []
    for match, entries in items:
        for status, s, _ in entries:
            if s.get("light") != "🟢":
                continue
            fair = s.get("fair_fin") or s.get("fair")
            tail = f" · Fair {fair:.2f}" if fair else ""
            new_tag = " 🆕" if status == "new" else ""
            rows.append(f"• {match['kickoff']} {esc(match['home'])} – {esc(match['away'])}: "
                        f"<b>{esc(s['metric'])} {s['direction']} {s['line']}</b>{tail}{new_tag}")
    head = f"{SEP}\n<b>✅ SPIELEN ({len(rows)})</b>\n{SEP}"
    return head + "\n" + ("\n".join(rows) if rows else "<i>heute nichts</i>")


def assemble_report(buckets, run_label, new_state=None, deferred_note=None):
    """Baut die Telegram-Nachricht(en); None = nichts zu melden.
    Liefert Liste von HTML-Text-Stücken (<= ~3500 Zeichen)."""
    n = {k: sum(len(sigs) for _, sigs in v) for k, v in buckets.items() if k != "dropped"}
    n["dropped"] = len(buckets["dropped"])
    total = n["new"] + n["changed"] + n["same"]
    parts_summary = []
    if n["new"]:
        parts_summary.append(f"🆕 {n['new']} neu")
    if n["changed"]:
        parts_summary.append(f"🔄 {n['changed']} geändert")
    if n["same"]:
        parts_summary.append(f"🔁 {n['same']} unverändert")
    if n["dropped"]:
        parts_summary.append(f"❌ {n['dropped']} weggefallen")
    summary = " · ".join(parts_summary) or "keine"

    # Lucios Vorgabe: JEDE Nachricht zeigt ALLE Signale des Tages (bis
    # Anpfiff), strikt nach Anstoßzeit; neue seit dem letzten Lauf tragen
    # 🆕, der Rest ▸. Geändert/weggefallen wird nicht extra ausgewiesen.
    items = day_list(buckets, new_state or {})
    total_day = sum(len(e) for _, e in items)
    if not total_day:
        return None
    legend = ("<i>⚓ Anker · 💰 Quoten · 🪜 faire Quote je Linie · 🎯 erwartete Spielsumme</i>"
              if COMPACT else
              "<i>⚓ Anker · 📊 Datenbasis · 💰 Quoten · 📈 Trefferquote Historie (jüngere "
              "Spiele stärker) · 🪜 faire Quote je Linie · 🎯 erwartete Spielsumme · "
              "↔ eigene/Gegner Ø</i>")
    lights = {"🟢": 0, "🟡": 0, "🔴": 0}
    for _, entries in items:
        for _, s, _ in entries:
            if s.get("light") in lights:
                lights[s["light"]] += 1
    lcount = f"✅ {lights['🟢']} spielen · ❌ {lights['🟡'] + lights['🔴']} nicht"
    legend = ("<i>✅ spielen · ❌ nicht spielen · 🪜 faire Quote je Linie, "
              "gegen deinen Bookie halten</i>") if COMPACT else legend
    if COMPACT:
        # Lucios Vorgabe (05.09.): nur ✅-Märkte, keine ❌, keine Leiter,
        # keine Abschlussliste. Spiele ohne grünen Markt entfallen.
        items = [(m, [e for e in entries if e[1].get("light") == "🟢"]) for m, entries in items]
        items = [(m, entries) for m, entries in items if entries]
        n_new_green = sum(1 for _, entries in items for st, _, _ in entries if st == "new")
        if not items:
            extra = (f"\n⏳ {deferred_note[0]} Spiele wegen API-Limit auf den nächsten Lauf verschoben"
                     if deferred_note else "")
            return [f"🟨🟨🟨 <b>TREND-SCAN {run_label}</b> 🟨🟨🟨\n"
                    f"✅ heute nichts Spielbares{extra}"]
        head = f"✅ {lights['🟢']} spielbar heute · 🆕 {n_new_green} neu seit letztem Lauf"
        if deferred_note:
            head += (f"\n⏳ {deferred_note[0]} Spiele wegen API-Limit auf den nächsten Lauf "
                     f"verschoben (ab {deferred_note[1]})")
        blocks = [head]
        blocks += [build_match_block(m, e) for m, e in items]
    else:
        blocks = [f"📊 {total_day} Signale heute · 🆕 {n['new']} neu · {lcount}\n{legend}"]
        blocks += [build_match_block(m, e) for m, e in items]
        blocks.append(build_recommendations(items))

    # Telegram erlaubt max. 4096 Zeichen pro Nachricht -> stückeln
    chunks, current = [], blocks[0]
    for block in blocks[1:]:
        if len(current) + len(block) + 2 > 3300:
            chunks.append(current)
            current = block
        else:
            current += "\n\n" + block
    chunks.append(current)
    # Auffälliger Kopf und Fuß je Nachricht, damit man beim Scrollen sofort
    # sieht, wo eine Nachricht beginnt und endet.
    total_parts = len(chunks)
    out = []
    for i, c in enumerate(chunks, 1):
        head = (f"{BANNER}\n"
                f"🟩 <b>TREND-SCAN {run_label}</b> · Teil {i}/{total_parts}\n"
                f"{BANNER}")
        foot = f"{FOOTER} Ende Teil {i}/{total_parts} {FOOTER}"
        out.append(f"{head}\n\n{c}\n\n{foot}")
    return out


def send_telegram(text: str) -> bool:
    if not (TG_TOKEN and TG_CHAT):
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text,
                                   "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as exc:
        print(f"Telegram-Fehler: {exc}", file=sys.stderr)
        return False


# ----------------------------------------------------------------------------
# Hauptlauf
# ----------------------------------------------------------------------------

def attach_extras(match, signals):
    """Zusatzinfos, die nur für Spiele mit Signalen Anfragen kosten:
    - Ecken-Signale: bet365-Hauptlinie mit Quote (Markt 1_4 "Asian Corners")
    - Karten/Fouls-Signale: angesetzter Schiedsrichter + sein Profil aus dem Cache
    Fehler hier dürfen den Lauf nie stoppen."""
    keys = {s["metric_key"] for s in signals}
    if keys & {"corners", "ht_corners"}:
        try:
            odds = api_get("/v2/event/odds", event_id=match["id"])
            allodds = (odds.get("results") or {}).get("odds") or {}
            for mkey, mk in (("corners", "1_4"), ("ht_corners", "1_7")):
                rows = allodds.get(mk) or []
                if rows:
                    r = rows[0]
                    b = (r.get("handicap"), r.get("over_od"), r.get("under_od"))
                    for s in signals:
                        if s["metric_key"] == mkey:
                            s["b365"] = b
                            if B365_AS_PROOF and not s.get("range"):   # Oder-Regel (aus)
                                try:
                                    s["range"] = (float(r.get("over_od")), float(r.get("under_od")))
                                    s.pop("unchecked", None)
                                except (TypeError, ValueError):
                                    pass
        except Exception as exc:
            print(f"  Quoten-Abfrage {match['home']}–{match['away']}: {exc}")
    if keys & {"yellowcards", "fouls", "ht_yellowcards"}:
        try:
            view = api_get("/v1/event/view", event_id=match["id"])
            res = (view.get("results") or [{}])[0]
            ref = ((res.get("extra") or {}).get("referee")) or {}
            if ref.get("id"):
                note = referee_note(ref["id"], ref.get("name", "?"))
                for s in signals:
                    if s["metric_key"] in ("yellowcards", "fouls", "ht_yellowcards"):
                        s["referee"] = note
                        f = referee_factor(ref["id"], s["metric_key"])
                        if f and s.get("expect") is not None:
                            adj = round(s["expect"] * f, 1)
                            s["expect_ref"] = adj
                            s["buffer_ref"] = round(adj - s["line"] if s["direction"] == "über"
                                                    else s["line"] - adj, 1)
        except Exception as exc:
            print(f"  Schiri-Abfrage {match['home']}–{match['away']}: {exc}")


def backfill(cache, hcache=None):
    """Nachlade-Lauf: frischt veraltete Cache-Einträge NUR für die Teams auf,
    die heute oder morgen spielen (alles andere wird nie gebraucht — der
    Cache hält weit über 100.000 Spiele). Bricht am Stundenlimit ab."""
    global _no_wait
    _no_wait = True
    now = now_berlin()
    end = (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    matches = fetch_matches_in_window(now, end)
    teams = []
    seen = set()
    for m in matches:
        for tid in (m["home_id"], m["away_id"]):
            if tid not in seen:
                seen.add(tid)
                teams.append(tid)
    need_set = set()
    hc = hcache if hcache is not None else {}
    for tid in teams:
        entry = hc.get(str(tid))
        if not entry:
            continue                       # Liste unbekannt -> holt der normale Lauf
        for e in entry["events"]:
            slim = cache.get(e["id"])
            if slim is not None and slim.get("x") != CACHE_VERSION:
                need_set.add(e["id"])
    need = sorted(need_set)
    print(f"NACHLADEN: {len(need)} veraltete Spiele für {len(teams)} Teams (heute+morgen), "
          f"Cache gesamt {len(cache)}")
    chunks = [need[i:i + 10] for i in range(0, len(need), 10)]
    done = 0

    def work(chunk):
        view = api_get("/v1/event/view", event_id=",".join(chunk))
        got = set()
        for ev in view.get("results", []):
            with _cache_lock:
                cache[ev["id"]] = slim_event(ev)
            got.add(ev["id"])
        for eid in chunk:                     # nicht mehr abrufbar -> nicht ewig neu versuchen
            if eid not in got:
                with _cache_lock:
                    cache[eid]["x"] = CACHE_VERSION
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(work, c) for c in chunks]
        for fut in as_completed(futures):
            done += 1
            try:
                fut.result()
            except BudgetExhausted:
                pass
            except Exception as exc:
                print(f"  Fehler: {exc}")
            if done % 50 == 0:
                save_cache(cache)
                print(f"  ... {done}/{len(chunks)} Pakete, {_request_count} Anfragen", flush=True)
    save_cache(cache)
    rest = sum(1 for eid in need if cache.get(eid, {}).get("x") != CACHE_VERSION)
    print(f"Nachladen fertig: {_request_count} Anfragen, noch {rest} relevante Spiele veraltet"
          + (" — Stundenlimit erreicht, bitte später erneut starten" if _budget_exhausted else ""))


# ----------------------------------------------------------------------------
# Inventar-Modus (06.09., Lucio): "welche Märkte / Daten gibt es pre-match?"
# Fragt für eine Stichprobe heutiger Spiele alles ab, was die API hergibt,
# und schreibt eine Übersicht nach runs/inventar_<Datum>.txt + Telegram.
# ----------------------------------------------------------------------------

INV_SAMPLE = 40          # Stichprobe kommender Spiele (max. 2 je Liga)
INV_ENDED = 30           # beendete Spiele für die Statistik-Felder

ODDS_MARKET_NAMES = {
    "1_1": "1X2 (Sieg/Remis/Niederlage)", "1_2": "Asian Handicap",
    "1_3": "Tore über/unter", "1_4": "Ecken (Asian Corners)",
    "1_5": "1. HZ 1X2", "1_6": "1. HZ Asian Handicap",
    "1_7": "1. HZ Ecken (Asian Corners)", "1_8": "1. HZ Tore über/unter",
}
STAT_FIELD_NAMES = {
    "corners": "Ecken", "corner_h": "Ecken 1. HZ", "corner_f": "Ecken 2. HZ",
    "yellowcards": "Gelbe Karten", "redcards": "Rote Karten",
    "yellowred_cards": "Gelb-Rote Karten", "on_target": "Schüsse aufs Tor",
    "off_target": "Schüsse daneben", "shots_blocked": "geblockte Schüsse",
    "goalattempts": "Torschüsse gesamt", "fouls": "Fouls", "offsides": "Abseits",
    "saves": "Paraden", "possession_rt": "Ballbesitz %", "goalkicks": "Abstöße",
    "throwins": "Einwürfe", "freekicks": "Freistöße", "penalties": "Elfmeter",
    "substitutions": "Auswechslungen", "crosses": "Flanken", "attacks": "Angriffe",
    "dangerous_attacks": "gefährliche Angriffe", "passing_accuracy": "Passquote",
    "key_passes": "Schlüsselpässe", "assists": "Vorlagen", "action_areas": "Spielzonen",
    "xg": "xG", "injuries": "Verletzungen", "ball_safe": "Ballsicherungen",
}


def _walk_market_names(node, out, depth=0):
    """Sammelt alle 'name'-Werte aus einer bet365-Prematch-Antwort (robust
    gegen Strukturänderungen: jedes dict mit 'sp' → Märkte darunter)."""
    if depth > 8:
        return
    if isinstance(node, dict):
        sp = node.get("sp")
        if isinstance(sp, dict):
            for mk, mv in sp.items():
                if isinstance(mv, dict) and mv.get("name"):
                    out[mv["name"]] += 1
                elif isinstance(mv, list):
                    out[mk] += 1
                else:
                    out[mk] += 1
        for v in node.values():
            _walk_market_names(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_market_names(v, out, depth + 1)


def inventory():
    """Vollständige Pre-Match-Bestandsaufnahme: welche Quoten-Märkte, welche
    Buchmacher, welche Statistik-Felder liefert die API? Kostet ~120 Anfragen."""
    from collections import Counter, defaultdict
    global _no_wait
    _no_wait = True
    now = now_berlin()
    lines = [f"INVENTAR pre-match · {now.strftime('%d.%m.%Y %H:%M')} deutscher Zeit", ""]
    try:
        all_matches = fetch_matches_in_window()
    except BudgetExhausted:
        print("Stundenbudget schon erschöpft – bitte später starten")
        return
    all_matches.sort(key=lambda m: m.get("kickoff_ts", 0))
    per_league = Counter(m["league"] for m in all_matches)
    sample, seen = [], Counter()
    for m in all_matches:
        if seen[m["league"]] < 2:
            seen[m["league"]] += 1
            sample.append(m)
        if len(sample) >= INV_SAMPLE:
            break
    lines.append(f"{len(all_matches)} Spiele im Prüffenster, {len(per_league)} Ligen; "
                 f"Stichprobe {len(sample)} Spiele (max. 2 je Liga).")
    lines.append("")

    # 1) /v2/event/odds (bet365) — welche Marktgruppen sind gefüllt?
    odds_hits = Counter()
    odds_examples = {}
    n_odds = 0
    # 2) /v1/event/odds_summary — welche Buchmacher, welche Märkte
    bk_hits = defaultdict(Counter)
    n_sum = 0
    # 3) /v1/bet365/prematch — voller bet365-Marktkatalog (falls im Paket)
    pm_names = Counter()
    n_pm = 0
    pm_error = None
    pm_tried = 0
    try:
        for m in sample:
            try:
                odds = api_get("/v2/event/odds", event_id=m["id"])
                n_odds += 1
                allodds = (odds.get("results") or {}).get("odds") or {}
                for mk, rows in allodds.items():
                    if rows:
                        odds_hits[mk] += 1
                        odds_examples.setdefault(mk, (m, rows[0]))
            except BudgetExhausted:
                raise
            except Exception as exc:
                print(f"  odds {m['home']}–{m['away']}: {exc}")
            try:
                summ = api_get("/v1/event/odds_summary", event_id=m["id"])
                n_sum += 1
                for bk, node in (summ.get("results") or {}).items():
                    if not isinstance(node, dict):
                        continue
                    for mk, rows in (node.get("odds") or {}).items():
                        if rows:
                            bk_hits[bk][mk] += 1
            except BudgetExhausted:
                raise
            except Exception as exc:
                print(f"  odds_summary {m['home']}–{m['away']}: {exc}")
            if m.get("bet365_id") and pm_tried < 15 and not (pm_error and pm_tried >= 3):
                pm_tried += 1
                try:
                    pm = api_get("/v1/bet365/prematch", FI=m["bet365_id"])
                    n_pm += 1
                    _walk_market_names(pm.get("results") or [], pm_names)
                except BudgetExhausted:
                    raise
                except Exception as exc:
                    pm_error = str(exc)
                    print(f"  prematch {m['home']}–{m['away']}: {exc}")
            print(f"  {m['kickoff']} {m['home']} – {m['away']} ({m['league']}) ✓", flush=True)

        # 4) Statistik-Felder aus beendeten Spielen
        stat_hits = Counter()
        extra_hits = Counter()
        n_view = 0
        day = (now - timedelta(days=1)).astimezone(timezone.utc).strftime("%Y%m%d")
        ended = api_get("/v3/events/ended", sport_id=1, day=day, per_page=100,
                        page=1, skip_esports=1).get("results") or []
        ended = [e for e in ended if "esoccer" not in ((e.get("league") or {}).get("name", "").lower())]
        ids = [e["id"] for e in ended[:INV_ENDED]]
        for i in range(0, len(ids), 10):
            view = api_get("/v1/event/view", event_id=",".join(ids[i:i + 10]))
            for ev in view.get("results") or []:
                n_view += 1
                for k, v in (ev.get("stats") or {}).items():
                    if v not in (None, "", [], {}):
                        stat_hits[k] += 1
                extra = ev.get("extra") or {}
                for k in ("referee", "stadium", "length", "weather", "pitch",
                          "home_manager", "away_manager", "attendance"):
                    if extra.get(k):
                        extra_hits[k] += 1
                if ev.get("events"):
                    extra_hits["events (Ereignis-Verlauf)"] += 1
                if ev.get("lineup") or ev.get("has_lineup"):
                    extra_hits["lineup"] += 1
    except BudgetExhausted:
        lines.append("⚠️ Stundenbudget erreicht – Inventar unvollständig.")
        stat_hits, extra_hits, n_view = Counter(), Counter(), 0

    # ---- Bericht ----
    lines.append(f"1) QUOTEN-MÄRKTE bet365 (/v2/event/odds), {n_odds} Spiele geprüft")
    if odds_hits:
        for mk in sorted(odds_hits, key=lambda k: -odds_hits[k]):
            name = ODDS_MARKET_NAMES.get(mk, mk)
            m, r = odds_examples[mk]
            ex = f" · z.B. {m['home']}–{m['away']}: Linie {r.get('handicap')} {r.get('over_od')}/{r.get('under_od')}" \
                if r.get("handicap") is not None else ""
            lines.append(f"   {name}: {odds_hits[mk]}/{n_odds}{ex}")
    else:
        lines.append("   keine Quoten")
    lines.append("")
    lines.append(f"2) BUCHMACHER (/v1/event/odds_summary), {n_sum} Spiele geprüft")
    for bk in sorted(bk_hits, key=lambda b: -sum(bk_hits[b].values())):
        parts = ", ".join(f"{ODDS_MARKET_NAMES.get(mk, mk)} {c}" for mk, c in
                          sorted(bk_hits[bk].items()))
        lines.append(f"   {bk}: {parts}")
    lines.append("")
    lines.append(f"3) bet365 PREMATCH-KATALOG (/v1/bet365/prematch), {n_pm} Spiele")
    if pm_names:
        for name, c in pm_names.most_common(80):
            lines.append(f"   {name}: {c}/{n_pm}")
    elif pm_error:
        lines.append(f"   nicht abrufbar: {pm_error}")
        lines.append("   (→ gehört vermutlich zum separaten Bet365-API-Paket)")
    else:
        lines.append("   keine bet365-IDs in der Stichprobe")
    lines.append("")
    lines.append(f"4) STATISTIK-FELDER (/v1/event/view), {n_view} beendete Spiele von gestern")
    for k, c in stat_hits.most_common():
        lines.append(f"   {k} = {STAT_FIELD_NAMES.get(k, '?')}: {c}/{n_view}")
    if extra_hits:
        lines.append("   Zusatzdaten: " + ", ".join(f"{k} {c}/{n_view}" for k, c in extra_hits.most_common()))
    lines.append("")
    lines.append(f"{_request_count} Anfragen.")
    text = "\n".join(lines)
    print("\n" + text)
    RUNS_DIR.mkdir(exist_ok=True)
    out = RUNS_DIR / f"inventar_{now.strftime('%Y-%m-%d')}.txt"
    out.write_text(text, encoding="utf-8")
    print(f"→ {out}")
    # Telegram: gekürzt (Katalog auf 40 Zeilen), in Teilen
    tg = "📋 <b>INVENTAR pre-match</b>\n<pre>" + esc("\n".join(lines[2:])) + "</pre>"
    chunks, cur = [], ""
    for ln in tg.split("\n"):
        if len(cur) + len(ln) + 1 > 3300:
            chunks.append(cur + "</pre>")
            cur = "<pre>" + ln
        else:
            cur += ("\n" if cur else "") + ln
    chunks.append(cur)
    for i, ch in enumerate(chunks, 1):
        send_telegram(f"{ch}\n<i>Teil {i}/{len(chunks)}</i>" if len(chunks) > 1 else ch)


def is_prewarm_run() -> bool:
    if os.environ.get("PREWARM") == "1":
        return True
    # Nachtfenster 23:00–06:00: Vorwärm-Läufe 23:17 / 01:17 / 03:17 / 05:17.
    # (Der 21:11-Bericht müsste sich um fast 2 Stunden verspäten, um hier
    # hineinzurutschen — bisher nie vorgekommen.)
    h = now_berlin().hour
    return h >= 23 or h < PREWARM_BEFORE_HOUR


def prewarm(cache, hcache):
    """Vorwärm-Lauf: nur Statistiken für die Spiele des Tages laden.
    Bricht am Stundenlimit sofort ab (kein Warten), speichert den Cache."""
    global _no_wait
    _no_wait = True
    now, end = prewarm_window()
    matches = fetch_matches_in_window(now, end)
    print(f"VORWÄRMEN: {len(matches)} Spiele bis {end:%a %H:%M}, "
          f"{len(cache)} Spiele im Statistik-Cache")
    teams = []
    seen = set()
    for m in matches:                       # in Anstoß-Reihenfolge, damit die
        for tid in (m["home_id"], m["away_id"]):   # frühen Spiele zuerst warm sind
            if tid not in seen:
                seen.add(tid)
                teams.append(tid)
    done = 0

    def warm(tid):
        fetch_team_history(tid, cache, hcache)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(warm, tid) for tid in teams]
        for fut in as_completed(futures):
            done += 1
            try:
                fut.result()
            except BudgetExhausted:
                pass
            except Exception as exc:
                print(f"  Team übersprungen: {exc}")
            if done % 100 == 0:
                save_cache(cache)
                save_history_cache(hcache)
                print(f"  ... {done}/{len(teams)} Teams, {_request_count} Anfragen", flush=True)
    save_cache(cache)
    save_history_cache(hcache)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    now_utc = datetime.now(timezone.utc)
    (RUNS_DIR / f"{now_utc:%Y-%m-%d_%H%M}_prewarm.json").write_text(json.dumps({
        "run_utc": now_utc.isoformat(timespec="seconds"), "prewarm": True,
        "matches": len(matches), "teams": len(teams), "requests": _request_count,
        "budget_exhausted": _budget_exhausted}, indent=1))
    print(f"Vorwärmen fertig: {len(teams)} Teams, {_request_count} Anfragen"
          + (" — Stundenlimit erreicht, Rest holt der nächste Lauf" if _budget_exhausted else ""))


def run():
    if not TOKEN:
        sys.exit("BETSAPI_TOKEN fehlt")
    cache = load_cache()
    hcache = load_history_cache()
    _base_rates.update(compute_base_rates(cache))
    _ref_stats.update(compute_referee_stats(cache))
    _base_means.update(compute_base_means(cache))
    if os.environ.get("BACKFILL") == "1":
        backfill(cache, hcache)
        return
    if os.environ.get("INVENTORY") == "1":
        inventory()
        return
    if is_prewarm_run():
        prewarm(cache, hcache)
        return
    global _no_wait
    state = load_state()
    # ausgeschlossene Märkte und Einträge alter Gedächtnis-Versionen werfen
    def _line_ok(v):
        lines = METRICS.get(v.get("metric_key"), (None, []))[1]
        return v.get("line") in lines            # gestrichene Linien (z.B. Ecken 6,5) raus
    state = {k: v for k, v in state.items()
             if (v.get("metric_key"), v.get("direction")) not in EXCLUDED_MARKETS
             and v.get("v") == STATE_VERSION and _line_ok(v)}
    matches = fetch_matches_in_window()
    # Anstoß-Reihenfolge: frühe Spiele zuerst. Am API-Limit wird NICHT
    # gewartet (kostet nur GitHub-Minuten) — der Rest wandert in den
    # nächsten Lauf (06.09.: 2-Stunden-Lauf am Sonntagmorgen).
    matches.sort(key=lambda m: m.get("kickoff_ts", 0))
    _no_wait = True
    deferred = []
    n_ht = sum(1 for s in cache.values() if s.get("ht_corners") is not None)
    n_htc = sum(1 for s in cache.values() if s.get("ht_yellowcards") is not None)
    print(f"{len(matches)} Spiele im Prüffenster ({WORKERS} parallel), "
          f"{len(state)} Signale im Lauf-Gedächtnis, "
          f"{len(hcache)} Team-Spiellisten im Tages-Cache, "
          f"Cache: {len(cache)} Spiele, davon {n_ht} mit HZ-Ecken, {n_htc} mit HZ-Karten")
    all_hits = []
    checked_ids = set()
    gate_dropped = set()     # Signale, die statistisch noch stehen, deren
                             # Quoten-Markt bei scores24 aber weg ist
    unverifiable = set()     # Signale, deren scores24-Seite nicht zuordenbar war

    def check(match):
        hist_home = fetch_team_history(match["home_id"], cache, hcache)
        hist_away = fetch_team_history(match["away_id"], cache, hcache)
        signals = evaluate_match(match, hist_home, hist_away)
        gated_out, unverifiable = [], []
        before = {signal_key(match, s) for s in signals}
        # 1) scores24: Verfügbarkeits-Näherung je Marktfamilie (keine Werte).
        #    Ecken/HZ-Ecken ohne Reiter bleiben markiert (zweite Chance bet365).
        if signals and GATE_ENABLED:
            groups = s24_fetch_groups(match)
            signals = apply_s24_gate(signals, groups)
        if signals:
            # 2) Zusatzabfragen: bet365-Linie (kann den Nachweis liefern),
            #    Schiedsrichter-Profil
            attach_extras(match, signals)
            # 3) Oder-Regel: weder scores24 noch bet365 -> raus
            if GATE_ENABLED:
                unverifiable = [signal_key(match, s) for s in signals if not s.get("range")]
                signals = [s for s in signals if s.get("range")]
                gated_out = sorted(before - {signal_key(match, s) for s in signals}
                                   - set(unverifiable))
            # 4) Bewertung + Mindest-Fair
            for s in signals:
                assess_signal(s)
            signals = [s for s in signals
                       if (s.get("fair_fin") or s.get("fair") or 0) >= MIN_FAIR]
        return signals, gated_out, unverifiable

    done = 0
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(check, m): m for m in matches}
        for fut in as_completed(futures):
            match = futures[fut]
            done += 1
            try:
                signals, gated_out, unverif = fut.result()
            except BudgetExhausted:
                deferred.append(match)
                continue
            except Exception as exc:
                print(f"  überspringe {match['home']}–{match['away']}: {exc}")
                continue
            checked_ids.add(match["id"])
            gate_dropped.update(gated_out)
            unverifiable.update(unverif)
            for line in match.pop("_contra", []):
                print(f"  {match['home']} – {match['away']}: {line}")
            if signals:
                all_hits.append((match, signals))
                print(f"  TREFFER: {match['home']} – {match['away']} ({len(signals)})")
            if done % 100 == 0:
                save_cache(cache)
                save_history_cache(hcache)
                print(f"  ... {done}/{len(matches)} geprüft, {_request_count} Anfragen, "
                      f"{int(time.time() - t_start)} s, {_cold_teams[0]} Teams nachgeladen",
                      flush=True)
    save_cache(cache)
    save_history_cache(hcache)
    # feste Sortierung nach Anstoßzeit (Parallelverarbeitung mischt sonst)
    all_hits.sort(key=lambda h: h[0].get("kickoff_ts", 0))

    # Lauf-Vergleich mit dem Gedächtnis des Vortags/Vorlaufs
    now = datetime.now(timezone.utc)
    run_label = fmt_day_time(now_berlin())
    buckets, new_state = classify_signals(
        state, all_hits, checked_ids, {m["id"] for m in matches},
        int(now.timestamp()), run_label, gate_dropped, unverifiable)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    log = {
        "run_utc": now.isoformat(timespec="seconds"),
        "matches_checked": len(matches),
        "requests": _request_count,
        "hits": [{"match": m, "signals": s} for m, s in all_hits],
        "new": [signal_key(m, s) for m, sigs in buckets["new"] for s in sigs],
        "changed": [signal_key(m, s) for m, sigs in buckets["changed"] for s in sigs],
        "dropped": [f"{e['match_id']}|{e['metric_key']}|{e['direction']}"
                    for e, _ in buckets["dropped"]],
    }
    (RUNS_DIR / f"{now:%Y-%m-%d_%H%M}.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1))

    if deferred:
        print(f"API-Limit erreicht: {len(deferred)} Spiele auf den nächsten Lauf verschoben "
              f"(frühester Anstoß {deferred[0]['kickoff']})")
    chunks = assemble_report(buckets, run_label, new_state,
                             deferred_note=(len(deferred), deferred[0]["kickoff"]) if deferred else None)
    delivered = True
    if chunks:
        if TG_TOKEN and TG_CHAT:
            delivered = all(send_telegram(c) for c in chunks)
        else:
            delivered = False
        if delivered:
            print(f"Telegram: {len(chunks)} Nachricht(en) verschickt")
        else:
            for c in chunks:
                print(c)
    else:
        print("Keine Treffer in diesem Lauf")
    # Gedächtnis erst ganz am Ende sichern — ein abgebrochener Lauf lässt den
    # alten Stand unangetastet (sonst wäre beim nächsten Mal alles "neu").
    # Kam die Nachricht nicht an, bleibt der alte Stand ebenfalls stehen,
    # damit die Signale beim nächsten Lauf erneut als neu erscheinen.
    if delivered or not (TG_TOKEN and TG_CHAT):
        save_state(new_state)
        print(f"Lauf-Gedächtnis: {len(new_state)} Signale gemerkt "
              f"({len(buckets['dropped'])} weggefallen)")
    else:
        print("Telegram-Zustellung fehlgeschlagen — Lauf-Gedächtnis nicht aktualisiert")
    if GATE_ENABLED:
        print(f"scores24: {_s24_stats['ok']} Seiten geladen, "
              f"{_s24_stats['no_link']} ohne Zuordnung, "
              f"{_s24_stats['fetch_fail']} Abruf-Fehler"
              + (f" | letzter Fehler: {_s24_stats['last_error']}"
                 if _s24_stats['last_error'] else ""))
    print(f"Anfragen gesamt: {_request_count} · Dauer {int(time.time() - t_start)} s · "
          f"{_cold_teams[0]} Teams nachgeladen · {len(deferred)} Spiele verschoben")


# ----------------------------------------------------------------------------
# Selbsttest (kein API-Zugriff nötig)
# ----------------------------------------------------------------------------

def _mk(corner_pairs, homes):
    hist = []
    for pair, is_home in zip(corner_pairs, homes):
        hist.append({"stats": {"corners": pair, "yellowcards": [1, 1],
                               "on_target": [4, 3], "offsides": [1, 1],
                               "fouls": [10, 9]},
                     "is_home": is_home, "label": "t"})
    return hist


def selftest():
    ok = True
    H, A = True, False

    # --- Fall 1: Gesamt-Anker (10/11) + zweites Team 5 in Folge -> Signal
    a = _mk([[6, 4], [5, 5], [7, 4], [3, 2], [6, 5], [8, 3], [5, 6],
             [4, 5], [7, 3], [6, 6], [5, 4], [9, 2], [4, 6], [5, 5], [6, 4]],
            [H, A] * 7 + [H])
    b = _mk([[7, 6], [7, 4], [6, 7], [4, 6], [8, 5], [2, 1], [1, 2],
             [2, 2], [1, 0], [2, 1], [0, 1], [1, 1], [2, 0], [1, 1], [0, 0]],
            [A, H] * 7 + [A])
    match = {"home": "A", "away": "B", "league": "Test", "kickoff": "20:00"}
    sig = [s for s in evaluate_match(match, a, b)
           if s["metric"] == "Ecken" and s["direction"] == "über"]
    if not sig or sig[0]["line"] != 8.5:
        print("FEHLER Fall 1: Ecken-über-Signal fehlt/falsche Linie:", sig)
        ok = False
    elif sig[0].get("next_line") != 9.5 or "B" not in sig[0].get("next_note", ""):
        print("FEHLER Fall 1b: Hinweis zur nächststrengeren Linie fehlt:", sig[0].get("next_note"))
        ok = False
    else:
        s1 = sig[0]
        lt = s1.get("longterm")
        if not lt or not (0.8 <= lt[0] <= 1.0) or not (0.2 <= lt[1] <= 0.5):
            print("FEHLER Fall 1c: Langzeitquote unplausibel:", lt)
            ok = False
        if not s1.get("fair") or not (1.2 <= s1["fair"] <= 2.5):
            print("FEHLER Fall 1d: faire Quote unplausibel:", s1.get("fair"))
            ok = False
        if s1.get("expect") is None or s1.get("fa") is None:
            print("FEHLER Fall 1e: Erwartung/Für-Gegen fehlt:", s1.get("expect"), s1.get("fa"))
            ok = False
        lad = s1.get("ladder") or []
        fairs = [f for _, f in lad]
        if [L for L, _ in lad] != [7.5, 8.5] or fairs != sorted(fairs):
            print("FEHLER Fall 1f: Fair-Leiter fehlt/unsortiert:", lad)
            ok = False
        # Gewichtung: Platzverweis-Spiel und altes Spiel zählen weniger
        if game_weight(0, {"stats": {}}) != 1.0 or game_weight(40, {"stats": {}}) >= 0.5 or \
           game_weight(0, {"stats": {"redcards": [1, 0]}}) != RED_CARD_WEIGHT:
            print("FEHLER Fall 1g: Gewichtung falsch")
            ok = False

    # --- Fall 2: Frische-Regel — Aussetzer im jüngsten Spiel bricht Anker
    a2 = _mk([[1, 1]] + [[6, 5]] * 14, [H, A] * 7 + [H])   # jüngstes Spiel Lücke
    sig2 = evaluate_match(match, a2, b)
    if any(s["metric"] == "Ecken" and s["direction"] == "über" and s["home_is_anchor"]
           for s in sig2):
        print("FEHLER Fall 2: Frische-Regel greift nicht")
        ok = False

    # --- Fall 3: Venue-Anker 15 Heimsiege-Serie zählt, 12 reichen nicht
    pairs = []
    homes = []
    for i in range(40):
        is_home = (i % 2 == 0)
        pairs.append([6, 5] if is_home else [1, 1])   # nur Heimspiele treffen über 8.5
        homes.append(is_home)
    a3 = _mk(pairs, homes)                             # 20 Heimspiele, alle Treffer
    anchor, other, _ = team_qualifies(a3, "corners", 8.5, "über", "home")
    if not anchor or anchor["kind"] != "heim" or anchor["hits"] < 15:
        print("FEHLER Fall 3: Heim-Anker (15er) nicht erkannt:", anchor)
        ok = False
    a4 = _mk(pairs[:24], homes[:24])                   # nur 12 Heimspiele
    anchor4, _, _ = team_qualifies(a4, "corners", 8.5, "über", "home")
    if anchor4:
        print("FEHLER Fall 3b: 12 Heimspiele dürfen keinen 15er-Anker ergeben")
        ok = False

    # --- Fall 4: Qualitätsfilter Fouls 0:0
    c = _mk([[5, 5]] * 15, [H] * 15)
    for m in c:
        m["stats"]["fouls"] = [0, 0]
    if metric_total(c[0], "fouls") is not None or metric_total(c[0], "offsides") is not None:
        print("FEHLER Fall 4: Qualitätsfilter Fouls 0:0 greift nicht")
        ok = False

    # --- Fall 4b: gestaffelte Lücken beim zweiten Team
    #  ✓✗✓✗✓✓✓✓✓✓✓✓ : 2 Lücken vor dem 5. Treffer -> 5er-Regel scheitert,
    #  aber 10 Treffer erreicht -> qualifiziert über die 10/2-Staffel
    e = _mk([[6, 5], [1, 1], [6, 5], [1, 1]] + [[6, 5]] * 9,
            [H, A] * 6 + [H])
    _, other_e, _ = team_qualifies(e, "corners", 8.5, "über", "home")
    if not other_e or other_e["hits"] < 10:
        print("FEHLER Fall 4b: 10/12-Staffel beim zweiten Team fehlt:", other_e)
        ok = False
    #  ✓✗✓✗✓ ohne weitere Treffer -> darf NICHT qualifizieren
    f = _mk([[6, 5], [1, 1], [6, 5], [1, 1], [6, 5]] + [[1, 1]] * 8,
            [H, A] * 6 + [H])
    _, other_f, _ = team_qualifies(f, "corners", 8.5, "über", "home")
    if other_f:
        print("FEHLER Fall 4c: 2 Lücken vor dem 10. Treffer dürfen nicht reichen:", other_f)
        ok = False

    # --- Fall 5: ohne Trend beim zweiten Team kein Signal
    d = _mk([[1, 1]] * 15, [A, H] * 7 + [A])
    if any(s["metric"] == "Ecken" and s["direction"] == "über"
           for s in evaluate_match(match, a, d)):
        print("FEHLER Fall 5: Signal trotz fehlendem Trend beim zweiten Team")
        ok = False

    # --- Fall 6: Quoten-Gate
    #  a) Markt existiert nur bei 8.5 mit Quote 1.85 -> Signal mit Quote
    odds_ok = {"corners": {8.5: {"über": 1.85}}, "yellowcards": {},
               "on_target": {}, "offsides": {}, "fouls": {}}
    sig6 = [s for s in evaluate_match(match, a, b, odds_ok)
            if s["metric"] == "Ecken" and s["direction"] == "über"]
    if not sig6 or sig6[0]["line"] != 8.5 or sig6[0].get("quote") != 1.85:
        print("FEHLER Fall 6a: Gate liefert kein Quoten-Signal:", sig6)
        ok = False
    #  b) Quote unter 1.30 -> kein Signal
    odds_low = {"corners": {8.5: {"über": 1.20}}, "yellowcards": {},
                "on_target": {}, "offsides": {}, "fouls": {}}
    if any(s["metric"] == "Ecken" for s in evaluate_match(match, a, b, odds_low)):
        print("FEHLER Fall 6b: Quote 1.20 darf nicht durchs Gate")
        ok = False
    #  c) Regelwerk qualifiziert bei 8.5, Markt nur bei 9.5 -> kein Signal
    #     (die Schnittmenge ist leer, egal wie gut die Quote ist)
    odds_wrong_line = {"corners": {9.5: {"über": 2.10}}, "yellowcards": {},
                       "on_target": {}, "offsides": {}, "fouls": {}}
    sig6c = [s for s in evaluate_match(match, a, b, odds_wrong_line)
             if s["metric"] == "Ecken" and s["direction"] == "über"]
    if any(s["line"] == 9.5 for s in sig6c):
        print("FEHLER Fall 6c: 9.5 qualifiziert statistisch nicht, darf nicht gemeldet werden")
        ok = False

    # --- Fall 7: lockeres scores24-Gate
    g = {"corners": (4, 1.54, 1.92), "cards": (2, 1.12, 1.25)}
    sigs = [
        {"metric": "Ecken", "metric_key": "corners"},
        {"metric": "Gelbe Karten", "metric_key": "yellowcards"},   # Spanne < 1.30
        {"metric": "Fouls", "metric_key": "fouls"},                # kein Reiter
    ]
    kept = apply_s24_gate([dict(s) for s in sigs], g)
    if [s["metric_key"] for s in kept] != ["corners"] or kept[0].get("range") != (1.54, 1.92):
        print("FEHLER Fall 7b: Gate-Anwendung:", kept)
        ok = False
    unmatched = apply_s24_gate([dict(s) for s in sigs], None)
    if len(unmatched) != 3 or not all(s.get("unchecked") for s in unmatched):
        print("FEHLER Fall 7c: unzuordenbare Seite muss markieren, nicht verwerfen")
        ok = False
    if s24_slug("VfL 1899 Osnabrück") != "vfl-1899-osnabruck" or s24_slug("Sheff Utd") != "sheff-utd":
        print("FEHLER Fall 7d: Slug-Bildung:", s24_slug("VfL 1899 Osnabrück"))
        ok = False
    # --- Fall 7e: Namens-Zuordnung ueber die Tagesuebersicht
    slug_body = "sheffield-united-bolton-wanderers"
    if _name_matches_slug("Sheff Utd", slug_body) < 2 or \
       _name_matches_slug("Bolton", slug_body) < 1:
        print("FEHLER Fall 7e: Fuzzy-Zuordnung greift nicht")
        ok = False
    if _name_matches_slug("Preston", "crystal-palace-brighton") != 0:
        print("FEHLER Fall 7f: Fuzzy-Zuordnung matcht falsches Spiel")
        ok = False
    # --- Fall 7g: Mannschafts-Zusätze müssen übereinstimmen
    if variant_tags("FK Jablonec B") != {"res"} or variant_tags("Legia Warsaw II") != {"res"} \
       or variant_tags("SEISA OSA Rheia FC (W)") != {"w"} or variant_tags("Roma U20") != {"u"} \
       or variant_tags("Sheffield United") != set():
        print("FEHLER Fall 7g: Zusatz-Erkennung falsch:",
              variant_tags("FK Jablonec B"), variant_tags("SEISA OSA Rheia FC (W)"))
        ok = False
    want = variant_tags("FK Jablonec B") | variant_tags("Slovan Liberec B")
    if variant_tags("fk-jablonec-slovan-liberec") == want:
        print("FEHLER Fall 7h: B-Team darf nicht auf die Seite der ersten Mannschaft passen")
        ok = False
    if variant_tags("fk-jablonec-b-slovan-liberec-b") != want:
        print("FEHLER Fall 7i: B-Team muss auf die B-Seite passen")
        ok = False

    # --- Fall 8: Gegenläufigkeit nur bei ENGEM Korridor
    #  a) breiter Korridor (über 6,5 + unter 12,5) -> beide Richtungen bleiben
    #  (Heim/Auswärts so gemischt, dass keine Rollen-Gegen-Serie entsteht)
    wide = _mk([[6, 6], [4, 4], [7, 5], [5, 4]] * 4, [H, H, A, A] * 4)[:15]
    saved_excl = set(EXCLUDED_MARKETS)
    EXCLUDED_MARKETS.clear()
    wsig = evaluate_match(match, wide, [dict(x) for x in wide])
    EXCLUDED_MARKETS.update(saved_excl)
    dirs = {s["direction"] for s in wsig if s["metric"] == "Ecken"}
    if dirs != {"über", "unter"}:
        print("FEHLER Fall 8a: breiter Korridor wurde verworfen:", dirs)
        ok = False
    #  c) mit Standard-Konfiguration: unter-Ecken werden nie gemeldet
    wsig2 = evaluate_match(match, wide, [dict(x) for x in wide])
    if any(s["metric"] == "Ecken" and s["direction"] == "unter" for s in wsig2):
        print("FEHLER Fall 8c: unter-Ecken müssen ausgeschlossen sein")
        ok = False
    #  b) enger Korridor (über 8,5 + unter 10,5 bei konstant 9/10 Ecken) -> raus
    tight = _mk([[5, 4], [5, 5]] * 8, [H, A] * 8)[:15]
    tsig = [s for s in evaluate_match(match, tight, [dict(x) for x in tight])
            if s["metric"] == "Ecken"]
    if tsig:
        print("FEHLER Fall 8b: enger Korridor muss verworfen werden:", tsig)
        ok = False

    # --- Fall 9: Lauf-Vergleich (neu / geändert / unverändert / weggefallen)
    def sig(metric_key, direction, line, rng=None, unchecked=False):
        s = {"metric": METRICS[metric_key][0], "metric_key": metric_key,
             "direction": direction, "line": line,
             "home_series": {"kind": "gesamt", "hits": 10, "window": 11},
             "away_series": {"kind": "gesamt", "hits": 6, "window": 6},
             "home_is_anchor": True, "away_is_anchor": False, "valid": (40, 38)}
        if rng:
            s["range"] = rng
        if unchecked:
            s["unchecked"] = True
        return s
    m1 = {"id": "1", "home": "A", "away": "B", "kickoff": "Di 20:00",
          "kickoff_ts": 1_900_050_000, "league": "L"}
    m2 = dict(m1, id="2", home="C", away="D")
    m3 = dict(m1, id="3", home="E", away="F")
    m4 = dict(m1, id="4", home="G", away="H", kickoff_ts=1_000)      # längst angepfiffen
    # erster Lauf: alles neu
    hits1 = [(m1, [sig("corners", "über", 8.5, (1.30, 1.80)),
                   sig("yellowcards", "unter", 4.5, unchecked=True)]),
             (m2, [sig("fouls", "über", 22.5, (1.50, 1.90))]),
             (m3, [sig("offsides", "unter", 4.5, (1.40, 1.60))])]
    b1, st1 = classify_signals({}, hits1, {"1", "2", "3"}, {"1", "2", "3"},
                               1_900_000_000, "Di 06:17")
    if len(b1["new"]) != 3 or b1["changed"] or b1["same"] or b1["dropped"] or len(st1) != 4:
        print("FEHLER Fall 9a: erster Lauf muss alles als neu melden")
        ok = False
    # zweiter Lauf: Quoten geändert, Quoten neu da, unverändert, weggefallen,
    # Spiel aus dem Spielplan verschwunden, altes Spiel angepfiffen
    st1["4|corners|über"] = {"match_id": "4", "home": "G", "away": "H",
                             "kickoff": "Mo 20:00", "kickoff_ts": 1_000,
                             "metric": "Ecken", "metric_key": "corners",
                             "direction": "über", "first_run": "Mo 18:17",
                             "first_line": 8.5, "first_range": None,
                             "line": 8.5, "range": None, "last_run": "Mo 18:17"}
    hits2 = [(m1, [sig("corners", "über", 8.5, (1.45, 2.10)),
                   sig("yellowcards", "unter", 4.5, (1.35, 1.50))]),
             (m2, [sig("fouls", "über", 22.5, (1.50, 1.90)),
                   sig("corners", "unter", 11.5, (1.40, 1.70))])]
    b2, st2 = classify_signals(st1, hits2, {"1", "2"}, {"1", "2"},
                               1_900_000_100, "Di 08:17")
    new_keys = [signal_key(m, s) for m, sigs in b2["new"] for s in sigs]
    chg = {signal_key(m, s): s["change_note"] for m, sigs in b2["changed"] for s in sigs}
    same_keys = [signal_key(m, s) for m, sigs in b2["same"] for s in sigs]
    dropped = {e["match_id"]: r for e, r in b2["dropped"]}
    if new_keys != ["2|corners|unter"]:
        print("FEHLER Fall 9b: neues Signal nicht erkannt:", new_keys)
        ok = False
    if "vorher 1.30–1.80" not in chg.get("1|corners|über", "") or \
       "jetzt da" not in chg.get("1|yellowcards|unter", ""):
        print("FEHLER Fall 9c: Quoten-Änderung nicht markiert:", chg)
        ok = False
    if same_keys != ["2|fouls|über"]:
        print("FEHLER Fall 9d: unverändertes Signal falsch einsortiert:", same_keys)
        ok = False
    if "3" not in dropped or "Spielplan" not in dropped["3"]:
        print("FEHLER Fall 9e: verschwundenes Spiel nicht als weggefallen markiert:", dropped)
        ok = False
    if "3|offsides|unter" not in st2:
        print("FEHLER Fall 9e2: einmal gemeldetes Signal muss bis Anpfiff gemerkt bleiben")
        ok = False
    if "4" in dropped or any(k.startswith("4|") for k in st2):
        print("FEHLER Fall 9f: angepfiffenes Spiel muss stillschweigend vergessen werden")
        ok = False
    if st2["1|corners|über"]["first_range"] != [1.30, 1.80] or \
       st2["1|corners|über"]["range"] != [1.45, 2.10]:
        print("FEHLER Fall 9g: Gedächtnis muss ersten Lauf UND aktuellen Stand kennen")
        ok = False
    # dritter Lauf: Signal von Spiel 1 fällt weg (Spiel geprüft, kein Signal)
    b3, st3 = classify_signals(st2, [(m2, hits2[1][1])], {"1", "2"}, {"1", "2"},
                               1_900_000_200, "Di 10:17", {"1|corners|über"})
    reasons = {f"{e['metric_key']}": r for e, r in b3["dropped"] if e["match_id"] == "1"}
    if set(reasons) != {"corners", "yellowcards"} or not any(k.startswith("1|") for k in st3):
        print("FEHLER Fall 9h: weggefallene Serie nicht erkannt / nicht gemerkt:", b3["dropped"])
        ok = False
    if "Quote rausgenommen" not in reasons.get("corners", "") or \
       "Regelwerk" not in reasons.get("yellowcards", ""):
        print("FEHLER Fall 9k: Wegfall-Grund (Quote vs. Serie) falsch:", reasons)
        ok = False
    b3u, _ = classify_signals(st2, [(m2, hits2[1][1])], {"1", "2"}, {"1", "2"},
                              1_900_000_200, "Di 10:17", set(), {"1|corners|über"})
    r_u = {e["metric_key"]: r for e, r in b3u["dropped"] if e["match_id"] == "1"}
    if "nicht mehr prüfbar" not in r_u.get("corners", ""):
        print("FEHLER Fall 9m: Grund 'nicht prüfbar' fehlt:", r_u)
        ok = False
    report = assemble_report(b2, "Di 08:17", st2)
    txt = "\n".join(report)
    # ohne Bewertung (alte Einträge) gibt es keine Grünen -> Ruhe-Meldung
    if not report or "nichts Spielbares" not in txt:
        print("FEHLER Fall 9i: ohne grüne Märkte muss die Ruhe-Meldung kommen:", txt[:200])
        ok = False
    for s_ in hits2[0][1] + hits2[1][1]:
        s_["light"] = "🟢"
    b2g, st2g = classify_signals(st1, hits2, {"1", "2"}, {"1", "2"}, 1_900_000_100, "Di 08:17")
    txt = "\n".join(assemble_report(b2g, "Di 08:17", st2g))
    for needle in ("spielbar heute", "<b>Ecken unter 11.5</b> 🆕", "<b>Ecken über 8.5</b>",
                   "<b>Fouls über 22.5</b>", "Teil 1/1", "Ende Teil 1/1"):
        if needle not in txt:
            print("FEHLER Fall 9i: Nachricht unvollständig, fehlt:", needle)
            ok = False
    for forbidden in ("Abseits unter 4.5", "🪜", "SPIELEN", "❌"):
        if forbidden in txt:
            print("FEHLER Fall 9i3: darf nicht mehr enthalten sein:", forbidden)
            ok = False
    for forbidden in ("vorher 1.30", "seit Di", "weggefallen", "<s>"):
        if forbidden in txt:
            print("FEHLER Fall 9i2: keine Änderungs-/Wegfall-Hinweise erwünscht, enthält:", forbidden)
            ok = False
    # Reihenfolge: E–F (ts 1_900_050_000) und die anderen gleich -> Name sortiert; ok
    early = dict(m3, id="9", home="Y", away="Z", kickoff="Di 12:00", kickoff_ts=1_900_010_000)
    s_early = sig("corners", "über", 7.5, (1.5, 1.6))
    s_early["light"] = "🟢"
    b_sorted = {"new": [(m2, hits2[1][1][:1]), (early, [s_early])],
                "changed": [], "same": [], "dropped": []}
    _, st_sorted = classify_signals({}, b_sorted["new"], {"2", "9"}, {"2", "9"},
                                    1_900_000_000, "Di 08:17")
    txt_sorted = "\n".join(assemble_report(b_sorted, "Di 08:17", st_sorted))
    if txt_sorted.index("Y – Z") > txt_sorted.index("C – D"):
        print("FEHLER Fall 9l: Meldung nicht nach Anstoßzeit sortiert")
        ok = False
    quiet = assemble_report({"new": [], "changed": [], "same": [(m2, hits2[1][1][:1])],
                             "dropped": []}, "Di 10:17", st2)
    if not quiet or "🆕 0 neu" not in quiet[0] or "<b>Fouls über 22.5</b>" not in quiet[0]:
        print("FEHLER Fall 9j: auch ohne Neues muss die Tagesliste der Grünen kommen:", quiet)
        ok = False
    if assemble_report({"new": [], "changed": [], "same": [], "dropped": []}, "Di 10:17", {}):
        print("FEHLER Fall 9j2: ohne Signale keine Nachricht")
        ok = False
    if "--show" in sys.argv:
        print("\n".join(report))

    # --- Fall 11: Gegenbewegung eines EINZELNEN Teams im engen Korridor
    #  Abseits: beide Teams unter 5.5 (immer 3-5), aber Heimteam zusätzlich
    #  über 4.5 in 7 der letzten 8 (genau 5 Abseits) -> Markt raus
    def _off(vals, homes):
        h = _mk([[5, 5]] * len(vals), homes)
        for m, v in zip(h, vals):
            m["stats"]["offsides"] = [v, 0]
        return h
    pal = _off([5, 5, 5, 3, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5], [H, A] * 7 + [H])
    man = _off([3] * 15, [A, H] * 7 + [A])
    sig11 = [s for s in evaluate_match(dict(match), pal, man) if s["metric"] == "Abseits"]
    if sig11:
        print("FEHLER Fall 11a: Gegenbewegung (über 4.5 bei einem Team) muss unter 5.5 kippen:", sig11)
        ok = False
    #  ohne die Gegen-Serie (Heimteam 2-3 Abseits) bleibt unter 5.5 bestehen
    pal2 = _off([3, 2, 3, 3, 2, 3, 3, 2, 3, 3, 2, 3, 3, 2, 3], [H, A] * 7 + [H])
    man2 = _off([3, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2], [A, H] * 7 + [A])
    sig11b = [s for s in evaluate_match(dict(match), pal2, man2)
              if s["metric"] == "Abseits" and s["direction"] == "unter"]
    if not sig11b:
        print("FEHLER Fall 11b: ohne Gegenbewegung muss das Signal bleiben")
        ok = False

    #  Abseits: Gegenteam immer genau 3 -> über 2.5 UND unter 3.5 gleichzeitig;
    #  Signal unter 5.5 (Heim 4-5) darf davon nicht kippen (Abstand 3 > 1)
    pal3 = _off([5, 4, 5, 4, 5, 4, 5, 4, 5, 4, 5, 4, 5, 4, 5], [H, H, A, A] * 4)
    sig11c = [s for s in evaluate_match(dict(match), pal3, man)
              if s["metric"] == "Abseits" and s["direction"] == "unter"]
    if not sig11c or sig11c[0]["line"] != 5.5:
        print("FEHLER Fall 11c: marktabhängiger Korridor (Abseits=1) greift nicht:", sig11c)
        ok = False

    # --- Fall 13: Ampel-Rechnung
    sA = sig("corners", "über", 8.5, (1.4, 1.7))
    sA.update({"expect": 11.0, "buffer": 2.5, "sd": 2.8, "fair": 1.25,
               "ladder": [[7.5, 1.15], [8.5, 1.25]],
               "p_emp": {"7.5": 1/1.15, "8.5": 1/1.25},
               "b365": ("8.5", "1.50", "2.50")})
    assess_signal(sA)
    if sA["light"] != "🟢" or sA["market_src"] != "bet365" or not (0.75 < sA["p_fin"] < 0.9):
        print("FEHLER Fall 13a: klarer Fall muss grün sein:", sA["light"], sA["reason"], sA["p_fin"])
        ok = False
    sB = dict(sA, expect=7.0, buffer=-1.5, b365=None)
    assess_signal(sB)
    if sB["light"] != "🔴":
        print("FEHLER Fall 13b: Erwartung unter Linie muss rot sein:", sB["light"], sB["reason"])
        ok = False
    sC = dict(sA, b365=("7.5", "1.30", "3.20"))          # Nachbarlinie -> umrechnen
    assess_signal(sC)
    if not str(sC["market_src"]).startswith("bet365 7.5") or not sC["market"]:
        print("FEHLER Fall 13c: Umrechnung über die Leiter fehlt:", sC["market_src"], sC["market"])
        ok = False
    sD = dict(sA, b365=("8.5", "1.10", "3.00"))          # exakter Markt weit unter fair
    assess_signal(sD)
    if sD["light"] != "🔴":
        print("FEHLER Fall 13d: Markt unter fair muss rot sein:", sD["light"], sD["reason"])
        ok = False
    lad = [f for _, f in sA["ladder_fin"]]
    if len(lad) != 2 or lad != sorted(lad):
        print("FEHLER Fall 13e: kombinierte Leiter unsortiert:", sA["ladder_fin"])
        ok = False
    sE = dict(sA, b365=None)                             # nur scores24-Spanne vorhanden
    assess_signal(sE)
    if sE["light"] != "🟢" or sE.get("market") is not None or "fair" not in sE["reason"]:
        print("FEHLER Fall 13f: ohne bet365 darf die Spanne nicht gerechnet werden:", sE["light"], sE.get("market"), sE["reason"])
        ok = False
    rec = build_recommendations([({"kickoff": "Mi 20:30", "home": "P", "away": "M"},
                                  [("new", sE, ""), ("known", sB, "")])])
    if "SPIELEN (1)" not in rec or "über 8.5" not in rec:
        print("FEHLER Fall 13g: Empfehlungsliste falsch:", rec)
        ok = False

    # --- Fall 14: Halbzeit-Daten aus dem Spieldatensatz
    ev14 = {"id": "h1", "home": {"name": "Navua FC"}, "away": {"name": "Nasinu FC"},
            "stats": {"corners": ["6", "2"], "corner_h": ["2", "0"], "yellowcards": ["3", "2"]},
            "events": [{"text": "15' - 1st Goal -   (Nasinu FC) -"},
                       {"text": "35' - 1st Corner - Navua FC"},
                       {"text": "45+5' ~ 1st Yellow Card ~  ~(Nasinu FC)"},
                       {"text": "45+7' - 2nd Corner - Navua FC"},
                       {"text": "Score After First Half - 0-1"},
                       {"text": "47' ~ 2nd Yellow Card ~  ~(Navua FC)"}]}
    sl14 = slim_event(ev14)
    if sl14.get("ht_corners") != [2, 0] or sl14.get("ht_yellowcards") != [0, 1] \
       or sl14.get("x") != CACHE_VERSION:
        print("FEHLER Fall 14a: Halbzeit-Felder falsch:", sl14)
        ok = False
    if parse_ht_cards({"events": [{"text": "12' ~ 1st Yellow Card ~ X ~(A)"}]}) is not None:
        print("FEHLER Fall 14b: ohne Halbzeit-Marker darf es keine HZ-Karten geben")
        ok = False
    #  HZ-Ecken-Signal: beide Teams über 3.5 in der 1. HZ
    def _ht(vals, homes):
        h = _mk([[5, 5]] * len(vals), homes)
        for m, v in zip(h, vals):
            m["stats"]["ht_corners"] = [v, 0]
            m["stats"]["ht_yellowcards"] = [1, 1]
        return h
    hA = _ht([5, 4, 6, 5, 4, 5, 6, 4, 5, 5, 4, 6, 5, 4, 5], [H, H, A, A] * 4)
    hB = _ht([4, 5, 4, 6, 5, 4, 5, 4, 6, 5, 4, 5, 4, 5, 6], [A, A, H, H] * 4)
    sig14 = [s for s in evaluate_match(dict(match), hA, hB) if s["metric_key"] == "ht_corners"]
    if not sig14 or sig14[0]["direction"] != "über" or sig14[0]["line"] != 3.5:
        print("FEHLER Fall 14c: HZ-Ecken-Signal fehlt/falsch:", [(s["direction"], s["line"]) for s in sig14])
        ok = False
    if any(s["metric_key"] == "ht_corners" and s["direction"] == "unter"
           for s in evaluate_match(dict(match), hA, hB)):
        print("FEHLER Fall 14d: unter-HZ-Ecken müssen ausgeschlossen sein")
        ok = False
    #  Gate lässt HZ-Märkte durch, HZ-Karten bekommen "Quote selbst prüfen"
    g14 = apply_s24_gate([{"metric_key": "ht_corners"}, {"metric_key": "ht_yellowcards"},
                          {"metric_key": "fouls"}], {"corners": (2, 1.5, 1.9)})  # Reiter-Namen
    if [s["metric_key"] for s in g14] != ["ht_corners"] or not g14[0].get("range"):
        print("FEHLER Fall 14e: HZ-Ecken nur mit Ecken-Reiter, HZ-Karten nur mit Karten-Reiter:", g14)
        ok = False
    g14c = apply_s24_gate([{"metric_key": "ht_corners"}, {"metric_key": "ht_yellowcards"},
                           {"metric_key": "corners"}], {"fouls": (1, 1.5, 1.6)})
    kept_keys = [s["metric_key"] for s in g14c]
    if B365_AS_PROOF:
        if kept_keys != ["ht_corners", "corners"] or not all(s.get("unchecked") for s in g14c):
            print("FEHLER Fall 14g: Ecken-Märkte ohne Reiter bleiben für die bet365-Prüfung markiert:", g14c)
            ok = False
    elif g14c:
        print("FEHLER Fall 14g: ohne passenden Reiter fliegen alle Märkte (bet365-Zweig aus):", g14c)
        ok = False

    # --- Fall 15: Beitrags-Modell (Angriff x Abwehr)
    #  Heim holt viel (7) und lässt wenig zu (3); Gast holt wenig (3), lässt viel zu (7)
    #  -> Summen-Modell: beide Ø 10 -> 10; Beitrag: 7*7/5 + 3*3/5 = 9.8+1.8 = 11.6
    _base_means["corners"] = 10.0
    hh = _mk([[7, 3]] * 15, [H, A] * 7 + [H])
    ha = _mk([[7, 3]] * 15, [A, H] * 7 + [A])      # als Gast: pair[1]=3 eigene, 7 zugelassen
    mu15 = matchup_expectation(hh, ha, "corners")
    if not mu15 or abs(mu15[0] - 11.6) > 0.05:
        print("FEHLER Fall 15a: Beitrags-Modell falsch:", mu15)
        ok = False
    s15 = sig("corners", "über", 8.5)
    enrich_signal(s15, hh, ha, "corners", "über", 8.5)
    if abs(s15["expect"] - 10.8) > 0.05 or s15.get("contrib") != (9.8, 1.8):
        print("FEHLER Fall 15b: Mischung Summen/Beitrag falsch:", s15.get("expect"), s15.get("contrib"))
        ok = False
    _base_means.pop("corners", None)

    # --- Fall 16: Schüsse gesamt — Feld, Fallback-Summe, Liga-Beschränkung
    if total_shots({"goalattempts": ["12", "9"]}) != [12, 9] or \
       total_shots({"on_target": ["4", "3"], "off_target": ["5", "4"], "shots_blocked": ["2", "1"]}) != [11, 8] or \
       total_shots({"on_target": ["4", "3"], "off_target": ["5", "4"]}) is not None:
        print("FEHLER Fall 16a: Schüsse-gesamt-Berechnung falsch")
        ok = False
    METRIC_LEAGUES["_test"] = ["england premier league"]
    if not metric_allowed_for_league("_test", "England Premier League") or \
       metric_allowed_for_league("_test", "Norway Division 3 Group 5") or \
       not metric_allowed_for_league("corners", "Norway Division 3 Group 5"):
        print("FEHLER Fall 16b: Liga-Beschränkung greift nicht")
        ok = False
    METRIC_LEAGUES.pop("_test", None)
    def _sh(vals, homes):
        h = _mk([[5, 5]] * len(vals), homes)
        for m, v in zip(h, vals):
            m["stats"]["shots_total"] = [v, 0]
        return h
    shA = _sh([31, 27, 33, 26, 32, 29, 34, 27, 31, 28, 33, 26, 32, 29, 31], [H, H, A, A] * 4)
    shB = _sh([27, 32, 26, 33, 29, 31, 27, 34, 28, 31, 26, 33, 29, 32, 27], [A, A, H, H] * 4)
    big = dict(match, league="England Premier League")
    small = dict(match, league="Norway Division 3 Group 5")
    if not any(s["metric_key"] == "shots_total" for s in evaluate_match(big, shA, shB)):
        print("FEHLER Fall 16c: Schüsse-gesamt-Signal in Top-Liga fehlt")
        ok = False
    if not any(s["metric_key"] == "shots_total" for s in evaluate_match(small, shA, shB)):
        print("FEHLER Fall 16d: Schüsse gesamt muss ohne Liga-Liste überall geprüft werden")
        ok = False

    # --- Fall 12: Schiedsrichter/Spieldauer im Cache + Profil
    ev = {"id": "e9", "stats": {"corners": ["5", "4"], "yellowcards": ["3", "2"],
                                "fouls": ["12", "11"], "redcards": ["0", "1"]},
          "extra": {"referee": {"id": 77, "name": "Max Muster"}, "length": 120}}
    sl = slim_event(ev)
    if sl.get("ref") != ["77", "Max Muster"] or sl.get("len") != 120 or sl.get("x") != CACHE_VERSION \
       or sl.get("redcards") != [0, 1]:
        print("FEHLER Fall 12a: slim_event unvollständig:", sl)
        ok = False
    _ref_stats.update(compute_referee_stats({"e9": sl, "e8": dict(sl, yellowcards=[1, 1])}))
    note = referee_note("77", "Max Muster")
    if "Ø 3.5 Karten (2 Sp.)" not in note or "23.0 Fouls" not in note:
        print("FEHLER Fall 12b: Schiri-Profil falsch:", note)
        ok = False
    if game_weight(0, {"stats": sl}) != RED_CARD_WEIGHT * RED_CARD_WEIGHT:
        print("FEHLER Fall 12c: Verlängerung + Platzverweis müssen beide halbieren")
        ok = False
    _base_means.update({"yellowcards": 3.0, "fouls": 23.0})
    f = referee_factor("77", "yellowcards")     # Schiri Ø 3.5 bei Basis 3.0, 2 Spiele -> leicht > 1
    if not f or not (1.0 < f < 1.17):
        print("FEHLER Fall 12d: Schiri-Faktor unplausibel:", f)
        ok = False

    # --- Fall 10: Tages-Cache für Spiellisten + Vorwärm-Abbruch am Limit
    global api_get, _no_wait, _hour_requests, _budget_exhausted
    real_api_get = api_get
    calls = []

    def fake_api_get(path, **params):
        calls.append(path)
        if path == "/v3/events/ended":
            return {"success": 1, "pager": {"total": 2}, "results": [
                {"id": "e1", "home": {"id": "7", "name": "X"}, "away": {"id": "8", "name": "Y"},
                 "league": {"name": "L"}},
                {"id": "e2", "home": {"id": "9", "name": "Z"}, "away": {"id": "7", "name": "X"},
                 "league": {"name": "L"}}]}
        if path == "/v1/event/view":
            return {"success": 1, "results": [
                {"id": i, "stats": {"corners": ["5", "4"], "fouls": ["10", "9"]}}
                for i in params["event_id"].split(",")]}
        raise AssertionError(path)
    api_get = fake_api_get
    try:
        c10, h10 = {}, {}
        hist = fetch_team_history("7", c10, h10)
        first = list(calls)
        hist_b = fetch_team_history("7", c10, h10)
        if first != ["/v3/events/ended", "/v1/event/view"] or len(calls) != 2:
            print("FEHLER Fall 10a: zweiter Abruf muss komplett aus dem Cache kommen:", calls)
            ok = False
        if [m["is_home"] for m in hist] != [True, False] or hist != hist_b or \
           hist[0]["stats"]["corners"] != [5, 4]:
            print("FEHLER Fall 10b: Historie aus Cache falsch:", hist)
            ok = False
        h10["7"]["ts"] -= HISTORY_TTL + 1              # abgelaufen -> neu holen
        fetch_team_history("7", c10, h10)
        if len(calls) != 3 or calls[-1] != "/v3/events/ended":
            print("FEHLER Fall 10c: abgelaufene Spielliste muss neu geholt werden:", calls)
            ok = False
        # Vorwärm-Modus: am Limit sofort abbrechen statt warten
        _no_wait = True
        _hour_requests = HOURLY_BUDGET
        try:
            _budget_guard()
            print("FEHLER Fall 10d: Vorwärm-Lauf muss am Limit abbrechen")
            ok = False
        except BudgetExhausted:
            pass
        if not _budget_exhausted:
            print("FEHLER Fall 10e: Limit-Flag nicht gesetzt")
            ok = False
    finally:
        api_get = real_api_get
        _no_wait = False
        _hour_requests = 0
        _budget_exhausted = False

    print("Selbsttest OK" if ok else "Selbsttest FEHLGESCHLAGEN")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        run()
