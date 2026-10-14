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
    erg = {"zeit": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "champs_var": {}}
    var = {
        "a": dict(sport=1, lng="de", country=1),
        "b": dict(sport=1, lng="de"),
        "c": dict(sport=1, lng="de", country=1, virtualSports="true"),
        "d": dict(sport=1, lng="en", country=1, tf=2200000, tz=3),
        "e": dict(sport=1, lng="de", country=1, getEmpty="true"),
    }
    ch = []
    for n, pr in var.items():
        try:
            v = hole("GetChampsZip", **pr).get("Value") or []
            erg["champs_var"][n] = len(v)
            if len(v) > len(ch):
                ch = v
        except Exception as e:
            erg["champs_var"][n] = f"{type(e).__name__}: {e}"
    for n, pr in {"sportsshort": dict(sports=1, lng="de", country=1),
                  "sportsshort2": dict(lng="de", country=1, gr=1)}.items():
        try:
            erg[n] = str(hole("GetSportsShortZip", **pr))[:3000]
        except Exception as e:
            erg[n] = f"{type(e).__name__}: {e}"
    erg["champs"] = [{k: c.get(k) for k in ("LI", "L", "GC", "CI", "SC", "SI")} for c in ch]
    erg["champs_roh0"] = ch[:2]
    erg["slowakei"] = []
    for c in ch:
        L = c.get("L") or ""
        if any(w in L for w in ("Slowak", "Youth", "Jugend", "UEFA")):
            try:
                v = hole("Get1x2_VZip", sports=1, champs=c["LI"], count=50, lng="de", mode=4, country=1, getEmpty="true").get("Value") or []
                for g in v:
                    erg["slowakei"].append({"L": g.get("L"), "I": g.get("I"), "O1": g.get("O1"), "O2": g.get("O2"), "S": g.get("S"),
                                            "E": [(e.get("G"), e.get("T"), e.get("P"), e.get("C")) for e in g.get("E") or []]})
            except Exception as e:
                erg["slowakei"].append({"L": L, "fehler": str(e)})
    Path("runs").mkdir(exist_ok=True)
    Path("runs/betlabel_sonde4.json").write_text(json.dumps(erg, ensure_ascii=False))
    print("BetLabel-Sonde 4 fertig")
