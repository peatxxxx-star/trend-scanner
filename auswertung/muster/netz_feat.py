"""Spinnennetz-Merkmale: für jedes Spiel, je Team, Mittel 'für'/'gegen' je Variable über 3/5/10/15 Spiele (gesamt) und 5/10 (Rolle).
Nur Spiele VOR dem Anstoß. Ziele: Ecken, Gelbe, Tore (gesamt + je Team), HZ-Ecken."""
import json, glob, gzip
import pandas as pd, numpy as np
from collections import defaultdict, deque
REPO="/home/claude/trend-scanner"
st={}
for f in glob.glob(f"{REPO}/cache/stats/s*.txt"):
    for l in open(f):
        i,_,j=l.partition("\t")
        try: st[i]=json.loads(j)
        except: pass
E=pd.read_csv("karten_ev.csv",dtype={"id":str,"h":str,"a":str})[["id","t","lg","h","a"]]
T=json.load(open(f"{REPO}/runs/archiv_teams.json"))
have=set(E.id); add=[]
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        e=g.get("ev")
        if e and e in T and e not in have:
            add.append({"id":e,"t":g["S"],"lg":T[e][5],"h":T[e][0],"a":T[e][1]}); have.add(e)
            if g.get("erg"): st[e]=g["erg"]
E=pd.concat([E,pd.DataFrame(add)],ignore_index=True).sort_values("t").reset_index(drop=True)
V=["corners","yellowcards","goals","on_target","shots_total","fouls","offsides","ht_corners"]
W=[3,5,10,15]
hist=defaultdict(lambda: deque(maxlen=15))      # team -> (is_home, {var:(for,against)})
lgq=defaultdict(lambda: {v: deque(maxlen=400) for v in V})
rows=[]
def mean_fa(q, var, n, venue=None):
    f=[];a=[]
    for ih,d in reversed(q):
        if venue is not None and ih!=venue: continue
        x=d.get(var)
        if x is None: continue
        f.append(x[0]); a.append(x[1])
        if len(f)>=n: break
    if len(f)<max(3,int(n*0.6)): return np.nan,np.nan
    return np.mean(f),np.mean(a)
for r in E.itertuples():
    s=st.get(r.id); lg=str(r.lg)
    row={"id":r.id,"t":r.t,"lg":lg}
    for side,tid,ven in (("h",r.h,True),("a",r.a,False)):
        q=hist[tid]
        for v in V:
            for n in W:
                fm,am=mean_fa(q,v,n)
                row[f"{side}_{v}_f{n}"]=fm; row[f"{side}_{v}_a{n}"]=am
            for n in (5,10):
                fm,am=mean_fa(q,v,n,ven)
                row[f"{side}_{v}_fv{n}"]=fm; row[f"{side}_{v}_av{n}"]=am
    for v in V:
        L=lgq[lg][v]; row[f"lg_{v}"]=np.mean(L) if len(L)>=30 else np.nan
    # Ziele
    ok=s and (s.get("len") in (None,90))
    for v in ("corners","yellowcards","goals","ht_corners"):
        x=s.get(v) if s else None
        good=ok and x and x[0] is not None and x[1] is not None and min(x)>=0
        row[f"y_{v}_h"]=x[0] if good else np.nan; row[f"y_{v}_a"]=x[1] if good else np.nan
    rows.append(row)
    if s:
        dh={};da={}
        for v in V:
            x=s.get(v)
            if x and x[0] is not None and x[1] is not None and min(x)>=0:
                dh[v]=(x[0],x[1]); da[v]=(x[1],x[0]); lgq[lg][v].append(x[0]+x[1])
        if dh:
            hist[r.h].append((True,dh)); hist[r.a].append((False,da))
D=pd.DataFrame(rows)
D.to_parquet("netz.parquet")
print(D.shape, "mit Ecken-Ziel", D.y_corners_h.notna().sum())
