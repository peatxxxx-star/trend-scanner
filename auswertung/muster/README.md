# Muster-Analyse 26.10.2026

Reihenfolge (im Ordner ausführen, Pfade in den Skripten anpassen):
1. `build_a.py` – jede BL-Linie (x.5) aus `runs/archiv/bl_*.json.gz` mit Quote, No-Vig-Wahrscheinlichkeit und Ergebnis → `ds_a.csv`
2. `seg.py` / `seg2.py` – Segmentsuche (Markt × Richtung × Wahrscheinlichkeit × Quote × Rolle), muss in 15.–20.10. UND 21.–25.10. positiv sein; `seg2` nur Märkte mit verlässlichen Statistiken
3. `build_b.py` – Vorab-Merkmale je Spiel aus Team-Historien (nur Spiele vor Anstoß; braucht `runs/archiv_teams.json` und die zusammengeführte Team-Historie aus `merge_hist.py`) → `ds_b.csv`
4. `model.py` – logistisches Modell je Markt auf 15.–20.10., Test auf 21.–25.10. gegen die echte BL-Quote

## Karten-Modell (26.10.)
5. `karten_ev.py` → `karten_feat.py` (Merkmale nur aus früheren Spielen: Liga-Schnitt, Team für/gegen, Schiri-Schnitt geschrumpft, Fouls, Pause, Europacup) → `karten_model.py` (Poisson-Regression, trainiert auf Spielen vor 15.10.) → `karten_test.py` (gegen alle BL-Kartenlinien 15.–25.10., je Spiel 1 Tipp)

## Spinnennetz (26.10.)
6. `netz_feat.py` – je Spiel und Team Mittel für/gegen von Ecken, Gelben, Toren, SaT, Torschüssen, Fouls, Abseits, HZ-Ecken über 3/5/10/15 Spiele (gesamt) und 5/10 (Rolle), nur Spiele vor Anstoß → `netz.parquet`
7. `netz_stufe1.py` – Zusatzwert jedes Merkmals über das Basismodell (Teamschnitt im selben Markt + Liga + Heim), Korrelation mit dem Rest bis 30.09. vs. ab 01.10.
8. `netz_stufe2.py` / `netz_karten.py` – Basis- vs. Spinnennetz-Modell (Poisson, Training vor 15.10.) gegen BL-Linien 15.–25.10.

## Karten komplett (26.10. nachmittags)
9. `karten_voll_feat.py` – Team-Zeilen mit Spinnennetz + H2H (letzte 6 Duelle) + Schiri + Wettbewerb (Pokal/Europa/Jugend) + Pause/Europacup + Monat; Ziele Spiel/1. HZ/2. HZ
10. `karten_voll_model.py <varianten> gbr|glm` – Boosting (Poisson) bzw. Poisson-GLM, Training vor 15.10., gegen alle 9 BL-Kartenmärkte
11. `kv_robust.py` – Schwellen, Quotenbänder, Richtung, Markt, Land, Bootstrap
12. `kv_final.py` – Mittel aus Boosting + GLM (netz+wettb), nur Spiel-Märkte, Edge > 5 %, Quote 1,30–2,00, 1 Tipp je Spiel; Einzel/2er/3er
