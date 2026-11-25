"""Test: Auswertung 25.11. (trocken) + ein trockener Scan im Papier-Modus."""
import os, json
os.environ["TS_TROCKEN"] = "1"
from datetime import date
from pathlib import Path
import trendscan as T, auswertung as A
T.TROCKEN = True
text, zeilen = A.tagesauswertung(date(2026, 11, 25), T.TZ, T.markt_aus_typ)
Path("runs/trendscan/probe.json").write_text(json.dumps({"text": text, "n": len(zeilen)}, ensure_ascii=False, indent=1))
print(text)
T.main()
