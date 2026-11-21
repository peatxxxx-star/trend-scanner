"""Eigene Teamwerte aus den letzten Spielen bei scores24 (statt FootyStats).

21.11. (Lucio): FootyStats zeigt auf der Spielseite nur Heim- bzw. Auswärtswerte, ohne die
Spielzahl zu nennen. Hier rechnen wir selbst – nur Ligaspiele der laufenden Saison, einmal über
alle Spiele und einmal in der Rolle (Gastgeber zu Hause, Gast auswärts), immer mit Spielzahl.

Quelle: /rapi/matches/soccer/{slug}/team-matches?teamType=home|away (bis 20 Spiele pro Seite,
alle Wettbewerbe, mit Ergebnis, Halbzeit, Ecken und Gelben Karten).
"""
import gzip
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from s24liste import get as s24_get

TTL = 12 * 3600
URL = ("https://scores24.live/rapi/matches/soccer/{slug}/team-matches?teamType={tt}&first=20"
       "&lang=de&sort=desc&status=finished&withStatistics=true")


def _d(x):
    return x if isinstance(x, dict) else {}


def _l(x):
    return x if isinstance(x, list) else []


def _paar(s):
    try:
        a, b = str(s).split(":")
        return int(a), int(b)
    except Exception:
        return None


def _abrufen(slug, tt):
    nodes, url = [], URL.format(slug=slug, tt=tt)
    for seite in range(2):                       # höchstens 2 Seiten (40 Spiele)
        d = _d(_d(json.loads(s24_get(url))).get("data"))
        nodes += [_d(e).get("node") for e in _l(d.get("edges")) if _d(_d(e).get("node"))]
        pi = _d(d.get("pageInfo"))
        if seite == 0 and pi.get("hasNextPage") and pi.get("endCursor") and len(nodes) >= 20:
            url = URL.format(slug=slug, tt=tt) + "&after=" + pi["endCursor"]
        else:
            break
    return nodes


def _spiele(nodes):
    """Knoten -> Spiele aus Sicht des Teams (das in allen Knoten vorkommt)."""
    nodes = [n for n in _l(nodes) if isinstance(n, dict)]
    c = Counter(_d(t).get("slug") for n in nodes for t in _l(n.get("teams"))[:2])
    if not c:
        return None, []
    team = c.most_common(1)[0][0]
    out = []
    for n in nodes:
        ts = [_d(t) for t in _l(n.get("teams"))]
        if len(ts) < 2 or team not in (ts[0].get("slug"), ts[1].get("slug")):
            continue
        heim = ts[0].get("slug") == team
        rs = {_d(r).get("type"): _paar(_d(r).get("value")) for r in _l(n.get("result_scores"))}
        ft = rs.get("FT") or _paar(n.get("result_score"))
        if not ft:
            continue
        ht = rs.get("HT")
        st = {_d(i).get("type"): (_d(i).get("team1_value"), _d(i).get("team2_value"))
              for i in _l(_d(n.get("statistic")).get("items"))}

        def wert(typ):
            v = st.get(typ)
            try:
                a, b = int(v[0]), int(v[1])
            except Exception:
                return None
            return (a, b) if heim else (b, a)
        tf, tg = ft if heim else (ft[1], ft[0])
        h = (ht if heim else (ht[1], ht[0])) if ht else None
        liga = n.get("league_slug") or _d(n.get("unique_tournament")).get("slug") or ""
        out.append({"d": n.get("match_date") or "", "ort": "H" if heim else "A", "tf": tf, "tg": tg,
                    "hf": h[0] if h else None, "hg": h[1] if h else None,
                    "ecken": wert("corner_kicks"), "gelb": wert("yellow_cards"),
                    "liga": liga, "tab": bool(n.get("has_standings")),
                    "freund": "friendly" in liga})
    out.sort(key=lambda s: s["d"], reverse=True)
    return team, out


_POKAL = ("cup", "pokal", "copa", "coupe", "trophy", "taca", "taça", "beker", "kupa", "puchar", "coppa",
          "supercup", "super-cup", "playoff", "play-off", "friendly", "qualification")


def _datum(s):
    try:
        return datetime.fromisoformat(s["d"].replace("Z", "+00:00"))
    except Exception:
        return None


def _saison(spiele, n_tab):
    """Nur Ligaspiele der laufenden Saison.
    Liga = häufigster Wettbewerb mit Tabelle; hat scores24 für die Liga keine Tabelle (z. B. 3. Liga
    Polen, U19 Slowakei), dann der häufigste Wettbewerb, der nicht nach Pokal/Testspiel aussieht.
    Saison = die letzten n_tab Spiele laut Tabelle, sonst bis zur ersten Pause > 60 Tage."""
    liga = Counter(s["liga"] for s in spiele if s["tab"] and not s["freund"]).most_common(1)
    if not liga:
        liga = Counter(s["liga"] for s in spiele
                       if s["liga"] and not any(w in s["liga"].lower() for w in _POKAL)).most_common(1)
    if not liga:
        return []
    ls = [s for s in spiele if s["liga"] == liga[0][0]]
    if n_tab:
        return ls[:n_tab]
    out, vorher = [], None
    for s in ls:                                   # neueste zuerst
        d = _datum(s)
        if d is None:
            continue
        if vorher is not None and (vorher - d).days > 60:
            break
        if not out and (datetime.now(timezone.utc) - d).days > 60:
            break                                  # letzte Ligaspiele zu alt -> Saison vorbei
        out.append(s)
        vorher = d
    return out


