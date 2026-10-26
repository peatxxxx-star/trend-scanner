"""Abseits mit reinen Fenster-Merkmalen (wie die Karten-Engine rechnen kann): Backtest + finaler Export."""
import pandas as pd, numpy as np, json, glob, gzip, datetime as dt, warnings, sys
warnings.filterwarnings("ignore")
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from scipy.stats import nbinom
MET=sys.argv[2]
REPO="/home/claude/trend-scanner"
N=pd.read_parquet("netz.parquet")
K=pd.read_parquet("karten_voll.parquet")[["id","side","cup","uefa","youth","monat","rest_own","rest_opp","eu_own","eu_opp"]]
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
win=[c[2:] for c in N.columns if c.startswith("h_")]
parts=[]
for own,opp,home in (("h","a",1),("a","h",0)):
    c={"id":N.id,"t":N.t,"side":pd.Series(own,index=N.index),"home":pd.Series(home,index=N.index),f"lg_{MET}":N[f"lg_{MET}"]}
    for w in win:
        c["own_"+w]=N[own+"_"+w]; c["opp_"+w]=N[opp+"_"+w]
    parts.append(pd.DataFrame(c))
S=pd.concat(parts,ignore_index=True).merge(K,on=["id","side"],how="left")
def tg(i):
    o=(st.get(i) or {}).get(MET); return o if o and o[0] is not None and o[1] is not None and min(o)>=0 else [np.nan,np.nan]
T=np.array([tg(i) for i in N.id],dtype=float)
S["y"]=np.concatenate([T[:,0],T[:,1]])
feats=[f"own_{MET}_f10",f"opp_{MET}_a10",f"lg_{MET}","home"]+[c for c in S.columns if c.startswith(("own_","opp_"))]+["cup","uefa","youth","monat","rest_own","rest_opp","eu_own","eu_opp"]
feats=list(dict.fromkeys(feats))
def fit(train):
    g=HistGradientBoostingRegressor(loss="poisson",max_iter=300,learning_rate=0.05,max_leaf_nodes=31,min_samples_leaf=300,random_state=1).fit(train[feats],train.y)
    med=S[feats].median(); l=PoissonRegressor(alpha=1e-4,max_iter=3000).fit(train[feats].fillna(med),train.y)
    return g,l,med
def disp(mu,train):
    d_t=float(np.mean((train.y-mu)**2)/np.mean(mu))
    P=pd.DataFrame({"id":train.id,"s":train.side,"mu":mu,"y":train.y}).pivot_table(index="id",columns="s",values=["mu","y"]).dropna()
    return d_t,float(np.mean((P.y.sum(axis=1)-P.mu.sum(axis=1))**2)/np.mean(P.mu.sum(axis=1)))
def pov(mu,L,d):
    d=max(d,1.01); r=mu/(d-1); p=r/(r+mu); return 1-nbinom.cdf(np.floor(L),r,p)
M=S[S.y.notna()]
if sys.argv[1]=="test":
    CUT=int(dt.datetime(2026,10,15,tzinfo=dt.timezone.utc).timestamp())
    tr=M[M.t<CUT]; g,l,med=fit(tr)
    A=pd.read_csv("ds_a.csv",dtype={"ev":str}); A=A[(A.base==MET)&(A.half=="ft")&A.p_nv.notna()&A.ev.isin(set(S.id))].copy(); A["roi"]=A.hit*A.q-1
    ps=[]
    for mod,mu_tr,mu_all in ((g,g.predict(tr[feats]),g.predict(S[feats])),(l,l.predict(tr[feats].fillna(med)),l.predict(S[feats].fillna(med)))):
        dt_,dtot=disp(mu_tr,tr); S["mu"]=mu_all
        MU=S.pivot_table(index="id",columns="side",values="mu").reindex(A.ev)
        mh,ma=MU["h"].values,MU["a"].values; sw=A.ev.map(swap).fillna(False).values
        m_=np.where(A.side=="tot",mh+ma,np.where(sw,mh,ma))
        po=np.array([pov(u,L,dtot if s=="tot" else dt_) for u,L,s in zip(m_,A.line,A.side)])
        ps.append(np.where(A.dir=="o",po,1-po))
    A["p_m"]=(ps[0]+ps[1])/2; A["edge"]=A.p_m*A.q-1
    for sd,xx in A.groupby("side"):
        bb=xx[(xx.edge>0.05)&(xx.edge<=0.2)&(xx.q>=1.3)&(xx.q<=2.0)].sort_values("edge",ascending=False).drop_duplicates("ev")
        print(sd,len(bb),"W",f"{bb.hit.mean():.0%}",f"ROI {bb.roi.mean():+.1%}",f"15–20 {bb[bb.tag<='2026-10-20'].roi.mean():+.1%} · 21–25 {bb[bb.tag>'2026-10-20'].roi.mean():+.1%}")
    b=A[(A.edge>0.05)&(A.q>=1.3)&(A.q<=2.0)].sort_values("edge",ascending=False).drop_duplicates("ev")
    b["eb"]=pd.cut(b.edge,[0.05,0.1,0.15,0.2,0.3,9])
    print(b.groupby("eb",observed=True).agg(n=("hit","size"),hit=("hit","mean"),p=("p_m","mean"),roi=("roi","mean")).round(3))
    for cap in (0.2,0.3,9):
        x=b[b.edge<=cap]; print(f"Vorteil 5–{cap:.0%}: {len(x)} W, Treffer {x.hit.mean():.0%}, ROI {x.roi.mean():+.1%} | 15–20 {x[x.tag<='2026-10-20'].roi.mean():+.1%} · 21–25 {x[x.tag>'2026-10-20'].roi.mean():+.1%} | unter {x[x.dir=='u'].roi.mean():+.1%} ({(x.dir=='u').sum()})")
else:
    g,l,med=fit(M); dg=disp(g.predict(M[feats]),M); dl=disp(l.predict(M[feats].fillna(med)),M)
    trees=[[[int(r["feature_idx"]),float(r["num_threshold"]),int(r["missing_go_to_left"]),int(r["left"]),int(r["right"]),int(r["is_leaf"]),float(r["value"])] for r in it[0].nodes] for it in g._predictors]
    out={"stand":pd.Timestamp.now().strftime("%Y-%m-%d"),"features":feats,"n_train":int(len(M)),
         "gbr":{"baseline":float(np.ravel(g._baseline_prediction)[0]),"trees":trees,"disp_team":dg[0],"disp_tot":dg[1]},
         "glm":{"intercept":float(l.intercept_),"coef":[float(c) for c in l.coef_],"median":[float(v) if pd.notna(v) else 0.0 for v in med.values],"disp_team":dl[0],"disp_tot":dl[1]}}
    json.dump(out,open("abseits_modell.json","w")); print("Export",len(feats),"Merkmale",len(M),"Zeilen",dg,dl)
