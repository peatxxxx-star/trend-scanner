# Muster-Analyse 26.10.2026

Reihenfolge (im Ordner ausführen, Pfade in den Skripten anpassen):
1. `build_a.py` – jede BL-Linie (x.5) aus `runs/archiv/bl_*.json.gz` mit Quote, No-Vig-Wahrscheinlichkeit und Ergebnis → `ds_a.csv`
2. `seg.py` / `seg2.py` – Segmentsuche (Markt × Richtung × Wahrscheinlichkeit × Quote × Rolle), muss in 15.–20.10. UND 21.–25.10. positiv sein; `seg2` nur Märkte mit verlässlichen Statistiken
3. `build_b.py` – Vorab-Merkmale je Spiel aus Team-Historien (nur Spiele vor Anstoß; braucht `runs/archiv_teams.json` und die zusammengeführte Team-Historie aus `merge_hist.py`) → `ds_b.csv`
4. `model.py` – logistisches Modell je Markt auf 15.–20.10., Test auf 21.–25.10. gegen die echte BL-Quote

## Karten-Modell (26.10.)
5. `karten_ev.py` → `karten_feat.py` (Merkmale nur aus früheren Spielen: Liga-Schnitt, Team für/gegen, Schiri-Schnitt geschrumpft, Fouls, Pause, Europacup) → `karten_model.py` (Poisson-Regression, trainiert auf Spielen vor 15.10.) → `karten_test.py` (gegen alle BL-Kartenlinien 15.–25.10., je Spiel 1 Tipp)
