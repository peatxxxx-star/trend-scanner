import json, re
from pathlib import Path
from s24liste import get
out = {}
for url in ["https://scores24.live/de/soccer/m-20-11-2026-annecy-clermont-h2h"]:
    try:
        h = get(url)
    except Exception as e:
        out[url] = "ERR " + str(e)[:200]; continue
    r = {"len": len(h)}
    txt = re.sub(r'<script.*?</script>', ' ', h, flags=re.S)
    txt = re.sub(r'<[^>]+>', ' ', txt); txt = re.sub(r'\s+', ' ', txt)
    r["text"] = txt[:12000]
    for kw in ['"homeScore"', '"score"', '"scores"', '"result"', 'teamAScore', '"goals"', '"ft"']:
        idx = [m.start() for m in re.finditer(re.escape(kw), h)][:2]
        r[kw] = [h[max(0, i-400): i+600] for i in idx]
    r["teamlinks"] = list(dict.fromkeys(re.findall(r'/de/soccer/(t-[a-z0-9\-]+)', h)))[:20]
    out[url] = r
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
