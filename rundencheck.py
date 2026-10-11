"""11.10. (Lucio): Reiner LESE-Test, ändert am Scanner nichts.

Frage: Lässt sich automatisch erkennen, ob ein Spiel ein Pokal-/K.o.-Spiel
(oder ein Derby) ist? Geprüft werden zwei Quellen:
  1) BetsAPI /v1/event/view -> Feld "extra" (enthält evtl. "round")
  2) scores24: Trends-JSON (Felder außer "data") und die Spielseite (Titel,
     Brotkrumen, Wörter wie Finale/Runde/Spieltag/Derby)
Bekannte vergangene Spiele (runs/rundencheck_ids.json) dienen als Abgleich,
dazu die anstehenden Spiele der nächsten Tage.

Start: Push auf "scan_now" mit "Rundencheck" in der Commit-Nachricht.
Ergebnis: runs/rundencheck_<Datum>.json — kein Scan, keine Telegram-Tipps.
"""
import json
import re
import time
from datetime import datetime, timedelta

RUNDEN_WORTE = re.compile(
    r"(finale?|halbfinale|viertelfinale|achtelfinale|sechzehntelfinale|"
    r"runde|spieltag|gruppe|playoff|play-off|qualifikation|hinspiel|"
    r"rückspiel|derby|round|final|semi|quarter|group|matchday|leg)",
    re.I)


def _snippets(text, max_n=25):
    out = []
    for m in RUNDEN_WORTE.finditer(text):
        a, b = max(0, m.start() - 70), min(len(text), m.end() + 70)
        s = re.sub(r"\s+", " ", text[a:b])
        if s not in out:
            out.append(s)
        if len(out) >= max_n:
            break
    return out


