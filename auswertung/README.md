# Auswertungen (Claude, ab 24.10.2026)

Skripte hinter den Zahlen, die Lucio im Chat bekommen hat – damit jede Auswertung später reproduzierbar ist.
Aufruf jeweils aus dem Repo-Hauptordner, z. B. `python3 auswertung/tore.py`.

| Skript | Wofür |
|---|---|
| `auswertung.py` | BL-Liste: Treffer/ROI je Markt, Quotenbereich, Hinweis, Tag, Jugend (Basis für 18.10. Marktbeschluss) |
| `tore.py` | wie oben, alle Tage; schreibt `auswertung/rows.json` (Grundlage der Markttabelle) |
| `schwankung.py`, `schwankung_alle.py` | Tages-Schwankung je Markt (Überstreuung vs. Zufall) – 23.10. |
| `ecken_heim.py` | Team-Ecken unter nach Heim/Gast × 1X2-Siegquote – 24.10. |
| `bt_tore3.py` | Offline-Backtest Tore über 1,5 / unter 3,5 + Kreuzvalidierung RECAL_LINE – 23.10. |
| `archiv_tore.py`, `merge_hist.py` | neue Tore-Linien gegen archivierte BL-Quoten – 23.10. |
| `check3er.py`, `auto_check.py` | 3er-Abgleich BL-Liste gegen laufende Scheine (wetten.csv) |
| `scheine_pdf.py` | PDF-Übersicht der Tagesscheine |

Datenquellen: `runs/*.json` (Signale + BL-Quoten je Lauf), `runs/archiv/bl_*.json.gz` (BL-Quotenbild + Ergebnisse),
`runs/ergebnisse_*.json`, `cache/` (Statistik-DB), `wetten.csv` / `spass_wetten.csv` (gespielte Scheine).
Regeländerungen mit Datum und Zahlen: `REGELWERK.md`.
