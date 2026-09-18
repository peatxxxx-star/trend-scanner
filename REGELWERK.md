# Trend-Scanner — aktueller Stand (06.09.2026, abends)

Schritt für Schritt, was das Skript macht. Reihenfolge = tatsächliche Verarbeitungsreihenfolge im Lauf.

---

## 1. Ablauf und Daten

**Läufe (deutsche Sommerzeit):**
- Berichte **stündlich** von 06:17 bis 21:17 (10.09.: vorher alle zwei Stunden bis 20:17 — Nebenmärkte werden oft erst kurz vor Anpfiff veröffentlicht, jede spätere Stunde bringt zusätzliche Märkte). Ab dem 20-Uhr-Lauf reicht das Prüffenster bis **09:00 früh** (Nacht- und Frühspiele), der **21:17-Lauf ist der letzte des Tages**.
- **Freitag und Samstag** noch ein Lauf um **22:05** — gleiches Fenster (bis 09:00 früh), aber näher am Anpfiff der Abend-/Nachtspiele.
- Nachtläufe 23:17, 01:17, 03:17, 05:17: laden nur die Statistiken der Teams des NÄCHSTEN Tages in den Cache, kein Bericht. Jeder hört am API-Stundenlimit auf, der nächste macht weiter.
- Ein Bericht wartet NIE am API-Limit: Spiele, die nicht mehr drankommen, stehen als "⏳ … verschoben" im Kopf und der nächste Lauf holt sie nach.

**Datenquelle:** BetsAPI Soccer API. Für jedes Team werden die letzten 50 beendeten Spiele mit Statistiken geladen (alle Wettbewerbe, auch Testspiele). Die Spielliste eines Teams gilt 12 Stunden.

**Cache (Tagesspeicher):** komprimiert (`cache/stats.json.gz`), enthält nur, was in den letzten 30 Tagen gebraucht wurde. Einträge aus einer alten Skript-Version bleiben liegen und werden nach und nach aufgefrischt, sobald ein Team drankommt (11.09.: früher wurden sie sofort verworfen — das riss die halbe Historie weg). Fehlende Spiele werden vor veralteten geholt. Kein Dauerarchiv mehr.

**Fouls — gestrichen (12.09.):** Im Backtest war das Modell dort systematisch zu optimistisch: es sagte 82 % Trefferwahrscheinlichkeit (faire Quote 1,22), tatsächlich waren es 76 % (faire Quote 1,32). Eine Buchmacher-Quote von 1,28 sieht damit nach Value aus und ist keiner. Das deckt sich mit Lucios echter Historie (Fouls 9/15, schwächster Markt). Der Fehler blieb in allen Filtervarianten bestehen, war also kein Selektionsproblem. Die Foul-Zahlen werden weiter gecacht (Schiedsrichter-Profil, Datenqualität). Zum Wiedereinschalten: die beiden `fouls`-Zeilen aus `EXCLUDED_MARKETS` entfernen.

**Schüsse gesamt — gestrichen (11.09.):** Zuerst fiel auf, dass das API-Feld `goalattempts` nur Schüsse aufs Tor + daneben zählt, nicht die geblockten (Ø 16,6 statt ~25 pro Spiel; 342 von 342 Signalen waren "unter"). Auch mit korrigierter Zählung (geblockte addiert) decken sich die Einzelwerte nicht mit Flashscore bzw. der Abrechnung des Buchmachers. Der Markt ist deshalb über `EXCLUDED_MARKETS` komplett gesperrt. Die Zahlen werden weiter mitgespeichert, gemeldet wird nichts. Zum Wiedereinschalten: die beiden `shots_total`-Zeilen in `EXCLUDED_MARKETS` entfernen.

**Backtest-Modus (11.09.):** Actions → Run workflow → Modus `backtest`, optional ein Datum (JJJJ-MM-TT, leer = gestern). Nimmt alle beendeten Spiele des Tages (max. 150 je Lauf), baut für beide Teams die Historie **nur aus Spielen vor dem jeweiligen Anstoß** nach, lässt das Regelwerk laufen und vergleicht jedes Signal mit dem tatsächlichen Ergebnis. Ausgabe: Trefferquote gesamt und je Markt, Vergleich mit der Modell-Wahrscheinlichkeit (Kalibrierung), Trefferquote nach p-Klassen und eine Liste der danebengegangenen grünen Signale. Grenzen: der scores24-Nachweis lässt sich rückwirkend nicht nachstellen (der Backtest sieht also auch Signale, die live rausgeflogen wären), historische Quoten gibt es nicht (gemessen wird die Trefferquote, nicht die Rendite), und der Schiedsrichter-Zuschlag fehlt.

**Prüfmodus "schuesse":** Actions → Run workflow → Modus `schuesse` gibt für 60 beendete Spiele die Rohfelder aus (aufs Tor / daneben / geblockt / goalattempts). Damit lässt sich jederzeit gegen Flashscore prüfen, ob die Grundlage inzwischen stimmt.

**Spielplan:** alle Fußballspiele weltweit im Zeitfenster, ohne eSoccer. Reserve-, U- und Frauenteams sind NICHT ausgeschlossen. Keine Liga-Beschränkung für irgendeinen Markt.

---

## 2. Märkte, Linien, Quellen

| Markt | Richtungen | Linien | Datenquelle | Korridor (nur falls Sperre wieder an) | scores24-Reiter (Nachweis) |
|---|---|---|---|---|---|
| Ecken | nur über | 7,5 – 12,5 | Spielstatistik `corners` | 2 Linien | Ecken |
| Gelbe Karten | über / unter | 2,5 – 6,5 | `yellowcards` | 1 Linie | Karten |
| ~~Schüsse aufs Tor~~ | **komplett gestrichen (15.09.)** | – | – | – | – |
| ~~Schüsse gesamt~~ | **gestrichen (11.09.)** | – | – | – | – |
| ~~Abseits~~ | **gestrichen (15.09.)** | – | – | – | – |
| ~~Fouls~~ | **gestrichen (12.09.)** | – | – | – | – |
| 1. HZ Ecken | **nur über** (wieder frei 15.09.) | 3,5 – 6,5 | `corner_h` | 1 Linie | Ecken |
| 1. HZ Gelbe Karten | über / unter (**ohne unter 2,5**, gesperrt 15.09.) | 0,5 – 2,5 | aus dem Ereignis-Verlauf | 1 Linie | Karten |

Immer nur **Gesamtmärkte** (Summe beider Teams). "Unter Ecken" ist ausgeschlossen, "Ecken über 6,5" gibt es nicht mehr, 1. HZ Ecken sind komplett gestrichen (13.09.: 6/12 über zwei Wochen, im Backtest der schwächste Markt — die erste Halbzeit ist zu kurz, da entscheidet der Zufall). Head-to-Head spielt keine Rolle.

**Cache-Fassung 5 (15.09.) — wichtige Korrektur der Logik:** Neue Felder (Endstand, Halbzeit-Tore, Paraden, Einwürfe, Abstöße, Freistöße) wurden zwar ab sofort mitgespeichert, aber bereits gecachte Spiele blieben unverändert — sie galten als "aktuell", weil die Cache-Fassung nicht hochgezählt wurde. Folge: In den Live-Historien hatten nur ~20 % der Spiele einen Endstand, und die Tor-Märkte lösten nie aus.

Seit 15.09. ist `CACHE_VERSION = 5` und `CACHE_OK_VERSIONS = {5}`: Ältere Einträge bleiben gültig und im Cache (für Ecken/Karten/Abseits ändert sich nichts), werden aber automatisch aufgefrischt, sobald das jeweilige Team wieder drankommt — `fetch_team_history` holt fehlende Spiele zuerst und veraltete danach, und der Anfragen-Wächter bremst vor dem Stundenlimit. Damit sich kein Lauf aufbläht, werden je Team und Lauf höchstens `STALE_PER_TEAM = 20` veraltete Spiele nachgeladen — die Serienregeln schauen ohnehin nur auf die letzten ~15 Spiele, und der Rest folgt im nächsten Lauf. Rechnung beim Umstieg: 564 Teams, rund 10.700 Spiele im ersten Durchgang = ~1.070 zusätzliche Anfragen, also etwa eine Minute mehr Laufzeit bei 24 Arbeitern und weit unter dem Stundenlimit von 3.300. Zusätzlich frischt der Modus `nachladen` gezielt die Teams von heute und morgen auf.

**Stand 15.09., später Abend (Lucio):** Kernsystem = **Ecken über · Gelbe Karten über/unter · 1. HZ Ecken über · 1. HZ Gelbe Karten über/unter (ohne unter 2,5)**. Abseits ist gestrichen, Schüsse aufs Tor ebenfalls; 1. HZ Ecken über ist wieder frei (unter bleibt raus). Getrennt gemeldet als Test: Tore gesamt, Einwürfe, Abstöße, Freistöße. Bonus und Team-Märkte sind komplett aus. Schalter: `EXCLUDED_MARKETS` (ganze Märkte) und `EXCLUDED_LINES` (einzelne Linien).

---

## 3. Datenqualität (gilt je Spiel und Markt)

- Fehlende Statistik → das Spiel zählt für diesen Markt nicht (weder Treffer noch Aussetzer).
- Fouls 0:0 → gilt als "nicht erfasst": macht das Spiel für Abseits ungültig (Fouls selbst sind als Markt gestrichen, die Zahlen werden nur noch für Schiedsrichter-Profil und Datenqualität genutzt).
- Schüsse aufs Tor 0:0 bzw. Schüsse gesamt 0:0 → ungültig für den jeweiligen Markt.
- Halbzeit-Karten: nur wenn der Ereignis-Verlauf einen Halbzeit-Marker hat, sonst ungültig.
- Ein Team braucht je Markt **mindestens 7 gültige Spiele**, sonst gibt es für diesen Markt kein Signal.

