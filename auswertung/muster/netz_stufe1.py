import pandas as pd, numpy as np, datetime as dt
from sklearn.linear_model import LinearRegression
D=pd.read_parquet("netz.parquet")
CUT=int(dt.datetime(2026,10,1,tzinfo=dt.timezone.utc).timestamp())
V=["corners","yellowcards","goals","on_target","shots_total","fouls","offsides","ht_corners"]
# Team-Sicht stapeln: own = Team, opp = Gegner
def stack():
    parts=[]
    for own,opp,home in (("h","a",1),("a","h",0)):
        x=pd.DataFrame({"id":D.id,"t":D.t,"lg":D.lg,"home":home})
        for c in D.columns:
            if c.startswith(own+"_"): x["own_"+c[2:]]=D[c]
            elif c.startswith(opp+"_"): x["opp_"+c[2:]]=D[c]
            elif c.startswith("lg_"): x[c]=D[c]
        for v in ("corners","yellowcards","goals","ht_corners"):
            x["y_"+v]=D[f"y_{v}_{own}"]; x["yo_"+v]=D[f"y_{v}_{opp}"]
        parts.append(x)
    return pd.concat(parts,ignore_index=True)
S=stack()
feats=[c for c in S.columns if c.startswith(("own_","opp_"))]
res=[]
for tgt in ("corners","goals","yellowcards","ht_corners"):
    y=S["y_"+tgt]
    base=["own_"+tgt+"_f10","opp_"+tgt+"_a10","lg_"+tgt,"home"]
    M=S.dropna(subset=base+["y_"+tgt]).copy()
    tr=M.t<CUT; te=~tr
    lr=LinearRegression().fit(M.loc[tr,base],M.loc[tr,"y_"+tgt])
    M["res"]=M["y_"+tgt]-lr.predict(M[base])
    r2b=1-M.loc[te,"res"].var()/M.loc[te,"y_"+tgt].var()
    print(f"\n### Ziel Team-{tgt}: n={len(M)} (Test {te.sum()}), Basismodell R² Test {r2b:.3f}")
    for f in feats:
        if f in base: continue
        z=M[[f,"res","t"]].dropna()
        if len(z)<20000: continue
        a=z[z.t<CUT]; b=z[z.t>=CUT]
        if len(b)<3000: continue
        ca=np.corrcoef(a[f],a.res)[0,1]; cb=np.corrcoef(b[f],b.res)[0,1]
        res.append((tgt,f,ca,cb,len(a),len(b)))
R=pd.DataFrame(res,columns=["ziel","merkmal","korr_train","korr_test","n_tr","n_te"])
R["stabil"]=np.sign(R.korr_train)==np.sign(R.korr_test)
R["staerke"]=np.minimum(R.korr_train.abs(),R.korr_test.abs())*R.stabil
R.to_csv("netz_stufe1.csv",index=False)
for tgt in R.ziel.unique():
    print(f"\n== Top Zusatz-Merkmale für Team-{tgt} (Korrelation mit Rest nach Basismodell) ==")
    print(R[R.ziel==tgt].sort_values("staerke",ascending=False).head(12)[["merkmal","korr_train","korr_test"]].round(3).to_string(index=False))
