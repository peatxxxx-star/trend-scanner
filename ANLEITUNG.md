# Fußball-Trend-Scanner — Einrichtung in 15 Minuten

Der Scanner läuft alle 2 Stunden (6–22 Uhr) kostenlos auf GitHub Actions,
prüft alle anstehenden Spiele weltweit gegen dein Regelwerk und schickt
dir Treffer per Telegram aufs Handy. Dein Rechner muss dafür NICHT laufen.

## Schritt 1: Telegram-Bot anlegen (~5 Min)

1. Öffne Telegram und such nach **@BotFather** (blauer Haken!).
2. Schreib ihm `/newbot`, gib einen Namen (z.B. "Mein Trend-Scanner") und
   einen Benutzernamen (muss auf `bot` enden, z.B. `lucio_trends_bot`).
3. BotFather antwortet mit einem **Token** wie `1234567890:AAE-xyz...`
   → das ist dein `TELEGRAM_BOT_TOKEN`. Kopieren und aufheben.
4. Schick deinem neuen Bot eine beliebige Nachricht (wichtig — sonst darf
   er dir nicht schreiben!).
5. Öffne im Browser (ersetze DEIN_TOKEN):
   `https://api.telegram.org/botDEIN_TOKEN/getUpdates`
   In der Antwort steht `"chat":{"id":123456789,...}` — diese Zahl ist
   deine `TELEGRAM_CHAT_ID`.

## Schritt 2: GitHub-Repository anlegen (~5 Min)

1. Account auf https://github.com anlegen (falls noch keiner da ist).
2. Oben rechts **+** → **New repository** → Name z.B. `trend-scanner`,
   Sichtbarkeit **Private**, dann **Create repository**.
3. Auf der leeren Repo-Seite: **uploading an existing file** anklicken und
   ALLE Dateien aus diesem Paket hochladen — wichtig: mitsamt der
   Ordnerstruktur. Falls der Upload den Ordner `.github/workflows/` nicht
   mitnimmt: im Repo **Add file → Create new file**, als Dateinamen
   `.github/workflows/scan.yml` eintippen und den Inhalt der Datei
   hineinkopieren.

## Schritt 3: Geheimnisse hinterlegen (~3 Min)

Im Repo: **Settings → Secrets and variables → Actions → New repository
secret** — drei Stück anlegen:

| Name | Wert |
|---|---|
| `BETSAPI_TOKEN` | dein BetsAPI-Token (Soccer API) |
| `TELEGRAM_BOT_TOKEN` | Token aus Schritt 1.3 |
| `TELEGRAM_CHAT_ID` | Zahl aus Schritt 1.5 |

## Schritt 4: Ersten Lauf starten

Im Repo: Reiter **Actions** → ggf. Workflows aktivieren ("I understand...")
→ links **Trend-Scan** → rechts **Run workflow**. Der erste Lauf dauert
je nach Spieltag 10–30 Minuten (er baut den Statistik-Cache auf; spätere
Läufe sind viel schneller). Treffer kommen als Telegram-Nachricht; wenn es
keine gibt, bleibt das Handy still — im Actions-Log steht es trotzdem.

Danach läuft alles automatisch alle 2 Stunden. Anhalten: Actions →
Trend-Scan → "…"-Menü → **Disable workflow**.

## Was der Scanner genau macht (dein Regelwerk)

- **Zeitfenster:** Läufe um 6, 8, 10, …, 22 Uhr. Jeder Lauf prüft alle
  noch nicht angepfiffenen Spiele bis Mitternacht; der 22-Uhr-Lauf
  reicht bis 6 Uhr früh (Nachtspiele).
- Nur **Gesamtmärkte**: Ecken, Gelbe Karten, Schüsse aufs Tor, Abseits,
  Fouls — jeweils die Spielsumme beider Teams, nie teambezogen.
  Head-to-Head spielt keine Rolle.
- **Serien** werden vom jüngsten Spiel rückwärts gezählt, maximal
  2 Aussetzer — bei der dritten Lücke ist die Serie gebrochen.
