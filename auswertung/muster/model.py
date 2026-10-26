import pandas as pd, numpy as np
from sklearn.linear_model import LogisticRegression
d=pd.read_csv('ds_b.csv',dtype={'ev':str})
d['roi']=d.hit*d.q-1
d['grp']=d.base+'|'+d.half+'|'+d.side+'|'+d.dir
lg=lambda p: np.log(np.clip(p,1e-3,1-1e-3)/(1-np.clip(p,1e-3,1-1e-3)))
d['l_nv']=lg(d.p_nv); d['l_mod']=lg(d.p_mod)
d['hr_own']=d.hr_own.fillna(d.p_mod); d['hr_opp']=d.hr_opp.fillna(d.p_mod)
d['l_own']=lg(d.hr_own*0.8+0.1); d['l_opp']=lg(d.hr_opp*0.8+0.1)
X=['l_nv','l_mod','l_own','l_opp','marg']
tr=d.tag<='2026-10-20'; te=~tr
print('Spiele train',d[tr].ev.nunique(),'test',d[te].ev.nunique())
d['p_fit']=np.nan
for gname,x in d.groupby('grp'):
    a=x[tr.loc[x.index]]; 
    if len(a)<400 or a.hit.nunique()<2: continue
    m=LogisticRegression(C=1.0,max_iter=500).fit(a[X],a.hit)
    d.loc[x.index,'p_fit']=m.predict_proba(x[X])[:,1]
t=d[te & d.p_fit.notna()].copy()
t['ev_edge']=t.p_fit*t.q-1
# nur eine Linie je Spiel+Markt (die mit größtem Edge), damit nicht 5 Linien desselben Markts gezählt werden
print('\nTEST 21.–25.10. (Modell aus 15.–20.10.), je Spiel/Markt nur beste Linie:')
for thr in (0.0,0.03,0.05,0.08,0.12):
    b=t[t.ev_edge>thr].sort_values('ev_edge',ascending=False).drop_duplicates(['ev','grp'])
    b=b[(b.q>=1.3)&(b.q<=2.0)]
    if len(b): print(f" Edge>{thr:.2f}: {len(b)} Wetten, Treffer {b.hit.mean():.0%}, Ø Quote {b.q.mean():.2f}, ROI {b.roi.mean():+.1%}")
# Vergleich: nur Modell p_mod ohne Training
print('\nOhne Training (Formel-Modell p_mod), ganzer Zeitraum, Quote 1.30–2.00:')
for thr in (0.0,0.05,0.1,0.15):
    b=d[(d.p_mod*d.q-1>thr)&(d.q>=1.3)&(d.q<=2.0)].sort_values('p_mod').drop_duplicates(['ev','grp'],keep='last')
    print(f" Edge>{thr:.2f}: {len(b)} Wetten, Treffer {b.hit.mean():.0%}, ROI {b.roi.mean():+.1%}  | train {b[b.tag<='2026-10-20'].roi.mean():+.1%} test {b[b.tag>'2026-10-20'].roi.mean():+.1%}")
# Kalibrierung Modell vs BL: wer sagt besser voraus? (Log-Loss)
from sklearn.metrics import log_loss, brier_score_loss
tt=t.dropna(subset=['p_fit'])
print('\nBrier Test: BL',round(brier_score_loss(tt.hit,tt.p_nv),4),' Formel',round(brier_score_loss(tt.hit,tt.p_mod),4),' Modell',round(brier_score_loss(tt.hit,tt.p_fit),4))
d.to_csv('ds_c.csv',index=False)
