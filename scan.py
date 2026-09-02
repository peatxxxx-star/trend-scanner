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
  Head-to-Head spielt keine Rolle.

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

  Gegenläufigkeits-Filter: zeigt eine Metrik qualifizierte Trends in
  BEIDE Richtungen, wird die Metrik komplett verworfen.

  Datenqualität: fehlende Statistik -> Spiel zählt für die Metrik nicht
  (weder Treffer noch Aussetzer). Fouls 0:0 gilt als "nicht erfasst"
  und macht Fouls UND Abseits des Spiels ungültig; Schüsse aufs Tor 0:0
  ebenso für diese Metrik. Ein Team braucht je Metrik mindestens
  MIN_VALID_MATCHES saubere Spiele in der Gesamt-Historie, sonst gibt
  es für die Metrik kein Signal. Meldungen zeigen immer die Datenbasis.

  Lauf-Vergleich (state/reported.json): Jede Meldung ist in vier Blöcke
  geteilt — 🆕 NEU (noch nie gemeldet), 🔄 GEÄNDERT (schon gemeldet, aber
  Linie oder Quoten-Spanne weichen vom ERSTEN Lauf ab; die alten Werte
  stehen dabei), 🔁 BEREITS GEMELDET (unverändert, Kurzform mit "seit
  HH:MM"), ❌ WEGGEFALLEN (früher gemeldet, jetzt nicht mehr erfüllt oder
  Spiel aus dem Spielplan verschwunden). Gibt es weder Neues noch
  Änderungen noch Wegfälle, kommt nur ein Einzeiler "nichts Neues".
  Angepfiffene Spiele werden automatisch vergessen. Das Gedächtnis wird
  nur nach erfolgreicher Zustellung gespeichert.

Benötigte Umgebungsvariablen:
  BETSAPI_TOKEN      – BetsAPI-Token (Soccer API)
  TELEGRAM_BOT_TOKEN – Telegram-Bot-Token (optional; ohne = nur Konsole)
  TELEGRAM_CHAT_ID   – Telegram-Chat-ID  (optional; ohne = nur Konsole)

Aufruf:
  python scan.py               # normaler Lauf (vor 6 Uhr: Vorwärm-Lauf)
  PREWARM=1 python scan.py     # Vorwärm-Lauf erzwingen
  python scan.py --selftest    # Regelwerk-Test ohne API-Zugriff
