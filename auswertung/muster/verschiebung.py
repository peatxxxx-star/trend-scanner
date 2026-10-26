"""BL-Leiter verschieben: neue Wahrscheinlichkeit P(Über L) = BL-P(Über L − k), k = b1·(Team-Hist − BL-Median) + b2·(Liga − BL-Median).
b1/b2 auf 15.–20. geschätzt, Wetten auf 21.–25. (und umgekehrt). Gesamt-Ecken/Tore, Quote 1,30–2,10, 1 Tipp je Spiel."""
import pandas as pd, numpy as np, sys
SP="/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad"
S=pd.read_parquet(f'{SP}/bulk/schrumpf.parquet'); N=pd.read_parquet(f"{SP}/muster/netz.parquet"); N["id"]=N.id.astype(str); N=N.drop_duplicates("id").set_index("id")
a=pd.read_csv(f'{SP}/bulk/ds_a.csv',dtype={'ev':str})
for base in ('corners','goals'):
    y=S[S.base==base].copy(); y['lg']=y.ev.map(N[f'lg_{base}']); y=y.dropna(subset=['lg','x15']).set_index('ev')
    lad=a[(a.base==base)&(a.half=='ft')&(a.side=='tot')&a.p_nv.notna()]
    O=lad[lad.dir=='o']; U=lad[lad.dir=='u']
    for fit,test in ((('2026-10-15','2026-10-20'),('2026-10-21','2026-10-25')),(('2026-10-21','2026-10-25'),('2026-10-15','2026-10-20'))):
        F=y[(y.tag>=fit[0])&(y.tag<=fit[1])]
        X=np.column_stack([F.x15-F.med,F.lg-F.med,np.ones(len(F))]); b=np.linalg.lstsq(X,(F.val-F.med).values,rcond=None)[0]
        T=y[(y.tag>=test[0])&(y.tag<=test[1])]
        k=b[0]*(T.x15-T.med)+b[1]*(T.lg-T.med)
        for thr in (0.0,0.02,0.04):
            res=[]
            for ev,kk in k.items():
                o=O[O.ev==ev].sort_values('line')
                if len(o)<2: continue
                Ls=o.line.values; ps=o.p_nv.values
                best=None
                for r in o.itertuples():
                    pn=np.interp(r.line-kk,Ls,ps)   # p fällt mit L; interp braucht steigende x -> Ls steigt, ok
                    if 1.3<=r.q<=2.1:
                        e=pn*r.q-1
                        if e>thr and (best is None or e>best[0]): best=(e,r.hit*r.q-1)
                    u=U[(U.ev==ev)&(U.line==r.line)]
                    if len(u) and 1.3<=u.q.iloc[0]<=2.1:
                        e=(1-pn)*u.q.iloc[0]-1
                        if e>thr and (best is None or e>best[0]): best=(e,u.hit.iloc[0]*u.q.iloc[0]-1)
                if best: res.append(best[1])
            r=np.array(res)
            print(f"{base:8s} Schätzung {fit[0][5:]}–{fit[1][5:]} (b={b[0]:.2f}/{b[1]:.2f}) → Test {test[0][5:]}–{test[1][5:]} | Vorteil>{thr:.0%}: n={len(r)} ROI {r.mean():+.1%}")
