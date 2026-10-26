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

## Ecken (26.10. abends)
13. `ecken_feat.py` – Team-Zeilen + Ecken-Ziele + Anteile (Ecken/Schüsse/SaT), Tordifferenz, erwartete Tordifferenz, Dominanz, geblockte Schüsse, Streuung
14. `ecken_stufe1.py` – Zusatzwert je Merkmal + Quintile
15. `ecken_bl.py` – alle BL-Eckenlinien inkl. ganzzahliger Linien (Push)
16. `ecken_model.py <varianten> gbr` – Modelle gegen alle 9 Eckenmärkte (NB-Verteilung, Push berücksichtigt)

## Tore (26.10. abends)
17. `tore_feat.py` – Stärke-Ratings (Angriff/Abwehr, gegnerbereinigt, chronologisch) für Tore, SaT, Schüsse, Ecken + Merkmale aus ecken_voll
18. `tore_model.py <varianten> gbr` – Basis / Rating / Rating+xG-Ersatz / alles gegen alle BL-Torlinien (x.5)
19. `tore_tiefer.py` – Modell-vs-BL-Abweichung, Liga-Trend, Länder-Stabilität, Serie × Modell × Trend, Wochentag/Uhrzeit
20. `serien_tore.py`, `serien_ecken.py` – Serien-Logik mit BL-Quote seit 14.10. (alle Signale / BL-Liste)

## Abseits (26.10. abends)
21. `abseits.py` – Abseits gesamt/Heim/Gast gegen BL (Basis/Netz/+Wettbewerb, Boosting/GLM)
22. `markt_live.py test <metrik>` – generischer Test eines Statistik-Markts (z. B. on_target) mit Live-Merkmalen gegen BL

## Massensuche + Quotenbewegung + bet365 (26.10. abends)
23. `bulk_feat.py` – jede spielbare BL-Linie (Quote 1,30–2,10) in Ecken/Tore/Abseits/Gelb mit ~26 Vorab-Merkmalen (BL-Preis, Team-Historie, Modellabweichung, Zeit, Wettbewerb) → `bulk.parquet`
24. `bulk_search.py [min_spiele] [perm]` – alle Einzel- und Paar-Bedingungen je Marktgruppe (173.000 Segmente), Suche 15.–20., Gegenprobe 21.–25.; mit `perm` = Zufallsprobe (Treffer der Gegenprobe gemischt innerhalb Linie × BL-Wahrscheinlichkeit). Ergebnis: echt 1.216 Überlebende, Zufall 925–1.235 → nichts über Zufall.
25. `bewegung.py` – BL-Quote Archiv (Vormittag) / erste / letzte stündliche Quote vor Anstoß; ROI je Zeitpunkt
26. `b365_vergleich.py` – BL vs. bet365 (BetsAPI-Quotenhistorie aus den Läufen) auf exakt gleicher x.5-Torlinie
27. `b365_alle.py`, `b365_asian.py` – dasselbe für Viertel-/Ganzzahl-Linien (Poisson-Umrechnung bzw. konvertierungsfrei als BL-Kombiwette)
28. `schrumpf.py` – BL-Median je Spiel (Linie bei 50 %) gegen Team-Historie: unterschätzt BL Extreme? (Ecken/Tore/Gelb)
29. `halbzeit.py` – Ecken-Anteil 1. HZ: BL (fast fest 47 %) vs. Historie
30. `verschiebung.py` – BL-Leiter um Historie+Liga-Korrektur verschieben, Schätzung/Test über Kreuz
31. `favorit.py` – Team-Ecken nach Siegchance (BL-1X2): Außenseiter unter / Favorit über bei klaren Favoriten
