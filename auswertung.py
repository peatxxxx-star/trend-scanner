"""Tägliche Auswertung (26.11., Lucio): Ergebnis jedes spielbaren Signals (🟢/🟡) und aller
Papier-Märkte vom Vortag. Quelle der Ergebnisse: scores24 team-matches (Spiel selbst).

Archiv: state/trendscan_archiv.json  {key: letzter Stand vor Anpfiff}
Ausgabe: runs/trendscan/auswertung/<YYYY-MM-DD>.json + gesamt.json, Telegram-Nachricht.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import teamstats

ROOT = Path(__file__).resolve().parent
ARCHIV = ROOT / "state" / "trendscan_archiv.json"
AUSDIR = ROOT / "runs" / "trendscan" / "auswertung"
LETZTE = ROOT / "state" / "trendscan_auswertung_letzte"


def archiv_laden():
    try:
        return json.loads(ARCHIV.read_text())
    except Exception:
        return {}


def archiv_aktualisieren(eintraege, jetzt):
    """eintraege: Signale dieses Laufs (spielbar oder Papier). Stand vor Anpfiff wird überschrieben."""
    a = archiv_laden()
    for e in eintraege:
        if e.get("anstoss", 0) > jetzt and e.get("check"):
            a[e["key"]] = {f: e.get(f) for f in ("spiel", "bl", "liga", "markt", "quote", "x12", "anstoss",
                                                  "sym", "check", "papier", "hinweis")}
    grenze = jetzt - 4 * 86400
    a = {k: v for k, v in a.items() if v.get("anstoss", 0) > grenze}
    ARCHIV.parent.mkdir(exist_ok=True)
    ARCHIV.write_text(json.dumps(a, ensure_ascii=False))


def _paar(v):
    try:
        x, y = str(v).split(":")
        return int(x), int(y)
    except Exception:
        return None


def _ergebnis(slug):
    for tt in ("home", "away"):
        try:
            nodes = teamstats._abrufen(slug, tt)
        except Exception:
            continue
        for n in nodes:
            if n.get("slug") == slug:
                rs = {r.get("type"): r.get("value") for r in n.get("result_scores") or []}
                st = {i.get("type"): (i.get("team1_value"), i.get("team2_value"))
                      for i in ((n.get("statistic") or {}).get("items") or [])}
                return {"FT": rs.get("FT") or n.get("result_score"), "HT": rs.get("HT"), "stat": st}
    return None


def bewerten(m, r):
    """m = markt_aus_typ-Dict, r = Ergebnis -> True/False/None (nicht bewertbar)."""
    ft, ht = _paar(r.get("FT")), _paar(r.get("HT"))
    if not ft:
        return None
    if m["art"] == "dc":
        h, g = ft
        return {"x1": h >= g, "x2": h <= g, "12": h != g}[m["wahl"]]
    if m["art"] == "hc":
        h, g = ft
        d = (h - g) if m["seite"] == "heim" else (g - h)
        return d + m["linie"] > 0
    met = m["metric"]
    if met == "goals":
        v = ft
    elif met == "ht_goals":
        v = ht
    elif met == "h2_goals":
        v = (ft[0] - ht[0], ft[1] - ht[1]) if ht else None
    else:
        typ = {"corners": "corner_kicks", "yellowcards": "yellow_cards", "fouls": "fouls"}.get(met)
        try:
            a, b = (r.get("stat") or {}).get(typ)
            v = (int(a), int(b))
        except Exception:
            v = None
    if v is None:
        return None
    x = v[0] + v[1] if not m["seite"] else (v[0] if m["seite"] == "heim" else v[1])
    if x == m["linie"]:
        return None
    return x > m["linie"] if m["richtung"] == "über" else x < m["linie"]


def markt_gruppe(m):
    if m["art"] == "dc":
        return "Doppelte Chance"
    if m["art"] == "hc":
        return "Handicap"
    name = {"goals": "Tore", "ht_goals": "Tore 1. HZ", "h2_goals": "Tore 2. HZ", "corners": "Ecken",
            "yellowcards": "Gelbe", "fouls": "Fouls"}.get(m["metric"], m["metric"])
    if m["metric"] == "goals" and m["seite"] and m["richtung"] == "über" and m["linie"] == 0.5:
        return "trifft"
    return f"{name} {'Team' if m['seite'] else 'gesamt'} {m['richtung']}"


def tagesauswertung(tag, tz, markt_aus_typ):
    """tag = date (Berlin). Gibt (text, daten) zurück."""
    a = archiv_laden()
    start = datetime(tag.year, tag.month, tag.day, tzinfo=tz).timestamp()
    ende = start + 86400
    sel = {k: v for k, v in a.items() if start <= v.get("anstoss", 0) < ende}
    slugs = sorted({k.split("|")[0] for k in sel})
    with ThreadPoolExecutor(8) as ex:
        res = dict(zip(slugs, ex.map(_ergebnis, slugs)))
    zeilen = []
    for k, v in sel.items():
        slug, *typ = k.split("|")
        m = markt_aus_typ(typ)
        r = res.get(slug)
        hit = bewerten(m, r) if (m and r) else None
        zeilen.append(dict(v, key=k, treffer=hit, gruppe=markt_gruppe(m) if m else "?",
                           ergebnis=(r or {}).get("FT")))
    AUSDIR.mkdir(parents=True, exist_ok=True)
    (AUSDIR / f"{tag.isoformat()}.json").write_text(json.dumps(zeilen, ensure_ascii=False, indent=1))
    # Gesamtbilanz fortschreiben
    gp = AUSDIR / "gesamt.json"
    try:
        gesamt = json.loads(gp.read_text())
    except Exception:
        gesamt = {"tage": [], "maerkte": {}}
    if tag.isoformat() not in gesamt["tage"]:
        gesamt["tage"].append(tag.isoformat())
        for z in zeilen:
            if z["treffer"] is None:
                continue
            art = ("Papier " if z.get("papier") else "") + z["gruppe"] + ("" if z.get("papier") else f" {z.get('sym')}")
            s = gesamt["maerkte"].setdefault(art, {"n": 0, "treffer": 0, "be": 0.0, "gewinn": 0.0})
            s["n"] += 1
            s["treffer"] += int(z["treffer"])
            s["be"] += 1 / z["quote"]
            s["gewinn"] += (z["quote"] - 1) if z["treffer"] else -1
        gp.write_text(json.dumps(gesamt, ensure_ascii=False, indent=1))

    def q(x):
        return f"{x:.2f}".replace(".", ",")
    spielbar = sorted([z for z in zeilen if not z.get("papier")], key=lambda z: z["anstoss"])
    papier = [z for z in zeilen if z.get("papier")]
    t = [f"📊 <b>Auswertung {tag:%d.%m.}</b>"]
    if spielbar:
        bw = [z for z in spielbar if z["treffer"] is not None]
        n_ok = sum(z["treffer"] for z in bw)
        t.append(f"Spielbare Signale: <b>{n_ok}/{len(bw)}</b>"
                 + (f" ({n_ok / len(bw):.0%}, BE Ø {sum(1 / z['quote'] for z in bw) / len(bw):.0%})" if bw else ""))
        for z in spielbar:
            s = {True: "✅", False: "❌", None: "❔"}[z["treffer"]]
            t.append(f"{s} {z.get('sym') or ''} {z['spiel']}: {z['markt']} @ {q(z['quote'])} · {z.get('ergebnis') or '?'}")
    else:
        t.append("Keine spielbaren Signale.")
    if papier:
        g = {}
        for z in papier:
            if z["treffer"] is None:
                continue
            g.setdefault(z["gruppe"], []).append(z)
        t.append("\nPapier (pausierte Märkte, nur 🟢/🟡):")
        for name, v in sorted(g.items(), key=lambda x: -len(x[1])):
            v2 = [z for z in v if z.get("sym") in ("🟢", "🟡")]
            if not v2:
                continue
            n_ok = sum(z["treffer"] for z in v2)
            be = sum(1 / z["quote"] for z in v2) / len(v2)
            t.append(f"• {name}: {n_ok}/{len(v2)} ({n_ok / len(v2):.0%}, BE {be:.0%})")
    # kumuliert spielbar
    tot = [(k, s) for k, s in gesamt["maerkte"].items() if not k.startswith("Papier") and s["n"]]
    if tot:
        n = sum(s["n"] for _, s in tot)
        ok = sum(s["treffer"] for _, s in tot)
        be = sum(s["be"] for _, s in tot) / n
        t.append(f"\nSeit Start ({len(gesamt['tage'])} Tage): {ok}/{n} = {ok / n:.0%} bei BE {be:.0%}")
    return "\n".join(t).replace("&", "&amp;"), zeilen