"""

import json
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
    "offsides": "offsides",
    "fouls": "fouls",
}

# Gegenläufigkeits-Regel: Über- und Unter-Trends derselben Metrik sind nur
# dann ein Widerspruch, wenn ihr Korridor eng ist (z.B. über 8,5 UND
# unter 10,5). Breite Korridore (über 6,5 + unter 12,5) sind legitim —
# bewiesen durch Lucios Wycombe-Wettschein vom 01.09.
CONTRA_GAP = 2.0

# Anfragen-Wächter: BetsAPI erlaubt 3.600 Anfragen/Stunde. Wir bremsen
# rechtzeitig, statt in Fehler zu laufen.
HOURLY_BUDGET = 3300

# Parallele Verarbeitung: so viele Spiele werden gleichzeitig geprüft.
# 16 ist das sinnvolle Maximum: mehr bringt kaum Tempo, erhöht aber das
# Risiko, dass die API einzelne Anfragen abweist. Der Anfragen-Wächter
# bremst vor dem Stundenlimit (3.600/h) automatisch.
WORKERS = 16

# Metriken: BetsAPI-Feldname -> (Anzeigename, Linienbereich)
METRICS = {
    "corners":  ("Ecken",             [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5]),
    "yellowcards": ("Gelbe Karten",   [2.5, 3.5, 4.5, 5.5, 6.5]),
    "on_target": ("Schüsse aufs Tor", [6.5, 7.5, 8.5, 9.5, 10.5, 11.5]),
    "offsides": ("Abseits",           [2.5, 3.5, 4.5, 5.5]),
    "fouls":    ("Fouls",             [18.5, 20.5, 22.5, 24.5, 26.5, 28.5]),
}

CACHE_FILE = Path(__file__).parent / "cache" / "stats.json"
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


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, separators=(",", ":")))


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
    slim = {k: v for k, v in hcache.items() if v.get("ts", 0) >= cutoff}
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
    if now.hour >= 21:            # der 22-Uhr-Lauf reicht bis 6 Uhr früh
        end = midnight + timedelta(hours=6)
    else:
        end = midnight
    return now, end


def fetch_matches_in_window():
    """Alle noch nicht gestarteten Spiele im Prüffenster."""
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

    with _cache_lock:
        need = [e["id"] for e in events if e["id"] not in cache]
    for i in range(0, len(need), 10):
        chunk = need[i:i + 10]
        view = api_get("/v1/event/view", event_id=",".join(chunk))
        for ev in view.get("results", []):
            stats = ev.get("stats") or {}
            slim = {}
            for key in METRICS:
                pair = stats.get(key)
                try:
                    slim[key] = [int(pair[0]), int(pair[1])]
                except (TypeError, ValueError, IndexError):
                    slim[key] = None
            with _cache_lock:
                cache[ev["id"]] = slim

    history = []
    with _cache_lock:
        for e in events:
            history.append({"stats": cache.get(e["id"], {}),
                            "is_home": e["h"], "label": e["l"]})
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
    if metric == "on_target" and pair[0] == 0 and pair[1] == 0:
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


_TOKEN_ALIASES = {"utd": "united", "cnty": "county", "wed": "wednesday",
                  "ath": "athletic", "intl": "international"}


def _name_matches_slug(name, slug_part):
    """Wieviele Tokens (>=3 Zeichen) des Teamnamens im Slug vorkommen
    (auch als Prefix, damit 'sheff' auf 'sheffield' passt)."""
    slug_tokens = slug_part.split("-")
    score = 0
    for tok in s24_slug(name).split("-"):
        if len(tok) < 3:
            continue
        tok = _TOKEN_ALIASES.get(tok, tok)
        if any(st == tok or st.startswith(tok) or tok.startswith(st)
               or (len(tok) >= 4 and tok in st) or (len(st) >= 4 and st in tok)
               for st in slug_tokens if len(st) >= 3):
            score += 1
    return score


def s24_fetch_groups(match):
    """Holt die Trend-Gruppen samt Quoten-Spannen eines Spiels aus der
    scores24-JSON-Schnittstelle (dieselbe, die der Browser der Seite nutzt).

    Liefert {metrik: (anzahl, quote_min, quote_max)} oder None, wenn das
    Spiel nicht zuzuordnen/erreichbar ist.
    """
    candidates = []
    for link in s24_day_links():
        body = re.sub(r"^m-\d{2}-\d{2}-\d{4}-", "", link)
        h = _name_matches_slug(match["home"], body)
        a = _name_matches_slug(match["away"], body)
        if h >= 1 and a >= 1:
            candidates.append((h + a, link))
    slugs = [link[2:] for _, link in sorted(candidates, reverse=True)[:2]]
    # Fallback: direkt geratener Slug (zwei Datumsvarianten)
    from zoneinfo import ZoneInfo
    kick = datetime.fromtimestamp(match["kickoff_ts"], tz=ZoneInfo("Europe/Berlin"))
    home, away = s24_slug(match["home"]), s24_slug(match["away"])
    for d in (kick, kick - timedelta(days=1)):
        slugs.append(f"{d.strftime('%d-%m-%Y')}-{home}-{away}")
    api_to_metric = {v: k for k, v in S24_GROUPS.items()}
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
        groups = {}
        for g in data:
            metric = api_to_metric.get(g.get("name"))
            if not metric:
                continue
            count = int(g.get("count") or 0)
            lo = float(g.get("min_odd") or 0)
            hi = float(g.get("max_odd") or lo)
            if count > 0:
                groups[metric] = (count, lo, hi)
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
        for s in signals:
            s["unchecked"] = True
        return signals
    kept = []
    for s in signals:
        g = groups.get(s["metric_key"])
        if not g:
            continue
        count, lo, hi = g
        if hi < MIN_ODDS:
            continue
        s["range"] = (lo, hi)
        kept.append(s)
    return kept


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
        for direction in ("über", "unter"):
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
           min(under_lines) - max(over_lines) <= CONTRA_GAP:
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


def classify_signals(state, all_hits, checked_ids, window_ids, now_ts, run_label,
                     gate_dropped=frozenset()):
    """Vergleicht die Signale dieses Laufs mit dem Lauf-Gedächtnis.

    state       : {key: eintrag} aus state/reported.json
    all_hits    : [(match, [signal, ...]), ...] dieses Laufs
    checked_ids : Spiel-IDs, die in diesem Lauf fehlerfrei geprüft wurden
    window_ids  : Spiel-IDs, die im Prüffenster lagen (Spielplan)
    now_ts      : Unix-Zeit jetzt (Einträge angepfiffener Spiele fliegen raus)
    gate_dropped: Signal-Keys, die statistisch noch stehen, aber am
                  Quoten-Gate gescheitert sind (Markt bei scores24 weg)

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
                }
                per["new"].append(s)
            else:
                entry = dict(prev, last_run=run_label, line=s["line"],
                             range=cur_range, kickoff=match["kickoff"],
                             kickoff_ts=match.get("kickoff_ts", prev.get("kickoff_ts", 0)))
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
            else:
                reason = "Serie erfüllt das Regelwerk nicht mehr"
            buckets["dropped"].append((prev, reason))
        elif mid not in window_ids and int(prev.get("kickoff_ts", 0)) < now_ts + 36 * 3600:
            buckets["dropped"].append((prev, "Spiel nicht mehr im Spielplan (verschoben/abgesagt?)"))
        else:
            new_state[key] = prev                      # nicht geprüft -> unverändert merken
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


