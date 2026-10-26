import pandas as pd, numpy as np, json, glob, gzip, datetime as dt, warnings
warnings.filterwarnings("ignore")
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import brier_score_loss
from scipy.stats import nbinom
REPO="/home/claude/trend-scanner"
st={}
for f in glob.glob(f"{REPO}/cache/stats/s*.txt"):
    for l in open(f):
        i,_,j=l.partition("\t")
        try: st[i]=json.loads(j)
        except: pass
swap={}
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        if g.get("ev"):
            swap[g["ev"]]=bool(g.get("swap"))
            if g.get("erg"): st[g["ev"]]=g["erg"]
S=pd.read_parquet("ecken_voll.parquet")
N=pd.read_parquet("netz.parquet")
oc=[c for c in N.columns if "offsides" in c and c[:2] in ("h_","a_")]+["lg_offsides"]
S=S.merge(N[["id"]+oc],on="id",how="left")
own_h=S.side=="h"
for c in [c for c in oc if c.startswith("h_")]:
    suf=c[2:]; S["own_"+suf+"_x"]=np.where(own_h,S["h_"+suf],S["a_"+suf]); S["opp_"+suf+"_x"]=np.where(own_h,S["a_"+suf],S["h_"+suf])
S=S.drop(columns=oc[:-1])
def tgt(r):
    o=(st.get(r) or {}).get("offsides")
    return o if o and o[0] is not None and o[1] is not None and min(o)>=0 else [np.nan,np.nan]
T=np.array([tgt(i) for i in S.id],dtype=float)
S["y"]=np.where(own_h,T[:,0],T[:,1])
CUT=int(dt.datetime(2026,10,15,tzinfo=dt.timezone.utc).timestamp())
netz=[c for c in S.columns if c.startswith(("own_","opp_"))]
wett=["cup","uefa","youth","monat","rest_own","rest_opp","eu_own","eu_opp"]
G={"basis":["own_offsides_f10_x","opp_offsides_a10_x","lg_offsides","home"],
   "netz":list(dict.fromkeys(["own_offsides_f10_x","opp_offsides_a10_x","lg_offsides","home"]+netz)),
   "netz+wettb":list(dict.fromkeys(["own_offsides_f10_x","opp_offsides_a10_x","lg_offsides","home"]+netz+wett))}
A=pd.read_csv("ds_a.csv",dtype={"ev":str}); A=A[(A.base=="offsides")&(A.half=="ft")&A.p_nv.notna()&A.ev.isin(set(S.id))].copy(); A["roi"]=A.hit*A.q-1
print("Spiele mit Abseits-Ziel:",S.y.notna().sum()//2,"BL-Spiele:",A.ev.nunique())
def pov(mu,L,d):
    d=max(d,1.01); r=mu/(d-1); p=r/(r+mu); return 1-nbinom.cdf(np.floor(L),r,p)
preds={}
for art in ("gbr","glm"):
    for gname,feats in G.items():
        M=S[S.y.notna()]; tr=M[M.t<CUT]
        if art=="gbr":
            m=HistGradientBoostingRegressor(loss="poisson",max_iter=300,learning_rate=0.05,max_leaf_nodes=31,min_samples_leaf=300,random_state=1).fit(tr[feats],tr.y); mu=m.predict(S[feats])
        else:
            med=S[feats].median(); X=S[feats].fillna(med); m=PoissonRegressor(alpha=1e-4,max_iter=3000).fit(X.loc[tr.index],tr.y); mu=m.predict(X)
        S["mu"]=mu; T_=S[(S.t<CUT)&S.y.notna()]
        dt_=np.mean((T_.y-T_.mu)**2)/np.mean(T_.mu)
        P=T_.pivot_table(index="id",columns="side",values=["mu","y"]).dropna(); dtot=np.mean((P.y.sum(axis=1)-P.mu.sum(axis=1))**2)/np.mean(P.mu.sum(axis=1))
        MU=S.pivot_table(index="id",columns="side",values="mu").reindex(A.ev)
        mh,ma=MU["h"].values,MU["a"].values; sw=A.ev.map(swap).fillna(False).values
        bh=np.where(sw,ma,mh); bg=np.where(sw,mh,ma)
        m_=np.where(A.side=="tot",mh+ma,np.where(A.side=="_heim",bh,bg))
        po=np.array([pov(u,L,dtot if s=="tot" else dt_) for u,L,s in zip(m_,A.line,A.side)])
        a=A.copy(); a["p_m"]=np.where(a.dir=="o",po,1-po); a["edge"]=a.p_m*a.q-1
        preds[(gname,art)]=a
        print(f"\n{gname} {art} (Dispersion {dt_:.2f}/{dtot:.2f})")
        for sd,x in a.groupby("side"):
            w=x[(x.edge>0.05)&(x.q>=1.3)&(x.q<=2.0)].sort_values("edge",ascending=False).drop_duplicates("ev")
            print(f"  {sd:6s} Brier Modell {brier_score_loss(x.hit,x.p_m):.4f} BL {brier_score_loss(x.hit,x.p_nv):.4f} | Wetten {len(w)}, Treffer {w.hit.mean():.0%}, ROI {w.roi.mean():+.1%} | 15–20 {w[w.tag<='2026-10-20'].roi.mean():+.1%} · 21–25 {w[w.tag>'2026-10-20'].roi.mean():+.1%}")
        w=a[(a.edge>0.05)&(a.q>=1.3)&(a.q<=2.0)].sort_values("edge",ascending=False).drop_duplicates("ev")
        print(f"  ALLE je Spiel 1 Tipp: {len(w)} Wetten, Treffer {w.hit.mean():.0%}, Ø {w.q.mean():.2f}, ROI {w.roi.mean():+.1%} | unter {w[w.dir=='u'].roi.mean():+.1%} ({(w.dir=='u').sum()}) · über {w[w.dir=='o'].roi.mean():+.1%} ({(w.dir=='o').sum()}) | 15–20 {w[w.tag<='2026-10-20'].roi.mean():+.1%} · 21–25 {w[w.tag>'2026-10-20'].roi.mean():+.1%}")
import pickle; pickle.dump(preds,open("abseits_preds.pkl","wb"))
