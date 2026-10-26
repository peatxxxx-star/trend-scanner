"""Tore: Stärke-Ratings (chronologisch, gegnerbereinigt) für Tore, SaT, Schüsse, Ecken + Merkmale aus ecken_voll."""
import pandas as pd, numpy as np, json, glob, gzip, math
from collections import defaultdict, deque
REPO="/home/claude/trend-scanner"
st={}
for f in glob.glob(f"{REPO}/cache/stats/s*.txt"):
    for l in open(f):
        i,_,j=l.partition("\t")
        try: st[i]=json.loads(j)
        except: pass
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        if g.get("ev") and g.get("erg"): st[g["ev"]]=g["erg"]
S=pd.read_parquet("ecken_voll.parquet")
N=pd.read_parquet("netz.parquet")[["id","y_goals_h","y_goals_a"]]
E=S[S.side=="h"][["id","t","lg"]].copy()
K=pd.read_csv("karten_ev.csv",dtype={"id":str,"h":str,"a":str})[["id","h","a"]]
T=json.load(open(f"{REPO}/runs/archiv_teams.json"))
K=pd.concat([K,pd.DataFrame([{"id":k,"h":v[0],"a":v[1]} for k,v in T.items()])]).drop_duplicates("id")
E=E.merge(K,on="id").sort_values("t").reset_index(drop=True)
VARS={"goals":0.07,"on_target":0.06,"shots_total":0.05,"corners":0.05}
att={v:defaultdict(lambda:1.0) for v in VARS}; dfn={v:defaultdict(lambda:1.0) for v in VARS}
nseen=defaultdict(int)
lgh={v:defaultdict(lambda: deque(maxlen=300)) for v in VARS}; lga={v:defaultdict(lambda: deque(maxlen=300)) for v in VARS}
glob_h={v:deque(maxlen=3000) for v in VARS}; glob_a={v:deque(maxlen=3000) for v in VARS}
rows=[]
for r in E.itertuples():
    s=st.get(r.id) or {}; lg=str(r.lg)
    row={"id":r.id,"nh":nseen[r.h],"na":nseen[r.a]}
    base={}
    for v in VARS:
        bh=np.mean(lgh[v][lg]) if len(lgh[v][lg])>=30 else (np.mean(glob_h[v]) if glob_h[v] else 1.3)
        ba=np.mean(lga[v][lg]) if len(lga[v][lg])>=30 else (np.mean(glob_a[v]) if glob_a[v] else 1.1)
        lh=bh*att[v][r.h]*dfn[v][r.a]; la=ba*att[v][r.a]*dfn[v][r.h]
        row[f"r_{v}_h"]=lh; row[f"r_{v}_a"]=la
        row[f"att_{v}_h"]=att[v][r.h]; row[f"att_{v}_a"]=att[v][r.a]; row[f"def_{v}_h"]=dfn[v][r.h]; row[f"def_{v}_a"]=dfn[v][r.a]
        base[v]=(lh,la)
    rows.append(row)
    ok=s.get("len") in (None,90)
    for v,eta in VARS.items():
        x=s.get(v)
        if not (x and x[0] is not None and x[1] is not None and min(x)>=0): continue
        if v=="goals" and not ok: continue
        lh,la=base[v]
        k=0.5 if v=="goals" else 1.0
        fh=math.log((x[0]+k)/(lh+k)); fa=math.log((x[1]+k)/(la+k))
        att[v][r.h]*=math.exp(eta*fh); dfn[v][r.a]*=math.exp(eta*fh)
        att[v][r.a]*=math.exp(eta*fa); dfn[v][r.h]*=math.exp(eta*fa)
        lgh[v][lg].append(x[0]); lga[v][lg].append(x[1]); glob_h[v].append(x[0]); glob_a[v].append(x[1])
    if s.get("goals"): nseen[r.h]+=1; nseen[r.a]+=1
R=pd.DataFrame(rows)
# Team-Sicht
parts=[]
for own,opp in (("h","a"),("a","h")):
    c=pd.DataFrame({"id":R.id,"side":own,"n_own":R["n"+own],"n_opp":R["n"+opp]})
    for v in VARS:
        c[f"r_{v}_own"]=R[f"r_{v}_{own}"]; c[f"r_{v}_opp"]=R[f"r_{v}_{opp}"]
        c[f"att_{v}_own"]=R[f"att_{v}_{own}"]; c[f"def_{v}_own"]=R[f"def_{v}_{own}"]
        c[f"att_{v}_opp"]=R[f"att_{v}_{opp}"]; c[f"def_{v}_opp"]=R[f"def_{v}_{opp}"]
    parts.append(c)
RR=pd.concat(parts)
S=S.drop(columns=["y_ft","y_h1","y_h2"]).merge(RR,on=["id","side"],how="left").merge(N,on="id",how="left")
S["y_ft"]=np.where(S.side=="h",S.y_goals_h,S.y_goals_a)
S=S.drop(columns=["y_goals_h","y_goals_a"])
S.to_parquet("tore_voll.parquet")
print(S.shape,"mit Tor-Ziel",S.y_ft.notna().sum())
# Kurzcheck: sagt das Rating Tore besser voraus als der 10er-Schnitt?
x=S.dropna(subset=["y_ft","r_goals_own","own_goals_f10","opp_goals_a10"]); x=x[x.n_own>=10]
print("Korrelation mit Toren: Rating",round(np.corrcoef(x.r_goals_own,x.y_ft)[0,1],3),"| Schnitt (für+gegen)/2",round(np.corrcoef((x.own_goals_f10+x.opp_goals_a10)/2,x.y_ft)[0,1],3),
      "| SaT-Rating",round(np.corrcoef(x.r_on_target_own,x.y_ft)[0,1],3))
