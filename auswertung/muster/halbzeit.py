"""Ecken-Halbzeitverteilung: BL-Median 1. HZ / ganzes Spiel vs. Historie (HZ-Ecken / Ecken, 10–15 Spiele)."""
import pandas as pd, numpy as np
SP="/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad"
a=pd.read_csv(f"{SP}/bulk/ds_a.csv",dtype={"ev":str})
N=pd.read_parquet(f"{SP}/muster/netz.parquet"); N["id"]=N.id.astype(str); N=N.drop_duplicates("id").set_index("id")
x=a[(a.base=="corners")&(a.side=="tot")&(a.dir=="o")&a.p_nv.notna()]
def median(g):
    g=g.sort_values("line"); L=g.line.values; p=g.p_nv.values
    i=np.where((p[:-1]>=0.5)&(p[1:]<0.5))[0]
    if not len(i): return np.nan
    i=i[0]; return L[i]+(p[i]-0.5)/(p[i]-p[i+1])*(L[i+1]-L[i])
M=x.groupby(["ev","half"]).apply(median).unstack()
M=M.dropna(subset=["ft","_h1"])
M["r_bl"]=M["_h1"]/M["ft"]
for w in (10,15):
    def ex(v): return (N[f"h_{v}_f{w}"]+N[f"a_{v}_a{w}"])/2+(N[f"a_{v}_f{w}"]+N[f"h_{v}_a{w}"])/2
    r=(ex("ht_corners")/ex("corners"))
    M[f"r_h{w}"]=M.index.map(r)
M["d10"]=M.r_h10-M.r_bl; M["d15"]=M.r_h15-M.r_bl
print(len(M),"Spiele; Ø BL-Anteil 1. HZ",M.r_bl.mean().round(3),"Ø Historie",M.r_h10.mean().round(3), "Streuung BL",M.r_bl.std().round(3),"Historie",M.r_h10.std().round(3))
# Ergebnis: Anteil 1. HZ tatsächlich
e=a[(a.base=="corners")&(a.side=="tot")].drop_duplicates(["ev","half"]).pivot(index="ev",columns="half",values="val")
M["v_h1"]=e["_h1"]; M["v_ft"]=e["ft"]
M["r_ist"]=M.v_h1/M.v_ft
M["tag"]=x.drop_duplicates("ev").set_index("ev").tag
y=M.dropna(subset=["d15","r_ist"])
print("Steigung (Ist-Anteil − BL) auf (Historie − BL), w=15:",np.polyfit(y.d15,y.r_ist-y.r_bl,1)[0].round(3), "w=10:",np.polyfit(M.dropna(subset=['d10','r_ist']).d10,M.dropna(subset=['d10','r_ist']).r_ist-M.dropna(subset=['d10','r_ist']).r_bl,1)[0].round(3))
M.to_parquet(f"{SP}/bulk/halbzeit.parquet")
# Wetten: Historie sagt mehr 1. HZ -> H1 über / H2 unter; weniger -> H1 unter / H2 über
b=a[(a.base=="corners")&(a.side=="tot")&(a.half.isin(["_h1","_h2"]))&a.p_nv.notna()&(a.q>=1.3)&(a.q<=2.1)].copy()
b["roi"]=b.hit*b.q-1; b["d"]=b.ev.map(M.d15)
b=b.dropna(subset=["d"])
qs=b.drop_duplicates("ev").d.quantile([.2,.4,.6,.8]).values; b["k"]=np.digitize(b.d,qs)
b["w"]=1/b.groupby(["ev","half","dir"]).roi.transform("size"); b["per"]=np.where(b.tag<="2026-10-20","A","B")
t=b.groupby(["half","dir","k","per"]).apply(lambda z:(z.roi*z.w).sum()/z.w.sum()).unstack().round(3)
t["spiele"]=b.groupby(["half","dir","k"]).w.sum().round()
print("\nk0 = Historie: weniger 1.-HZ-Ecken als BL … k4 = mehr"); print(t.to_string())
