import pandas as pd, numpy as np, itertools
d=pd.read_csv('ds_a.csv'); d=d[d.p_nv.notna()].copy()
d['roi']=d.hit*d.q-1
ok=((d.base=='corners')|((d.base=='goals')&((d.half=='ft')|((d.half=='_h1')&(d.side!='_gast'))))|((d.base=='yellowcards')&(d.half!='_h2')&~((d.half=='ft')&(d.side=='_gast')))|((d.base=='on_target')&(d.half=='ft')))
d=d[ok].copy()
d['train']=d.tag<='2026-10-20'
d['pband']=pd.cut(d.p_nv,[0,.3,.45,.55,.65,.75,.85,1],labels=['<30','30-45','45-55','55-65','65-75','75-85','85+'])
d['qband']=pd.cut(d.q,[1,1.3,1.5,1.7,2.0,2.5,100],labels=['<1.3','1.3-1.5','1.5-1.7','1.7-2.0','2.0-2.5','2.5+'])
d['rolle']=pd.cut(pd.to_numeric(d.p_team,errors='coerce'),[0,.25,.4,.55,.7,1],labels=['klarer Außens.','Außens.','ausgegl.','Fav','klarer Fav'])
d['land']=d.bl_liga.str.split('.').str[0].str.strip()
# eine Zeile je Spiel x Markt-Gruppe x Richtung? Linien hängen zusammen -> pro Spiel gewichten
dims=['base','half','side','dir','pband','qband','rolle']
res=[]
for k in (2,3,4):
    for combo in itertools.combinations(dims,k):
        g=d.groupby(list(combo)+['train'],observed=True).agg(n=('roi','size'),spiele=('ev','nunique'),roi=('roi','mean'),hit=('hit','mean'),q=('q','mean'))
        g=g.unstack('train')
        g.columns=[f"{a}_{'tr' if b else 'te'}" for a,b in g.columns]
        g=g.dropna()
        g=g[(g.spiele_tr>=120)&(g.spiele_te>=120)&(g.roi_tr>0.03)&(g.roi_te>0.03)]
        for idx,r in g.iterrows():
            res.append((r.roi_te+r.roi_tr, dict(zip(combo, idx if isinstance(idx,tuple) else (idx,))), int(r.spiele_tr), round(r.roi_tr,3), int(r.spiele_te), round(r.roi_te,3), round(r.hit_te,3), round(r.q_te,2)))
res.sort(key=lambda x:-x[0])
seen=0
for r in res[:60]: print(r[1:])
print(len(res))
