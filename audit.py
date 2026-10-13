"""Vorab-Audit je Tipp (REGELWERK Abschnitt 18) — 13.10. (Lucio: "umfassende
Audit-Methodik, die immer gleich auf jedes Spiel angewandt wird, zu 100 %
gleich, ohne Abweichungen").

Jeder Tipp durchläuft dieselben Prüfschritte A–K in derselben Reihenfolge.
Jeder Schritt endet mit OK / WARNUNG / STOPP. Das Urteil folgt einer festen
Regel (kein Bauchgefühl):
  - mind. ein STOPP oder eine WARNUNG -> NICHT SPIELEN (keine Ausnahmen,
                                         keine "Begründung", 13.10. Lucio)
  - offene Pflichtpunkte (Derby, Schiri) -> OFFEN: erst klären, dann neu prüfen
  - sonst                                -> SPIELEN

Aufruf:
  python3 audit.py "<Teamname-Teil>" <metric_key> <über|unter> <linie> <quote> --derby nein [--schiri "Name: Ø 4.3"]
  metric_key wie im Scanner: goals, corners, yellowcards, offsides, fouls,
  on_target, ht_yellowcards, ht_corners, team_corners_heim, team_corners_gast,
  team_yellowcards_heim, team_yellowcards_gast
Ausgabe zusätzlich in audits/<Datum>.md (Protokoll jedes Audits).

Rein lesend: ändert weder Scanner noch State.
"""
import argparse
import glob
import gzip
import json
import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import scan  # noqa: E402  (nur Hilfsfunktionen: play_min, fav_class, calibrate)

# ---------------------------------------------------------------- Schwellen
# Stärke = Tordifferenz-Schnitt der letzten 10 Pflichtspiele, Heimvorteil +-0,3.
# Backtest 13.10. (rule7.py, 34.700 Serien-Fälle aus 350.000 Spielen):
#   Teamecken unter 6,5:  klarer Außenseiter 90 %, ausgeglichen 83 %, klarer Favorit 75 %
#   Teamecken unter 5,5:  klarer Außenseiter 86 %, ausgeglichen 74 %, klarer Favorit 66 %
#   Teamecken über 3,5:   klarer Außenseiter 59 %, ausgeglichen 68 %, klarer Favorit 82 %
#   Teamkarten unter 2,5: 82–88 % in allen Gruppen (kein Effekt)
STRENGTH_CLEAR = 1.0
STRENGTH_SOFT = 0.3
HOME_ADV = 0.3
GAP_EXPLAIN = 0.25        # Quote > fair x 1,25 -> Erklärung Pflicht
MIN_GAMES = 7
CUP_WORDS = re.compile(r"cup|pokal|copa|coupe|coppa|ta[cç]a|kupa|beker|trophy|play-?off|knockout|qualif", re.I)
REF_WARN = 5.0


def load_state():
    return json.loads((ROOT / "state" / "reported.json").read_text(encoding="utf-8"))


def find_signal(state, needle, mk, direction, line):
    hits = []
    for k, v in state.items():
        if needle.lower() not in (v["home"] + " " + v["away"]).lower():
            continue
        if v["metric_key"] != mk or v["direction"] != direction:
            continue
        if abs(float(v["line"]) - float(line)) > 1e-6:
            continue
        hits.append(v)
    return hits


def find_in_runs(needle, mk, direction, line):
    """Fallback für bereits angepfiffene Spiele (State räumt sie ab)."""
    for f in sorted(glob.glob(str(ROOT / "runs" / "20*.json")), reverse=True)[:40]:
        try:
            j = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        for h in j.get("hits") or []:
            m = h.get("match") or {}
            if needle.lower() not in (m.get("home", "") + " " + m.get("away", "")).lower():
                continue
            for s in h.get("signals") or []:
                if s.get("metric_key") == mk and s.get("direction") == direction \
                        and abs(float(s.get("line", -99)) - float(line)) < 1e-6:
                    return [{"home": m["home"], "away": m["away"], "league": m.get("league", ""),
                             "kickoff": m.get("kickoff", ""), "first_run": s.get("first_run") or Path(f).stem,
                             "match_id": m["id"], "signal": s}]
    return []


def match_ids(match_id):
    """home_id / away_id aus dem jüngsten Laufprotokoll, das das Spiel enthält."""
    for f in sorted(glob.glob(str(ROOT / "runs" / "20*.json")), reverse=True)[:60]:
        try:
            j = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        for h in j.get("hits") or []:
            m = h.get("match") or {}
            if str(m.get("id")) == str(match_id):
                return m
    return None


