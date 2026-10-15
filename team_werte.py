"""Letzte Pflichtspiele eines Teams aus cache/history.json + stats.json.gz
(für Claudes Zweitprüfung). Teamsuche unscharf: "KuPS" findet "KuPS Kuopio",
"Manchester City" findet "Man City" (15.10., Lucio: nicht an Namen scheitern).
Aufruf: python3 team_werte.py "Teamname" ["Teamname" ...]"""
import gzip, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import scan, betlabel

R = Path(__file__).parent
H = json.load(open(R / "cache/history.json"))
S = json.load(gzip.open(R / "cache/stats.json.gz"))
MK = ["goals", "corners", "yellowcards", "on_target", "offsides", "fouls"]


def finde(name):
    beste, best_sc = None, 0.0
    for tid, v in H.items():
        ev = v.get("events") or []
        if len(ev) < 5:
            continue
        sc = 0.0
        for e in ev[:10]:
            hm, aw = (e["l"].split(" - ", 1) + [""])[:2]
            seite = (hm if e["h"] else aw).strip()
            s = betlabel.name_score(name, seite)
            if s >= 0.6:
                sc += s + (0.5 if seite.lower() == name.lower() else 0)
        if sc > best_sc:
            beste, best_sc = tid, sc
    return beste if best_sc >= 3 else None


def zeige(name, n=10):
    tid = finde(name)
    if not tid:
        print(f"?? {name} nicht gefunden")
        return
    ev = [e for e in H[tid]["events"] if not scan.is_friendly(e.get("lg"))][:n]
    print(f"\n== {name} (ID {tid}) – Spalten: Tore Ecken Gelb SaT Abseits Fouls (eigen-gegner)")
    for e in ev:
        st = S.get(e["id"]) or {}
        row = []
        for m in MK:
            p = st.get(m)
            if p is None or (m in ("on_target", "fouls", "offsides") and p == [0, 0]):
                row.append("  -  ")
            else:
                own, opp = (p[0], p[1]) if e["h"] else (p[1], p[0])
                row.append(f"{own}-{opp}".rjust(5))
        print(" ", e["l"][:34].ljust(34), (e.get("lg") or "")[:16].ljust(16), " ".join(row))


if __name__ == "__main__":
    for n in sys.argv[1:]:
        zeige(n)
