import pandas as pd, numpy as np, datetime as dt, json, glob, gzip, warnings
warnings.filterwarnings("ignore")
from sklearn.linear_model import PoissonRegressor
from scipy.stats import nbinom, poisson
REPO="/home/claude/trend-scanner"
D=pd.read_parquet("netz.parquet")
R=pd.read_csv("netz_stufe1.csv")
CUT=int(dt.datetime(2026,10,15,tzinfo=dt.timezone.utc).timestamp())
def stack():
    parts=[]
    for own,opp,home in (("h","a",1),("a","h",0)):
        cols={"id":D.id,"t":D.t,"home":pd.Series(home,index=D.index),"side":pd.Series(own,index=D.index)}
        for c in D.columns:
            if c.startswith(own+"_"): cols["own_"+c[2:]]=D[c]
            elif c.startswith(opp+"_"): cols["opp_"+c[2:]]=D[c]
            elif c.startswith("lg_"): cols[c]=D[c]
        for v in ("corners","yellowcards","goals"):
            cols["y_"+v]=D[f"y_{v}_{own}"]
        parts.append(pd.DataFrame(cols))
    return pd.concat(parts,ignore_index=True)
S=stack()
K=pd.read_csv("karten_feat.csv",dtype={"id":str})[["id","ref_s","lgm"]].drop_duplicates("id")
S=S.merge(K,on="id",how="left")
S["ref_rel"]=np.log(S.ref_s.clip(0.5)/S.lgm.clip(0.5)).fillna(0); S["ref_known"]=S.ref_s.notna().astype(int)
swap={}
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        if g.get("ev"): swap[g["ev"]]=bool(g.get("swap"))
A=pd.read_csv("ds_a.csv",dtype={"ev":str})
A=A[A.p_nv.notna()&(A.half=="ft")&A.base.isin(["corners","goals","yellowcards"])]
A=A[~((A.base=="yellowcards")&(A.side=="_gast"))]
A["roi"]=A.hit*A.q-1
out={}
def fit(tgt,feats):
    M=S.dropna(subset=feats+["y_"+tgt]).copy()
    X=M[feats].copy()
    tr=M.t<CUT
    m=PoissonRegressor(alpha=1e-4,max_iter=2000).fit(X[tr],M.loc[tr,"y_"+tgt])
    mu=m.predict(X[tr]); disp=max(1.01,np.mean((M.loc[tr,"y_"+tgt]-mu)**2)/np.mean(mu))
    S.loc[M.index,f"mu_{tgt}"]=m.predict(X)
    return disp
def p_over(mu,L,disp):
    k=np.floor(L); r=mu/(disp-1); p=r/(r+mu); return 1-nbinom.cdf(k,r,p)
ergebnis=[]
for tgt in ("yellowcards",):
    base=["own_"+tgt+"_f10","opp_"+tgt+"_a10","lg_"+tgt,"home"]
    top=R[(R.ziel==tgt)&R.stabil].sort_values("staerke",ascending=False).merkmal.tolist()
    extra=[]
    for f in top:
        if f not in base and len(extra)<8 and not any(f.rsplit("_",1)[0]==e.rsplit("_",1)[0] for e in extra): extra.append(f)
    for variante,feats in (("Basis",base),("Spinnennetz",base+extra),("Netz+Schiri",base+extra+["ref_rel","ref_known"])):
        disp=fit(tgt,feats)
        P=S[["id","side",f"mu_{tgt}"]].dropna().pivot_table(index="id",columns="side",values=f"mu_{tgt}")
        a=A[(A.base==tgt)&A.ev.isin(P.index)].copy()
        if a.empty: continue
        mh=P.reindex(a.ev)["h"].values; ma=P.reindex(a.ev)["a"].values
        sw=a.ev.map(swap).fillna(False).values
        heim_bl=np.where(sw,ma,mh); gast_bl=np.where(sw,mh,ma)
        mu=np.where(a.side=="tot",mh+ma,np.where(a.side=="_heim",heim_bl,gast_bl))
        dsp=disp*1.15 if True else disp
        po=np.array([p_over(u,L,dsp if s=="tot" else disp) for u,L,s in zip(mu,a.line,a.side)])
        a["p_m"]=np.where(a.dir=="o",po,1-po); a["edge"]=a.p_m*a.q-1
        from sklearn.metrics import brier_score_loss
        bm=brier_score_loss(a.hit,a.p_m); bb=brier_score_loss(a.hit,a.p_nv)
        for thr in (0.05,0.10):
            b=a[(a.edge>thr)&(a.q>=1.3)&(a.q<=2.0)].sort_values("edge",ascending=False).drop_duplicates(["ev","side"])
            if len(b)==0: continue
            se=(b.roi).std()/np.sqrt(len(b))
            tage=b.groupby("tag").roi.mean()
            if thr==0.05: b.assign(modell=variante).to_csv(f"wetten_{tgt}_{variante}.csv",index=False)
            ergebnis.append((tgt,variante,thr,len(b),round(b.hit.mean(),3),round(b.q.mean(),2),round(b.roi.mean(),3),round(se,3),f"{int((tage>0).sum())}/{len(tage)}",round(bm,4),round(bb,4),"|".join(extra) if variante!="Basis" else ""))
E=pd.DataFrame(ergebnis,columns=["ziel","modell","edge>","wetten","treffer","q","roi","±se","tage+","brier_mod","brier_bl","merkmale"])
print(E.drop(columns="merkmale").to_string(index=False))
print(E[E.modell=="Spinnennetz"].drop_duplicates("ziel")[["ziel","merkmale"]].to_string(index=False))
E.to_csv("netz_karten.csv",index=False)
