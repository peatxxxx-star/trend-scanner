import pandas as pd, numpy as np, datetime as dt, json, glob, gzip, warnings, sys
warnings.filterwarnings("ignore")
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import brier_score_loss
from scipy.stats import nbinom
REPO="/home/claude/trend-scanner"
S=pd.read_parquet("karten_voll.parquet")
CUT=int(dt.datetime(2026,10,15,tzinfo=dt.timezone.utc).timestamp())
netz=[c for c in S.columns if c.startswith(("own_","opp_")) and not c.startswith(("own_h2h","opp_h2h"))]
G={"basis":["own_yellowcards_f10","opp_yellowcards_a10","lg_yellowcards","home"]}
G["netz"]=G["basis"]+[c for c in netz if c not in G["basis"]]+["lg_fouls"]
G["netz+schiri"]=G["netz"]+["ref_rel","ref_n"]
G["netz+h2h"]=G["netz"]+["h2h_n","h2h_tot","h2h_own","h2h_opp"]
G["netz+wettb"]=G["netz"]+["cup","uefa","youth","monat","rest_own","rest_opp","eu_own","eu_opp"]
G["alles"]=G["netz"]+["ref_rel","ref_n","h2h_n","h2h_tot","h2h_own","h2h_opp","cup","uefa","youth","monat","rest_own","rest_opp","eu_own","eu_opp"]
swap={}
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        if g.get("ev"): swap[g["ev"]]=bool(g.get("swap"))
A=pd.read_csv("ds_a.csv",dtype={"ev":str})
A=A[(A.base=="yellowcards")&A.p_nv.notna()&A.ev.isin(set(S.id))].copy(); A["roi"]=A.hit*A.q-1
def nb_over(mu,L,disp):
    disp=max(disp,1.01); r=mu/(disp-1); p=r/(r+mu); return 1-nbinom.cdf(np.floor(L),r,p)
res=[]; preds={}
modelle=sys.argv[1].split(",") if len(sys.argv)>1 else list(G)
art=sys.argv[2] if len(sys.argv)>2 else "gbr"
for gname in modelle:
    feats=G[gname]; MU={}
    disp={}
    for tgt in ("y_ft","y_h1"):
        M=S[S[tgt].notna()]
        tr=M[M.t<CUT]
        if art=="gbr":
            m=HistGradientBoostingRegressor(loss="poisson",max_iter=300,learning_rate=0.05,max_leaf_nodes=31,min_samples_leaf=300,random_state=1)
            m.fit(tr[feats],tr[tgt])
            mu_all=m.predict(S[feats])
        else:
            X=S[feats].fillna(S[feats].median())
            m=PoissonRegressor(alpha=1e-4,max_iter=2000).fit(X[S.t<CUT][S[tgt].notna()[S.t<CUT]],tr[tgt]); mu_all=m.predict(X)
        S["mu_"+tgt]=mu_all
        trm=S[(S.t<CUT)&S[tgt].notna()]
        disp[tgt+"_team"]=np.mean((trm[tgt]-trm["mu_"+tgt])**2)/np.mean(trm["mu_"+tgt])
        P=trm.pivot_table(index="id",columns="side",values=["mu_"+tgt,tgt])
        P=P.dropna()
        tot=P[tgt].sum(axis=1); mt=P["mu_"+tgt].sum(axis=1)
        disp[tgt+"_tot"]=np.mean((tot-mt)**2)/np.mean(mt)
        MU[tgt]=S.pivot_table(index="id",columns="side",values="mu_"+tgt)
    a=A.copy()
    def lam(row_ev,half,side):
        if half=="_h2":
            h=MU["y_ft"].loc[row_ev]-MU["y_h1"].loc[row_ev]
        else:
            h=MU["y_ft" if half=="ft" else "y_h1"].loc[row_ev]
        hh,aa=h["h"],h["a"]
        if swap.get(row_ev): hh,aa=aa,hh
        return hh+aa if side=="tot" else (hh if side=="_heim" else aa)
    a["mu"]=[lam(e,hf,sd) for e,hf,sd in zip(a.ev,a.half,a.side)]
    def dsp(hf,sd):
        k="y_ft" if hf in("ft","_h2") else "y_h1"
        return disp[k+("_tot" if sd=="tot" else "_team")]
    a["po"]=[nb_over(m_,L,dsp(hf,sd)) for m_,L,hf,sd in zip(a.mu,a.line,a.half,a.side)]
    a["p_m"]=np.where(a.dir=="o",a.po,1-a.po); a["edge"]=a.p_m*a.q-1
    preds[gname]=a
    for (hf,sd),x in a.groupby(["half","side"]):
        b=x[(x.edge>0.05)&(x.q>=1.3)&(x.q<=2.0)].sort_values("edge",ascending=False).drop_duplicates("ev")
        res.append((gname,hf,sd,round(brier_score_loss(x.hit,x.p_m),4),round(brier_score_loss(x.hit,x.p_nv),4),len(b),round(b.hit.mean(),3) if len(b) else None,round(b.roi.mean(),3) if len(b) else None))
    b=a[(a.edge>0.05)&(a.q>=1.3)&(a.q<=2.0)].sort_values("edge",ascending=False).drop_duplicates(["ev","half","side"])
    res.append((gname,"ALLE","",round(brier_score_loss(a.hit,a.p_m),4),round(brier_score_loss(a.hit,a.p_nv),4),len(b),round(b.hit.mean(),3),round(b.roi.mean(),3)))
    a.to_csv(f"kv_pred_{gname}_{art}.csv",index=False)
    print(gname,"fertig",flush=True)
R=pd.DataFrame(res,columns=["modell","hz","seite","brier_mod","brier_bl","wetten","treffer","roi"])
print(R.to_string(index=False))
R.to_csv(f"kv_vergleich_{art}.csv",index=False)
