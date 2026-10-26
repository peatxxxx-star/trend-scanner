"""Ecken: gestapelte Team-Zeilen aus karten_voll.parquet + Ecken-Ziele + abgeleitete Merkmale + Streuung."""
import pandas as pd, numpy as np, json, glob, gzip
from collections import defaultdict, deque
REPO="/home/claude/trend-scanner"
S=pd.read_parquet("karten_voll.parquet")
N=pd.read_parquet("netz.parquet")[["id","t","y_corners_h","y_corners_a","y_ht_corners_h","y_ht_corners_a","lg_corners","lg_ht_corners","h_offsides_f10","h_offsides_a10","a_offsides_f10","a_offsides_a10"]]
S=S.merge(N,on=["id","t"],how="left")
own_is_h=S.side=="h"
S["y_ft"]=np.where(own_is_h,S.y_corners_h,S.y_corners_a)
S["y_h1"]=np.where(own_is_h,S.y_ht_corners_h,S.y_ht_corners_a)
S["y_h2"]=S.y_ft-S.y_h1
S["own_offsides_f10"]=np.where(own_is_h,S.h_offsides_f10,S.a_offsides_f10); S["own_offsides_a10"]=np.where(own_is_h,S.h_offsides_a10,S.a_offsides_a10)
S["opp_offsides_f10"]=np.where(own_is_h,S.a_offsides_f10,S.h_offsides_f10); S["opp_offsides_a10"]=np.where(own_is_h,S.a_offsides_a10,S.h_offsides_a10)
S=S.drop(columns=["y_corners_h","y_corners_a","y_ht_corners_h","y_ht_corners_a","h_offsides_f10","h_offsides_a10","a_offsides_f10","a_offsides_a10","y_h1_x"],errors="ignore")
def sh(a,b): return a/(a+b).replace(0,np.nan)
for p in ("own","opp"):
    for n in (5,10,15):
        S[f"{p}_cshare{n}"]=sh(S[f"{p}_corners_f{n}"],S[f"{p}_corners_a{n}"])
        S[f"{p}_sshare{n}"]=sh(S[f"{p}_shots_total_f{n}"],S[f"{p}_shots_total_a{n}"])
        S[f"{p}_tshare{n}"]=sh(S[f"{p}_on_target_f{n}"],S[f"{p}_on_target_a{n}"])
        S[f"{p}_gd{n}"]=S[f"{p}_goals_f{n}"]-S[f"{p}_goals_a{n}"]
        S[f"{p}_blk_f{n}"]=S[f"{p}_shots_total_f{n}"]-S[f"{p}_on_target_f{n}"]
        S[f"{p}_blk_a{n}"]=S[f"{p}_shots_total_a{n}"]-S[f"{p}_on_target_a{n}"]
for n in (5,10,15):
    S[f"exp_gd{n}"]=(S[f"own_goals_f{n}"]+S[f"opp_goals_a{n}"])/2-(S[f"opp_goals_f{n}"]+S[f"own_goals_a{n}"])/2
    S[f"exp_cor{n}"]=(S[f"own_corners_f{n}"]+S[f"opp_corners_a{n}"])/2
    S[f"dom{n}"]=S[f"own_sshare{n}"]-S[f"opp_sshare{n}"]
# Streuung: Std der eigenen/zugelassenen Ecken in den letzten 10 Spielen (chronologisch, nur Vorab)
st={}
for f in glob.glob(f"{REPO}/cache/stats/s*.txt"):
    for l in open(f):
        i,_,j=l.partition("\t")
        try: st[i]=json.loads(j)
        except: pass
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        if g.get("ev") and g.get("erg"): st[g["ev"]]=g["erg"]
E=S[S.side=="h"][["id","t"]].copy()
K=pd.read_csv("karten_ev.csv",dtype={"id":str,"h":str,"a":str})[["id","h","a"]]
T=json.load(open(f"{REPO}/runs/archiv_teams.json"))
K=pd.concat([K,pd.DataFrame([{"id":k,"h":v[0],"a":v[1]} for k,v in T.items()])]).drop_duplicates("id")
E=E.merge(K,on="id").sort_values("t")
q=defaultdict(lambda: deque(maxlen=10)); out={}
for r in E.itertuples():
    for side,tid in (("h",r.h),("a",r.a)):
        x=q[tid]
        out[(r.id,side)]=(np.std([v[0] for v in x]) if len(x)>=6 else np.nan, np.std([v[1] for v in x]) if len(x)>=6 else np.nan, np.std([v[0]+v[1] for v in x]) if len(x)>=6 else np.nan)
    c=(st.get(r.id) or {}).get("corners")
    if c and c[0] is not None and c[1] is not None and min(c)>=0:
        q[r.h].append((c[0],c[1])); q[r.a].append((c[1],c[0]))
sd=pd.DataFrame([(k[0],k[1],*v) for k,v in out.items()],columns=["id","side","own_csd_f","own_csd_a","own_csd_tot"])
S=S.merge(sd,on=["id","side"],how="left")
o=sd.rename(columns={"own_csd_f":"opp_csd_f","own_csd_a":"opp_csd_a","own_csd_tot":"opp_csd_tot"}); o["side"]=o.side.map({"h":"a","a":"h"})
S=S.merge(o,on=["id","side"],how="left")
S.to_parquet("ecken_voll.parquet")
print(S.shape,"mit Ecken-Ziel",S.y_ft.notna().sum(),"HZ",S.y_h1.notna().sum())
