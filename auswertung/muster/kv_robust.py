import pandas as pd, numpy as np, sys
rng=np.random.default_rng(1)
def lade(n):
    a=pd.read_csv(n,dtype={"ev":str}); return a[a.half!="_h1"].copy()
def wetten(a,thr=0.05,qlo=1.3,qhi=2.0,dirs=("o","u")):
    b=a[(a.edge>thr)&(a.q>=qlo)&(a.q<=qhi)&a.dir.isin(dirs)]
    return b.sort_values("edge",ascending=False).drop_duplicates("ev")   # 1 Tipp je Spiel (bester Vorteil)
def kz(b):
    if len(b)==0: return "—"
    g=b.groupby("ev").roi.mean().values
    bs=[rng.choice(g,len(g)).mean() for _ in range(2000)]
    lo,hi=np.percentile(bs,[5,95])
    tr=b[b.tag<="2026-10-20"]; te=b[b.tag>"2026-10-20"]
    tage=b.groupby("tag").roi.mean()
    return f"{len(b):4d} W | Treffer {b.hit.mean():.0%} | Ø {b.q.mean():.2f} | ROI {b.roi.mean():+.1%} [90%: {lo:+.1%} … {hi:+.1%}] | 15.–20. {tr.roi.mean():+.1%} ({len(tr)}) · 21.–25. {te.roi.mean():+.1%} ({len(te)}) | Tage+ {int((tage>0).sum())}/{len(tage)}"
for n in sys.argv[1:]:
    a=lade(n); print(f"\n######## {n}")
    for thr in (0.0,0.03,0.05,0.08,0.12):
        print(f" Edge>{thr:.2f}:",kz(wetten(a,thr)))
    print(" nur unter:",kz(wetten(a,0.05,dirs=("u",))))
    print(" nur über :",kz(wetten(a,0.05,dirs=("o",))))
    for lo,hi in ((1.3,1.5),(1.5,1.75),(1.75,2.0),(2.0,2.5)):
        print(f" Quote {lo}-{hi}:",kz(wetten(a,0.05,lo,hi)))
    b=wetten(a,0.05)
    print(" je Markt:"); print(b.groupby(["half","side"]).agg(n=("hit","size"),hit=("hit","mean"),roi=("roi","mean")).round(3).to_string())
    b["land"]=b.bl_liga.str.split(".").str[0]
    print(" je Land (≥8):"); x=b.groupby("land").agg(n=("hit","size"),roi=("roi","mean")); print(x[x.n>=8].round(3).sort_values("roi").to_string())
