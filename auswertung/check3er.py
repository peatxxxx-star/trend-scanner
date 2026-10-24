import json, sys, glob, csv, time, itertools, unicodedata, re
sys.path.insert(0, "/home/claude/trend-scanner")
import scan
from datetime import datetime
from zoneinfo import ZoneInfo
heute = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d")
runs = sorted(f for f in glob.glob(f"/home/claude/trend-scanner/runs/{heute}_*.json") if "ergeb" not in f and "prewarm" not in f)
f = runs[-1]; d = json.load(open(f)); now = time.time()
print("Lauf:", f.split("/")[-1])
def norm(x): 
    x = unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()
    return set(w for w in re.findall(r"[a-z]+", x) if len(w) > 2 and w not in ("u19","u21","fc","club","the"))
# laufende Scheine -> blockierte Spiele
sch = {}
for r in csv.DictReader(open("/home/claude/trend-scanner/wetten.csv")):
    sch.setdefault(r["schein"], []).append(r)
blocked = []
for k, rs in sch.items():
    st = rs[0]["schein_status"]
    if st == "offen":
        for r in rs: blocked.append((k, r["spiel"]))
print("laufende Scheine:", sorted({k for k, _ in blocked}))
def ist_blockiert(m):
    a = norm(m["home"]); b = norm(m["away"])
    for k, sp in blocked:
        t = norm(sp)
        if (a & t) and (b & t): return k
    return None
fair = {}
# 23.10.: Signale, die in einem Lauf kurz rausfallen ("dropped"), bleiben laut Lucios Regel
# bis zum Anpfiff gemeldet und stehen weiter in der BL-Liste -> Signal aus früheren Läufen nehmen
for _f in runs[:-1]:
    try:
        for h in json.load(open(_f))["hits"]:
            m = h["match"]
            for s in h["signals"]: fair[f'{m["id"]}|{s["metric_key"]}|{s["direction"]}|{s["line"]:g}'] = (s, m)
    except Exception: pass
for h in d["hits"]:
    m = h["match"]
    for s in h["signals"]: fair[f'{m["id"]}|{s["metric_key"]}|{s["direction"]}|{s["line"]:g}'] = (s, m)
frei, gesp = [], []
CHECK = []
for t in d["betlabel"]["tipps"]:
    if not t[2]: continue
    kk = t[0].rsplit("|", 1); key = kk[0] + "|" + f"{float(kk[1]):g}"
    if key not in fair: continue
    s, m = fair[key]; mn, _ = scan.play_min(s)
    if scan.ausgeblendet(s) or not mn or t[2] < mn - 1e-9 or t[2] < 1.30 or t[2] > 2.00 or m["kickoff_ts"] <= now: continue
    if any(p[1] == "stop" for p in scan.vp_bewertung(m, s, t[2])): continue   # ⛔ steht nicht in der BL-Liste
    if getattr(scan, "BL_OHNE_JUGEND", False) and scan.youth_or_reserve(m): continue   # 24.10.: Jugend/Reserve nur im Hintergrund
    b = ist_blockiert(m)
    row = (m["kickoff_ts"], m["kickoff"], m["id"], f'{m["home"]} – {m["away"]}', m["league"], f'{s["metric"]} {s["direction"]} {s["line"]}', t[2], mn)
    (gesp if b else frei).append((b,) + row)
    if not b: CHECK.append((m, s, t[2], mn))
for g in gesp: print("  gesperrt", g[0], g[4], g[6])
for g in frei: print("  frei   ", g[2], g[4], g[5], g[6], g[7], g[8])
for g in frei: print(f"TG|{g[2]}|{g[4]}|{g[6]}|@{g[7]:.2f} (ab {g[8]:.2f})")
spiele = {}
for g in frei: spiele.setdefault(g[3], g)  # je Spiel nur ein Tipp (erster)
print("freie Spiele:", len(spiele), "-> 3er möglich" if len(spiele) >= 3 else "-> kein 3er")

# --- Checkliste (22.10., Lucio): jeder Tipp EINMAL vollständig; erneut nur bei neuen Infos (Schiri neu/anders)
import os
SEEN = "auswertung/check_seen.json"
try: seen = json.load(open(SEEN))
except Exception: seen = {}
WETTB = re.compile(r"champions|europa|conference|youth league|libertadores|sudamericana|cup|pokal|copa|coupe|coppa|taca|beker|kupa|trophy|play.?off|qualif", re.I)
for m, s, q, mn in CHECK:
    key = f'{m["id"]}|{s["metric_key"]}|{s["line"]}'
    ref = s.get("vp_ref") or {}
    fp = f'{ref.get("name")}|{ref.get("avg")}'
    if seen.get(key) == fp: continue
    pk = []
    if WETTB.search(m["league"]):
        vl = s.get("vp_liga") or []
        pk.append(f"Regel 22: Wettbewerb ({m['league']}) – Anteil Spiele in diesem Wettbewerb {vl} → Liga- vs. Wettbewerbswerte prüfen")
    if "yellow" in s["metric_key"]:
        pk.append(f"Schiri: {ref.get('name')} Ø {ref.get('avg')} (n={ref.get('n')})" if ref else "Schiri: unbekannt")
    vp = [p[2] for p in scan.vp_bewertung(m, s, q) if p[1] in ("warn", "stop")]
    if vp: pk.append("VP: " + " | ".join(vp))
    pk.append("Derby/K.o./Aufsteiger: manuell prüfen")
    print(f"  CHECK NEU {m['kickoff']} {m['home']} – {m['away']} | {s['metric']} {s['line']}:")
    for x in pk: print("     -", x)
    seen[key] = fp
json.dump(seen, open(SEEN, "w"))
