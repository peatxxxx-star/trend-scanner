"""Karten komplett: Team-Zeilen (gestapelt) mit allen Merkmalsgruppen + Ziele Spiel/1.HZ/2.HZ."""
import json, glob, gzip, re
import pandas as pd, numpy as np
from collections import defaultdict
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
D=pd.read_parquet("netz.parquet")
K=pd.read_csv("karten_feat.csv",dtype={"id":str}).drop_duplicates("id").set_index("id")
E=pd.read_csv("karten_ev.csv",dtype={"id":str,"h":str,"a":str})[["id","h","a"]]
T=json.load(open(f"{REPO}/runs/archiv_teams.json"))
E=pd.concat([E,pd.DataFrame([{"id":k,"h":v[0],"a":v[1]} for k,v in T.items()])]).drop_duplicates("id").set_index("id")
D=D[D.id.isin(E.index)].sort_values("t").reset_index(drop=True)
D["hid"]=D.id.map(E.h); D["aid"]=D.id.map(E.a)
# H2H chronologisch
h2h=defaultdict(list)
H2=[]
for r in D.itertuples():
    s=st.get(r.id); key=tuple(sorted((r.hid,r.aid)))
    prev=h2h[key][-6:]
    if prev:
        tot=[p[1]+p[2] for p in prev]
        own_h=[p[1] if p[0]==r.hid else p[2] for p in prev]; own_a=[p[2] if p[0]==r.hid else p[1] for p in prev]
        H2.append((len(prev),np.mean(tot),np.mean(own_h),np.mean(own_a)))
    else: H2.append((0,np.nan,np.nan,np.nan))
    y=(s or {}).get("yellowcards")
    if y and y[0] is not None and min(y)>=0: h2h[key].append((r.hid,y[0],y[1]))
D[["h2h_n","h2h_tot","h2h_h","h2h_a"]]=pd.DataFrame(H2,index=D.index)
lg=D.lg.str.lower()
D["cup"]=lg.str.contains(r"cup|pokal|copa|coupe|coppa|ta[cç]a|beker|trophy|shield|knock|play-?off|super ?cup|supercopa|supercoppa").astype(int)
D["uefa"]=lg.str.contains(r"uefa|champions|europa|conference|libertadores|sudamericana|concacaf|afc|caf ").astype(int)
D["youth"]=lg.str.contains(r"u1\d|u2\d|youth|reserve|primavera|junior|jugend|juvenil").astype(int)
D["monat"]=pd.to_datetime(D.t,unit="s").dt.month
for c in ("ref_s","ref_n","lgm","rest_h","rest_a","eu_h","eu_a"): D[c]=D.id.map(K[c])
D["ref_rel"]=np.log(D.ref_s.clip(0.5)/D.lgm.clip(0.5))
def ht(s):
    x=(s or {}).get("ht_yellowcards")
    return x if x and x[0] is not None and x[1] is not None and min(x)>=0 else [np.nan,np.nan]
def ft(s):
    x=(s or {}).get("yellowcards"); ok=s and s.get("len") in (None,90)
    return x if ok and x and x[0] is not None and min(x)>=0 else [np.nan,np.nan]
FT=np.array([ft(st.get(i)) for i in D.id],dtype=float); HT=np.array([ht(st.get(i)) for i in D.id],dtype=float)
parts=[]
base_cols=["id","t","lg","cup","uefa","youth","monat","ref_rel","ref_n","h2h_n","h2h_tot","lg_yellowcards","lg_fouls"]
for own,opp,home,j in (("h","a",1,0),("a","h",0,1)):
    c={k:D[k] for k in base_cols}
    c["home"]=pd.Series(home,index=D.index); c["side"]=pd.Series(own,index=D.index)
    for col in D.columns:
        if col.startswith(own+"_") and any(v in col for v in ("yellowcards","fouls","goals","on_target","shots_total","corners")): c["own_"+col[2:]]=D[col]
        elif col.startswith(opp+"_") and any(v in col for v in ("yellowcards","fouls","goals","on_target","shots_total","corners")): c["opp_"+col[2:]]=D[col]
    c["h2h_own"]=D["h2h_"+own]; c["h2h_opp"]=D["h2h_"+opp]
    c["rest_own"]=D["rest_"+own]; c["rest_opp"]=D["rest_"+opp]; c["eu_own"]=D["eu_"+own]; c["eu_opp"]=D["eu_"+opp]
    c["y_ft"]=pd.Series(FT[:,j],index=D.index); c["y_h1"]=pd.Series(HT[:,j],index=D.index)
    parts.append(pd.DataFrame(c))
S=pd.concat(parts,ignore_index=True)
S["y_h2"]=S.y_ft-S.y_h1
S.to_parquet("karten_voll.parquet")
print(S.shape, "mit FT",S.y_ft.notna().sum(),"mit HZ",S.y_h1.notna().sum(),"H2H vorhanden",(S.h2h_n>0).mean().round(3))