def team_games(hist, tid, stats, n=10):
    """Letzte n Pflichtspiele (ohne Testspiele) mit Statistik, jüngstes zuerst."""
    out = []
    for e in (hist.get(str(tid)) or {}).get("events", []):
        if scan.is_friendly(e.get("lg")):
            continue
        st = stats.get(e["id"])
        if not st:
            continue
        out.append((e, st))
        if len(out) >= n:
            break
    return out


def val(st, metric, is_home, side):
    """side: 'total' | 'own' | 'opp'."""
    pair = st.get(metric)
    if pair is None:
        return None
    if metric in ("corners", "offsides", "fouls", "on_target", "throwins", "goalkicks") and pair[0] == 0 and pair[1] == 0:
        return None
    if side == "total":
        return pair[0] + pair[1]
    i = 0 if is_home else 1
    return pair[i] if side == "own" else pair[1 - i]


def hit(v, line, direction):
    return v > line if direction == "über" else v < line


def strength(games):
    gd = []
    for e, st in games:
        g = st.get("goals")
        if not g:
            continue
        i = 0 if e["h"] else 1
        gd.append(g[i] - g[1 - i])
    return (sum(gd) / len(gd)) if gd else None


def role_label(diff):
    if diff is None:
        return None
    if diff >= STRENGTH_CLEAR:
        return "klarer Favorit"
    if diff >= STRENGTH_SOFT:
        return "Favorit"
    if diff <= -STRENGTH_CLEAR:
        return "klarer Außenseiter"
    if diff <= -STRENGTH_SOFT:
        return "Außenseiter"
    return "ausgeglichen"


