"""Alle BL-Eckenlinien (x.5 und ganzzahlig) mit Ergebnis: Sieg/Push/Verlust."""
import json, glob, gzip, re, csv
REPO="/home/claude/trend-scanner"
rows=[]
for f in sorted(glob.glob(f"{REPO}/runs/archiv/bl_*.json.gz")):
    tag=re.search(r"bl_(\d{4}-\d{2}-\d{2})",f).group(1)
    for g in json.load(gzip.open(f,"rt"))["spiele"]:
        e=g.get("erg"); ev=g.get("ev")
        if not e or not ev or e.get("len") not in (None,90): continue
        sw=bool(g.get("swap")); c=e.get("corners"); h=e.get("ht_corners")
        x=g.get("x12") or {}
        try:
            s=1/float(x["1"])+1/float(x["2"])+1/float(x["3"]); p1=(1/float(x["1"]))/s; p2=(1/float(x["3"]))/s
        except Exception: p1=p2=None
        gl=(g["m"].get("goals") or {})
        try: pg=(1/gl["o2.5"])/((1/gl["o2.5"])+(1/gl["u2.5"]))
        except Exception: pg=None
        for k,lad in g["m"].items():
            m=re.match(r"^corners(_h1|_h2)?(_heim|_gast)?$",k)
            if not m: continue
            half=m.group(1) or "ft"; side=m.group(2) or "tot"
            if half=="ft": pr=c
            elif half=="_h1": pr=h
            else: pr=[c[0]-h[0],c[1]-h[1]] if c and h and None not in c+h else None
            if not pr or pr[0] is None or pr[1] is None or min(pr)<0: continue
            if side=="tot": val=pr[0]+pr[1]
            else:
                i=0 if side=="_heim" else 1
                if sw: i=1-i
                val=pr[i]
            for lk,q in lad.items():
                L=float(lk[1:]); d=lk[0]
                if abs(L*2-round(L*2))>1e-9: continue          # nur .0 und .5
                opp=lad.get(("u" if d=="o" else "o")+lk[1:])
                pnv=(1/q)/((1/q)+(1/opp)) if opp else None
                if val==L: res="push"
                else: res="win" if ((val>L) if d=="o" else (val<L)) else "loss"
                roi=(q-1) if res=="win" else (0.0 if res=="push" else -1.0)
                rows.append(dict(tag=tag,ev=ev,bl_liga=g.get("L"),swap=int(sw),half=half,side=side,dir=d,line=L,q=q,p_nv=pnv,
                                 p1=p1,p2=p2,pg25=pg,val=val,res=res,roi=roi,ganz=int(L==int(L))))
with open("ecken_bl.csv","w",newline="") as fh:
    w=csv.DictWriter(fh,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(len(rows),"Linien",len({r['ev'] for r in rows}),"Spiele")
