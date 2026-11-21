"""Erkundung: freie Quellen für Abseits / Schüsse aufs Tor je Spiel (vom Actions-Server aus)."""
import json, urllib.request
from pathlib import Path
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept": "application/json,text/html", "Accept-Language": "de,en;q=0.8"}
tests = {
    "sofascore_team_last": "https://api.sofascore.com/api/v1/team/17/events/last/0",
    "sofascore_www": "https://www.sofascore.com/api/v1/team/17/events/last/0",
    "fotmob_team": "https://www.fotmob.com/api/teams?id=10261",
    "4score": "https://4score.ru/en/teams/rubin-kazan/",
    "footystats": "https://footystats.org/clubs/fc-rubin-kazan-347",
    "fbref": "https://fbref.com/en/comps/9/Premier-League-Stats",
}
out = {}
for name, url in tests.items():
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20)
        b = r.read().decode("utf-8", "replace")
        out[name] = {"status": r.status, "len": len(b), "start": b[:400],
                     "offside": b.lower().count("offside"), "ontarget": b.lower().count("on target") + b.count("onTarget")}
    except Exception as e:
        out[name] = {"err": str(e)[:200]}
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("ok")
