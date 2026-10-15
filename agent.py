"""Claudes Zweitprüfung als Agent (REGELWERK 20 + 25, Teil B).

15.10. (Lucio: "Könntest du deine Bewertung spielen oder nicht spielen ...
automatisieren mit einem Agenten?" -> "danach B, hab schon Claude API mit
Geld drauf").

Ablauf je Lauf (nach dem Telegram-Bericht, damit der Bericht nicht wartet):
  1. Alle Tipps aus "PASST BEI BETLABEL", die heute noch kein Urteil haben.
  2. Je Tipp ein Claude-Aufruf mit Websuche: der Scanner gibt seine Daten und
     die automatische Vorprüfung (Punkte 1-6, 8) mit, der Agent recherchiert
     Schiri, Gegner, Rotation, Aufstellung, Wettbewerb und liefert die feste
     Liste 1-8 plus "spielen" / "nicht spielen".
  3. Urteil wird in state/agent.json gemerkt (je Tipp einmal am Tag) und
     steht ab dann in jeder BetLabel-Liste unter dem Tipp. Neue Urteile kommen
     sofort als eigene Telegram-Nachricht "ZWEITPRÜFUNG".

Schlüssel: GitHub-Secret ANTHROPIC_API_KEY (fehlt er, passiert nichts).
Kostenbremse: AGENT_MAX_TAG Tipps und AGENT_MAX_USD_TAG Dollar je Tag.
"""
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()   # 15.10.: Zeilenumbruch aus dem Secret entfernen
# Modell umstellen ohne Code: GitHub -> Settings -> Secrets and variables ->
# Actions -> Reiter "Variables" -> AGENT_MODEL (leer = Sonnet 5.5)
MODELL = os.environ.get("AGENT_MODEL") or "claude-sonnet-5-5"
MAX_TAG = int(os.environ.get("AGENT_MAX_TAG", "20"))          # Tipps je Tag
MAX_USD_TAG = float(os.environ.get("AGENT_MAX_USD_TAG", "3.0"))
MAX_SUCHEN = int(os.environ.get("AGENT_MAX_SUCHEN", "5"))     # Websuchen je Tipp
PARALLEL = 4
FRIST_S = 8 * 60                 # nach so vielen Sekunden keine neuen Aufrufe mehr
# Preise in US-Dollar (Stand Okt. 2026, Sonnet 5.5): je Mio. Token / je Suche
_PREISE = {"opus": (4.0, 20.0), "sonnet": (2.0, 10.0), "haiku": (1.0, 5.0)}
_p = next((v for k, v in _PREISE.items() if k in MODELL), _PREISE["sonnet"])
PREIS_IN = float(os.environ.get("AGENT_PREIS_IN") or _p[0])
PREIS_OUT = float(os.environ.get("AGENT_PREIS_OUT") or _p[1])
PREIS_SUCHE = 0.01

DATEI = Path(__file__).parent / "state" / "agent.json"
BERLIN = ZoneInfo("Europe/Berlin")

SYSTEM = """Du bist Claude und machst für Lucio die Zweitprüfung von Fußball-Wett-Tipps aus seinem Trend-Scanner (Regelwerk 20). Lucio spielt 3er-Kombis zu 10 €, nur Scanner-Tipps. Du entscheidest je Tipp „spielen“ oder „nicht spielen“.

Die feste Liste, jeder Punkt muss stehen:
1. Scanner-Signal + faire Quote + „spielbar ab“ gegen die BetLabel-Quote
2. Rolle: Favorit/Außenseiter nach Form und Gegnerstärke (Team-Ecken unter als klarer Favorit: nicht spielen)
3. Puffer: letzte 10 Spiele einzeln – wie viele lagen genau an der Linie? Hälfte knapp = Risiko klar benennen
4. Datenbasis: Aufsteiger/Absteiger, Ligawechsel, Testspiele, Reserve-/Jugend-Verwechslung, Liga-Werte vs. Wettbewerb (Europapokal ist oft strenger/anders als die heimische Liga)
5. Wettbewerb: Pokal/K.o., Hin-/Rückspiel, Derby, Bedeutung des Spiels
6. Schiri bei JEDEM Kartentipp nachschlagen und Ø Karten nennen (bei anderen Märkten: entfällt)
7. Gegner: Form, Tabellenlage, was er zulässt; Spielverlaufs-Risiko (Rückstand -> Anrennen), Rotation, Ausfälle, Aufstellung
8. Quotenabstand > 25 % zur fairen Quote: Erklärung finden

Der Scanner hat 1-6 und 8 schon vorgeprüft (Daten unten). Übernimm, was stimmt, und ergänze per Websuche vor allem 5, 6 und 7 (Schiri, Rotation/Aufstellung, Ausfälle, Tabellenlage, Hin-/Rückspiel). Suche gezielt und knapp.

Regeln:
- ⚠️ NUR für echte Unsicherheit im Spiel (dünner Puffer, Widerspruch, Rotation). NIE für eigene Suchprobleme. Findest du etwas nicht, schreib kurz, wonach du gesucht hast, und bewerte mit dem, was da ist.
- Nichts erfinden. Zahlen nur aus den Daten oder aus Quellen.
- „spielen“ nur, wenn kein Punkt ernsthaft dagegen spricht. Im Zweifel bei mehreren echten Warnungen: „nicht spielen“.
- Kurz und klar, Deutsch, jeder Punkt höchstens ein Satz.
- Im JSON keine Zitat-Markierungen, keine Quellen-Tags, kein HTML – nur Klartext.

Antworte am Ende AUSSCHLIESSLICH mit diesem JSON (kein Text davor oder danach):
{"urteil": "spielen" oder "nicht spielen", "grund": "der entscheidende Grund in einem Satz", "punkte": [{"nr": 1, "status": "✓" oder "⚠️", "text": "..."}, ... bis nr 8]}"""


