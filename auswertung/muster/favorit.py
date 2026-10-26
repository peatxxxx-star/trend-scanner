"""Das Offensichtliche gegen BL: Favorit holt mehr Ecken. Team-Ecken (ganzes Spiel/1./2. HZ) und Ecken gesamt
nach Siegwahrscheinlichkeit (BL-1X2 ohne Marge), Heim/Auswärts, Über/Unter, Quote 1,30–2,10, je Team-Spiel 1x gewichtet."""
import pandas as pd, numpy as np
SP="/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad"
a=pd.read_csv(f"{SP}/bulk/ds_a.csv",dtype={"ev":str})
x=a[(a.base=="corners")&a.p_nv.notna()&(a.q>=1.30)&(a.q<=2.10)&a.p1.notna()].copy()
x["roi"]=x.hit*x.q-1
x["p_win"]=np.where(x.side=="_gast",x.p2,np.where(x.side=="_heim",x.p1,np.maximum(x.p1,x.p2)))
x["rolle"]=pd.cut(x.p_win,[0,.15,.25,.35,.5,.65,.8,1],labels=["Außens. <15%","15–25%","25–35%","35–50%","Fav 50–65%","Fav 65–80%","Fav >80%"])
x["w"]=1/x.groupby(["ev","base","half","side","dir"]).roi.transform("size")
x["per"]=np.where(x.tag<="2026-10-20","15–20","21–25")
def tab(y,titel):
    g=y.groupby(["rolle","dir","per"],observed=True)
    t=g.apply(lambda z:(z.roi*z.w).sum()/z.w.sum()).unstack()
    t["Spiele"]=y.groupby(["rolle","dir"],observed=True).w.sum().round()
    t["Treffer"]=y.groupby(["rolle","dir"],observed=True).apply(lambda z:(z.hit*z.w).sum()/z.w.sum())
    t["BL"]=y.groupby(["rolle","dir"],observed=True).apply(lambda z:(z.p_nv*z.w).sum()/z.w.sum())
    print(f"\n=== {titel}"); print((t.round(3)).to_string())
for half,hn in (("ft","ganzes Spiel"),("_h1","1. HZ"),("_h2","2. HZ")):
    tab(x[(x.half==half)&(x.side!="tot")],f"Team-Ecken {hn} (Rolle = Siegchance des Teams)")
tab(x[(x.half=="ft")&(x.side=="tot")],"Ecken gesamt (Rolle = Siegchance des Favoriten)")
# Heim- vs. Auswärtsfavorit
y=x[(x.half=="ft")&(x.side!="tot")&(x.p_win>=.5)]
for s,lab in (("_heim","Heimfavorit"),("_gast","Auswärtsfavorit")):
    z=y[y.side==s]
    for d in ("o","u"):
        q=z[z.dir==d]
        print(f"{lab} Team-Ecken {'über' if d=='o' else 'unter'}: Spiele {q.w.sum():.0f}, Treffer {(q.hit*q.w).sum()/q.w.sum():.0%} (BL {(q.p_nv*q.w).sum()/q.w.sum():.0%}), ROI 15–20 {((q.roi*q.w)[q.per=='15–20']).sum()/q.w[q.per=='15–20'].sum():+.1%} / 21–25 {((q.roi*q.w)[q.per=='21–25']).sum()/q.w[q.per=='21–25'].sum():+.1%}")
