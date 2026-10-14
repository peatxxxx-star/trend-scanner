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
    erg = {"zeit": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
    try:
        liste = hole("Get1x2_VZip", sports=1, count=3000, lng="de", mode=4, country=1, getEmpty="true")
        spiele = liste.get("Value") or []
        erg["anzahl"] = len(spiele)
        erg["felder_beispiel"] = spiele[0] if spiele else None
        erg["spiele"] = [{k: g.get(k) for k in ("I", "L", "LI", "O1", "O2", "S", "SGC", "EC", "CN")}
                         for g in spiele]
    except Exception as e:
        erg["liste_fehler"] = f"{type(e).__name__}: {e}"
        spiele = []
    # Drei Spiele mit vielen Märkten (größte EC/SGC) genauer ansehen
    def gewicht(g):
        return (g.get("SGC") or 0) * 1000 + (g.get("EC") or 0)
    auswahl = sorted(spiele, key=gewicht, reverse=True)[:2]
    # plus ein Spiel aus einer kleinen Liga (Mitte der Liste)
    klein = [g for g in spiele if (g.get("SGC") or 0) > 0]
    if klein:
        auswahl.append(klein[len(klein) // 2])
    erg["details"] = []
    for g in auswahl:
        d = {"I": g.get("I"), "spiel": f"{g.get('O1')} - {g.get('O2')}", "L": g.get("L")}
        try:
            voll = hole("GetGameZip", id=g["I"], lng="de", isSubGames="true", GroupEvents="true",
                        countevents=500, grMode=4, partner=1, topGroups="", marketType=1)
            v = voll.get("Value") or {}
            d["haupt"] = v
            d["sub"] = []
            for sg in (v.get("SG") or [])[:25]:
                try:
                    s = hole("GetGameZip", id=sg.get("CI") or sg.get("I"), lng="de", isSubGames="true",
                             GroupEvents="true", countevents=500, grMode=4, partner=1, topGroups="", marketType=1)
                    d["sub"].append({"kopf": sg, "wert": s.get("Value")})
                except Exception as e:
                    d["sub"].append({"kopf": sg, "fehler": f"{type(e).__name__}: {e}"})
                time.sleep(0.3)
        except Exception as e:
            d["fehler"] = f"{type(e).__name__}: {e}"
        erg["details"].append(d)
    Path("runs").mkdir(exist_ok=True)
    Path("runs/betlabel_sonde2.json").write_text(json.dumps(erg, ensure_ascii=False))
    print("BetLabel-Sonde 2 fertig:", erg.get("anzahl"), "Spiele")
