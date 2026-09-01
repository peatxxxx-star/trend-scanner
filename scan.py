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

Benötigte Umgebungsvariablen:
  BETSAPI_TOKEN      – BetsAPI-Token (Soccer API)
  TELEGRAM_BOT_TOKEN – Telegram-Bot-Token (optional; ohne = nur Konsole)
  TELEGRAM_CHAT_ID   – Telegram-Chat-ID  (optional; ohne = nur Konsole)

Aufruf:
  python scan.py               # normaler Lauf
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

# scores24-Reiternamen je Metrik
S24_GROUPS = {
    "corners": "Eckstoß",
    "yellowcards": "Karten",
    "on_target": "Schüsse",
    "offsides": "Abseits",
    "fouls": "Fouls",
}

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


# ----------------------------------------------------------------------------
# HTTP + Anfragen-Wächter + Cache
# ----------------------------------------------------------------------------

_request_count = 0
_hour_started = time.time()
_hour_requests = 0
_counter_lock = threading.Lock()
_cache_lock = threading.Lock()


def _budget_guard():
    """Bleibt unter dem Stundenlimit: notfalls bis zur nächsten Stunde warten."""
    global _hour_started, _hour_requests
    while True:
        with _counter_lock:
            now = time.time()
            if now - _hour_started >= 3600:
                _hour_started = now
                _hour_requests = 0
            if _hour_requests < HOURLY_BUDGET:
                return
            wait = 3600 - (now - _hour_started) + 5
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
                    "kickoff": kickoff_local.strftime("%a %H:%M"),
                    "kickoff_ts": int(e["time"]),
                    "bet365_id": e.get("bet365_id"),
                }
            total = int((data.get("pager") or {}).get("total", 0))
            if page * 100 >= total:
                break
            page += 1
    return list(matches.values())


def fetch_team_history(team_id: str, cache: dict):
    """Letzte HISTORY_DEPTH beendete Spiele eines Teams inkl. Statistiken.

    Liefert Liste (jüngstes zuerst) von:
      {"stats": {...}, "is_home": bool, "label": str}
    Statistiken beendeter Spiele sind unveränderlich und werden dauerhaft
    gecacht — nur neue Spiele kosten Anfragen.
    """
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
    events = events[:HISTORY_DEPTH]

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
            history.append({
                "stats": cache.get(e["id"], {}),
                "is_home": str((e.get("home") or {}).get("id")) == str(team_id),
                "label": f'{(e.get("home") or {}).get("name","?")} - {(e.get("away") or {}).get("name","?")}',
            })
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


def s24_fetch_page(match):
    """Findet die scores24-Spielseite ueber die Tagesuebersicht (Namens-
    aehnlichkeit) mit Fallback auf die geratene URL. Liefert HTML oder None."""
    candidates = []
    for link in s24_day_links():
        body = re.sub(r"^m-\d{2}-\d{2}-\d{4}-", "", link)
        h = _name_matches_slug(match["home"], body)
        a = _name_matches_slug(match["away"], body)
        if h >= 1 and a >= 1:
            candidates.append((h + a, link))
    urls = [f"{S24_BASE}/{link}" for _, link in
            sorted(candidates, reverse=True)[:2]]
    # Fallback: direkt geratene URL (zwei Datumsvarianten)
    from zoneinfo import ZoneInfo
    kick = datetime.fromtimestamp(match["kickoff_ts"], tz=ZoneInfo("Europe/Berlin"))
    home, away = s24_slug(match["home"]), s24_slug(match["away"])
    for d in (kick, kick - timedelta(days=1)):
        urls.append(f"{S24_BASE}/m-{d.strftime('%d-%m-%Y')}-{home}-{away}")
    for url in urls:
        try:
            html = _s24_get(url)
        except Exception as exc:
            _s24_stats["last_error"] = f"{url} -> {exc}"[:160]
            continue
        # Verifikation: beide Teamnamen muessen auf der Seite auftauchen,
        # sonst war die Zuordnung falsch -> naechsten Kandidaten probieren
        text = re.sub(r"<[^>]+>", " ", html).lower()
        def on_page(name):
            toks = [_TOKEN_ALIASES.get(t, t)
                    for t in s24_slug(name).split("-") if len(t) >= 4]
            return (not toks) or any(t in text for t in toks)
        if on_page(match["home"]) and on_page(match["away"]):
            _s24_stats["ok"] += 1
            return html
        _s24_stats["last_error"] = f"{url} -> Teamnamen nicht auf Seite"[:160]
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
    # Gegenläufigkeits-Filter: Metrik mit Trends in beide Richtungen fliegt raus
    directions_per_metric = {}
    for (metric, direction) in candidates:
        directions_per_metric.setdefault(metric, set()).add(direction)
    signals = []
    for (metric, direction), cands in candidates.items():
        if len(directions_per_metric[metric]) > 1:
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
# Ausgabe
# ----------------------------------------------------------------------------