def laden(eintraege, cache_datei):
    """eintraege: [(slug, n_heim, n_gast)] -> {slug: {"heim": [...], "gast": [...]}}"""
    try:
        with gzip.open(cache_datei, "rt", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    jetzt = time.time()
    fehlt = [(s, tt) for s, _, _ in eintraege for tt in ("home", "away")
             if jetzt - _d(cache.get(f"{s}|{tt}")).get("t", 0) > TTL]

    def eins(a):
        s, tt = a
        try:
            return a, _abrufen(s, tt)
        except Exception:
            return a, None
    with ThreadPoolExecutor(8) as ex:
        for (s, tt), nodes in ex.map(eins, fehlt):
            if nodes is not None:
                cache[f"{s}|{tt}"] = {"t": jetzt, "nodes": nodes}
    cache = {k: v for k, v in cache.items() if jetzt - v.get("t", 0) < 2 * 86400}
    cache_datei.parent.mkdir(exist_ok=True)
    with gzip.open(cache_datei, "wt", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    out = {}
    for s, nh, ng in eintraege:
        r = {}
        for tt, seite, n in (("home", "heim", nh), ("away", "gast", ng)):
            nodes = _d(cache.get(f"{s}|{tt}")).get("nodes")
            if nodes:
                _, sp = _spiele(nodes)
                r[seite] = _saison(sp, n)
                r["liga_" + seite] = r[seite][0]["liga"] if r[seite] else None
        out[s] = r
    return out


# ------------------------------------------------------------------ Markt-Gegencheck
def _quote(spiele, bed):
    ok = n = 0
    for s in spiele:
        v = bed(s)
        if v is None:
            continue
        n += 1
        ok += bool(v)
    return ok, n


def _wert(s, metric, wer):
    """wer: 'f' (für das Team), 'g' (gegen), 's' (Summe)."""
    if metric == "goals":
        f, g = s["tf"], s["tg"]
    elif metric == "ht_goals":
        if s["hf"] is None:
            return None
        f, g = s["hf"], s["hg"]
    elif metric == "h2_goals":
        if s["hf"] is None:
            return None
        f, g = s["tf"] - s["hf"], s["tg"] - s["hg"]
    elif metric in ("corners", "yellowcards"):
        v = s["ecken"] if metric == "corners" else s["gelb"]
        if not v:
            return None
        f, g = v
    else:
        return None
    return {"f": f, "g": g, "s": f + g}[wer]


def bedingungen(k):
    """-> (Bedingung fürs eigene Team, Bedingung für den Gegner) oder None, wenn keine Daten."""
    art = k["art"]
    if art == "dc":
        w = k["wahl"]
        heim = {"x1": lambda s: s["tf"] >= s["tg"], "x2": lambda s: s["tf"] <= s["tg"],
                "12": lambda s: s["tf"] != s["tg"]}[w]
        gast = {"x1": lambda s: s["tf"] <= s["tg"], "x2": lambda s: s["tf"] >= s["tg"],
                "12": lambda s: s["tf"] != s["tg"]}[w]
        return heim, gast, "heim"
    if art == "hc":
        L = k["linie"]
        return (lambda s: s["tf"] - s["tg"] + L > 0), (lambda s: s["tg"] - s["tf"] + L > 0), k["seite"]
    m, L, ueber = k["metric"], k["linie"], k["richtung"] == "über"
    if m not in ("goals", "ht_goals", "h2_goals", "corners", "yellowcards"):
        return None

    def cmp(v):
        return None if v is None else (v > L if ueber else v < L)
    if not k["seite"]:
        b = lambda s: cmp(_wert(s, m, "s"))
        return b, b, "heim"
    return (lambda s: cmp(_wert(s, m, "f"))), (lambda s: cmp(_wert(s, m, "g"))), k["seite"]


_GENERISCH = {"fc", "fk", "sc", "sv", "ud", "us", "ss", "cd", "cf", "ca", "ac", "as", "afc", "csc", "cs", "fsv",
              "vfb", "vfl", "tsv", "sk", "nk", "ks", "gks", "mks", "club", "real", "atletico", "sporting",
              "deportivo", "union", "st.", "san", "the", "royal", "kv", "kfc", "rsc", "if", "bk", "ik", "aik"}


def kurzname(n):
    ts = [t for t in (n or "").replace("(", " ").replace(")", " ").split() if t]
    for t in ts:
        if t.lower() not in _GENERISCH and len(t) > 2:
            return t[:13]
    return (" ".join(ts[:2]) or "?")[:13]


def _schnitt(sp, f):
    w = [f(x) for x in sp]
    w = [x for x in w if x is not None]
    return sum(w) / len(w) if w else None


def deckel(k, st, x12):
    """21.11. Spaßschein-Regeln, die über die reine Trefferquote hinausgehen -> Gründe für höchstens 🟡."""
    H, G = st.get("heim") or [], st.get("gast") or []
    gruende = []
    ga = {"heim": _schnitt(H, lambda s: s["tg"]), "gast": _schnitt(G, lambda s: s["tg"])}
    tot = {"heim": _schnitt(H, lambda s: s["tf"] + s["tg"]), "gast": _schnitt(G, lambda s: s["tf"] + s["tg"])}
    if k["art"] == "ou" and k["metric"] == "goals":
        L = k["linie"]
        if k["seite"] and k["richtung"] == "unter" and x12:
            eigen, gegner = (x12[0], x12[2]) if k["seite"] == "heim" else (x12[2], x12[0])
            andere = "gast" if k["seite"] == "heim" else "heim"
            if eigen < gegner and ga[andere] is not None and ga[andere] >= 1.5:
                gruende.append(f"Favorit, Gegner kassiert {ga[andere]:.1f}".replace(".", ",") + " pro Spiel")
        if not k["seite"] and k["richtung"] == "unter":
            for sd in ("heim", "gast"):
                if tot[sd] is not None and tot[sd] > L - 1.0:
                    gruende.append(f"Ø {tot[sd]:.1f}".replace(".", ",") + " Tore pro Spiel, weniger als 1 unter der Linie")
                    break
        if not k["seite"] and k["richtung"] == "über":
            if L == 1.5:
                for sd, sp in (("heim", H), ("gast", G)):
                    ok, n = _quote(sp, lambda s: s["tf"] + s["tg"] > 1.5)
                    if n and ok / n < 0.85:
                        gruende.append(f"über 1,5 nur {ok / n:.0%} (<85 %)")
                        break
                if any(v is not None and v < 1.0 for v in ga.values()):
                    gruende.append("starke Abwehr (unter 1,0 Gegentore pro Spiel)")
            else:
                for sd in ("heim", "gast"):
                    if tot[sd] is not None and tot[sd] < L + 1.0:
                        gruende.append(f"Ø {tot[sd]:.1f}".replace(".", ",") + " Tore pro Spiel, weniger als 1 über der Linie")
                        break
    return gruende


def gegencheck(k, st, heim_name, gast_name, quote, mit_tabelle=True, x12=None):
    """Zeilen für Telegram + Vorcheck-Symbol. st = {"heim": [...], "gast": [...]}"""
    b = bedingungen(k)
    if not b or not st or not st.get("heim") or not st.get("gast"):
        return None
    b_eigen, b_gegner, seite = b
    if seite == "heim":
        bh, bg = b_eigen, b_gegner
    else:
        bh, bg = b_gegner, b_eigen
    H, G = st["heim"], st["gast"]
    ah, ag = _quote(H, bh), _quote(G, bg)
    rh = _quote([s for s in H if s["ort"] == "H"], bh)
    rg = _quote([s for s in G if s["ort"] == "A"], bg)
    if not ah[1] or not ag[1]:
        return None
    be = 1 / quote if quote else None
    p = lambda x: f"{x[0]}/{x[1]}" + (f" ({x[0] / x[1]:.0%})" if x[1] else "")
    # Vorcheck: Rot, wenn eine Gesamtquote unter Break-even; Grün nur mit Puffer und Stichprobe
    alle = [x[0] / x[1] for x in (ah, ag)]
    rolle = [x[0] / x[1] for x in (rh, rg) if x[1] >= 4]
    if be is None:
        sym = "⚪"
    elif min(alle) < be:
        sym = "🔴"
    elif min(alle) >= be + 0.05 and min(ah[1], ag[1]) >= 8 and all(r >= be for r in rolle):
        sym = "🟢"
    else:
        sym = "🟡"
    grund = ""
    if sym == "🟢" and not mit_tabelle:
        sym, grund = "🟡", "evtl. kein Ligaspiel"      # Ligawerte evtl. fremder Wettbewerb
    if sym == "🟢":
        g = deckel(k, st, x12)
        if g:
            sym, grund = "🟡", g[0]
    hn, gn = kurzname(heim_name), kurzname(gast_name)
    if hn == gn:
        hn, gn = heim_name[:13], gast_name[:13]
    z1 = (f"{sym} Alle: {hn} {p(ah)} · {gn} {p(ag)}" + (f" · BE {be:.0%}" if be else "")
          + (f" · 🟡 weil: {grund}" if grund else ""))
    z2 = f"   Rolle: {hn} heim {p(rh)} · {gn} ausw. {p(rg)}"
    return {"sym": sym, "zeilen": [z1, z2], "alle": [ah, ag], "rolle": [rh, rg]}


def schnitt(st):
    """Kurzer Torschnitt pro Team aus den Ligaspielen (für die Kopfzeile)."""
    out = {}
    for seite in ("heim", "gast"):
        sp = st.get(seite) or []
        if sp:
            out[seite] = (len(sp), sum(s["tf"] for s in sp) / len(sp), sum(s["tg"] for s in sp) / len(sp))
    return out
