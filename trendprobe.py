"""Serienfreie Suche für deutsche Spiele heute (1./2./3. Liga)."""
import sys, json, time
from pathlib import Path
import betlabel
alle = betlabel.lade_spiele()
jetzt = time.time()
fenster = [g for g in alle if jetzt < g["S"] < jetzt + 14 * 3600]
ligen = sorted({g.get("L") or "" for g in fenster})
Path("runs/trendscan/probe.json").write_text(json.dumps({"n": len(alle), "fenster": len(fenster),
    "ligen_de": [l for l in ligen if "erman" in l or "eutsch" in l], "beispiel": ligen[:40]}, ensure_ascii=False, indent=1))
sys.argv = ["ohneserie.py", r"^Germany\. (Bundesliga|2\. Bundesliga|3\. Liga)$", "14"]
import ohneserie
ohneserie.main()
