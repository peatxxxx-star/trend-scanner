"""12.10. (Lucio: "2 auch direkt"): Reiner LESE-Lauf, ändert am Scanner nichts.

Holt für eine feste Liste vergangener Spiele (runs/quotencheck_ids.json) den
bet365-Quotenverlauf über /v2/event/odds und speichert je Spiel Eröffnungs- und
Schlussquote (letzte Quote vor Anpfiff) für:
  1_1  1X2               (Stärke-Einschätzung des Buchmachers)
  1_3  Tore Über/Unter   (Hauptlinie)
  1_4  Ecken Über/Unter  (Hauptlinie)
Damit wird offline getestet, ob das Wissen des Buchmachers die Trefferquote
der Scanner-Signale erklärt (Modelltest Teil 2).

Start: Push auf "scan_now" mit "Quotencheck" in der Commit-Nachricht.
Fortsetzbar: bereits geholte Spiele werden übersprungen; jeder Lauf stoppt
nach QC_MINUTES Minuten bzw. QC_MAX_REQ Anfragen. Ergebnis:
runs/quotencheck_data.json  (id -> {m: {"o": [...], "c": [...]}})
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

QC_MINUTES = 36
QC_MAX_REQ = 2600
MARKETS = {"1_1": ("home_od", "draw_od", "away_od"),
           "1_3": ("handicap", "over_od", "under_od"),
           "1_4": ("handicap", "over_od", "under_od")}


def _prematch(rows):
    out = []
    for r in rows or []:
        if r.get("ss") not in (None, "") or r.get("time_str") not in (None, ""):
            continue                        # Live-Quote (Spielstand oder Minute gesetzt)
        out.append(r)
    return out


def extract(res):
    odds = (res or {}).get("odds") or {}
    d = {}
    for mk, fields in MARKETS.items():
        rows = _prematch(odds.get(mk))
        vals = []
        for r in rows:                      # jüngste zuerst
            try:
                v = [float(r[f]) for f in fields]
            except (KeyError, TypeError, ValueError):
                continue
            vals.append(v)
        if vals:
            d[mk] = {"c": vals[0], "o": vals[-1], "n": len(vals)}
    return d


def run(scan):
    t0 = time.time()
    ids_p = scan.RUNS_DIR / "quotencheck_ids.json"
    data_p = scan.RUNS_DIR / "quotencheck_data.json"
    ids = json.loads(ids_p.read_text(encoding="utf-8"))
    data = json.loads(data_p.read_text(encoding="utf-8")) if data_p.exists() else {}
    todo = [i for i in ids if i not in data][:QC_MAX_REQ]
    print(f"Quotencheck: {len(data)} schon da, {len(todo)} in diesem Lauf geplant")
    fehler = 0
    done = 0

    sample = {}

    def one(eid):
        res = scan.api_get("/v2/event/odds", event_id=eid, odds_market="1,3,4")
        r = res.get("results") or {}
        if not sample and (r.get("odds") or {}).get("1_1"):
            # Rohformat einmal sichern (je Markt die ersten/letzten 3 Zeilen)
            sample.update({mk: {"anz": len(v), "erste": v[:3], "letzte": v[-3:]}
                           for mk, v in (r.get("odds") or {}).items()})
            sample["_id"] = eid
            sample["_keys"] = sorted(r.keys())
        return eid, extract(r)

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = []
        for eid in todo:
            futs.append(ex.submit(one, eid))
        for f in as_completed(futs):
            try:
                eid, d = f.result()
                data[eid] = d
            except Exception as exc:
                fehler += 1
                if fehler <= 5:
                    print("  Fehler:", str(exc)[:120])
            done += 1
            if done % 250 == 0:
                data_p.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
                print(f"  {done}/{len(todo)} ({round(time.time() - t0)} s)", flush=True)
            if time.time() - t0 > QC_MINUTES * 60:
                print("  Zeitlimit erreicht — Rest im nächsten Lauf")
                for g in futs:
                    g.cancel()
                break
    data_p.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    if sample:
        (scan.RUNS_DIR / "quotencheck_sample.json").write_text(
            json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    mit = sum(1 for v in data.values() if v)
    print(f"Quotencheck fertig: {len(data)}/{len(ids)} Spiele abgefragt, {mit} mit Quoten, "
          f"{fehler} Fehler, {round(time.time() - t0)} s")
