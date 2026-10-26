import pandas as pd, numpy as np, datetime as dt
from sklearn.linear_model import PoissonRegressor
from scipy.stats import nbinom, poisson
F=pd.read_csv("karten_feat.csv",dtype={"id":str})
CUT=int(dt.datetime(2026,10,15,tzinfo=dt.timezone.utc).timestamp())
F=F[(F.len.isna())|(F.len==90)]
F["exp_team"]=(F.hf+F.aa)/2+(F.af+F.ha)/2
F["ref_known"]=F.ref_s.notna().astype(int)
F["ref_rel"]=np.log(F.ref_s.fillna(F.lgm).clip(0.5)/F.lgm.clip(0.5))
F["l_lg"]=np.log(F.lgm.clip(0.5)); F["l_team"]=np.log(F.exp_team.clip(0.5))
F["fo"]=np.log(((F.hfo+F.afo)/2).clip(3)).fillna(np.log(11)); F["fo_known"]=((F.hfo+F.afo).notna()).astype(int)
F["rest_min"]=np.minimum(F.rest_h,F.rest_a); F["eu"]=F.eu_h+F.eu_a
X=["l_lg","l_team","ref_rel","ref_known","fo","fo_known","rest_min","eu"]
D=F.dropna(subset=["exp_team"]).copy(); D[X]=D[X].replace([np.inf,-np.inf],np.nan).fillna(0)
tr=D[(D.t<CUT)&D.y.notna()]
m=PoissonRegressor(alpha=1e-4,max_iter=1000).fit(tr[X],tr.y)
print("Koeffizienten:",dict(zip(X,np.round(m.coef_,3))),"n_train",len(tr))
mu=m.predict(tr[X]); disp=np.mean((tr.y-mu)**2)/np.mean(mu); print("Dispersion var/mean",round(disp,2))
# Validierung auf Spielen ab 15.10. (ohne Quoten): Kalibrierung über 3.5/4.5
te=D[(D.t>=CUT)&D.y.notna()].copy(); te["mu"]=m.predict(te[X])
def p_over(mu,L,disp):
    k=int(np.floor(L))
    if disp<=1.02: return 1-poisson.cdf(k,mu)
    r=mu/(disp-1); p=r/(r+mu); return 1-nbinom.cdf(k,r,p)
for L in (3.5,4.5,5.5):
    te["p"]=[p_over(u,L,disp) for u in te.mu]
    te["b"]=pd.cut(te.p,[0,.3,.45,.55,.7,1])
    print(f"Über {L}:",te.groupby("b",observed=True).apply(lambda x: f"n={len(x)} Modell {x.p.mean():.2f} echt {(x.y>L).mean():.2f}",include_groups=False).to_dict())
D["mu"]=m.predict(D[X]); D[["id","t","mu","ref_known","ref_s","lgm","exp_team","y"]].to_csv("karten_mu.csv",index=False)
open("karten_disp.txt","w").write(str(disp))
