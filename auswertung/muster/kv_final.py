import pandas as pd, numpy as np, json, glob, gzip, datetime as dt
from zoneinfo import ZoneInfo
rng=np.random.default_rng(7)
g=pd.read_csv("kv_pred_netz+wettb_gbr.csv",dtype={"ev":str}); l=pd.read_csv("kv_pred_netz+wettb_glm.csv",dtype={"ev":str})
k=["ev","half","side","dir","line"]
a=g.merge(l[k+["p_m"]],on=k,suffixes=("_g","_l"))
a["p_m"]=(a.p_m_g+a.p_m_l)/2; a["edge"]=a.p_m*a.q-1
ok=(a.half=="ft")
a=a[ok]
REPO="/home/claude/trend-scanner"; B=ZoneInfo("Europe/Berlin")
info={}
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for x in json.load(gzip.open(f,"rt"))["spiele"]:
        if x.get("ev"): info[x["ev"]]=(x["S"],x["O1"],x["O2"])
a["S"]=a.ev.map(lambda e: info[e][0]); a["ko"]=a.S.map(lambda s: dt.datetime.fromtimestamp(s,B)); a["tagB"]=a.ko.map(lambda d: d.strftime("%Y-%m-%d"))
def sel(thr,qlo,qhi):
    b=a[(a.edge>thr)&(a.q>=qlo)&(a.q<=qhi)]
    return b.sort_values("edge",ascending=False).drop_duplicates("ev")
def kz(b):
    gg=b.groupby("ev").roi.mean().values; bs=[rng.choice(gg,len(gg)).mean() for _ in range(3000)]; lo,hi=np.percentile(bs,[5,95])
    tr=b[b.tag<="2026-10-20"]; te=b[b.tag>"2026-10-20"]; tage=b.groupby("tagB").roi.mean()
    return f"{len(b)} Wetten ({len(b)/11:.0f}/Tag) | Treffer {b.hit.mean():.0%} | Ø {b.q.mean():.2f} | ROI {b.roi.mean():+.1%} [90%: {lo:+.1%}…{hi:+.1%}] | 15.–20. {tr.roi.mean():+.1%} · 21.–25. {te.roi.mean():+.1%} | Tage+ {int((tage>0).sum())}/{len(tage)} | Wahrsch. Verlust auf Dauer {np.mean(np.array(bs)<0):.0%}"
for thr in (0.03,0.05,0.08):
    for qlo,qhi in ((1.3,2.0),(1.5,2.0),(1.5,2.5)):
        print(f"Edge>{thr:.2f} Quote {qlo}-{qhi}: ",kz(sel(thr,qlo,qhi)))
b=sel(0.05,1.3,2.0).sort_values("S")
print("\nje Markt:",b.groupby(["half","side","dir"]).agg(n=("hit","size"),hit=("hit","mean"),roi=("roi","mean")).round(3).to_string())
# Kombis über alle 11 Tage, Anstoß-Reihenfolge, je Tag
def kombi(b,n,cap=None):
    tot=0;cnt=0;win=0; ser=0; maxser=0
    for t,x in b.groupby("tagB"):
        x=x.sort_values("S")
        if cap: x=x.sort_values("edge",ascending=False).head(cap*n).sort_values("S")
        for i in range(len(x)//n):
            s=x.iloc[n*i:n*i+n]; q=s.q.prod(); w=s.hit.all(); cnt+=1; win+=w; tot+=(10*q if w else 0)-10
            ser=0 if w else ser+1; maxser=max(maxser,ser)
    return f"{cnt} Scheine, {win} gewonnen ({win/cnt:.0%}), Saldo {tot:+.0f} € bei {cnt*10} € Einsatz ({tot/(cnt*10):+.0%}), längste Verlustserie {maxser}"
print("\nEinzel: ",f"{len(b)} Wetten, Saldo {10*b.roi.sum():+.0f} € bei {len(b)*10} € ({b.roi.mean():+.0%})")
print("2er:    ",kombi(b,2)); print("3er:    ",kombi(b,3))
print("2er max 4/Tag:",kombi(b,2,4)); print("3er max 3/Tag:",kombi(b,3,3))
b.to_csv("kv_final_wetten.csv",index=False)