---

## 4. Serienregeln (identisch für alle Märkte)

Serien werden vom jüngsten Spiel rückwärts gezählt. **Dritte Lücke = Serie gebrochen.**

**Anker (mindestens ein Team muss Anker sein):**
- ≥ 10 Treffer mit max. 2 Lücken, alle Spiele ohne Heim/Auswärts-Filter (10/11, 10/12, 12/14 …), **oder**
- ≥ 15 Treffer mit max. 2 Lücken nur in der heutigen Rolle (Heimteam → seine Heimspiele, Auswärtsteam → seine Auswärtsspiele).
- **Frische-Regel:** liegt eine Lücke in den jüngsten 2 gewerteten Spielen, ist die Anker-Serie ungültig.

**Zweites Team:**
- ≥ 5 Treffer mit max. 1 Lücke, wahlweise aus allen Spielen oder aus der heutigen Rolle.
- Gestaffelt: ab 10 Treffern sind 2 Lücken erlaubt.
- Frische-Regel gilt hier NICHT.

Beide Teams werden getrennt geprüft. Signal = beide erfüllen dieselbe Linie in dieselbe Richtung, mindestens einer ist Anker.

---

## 5. Linienauswahl und Gegenbewegung

- Je Markt und Richtung wird nur die **strengste** erfüllte Linie gemeldet (über: höchste, unter: niedrigste).
- **Gegenbewegung: abgeschaltet (12.09., Variante C).** Es wird gar nicht mehr auf gegenläufige Serien geprüft. Grund: an 4.665 grünen Signalen aus dem Cache verglichen — und zwar nicht nach Trefferquote, sondern nach der Frage, ob die faire Quote hält ("Rendite, wenn man immer exakt die faire Quote bekäme"):

| Variante | Signale | Rendite zur fairen Quote |
|---|---|---|
| bisherige Korridor-Sperre | 4.103 | −0,34 % |
| nur Gegen-Signale (beide Teams gegenläufig) | 3.525 | +0,09 % |
| **keine Sperre** | **4.665** | **−0,50 %** |

Die drei liegen 0,6 Punkte auseinander, also im Rauschen — mehr Signale bedeuten dagegen mehr Gelegenheiten, beim Buchmacher eine Quote über fair zu finden. Zum Wiedereinschalten: `CONTRA_ENABLED = True` in `scan.py`; die alte Korridor-Logik inklusive `CONTRA_ANCHOR_ONLY` liegt unverändert daneben.
- Zeigt eine Metrik voll qualifizierte Signale in beide Richtungen im engen Korridor, fliegt die Metrik komplett.

---

## 6. Verfügbarkeits-Nachweis (nur scores24)

Ein Signal bleibt nur, wenn **scores24** für das Spiel den Reiter der **Marktfamilie** mit Quoten kennt (Spalte rechts in Tabelle 2): Ecken-Reiter für Ecken und HZ-Ecken, Karten-Reiter für Karten und HZ-Karten, Schüsse-Reiter für Schüsse aufs Tor und Schüsse gesamt, Abseits- bzw. Fouls-Reiter entsprechend.

- Das ist nur eine **Verfügbarkeits-Näherung**. Die scores24-Quotenspannen werden **nirgends** als Wert benutzt — nicht für fair, nicht für die Entscheidung.
- Der bet365-Nachweis ist **abgeschaltet** (Quoten weichen zu stark ab). Die bet365-Linie für Ecken/HZ-Ecken wird nur noch intern zur Erwartungs-Berechnung genutzt, nie angezeigt.
- Kein scores24-Reiter → Signal raus.

**Seiten-Zuordnung bei scores24:** Teamnamen werden unscharf abgeglichen, aber Mannschafts-Zusätze müssen exakt passen (B, II, 2, Reserves, III, U17–U23, (W)/Women/Frauen, Youth/Academy). Ein B-Team landet nie auf der Seite der ersten Mannschaft. Findet der Scanner keine passende Seite → wie "kein Nachweis".

---

## 7. Kennzahlen (für die Entscheidung, alles aus den geladenen Spielen)

**Gewichtung der Historie** (nur für Kennzahlen, nicht für die Serienregeln): die jüngsten 10 Spiele voll, danach halbiert sich das Gewicht alle 15 Spiele. Spiele mit Platzverweis zählen halb, Spiele mit Verlängerung (120 Min.) zählen halb.

**Historie-Wahrscheinlichkeit:** gewichtete Trefferquote der Linie über die Spiele beider Teams, zur Grundrate aller gecachten Spiele hin gedämpft (Gewicht 20 "neutrale" Spiele).

**Erwartung (erwartete Spielsumme):** Mittel aus zwei Modellen:
- Summen-Modell: Ø der Spielsummen — Heimspiele des Heimteams und Auswärtsspiele des Gastteams (Fallback: alle Spiele).
- Beitrags-Modell: (Heim holt selbst × Gast lässt zu) + (Gast holt selbst × Heim lässt zu), jeweils relativ zum Schnitt aller gecachten Spiele je Team. Erkennt, ob beide Serien vom selben Erzeuger stammen.

**Schiedsrichter** (nur Karten, HZ-Karten, Fouls): Ist der Schiri angesetzt, wird die Erwartung mit seinem Faktor skaliert (sein Schnitt ÷ Schnitt aller Spiele, bei wenigen Spielen zu 1 hin gedämpft mit 8 neutralen Spielen). Sein Profil kommt aus dem Cache — mit dem Tagesspeicher ist es entsprechend kleiner als früher.

**Modell-Wahrscheinlichkeit:** aus Erwartung und Streuung (gewichtete Standardabweichung der Spielsummen beider Teams, Normalverteilung).

**Kombiniert:** p = Mittel aus Historie und Modell. **Faire Quote = 1 / p.**

---

## 8. Entscheidung

**Kein Vorfilter mehr:** Die faire Quote begrenzt nichts (MIN_FAIR aus). Jeder ✅-Markt wird gemeldet, egal wie tief fair liegt — Lucio vergleicht selbst mit der Bookie-Quote und spielt nur, wo sie über fair UND ≥ 1,30 liegt.

**✅ spielen**, wenn alles zutrifft:
- kombinierte Wahrscheinlichkeit ≥ 68 %
- Historie und Modell nicht mehr als 12 Punkte auseinander
- Puffer ≥ 0 (Erwartung auf der richtigen Seite der Linie)
- falls intern eine bet365-Linie exakt vorliegt (nur Ecken/HZ-Ecken): Erwartungswert ≥ +3 %

**❌ nicht spielen** (wird nicht angezeigt), u. a. bei: p < 58 %, Erwartung klar auf der falschen Seite (mehr als eine halbe Streuung), Historie/Modell > 25 Punkte auseinander, exakte bet365-Quote deutlich unter fair, oder eines der ✅-Kriterien knapp verfehlt.

---

## 9. Anzeige (Telegram)

- Jede Nachricht zeigt **alle ✅-Märkte des Tages**, die noch nicht angepfiffen sind. Neue seit dem letzten Lauf tragen 🆕.
- **Sortierung: Zeit zuerst, Ligen gruppiert** (15.09., ersetzt die Liga-Block-Sortierung vom 12.09.): Die Liste ist **streng chronologisch nach Anstoßzeit**. Spiele mit **derselben** Anstoßzeit stehen nach Liga zusammen (Sortierschlüssel `(kickoff_ts, liga, heim)`), damit man einen 15:30-Block im Konto Liga für Liga abarbeiten kann, ohne dass ein späteres Spiel derselben Liga die Reihenfolge nach vorne zieht. Gilt für die Hauptliste, die Abschlussliste und den Extra-Block. Im Selbsttest abgesichert (Fall 18).
- Je Markt: Kopfzeile (Markt, Linie, Fair) + Serien beider Teams (⚓ = Anker, "heim"/"auswärts" = Rollen-Serie). Keine Leiter, keine ❌-Märkte, keine Spielliste am Ende.
- Was einmal drin war, bleibt bis zum Anpfiff drin — auch wenn ein späterer Lauf keine Quoten mehr findet oder die Serie kippt.
- Grüner Balken oben / roter Fuß unten je Nachricht, "Teil x/y" bei mehreren. Gibt es nichts Grünes: gelber Einzeiler.
- Kopfzeile: "✅ N spielbar heute · 🆕 M neu seit letztem Lauf", ggf. "⏳ X Spiele wegen API-Limit verschoben".
- Das Tagesgedächtnis wird nur gespeichert, wenn Telegram die Nachricht bestätigt hat.

---

## 10. Sonstiges

- **Nachladen** (Actions → Run workflow → Modus "nachladen"): lädt nur die Historien der Teams von heute und morgen komplett neu. Normalerweise unnötig — die Nachtläufe erledigen das von selbst.
- Stellschrauben stehen oben in `scan.py`: Serienparameter, `METRICS` (Linien), `EXCLUDED_MARKETS`, Korridore je Markt (`CONTRA_GAP_BY_METRIC`), `MIN_FAIR`, `CONTRA_ENABLED` (Gegenbewegungs-Sperre, aktuell aus), Ampel-Schwellen (`GREEN_MIN_P`, `AGREE_OK`, …), Gewichtung, `CACHE_KEEP_DAYS`, `B365_AS_PROOF`.
- Zeitumstellung 25.10.: Cron-Zeiten in `scan.yml` um eine Stunde schieben (Kommentare dort nennen die Winter-Werte).

## 9. Bonus-Picks (Samstag + Sonntag, 12.–13.09.) — VERWORFEN

