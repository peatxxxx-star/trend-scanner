"""14.10. (Lucio: "Ich brauche zu jedem meiner Märkte eine Quote, direkt im
Telegram"): Erkundung der BetLabel-Quoten. BetLabel läuft auf der
1xBet-Plattform; deren Feed antwortet unter /service-api/LineFeed/.
Läuft nur per Push auf scan_now mit "BetLabel-Sonde" in der Commit-Nachricht
und schreibt runs/betlabel_sonde*.json. Ändert am Scan nichts."""
import json, time, urllib.request, urllib.error, gzip, zlib
from pathlib import Path

UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36")
BASE = "https://betlabel.com/service-api/LineFeed/"


def hole(pfad, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = BASE + pfad + ("?" + q if q else "")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding", "")
        if enc == "gzip":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            raw = zlib.decompress(raw)
        return json.loads(raw.decode("utf-8", "replace"))


def run(_scan=None):
    erg = {"zeit": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "varianten": {}}
    var = {
        "count1000": dict(sports=1, count=1000, lng="de", mode=4, country=1, getEmpty="true"),
        "count1000_tf": dict(sports=1, count=1000, lng="de", tf=3000000, mode=4, country=1, getEmpty="true"),
        "count1000_partner": dict(sports=1, count=1000, lng="de", mode=4, country=1, partner=1, getEmpty="true", virtualSports="true"),
    }
    for n, pr in var.items():
        try:
            v = hole("Get1x2_VZip", **pr).get("Value") or []
            erg["varianten"][n] = len(v)
        except Exception as e:
            erg["varianten"][n] = f"{type(e).__name__}: {e}"
    try:
        ch = hole("GetChampsZip", sport=1, lng="de", country=1, tf=3000000, tz=2).get("Value") or []
        erg["champs_anzahl"] = len(ch)
        erg["champs"] = [{k: c.get(k) for k in ("LI", "L", "GC", "CI", "SC")} for c in ch]
    except Exception as e:
        erg["champs_fehler"] = f"{type(e).__name__}: {e}"
        ch = []
    # Slowakei-Ligen/Pokal: Spiele + Hauptquoten (Abgleich mit Lucios Schein)
    erg["slowakei"] = []
    for c in ch:
        if "Slowak" in (c.get("L") or "") or "Youth" in (c.get("L") or "") or "Jugend" in (c.get("L") or ""):
            try:
                v = hole("Get1x2_VZip", sports=1, champs=c["LI"], count=50, lng="de", mode=4, country=1, getEmpty="true").get("Value") or []
                for g in v:
                    erg["slowakei"].append({"L": g.get("L"), "I": g.get("I"), "O1": g.get("O1"), "O2": g.get("O2"), "S": g.get("S"),
                                            "E": [(e.get("G"), e.get("T"), e.get("P"), e.get("C")) for e in g.get("E") or []]})
            except Exception as e:
                erg["slowakei"].append({"L": c.get("L"), "fehler": str(e)})
    Path("runs").mkdir(exist_ok=True)
    Path("runs/betlabel_sonde3.json").write_text(json.dumps(erg, ensure_ascii=False))
    print("BetLabel-Sonde 3 fertig")
