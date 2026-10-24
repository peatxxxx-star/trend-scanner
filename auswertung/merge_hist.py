import json, subprocess, sys
cmts = subprocess.run(["git","log","--since=2026-10-14","--format=%h","--","cache/history.json"],capture_output=True,text=True,cwd="/home/claude/trend-scanner").stdout.split()
M = {}
for i, c in enumerate(cmts):
    try:
        raw = subprocess.run(["git","show",f"{c}:cache/history.json"],capture_output=True,cwd="/home/claude/trend-scanner").stdout
        H = json.loads(raw)
    except Exception as e:
        print("skip", c, e); continue
    for tid, v in H.items():
        d = M.setdefault(tid, {})
        for e in v.get("events") or []:
            d[e["id"]] = e
    if i % 20 == 0: print(i, len(cmts), len(M), flush=True)
out = {tid: {"ts": 0, "events": sorted(d.values(), key=lambda e: -(e.get("t") or 0))} for tid, d in M.items()}
json.dump(out, open("auswertung/hist_merged.json","w"))
print("Teams", len(out))