> **13.09., endgültig:** Der Bonus ist komplett verworfen ("bindet mich zu sehr für zu wenig Ertrag"). Beide Bonus-Bausteine sind abgeschaltet (`BONUS_DAYS = set()`): keine 1X2-Liste, keine 🥇-Siegwetten, keine Quoten-Abfragen. Der Code bleibt drin, Abschnitte 9 und 11 gelten nur noch als Doku. Gründe aus der Analyse: nach den Bedingungen (100 % der Einzahlung bis 100 €, 3× Umsatz in 24 h in 3er-Kombis ≥ 1,40, Gesamtzahl/Handicap ausgeschlossen, Auszahlung bis max. Bonusbetrag) ist im Erwartungswert nur 40–70 € je Wochenende drin, jedes zweite Mal die vollen 100, jedes dritte Mal nichts; dafür ein ganzer Samstag in 5–6 Abrechnungswellen, Kontosperre für Auszahlungen während der 24 h, und die Klausel "vor einer Einzahlung keine Auszahlungen" kollidiert mit dem Freitags-Zyklus. Siegwetten ("wer hat mehr") empfindet Lucio ohnehin als Würfeln.

Lucio bekommt als Stammkunde jeden Samstag **100 € Bonusguthaben** bei BetLabel. Bedingungen: innerhalb von **24 Stunden das 3-fache (300 €) in Akkumulatoren** mit mindestens 3 Auswahlen umsetzen, davon **3 Auswahlen mit Quote ≥ 1,40**. Wetten auf **Gesamtzahlen und Handicaps zählen nicht** — also genau seine komplette normale Strategie. Nach erfülltem Umsatz wandert das restliche Bonusguthaben **bis maximal 100 €** aufs Hauptkonto.

**Wichtig zur Einordnung:** Hier gibt es keinen Vorteil aus Serien. 1X2 ist der am schärfsten bepreiste Markt; der Vorteil kommt allein daraus, dass das Bonusgeld geschenkt ist. Die Aufgabe lautet deshalb nicht "welcher Pick gewinnt", sondern **"welcher Umsatz kostet am wenigsten Marge"**.

**Rolle der Liste (12.09. nachgeordnet):** Seit es die 🥇-Siegwetten in den Nebenmärkten gibt (Abschnitt 11), ist die 1X2-Liste nur noch **Lückenfüller**. Die Bonus-Beine kommen zuerst aus 🥇 (dort gibt es einen Modellvorteil und sie zählen genauso für den Umsatz); 1X2 füllt auf, wenn nicht genug Beine über 1,40 zusammenkommen. Angezeigt werden deshalb nur noch 8 Einträge.

**Was der Scanner liefert** (an Sa/So in jedem Lauf, als separate Telegram-Nachricht mit 🎁 markiert):

- Spiele, die in den nächsten 14 Stunden anpfeifen, mit bet365-Quoten für 1X2 (API-Markt `1_1`, 1 Anfrage je Spiel, 2 Stunden zwischengespeichert in `cache/odds1x2.json`, max. 400 Abfragen je Lauf)
- die **Marge** je Spiel: `1/Quote1 + 1/QuoteX + 1/Quote2 − 1` — reine Arithmetik, sortiert nach der günstigsten
- je Spiel **genau EINE Empfehlung** (12.09. nachgeschärft — 1X und X2 beim selben Spiel sind Gegenseiten und widersprachen sich): gewählt wird die Auswahl mit der **niedrigsten** erwarteten Bookie-Quote, die noch über der Schwelle liegt, denn niedrigste Quote = höchste Trefferchance = kleinste Schwankung beim Umsetzen. Value gibt es hier nicht zu holen. Kandidaten sind Sieg/Remis und Doppelte Chance (1X, 12, X2, aus denselben entmargten Wahrscheinlichkeiten abgeleitet). **Filter (12.09. nachgeschärft):** entscheidend ist nicht die faire Quote, sondern die **erwartete Buchmacher-Quote** = fair ÷ (1 + Marge). Die Bedingung verlangt ≥ 1,40; in Frage kommt nur, was voraussichtlich darüber landet (`BONUS_MIN_BOOKIE` = 1,38 als Toleranz), obere Grenze fair 1,85. Die bet365-Rohquote steht nicht mehr in der Anzeige (es gibt sie nur für Sieg/Remis, nicht für Doppelte Chance — das sah nach Qualitätsunterschied aus, war aber nur eine Datenlücke); sie bleibt in `runs/` protokolliert. Vorher stand eine reine Fair-Untergrenze von 1,42 drin — dabei landeten Auswahlen in der Liste, die beim Bookie bei ~1,35 herauskommen und damit nicht für den Umsatz zählen.

**Simulation der Umsatzbedingung** (200.000 Durchläufe, Start 100 €, Ziel 300 € Umsatz, Scheine 3 × 1,40 = 2,744, Auszahlung gedeckelt bei 100 €):

| Abrechnungswellen | Scheine je Welle | Umsatz erfüllt | Ø Auszahlung |
|---|---|---|---|
| 3 | 1 | 31 % | 9 € |
| 4 | 20 | 51 % | 35 € |
| 5 | 20 | 67 % | 41 € |
| 6 | 40 | 86 % | 45 € |

Marge je Bein 4 % statt 8 % macht zusätzlich rund 13 € aus. Daraus die Handlungsregeln: **viele kleine Scheine**, je Schein 3 Beine aus **verschiedenen** Spielen, **früh anfangen** (5–6 Abrechnungswellen in 24 h), und **aufhören, sobald der Umsatz steht**.

**Überprüfbarkeit:** Seit 12.09. wird der **Endstand** jedes Spiels mit im Cache gespeichert (`goals`, kommt in derselben API-Antwort mit). Damit lassen sich die 1X2-Fair-Quoten nachträglich genauso kalibrieren wie die Nebenmärkte ("Modell sagte X %, real waren es Y %"). Alte Cache-Einträge haben das Feld nicht — es füllt sich mit der Zeit. Die Bonus-Kandidaten jedes Laufs landen unter `bonus` in `runs/<Datum>_<Zeit>.json`.

## 10a. Abdeckungs-Abfrage (15.09., Lucios Vorgehen für neue Märkte)

**Reihenfolge, die Lucio festgelegt hat:** erst die "Exoten"-Felder (Paraden, Einwürfe, Abstöße, Freistöße, Elfmeter, Flanken, Angriffe, xG, Ballbesitz, Passquote …), danach die Tor-Märkte. Schritt 1 ist immer die Frage, **in welchen Ligen** ein Feld überhaupt konstant erfasst wird.

**Regel (Lucio):** 4 Wochen rückwärts. Reißt innerhalb der 4 Wochen auch nur **eine Woche** aus (keine Daten), ist die Liga für dieses Feld **sofort gestrichen**. Ist das Feld in allen 4 Wochen vorhanden, gilt die Liga als **prinzipiell untersuchbar und spielbar**.

**Modus `abdeckung`** (Run workflow → modus = abdeckung): zieht die beendeten Spiele der letzten 4 Wochen mit Liga, nimmt je Liga und Woche bis zu 3 Spiele als Stichprobe und prüft je Spiel, welche Felder gefüllt sind (Zahlenpaar, nicht 0:0 — außer bei Feldern, die legitim 0:0 sein können). Urteil je Liga und Feld: **OK** = in jeder Woche ≥ 75 % der Stichprobe gefüllt (`COV_WEEK_MIN`); **raus** = mindestens eine Woche darunter; **n.b.** = Liga hat nicht in allen 4 Wochen gespielt (nicht bewertbar, z. B. Pokal, Länderspielpause).

**Ergebnis:** `runs/abdeckung_<Datum>.csv` — je Liga und Feld die vier Wochenwerte in Prozent plus Urteil (Semikolon, Excel-tauglich); `runs/abdeckung_<Datum>.txt` und Telegram: je Exoten-Feld die Anzahl Ligen OK / raus / n.b. mit Beispielen, bekannte Felder zum Vergleich darunter. Kosten ~1.500–1.800 Anfragen (bricht am Stundenlimit sauber mit Teilstichprobe ab), kein Einfluss auf Cache oder Signale.

**Ergebnis 15.09. (882 Ligen, 6.887 Spiele):** einziges Exoten-Feld mit breiter Abdeckung ist **Paraden** (74 Ligen über 4 Wochen, 99 inkl. der Ligen mit Länderspielpause — alle Top-Ligen dabei); **Einwürfe, Abstöße, Freistöße** nur 13–16 Ligen (Russland, Belarus, Estland II, Premier League). Lucios Entscheidung: diese vier Felder kommen in die Datensammlung, der Rest (Ballbesitz, Angriffe, xG, Flanken, Elfmeter, Auswechslungen …) ist verworfen. Ob es beim Bookie einen Markt gibt, prüft Lucio selbst — das ist nicht Sache des Scanners.

**Datensammlung (15.09.):** `EXTRA_STAT_FIELDS` enthält jetzt `saves`, `throwins`, `goalkicks`, `freekicks` — jeder neu gecachte Spieleintrag trägt die Felder mit (kostet keine Anfrage). **Modus `exoten`** liest die jüngste `runs/abdeckung_*.csv`, nimmt alle Ligen, die bei einem der vier Felder OK sind (4 Wochen oder 3 gespielte Wochen), lädt deren beendete Spiele der letzten 12 Wochen (`EXO_WEEKS`) in den Cache nach und schreibt `cache/exoten_history.json` (je Team die Spielliste dieser Ligen — nur für den Offline-Backtest, das Live-System liest weiter `history.json`). Kosten ~1.100–1.300 Anfragen, parallel, ca. 3–4 Minuten. Danach: Backtest nach Serienregel → Preisvergleich → Freigabe durch Lucio, sonst kein Markt.

## 10a2. ALLE UNTER-MÄRKTE GESTRICHEN (17.09.)

> Lucio: „Ich mochte unter Märkte noch nie — du musst das ganze Spiel bis Ende warten, und wenn du Pech hast, wirst du in den letzten 10 Minuten hopsgenommen."

