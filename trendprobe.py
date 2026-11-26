"""Probe: PinnFeed (Pinnacle) – Erreichbarkeit, Struktur, Abdeckung. Key nur aus Secret, nie ausgeben."""
import json, os, time, urllib.request, urllib.error
from collections import Counter
from pathlib import Path
KEY = os.environ.get("PINNFEED_KEY", "")
out = {"key_da": bool(KEY), "key_prefix_ok": KEY.startswith("ps_")}
def get(path):
    req = urllib.request.Request("https://pinnfeed.io" + path, headers={"x-api-key": KEY, "Accept": "application/json",
                                                                       "User-Agent": "trend-scanner"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "ignore")[:500]
    except Exception as e:
        return None, {}, str(e)[:300]
st, h, b = get("/health"); out["health"] = [st, b[:200]]
for path in ("/v1/odds?sport=soccer&main=true", "/v1/odds?sport=soccer&main=true&live=false",
             "/v1/events?sport=soccer"):
    time.sleep(1.5)
    st, h, b = get(path)
    r = {"status": st, "headers": {k: v for k, v in h.items() if k.lower().startswith(("x-", "retry", "ratelimit"))}}
    try:
        d = json.loads(b)
    except Exception:
        r["body"] = b[:400]; out[path] = r; continue
    ev = d.get("events") if isinstance(d, dict) else d
    r["keys"] = list(d.keys())[:20] if isinstance(d, dict) else None
    r["count"] = d.get("count") if isinstance(d, dict) else None
    if isinstance(ev, list):
        r["n_events"] = len(ev)
        r["ev_keys"] = sorted({k for e in ev[:50] for k in e})[:40]
        lg = Counter(str(e.get("league") or e.get("leagueName") or e.get("league_name")) for e in ev)
        r["n_ligen"] = len(lg); r["ligen_top"] = lg.most_common(40)
        mt = Counter(m.get("type") for e in ev for m in (e.get("markets") or []))
        r["markttypen"] = mt.most_common(20)
        r["live_anteil"] = sum(1 for e in ev if e.get("live") or e.get("isLive") or e.get("status") == "live") / max(1, len(ev))
        r["beispiel"] = ev[:2]
    else:
        r["body"] = str(d)[:400]
    out[path] = r
Path("runs/trendscan/probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:400000])
