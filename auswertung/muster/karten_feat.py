import json, glob, gzip
import pandas as pd, numpy as np
from collections import defaultdict, deque
REPO="/home/claude/trend-scanner"
df=pd.read_csv("karten_ev.csv",dtype={"id":str,"h":str,"a":str,"ref":str})
# Archiv-Spiele ergänzen (Quelle der Wahrheit für 15.–25.10.)
T=json.load(open(f"{REPO}/runs/archiv_teams.json"))
add=[]
have=set(df.id)
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        e=g.get("ev"); er=g.get("erg") or {}
        if not e or e not in T or e in have: continue
        y=er.get("yellowcards"); rf=er.get("ref"); fo=er.get("fouls") or [None,None]
        add.append({"id":e,"t":g["S"],"lg":T[e][5],"h":T[e][0],"a":T[e][1],"yh":y[0] if y else None,"ya":y[1] if y else None,
                    "ref":rf[0] if rf else None,"len":er.get("len"),"fh":fo[0],"fa":fo[1]})
        have.add(e)
df=pd.concat([df,pd.DataFrame(add)],ignore_index=True)
df=df.sort_values("t").reset_index(drop=True)
team=defaultdict(lambda: deque(maxlen=10)); teamlast={}; teamuefa={}
refh=defaultdict(list); lgh=defaultdict(lambda: deque(maxlen=300)); allh=deque(maxlen=3000)
out=[]
for r in df.itertuples():
    lg=str(r.lg); ok=pd.notna(r.yh) and pd.notna(r.ya) and r.yh>=0 and r.ya>=0
    lgm=np.mean(lgh[lg]) if len(lgh[lg])>=30 else (np.mean(allh) if allh else 4.0)
    def tm(tid):
        q=team[tid]
        if len(q)<5: return (np.nan,)*3
        return (np.mean([x[0] for x in q]), np.mean([x[1] for x in q]),
                np.mean([x[2] for x in q if x[2] is not None]) if any(x[2] is not None for x in q) else np.nan)
        
    hf,ha,hfo=tm(r.h); af,aa,afo=tm(r.a)
    rl=refh.get(r.ref) if isinstance(r.ref,str) else None
    rn=len(rl) if rl else 0
    k=6
    ref_s=(sum(rl)+k*lgm)/(rn+k) if rl else np.nan
    rest_h=min((r.t-teamlast.get(r.h,r.t-14*86400))/86400,14); rest_a=min((r.t-teamlast.get(r.a,r.t-14*86400))/86400,14)
    eu_h=1 if teamuefa.get(r.h,0)>r.t-5*86400 else 0; eu_a=1 if teamuefa.get(r.a,0)>r.t-5*86400 else 0
    out.append((r.id,r.t,lg,lgm,hf,ha,hfo,af,aa,afo,ref_s,rn,rest_h,rest_a,eu_h,eu_a,(r.yh+r.ya) if ok else np.nan,r.len))
    # Update NACH der Merkmalsberechnung (kein Blick in die Zukunft)
    if ok:
        tot=r.yh+r.ya
        fh=r.fh if pd.notna(r.fh) else None; fa=r.fa if pd.notna(r.fa) else None
        team[r.h].append((r.yh,r.ya,fh)); team[r.a].append((r.ya,r.yh,fa))
        lgh[lg].append(tot); allh.append(tot)
        if isinstance(r.ref,str): refh[r.ref].append(tot)
    teamlast[r.h]=r.t; teamlast[r.a]=r.t
    if "UEFA" in lg or "Champions" in lg: teamuefa[r.h]=r.t; teamuefa[r.a]=r.t
F=pd.DataFrame(out,columns=["id","t","lg","lgm","hf","ha","hfo","af","aa","afo","ref_s","ref_n","rest_h","rest_a","eu_h","eu_a","y","len"])
F.to_csv("karten_feat.csv",index=False)
print(len(F), F.y.notna().sum(), "mit Schiri-Schnitt", F.ref_s.notna().sum())
