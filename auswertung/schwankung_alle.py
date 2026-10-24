import json, math
from collections import defaultdict
rows=json.load(open("auswertung/rows.json"))
pl=rows
NAME={"yellowcards unter":"Gelbe unter","yellowcards über":"Gelbe über","Team-corners unter":"Team-Ecken unter","Team-corners über":"Team-Ecken über",
"offsides unter":"Abseits unter","corners über":"Ecken über","corners unter":"Ecken unter","goals über":"Tore über 2.5","on_target über":"SaT über",
"Team-yellowcards unter":"Team-Gelbe unter","fouls über":"Fouls über","Team-fouls über":"Team-Fouls über","ht_yellowcards über":"1.HZ Gelbe über"}
by=defaultdict(lambda: defaultdict(list))
for r in pl: by[r["markt"]][r["tag"]].append(r)
out=[]
for mk,days in by.items():
    rs=[r for d in days.values() for r in d]; n=len(rs)
    if n<30: continue
    h=sum(r["hit"] for r in rs); p=h/n; aq=sum(r["q"] for r in rs)/n; roi=sum(r["q"] for r in rs if r["hit"])/n-1
    # Überstreuung: beobachtete Varianz der Tagestreffer vs. Binomial
    num=sum((sum(r["hit"] for r in d)-len(d)*p)**2 for d in days.values()); den=sum(len(d)*p*(1-p) for d in days.values())
    disp=num/den if den else float("nan")
    dr=[(t,sum(r["hit"] for r in d)/len(d),len(d), sum(r["q"] for r in d if r["hit"])/len(d)-1) for t,d in days.items() if len(d)>=3]
    worst=min(dr,key=lambda x:x[1]) if dr else None
    minus=sum(1 for x in dr if x[3]<0)
    out.append((NAME.get(mk,mk),n,len(days),p,1/aq,roi,disp,worst,minus,len(dr)))
for o in sorted(out,key=lambda o:o[6]):
    w=f"{o[7][0]}: {o[7][1]:.0%} (n={o[7][2]})" if o[7] else "-"
    print(f"{o[0]:18s} n={o[1]:3d} Tage={o[2]:2d} Treffer {o[3]:.0%} nötig {o[4]:.0%} ROI {o[5]:+.0%}  Schwankung×Zufall {o[6]:.2f}  schlechtester Tag {w}  Tage im Minus {o[8]}/{o[9]}")
