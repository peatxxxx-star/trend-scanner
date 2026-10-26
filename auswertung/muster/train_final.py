"""Finales Karten-Modell (netz+wettb): Boosting (Poisson) + Poisson-GLM auf allen Spielen bis heute.
Export als reines JSON (Bäume + Koeffizienten), damit der Scanner ohne scikit-learn rechnen kann."""
import pandas as pd, numpy as np, json, warnings
warnings.filterwarnings("ignore")
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
S=pd.read_parquet("karten_voll.parquet")
netz=[c for c in S.columns if c.startswith(("own_","opp_")) and not c.startswith(("own_h2h","opp_h2h"))]
base=["own_yellowcards_f10","opp_yellowcards_a10","lg_yellowcards","home"]
feats=base+[c for c in netz if c not in base]+["lg_fouls","cup","uefa","youth","monat","rest_own","rest_opp","eu_own","eu_opp"]
M=S[S.y_ft.notna()]
g=HistGradientBoostingRegressor(loss="poisson",max_iter=300,learning_rate=0.05,max_leaf_nodes=31,min_samples_leaf=300,random_state=1).fit(M[feats],M.y_ft)
med=S[feats].median()
X=M[feats].fillna(med)
l=PoissonRegressor(alpha=1e-4,max_iter=3000).fit(X,M.y_ft)
def disp(mu,y,ids,sides):
    d_team=float(np.mean((y-mu)**2)/np.mean(mu))
    P=pd.DataFrame({"id":ids,"s":sides,"mu":mu,"y":y}).pivot_table(index="id",columns="s",values=["mu","y"]).dropna()
    t=P["y"].sum(axis=1); m=P["mu"].sum(axis=1)
    return d_team,float(np.mean((t-m)**2)/np.mean(m))
mg=g.predict(M[feats]); ml=l.predict(X)
dg=disp(mg,M.y_ft.values,M.id.values,M.side.values); dl=disp(ml,M.y_ft.values,M.id.values,M.side.values)
trees=[]
for it in g._predictors:
    n=it[0].nodes
    trees.append([[int(r["feature_idx"]),float(r["num_threshold"]),int(r["missing_go_to_left"]),int(r["left"]),int(r["right"]),int(r["is_leaf"]),float(r["value"])] for r in n])
out={"stand":pd.Timestamp.now().strftime("%Y-%m-%d"),"features":feats,"n_train":int(len(M)),
     "gbr":{"baseline":float(np.ravel(g._baseline_prediction)[0]),"trees":trees,"disp_team":dg[0],"disp_tot":dg[1]},
     "glm":{"intercept":float(l.intercept_),"coef":[float(c) for c in l.coef_],"median":[float(v) if pd.notna(v) else 0.0 for v in med.values],"disp_team":dl[0],"disp_tot":dl[1]}}
json.dump(out,open("karten_modell.json","w"))
# Selbstkontrolle: reine Python-Auswertung == sklearn
def pred_tree(x):
    raw=out["gbr"]["baseline"]
    for t in trees:
        i=0
        while True:
            f,th,ml_,le,ri,leaf,val=t[i]
            if leaf: raw+=val; break
            v=x[f]
            i = (le if ml_ else ri) if v is None or (isinstance(v,float) and np.isnan(v)) else (le if v<=th else ri)
    return float(np.exp(raw))
smp=M.sample(300,random_state=3)
own=[pred_tree(list(r)) for r in smp[feats].itertuples(index=False)]
print("max Abweichung Bäume:",float(np.max(np.abs(np.array(own)-g.predict(smp[feats])))))
xl=smp[feats].fillna(med).values
own_l=np.exp(out["glm"]["intercept"]+xl@np.array(out["glm"]["coef"]))
print("max Abweichung GLM:",float(np.max(np.abs(own_l-l.predict(smp[feats].fillna(med))))))
print("Merkmale",len(feats),"Spiele",len(M),"Disp",dg,dl, "Dateigröße", round(len(json.dumps(out))/1e6,2),"MB")