- **Anker-Regel:** Mindestens ein Team braucht entweder ≥ 10 Treffer
  ohne Heim/Auswärts-Filter (z.B. "10 der letzten 12") ODER ≥ 15 Treffer
  in seiner heutigen Rolle (Heimteam → letzte Heimspiele, Auswärtsteam →
  letzte Auswärtsspiele; z.B. "15 der letzten 17 Heimspiele").
- **Frische-Regel (nur Anker):** Liegt ein Aussetzer in den jüngsten
  2 gewerteten Spielen der Serie, zählt die Serie nicht.
- **Zweites Team:** ≥ 5 Treffer in dieselbe Richtung, aus der
  Gesamt-Serie oder der Serie seiner heutigen Rolle. Die erlaubten
  Lücken sind gestaffelt: bis 9 Treffer höchstens 1 Lücke, ab
  10 Treffern höchstens 2 (drei Lücken gibt es nie). Beide Teams werden
  getrennt geprüft — scheitert eines an einer Linie, wird das andere
  trotzdem voll ausgewertet.
- **Gegenläufigkeits-Filter:** Zeigt eine Metrik Trends in beide
  Richtungen (z.B. Ecken über 6,5 UND unter 10,5), wird sie komplett
  verworfen — gegenläufige Signale disqualifizieren den Markt.
- **Datenqualität:** Spiele mit verdächtigen Werten (z.B. Fouls 0:0 — in
  echtem Fußball praktisch unmöglich) zählen für die betroffene Metrik
  nicht mit. Ein Signal entsteht nur, wenn beide Teams mindestens
  7 sauber erfasste Spiele für die Metrik haben, und die Meldung zeigt
  immer die echte Datenbasis an ("[Datenbasis 43/38]").
- In der Telegram-Meldung markiert ⚓ die Anker-Serie; "(heim)"/
  "(auswärts)" zeigt an, wenn eine Serie aus der Rollen-Wertung stammt.
- Quoten prüfst du selbst beim Buchmacher deiner Wahl — der Scanner
  meldet nur die Statistik-Signale samt Linie und Richtung.

## Anfragen-Verbrauch

Das Soccer-Abo erlaubt 3.600 Anfragen pro Stunde. Der Scanner hat einen
eingebauten Wächter, der vorher bremst statt in Fehler zu laufen, und
einen dauerhaften Statistik-Cache: Der erste Lauf eines Tages ist der
teuerste (je nach Spieltag einige tausend Anfragen, der Lauf pausiert
dann notfalls selbstständig), danach kosten nur noch neue Spiele etwas.
Der tatsächliche Verbrauch steht nach jedem Lauf im Actions-Log und in
der Protokolldatei unter `runs/`.

## Stellschrauben

Alle Parameter stehen oben in `scan.py` und sind kommentiert:
`ANCHOR_HITS_OVERALL` (10er-Regel), `ANCHOR_HITS_VENUE` (15er-Regel),
`ANCHOR_MAX_MISSES` (2er-Puffer), `FRESH_GAMES` (Frische-Regel),
`OTHER_HITS`/`OTHER_MAX_MISSES` (zweites Team), `MIN_VALID_MATCHES`
(Mindest-Datenbasis), `HISTORY_DEPTH` (geladene Spiele pro Team) sowie
die Linienbereiche je Markt in `METRICS`. Nach einer Änderung einfach
die Datei im Repo bearbeiten und committen — der nächste Lauf nutzt sie
automatisch.

## Protokolle & Beweissicherung

Jeder Lauf legt unter `runs/` eine JSON-Datei mit Zeitstempel, allen
Treffern und der Anfragezahl ab. Wenn ein Trend später "verschwindet",
kannst du hier nachweisen, was wann galt. Der Ordner `cache/` speichert
Statistiken abgeschlossener Spiele dauerhaft — dadurch sinkt der
API-Verbrauch von Lauf zu Lauf deutlich (Limit: 3.600 Anfragen/Stunde,
der Scanner bleibt nach dem ersten Tag weit darunter).
