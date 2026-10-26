"""Ereignistabelle: jedes Spiel mit Gelben, Schiri, Teams, Liga, Zeit (aus Stats-Cache + Team-Historien)."""
import json, glob
import pandas as pd
REPO="/home/claude/trend-scanner"; SP="/tmp/claude-0/-home-claude/c3b09894-1e6f-5fae-8b47-559d8ea63d12/scratchpad"
st={}
for f in glob.glob(f"{REPO}/cache/stats/s*.txt"):
    for l in open(f):
        i,_,j=l.partition("\t")
        try: st[i]=json.loads(j)
        except: pass
H=json.load(open(f"{SP}/hist_merged.json"))
for src in (f"{REPO}/cache/history.json", f"{REPO}/cache/exoten_history.json"):
    try:
        for tid,v in json.load(open(src)).items():
            d={e["id"]:e for e in H.get(tid,{}).get("events",[])}
            for e in v.get("events",[]): d[e["id"]]=e
            H[tid]={"events":list(d.values())}
    except Exception as ex: print("skip",src,ex)
ev={}
for tid,v in H.items():
    for e in v["events"]:
        r=ev.setdefault(e["id"],{"id":e["id"],"t":e.get("t"),"lg":e.get("lg"),"l":e.get("l")})
        r["h_id" if e["h"] else "a_id"]=tid
# Archiv-Spiele (Team-IDs aus archiv_teams)
T=json.load(open(f"{REPO}/runs/archiv_teams.json"))
rows=[]
for i,r in ev.items():
    s=st.get(i)
    if not s or "h_id" not in r or "a_id" not in r or not r.get("t"): continue
    y=s.get("yellowcards"); rf=s.get("ref")
    rows.append({"id":i,"t":r["t"],"lg":r["lg"],"h":r["h_id"],"a":r["a_id"],
                 "yh":y[0] if y else None,"ya":y[1] if y else None,"ref":rf[0] if rf else None,
                 "len":s.get("len"),"fh":(s.get("fouls") or [None,None])[0],"fa":(s.get("fouls") or [None,None])[1],
                 "rc":sum(s.get("redcards") or [0,0]) if s.get("redcards") else None})
df=pd.DataFrame(rows)
df["tdt"]=pd.to_datetime(df.t,unit="s")
df.to_csv("karten_ev.csv",index=False)
print(len(df),"Spiele | mit Gelben",df.yh.notna().sum(),"| mit Schiri",df.ref.notna().sum(),"| Zeitraum",df.tdt.min(),df.tdt.max())
print("je Monat:",df.groupby(df.tdt.dt.to_period('M')).size().tail(8).to_dict())