**Nicht wegen der Trefferquote.** Karten unter war gemessen der **beste** Markt im ganzen System:

| Markt | Signale | real | angezeigt | Differenz |
|---|---|---|---|---|
| Karten unter | 14.208 | 84,5 % | 83,1 % | **+1,4** |
| Abseits unter | 3.037 | 84,0 % | 83,8 % | +0,2 |
| Schüsse aT unter | 7.720 | 76,7 % | 79,7 % | −3,0 |
| Ecken über | 3.660 | 73,3 % | 76,8 % | −3,5 |
| Karten über | 4.847 | 76,3 % | 80,5 % | −4,2 |

Höchste Trefferquote, größte Stichprobe, als einziger Kernmarkt **über** dem, was die Anzeige verspricht, in beiden Zeithälften stabil, und auch im jüngsten Zeitviertel noch mit Abstand vorn (82,5 % gegen 72 % bei Ecken).

**Der Grund ist der Verlauf.** Eine Unter-Wette steht 90 Minuten auf Gewinn und kann nur noch sterben; eine verlorene Über-Wette war schon nach 20 Minuten tot und stört nicht weiter. Dazu die Messung: **53 % aller verlorenen Karten-unter-Wetten gingen um genau eine Karte daneben** (bei Ecken über nur 37 %). Gleiche Verlustquote, völlig anderes Erlebnis — und der Nervenaufwand ist ein realer Preis, auch wenn er in keiner Tabelle steht.

Technisch über `UNTER_RAUS` gelöst: die Menge fließt in `EXCLUDED_MARKETS`, Daten/Backtest/Kalibrierung bleiben unangetastet. Zum Wiedereinschalten genügt es, einen Eintrag aus `UNTER_RAUS` zu entfernen.

**Kosten:** im Lauf vom 15.09. waren 22 von 49 Signalen Unter-Wetten (45 %). Es bleiben also gut die Hälfte. Aktive Märkte danach: Ecken über, Gelbe Karten über, 1. HZ Ecken über, 1. HZ Gelbe Karten über, Einwürfe über, Abstöße über, Tore über 2,5.

**Offene Frage dazu (17.09., Lucios Einwand):** die 84,5 % stammen aus dem historischen Nachspielen der Regel — **ohne jeden Buchmacher**. Gespielt wird aber nur die Teilmenge, bei der BetLabel eine Quote über fair × 1,05 anbietet, und diesen Filter setzt der Buchmacher. Ob die spielbare Teilmenge dieselbe Trefferquote hat, lässt sich rückwirkend nicht messen — der Cache kennt keine historischen Quoten. Nur nach vorne, über ein Protokoll der tatsächlich platzierten Wetten (vorgeschlagen: `WETTEN.csv` mit Datum, Spiel, Markt, Linie, fairer Quote, genommener Quote, Ergebnis; nach 50–100 Beinen ist die Frage beantwortet). Noch nicht angelegt.

## 10b. NEUE MÄRKTE: Einwürfe und Abstöße (15.09., seit 16.09. regulär)

**Backtest** (30 Wochen Historie, 15.813 Spiele, Serienregel unverändert — beide Teams im Trend, mindestens ein Anker):

| Markt | Linie | Signale | Treffer | Grundrate |
|---|---|---|---|---|
| Einwürfe | über 38,5 | 157 | 87 % | 66 % |
| Einwürfe | über 42,5 | 69 | 80 % | 53 % |
| Einwürfe | unter 46,5 / 50,5 | 62 / 146 | 86 / 86 % | 60 / 70 % |
| Abstöße | über 16,5 | 132 | 83 % | 65 % |
| Abstöße | unter 20,5 | 125 | 81 % | 67 % |
| Freistöße | über 20,5 / 22,5 | 154 / 72 | 86 / 85 % | 62 / 51 % |
| Freistöße | unter 26,5 | 106 | 88 % | 70 % |

Die Serie hebt hier 15–33 Punkte über die Grundrate — deutlich mehr als in den Kernmärkten. Grund: Einwürfe, Abstöße und Freistöße sind Spielstil-Größen, die eine Mannschaft mitbringt. **Paraden NICHT aufgenommen**: dort liegt die Trefferquote praktisch auf der Grundrate (unter 8,5: 84 % vs. 82 %) — die Zahl hängt am Gegner, nicht am Team.

**Ligen** (`METRIC_LEAGUES`) — zweimal eingeengt:

*Erst nach Datenabdeckung.* Am 17.09. direkt im Cache nachgezählt (Anteil der Spiele mit gefülltem Feld):

| Liga | Spiele | Ecken | Karten | Abstöße | Einwürfe |
|---|---|---|---|---|---|
| Russia Premier League | 64 | 98 % | 95 % | **97 %** | **98 %** |
| England Premier League | 24 | 100 % | 92 % | **88 %** | **88 %** |
| Netherlands Eredivisie | 42 | 100 % | 93 % | 14 % | 14 % |
| France Ligue 1 | 25 | 100 % | 100 % | 0 % | 0 % |
| Spain La Liga | 40 | 100 % | 95 % | 0 % | 0 % |
| Italy Serie A | 23 | 100 % | 91 % | 0 % | 0 % |
| Germany Bundesliga | 36 | 100 % | 97 % | 0 % | 0 % |

Bei den großen westeuropäischen Ligen ist das **kein Stichprobenfehler** — über 17 bis 50 Spiele hinweg null Einträge. Der Datenlieferant erfasst die Felder dort nicht; kein Nachladen hilft. Ecken und Karten kommen dort lückenlos, deshalb laufen die Kernmärkte normal. Die Eredivisie mit 14 % sieht nach einem beginnenden Rollout aus — **in einigen Wochen erneut prüfen**, das wäre die nächste brauchbare Liga.

*Dann nach Bookie-Angebot (17.09., Lucio).* Am 17.09. lieferte der Lauf Signale, aber keinen spielbaren Pick: die Treffer lagen in der zweiten und dritten russischen Liga, wo BetLabel den Markt nicht führt. Datenabdeckung und Angebot sind zwei verschiedene Dinge — maßgeblich ist der Schnitt. Aktive Liste: **Russia Premier League, England Premier League, Belarus Premier League**. Russland Division 3 / Regional League, Belarus Division 1 und 2, Estonia II Liiga und die Frauenligen sind trotz sauberer Daten raus. Ergänzen, sobald Lucio den Markt anderswo im Konto findet. Im Selbsttest abgesichert (Fall 24k).

**Datenschutz gegen Phantomsignale:** 0:0 gilt als *nicht erfasst*, nicht als Wert (ein Spiel ohne Einwurf gibt es nicht) — solche Spiele werden übersprungen, wie bei Fouls/Abseits. Mindestens `MIN_VALID_MATCHES` gewertete Spiele je Team, sonst kein Signal.

**Freistöße gestrichen (16.09.):** Lucio hat im Konto nachgesehen — seinem Buchmacher fehlt der Markt. Daten, Backtest und Linien bleiben im Code, gesperrt sind nur die Meldungen über `EXCLUDED_MARKETS`; zum Wiedereinschalten genügt es, die beiden Einträge zu entfernen.

**Preisvergleich bestanden, 🧪 entfernt (16.09.):** erster echter Test am 16.09. mit zwei gespielten Scheinen —

| Spiel | Markt | faire Quote | BetLabel | über fair | Ergebnis |
|---|---|---|---|---|---|
| Rodina Moscow – Rubin Kasan | Abstöße über 14,5 | 1,42 | 1,51 | +6 % | 16 ✓ |
| Spartak Moskau – Fakel Woronesch | Abstöße über 12,5 | 1,31 | 1,41 | +8 % | 13 ✓ |

Der Markt ist also nicht nur vorhanden, sondern auch über fair bezahlbar. Bei BetLabel heißen die Gruppen **„Gesamtzahl. Abstöße"** bzw. **„Eckstöße"** für Ecken — über das Feld „Suche nach Markt" auf der Spielseite am schnellsten zu finden.

**Anzeige seit 16.09.:** Einwürfe und Abstöße stehen **ganz normal in der Hauptliste**, wie jeder Kernmarkt. Der Extra-Block „NEUE MÄRKTE" ist abgeschaltet (`EXO_METRICS = ()`, `EXO_ENABLED = False`, `EXO_TEST = False`); `build_exo_block()` bleibt als Gerüst im Code, falls je wieder eine neue Marktfamilie eingeführt wird. Da scores24 für diese Märkte weiterhin keinen Reiter hat, stehen sie in `GATE_EXEMPT`: sie gehen unverändert durch das Verfügbarkeits-Gate und durch die Oder-Regel, tragen dafür den Hinweis `Quote selbst prüfen`. Im Selbsttest abgesichert (Fall 24a–24j).

## 10c. TOR-MÄRKTE: Datenbeschaffung (15.09.)

Der Ereignis-Verlauf kommt in derselben API-Antwort wie die Statistiken — bisher wurden daraus nur die gelben Karten der 1. Halbzeit gelesen. Seit 15.09. werden zusätzlich die **Halbzeit-Tore** (`ht_goals`) gespeichert; kostet keine Anfrage. **Torminuten werden bewusst NICHT gespeichert** — Zeitpunkt-Märkte hat Lucio als „zu heikel" gestrichen (15.09.).

**Selbstprüfung gegen den Endstand:** Die aus dem Verlauf gezählten Tore je Seite müssen exakt dem Endstand entsprechen, sonst wird gar nichts gespeichert (`None`). Damit kann ein unbekanntes oder verändertes Textformat keine falschen Zahlen ins System tragen. Eigentore werden der anderen Seite zugerechnet.

