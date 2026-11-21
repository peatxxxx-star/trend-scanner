"""Erkundung: REST-Pfad für matchesTeamMatches finden."""
import json, re
from pathlib import Path
from s24liste import get
slug = "21-11-2026-radnicki-nis-zemun"
q = "teamType=home&first=30&lang=de&sort=desc&status=finished&withStatistics=true"
B = "https://scores24.live/rapi"
cands = [f"{B}/localized/matches/soccer/{slug}/team-matches?{q}",
         f"{B}/matches/soccer/{slug}/team-matches?{q}",
         f"{B}/localized/matches/soccer/{slug}/team_matches?{q}",
         f"{B}/matches/soccer/{slug}/team_matches?{q}",
         f"{B}/localized/matches/soccer/{slug}/teamMatches?{q}",
         f"{B}/matches/soccer/{slug}/teamMatches?{q}",
         f"{B}/localized/matches/soccer/{slug}/team-matches?{q}&audience=de",
         f"{B}/localized/matches/soccer/{slug}/matches?{q}"]
out = {}
for u in cands:
    try:
        t = get(u)
        out[u] = {"ok": True, "len": len(t), "start": t[:1500]}
    except Exception as e:
        out[u] = {"ok": False, "err": str(e)[:120]}
# JS-Bundles nach "team-matches"/"teamMatches" durchsuchen
h = get(f"https://scores24.live/de/soccer/m-{slug}-h2h")
js = list(dict.fromkeys(re.findall(r'(https?://[^"\']+?\.js|/_next/[^"\']+?\.js|/static/[^"\']+?\.js)', h)))[:80]
out["js"] = js
hits = []
for j in js:
    url = j if j.startswith("http") else "https://scores24.live" + j
    try:
        t = get(url)
    except Exception:
        continue
    for m in re.finditer(r'.{0,200}(team-matches|teamMatches|TeamMatches).{0,300}', t):
        hits.append(m.group(0)[:500])
        if len(hits) > 12: break
    if len(hits) > 12: break
out["js_hits"] = hits
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("ok")
