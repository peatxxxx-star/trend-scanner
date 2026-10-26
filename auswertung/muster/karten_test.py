import pandas as pd, numpy as np
from scipy.stats import poisson, nbinom
disp=float(open("karten_disp.txt").read())
M=pd.read_csv("karten_mu.csv",dtype={"id":str})
A=pd.read_csv("ds_a.csv",dtype={"ev":str})
y=A[(A.base=="yellowcards")&(A.half=="ft")&(A.side=="tot")&A.p_nv.notna()].merge(M,left_on="ev",right_on="id")
def pov(mu,L):
    k=int(np.floor(L)); r=mu/(disp-1); p=r/(r+mu)
    return 1-nbinom.cdf(k,r,p)
y["p_o"]=[pov(u,L) for u,L in zip(y.mu,y.line)]
y["p_m"]=np.where(y.dir=="o",y.p_o,1-y.p_o)
y["roi"]=y.hit*y.q-1; y["edge"]=y.p_m*y.q-1
print("BL-Kartenlinien gesamt:",len(y),"Spiele",y.ev.nunique(),"davon mit Schiri",y[y.ref_known==1].ev.nunique())
from sklearn.metrics import brier_score_loss
print("Brier BL",round(brier_score_loss(y.hit,y.p_nv),4),"Modell",round(brier_score_loss(y.hit,y.p_m),4),
      "| mit Schiri: BL",round(brier_score_loss(y[y.ref_known==1].hit,y[y.ref_known==1].p_nv),4),"Modell",round(brier_score_loss(y[y.ref_known==1].hit,y[y.ref_known==1].p_m),4))
def bericht(x,lab):
    for thr in (0.0,0.05,0.10,0.15):
        b=x[(x.edge>thr)&(x.q>=1.3)&(x.q<=2.2)].sort_values("edge",ascending=False).drop_duplicates(["ev","dir"])
        if len(b)==0: continue
        tage=b.groupby("tag").roi.mean()
        print(f"  {lab} Edge>{thr:.2f}: {len(b)} Wetten, Treffer {b.hit.mean():.0%}, Ø Quote {b.q.mean():.2f}, ROI {b.roi.mean():+.1%} | Tage im Plus {int((tage>0).sum())}/{len(tage)} | 1.Hälfte {b[b.tag<='2026-10-20'].roi.mean():+.1%} 2.Hälfte {b[b.tag>'2026-10-20'].roi.mean():+.1%}")
for d_,lab in (("u","UNTER"),("o","ÜBER")):
    bericht(y[y.dir==d_],lab+" alle")
    bericht(y[(y.dir==d_)&(y.ref_known==1)],lab+" mit Schiri")
y.to_csv("karten_bl.csv",index=False)
