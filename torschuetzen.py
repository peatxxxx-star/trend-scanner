"""Torschützen-Scan (01.11., Lucio): Welche BL-Spiele haben einen Torschützen-Markt?
Erkennung: Ereignisse mit Spielerbezug (PL) im Hauptspiel (Gruppe 119 = Torschütze); daneben Spiele, die nur
„Spielerstatistik“ als Unterspiel haben. Feste Läufe mit Zeitfenster (Lucio 01.11.):
06 → bis 18 · 12 → bis 18 · 15 → bis 21 · 18 → bis 21 · 19 → bis 24 · 21 → bis 07 (nächster Morgen)."""
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

B = ZoneInfo("Europe/Berlin")
WT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _wt(dt):
    return f"{WT[dt.weekday()]} {dt:%H:%M}"
PLAN = {6: 18, 12: 18, 15: 21, 18: 21, 19: 24, 21: 31}      # Starthour → Endstunde (31 = morgen 07:00)
STATE = "state/torschuetzen_gesendet.json"


def _pl_events(val):
    n, namen = 0, []
    for g in val.get("GE") or []:
        for col in g.get("E") or []:
            for e in col:
                pl = e.get("PL") or {}
                if pl:
                    n += 1
                    nm = pl.get("N") if isinstance(pl, dict) else None
                    if nm and nm not in namen and len(namen) < 3:
                        namen.append(nm)
    return n, namen


def scan(von, bis):
    """Spiele mit Anstoß in [von, bis) → Liste dicts (zeit, liga, spiel, torschuetze, spielerstatistik, namen)."""
    import betlabel
    spiele = [g for g in betlabel.lade_spiele(frisch=True) if von.timestamp() <= g["S"] < bis.timestamp()]

    def eins(g):
        try:
            h = betlabel._spiel_detail(g["I"])
        except Exception:
            return g, None
        n, namen = _pl_events(h)
        stat = any("spielerstatistik" in (sg.get("TG") or "").lower() for sg in h.get("SG") or [])
        return g, {"torschuetze": n > 0, "spielerstatistik": stat, "namen": namen}

    out = []
    with ThreadPoolExecutor(12) as ex:
        for g, r in ex.map(eins, spiele):
            if r and (r["torschuetze"] or r["spielerstatistik"]):
                out.append(dict(ts=g["S"], zeit=_wt(datetime.fromtimestamp(g["S"], B)),
                                liga=g.get("L") or "", spiel=f"{g.get('O1')} – {g.get('O2')}", **r))
    out.sort(key=lambda x: (x["ts"], x["liga"]))
    return out, len(spiele)


def text(out, n_alle, von, bis, esc=lambda s: s):
    """01.11. (Lucio): nach Liga gruppiert. Ligen in der Reihenfolge ihres ersten Anstoßes, darunter alle
    Spiele dieser Liga im Zeitfenster (auch spätere)."""
    # 01.11. (Lucio): „Spielerstatistik“ enthält bei BL ebenfalls den Torschützen-Markt → zählt mit.
    ts = [x for x in out if x["torschuetze"] or x["spielerstatistik"]]
    st = []
    z = [f"⚽ <b>TORSCHÜTZEN bei BL</b> · {_wt(von)} bis {_wt(bis)}",
         f"<i>{len(ts)} Spiele mit Torschützen-Markt · {n_alle} Spiele geprüft</i>"]
    if not ts:
        z.append("Keine Spiele mit Torschützen-Markt im Zeitraum.")

    def gruppen(liste):
        g = {}
        for x in liste:
            g.setdefault(x["liga"], []).append(x)
        return sorted(g.items(), key=lambda kv: min(y["ts"] for y in kv[1]))
    tag0 = von.strftime("%d.%m.")
    for liga, xs in gruppen(ts):
        z.append("")
        z.append(f"<b>{esc(liga)}</b>")
        for x in sorted(xs, key=lambda y: y["ts"]):
            d = datetime.fromtimestamp(x["ts"], B)
            zeit = d.strftime("%H:%M") if d.strftime("%d.%m.") == tag0 else f"{WT[d.weekday()]} {d:%H:%M}"
            z.append(f"   {zeit} {esc(x['spiel'])}")
    if st:
        z.append("")
        z.append("<i>nur Spielerstatistik (kein Torschützen-Markt erkannt):</i>")
        for liga, xs in gruppen(st):
            z.append(f"<i>{esc(liga)}: " + ", ".join(f"{datetime.fromtimestamp(x['ts'], B):%H:%M} {esc(x['spiel'])}" for x in xs) + "</i>")
    return "\n".join(z)


def teile(t, n=3800):
    out, cur = [], ""
    for ln in t.split("\n"):
        if len(cur) + len(ln) + 1 > n:
            out.append(cur)
            cur = ln
        else:
            cur = (cur + "\n" + ln) if cur else ln
    if cur:
        out.append(cur)
    return out


def stundenlauf(scan_mod, jetzt=None, zwingen=None):
    """Im Stundenlauf aufrufen: läuft nur zu den Plan-Stunden (einmal je Stunde/Tag)."""
    import os
    jetzt = jetzt or datetime.now(B)
    std = zwingen if zwingen is not None else jetzt.hour
    if std not in PLAN:
        return None
    pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), STATE)
    schluessel = f"{jetzt:%Y-%m-%d}#{std}"
    try:
        gesendet = json.load(open(pfad))
    except Exception:
        gesendet = []
    if zwingen is None and schluessel in gesendet:
        return None
    von = jetzt
    tag0 = jetzt.replace(hour=0, minute=0, second=0, microsecond=0)
    bis = tag0 + timedelta(hours=PLAN[std])
    out, n_alle = scan(von, bis)
    for t in teile(text(out, n_alle, von, bis, scan_mod.esc)):
        scan_mod.send_telegram(t, trotz_pause=True)
    gesendet = (gesendet + [schluessel])[-60:]
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    json.dump(gesendet, open(pfad, "w"))
    try:
        (scan_mod.RUNS_DIR / f"torschuetzen_{jetzt:%Y-%m-%d_%H%M}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    except Exception:
        pass
    print(f"Torschützen-Scan {std} Uhr: {len(out)} mit Markt von {n_alle}", flush=True)
    return out


def run(runs_dir, tag=None):
    """Handstart (Commit „Torschützen-Scan“): Zeitfenster jetzt bis morgen 24 Uhr, nur Datei."""
    jetzt = datetime.now(B)
    bis = jetzt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2)
    out, n = scan(jetzt, bis)
    (runs_dir / f"torschuetzen_{jetzt:%Y-%m-%d_%H%M}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("Torschützen-Scan:", n, "geprüft,", sum(x["torschuetze"] for x in out), "mit Markt")
    return out