def _s24_probe(scan, match):
    """Slug wie im Scanner suchen, dann Trends-JSON + Spielseite lesen."""
    res = {"slug": None}
    want = frozenset(scan.variant_tags(match["home"]) | scan.variant_tags(match["away"]))
    ht, at = scan._name_tokens(match["home"]), scan._name_tokens(match["away"])
    cands = []
    for link, body, toks, tags in scan.s24_link_index():
        if tags != want:
            continue
        h = scan._tokens_match(ht, toks)
        a = scan._tokens_match(at, toks) if h else 0
        if h and a:
            cands.append((h + a, link))
    if not cands:
        return res
    link = sorted(cands, reverse=True)[0][1]
    res["slug"] = link
    try:
        raw = scan._s24_get("https://scores24.live/rapi/localized/matches/soccer/"
                            f"{link[2:]}/trends?lang=de&audience=de")
        j = json.loads(raw)
        res["trends_keys"] = sorted(j.keys()) if isinstance(j, dict) else str(type(j))
        res["trends_extra"] = {k: v for k, v in j.items() if k != "data"} if isinstance(j, dict) else None
    except Exception as exc:
        res["trends_err"] = str(exc)[:120]
    for name, url in (("rapi_match", "https://scores24.live/rapi/localized/matches/soccer/"
                       f"{link[2:]}?lang=de&audience=de"),
                      ("seite", f"https://scores24.live/de/soccer/{link}")):
        try:
            txt = scan._s24_get(url)
        except Exception as exc:
            res[name + "_err"] = str(exc)[:120]
            continue
        res[name + "_len"] = len(txt)
        if name == "seite":
            t = re.search(r"<title>(.*?)</title>", txt, re.S)
            res["title"] = t.group(1).strip()[:200] if t else None
            for prop in ("og:title", "description", "og:description"):
                m = re.search(r'<meta[^>]+(?:name|property)="%s"[^>]+content="([^"]*)"' % prop, txt)
                res[prop] = m.group(1)[:300] if m else None
            res["jsonld"] = [s[:1500] for s in re.findall(
                r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', txt, re.S)][:3]
            plain = re.sub(r"<script.*?</script>|<style.*?</style>", " ", txt, flags=re.S)
            plain = re.sub(r"<[^>]+>", " ", plain)
            res["text_hits"] = _snippets(plain)
            res["derby_im_quelltext"] = len(re.findall(r"derby", txt, re.I))
            # Rohdaten im Quelltext (Next/Redux-State) nach Rundenfeldern absuchen
            res["state_hits"] = sorted(set(re.findall(
                r'"(round|roundName|stage|stageName|tournamentStage|season|tournament|'
                r'isDerby|derby|cupRound|phase)"\s*:\s*("[^"]{0,80}"|\{[^{}]{0,200}\}|[\w.]+)',
                txt)))[:40]
        else:
            res[name + "_head"] = txt[:1500]
    return res


def run(scan):
    t0 = time.time()
    out = {"stand": datetime.now().isoformat(timespec="seconds"),
           "vergangen": [], "anstehend": []}
    # 1) bekannte vergangene Spiele: nur BetsAPI-extra (scores24 kennt sie
    #    nicht mehr in der Sitemap der anstehenden Spiele)
    known = json.loads((scan.RUNS_DIR / "rundencheck_ids.json").read_text(encoding="utf-8"))
    by_id = {k["id"]: k for k in known}
    ids = list(by_id)
    for i in range(0, len(ids), 10):
        try:
            view = scan.api_get("/v1/event/view", event_id=",".join(ids[i:i + 10]))
        except Exception as exc:
            out["vergangen"].append({"fehler": str(exc)[:160]})
            continue
        for ev in view.get("results", []):
            k = by_id.get(str(ev.get("id")), {})
            extra = dict(ev.get("extra") or {})
            for big in ("stadium_data", "home_manager", "away_manager", "referee"):
                if big in extra:
                    extra[big] = "…"
            out["vergangen"].append({
                "spiel": k.get("label"), "liga": k.get("league"),
                "top_keys": sorted(ev.keys()), "extra": extra})
    # 2) anstehende Spiele (nächste 4 Tage): BetsAPI-extra + scores24
    now, _ = scan.scan_window()
    matches = scan.fetch_matches_in_window(now, now + timedelta(days=4))
    pat = re.compile(r"cup|pokal|copa|coupe|coppa|ta[cç]a|kupa|beker|trophy|shield", re.I)
    cups = [m for m in matches if pat.search(m["league"])]
    seen, rest = set(), []
    for m in matches:                      # dazu je Liga ein normales Spiel
        if m in cups or m["league"] in seen:
            continue
        seen.add(m["league"])
        rest.append(m)
    pick = cups[:40] + rest[:20]
    out["anzahl_spiele_fenster"] = len(matches)
    out["anzahl_pokal_fenster"] = len(cups)
    views = {}
    ids = [m["id"] for m in pick]
    for i in range(0, len(ids), 10):
        try:
            view = scan.api_get("/v1/event/view", event_id=",".join(ids[i:i + 10]))
            for ev in view.get("results", []):
                views[str(ev.get("id"))] = ev
        except Exception as exc:
            out.setdefault("fehler", []).append(str(exc)[:160])
    for m in pick:
        ev = views.get(str(m["id"]), {})
        extra = dict(ev.get("extra") or {})
        for big in ("stadium_data", "home_manager", "away_manager", "referee"):
            if big in extra:
                extra[big] = "…"
        row = {"spiel": f"{m['home']} - {m['away']}", "liga": m["league"],
               "anstoss": m["kickoff"], "extra": extra,
               "top_keys": sorted(ev.keys())}
        try:
            row["scores24"] = _s24_probe(scan, m)
        except Exception as exc:
            row["scores24"] = {"fehler": str(exc)[:160]}
        out["anstehend"].append(row)
    out["dauer_s"] = round(time.time() - t0)
    scan.RUNS_DIR.mkdir(exist_ok=True)
    p = scan.RUNS_DIR / f"rundencheck_{time.strftime('%Y-%m-%d')}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Rundencheck geschrieben: {p.name} ({len(out['vergangen'])} vergangen, "
          f"{len(out['anstehend'])} anstehend, {out['dauer_s']} s)")
