import pandas as pd, numpy as np, datetime as dt, sys, json, glob, gzip, warnings
warnings.filterwarnings("ignore")
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import brier_score_loss
from scipy.stats import nbinom, poisson
REPO="/home/claude/trend-scanner"
S=pd.read_parquet("tore_voll.parquet")
CUT=int(dt.datetime(2026,10,15,tzinfo=dt.timezone.utc).timestamp())
rat=[c for c in S.columns if c.startswith(("r_","att_","def_"))]+["n_own","n_opp"]
netz=[c for c in S.columns if c.startswith(("own_","opp_"))]
neu=[c for c in S.columns if c.startswith(("exp_gd","exp_cor","dom"))]
wett=["cup","uefa","youth","monat","rest_own","rest_opp","eu_own","eu_opp"]
G={"basis":["own_goals_f10","opp_goals_a10","home"],
   "rating":["r_goals_own","r_goals_opp","home","n_own","n_opp"],
   "rating+xg":["home","n_own","n_opp"]+rat,
   "alles":list(dict.fromkeys(["home"]+rat+netz+neu+wett))}
swap={}
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        if g.get("ev"): swap[g["ev"]]=bool(g.get("swap"))
A=pd.read_csv("ds_a.csv",dtype={"ev":str})
A=A[(A.base=="goals")&(A.half=="ft")&A.p_nv.notna()&A.ev.isin(set(S.id))].copy(); A["roi"]=A.hit*A.q-1
def pov(mu,L,disp):
    if disp<=1.02: return 1-poisson.cdf(np.floor(L),mu)
    r=mu/(disp-1); p=r/(r+mu); return 1-nbinom.cdf(np.floor(L),r,p)
art=sys.argv[2] if len(sys.argv)>2 else "gbr"
out=[]
for gname in sys.argv[1].split(","):
    feats=list(dict.fromkeys(G[gname])); M=S[S.y_ft.notna()]; tr=M[M.t<CUT]
    if art=="gbr":
        m=HistGradientBoostingRegressor(loss="poisson",max_iter=400,learning_rate=0.05,max_leaf_nodes=31,min_samples_leaf=300,random_state=1).fit(tr[feats],tr.y_ft)
        S["mu"]=m.predict(S[feats])
    else:
        med=S[feats].median(); X=S[feats].fillna(med)
        m=PoissonRegressor(alpha=1e-4,max_iter=3000).fit(X.loc[tr.index],tr.y_ft); S["mu"]=m.predict(X)
    T=S[(S.t<CUT)&S.y_ft.notna()]
    d_team=float(np.mean((T.y_ft-T.mu)**2)/np.mean(T.mu))
    P=T.pivot_table(index="id",columns="side",values=["mu","y_ft"]).dropna()
    d_tot=float(np.mean((P.y_ft.sum(axis=1)-P.mu.sum(axis=1))**2)/np.mean(P.mu.sum(axis=1)))
    MU=S.pivot_table(index="id",columns="side",values="mu")
    a=A.copy(); mm=MU.reindex(a.ev)
    mh,ma=mm["h"].values,mm["a"].values; sw=a.ev.map(swap).fillna(False).values
    bh=np.where(sw,ma,mh); bg=np.where(sw,mh,ma)
    mu=np.where(a.side=="tot",mh+ma,np.where(a.side=="_heim",bh,bg))
    po=np.array([pov(u,L,d_tot if s=="tot" else d_team) for u,L,s in zip(mu,a.line,a.side)])
    a["p_m"]=np.where(a.dir=="o",po,1-po); a["edge"]=a.p_m*a.q-1
    a.to_csv(f"tr_pred_{gname}_{art}.csv",index=False)
    print(gname,art,"Dispersion team/tot",round(d_team,2),round(d_tot,2),flush=True)
    for (sd,L),x in a.groupby(["side","line"]):
        if L not in (1.5,2.5,3.5) : continue
        w=x[(x.edge>0.03)&(x.q>=1.3)&(x.q<=2.2)].sort_values("edge",ascending=False).drop_duplicates("ev")
        out.append((gname,sd,L,round(brier_score_loss(x.hit,x.p_m),4),round(brier_score_loss(x.hit,x.p_nv),4),len(w),round(w.hit.mean(),3) if len(w) else None,round(w.roi.mean(),3) if len(w) else None))
R=pd.DataFrame(out,columns=["modell","seite","linie","brier_mod","brier_bl","wetten","treffer","roi"])
print(R.to_string(index=False))