def run(args):
    out = []
    res = []          # (Schritt, Status, Text)

    def step(code, status, text):
        res.append((code, status, text))

    state = load_state()
    hits = find_signal(state, args.team, args.metric, args.direction, args.line) \
        or find_in_runs(args.team, args.metric, args.direction, args.line)
    team_market = args.metric.startswith("team_")
    base = args.metric.rsplit("_", 1)[0][5:] if team_market else args.metric
    side_home = args.metric.endswith("_heim") if team_market else None

    # A — Scanner-Signal
    if not hits:
        step("A Scanner-Signal", "STOPP", "kein Scanner-Signal für diesen Markt/diese Linie → kein Scanner-Tipp")
        return finish(args, out, res, None)
    v = hits[0]
    s = v["signal"]
    step("A Scanner-Signal", "OK", f"{v['home']} – {v['away']} ({v['league']}), {v['kickoff']}, gemeldet {v.get('first_run')}")

    m = match_ids(v["match_id"]) or {}
    hist = json.loads((ROOT / "cache" / "history.json").read_text(encoding="utf-8"))
    stats = json.load(gzip.open(ROOT / "cache" / "stats.json.gz"))
    hg = team_games(hist, m.get("home_id"), stats)
    ag = team_games(hist, m.get("away_id"), stats)

    # E (vorgezogen, wird für B gebraucht) — Stärke/Rolle
    sh, sa = strength(hg), strength(ag)
    diff_home = (sh - sa + HOME_ADV) if (sh is not None and sa is not None) else None
    fav_proxy = None
    if diff_home is not None:
        fav_proxy = "klar" if abs(diff_home) >= STRENGTH_CLEAR else ("ausgeglichen" if abs(diff_home) < STRENGTH_SOFT else "mittel")

    # B — Quote gegen Mindestquote
    fair = s.get("fair_fin") or s.get("fair")
    sig = dict(s)
    if not sig.get("fav") and fav_proxy:
        sig["fav"] = fav_proxy
    mn, tag = scan.play_min(sig)
    if mn is None and (args.metric, args.direction) in scan.PLAY_FACTOR:
        step("B Mindestquote", "STOPP", "Markt laut Regelwerk nicht spielen")
    elif mn is None:
        step("B Mindestquote", "STOPP", "keine faire Quote vorhanden")
    elif args.quote < mn:
        step("B Mindestquote", "STOPP", f"Quote {args.quote:.2f} < spielbar ab {mn:.2f} (fair {fair:.2f}{', ' + tag if tag else ''})")
    else:
        gap = args.quote / fair - 1
        if gap > GAP_EXPLAIN:
            step("B Mindestquote", "WARNUNG", f"Quote {args.quote:.2f} ≥ {mn:.2f}, aber {gap:+.0%} über fair → Erklärung Pflicht (weiß der Bookie etwas?)")
        else:
            step("B Mindestquote", "OK", f"Quote {args.quote:.2f} ≥ spielbar ab {mn:.2f} (fair {fair:.2f}, {gap:+.0%}{', ' + tag if tag else ''})")

    # C — Datenbasis / Liga
    own_games = (hg if side_home else ag) if team_market else None
    sets = [("Heim", hg), ("Gast", ag)] if not team_market else [("Team", own_games)]
    for nm, g in sets:
        if len(g) < MIN_GAMES:
            step(f"C Daten {nm}", "WARNUNG", f"nur {len(g)} Pflichtspiele mit Statistik")
            continue
        leagues = [e.get("lg") or "" for e, _ in g]
        cur = sum(1 for lg in leagues if lg == v["league"]) / len(leagues)
        if cur < 0.6 and not CUP_WORDS.search(v["league"]):
            step(f"C Daten {nm}", "WARNUNG", f"nur {cur:.0%} der letzten {len(g)} Spiele in {v['league']} → Liga-/Rollenwechsel (Auf-/Absteiger?)")
        else:
            step(f"C Daten {nm}", "OK", f"{len(g)} Pflichtspiele, {cur:.0%} in der aktuellen Liga, keine Testspiele")

    # D — Serie konkret (letzte 10) + jüngste Ausreißer
    def show(g, side, is_team_home=None):
        vals = []
        for e, st in g:
            x = val(st, base, e["h"], side)
            if x is not None:
                vals.append(x)
        return vals
    if team_market:
        vals = show(own_games, "own")
        h10 = sum(hit(x, args.line, args.direction) for x in vals)
        st_ = "WARNUNG" if (len(vals) and h10 / len(vals) < 0.7) else "OK"
        step("D Serie Team", st_, f"eigene Werte {vals} → {h10}/{len(vals)} getroffen")
    else:
        for nm, g in sets:
            vals = show(g, "total")
            h10 = sum(hit(x, args.line, args.direction) for x in vals)
            st_ = "WARNUNG" if (len(vals) and h10 / len(vals) < 0.7) else "OK"
            step(f"D Serie {nm}", st_, f"Spielsummen {vals} → {h10}/{len(vals)}")

    # E — Rolle / Stärke (Backtest-Regeln)
    if diff_home is None:
        step("E Rolle", "WARNUNG", "Stärke nicht berechenbar (zu wenige Tor-Daten) → manuell prüfen")
    else:
        d_team = diff_home if (not team_market or side_home) else -diff_home
        role = role_label(d_team) if team_market else role_label(diff_home)
        who = "Team" if team_market else "Heim"
        txt = f"Tordiff-Schnitt Heim {sh:+.2f} / Gast {sa:+.2f} → {who}: {role}"
        status = "OK"
        if team_market and base == "corners" and args.direction == "unter":
            if role == "klarer Favorit":
                status, txt = "STOPP", txt + " · Teamecken unter als klarer Favorit (Backtest 66–75 %)"
            elif role == "Favorit":
                status, txt = "WARNUNG", txt + " · Teamecken unter als Favorit (Backtest 73–81 %)"
        if team_market and base == "corners" and args.direction == "über":
            if role == "klarer Außenseiter":
                status, txt = "STOPP", txt + " · Teamecken über als klarer Außenseiter (Backtest 59 %)"
            elif role == "Außenseiter":
                status, txt = "WARNUNG", txt + " · Teamecken über als Außenseiter (Backtest 67 %)"
        if not team_market and base == "yellowcards" and args.direction == "unter" and fav_proxy == "ausgeglichen":
            status, txt = "WARNUNG", txt + " · Karten unter in ausgeglichenem Spiel (Live 76 %)"
        if not team_market and base == "yellowcards" and args.direction == "über" and fav_proxy == "klar":
            status, txt = "WARNUNG", txt + " · Karten über mit klarem Favoriten (Live 72 %)"
        if not team_market and base == "offsides" and args.direction == "unter" and fav_proxy == "klar":
            status, txt = "WARNUNG", txt + " · Abseits unter mit klarem Favoriten (Live 73 %)"
        step("E Rolle", status, txt)

    # F — Gegner-Kontext (Team-Märkte): was lässt der Gegner zu?
    if team_market:
        opp_games = ag if side_home else hg
        allowed = [x for x in (val(st, base, e["h"], "opp") for e, st in opp_games) if x is not None]
        if allowed:
            share = sum(hit(x, args.line, args.direction) for x in allowed) / len(allowed)
            st_ = "WARNUNG" if share < 0.6 else "OK"
            step("F Gegner lässt zu", st_, f"Gegner-Gegenwerte {allowed} → {share:.0%} im Sinne des Tipps")
        else:
            step("F Gegner lässt zu", "WARNUNG", "keine Gegner-Daten")

    # G — Wettbewerb (Pokal/K.o.) und Derby
    cup = bool(CUP_WORDS.search(v["league"]))
    if base in ("yellowcards", "ht_yellowcards") and args.direction == "über" and cup:
        step("G Wettbewerb", "STOPP", "Karten über im Pokal (Analyse 11.10.: 61 % statt 75 %)")
    elif base in ("yellowcards", "ht_yellowcards") and args.direction == "unter" and cup:
        step("G Wettbewerb", "WARNUNG", "Karten unter im Pokal → K.o.-Spiel? (Regel: nie in K.o.) manuell klären")
    elif cup:
        step("G Wettbewerb", "OK", "Pokal/Qualifikation – für diesen Markt kein Ausschluss (K.o. trotzdem notieren)")
    else:
        step("G Wettbewerb", "OK", "Ligaspiel")
    if args.derby == "ja":
        if base in ("yellowcards", "ht_yellowcards") and args.direction == "unter":
            step("G Derby", "STOPP", "Derby + Karten unter (Regel: nie)")
        else:
            step("G Derby", "WARNUNG", "Derby – erhöhte Unberechenbarkeit")
    elif args.derby == "nein":
        step("G Derby", "OK", "kein Derby (geprüft)")
    else:
        step("G Derby", "MANUELL", "Derby/Rivalität prüfen und mit --derby ja/nein angeben")

    # H — Schiedsrichter (alle Kartenmärkte)
    if base in ("yellowcards", "ht_yellowcards", "fouls"):
        ref = args.schiri or s.get("referee") or ""
        mm = re.search(r"Ø\s*([\d.]+)|:\s*([\d.]+)", ref)
        avg = float(mm.group(1) or mm.group(2)) if mm else None
        if avg is None:
            step("H Schiri", "MANUELL", "Schiri unbekannt → nachschlagen (Pflicht), dann mit --schiri \"Name:Ø\" erneut prüfen")
        elif avg >= REF_WARN and args.direction == "unter":
            step("H Schiri", "STOPP" if team_market else "WARNUNG", f"{ref} – Ø ≥ {REF_WARN:g} Karten")
        else:
            step("H Schiri", "OK", ref)

    # J — Direkter Vergleich (nur Info: kleine Stichprobe)
    h2h = []
    for e in (hist.get(str(m.get("home_id"))) or {}).get("events", []):
        if scan.is_friendly(e.get("lg")):
            continue
        parts = [x.strip() for x in e["l"].split(" - ")]
        if len(parts) != 2 or v["away"] not in parts:
            continue
        st = stats.get(e["id"])
        if not st:
            continue
        if team_market:
            x = val(st, base, e["h"] if side_home else (not e["h"]), "own")
        else:
            x = val(st, base, e["h"], "total")
        if x is not None:
            h2h.append(x)
    if h2h:
        miss = [x for x in h2h if not hit(x, args.line, args.direction)]
        step("J Direkter Vergleich", "INFO", f"Werte {h2h}" + (f" · {len(miss)} Fehlschlag/-schläge" if miss else " · alle im Sinne des Tipps"))
    else:
        step("J Direkter Vergleich", "INFO", "kein früheres Duell in den Daten")

    # K — Spielverlaufs-Risiko (Merksatz, fest)
    if team_market and base == "corners" and args.direction == "unter":
        step("K Verlaufsrisiko", "INFO", "Rückstand → Team rennt an → Ecken (Hougang 12.10., Würzburg 13.10.)")
    return finish(args, out, res, v)


