import pandas as pd, numpy as np, datetime as dt
from sklearn.linear_model import LinearRegression
S=pd.read_parquet("ecken_voll.parquet")
CUT=int(dt.datetime(2026,10,1,tzinfo=dt.timezone.utc).timestamp())
base=["own_corners_f10","opp_corners_a10","lg_corners","home"]
M=S.dropna(subset=base+["y_ft"]).copy()
tr=M.t<CUT
lr=LinearRegression().fit(M.loc[tr,base],M.loc[tr,"y_ft"])
M["res"]=M.y_ft-lr.predict(M[base])
print("Basis R² (Test):",round(1-M.loc[~tr,"res"].var()/M.loc[~tr,"y_ft"].var(),4))
feats=[c for c in M.columns if c not in base and c not in ("id","t","lg","side","y_ft","y_h1","y_h2","res") and M[c].dtype!=object]
out=[]
for f in feats:
    z=M[[f,"res","t"]].dropna()
    if len(z)<20000 or z[f].nunique()<3: continue
    a=z[z.t<CUT]; b=z[z.t>=CUT]
    out.append((f,np.corrcoef(a[f],a.res)[0,1],np.corrcoef(b[f],b.res)[0,1],len(b)))
R=pd.DataFrame(out,columns=["merkmal","k_train","k_test","n_test"])
R["stabil"]=np.sign(R.k_train)==np.sign(R.k_test); R["staerke"]=np.minimum(R.k_train.abs(),R.k_test.abs())*R.stabil
R.sort_values("staerke",ascending=False).to_csv("ecken_stufe1.csv",index=False)
print(R.sort_values("staerke",ascending=False).head(30).round(3).to_string(index=False))
# Interpretation: Wirkung der stärksten neuen Merkmale in Quintilen (Rest = Ecken über/unter Basis-Erwartung)
for f in ("exp_gd10","own_sshare10","opp_tshare10","own_blk_f10","opp_blk_a10","dom10","own_csd_f","cup","uefa","youth","rest_own","eu_own","opp_cshare10"):
    if f not in M: continue
    z=M[[f,"res"]].dropna()
    try: z["b"]=pd.qcut(z[f],5,duplicates="drop")
    except Exception: z["b"]=z[f]
    print(f"\n{f}:", " | ".join(f"{str(k)[:16]}: {v:+.2f}" for k,v in z.groupby("b",observed=True).res.mean().items()))
