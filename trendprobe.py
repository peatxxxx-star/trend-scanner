import json, re
from pathlib import Path
from s24liste import get
out = {}
def clean(h):
    t = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', h, flags=re.S)
    t = re.sub(r'<[^>]+>', ' ', t); return re.sub(r'\s+', ' ', t)
for url in ["https://scores24.live/de/soccer/m-20-11-2026-annecy-clermont-h2h",
            "https://scores24.live/de/soccer/t-annecy-fc/results",
            "https://scores24.live/de/soccer/t-annecy-fc"]:
    try:
        h = get(url)
    except Exception as e:
        out[url] = "ERR " + str(e)[:200]; continue
    t = clean(h)
    r = {"len": len(h), "textlen": len(t)}
    i = t.find("Letzte")
    r["text_letzte"] = t[max(0,i-200): i+4000] if i >= 0 else None
    r["text_start"] = t[:3000]
    # JSON-Keys rund um Ergebnisse
    r["keys"] = sorted(set(re.findall(r'"([a-zA-Z]*(?:[Ss]core|[Gg]oal|[Rr]esult)[a-zA-Z]*)"\s*:', h)))[:60]
    k = re.search(r'"(homeScore|scoreHome|teamAScore|score)"\s*:', h)
    r["json_ctx"] = h[max(0, k.start()-800): k.start()+800] if k else None
    out[url] = r
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