def finish(args, out, res, v):
    stops = [r for r in res if r[1] == "STOPP"]
    warns = [r for r in res if r[1] == "WARNUNG"]
    manual = [r for r in res if r[1] == "MANUELL"]
    if stops or warns:
        verdict = "❌ NICHT SPIELEN"
    elif manual:
        verdict = "✋ OFFEN – erst klären: " + ", ".join(r[0] for r in manual)
    else:
        verdict = "✅ SPIELEN"
    head = f"AUDIT {time.strftime('%d.%m. %H:%M')} · {args.team} · {args.metric} {args.direction} {args.line} @ {args.quote}"
    icon = {"OK": "✅", "WARNUNG": "⚠️", "STOPP": "⛔", "MANUELL": "✋", "INFO": "ℹ️"}
    lines = [head] + [f"{icon[s]} {c}: {t}" for c, s, t in res] + [f"URTEIL: {verdict}"]
    txt = "\n".join(lines)
    print(txt)
    d = ROOT / "audits"
    d.mkdir(exist_ok=True)
    with open(d / f"{time.strftime('%Y-%m-%d')}.md", "a", encoding="utf-8") as fh:
        fh.write(txt + "\n\n")
    return verdict


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("team")
    ap.add_argument("metric")
    ap.add_argument("direction", choices=["über", "unter"])
    ap.add_argument("line", type=float)
    ap.add_argument("quote", type=float)
    ap.add_argument("--schiri", default="")
    ap.add_argument("--derby", choices=["ja", "nein"], default=None)
    run(ap.parse_args())