def _sauber(txt):
    """15.10.: Fehlertexte dürfen den Schlüssel nie enthalten (landen im Repo)."""
    import re
    if API_KEY:
        txt = txt.replace(API_KEY, "[Schlüssel]")
    return re.sub(r"sk-ant-[A-Za-z0-9_\-]+", "[Schlüssel]", txt)


def _lade():
    try:
        return json.loads(DATEI.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _speichere(d):
    DATEI.parent.mkdir(parents=True, exist_ok=True)
    DATEI.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _heute():
    return datetime.now(BERLIN).strftime("%Y-%m-%d")


def _aufraeumen(d):
    """Urteile älter als 3 Tage raus."""
    grenze = time.time() - 3 * 86400
    return {k: v for k, v in d.items() if k == "_tag" or (v.get("ts") or 0) > grenze}


_CACHE = {"d": None}


def urteil(key):
    if _CACHE["d"] is None:
        _CACHE["d"] = _lade()
    v = _CACHE["d"].get(key)
    if v and v.get("datum") == _heute():
        return v
    return None


def _api(body):
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    for versuch in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            txt = exc.read().decode(errors="replace")[:300]
            if exc.code in (429, 500, 502, 503, 529) and versuch < 2:
                time.sleep(10 * (versuch + 1))
                continue
            raise RuntimeError(f"HTTP {exc.code}: {txt}")


class AgentFehler(Exception):
    def __init__(self, msg, kosten=None):
        super().__init__(msg)
        self.kosten = kosten or {}


ROH = Path(__file__).parent / "runs" / "agent_roh.json"


def _ohne_zitate(x):
    """15.10.: Die Websuche hängt Zitat-Markierungen an (<cite index=...>).
    Im Telegram sähe das wie Kauderwelsch aus -> rausnehmen, Text behalten."""
    import re
    if isinstance(x, str):
        x = re.sub(r"</cite>\)?", "", x)
        x = re.sub(r"\(?<?cite\b[^>]*>", "", x)
        return re.sub(r"\s{2,}", " ", x).strip()
    if isinstance(x, list):
        return [_ohne_zitate(v) for v in x]
    if isinstance(x, dict):
        return {k: _ohne_zitate(v) for k, v in x.items()}
    return x


def _json_aus(txt):
    e = txt.rfind("}")
    for start in [i for i, ch in enumerate(txt) if ch == "{"]:
        try:
            erg = json.loads(txt[start:e + 1])
            if isinstance(erg, dict) and "urteil" in erg:
                return _ohne_zitate(erg)
        except json.JSONDecodeError:
            continue
    return None


def frage_claude(text):
    """Ein Tipp -> (Antwort-JSON, Kosten-Dict). Fehler: AgentFehler mit Kosten."""
    msgs = [{"role": "user", "content": text}]
    kosten = {"in": 0, "out": 0, "suchen": 0}
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SUCHEN}]
    verlauf = []                              # stop_reason je Aufruf (Diagnose)
    antwort, erg = None, None
    for schritt in range(7):
        body = {"model": MODELL, "max_tokens": 4000, "system": SYSTEM,
                "messages": msgs, "tools": tools}
        if schritt >= 5:                      # letzte Chance: keine Suche mehr
            body["tool_choice"] = {"type": "none"}
        antwort = _api(body)
        u = antwort.get("usage") or {}
        kosten["in"] += (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
        kosten["out"] += u.get("output_tokens") or 0
        kosten["suchen"] += ((u.get("server_tool_use") or {}).get("web_search_requests") or 0)
        sr = antwort.get("stop_reason")
        inhalt = antwort.get("content") or []
        verlauf.append(f"{sr}:{'/'.join(b.get('type', '?')[:12] for b in inhalt)}")
        txt = "".join(b.get("text", "") for b in inhalt if b.get("type") == "text")
        erg = _json_aus(txt)
        if erg or sr == "refusal":
            break
        if inhalt:
            msgs = msgs + [{"role": "assistant", "content": inhalt}]
        if sr != "pause_turn":
            if schritt >= 2:
                break
            # fertig, aber ohne JSON -> ausdrücklich nachfordern
            msgs.append({"role": "user", "content": "Gib jetzt ausschließlich das JSON aus, ohne weiteren Text."})
    kosten["usd"] = round(kosten["in"] / 1e6 * PREIS_IN + kosten["out"] / 1e6 * PREIS_OUT
                          + kosten["suchen"] * PREIS_SUCHE, 4)
    kosten["verlauf"] = verlauf
    if erg:
        return erg, kosten
    try:
        ROH.parent.mkdir(parents=True, exist_ok=True)
        ROH.write_text(json.dumps({"verlauf": verlauf, "antwort": antwort}, ensure_ascii=False, indent=1)[:200000])
    except Exception:
        pass
    raise AgentFehler(f"kein Urteil ({' > '.join(verlauf)})", kosten)


def tipp_text(scan, match, s, q, mn):
    """Alles, was der Agent über den Tipp wissen muss."""
    tage = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
    _n = datetime.now(BERLIN)
    jetzt = f"{tage[_n.weekday()]} {_n:%d.%m.%Y %H:%M}"
    ko = datetime.fromtimestamp(match.get("kickoff_ts") or 0, BERLIN).strftime("%d.%m.%Y %H:%M") \
        if match.get("kickoff_ts") else match.get("kickoff")
    fair = s.get("fair_fin") or s.get("fair")
    zeilen = [
        f"Jetzt: {jetzt} (deutsche Zeit).",
        f"Spiel: {match['home']} – {match['away']}",
        f"Wettbewerb: {match.get('league', '')}",
        f"Anstoß: {ko} (deutsche Zeit)",
        f"Tipp: {s.get('metric')} {s.get('direction')} {s.get('line')}"
        + (f" (Team-Markt: {s.get('team')})" if s.get("team_market") else " (beide Teams zusammen)"),
        f"BetLabel-Quote: {q:.2f} · faire Quote Scanner: {fair:.2f} · spielbar ab: {mn:.2f}",
    ]
    if s.get("team_market") and s.get("serie"):
        sr = s["serie"]
        zeilen.append(f"Scanner-Serie {s.get('team')}: {sr.get('hits')}/{sr.get('window')} ({sr.get('kind')}); "
                      f"Ø eigene Zahl {s.get('erwartet')}; Gegner ließ {s.get('gegner')}/10 auf derselben Seite zu")
    elif s.get("home_series"):
        hs, as_ = s["home_series"], s.get("away_series") or {}
        zeilen.append(f"Scanner-Serien: {match['home']} {hs.get('hits')}/{hs.get('window')} ({hs.get('kind')}), "
                      f"{match['away']} {as_.get('hits')}/{as_.get('window')} ({as_.get('kind')})")
        if s.get("expect") is not None:
            zeilen.append(f"Erwartung Spielsumme: {s.get('expect')} (Ø {s.get('avg')})")
    pp = s.get("vp_puffer") or []
    namen = [s.get("team")] if s.get("team_market") else [match["home"], match["away"]]
    for name, p in zip(namen, pp):
        if p:
            art = "eigene Werte" if s.get("team_market") else "Spielsummen"
            zeilen.append(f"Letzte {p['n']} Spiele {name} ({art}, jüngstes zuerst): "
                          f"{', '.join(str(v) for v in p['werte'])}")
    if s.get("vp_1x2"):
        h, d, a = s["vp_1x2"]
        zeilen.append(f"1X2-Quoten (bet365, vor dem Spiel): Heim {h} · Remis {d} · Gast {a}")
    if s.get("vp_ref"):
        r = s["vp_ref"]
        zeilen.append(f"Angesetzter Schiri laut Datenquelle: {r['name']}"
                      + (f", Ø {r['avg']} Gelbe in {r['n']} Spielen unserer Datenbank" if r.get("avg") is not None else ""))
    if s.get("vp_liga"):
        zeilen.append(f"Anteil der letzten 10 Spiele im selben Wettbewerb: Heim {s['vp_liga'][0]}, Gast {s['vp_liga'][1]}")
    zeilen.append("")
    zeilen.append("Automatische Vorprüfung des Scanners:")
    for nr, st, t in scan.vp_bewertung(match, s, q):
        zeilen.append(f"{nr}. [{st}] {t}")
    zeilen.append("7. [offen] Gegner/Spielverlauf/Rotation – bitte recherchieren")
    return "\n".join(zeilen)


def agent_zeile(key):
    v = urteil(key)
    if not v:
        return ""
    ja = v.get("urteil", "").strip().lower() == "spielen"
    from html import escape
    return (f"   🤖 <b>{'spielen' if ja else 'nicht spielen'}</b> – "
            f"<i>{escape(v.get('grund', ''))}</i>")


def _block(match, s, q, mn, v):
    from html import escape as esc
    ja = v.get("urteil", "").strip().lower() == "spielen"
    z = [f"⚽ <b>{esc(match['home'])} – {esc(match['away'])}</b>",
         f"🕒 {match.get('kickoff')} · {esc(match.get('league', ''))}",
         f"<b>{esc(str(s.get('metric')))} {s.get('direction')} {s.get('line')}</b> · BL <b>{q:.2f}</b> (ab {mn:.2f})"]
    for p in sorted(v.get("punkte") or [], key=lambda p: p.get("nr", 0)):
        z.append(f"{p.get('nr')}. {p.get('status', '')} {esc(str(p.get('text', '')))}")
    z.append(f"➡️ <b>{'SPIELEN' if ja else 'NICHT SPIELEN'}</b> – {esc(v.get('grund', ''))}")
    return "\n".join(z)


def laufen(scan, tipps):
    """tipps: [(match, signal, quote, spielbar_ab, key)] aus der BetLabel-Liste.
    -> (Telegram-Text oder None, Protokoll)"""
    proto = {"modell": MODELL, "neu": 0, "fehler": [], "usd": 0.0}
    if not API_KEY:
        proto["aus"] = "kein ANTHROPIC_API_KEY"
        return None, proto
    d = _aufraeumen(_lade())
    tag = d.get("_tag") or {}
    if tag.get("datum") != _heute():
        tag = {"datum": _heute(), "anzahl": 0, "usd": 0.0}
    offen = [t for t in tipps if not (d.get(t[4]) and d[t[4]].get("datum") == _heute())]
    frei = max(0, min(MAX_TAG - tag["anzahl"], len(offen)))
    if tag["usd"] >= MAX_USD_TAG:
        frei = 0
    if len(offen) > frei:
        proto["uebersprungen"] = len(offen) - frei
    offen = offen[:frei]
    if not offen:
        _speichere(d | {"_tag": tag})
        return None, proto
    t0 = time.time()
    neu = []

    def eins(t):
        match, s, q, mn, key = t
        if time.time() - t0 > FRIST_S:
            raise TimeoutError("Frist")
        erg, kosten = frage_claude(tipp_text(scan, match, s, q, mn))
        return t, erg, kosten

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        futs = [pool.submit(eins, t) for t in offen]
        for f in as_completed(futs):
            try:
                t, erg, kosten = f.result()
            except Exception as exc:
                proto["fehler"].append(_sauber(f"{type(exc).__name__}: {str(exc)[:300]}"))
                k = getattr(exc, "kosten", None) or {}
                if k.get("usd"):
                    tag["usd"] = round(tag["usd"] + k["usd"], 4)
                    proto["usd"] = round(proto["usd"] + k["usd"], 4)
                continue
            match, s, q, mn, key = t
            d[key] = {"datum": _heute(), "ts": int(time.time()), "quote": q,
                      "spiel": f"{match['home']} – {match['away']}",
                      "tipp": f"{s.get('metric')} {s.get('direction')} {s.get('line')}",
                      "urteil": erg.get("urteil"), "grund": erg.get("grund"),
                      "punkte": erg.get("punkte"), "kosten": kosten}
            tag["anzahl"] += 1
            tag["usd"] = round(tag["usd"] + kosten["usd"], 4)
            proto["usd"] = round(proto["usd"] + kosten["usd"], 4)
            neu.append((match, s, q, mn, d[key]))
    d["_tag"] = tag
    _speichere(d)
    _CACHE["d"] = d
    proto["neu"] = len(neu)
    proto["tag"] = tag
    proto["sekunden"] = int(time.time() - t0)
    print(f"Agent: {len(neu)} Urteile, {proto['usd']:.3f} $ (heute {tag['usd']:.2f} $), "
          f"{proto['sekunden']} s, Fehler {len(proto['fehler'])}", flush=True)
    if not neu:
        return None, proto
    neu.sort(key=lambda x: x[0].get("kickoff_ts") or 0)
    stand = datetime.now(BERLIN).strftime("%H:%M")
    kopf = f"🤖 <b>ZWEITPRÜFUNG ({len(neu)})</b> · Stand {stand}"
    return kopf + "\n\n" + "\n\n".join(_block(*x) for x in neu), proto