**Modus `tore`:** lädt für alle Ligen mit Verlauf-Abdeckung (laut letzter Abdeckungs-CSV, Spalte „HZ-Karten (Verlauf)" — 234 Ligen) die beendeten Spiele der letzten 20 Wochen nach. Reihenfolge nach Relevanz: zuerst die Ligen, in denen Lucio tatsächlich Signale bekommt (aus `runs/`), dann der Rest. Bricht am Stundenlimit sauber ab und kann erneut gestartet werden — bereits geholte Spiele werden übersprungen. Ergebnis: Cache + `cache/tore_history.json` (je Team die Spielliste, nur für die Offline-Auswertung).

**Daraus analysierbare Märkte** (Serienregel unverändert, Ergebnis offen): **Tore gesamt über/unter, 1. HZ Tore, 2. HZ Tore** — dazu als Nebenrechnung „beide treffen". **Gestrichen von Lucio (15.09.):** Elfmeter, xG und alle Zeitpunkt-Märkte (Tor vor Minute X, Tor in den letzten 15). Damit bleiben genau drei Tor-Märkte zur Prüfung.

## 10d. MARKT „TORE GESAMT" (15.09., 🧪 TEST)

**Backtest** an 40.796 Spielen mit Endstand (Serienregel unverändert):

| Linie | Signale | Treffer | Grundrate | faire Quote |
|---|---|---|---|---|
| ~~über 1,5~~ | 6.621 | 84,5 % | 77,9 % | 1,18 — **gesperrt (Flut)** |
| über 2,5 | 1.022 | **75,0 %** | 57,1 % | **1,33** |
| über 3,5 | 68 | 73,5 % | 35,9 % | 1,36 |
| unter 3,5 | 2.066 | **75,1 %** | 64,1 % | **1,33** |
| ~~unter 4,5~~ | 7.554 | 85,0 % | 79,1 % | 1,18 — **gesperrt (Flut)** |
| ~~unter 2,5~~ | 90 | 60,0 % | 42,9 % | **gesperrt** |

**Stand 15.09. abends: gemeldet wird NUR "über 2,5"** (Lucios Entscheidung, "für den Anfang"). "über 3,5" und "unter 3,5" sind ebenfalls über `EXCLUDED_LINES` gesperrt und lassen sich durch Entfernen einer Zeile wieder zuschalten. Gesperrt über `EXCLUDED_LINES`: „unter 2,5" (60 %, unter Lucios 70er-Grenze), „unter 1,5" und „über 4,5" (nicht belegbar) sowie seit 15.09. auch **„über 1,5" und „unter 4,5"** — sie lösen bei 16 bzw. 18,5 % aller Spiele aus (zusammen rund ein Drittel = Signalflut) und sind mit fair 1,18 für Lucio ohnehin nicht spielbar. Übrig bleiben rund 8 % der Spiele, und zwar die mit der stärksten Hebung über die Grundrate (über 2,5: +18 Punkte, unter 3,5: +11).

**Besonderheit:** 0:0 ist bei Toren ein echtes Ergebnis und **kein** fehlender Wert (anders als bei Einwürfen/Abstößen/Freistößen) — im Selbsttest abgesichert (Fall 26c). Ein scores24-Nachweis ist nicht nötig, Tore über/unter bietet jeder Buchmacher an: `GATE_EXEMPT = ("goals", "ht_goals", "h2_goals")` — diese Signale gehen unverändert durch das Verfügbarkeits-Gate und durch die Oder-Regel, bekommen aber die Kennzeichnung `no_odds_check`.

**Anzeige (geändert 15.09. auf Lucios Wunsch):** „Tore über 2,5" steht **nicht mehr im Extra-Block „NEUE MÄRKTE"**, sondern ganz normal im Spielblock der Hauptliste, zwischen Ecken und Karten — gleiche Darstellung, gleiche Ampel, gleiche Fair-Quote. Hinter der Zeile steht `· Quote selbst prüfen`, weil es für Tore keinen scores24-Nachweis gibt. Damit gilt weiter: Tore sind der am schärfsten bepreiste Markt — die Bookie-Quote muss wirklich über fair liegen. Der Extra-Block führt seitdem nur noch Einwürfe/Abstöße/Freistöße. Im Selbsttest abgesichert (Fall 26e–26h).

## 10b2. PUFFER-BELASTBARKEIT bei den neuen Märkten (16.09.)

Anlass: der Scanner meldete „Abstöße über 14,5" mit Puffer +1,4 bei einer Streuung von rund 5 — die Linie lag praktisch auf dem Erwartungswert. BetLabel bot dafür 1,51, unsere faire Quote lag bei 1,42. Margenbereinigt preist der Buchmacher an dieser Linie aber nur 60,4 %, unser Modell 70,4 %. Beim **Erwartungswert** sind sich Modell und Markt einig (15,9 gegen 15,8) — der ganze Unterschied steckt im Puffer.

Nachgerechnet an 2.415 Signalen der drei neuen Märkte (Puffer geteilt durch die Streuung, damit Einwürfe/Abstöße/Freistöße trotz unterschiedlicher Größenordnung vergleichbar sind):

| Puffer / Streuung | Signale | real | Modell | Differenz |
|---|---|---|---|---|
| unter 0,5 | 111 | — | — | **kaum getestet** |
| 0,5 – 0,75 | 329 | 75,1 % | 70,8 % | +4,3 |
| 0,75 – 1,0 | 551 | 83,7 % | 75,0 % | +8,7 |
| 1,0 – 1,5 | 1.046 | 85,7 % | 80,1 % | +5,6 |
| über 1,5 | 378 | 92,6 % | 84,3 % | +8,3 |

Die „80–88 %" aus Abschnitt 10b gelten also für **dicke** Puffer. Das Modell ist dort durchweg **zu vorsichtig** (real 4–9 Punkte über der angezeigten fairen Quote) — eine Kalibrierung nach unten ist nicht nötig.

**Kein Filter.** Erwogen und verworfen: ein Mindestpuffer würde genau die Signale entfernen, die Lucio spielen kann. Ein dicker Puffer bedeutet eine kurze faire Quote (bis herunter auf 1,06) — im Backtest der stärkste Bereich, aber beim Buchmacher nie bezahlt. Die spielbaren Quoten liegen alle im dünnen Bereich. Ebenfalls verworfen: die Linienleiter auf das kürzen, was BetLabel in einem Spiel führte — die angebotenen Linien wandern von Liga zu Liga (ein russisches Spiel zentriert bei 15,5, ein anderes bei 22), genauso wie „unter 6,5 Gelbe" in Südamerika und Griechenland eine gute Linie ist und anderswo nie erscheint.

**Stattdessen reine Anzeige** (`EXO_EVIDENCE` / `buffer_evidence()`): hinter dem Puffer steht, wie gut dieser Bereich belegt ist — `⚠️ dünn getestet (111 Fälle)` oder `✓ 551 Fälle · 84 %`. Lucio (16.09.): „Das passt so learning by doing." Im Selbsttest abgesichert (Fall 24e–24g).

Seit dem Umzug in die Hauptliste (Abschnitt 10b) zeigt der kompakte Spielblock keine Erwartungs- und Pufferzeile mehr. Deshalb gibt es die **Kurzform** `buffer_evidence(s, short=True)`: sie hängt an die Kopfzeile nur dann etwas an, wenn der Puffer im kaum getesteten Bereich liegt — `· ⚠️ dünner Puffer`. Gilt nur für die Märkte in `EVIDENCE_METRICS` (Einwürfe, Abstöße), für die die Tabelle gemessen wurde.

**Erste Bewährungsprobe (16.09.):** ausgerechnet das als dünn markierte Signal (Rodina, Puffer +1,4) ging mit 16 gegen Linie 14,5 komfortabel durch, während das mit dem dicken Puffer (Spartak, Erwartung 14,7) mit 13 gegen 12,5 nur knapp gewann. Der Puffer ist eine Wahrscheinlichkeit, keine Zusage — ein Datenpunkt, kein Widerspruch zur Tabelle.

## 10e. Nachrichtenlänge (15.09.)

Telegram nimmt höchstens 4.096 Zeichen je Nachricht. Die Blöcke „Neue Märkte" und „Team-Märkte" wurden bisher als EINE Nachricht verschickt — bei 169 Tor-Signalen waren das 38.000 Zeichen, Telegram hat die Nachricht komplett abgewiesen, und es kam gar nichts an (die Kernliste war davon nicht betroffen, weil sie schon immer geteilt wird). Seit 15.09. laufen alle Zusatzblöcke durch `split_message()`: Teilung an Zeilengrenzen, jedes Stück unter 3.500 Zeichen, mit „Teil x/y" gekennzeichnet. Im Selbsttest abgesichert (Fall 27).

## 10e2. HALBZEIT-TORE (15.09.) — noch am selben Abend wieder RAUS

> Lucio: „Ich will die ht Märkte wieder raus haben.“ Beide Linien sind über `EXCLUDED_MARKETS` gesperrt; Daten, Parser und Kalibrierung bleiben im Code — zum Wiedereinschalten genügt es, die vier Einträge zu entfernen. Die Zahlen unten bleiben als Beleg stehen.

Backtest an 26.131 Spielen mit Halbzeitstand (Serienregel unverändert):

| Markt | Signale | Treffer | Grundrate |
|---|---|---|---|
| 1. HZ Tore über 0,5 | 1.325 | 76,2 % | 72,1 % |
| 2. HZ Tore über 0,5 | 2.901 | 82,5 % | 80,1 % |
| ~~1. HZ unter 1,5~~ | 417 | 70,7 % | 62,7 % | — Unter-Tore spielt Lucio nicht |
| ~~1. HZ unter 2,5~~ | 4.434 | 87,2 % | 85,3 % | — dito |
| ~~2. HZ unter 2,5~~ | 2.584 | 82,0 % | 77,6 % | — dito |

**Aufgenommen:** nur die beiden Über-0,5-Linien (Lucios Vorgabe: mindestens 75 % Trefferquote, keine Unter-Tore). Beide Märkte sind abgeleitet: `ht_goals` kommt aus dem Ereignis-Verlauf, `h2_goals` = Endstand minus Halbzeitstand. Steht im Verlauf nur die Summe (Seiten nicht zuzuordnen), wird `[Gesamt, -1]` gespeichert — für Gesamtmärkte reicht das. Unplausible Kombinationen (Halbzeit > Endstand) gelten als fehlende Daten.

**Kalibrierung war hier besonders wichtig:** Bei „1. HZ über 0,5" sagte das Modell 86,8 %, real sind es 75,6 % (n=1.726) — die Normalverteilung passt bei so kleinen Zahlen nahe null schlecht. Ohne Korrektur stünde dort Fair 1,15 statt der ehrlichen 1,32. Faktor 0,87; 2. HZ 0,98.

## 10f. Kalibrierung der fairen Quote (15.09.)

Am Cache gemessen, wie oft das Modell recht behält. Über alle Märkte zusammen stimmt es fast genau (Abweichung 0,6–1,4 Punkte je Quotenklasse) — die Abweichung sitzt im einzelnen **Markt**:

| Markt | Modell | real | Faktor |
|---|---|---|---|
| Ecken über | 76,8 % | 73,3 % | 0,95 |
| Gelbe Karten über | 80,5 % | 76,3 % | 0,95 |
| Gelbe Karten unter | 83,1 % | 84,5 % | 1,02 |
| Abseits über/unter | 83,8 % | 84,0 % | 1,00 |
| Tore über | 77,1 % | 72,5 % | 0,94 |
| 1. HZ Tore über 0,5 | 86,8 % | 75,6 % | 0,87 |
| 2. HZ Tore über 0,5 | 84,0 % | 81,9 % | 0,98 |
| 1. HZ Ecken über 3,5 | 75,5 % | 69,1 % | 0,92 |
| 1. HZ Karten über 0,5 | 81,9 % | 79,2 % | 0,97 |
| 1. HZ Karten unter | 77,7 % | 78,1 % | 1,00 |

Der Faktor (`CALIBRATION`) wird auf die kombinierte Wahrscheinlichkeit angewendet, bevor daraus die faire Quote wird — auch in der Fair-Leiter. Wirkung an echten Signalen: Ecken über 7,5 von 1,36 auf 1,43, von 1,26 auf 1,33; Karten unter 4,5 von 1,38 auf 1,36.

Märkte ohne eigene Messung (Einwürfe, Abstöße, Freistöße) laufen mit Faktor 1,00 mit — lieber unkorrigiert als geraten. **Empfehlung an Lucio:** auf die angezeigte Fair weiterhin rund 5 % Sicherheitsmarge aufschlagen (Streuung der Messung), also bei Fair 1,35 ab etwa 1,42 spielen. Die Faktoren gehören bei der Monatsauswertung überprüft.

## 10g. HTTP 429 (15.09.)

Der eigene Anfragen-Wächter zählt nur die Anfragen **des laufenden Prozesses** — jeder Actions-Lauf startet bei null, das Stundenlimit der API gilt aber über alle Läufe zusammen. Ein Nachlade-Lauf direkt nach einem Scan konnte deshalb ins Limit rennen: Die API antwortete mit HTTP 429, der Code behandelte das wie einen normalen Fehler, wiederholte mit Wartezeiten und produzierte hunderte 429-Zeilen, bis Lucio den Lauf von Hand abgebrochen hat.

Seit 15.09. gilt HTTP 429 als **verbindliche Auskunft**, dass das Limit voll ist: Der eigene Zähler wird sofort auf das Limit gesetzt; in den Nachlade-Modi bricht der Lauf sauber ab und meldet „TEILWEISE (Budget)", im normalen Scan wird 120 Sekunden gewartet. Ist das Budget einmal als erschöpft erkannt, brechen alle weiteren Anfragen sofort ab, statt einzeln in Wiederholungen zu laufen. Im Selbsttest abgesichert (Fall 29).

## 10. Robustheit (12.09.)

Ein einzelner hängender API-Aufruf hat am 12.09. einen kompletten Lauf mit `TimeoutError` abgebrochen (erste Anfrage auf `/v3/events/upcoming`). Drei Änderungen:

- **`api_get`:** 5 Versuche statt 3, Zeitlimit 45 s statt 30, wachsende Wartezeit (3/6/12/24 s).
- **Spielliste:** Eine fehlgeschlagene Seite bricht den Lauf nicht mehr ab — es wird mit den geladenen Spielen weitergearbeitet und ein Hinweis in die Telegram-Nachricht gesetzt ("Unvollständige Spielliste"). Nur wenn **gar keine** Seite geladen werden konnte, bricht der Lauf mit klarer Meldung ab.
- **`run()`:** umhüllt den Lauf. Ein unerwarteter Fehler geht jetzt als Telegram-Nachricht raus ("Lauf abgebrochen: …") statt still im Actions-Protokoll zu verschwinden. Der Job endet weiter mit Fehlercode, damit es in Actions rot sichtbar bleibt; der Commit-Schritt läuft trotzdem (`if: always()`).

## 11. "Wer hat mehr" — Siegwetten in den Nebenmärkten (12.09., Lucios Idee) — AUS seit 13.09.

> Abgeschaltet zusammen mit dem Bonus (Abschnitt 9), Schalter `BONUS_DAYS`. Modell und Guards bleiben im Code, nur als Doku.

Sein Bookie bietet die Nebenmärkte auch als **Siegwette** an ("wer hat mehr Ecken / Schüsse"). Das sind **keine Gesamtzahl-Wetten**, zählen also für die Bonus-Umsatzbedingung — und es sind Nebenmärkte, in denen der Buchmacher weniger sorgfältig rechnet als bei 1X2.

**Modell:** erwartete Anzahl **je Mannschaft** (eigener Ø + Gegen-Ø des Gegners, zeitgewichtet) mal Heimfaktor; daraus die Differenzverteilung zweier Poisson-Zähler (Skellam) → P(Heim mehr), P(gleich), P(Gast mehr). Gemeldet wird die stärkere Seite ab **55 %** Wahrscheinlichkeit, **ohne Obergrenze** (12.09. gelockert — Lucio: "die Fair-Restriktion spült Fehler des Bookies mit raus", dasselbe Argument wie bei `MIN_FAIR` am 06.09.). Die 55 % sind keine Geschmacksgrenze: in der Klasse 50–55 % lag die Realität bei 51,1 %, dort steckt keine Information.

**Auswahl nach der Serienregel (12.09., zweite Fassung):** Wie bei den Gesamtmärkten entscheiden die **Serien**, ob ein Signal existiert — nicht das Modell. Der Favorit muss eine "mehr als der Gegner"-Serie haben, der Gegner eine "weniger"-Serie, und mindestens eine davon muss ein Anker sein (10 von ≤12 gesamt bzw. 15 in der heutigen Rolle, Frische-Regel). Das Modell liefert danach nur die faire Quote und darf nicht in die Gegenrichtung zeigen (≥ 50 %). Zwischenzeitlich (erste Fassung, 12.09. nachmittags) kamen Signale allein aus dem Modell ab 55 % — Lucio: "Dachte, die Auswahl-Logik ist weiterhin gleich wie beim normalen Modell?" Der Backtest gab ihm recht:

| | Signale je 3.700 Spiele | real | Modell sagte |
|---|---|---|---|
| Ecken, nur Modell ≥ 55 % | 1.755 | 64,3 % | 64,2 % |
| Ecken, Serienregel | 55 | **70,9 %** | 71,3 % |
| Schüsse, nur Modell ≥ 55 % | 1.695 | 66,0 % | 65,1 % |
| Schüsse, Serienregel | 66 | **78,8 %** | 70,7 % |

Die Modell-Signale bei 64–66 % sind gegen Bookie-Quoten um 1,57 (impliziert ~64 %) kein Value; die Serien-Signale bei 71–79 % dagegen schon — und das Modell unterschätzt sie sogar, die angezeigte faire Quote ist also konservativ. Preis: 7–10 Signale am Tag statt ~200.

**Anker-Serien (12.09., Lucios Idee):** Die bekannte Serienlogik auf "hatte mehr als der Gegner" — 10 von ≤12 Spielen gesamt bzw. 15 in der heutigen Rolle, Frische-Regel, Gleichstand zählt als Aussetzer; dazu die kleine Serie (5 von ≤6) und die Gegen-Serie des Gegners ("hatte weniger"). Am Cache nachgerechnet (Ecken):

| Fall | Spiele | real | Modell sagte |
|---|---|---|---|
| alle Spiele | 3.697 | 51,5 % | 50,5 % |
| Modell ≥ 60 % **ohne** Anker | 779 | 66,2 % | 67,6 % |
| Modell ≥ 60 % **mit** Anker | 146 | **76,7 %** | 72,2 % |
| Anker allein | 226 | 68,1 % | 65,2 % |

Der Anker trägt also Information, die das Erwartungsmodell **nicht** hat (+10,5 Punkte bei gleicher Modellklasse, ~2,7σ). Bei Schüssen aufs Tor dieselbe Richtung (73,8 % mit vs. 67,7 % ohne). Deshalb: ⚓ in der Anzeige, Anker-Fälle stehen oben, und die Serien beider Seiten werden wie bei den Gesamtmärkten mitgeschrieben. Gefiltert wird damit **nicht** — die Entscheidung bleibt bei Lucio.

**Datenqualität (12.09. nachgezogen, vier Sperren):**

1. **mindestens 8 gewertete Spiele** je Team und Metrik
2. **Summe** der Erwartungen zwischen 50 % und 180 % des Gesamtschnitts
3. **jede Seite einzeln** zwischen 45 % und 200 % des Schnitts je Team — die Summenprüfung allein hätte den Auslöser nicht gefangen (1,0 + 3,1 = 4,1 bei Schnitt 4,4 ist unauffällig, erst 1,0 gegen 2,2 je Team fällt auf)
4. **einseitige Erwartungen brauchen mehr Belege**: ab einem Verhältnis von 1,6 zwischen den Seiten sind 12 statt 8 gewertete Spiele nötig

Im Backtest kosten alle vier Sperren zusammen nur 2–3 % der Fälle — sie treffen genau die Ligen ohne Datenerfassung. Anlass: für Neman Grodno – Torpedo Zhodino kam ein HZ-Ecken-Signal mit fair 1,27 heraus, während BetLabel entmargt 31,3 % stellte (fair 3,20). Ursache: in der weißrussischen Liga werden **keine** Halbzeit-Ecken erfasst — von 50 Spielen des Teams hatte **keines** HZ-Werte, die Erwartung 1,0:3,1 stammte aus drei Zufallsspielen bei einem Ligaschnitt von 2,2 je Team. Die Datenbasis steht jetzt als 📊 x/y in der Anzeige.

**Nachweis:** identisch zu allen anderen Signalen — der scores24-Reiter der Marktfamilie muss die Metrik kennen (Ecken-Reiter für Ecken und HZ-Ecken, Schüsse-Reiter für Schüsse aufs Tor). Kostet keine zusätzlichen API-Anfragen; die scores24-Abfrage wird nur für Kandidaten geholt.

**Geprüft an 3.697 Spielen aus dem Cache** (Heimfaktor auf einer Datenhälfte geschätzt, auf der anderen getestet — Ecken 1,06, Schüsse 1,08):

| Modell sagt | Spiele | real |
|---|---|---|
| 50–55 % | 538 | 51,1 % |
| 55–60 % | 459 | 58,6 % |
| 60–65 % | 349 | 62,5 % |
| 65–70 % | 262 | 66,8 % |
| 70–80 % | 252 | 71,8 % |
| über 80 % | 62 | 87,1 % |

Schüsse aufs Tor genauso gut (Gastseite sogar besser als das Modell: sagt 71,5 %, real 81,0 %). **Gelbe Karten sind bewusst NICHT dabei** — dort gibt es kein Signal (Heimfaktor 1,00, keine Verbesserung gegenüber der pauschalen Grundrate; der Schiedsrichter bestimmt mehr als die Teams).

**Anzeige:** eigener Abschnitt 🥇 unterhalb der Bonus-Picks, mit fairer Quote (Dreiweg, Gleichstand ist eine eigene Auswahl und steckt in der Quote), erwarteter Anzahl je Mannschaft und der Gleichstand-Wahrscheinlichkeit. Die frühere "ohne X"-Spalte ist raus (12.09.): sein Bookie führt diese Märkte immer als Dreiweg, eine Rückgabe bei Gleichstand gibt es dort nicht. 🎁 markiert faire Quoten über 1,40, die damit als Bonus-Bein taugen. Alle Kandidaten landen unter `who_more` in `runs/<Datum>_<Zeit>.json`.

**Offen:** ob der Bookie dort schlechter rechnet als das Modell, lässt sich erst mit echten Preisen sagen. Dafür braucht es Lucios Quoten zu ein paar Spielen.

## 12. Prüfpflicht für neue Märkte (12.09., Vorgabe von Lucio)

Auslöser: eine neue Marktfamilie ("Wer hat mehr") ging in derselben Stunde nach Telegram, in der sie gebaut wurde — ohne die Datenqualitätsregeln der bestehenden Strategie. Ergebnis war ein Phantomsignal (HZ-Ecken in einer Liga, die keine HZ-Ecken erfasst: fair 1,27 gegen 3,20 beim Buchmacher). Lucios Vorgabe: **"Ich will kein Geld damit verbrennen."**

Ab jetzt gilt für **jeden** neuen Markt, bevor er als spielbar gilt:

1. **Datenabdeckung messen.** Wie viele Spiele im Cache haben die Metrik überhaupt? Und stichprobenweise: haben die Teams der Zielligen Werte? (Der Neman-Fall: 50 Spiele in der Liste, 0 mit HZ-Ecken.)
2. **Mindest-Datenbasis übernehmen**, nicht neu erfinden: ≥ 8 gewertete Spiele je Team und Metrik, bei einseitigen Erwartungen (Verhältnis ≥ 1,6) ≥ 12.
3. **Plausibilität** gegen den Gesamtschnitt — Summe UND jede Seite einzeln.
4. **Backtest mit aktiven Sperren** auf mindestens 500 Fällen: Kalibrierungstabelle (Modell gegen real) in Klassen. Abgelehnt, wenn die Abweichung über 3 Punkte liegt oder die Reihenfolge nicht monoton ist.
5. **Anker-Logik prüfen**, ob sie über das Modell hinaus etwas beiträgt (bei "Wer hat mehr": +10,5 Punkte, ~2,7σ).
6. **Preisvergleich mit echten Buchmacher-Quoten** an mindestens 3 Spielen. Ohne das ist unbekannt, ob überhaupt Luft im Markt ist.
7. **Bis Punkt 6 erledigt ist:** Der Markt läuft als **🧪 TEST** — jedes Signal ist markiert, der Kopf der Nachricht sagt ausdrücklich "noch nicht gegen echte Preise geprüft, für eigenes Geld erst danach". Schalter im Code: `WHO_TEST` (bzw. analog für künftige Familien).
8. **Getrennte Auswertung** in den ersten zwei Wochen, bevor der Markt in die normale Monatsbilanz einfließt.

Selbsttest: jede der Sperren hat einen eigenen Testfall, inklusive einem, der den Neman-Fall nachbaut (Fälle 22g–22l).

## 13. Team-Märkte — eine Mannschaft über/unter (13.09., Lucios Fund) — AUS

> **13.09.:** Abgeschaltet (`TEAM_ENABLED = False`), weil zu voreilig eingebaut. Von der Prüfpflicht (Abschnitt 12) ist erledigt: Backtest auf 3.700 Spielen mit Anker-Prüfung, Mindest-Datenbasis, Trivial-Filter. **Nicht** erledigt: Preisvergleich an mindestens 3 Spielen und ein Nachweis, dass der **Team**-Markt (nicht nur die Marktfamilie) bei scores24/BetLabel tatsächlich existiert — der Verfügbarkeits-Check prüft bisher nur den Ecken-/Karten-Reiter des Spiels. Erst wenn Lucio das ausdrücklich freigibt, geht der Schalter wieder an.

Beim Bookie "Individuell Gesamtzahl": eine Mannschaft über/unter x Ecken, Karten oder Schüsse aufs Tor. Lucio hatte so etwas auf scores24 entdeckt und am 12.09. gespielt (Seattle Sounders unter 2,5 Gelbe Karten, "weil ich sonst einfach nichts hatte"). Dieselbe Anker-Logik, nur auf **ein** Team.

**Regel:** Das Team muss in den **letzten 10 Spielen lückenlos** über/unter der Linie gelegen haben (bzw. 15 in der heutigen Rolle mit max. 1 Lücke), Frische-Regel, mindestens 7 gewertete Spiele. Je Team, Metrik und Richtung nur die strengste qualifizierende Linie. Linien mit Grundrate ≥ 70 % werden nicht gemeldet (z.B. Ecken unter 6,5 — das tritt ohnehin fast immer ein). Faire Quote: gewichtete Historie zur Grundrate geschrumpft, gemischt mit dem Normalverteilungs-Modell der eigenen Zahlen. Nachweis wie immer über den scores24-Reiter der Marktfamilie.

**Linien:** Ecken 3,5 / 4,5 / 5,5 / 6,5 · Gelbe Karten 1,5 / 2,5 · Schüsse aufs Tor 3,5 / 4,5 / 5,5.

**Backtest** (Cache, 3.700 Spiele, beide Seiten), Anker 10 von ≤12 vs. lückenlos:

| Anker-Regel | Signale je Spiel | Treffer |
|---|---|---|
| 10 von ≤12 | 1,8 | 71,7 % |
| 10 von ≤11 | 1,1 | 74,3 % |
| **10 von 10, lückenlos** | **0,4** | **78,2 %** |

Und je Linie (lockere Variante) gegenüber der Grundrate: Karten unter 1,5 74,9 % statt 46,4 %, Ecken über 4,5 66,8 % statt 48,6 %, Schüsse unter 4,5 69,8 % statt 55,1 %. Die lückenlose Variante liegt auf Kernsystem-Niveau und liefert statt einer Flut rund 0,4 Signale je Spiel.

**Anzeige:** eigener Abschnitt 🏷, je Spiel ein Block mit allen qualifizierenden Team-Linien, täglich (nicht nur Sa/So). Läuft als **🧪 TEST** bis zum Preisvergleich (Abschnitt 12), Schalter `TEAM_TEST`. Protokoll unter `team_totals` in `runs/`.

**Ebenfalls 13.09.:** Bonus komplett verworfen (Abschnitt 9) — 1X2-Liste und 🥇-Siegwetten aus. Die Team-Märkte sind ebenfalls aus (siehe oben).

## 14. Mindestquote „Anzeige × 1,05" (16.09., Lucios Spielregel)

Die angezeigte faire Quote ist kalibriert (Abschnitt 10f) und liegt im Mittel etwa einen Punkt zu optimistisch. Lucio nimmt einen Markt deshalb nur, wenn der Buchmacher **mindestens angezeigte Fair × 1,05** zahlt (Fair 1,25 → ab 1,31; Fair 1,40 → ab 1,47), und weiterhin nie unter 1,30. Relativ, keine feste Grenze — Simulation über 50 Dreier: bei Quoten knapp über Fair schwankt die Bilanz um null, erst der Aufschlag macht die Kombis tragfähig.

## 15. ALLE ÜBER-MÄRKTE EINGESCHALTET, Anzeige ab Fair 1,15 (17.09. abends, Lucio)

> Lucio: „Alles einschalten, auch beim Fußball — alle Über-Märkte, bei denen die Trefferquote der Strategie mindestens 75 % lag. Faire Quote ab 1,15 anzeigen, mehr Filter nicht." Unter-Märkte bleiben überall draußen (Abschnitt 10a2).

**Backtest** (36.616 Spiele aus dem Cache-Stand 17.09., 48.492 Über-Signale der Serien-Regel, alle Sperren aus). Trefferquote je Markt und Linie, daneben die im Mittel *angezeigte* faire Quote — sie trifft die echte fast überall:

| Markt | Linie | n | Treffer | Fair real | Fair angezeigt |
|---|---|---|---|---|---|
| Fouls | über 18,5 / 20,5 / 22,5 / 24,5 | 1241 / 658 / 293 / 140 | 81 / 79 / 77 / 75 % | 1,23–1,33 | 1,25–1,29 |
| Schüsse aufs Tor | über 6,5 / 7,5 / 8,5 | 4355 / 2152 / 799 | 79 / 75 / 74 % | 1,27 / 1,33 / 1,35 | 1,28 / 1,34 / 1,37 |
| Abseits | über 2,5 / 3,5 | 459 / 76 | 78 / 75 % | 1,27 / 1,33 | 1,29 / 1,34 |
| Tore | über 1,5 / 2,5 / 3,5 | 5886 / 930 / 69 | 82 / 72 / 65 % | 1,22 / 1,40 / 1,53 | 1,31 / 1,43 / 1,50 |
| 1. HZ Tore / 2. HZ Tore | über 0,5 | 2162 / 4169 | 77 / 81 % | 1,30 / 1,23 | 1,33 / 1,23 |
| Gelbe Karten | über 2,5 / 3,5 / 4,5 | 6167 / 1978 / 282 | 77 / 71 / 61 % | 1,29 / 1,40 / 1,63 | 1,30 / 1,36 / **1,43** |
| 1. HZ Gelbe Karten | über 0,5 / 1,5 | 6052 / 119 | 78 / 55 % | 1,29 / 1,83 | 1,27 / **1,45** |
| Ecken | über 7,5 / 8,5 / 9,5 | 4496 / 1292 / 251 | 74 / 70 / 60 % | 1,35 / 1,44 / 1,66 | 1,37 / 1,44 / **1,50** |
| 1. HZ Ecken | über 3,5 / 4,5 | 2284 / 142 | 71 / 59 % | 1,40 / 1,69 | 1,46 / 1,61 |
| Einwürfe / Abstöße | über 30,5–34,5 / 12,5–14,5 | 65–99 | 84–92 % | 1,08–1,19 | 1,15–1,22 |
| Schüsse gesamt | über 18,5 / 20,5 | 623 / 232 | 79 / 77 % | — | bleibt raus (Datenfeld unbrauchbar, 11.09.) |
| Freistöße | über 16,5 | 60 | 82 % | — | bleibt raus (kein Markt beim Buchmacher, 16.09.) |

**Umsetzung im Fußball:**
- Wieder eingeschaltet: Fouls über, Schüsse aufs Tor über, Abseits über, 1. HZ Tore über 0,5, 2. HZ Tore über 0,5, Tore über 1,5 und über 3,5.
- Anzeige ab **Fair 1,15** (`MIN_FAIR = 1.15`). Darunter kann kein Buchmacher 1,30 geben; das hält auch die 1,05er-Fälle von „Tore über 1,5" fern.
- Linien unter 75 % **bleiben**, wenn die angezeigte faire Quote stimmt (Ecken 8,5, Tore 2,5, Karten 3,5, 1. HZ Ecken 3,5): im Fußball ist die faire Quote je Spiel gerechnet und je Markt kalibriert, die 75 % stecken in der Quote — eine Linie mit 70 % zeigt 1,43 an, und dann entscheidet Lucios Regel „Bookie ≥ Fair × 1,05".
- **Rausgenommen** (fett in der Tabelle): Linien, bei denen die Anzeige deutlich zu optimistisch ist — 1. HZ Karten über 1,5 (55 % real, 69 % angezeigt), Gelbe Karten über 4,5 (61 / 70 %), Schüsse aufs Tor über 9,5 (65 / 72 %), Ecken über 9,5 (60 / 67 %). Auf solche Anzeigen kann er sich nicht verlassen (`EXCLUDED_LINES`).
- Gespielt wird damit über: Ecken 7,5–8,5 · 1. HZ Ecken 3,5–4,5 · Gelbe Karten 2,5–3,5 · 1. HZ Karten 0,5 · Schüsse aufs Tor 6,5–8,5 · Abseits 2,5–5,5 · Fouls 18,5–28,5 · Tore 1,5 / 2,5 / 3,5 · 1./2. HZ Tore 0,5 · Einwürfe · Abstöße (Ligen: Russland, England, Belarus, jeweils höchste Liga).

**Andere Sportarten (handball.py, Modus `<sportart>-scan`):** dort gibt es keine Modell-Rechnung, sondern Lucios Serien-Regel mit der *reinen* Trefferquote als fairer Quote — „ich guck mir sowieso jedes einzelne Spiel und jeden einzelnen Markt an, dann kann ich das gleich mitchecken". Summen-Märkte: beide Teams in 9 (A) bzw. 8 (B) ihrer letzten 10 Spiele über der Linie; Team-Märkte: das Team selbst 9/10. Nur über, je Markt die strengste Linie, Fair = 1 / Trefferquote genau dieser Linie+Regel aus der Historie (mind. 100 Fälle), bei jedem Lauf frisch gerechnet. Gemeldet wird das Fenster **Trefferquote ≥ 75 % und Fair ≥ 1,15**. Es zählen heute laufende Spiele mit (🔴 läuft bereits) und die nächsten zwei Tage.
- Basketball: Punkte, 1. HZ, Q1, 3er, Fouls, Freiwürfe (beide Teams) + Team-Punkte, Team-1. HZ, Team-3er. Achtung Datenquelle: Abschnitt 3 ist der Halbzeitstand, nicht Q3.
- Handball: Tore, 1. HZ, 2. HZ + Team-Tore, Team-1. HZ.
- Eishockey: Tore regulär (drei Drittel, ohne OT), 1./2./3. Drittel + Team-Tore regulär; zusätzlich die Gast-Abwehr-Regel „Heim über 2,5" (Gast kassiert Ø ≥ 4,5 → 89 %; Ø ≥ 4,0 oder 9/10 mit 3+ und Heim Ø ≥ 3,2 → 83 %; Heim immer Ø ≥ 2,6; Testspiele raus).
- Ligen und Märkte, für die BetLabel keine Quoten stellt, werden nach Lucios Rückmeldung aus der Praxis rausgenommen.

**Zurückgenommen (17.09. spät, Lucio: „Mach bitte alles wieder normal wie vorher. Nur meine Fußball-Tipps mit den gewohnten Märkten, ohne Quoten, nur die faire wie sonst auch."):** Der Fußball läuft wieder auf dem Stand vom Nachmittag — Ecken über, Gelbe Karten über, 1. HZ Ecken über, 1. HZ Karten über, Einwürfe/Abstöße über (Russland, England, Belarus), Tore über 2,5; Halbzeit-Tore, Schüsse aufs Tor, Abseits, Fouls, Tore über 1,5/3,5 wieder aus; Anzeige ohne Fair-Untergrenze (`MIN_FAIR = 1.0`); bet365-Quotenvergleich aus (`B365_PREMATCH = False`, Code bleibt). Grund: bet365 deckt über die API nur Tore, Ecken-Hauptlinie und Karten-Hauptlinie ab — „lohnt gar nicht", und die Halbzeit-Tore „nerven nur". Geblieben sind nur die vier gesperrten Linien mit irreführender Anzeige (1. HZ Karten über 1,5, Karten über 4,5, Schüsse aufs Tor über 9,5, Ecken über 9,5). Die Sport-Scans (Handball, Eishockey, Basketball) behalten den bet365-Abgleich.

**Tor-Signale nur mit Quoten-Nachweis (18.09., Lucios Beobachtung):** „Die über-2,5-Signale sind fast alles Spiele, die ich bei meinem Bookie gar nicht finde." Ursache: Tore liefen als `GATE_EXEMPT` komplett ohne scores24-Prüfung, also auch in Reserve-, Jugend- und Randligen, die kein Buchmacher führt — die anderen Märkte wurden dort längst vom Reiter-Nachweis gefiltert. Jetzt: Tor-Signale nur, wenn scores24 für das Spiel überhaupt Quoten-Reiter kennt (Seite zuordenbar und mindestens ein Reiter mit Quoten); sonst raus. Die Reiter-Namen je Lauf stehen im Protokoll (`s24_reiter`), um später gezielt auf den Tore-Reiter prüfen zu können.

**Nachgeschärft (18.09. mittags):** scores24 kennt auch für Oberliga Bremen & Co. einen Tore-Reiter (irgendein Buchmacher führt sie), BetLabel aber nicht — Lucio: „Das muss ein Fehler sein, bei meinem Bookie wird das Spiel überhaupt nicht angezeigt." Deshalb für Tore zusätzlich: der Reiter muss der Tore-Reiter selbst sein (`totals`), eine pauschale Liga-Sperre für Tore war kurz aktiv und ist auf Lucios Wunsch („bitte nichts pauschal rausnehmen") wieder aus (`GOALS_LIGA_FILTER = False`) (`GOALS_LIGA_RAUS`, `goals_liga_ok`). Ecken/Karten bleiben unverändert (dort wollte Lucio Reserve-/Jugendligen ausdrücklich behalten).