def build_message(match, signals):
    """Ein Spiel mit seinen Signalen — für Handy-Lesbarkeit kurze Zeilen,
    Wichtiges fett, jede Info auf eigener Zeile."""
    lines = [f"⚽ <b>{esc(match['home'])} – {esc(match['away'])}</b>",
             f"🕒 {match['kickoff']} · {esc(match['league'])}"]
    for s in signals:
        lines.append("")
        lines.append(f"▸ <b>{esc(s['metric'])} {s['direction']} {s['line']}</b>")
        lines.append(f"   {esc(match['home'])}: {fmt_series(s['home_series'], s['home_is_anchor'])}")
        lines.append(f"   {esc(match['away'])}: {fmt_series(s['away_series'], s['away_is_anchor'])}")
        tail = fmt_odds_tail(s)
        base = f"📊 {s['valid'][0]}/{s['valid'][1]}"
        lines.append(f"   {tail} · {base}" if tail else f"   {base}")
        if s.get("change_note"):
            lines.append(f"   🔄 <i>{esc(s['change_note'])}</i>"
                         f" · erster Lauf {s.get('first_run', '?')}")
    return "\n".join(lines)


def build_compact(match, signals):
    """Kurzform für bereits gemeldete, unveränderte Signale."""
    lines = [f"⚽ <b>{esc(match['home'])} – {esc(match['away'])}</b> · {match['kickoff']}"]
    for s in signals:
        odds = f" · 💰 {fmt_range(s['range'])}" if s.get("range") else ""
        lines.append(f"   {esc(s['metric'])} {s['direction']} {s['line']}{odds}"
                     f" · seit {s.get('first_run', '?')}")
    return "\n".join(lines)


