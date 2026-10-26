import pandas as pd, numpy as np, json
from sklearn.linear_model import PoissonRegressor
F=pd.read_csv("karten_feat.csv",dtype={"id":str})
F=F[(F.len.isna())|(F.len==90)]
F["exp_team"]=(F.hf+F.aa)/2+(F.af+F.ha)/2
F["ref_known"]=F.ref_s.notna().astype(int)
F["ref_rel"]=np.log(F.ref_s.fillna(F.lgm).clip(0.5)/F.lgm.clip(0.5))
F["l_lg"]=np.log(F.lgm.clip(0.5)); F["l_team"]=np.log(F.exp_team.clip(0.5))
F["fo"]=np.log(((F.hfo+F.afo)/2).clip(3)).fillna(np.log(11)); F["fo_known"]=((F.hfo+F.afo).notna()).astype(int)
F["rest_min"]=np.minimum(F.rest_h,F.rest_a); F["eu"]=F.eu_h+F.eu_a
X=["l_lg","l_team","ref_rel","ref_known","fo","fo_known","rest_min","eu"]
D=F.dropna(subset=["exp_team"]).copy(); D[X]=D[X].replace([np.inf,-np.inf],np.nan).fillna(0)
tr=D[D.y.notna()]
m=PoissonRegressor(alpha=1e-4,max_iter=1000).fit(tr[X],tr.y)
mu=m.predict(tr[X]); disp=float(np.mean((tr.y-mu)**2)/np.mean(mu))
glob_lgm=float(F.lgm.median())
json.dump({"stand":pd.Timestamp.now().strftime("%Y-%m-%d"),"features":X,"intercept":float(m.intercept_),"coef":[float(c) for c in m.coef_],"disp":disp,"lgm_fallback":glob_lgm,"shrink_k":6,"n_train":int(len(tr))},open("karten_schiri_modell.json","w"))
print(dict(zip(X,np.round(m.coef_,3))),"disp",round(disp,3),"n",len(tr),"lgm_fallback",glob_lgm)
