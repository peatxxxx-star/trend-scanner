import pandas as pd, numpy as np, datetime as dt, sys, warnings
warnings.filterwarnings("ignore")
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from scipy.stats import nbinom
S=pd.read_parquet("ecken_voll.parquet")
CUT=int(dt.datetime(2026,10,15,tzinfo=dt.timezone.utc).timestamp())
VARS=("yellowcards","fouls","goals","on_target","shots_total","corners")
netz=[c for c in S.columns if c.startswith(("own_","opp_")) and any(v in c for v in VARS) and not any(x in c for x in ("share","_gd","blk","csd","h2h"))]
neu=[c for c in S.columns if any(x in c for x in ("share","_gd","blk","exp_gd","exp_cor","dom","csd","offsides"))]
wett=["cup","uefa","youth","monat","rest_own","rest_opp","eu_own","eu_opp"]
G={"basis":["own_corners_f10","opp_corners_a10","lg_corners","home"]}
G["netz"]=G["basis"]+[c for c in netz if c not in G["basis"]]+["lg_corners","lg_ht_corners"]
G["netz+neu"]=G["netz"]+neu
G["netz+neu+wettb"]=G["netz+neu"]+wett
G={k:list(dict.fromkeys(v)) for k,v in G.items()}
B=pd.read_csv("ecken_bl.csv",dtype={"ev":str}); B=B[B.ev.isin(set(S.id))]
def nb(mu,disp):
    disp=np.maximum(disp,1.01); r=mu/(disp-1); p=r/(r+mu); return r,p
art=sys.argv[2] if len(sys.argv)>2 else "gbr"
res=[]
for gname in sys.argv[1].split(","):
    feats=G[gname]; MU={}; D={}
    for tgt in ("y_ft","y_h1"):
        M=S[S[tgt].notna()]; tr=M[M.t<CUT]
        if art=="gbr":
            m=HistGradientBoostingRegressor(loss="poisson",max_iter=400,learning_rate=0.05,max_leaf_nodes=31,min_samples_leaf=300,random_state=1).fit(tr[feats],tr[tgt])
            S["mu_"+tgt]=m.predict(S[feats])
        else:
            med=S[feats].median(); X=S[feats].fillna(med)
            m=PoissonRegressor(alpha=1e-4,max_iter=3000).fit(X.loc[tr.index],tr[tgt]); S["mu_"+tgt]=m.predict(X)
        T=S[(S.t<CUT)&S[tgt].notna()]
        D[tgt+"_team"]=float(np.mean((T[tgt]-T["mu_"+tgt])**2)/np.mean(T["mu_"+tgt]))
        P=T.pivot_table(index="id",columns="side",values=["mu_"+tgt,tgt]).dropna()
        D[tgt+"_tot"]=float(np.mean((P[tgt].sum(axis=1)-P["mu_"+tgt].sum(axis=1))**2)/np.mean(P["mu_"+tgt].sum(axis=1)))
        MU[tgt]=S.pivot_table(index="id",columns="side",values="mu_"+tgt)
    print(gname,art,"Dispersion",{k:round(v,2) for k,v in D.items()},flush=True)
    b=B.copy()
    ft=MU["y_ft"].reindex(b.ev); h1=MU["y_h1"].reindex(b.ev)
    mh=np.where(b.half=="ft",ft["h"].values,np.where(b.half=="_h1",h1["h"].values,ft["h"].values-h1["h"].values))
    ma=np.where(b.half=="ft",ft["a"].values,np.where(b.half=="_h1",h1["a"].values,ft["a"].values-h1["a"].values))
    sw=b.swap.values==1
    bh=np.where(sw,ma,mh); bg=np.where(sw,mh,ma)
    mu=np.where(b.side=="tot",mh+ma,np.where(b.side=="_heim",bh,bg))
    key=np.where(b.half=="_h1","y_h1","y_ft")
    disp=np.array([D[k+("_tot" if s=="tot" else "_team")] for k,s in zip(key,b.side)])
    r,p=nb(np.clip(mu,0.05,None),disp)
    L=b.line.values; k=np.floor(L).astype(int)
    cdf_k=nbinom.cdf(k,r,p); cdf_km1=nbinom.cdf(k-1,r,p)
    ganz=b.ganz.values==1
    p_push=np.where(ganz,cdf_k-cdf_km1,0.0)
    p_over_win=np.where(ganz,1-cdf_k,1-cdf_k)          # X > L
    p_under_win=np.where(ganz,cdf_km1,cdf_k)           # X < L
    pw=np.where(b.dir=="o",p_over_win,p_under_win)
    b["p_win"]=pw; b["p_push"]=p_push; b["ev_m"]=pw*b.q+p_push-1
    b["p_m"]=pw/(1-p_push+1e-12)
    b.to_csv(f"ek_pred_{gname}_{art}.csv",index=False)
    for (hf,sd),x in b.groupby(["half","side"]):
        y=x[(x.res!="push")]
        from sklearn.metrics import brier_score_loss
        bm=brier_score_loss((y.res=="win").astype(int),y.p_m) if len(y) else np.nan
        bb=brier_score_loss((y.res=="win").astype(int),y.p_nv.fillna(0.5)) if len(y) else np.nan
        w=x[(x.ev_m>0.05)&(x.q>=1.3)&(x.q<=2.0)].sort_values("ev_m",ascending=False).drop_duplicates("ev")
        res.append((gname,hf,sd,round(bm,4),round(bb,4),len(w),round((w.res=="win").mean(),3) if len(w) else None,round(w.roi.mean(),3) if len(w) else None))
R=pd.DataFrame(res,columns=["modell","hz","seite","brier_mod","brier_bl","wetten","treffer","roi"])
print(R.to_string(index=False))
R.to_csv(f"ek_vergleich_{art}.csv",mode="a",index=False)
