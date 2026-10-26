"""Serien-Logik, Ecken GESAMT (über/unter): alle Signale mit BL-Quote seit 14.10., letzter Lauf vor Anstoß.
Daneben: BL-Wahrscheinlichkeit (No-Vig aus dem Archiv) und das Ecken-Modell."""
import json, glob, gzip, sys, time, re
import pandas as pd, numpy as np
sys.path.insert(0, "/home/claude/trend-scanner")
import scan
SP="/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad/muster"
cache = scan.load_cache()
erg = {}
for f in sorted(glob.glob("runs/ergebnisse_*.json")):
    for k, v in json.load(open(f)).items():
        if str(v.get("time_status")) == "3": erg[k] = v["slim"]
for f in glob.glob("runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        if g.get("erg") and g.get("ev"): erg.setdefault(str(g["ev"]), g["erg"])
tipps = {}
for f in sorted(glob.glob("runs/2026-10-*_*.json")):
    if any(x in f for x in ("ergeb","dump","prewarm","h2h","archiv")): continue
    name=f.split("/")[-1][:15]
    if name < "2026-10-14": continue
    try: d = json.load(open(f))
    except Exception: continue
    try: lauf_ts = time.mktime(time.strptime(name, "%Y-%m-%d_%H%M")) - time.timezone
    except Exception: continue
    q = {t[0]: t[2] for t in (d.get("betlabel") or {}).get("tipps") or [] if t[2]}
    for h in d.get("hits") or []:
        m = h["match"]
        if m.get("kickoff_ts", 0) <= lauf_ts: continue
        for s in h["signals"]:
            if s.get("metric_key") != "goals": continue
            k = f'{m["id"]}|goals|{s["direction"]}|{s["line"]}'
            if k in q:
                mn,_ = scan.play_min(s)
                tipps[k] = dict(ev=str(m["id"]), spiel=f'{m["home"]} – {m["away"]}', liga=m.get("league"), dir=s["direction"], line=float(s["line"]),
                                q=q[k], ab=mn, fair=s.get("fair_fin") or s.get("fair"), ko=m.get("kickoff_ts"), jugend=scan.youth_or_reserve(m))
rows=[]
for k,t in tipps.items():
    st = erg.get(t["ev"]) or cache.get(t["ev"])
    c = (st or {}).get("goals")
    if not c or c[0] is None or (st.get("len") not in (None,90)): continue
    v=c[0]+c[1]; hit = v>t["line"] if t["dir"]=="über" else v<t["line"]
    rows.append(dict(t, wert=v, hit=int(hit), roi=(t["q"] if hit else 0)-1, tag=time.strftime("%Y-%m-%d", time.gmtime(t["ko"]))))
R=pd.DataFrame(rows)
R["liste"]=(R.ab.notna())&(R.q>=R.ab)&(R.q>=1.3)&(R.q<=2.0)
# BL-No-Vig und Modell aus dem Archiv (gleiche Linie)
B=pd.read_csv(f"{SP}/ds_a.csv",dtype={"ev":str}); B=B[B.base=="goals"]; B["p_m"]=np.nan
B=B[(B.half=="ft")&(B.side=="tot")][["ev","dir","line","p_nv","p_m"]]
B["dir"]=B.dir.map({"o":"über","u":"unter"})
R=R.merge(B,on=["ev","dir","line"],how="left")
def zeile(x,lab):
    if len(x)==0: return
    nv=x.p_nv.dropna()
    print(f"{lab:38s} {len(x):4d} Tipps | Treffer {x.hit.mean():.0%} | Ø Quote {x.q.mean():.2f} (nötig {np.mean(1/x.q):.0%}) | ROI {x.roi.mean():+.1%}"
          + (f" | BL sagt {nv.mean():.0%}, Modell {x.p_m.dropna().mean():.0%} (n={len(nv)})" if len(nv) else ""))
for d_,L in (("über",1.5),("über",2.5),("unter",3.5),("über",3.5)):
    x=R[(R.dir==d_)&(R.line==L)]
    print(f"\n=== Tore {d_} {L} ===")
    zeile(x,"alle Signale mit BL-Quote")
    zeile(x[x.liste],"davon BL-Liste (Quote ≥ ab, 1,30–2,00)")
    zeile(x[x.liste & ~x.jugend],"   ohne Jugend/Reserve")
    zeile(x[~x.liste],"davon NICHT in der Liste")
    for a,b in (("2026-10-14","2026-10-19"),("2026-10-20","2026-10-25")):
        zeile(x[x.liste&(x.tag>=a)&(x.tag<=b)],f"   BL-Liste {a[5:]}–{b[5:]}")
    zeile(x[x.liste&(x.q<1.5)],"   BL-Liste Quote < 1,50")
    zeile(x[x.liste&(x.q>=1.5)],"   BL-Liste Quote ≥ 1,50")
R.to_csv(f"{SP}/serien_tore.csv",index=False)
