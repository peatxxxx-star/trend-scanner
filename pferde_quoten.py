"""Pferde-Quoten von BetLabel (03.11., Lucio: "Bei BetLabel gibt es auch Quoten
für Pferderennen ... ob du die nicht darüber mit abgefragt bekommst").

Claudes stündlicher Pferde-Check kommt aus der Cloud nicht an Racing Post/
Oddschecker heran, und betlabel.com ist dort gesperrt. GitHub Actions erreicht
den Feed: dieses Skript holt alle Rennen in GB/IRE samt Sieg-Quoten und legt
sie unter state/pferde_quoten_<JJJJ-MM-TT>.json ab. Start: Push auf "pferde_now".

Feed (1xBet-Plattform, wie betlabel.py): Sport 44 = Horse Racing, je Bahn eine
"Liga" ("United Kingdom. Warwick"), je Rennen ein Spiel. GetGameZip liefert
Gruppe 26 = Sieg-Quoten (PL.N = "№7 Some Song"), Gruppe 7571 = SP, und unter
GI/Stat Starterliste mit Jockey (J), Trainer (T), Form (E), Gewicht (W).
"erste" = erste Quote des Tages je Pferd -> Bewegung seit dem Morgen.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from betlabel import _get, _stats

SPORT = 44
LAENDER = ("United Kingdom.", "Ireland.")
MEZ = timezone(timedelta(hours=1))   # Winterzeit; ab 28.03.2027 +2


def _stat(d):
    for gi in d.get("GI") or []:
        if gi.get("Key") == "Stat":
            try:
                return json.loads(gi.get("Value") or "{}")
            except Exception:
                return {}
    return {}


def rennen_detail(gid):
    d = _get("GetGameZip", id=gid, lng="en", isSubGames="true", GroupEvents="true",
             countevents=500, grMode=4, partner=1, topGroups="", marketType=1).get("Value") or {}
    st = _stat(d)
    info = {(r.get("N") or "").lower(): r for r in st.get("R") or []}
    pferde = {}
    for grp in d.get("GE") or []:
        if grp.get("G") != 26:
            continue
        for liste in grp.get("E") or []:
            for e in (liste if isinstance(liste, list) else [liste]):
                name = re.sub(r"^№\s*\d+\s*", "", (e.get("PL") or {}).get("N") or "").strip()
                if not name:
                    continue
                r = info.get(name.lower(), {})
                pferde[name] = {"nr": e.get("N"), "quote": e.get("C"), "jockey": r.get("J"),
                                "trainer": r.get("T"), "form": r.get("E"), "alter": r.get("A")}
    return d, st, pferde


def main():
    jetzt = datetime.now(timezone.utc)
    heute = jetzt.astimezone(MEZ).strftime("%Y-%m-%d")
    p = Path("state") / f"pferde_quoten_{heute}.json"
    alt = {}
    if p.exists():
        try:
            alt = {r["key"]: r for r in json.loads(p.read_text(encoding="utf-8")).get("rennen", [])}
        except Exception:
            alt = {}
    champs = _get("GetChampsZip", sport=SPORT, lng="en", country=1).get("Value") or []
    champs = [c for c in champs if (c.get("L") or "").startswith(LAENDER)]
    rennen, fehler = [], []
    for c in champs:
        bahn = c["L"].split(". ", 1)[-1]
        try:
            spiele = _get("Get1x2_VZip", sports=SPORT, champs=c["LI"], count=50, lng="en",
                          mode=4, country=1, getEmpty="true").get("Value") or []
        except Exception as e:
            fehler.append(f"{bahn}: {e}")
            continue
        for g in spiele:
            start = int(g.get("S") or 0)
            zeit = datetime.fromtimestamp(start, timezone.utc).astimezone(MEZ)
            if zeit.strftime("%Y-%m-%d") != heute:
                continue
            try:
                d, st, pferde = rennen_detail(g["I"])
            except Exception as e:
                fehler.append(f"{bahn} {zeit:%H:%M}: {e}")
                continue
            key = f"{zeit:%H:%M} {bahn}"
            frueher = (alt.get(key) or {}).get("pferde", {})
            for name, v in pferde.items():
                f = frueher.get(name, {})
                v["erste"] = f.get("erste") or v["quote"]
                v["erste_um"] = f.get("erste_um") or f"{jetzt.astimezone(MEZ):%H:%M}"
            fehlen = sorted(set(frueher) - set(pferde))
            reihe = sorted(pferde.items(), key=lambda kv: kv[1]["quote"] or 999)
            rennen.append({
                "key": key, "zeit_mez": f"{zeit:%H:%M}", "bahn": bahn, "land": c["L"].split(".")[0],
                "id": g["I"], "starter": len(pferde), "distanz_m": st.get("D"), "alter": st.get("AGE"),
                "favorit": reihe[0][0] if reihe else None,
                "favoritenquote": reihe[0][1]["quote"] if reihe else None,
                "nicht_mehr_im_feld": sorted(set(fehlen) | set((alt.get(key) or {}).get("nicht_mehr_im_feld", []))),
                "pferde": dict(reihe),
            })
    rennen.sort(key=lambda r: (r["zeit_mez"], r["bahn"]))
    erg = {"stand_utc": f"{jetzt:%Y-%m-%d %H:%M}", "stand_mez": f"{jetzt.astimezone(MEZ):%H:%M}",
           "quelle": "betlabel.com LineFeed (Sport 44)", "fehler": fehler,
           "anfragen": dict(_stats), "rennen": rennen}
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(erg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(champs)} Bahnen, {len(rennen)} Rennen, {len(fehler)} Fehler -> {p}")


if __name__ == "__main__":
    main()
