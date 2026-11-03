"""Pferde-Quoten von BetLabel (03.11., Lucio: "Bei BetLabel gibt es auch Quoten
für Pferderennen ... ob du die nicht darüber mit abgefragt bekommst").

Claudes stündlicher Pferde-Check kommt aus der Cloud nicht an Racing Post/
Oddschecker heran, und betlabel.com ist dort gesperrt. GitHub Actions erreicht
den Feed – dieses Skript holt die Rennen (GB/IRE) samt Sieg-Quoten und legt sie
unter state/pferde_quoten_<JJJJ-MM-TT>.json ab. Start: Push auf "pferde_now".

Erster Lauf ist zugleich Erkundung: Welche Sport-Id hat Pferderennen, wie
heißen die Ligen, wie sind Rennen und Starter im Feed abgelegt? Dafür landen
die Rohdaten der ersten Rennen unter "roh" mit in der Datei.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from betlabel import _get, _stats

WORTE = ("horse", "racing", "pferd", "galopp", "turf")
GB_IE = ("uk", "united kingdom", "great britain", "england", "ireland", "irland", "gb", "ire",
         "lingfield", "warwick", "sedgefield", "fairyhouse", "wolverhampton")


def sportarten():
    out = []
    for pfad in ("GetSportsShortZip", "GetSportsZip"):
        try:
            v = _get(pfad, lng="en", country=1).get("Value") or []
            out = [{"I": s.get("I"), "N": s.get("N"), "C": s.get("C")} for s in v]
            if out:
                return out, pfad
        except Exception as e:
            out = [{"fehler": f"{pfad}: {e}"}]
    return out, None


def main():
    heute = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    erg = {"stand_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "quelle": "betlabel"}
    sports, pfad = sportarten()
    erg["sportarten_quelle"] = pfad
    erg["sportarten"] = sports
    kandid = [s for s in sports if any(w in (s.get("N") or "").lower() for w in WORTE)]
    erg["pferde_sport"] = kandid
    rennen, roh = [], []
    for sp in kandid:
        sid = sp["I"]
        try:
            champs = _get("GetChampsZip", sport=sid, lng="en", country=1).get("Value") or []
        except Exception as e:
            erg.setdefault("fehler", []).append(f"champs {sid}: {e}")
            continue
        erg.setdefault("ligen", []).extend(
            {"sport": sid, "LI": c.get("LI"), "L": c.get("L"), "GC": c.get("GC")} for c in champs)
        for c in champs:
            name = (c.get("L") or "").lower()
            if not any(w in name for w in GB_IE):
                continue
            try:
                spiele = _get("Get1x2_VZip", sports=sid, champs=c["LI"], count=50, lng="en",
                              mode=4, country=1, getEmpty="true").get("Value") or []
            except Exception as e:
                erg.setdefault("fehler", []).append(f"spiele {c.get('L')}: {e}")
                continue
            for g in spiele:
                gid = g.get("I")
                try:
                    d = _get("GetGameZip", id=gid, lng="en", isSubGames="true", GroupEvents="true",
                             countevents=500, grMode=4, partner=1, topGroups="", marketType=1
                             ).get("Value") or {}
                except Exception as e:
                    d = {"fehler": str(e)}
                if len(roh) < 3:
                    roh.append({"liste": g, "detail": d})
                start = int(g.get("S") or d.get("S") or 0)
                rennen.append({
                    "liga": c.get("L"), "id": gid,
                    "start_utc": datetime.fromtimestamp(start, timezone.utc).strftime("%H:%M") if start else None,
                    "name": " / ".join(x for x in (g.get("O1"), g.get("O2"), d.get("O1"), g.get("L")) if x),
                    "maerkte": [{"G": e.get("G"), "T": e.get("T"), "C": e.get("C"), "P": e.get("P"),
                                 "N": e.get("N"), "PL": e.get("PL")}
                                for grp in (d.get("GE") or []) for liste in (grp.get("E") or [])
                                for e in (liste if isinstance(liste, list) else [liste])][:200],
                })
                time.sleep(0.2)
    erg["rennen"] = rennen
    erg["roh"] = roh
    erg["anfragen"] = dict(_stats)
    p = Path("state") / f"pferde_quoten_{heute}.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(erg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(kandid)} Pferde-Sportart(en), {len(erg.get('ligen', []))} Ligen, {len(rennen)} Rennen GB/IRE -> {p}")


if __name__ == "__main__":
    main()
