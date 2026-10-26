import pandas as pd, numpy as np, json, glob, gzip
from collections import defaultdict, deque
REPO="/home/claude/trend-scanner"
lg_=lambda p: np.log(np.clip(p,1e-3,1-1e-3)/(1-np.clip(p,1e-3,1-1e-3)))
a=pd.read_csv("tr_pred_alles_gbr.csv",dtype={"ev":str})
x=a[(a.side=="tot")&(a.line==2.5)].copy()
x["tr"]=x.tag<="2026-10-20"
# 1) Abweichung Modell vs BL: wer hat recht?
x["d"]=lg_(x.p_m)-lg_(x.p_nv); x["db"]=pd.cut(x.d,[-9,-.4,-.2,-.07,.07,.2,.4,9])
print("1) Modell weicht von BL ab (Über/Unter 2.5):")
print(x.groupby("db",observed=True).apply(lambda z: f"n={len(z)} BL {z.p_nv.mean():.3f} Modell {z.p_m.mean():.3f} echt {z.hit.mean():.3f}",include_groups=False).to_string())
# 2) Liga-Trend: laufende Über-2.5-Quote der Liga (letzte 80 Spiele vor Anstoß) vs. BL
st={}
for f in glob.glob(f"{REPO}/cache/stats/s*.txt"):
    for l in open(f):
        i,_,j=l.partition("\t")
        try: st[i]=json.loads(j)
        except: pass
E=pd.read_csv("karten_ev.csv",dtype={"id":str})[["id","t","lg"]]
T=json.load(open(f"{REPO}/runs/archiv_teams.json"))
S=pd.read_parquet("netz.parquet")[["id","t"]]
arch=pd.DataFrame([{"id":k,"lg":v[5]} for k,v in T.items()]).merge(S,on="id")
E=pd.concat([E,arch]).drop_duplicates("id").sort_values("t")
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        if g.get("ev") and g.get("erg"): st[g["ev"]]=g["erg"]
q=defaultdict(lambda: deque(maxlen=80)); rate={}
for r in E.itertuples():
    L=q[str(r.lg)]; rate[r.id]=(np.mean(L) if len(L)>=40 else np.nan, len(L))
    s=st.get(r.id) or {}; g=s.get("goals")
    if g and g[0] is not None and min(g)>=0 and s.get("len") in (None,90): L.append(int(g[0]+g[1]>2.5))
o=x[x.dir=="o"].copy()
o["lgrate"]=o.ev.map(lambda e: rate.get(e,(np.nan,0))[0])
o["gap"]=o.lgrate-o.p_nv
o=o.dropna(subset=["gap"])
o["gb"]=pd.cut(o.gap,[-1,-.1,-.05,0,.05,.1,.15,1])
print("\n2) Über 2.5 nach Liga-Trend (laufende Über-Quote der Liga minus BL):")
print(o.groupby(["gb"],observed=True).apply(lambda z: f"n={len(z)} BL {z.p_nv.mean():.3f} echt {z.hit.mean():.3f} ROI {z.roi.mean():+.3f} | 15–20 {z[z.tr].roi.mean():+.3f} ({z.tr.sum()}) · 21–25 {z[~z.tr].roi.mean():+.3f} ({(~z.tr).sum()})",include_groups=False).to_string())
# 3) Länder-Stabilität: Über 2.5 je Land in beiden Zeiträumen
o["land"]=o.bl_liga.str.split(".").str[0]
L=o.groupby(["land","tr"]).agg(n=("hit","size"),gap=("hit",lambda h: 0)).unstack()
g=o.assign(l=o.hit-o.p_nv).groupby(["land","tr"]).l.mean().unstack()
c=o.groupby(["land","tr"]).size().unstack()
g=g[(c[True]>=20)&(c[False]>=20)]
print("\n3) Über-2.5-Lücke (echt − BL) je Land, 15–20 vs 21–25 (≥20 Spiele je Zeitraum): Korrelation",round(np.corrcoef(g[True],g[False])[0,1],2),"bei",len(g),"Ländern")
print(g.round(3).sort_values(True).to_string())
# 4) Kombination Serie × Modell × Trend: Serien-BL-Liste über 2.5
R=pd.read_csv("serien_tore.csv",dtype={"ev":str})
R=R[(R.dir=="über")&(R.line==2.5)&R.liste]
R=R.merge(o[["ev","p_m","lgrate","gap"]],on="ev",how="left",suffixes=("_x",""))
for lab,f in (("alle",R.index==R.index),("Modell ≥ BL",R.p_m>=R.p_nv),("Modell < BL",R.p_m<R.p_nv),("Liga-Trend > 0",R.gap>0),("Liga-Trend ≤ 0",R.gap<=0)):
    z=R[f]
    if len(z): print(f"4) Serien-Liste über 2.5 · {lab:14s}: {len(z):3d} Tipps, Treffer {z.hit.mean():.0%}, ROI {z.roi.mean():+.1%}")
# 5) Wochentag / Anstoßzeit
import datetime as dt
from zoneinfo import ZoneInfo
info={}
for f in glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz"):
    for g_ in json.load(gzip.open(f,"rt"))["spiele"]:
        if g_.get("ev"): info[g_["ev"]]=g_["S"]
o["ko"]=o.ev.map(info).map(lambda s: dt.datetime.fromtimestamp(s,ZoneInfo("Europe/Berlin")) if s else None)
o["wt"]=o.ko.map(lambda d: d.weekday()>=5); o["std"]=o.ko.map(lambda d: d.hour)
print("\n5) Über 2.5 Wochenende vs. unter der Woche:",o.groupby("wt").apply(lambda z: f"n={len(z)} echt−BL {(z.hit-z.p_nv).mean():+.3f} ROI {z.roi.mean():+.3f}",include_groups=False).to_dict())
o["sb"]=pd.cut(o["std"],[-1,11,15,18,21,24])
print("   nach Anstoß-Stunde:",o.groupby("sb",observed=True).apply(lambda z: f"n={len(z)} echt−BL {(z.hit-z.p_nv).mean():+.3f} ROI {z.roi.mean():+.3f}",include_groups=False).to_dict())