def build_dropped(entry, reason):
    odds = f" · 💰 {fmt_range(entry['range'])}" if entry.get("range") else ""
    return (f"⚽ <b>{esc(entry['home'])} – {esc(entry['away'])}</b> · {entry['kickoff']}\n"
            f"   {esc(entry['metric'])} {entry['direction']} {entry['line']}{odds}"
            f" · gemeldet {entry.get('first_run', '?')}\n"
            f"   <i>{esc(reason)}</i>")


def section(title) -> str:
    return f"{SEP}\n<b>{title}</b>\n{SEP}"


def assemble_report(buckets, run_label):
    """Baut die Telegram-Nachricht(en) aus den vier Blöcken; None = nichts
    zu melden. Liefert Liste von HTML-Text-Stücken (<= 3500 Zeichen)."""
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

    if not (n["new"] or n["changed"] or n["dropped"]):
        if not n["same"]:
            return None
        # nichts Neues: nur ein Einzeiler, damit klar ist, dass der Lauf lief
        return [f"🟨🟨🟨 <b>TREND-SCAN {run_label}</b> 🟨🟨🟨\n"
                f"🔁 nichts Neues — {n['same']} Signal(e) unverändert"]

    blocks = [f"📊 {total} Signale · {summary}\n"
              f"<i>⚓ Anker-Serie · 📊 Datenbasis Heim/Gast · 💰 Quotenspanne</i>"]
    if buckets["new"]:
        blocks.append(section(f"🆕 NEU ({n['new']})"))
        blocks += [build_message(m, s) for m, s in buckets["new"]]
    if buckets["changed"]:
        blocks.append(section(f"🔄 GEÄNDERT seit erstem Lauf ({n['changed']})"))
        blocks += [build_message(m, s) for m, s in buckets["changed"]]
    if buckets["same"]:
        blocks.append(section(f"🔁 BEREITS GEMELDET ({n['same']})"))
        blocks += [build_compact(m, s) for m, s in buckets["same"]]
    if buckets["dropped"]:
        blocks.append(section(f"❌ WEGGEFALLEN ({n['dropped']})"))
        blocks += [build_dropped(e, r) for e, r in buckets["dropped"]]

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
    # sieht, wo eine Nachricht beginnt und endet (Lucios Wunsch).
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

def is_prewarm_run() -> bool:
    if os.environ.get("PREWARM") == "1":
        return True
    # Nur im Fenster 02–06 Uhr: ein stark verspäteter 22-Uhr-Lauf (nach
    # Mitternacht) soll trotzdem ein normaler Lauf mit Bericht bleiben.
    return 2 <= now_berlin().hour < PREWARM_BEFORE_HOUR


