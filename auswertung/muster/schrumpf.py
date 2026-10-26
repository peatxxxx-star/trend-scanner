"""Schrumpft BL extreme Teams zu stark zur Mitte? Je Spiel: BL-Median (Linie, an der Über ≈ 50 %, interpoliert),
Historien-Erwartung x (10 Spiele für/gegen), Ergebnis. Steigung von (Ergebnis − BL) auf (x − BL)."""
import pandas as pd, numpy as np, sys
SP="/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad"
a=pd.read_csv(f"{SP}/bulk/ds_a.csv",dtype={"ev":str})
N=pd.read_parquet(f"{SP}/muster/netz.parquet"); N["id"]=N.id.astype(str); N=N.set_index("id")
out=[]
for base,var in (("corners","corners"),("goals","goals"),("yellowcards","yellowcards")):
    x=a[(a.base==base)&(a.half=="ft")&(a.side=="tot")&(a.dir=="o")&a.p_nv.notna()]
    for ev,g in x.groupby("ev"):
        g=g.sort_values("line"); L=g.line.values; p=g.p_nv.values
        if len(L)<2 or not (p.max()>=0.5>=p.min()): continue
        i=np.where((p[:-1]>=0.5)&(p[1:]<0.5))[0]
        if not len(i): continue
        i=i[0]; med=L[i]+(p[i]-0.5)/(p[i]-p[i+1])*(L[i+1]-L[i])
        if ev not in N.index: continue
        n=N.loc[ev]
        if isinstance(n,pd.DataFrame): n=n.iloc[0]
        xs={}
        for w in (5,10,15):
            try: xs[w]=(n[f"h_{var}_f{w}"]+n[f"a_{var}_a{w}"])/2+(n[f"a_{var}_f{w}"]+n[f"h_{var}_a{w}"])/2
            except KeyError: xs[w]=np.nan
        out.append(dict(base=base,ev=ev,tag=g.tag.iloc[0],med=med,val=g.val.iloc[0],x5=xs[5],x10=xs[10],x15=xs[15],liga=g.bl_liga.iloc[0]))
D=pd.DataFrame(out); D.to_parquet(f"{SP}/bulk/schrumpf.parquet")
for base,d in D.groupby("base"):
    print(f"\n=== {base}: {len(d)} Spiele, Ø Ergebnis {d.val.mean():.2f}, Ø BL-Median {d.med.mean():.2f}")
    for w in (5,10,15):
        y=d.dropna(subset=[f"x{w}"]); dx=y[f"x{w}"]-y.med; dr=y.val-y.med
        b=np.polyfit(dx,dr,1)[0]
        for per,m in (("15–20",y.tag<="2026-10-20"),("21–25",y.tag>"2026-10-20")):
            pass
        bA=np.polyfit(dx[y.tag<="2026-10-20"],dr[y.tag<="2026-10-20"],1)[0]; bB=np.polyfit(dx[y.tag>"2026-10-20"],dr[y.tag>"2026-10-20"],1)[0]
        print(f"  x{w}: Steigung {b:+.3f} (15–20 {bA:+.3f}, 21–25 {bB:+.3f}), n={len(y)}")
    y=d.dropna(subset=["x10"]).copy(); y["dx"]=y.x10-y.med
    y["band"]=pd.qcut(y.dx,7)
    print(y.groupby("band").apply(lambda z: pd.Series(dict(n=len(z),hist_minus_BL=z.dx.mean(),ergebnis_minus_BL=(z.val-z.med).mean()))).round(2).to_string())