def fmt_series(s, is_anchor):
    base = f'{s["hits"]}/{s["window"]}' if s["window"] > s["hits"] else f'{s["hits"]} in Folge'
    scope = "" if s["kind"] == "gesamt" else f' ({s["kind"]})'
    star = "⚓" if is_anchor else ""
    return f"{base}{scope}{star}"


def build_message(match, signals):
    lines = [f"⚽ {match['home']} – {match['away']}",
             f"🕒 {match['kickoff']} · {match['league']}"]
    for s in signals:
        if s.get("range"):
            lo, hi = s["range"]
            tail = f" · Quoten {lo:.2f}–{hi:.2f}" if hi > lo else f" · Quote {lo:.2f}"
        elif s.get("quote"):
            tail = f" @ {s['quote']:.2f}"
        elif s.get("unchecked"):
            tail = " ❓scores24-Seite nicht gefunden, selbst prüfen"
        else:
            tail = ""
        lines.append(
            f"• Gesamt-{s['metric']} {s['direction']} {s['line']}: "
            f"{match['home']} {fmt_series(s['home_series'], s['home_is_anchor'])}, "
            f"{match['away']} {fmt_series(s['away_series'], s['away_is_anchor'])} "
            f"[Datenbasis {s['valid'][0]}/{s['valid'][1]}]{tail}"
        )
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    if not (TG_TOKEN and TG_CHAT):
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as exc:
        print(f"Telegram-Fehler: {exc}", file=sys.stderr)
        return False


# ----------------------------------------------------------------------------
# Hauptlauf
# ----------------------------------------------------------------------------

def run():
    if not TOKEN:
        sys.exit("BETSAPI_TOKEN fehlt")
    cache = load_cache()
    matches = fetch_matches_in_window()
    print(f"{len(matches)} Spiele im Prüffenster ({WORKERS} parallel)")
    all_hits = []

    def check(match):
        hist_home = fetch_team_history(match["home_id"], cache)
        hist_away = fetch_team_history(match["away_id"], cache)
        signals = evaluate_match(match, hist_home, hist_away)
        if signals and GATE_ENABLED:
            html = s24_fetch_page(match)
            groups = s24_market_groups(html) if html else None
            signals = apply_s24_gate(signals, groups)
        return signals

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(check, m): m for m in matches}
        for fut in as_completed(futures):
            match = futures[fut]
            done += 1
            try:
                signals = fut.result()
            except Exception as exc:
                print(f"  überspringe {match['home']}–{match['away']}: {exc}")
                continue
            if signals:
                all_hits.append((match, signals))
                print(f"  TREFFER: {match['home']} – {match['away']} ({len(signals)})")
            if done % 25 == 0:
                with _cache_lock:
                    save_cache(cache)
                print(f"  ... {done}/{len(matches)} geprüft, {_request_count} Anfragen", flush=True)
    save_cache(cache)
    # feste Sortierung nach Anstoßzeit (Parallelverarbeitung mischt sonst)
    all_hits.sort(key=lambda h: h[0].get("kickoff_ts", 0))

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    log = {
        "run_utc": now.isoformat(timespec="seconds"),
        "matches_checked": len(matches),
        "requests": _request_count,
        "hits": [{"match": m, "signals": s} for m, s in all_hits],
    }
    (RUNS_DIR / f"{now:%Y-%m-%d_%H%M}.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1))

    if all_hits:
        header = (f"📊 Trend-Scan {now_berlin().strftime('%d.%m. %H:%M')} – "
                  f"{len(all_hits)} Treffer (⚓ = Anker-Serie)")
        # Telegram erlaubt max. 4096 Zeichen pro Nachricht -> stückeln
        chunks, current = [], header
        for m, s in all_hits:
            block = build_message(m, s)
            if len(current) + len(block) + 2 > 3500:
                chunks.append(current)
                current = block
            else:
                current += "\n\n" + block
        chunks.append(current)
        sent = all(send_telegram(c) for c in chunks)
        if sent:
            print(f"Telegram: {len(chunks)} Nachricht(en) verschickt")
        else:
            print(header)
            for c in chunks:
                print(c)
    else:
        print("Keine Treffer in diesem Lauf")
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

    # --- Fall 7: scores24-Parser + lockeres Gate
    fake_html = ("<div>Eckstoß Vorhersagen</div><span>(4)</span><b>1.54</b> - "
                 "<b>1.92</b> <div>Karten</div> (2) 1.12 - 1.25 "
                 "<div>Abseits Vorhersagen (3) 1.34 - 1.75</div>")
    g = s24_market_groups(fake_html)
    if g.get("corners") != (4, 1.54, 1.92) or g.get("yellowcards") != (2, 1.12, 1.25):
        print("FEHLER Fall 7a: scores24-Parser:", g)
        ok = False
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

    print("Selbsttest OK" if ok else "Selbsttest FEHLGESCHLAGEN")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        run()