def prewarm(cache, hcache):
    """Vorwärm-Lauf: nur Statistiken für die Spiele des Tages laden.
    Bricht am Stundenlimit sofort ab (kein Warten), speichert den Cache."""
    global _no_wait
    _no_wait = True
    now, end = scan_window()
    matches = fetch_matches_in_window()
    print(f"VORWÄRMEN: {len(matches)} Spiele bis {end:%H:%M}, "
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
                with _cache_lock:
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
    if is_prewarm_run():
        prewarm(cache, hcache)
        return
    state = load_state()
    matches = fetch_matches_in_window()
    print(f"{len(matches)} Spiele im Prüffenster ({WORKERS} parallel), "
          f"{len(state)} Signale im Lauf-Gedächtnis, "
          f"{len(hcache)} Team-Spiellisten im Tages-Cache")
    all_hits = []
    checked_ids = set()
    gate_dropped = set()     # Signale, die statistisch noch stehen, deren
                             # Quoten-Markt bei scores24 aber weg ist

    def check(match):
        hist_home = fetch_team_history(match["home_id"], cache, hcache)
        hist_away = fetch_team_history(match["away_id"], cache, hcache)
        signals = evaluate_match(match, hist_home, hist_away)
        gated_out = []
        if signals and GATE_ENABLED:
            groups = s24_fetch_groups(match)
            before = {signal_key(match, s) for s in signals}
            signals = apply_s24_gate(signals, groups)
            gated_out = sorted(before - {signal_key(match, s) for s in signals})
        return signals, gated_out

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(check, m): m for m in matches}
        for fut in as_completed(futures):
            match = futures[fut]
            done += 1
            try:
                signals, gated_out = fut.result()
            except Exception as exc:
                print(f"  überspringe {match['home']}–{match['away']}: {exc}")
                continue
            checked_ids.add(match["id"])
            gate_dropped.update(gated_out)
            if signals:
                all_hits.append((match, signals))
                print(f"  TREFFER: {match['home']} – {match['away']} ({len(signals)})")
            if done % 25 == 0:
                with _cache_lock:
                    save_cache(cache)
                    save_history_cache(hcache)
                print(f"  ... {done}/{len(matches)} geprüft, {_request_count} Anfragen", flush=True)
    save_cache(cache)
    save_history_cache(hcache)
    # feste Sortierung nach Anstoßzeit (Parallelverarbeitung mischt sonst)
    all_hits.sort(key=lambda h: h[0].get("kickoff_ts", 0))

    # Lauf-Vergleich mit dem Gedächtnis des Vortags/Vorlaufs
    now = datetime.now(timezone.utc)
    run_label = fmt_day_time(now_berlin())
    buckets, new_state = classify_signals(
        state, all_hits, checked_ids, {m["id"] for m in matches},
        int(now.timestamp()), run_label, gate_dropped)

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

    chunks = assemble_report(buckets, run_label)
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
    print(f"Anfragen gesamt: {_request_count}")


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
    g = {"corners": (4, 1.54, 1.92), "yellowcards": (2, 1.12, 1.25)}
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

    # --- Fall 8: Gegenläufigkeit nur bei ENGEM Korridor
    #  a) breiter Korridor (über 6,5 + unter 12,5) -> beide Richtungen bleiben
    wide = _mk([[6, 5], [4, 3], [6, 6], [4, 4]] * 4, [H, A] * 8)[:15]
    wsig = evaluate_match(match, wide, [dict(x) for x in wide])
    dirs = {s["direction"] for s in wsig if s["metric"] == "Ecken"}
    if dirs != {"über", "unter"}:
        print("FEHLER Fall 8a: breiter Korridor wurde verworfen:", dirs)
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
    if set(reasons) != {"corners", "yellowcards"} or any(k.startswith("1|") for k in st3):
        print("FEHLER Fall 9h: weggefallene Serie nicht erkannt:", b3["dropped"])
        ok = False
    if "Quote rausgenommen" not in reasons.get("corners", "") or \
       "Regelwerk" not in reasons.get("yellowcards", ""):
        print("FEHLER Fall 9k: Wegfall-Grund (Quote vs. Serie) falsch:", reasons)
        ok = False
    report = assemble_report(b2, "Di 08:17")
    txt = "\n".join(report)
    for needle in ("🆕 NEU (1)", "🔄 GEÄNDERT", "🔁 BEREITS GEMELDET", "❌ WEGGEFALLEN (1)",
                   "vorher 1.30–1.80", "seit Di 06:17", "<b>",
                   "Teil 1/1", "Ende Teil 1/1"):
        if needle not in txt:
            print("FEHLER Fall 9i: Nachricht unvollständig, fehlt:", needle)
            ok = False
    quiet = assemble_report({"new": [], "changed": [], "same": [(m2, hits2[1][1][:1])],
                             "dropped": []}, "Di 10:17")
    if not quiet or "nichts Neues" not in quiet[0] or len(quiet[0]) > 120:
        print("FEHLER Fall 9j: Ruhe-Meldung falsch:", quiet)
        ok = False
    if "--show" in sys.argv:
        print("\n".join(report))

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
