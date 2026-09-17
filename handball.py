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

Aufruf:  python3 handball.py [wochen]      (Vorgabe: 4)
Umgebung: BETSAPI_TOKEN, optional TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
"""
import json
import os
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
SPORT_HANDBALL = 78          # laut BetsAPI-Glossar
WORKERS = 24
HOURLY_BUDGET = 3000         # Puffer zum Limit von 3600, der Fußball-Scanner
                             # läuft stündlich und braucht auch etwas
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
                print("HTTP 429 – Stundenlimit, warte 120 s", flush=True)
                time.sleep(120)
                last = exc
                continue
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


def ended_day(day: str) -> list:
    """Alle beendeten Handballspiele eines Tages (Format YYYYMMDD)."""
    out, page = [], 1
    while True:
        d = api_get("/v3/events/ended", sport_id=SPORT_HANDBALL, day=day, page=page)
        res = d.get("results") or []
        out += res
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


def half_time(ev):
    """Halbzeitstand aus dem scores-Block, falls vorhanden."""
    sc = ev.get("scores") or {}
    for key in ("1", 1):
        p = sc.get(key)
        if isinstance(p, dict) and p.get("home") is not None:
            try:
                return int(p["home"]), int(p["away"])
            except (TypeError, ValueError):
                return None
    return None


def main():
    if not TOKEN:
        sys.exit("BETSAPI_TOKEN fehlt")
    wochen = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    tage = wochen * 7
    heute = datetime.now(timezone.utc).date()
    days = [(heute - timedelta(days=i + 1)).strftime("%Y%m%d") for i in range(tage)]

    print(f"Handball-Abdeckung: {wochen} Wochen ({tage} Tage), {WORKERS} Worker", flush=True)
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
        sc = split_score(ev.get("ss"))
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
    for eid in probe_ids:
        try:
            r = (api_get("/v1/event/view", event_id=eid).get("results") or [None])[0]
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
    L.append(f"HANDBALL-ABDECKUNG · {wochen} Wochen · Stand {heute:%d.%m.%Y}")
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
    L.append(f"   {'Liga':38s} {'Spiele':>6} {'Wo':>3} {'Endst.':>7} {'HZ':>6} "
             f"{'Ø Tore':>7} {'SD':>5} {'Ø HZ':>6}")
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
        # Linien rund um den Ligaschnitt, in Zweierschritten
        basis = round(m / 2) * 2
        linien = [basis - 6.5, basis - 4.5, basis - 2.5, basis - 0.5,
                  basis + 1.5, basis + 3.5, basis + 5.5]
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
    pfad = OUT / f"handball_abdeckung_{heute:%Y-%m-%d}.txt"
    pfad.write_text(bericht, encoding="utf-8")
    print(f"\ngespeichert: {pfad}")

    # Rohdaten für die spätere Auswertung — je Spiel eine Zeile
    roh = OUT / f"handball_spiele_{heute:%Y-%m-%d}.json"
    schlank = []
    for ev in events:
        sc = split_score(ev.get("ss"))
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

    if TG_TOKEN and TG_CHAT:
        kopf = "🤾 <b>HANDBALL — Abdeckung</b>\n<pre>"
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
