"""Torschützen-Scan (01.11., Lucio): Welche BL-Spiele eines Tages haben einen Torschützen-Markt?
Erkennung ohne Gruppennamen: Ereignisse mit Spielerbezug (Feld PL / Spielername) im Hauptspiel oder in
Unterspielen, deren Titel nach Spielern/Torschützen klingt. Schreibt runs/torschuetzen_<Tag>.json."""
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

B = ZoneInfo("Europe/Berlin")
WORTE = ("torsch", "spieler", "player", "scorer", "goalscorer", "tor erzielt", "trifft")


def _pl_events(val):
    """(Anzahl Ereignisse mit Spielerbezug, {Gruppe: Anzahl}, Beispiel-Namen)."""
    n, gr, namen = 0, {}, []
    for g in val.get("GE") or []:
        for col in g.get("E") or []:
            for e in col:
                pl = e.get("PL") or {}
                if pl or e.get("PN"):
                    n += 1
                    gr[g.get("G")] = gr.get(g.get("G"), 0) + 1
                    nm = pl.get("N") if isinstance(pl, dict) else None
                    if nm and len(namen) < 4:
                        namen.append(nm)
    return n, gr, namen


def run(runs_dir, tag=None):
    import betlabel
    jetzt = datetime.now(B)
    tag = tag or (jetzt + timedelta(days=1)).strftime("%Y-%m-%d")
    spiele = [g for g in betlabel.lade_spiele(frisch=True)
              if datetime.fromtimestamp(g["S"], B).strftime("%Y-%m-%d") == tag]

    def eins(g):
        try:
            h = betlabel._spiel_detail(g["I"])
        except Exception as exc:
            return g, {"fehler": str(exc)[:80]}
        n, gr, namen = _pl_events(h)
        sgs = []
        for sg in h.get("SG") or []:
            t = ((sg.get("TG") or "") + " " + (sg.get("PN") or "")).strip()
            sgs.append(t)
        treffer = [t for t in sgs if any(w in t.lower() for w in WORTE)]
        sub_pl = 0
        for sg in (h.get("SG") or []):
            t = ((sg.get("TG") or "") + " " + (sg.get("PN") or "")).lower()
            if any(w in t for w in WORTE):
                try:
                    v = betlabel._spiel_detail(sg.get("CI") or sg.get("I"))
                    sub_pl += _pl_events(v)[0]
                except Exception:
                    pass
        return g, {"pl_haupt": n, "pl_gruppen": gr, "namen": namen, "sg_spieler": treffer,
                   "sub_pl": sub_pl, "sg_alle": sorted(set(sgs))[:40]}

    out = []
    with ThreadPoolExecutor(12) as ex:
        for g, r in ex.map(eins, spiele):
            out.append(dict(zeit=datetime.fromtimestamp(g["S"], B).strftime("%H:%M"), liga=g.get("L"),
                            spiel=f"{g.get('O1')} – {g.get('O2')}", id=g["I"], **r))
    out.sort(key=lambda x: (x["zeit"], x["liga"] or ""))
    p = runs_dir / f"torschuetzen_{tag}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("Torschützen-Scan:", tag, len(out), "Spiele,",
          sum(1 for x in out if x.get("pl_haupt") or x.get("sub_pl") or x.get("sg_spieler")), "mit Spielerbezug")
    return out
