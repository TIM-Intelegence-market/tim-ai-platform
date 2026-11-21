# Prüfprotokoll Konsolidierung 1.0 (eingefroren vor der Bewertung neuer Kandidaten)

| Feld | Wert |
|---|---|
| Version | 1.0 |
| Datum | 2026-11-16 |
| Auftrag | Uzi, 2026-11-16 12:43 UTC: alle TIM-Studien prüfen, belastbare Befunde zu einer Studie verdichten, ehrliches Urteil |
| Ausführung | Forschungsthread (Claude), nur Papier und Analyse |
| Einfrieren | Dieses Dokument wird vor dem Lauf der Tests T2 bis T12 in Git festgeschrieben (Commit-Hash steht im Ergebnisordner `ergebnisse/PROTOKOLL_STAND.json`). Danach gilt: keine Änderung von Kriterien, Kandidaten, Rastern, Seeds. Änderungen nur als neue Version mit Begründung, alte Ergebnisse bleiben stehen |
| Sperren | `TRADING_AUTHORIZED=NO` bleibt. Keine Orders, keine Freigaben, keine Live-Aktivierung. Holdout (Archivkurse ab 2025-01-01) wird nicht geladen; der Lader verweigert ihn. Kein Merge durch diesen Auftrag |
| Bezug | `docs/research_lab/PROTOKOLL.md` 1.3 (Split, Abschnittsregel 1.2, Kostenmodell 4.4, Holm). Dieses Protokoll ersetzt es nicht, es ergänzt es für die Konsolidierung |

## 1. Zweck und Grenzen

Die Frage lautet: Gibt es nach realistischen Kosten eine robuste, praktisch ausführbare Strategie, die aus den bisherigen TIM-Studien folgt? Dieses Protokoll legt fest, **wie** das beurteilt wird, bevor die neuen Rechnungen laufen.

**Vorbelastung der Daten (offengelegt, bindend für die Lesart).**

- Training (Signale bis 2022-12-31) und Validierung (2023-01-01 bis 2024-12-31) sind für S7/S7b mehrfach gesehen. S7b ist eine Reaktion auf das S7-Validierungsergebnis (Positionsgrenze 1, Reihenfolge BTC > ETH > SOL, nach Kenntnis der Instrumentwerte gewählt; `S7B_EINE_POSITION_PRAEREGISTRIERUNG.md` Abschnitt 2). Beide Abschnitte gelten deshalb **nicht als unberührter Endtest**. Sie dienen hier als Filter und Diagnose.
- Die Instrumente BTC/ETH/SOL wurden 2026 mit Wissen um das Überleben gewählt (Protokoll 3.1, Survivorship-Grenze).
- Vor dem Einfrieren bekannt (aus Labordateien): alle S7/S7b-Kennzahlen, die S32-Validierung (gleiche Regel auf 137 anderen Coins: Netto −0,026 R), der Deflated-Sharpe-Bericht (S7b-D20-T3 beide Abschnitte 0,81 bei N = 64), die Filter-Erkundung F1 bis F5, der Probelauf Juli bis Oktober 2026 (35 Trades, −0,17 R je Trade, nur berichtet), der Stand des Vorwärtsjournals (4 geschlossene Trades). Eigene Ergebnisse zu T2 bis T12 lagen **nicht** vor. Vorhanden waren nur die Nachrechnung (T1: alle gespeicherten Trades reproduziert), das Datenaudit und der Bitunix-Kerzenvergleich.
- Ein unberührter Endtest steht in diesem Auftrag **nicht** zur Verfügung. Der Holdout (2025-01-01 bis 2026-09) ist versiegelt und braucht Uzis ausdrückliches Wort und laut `S7B_MAKRO_FILTER.md` Abschnitt 6 (C) auch Bartis Zustimmung. Bestätigung kann damit nur vorwärts (Papier) oder über den Holdout kommen. Das Protokoll sagt das offen und plant den Vorwärtstest (Abschnitt 9).

## 2. Kandidaten (höchstens drei, vollständig festgelegt)

| Nr. | Name | Regel | Begründung der Auswahl (ohne Blick auf neue Ergebnisse) |
|---|---|---|---|
| C1 | Einfache starke Referenz | S7b-D20-T3 unverändert: Donchian-Ausbruch Kanal 20 in Richtung SMA200, 4h, BTC/ETH/SOL USD-M, Stop max(1,5 x ATR14; 1 %), Ziel 3R, Zeitstopp 30 Kerzen, höchstens eine Position, Reihenfolge BTC > ETH > SOL, Einstieg zur nächsten Eröffnung | Einziger Registereintrag mit Status `candidate` und stärkste Reihe laut Deflated-Sharpe-Bericht. T4 (Ziel 4R) läuft nur als Sensitivität mit, nicht als Kandidat |
| C2 | Sparsame Kombination | C1 als Trendanteil plus Funding-Carry auf BTC und ETH (Spot long, Perp short, gleiche Stückzahl, gleichgewichtet, immer investiert, kein Nachjustieren, ein Einstieg zu Beginn des Zeitraums). Kapitalaufteilung fest: 50 % Carry-Kapital, 50 % Reserve für den Trendanteil; der Trendanteil riskiert 1 % des **Gesamtkapitals** je Trade (nicht aufgezinst) | Zwei Befunde mit unterschiedlicher Ertragsquelle: Trendfolge (positive Schiefe, wenige Gewinner) und Funding (strukturelle Prämie, S33-Carry Training +8,5 % p. a. auf beide Beine, ungeprüft in der Validierung). Schwellen-Varianten des Carry werden nicht gerechnet (im Training schlechter, S33-Carry) |
| C3 | Universums-Variante | C1-Regel unverändert, aber nur BTC und ETH (Reihenfolge BTC > ETH) | SOL steht wegen Überlebens-Auswahl und fehlender Historie vor 2020-09 unter Survivorship-Verdacht. C3 misst, wie viel vom Befund an SOL hängt. Vor dem Rechnen erwartet: niedrigerer E[R] in der Validierung, weil ETH dort laut Labor nichts beiträgt |

Nicht gerechnet, aber im Register geführt: alle anderen Studien (Gründe im Register). Es gibt keinen vierten Kandidaten, keine Nachsuche an Parametern und keine Kombination aus Teilen, die nach Ergebnissen ausgewählt wurden.

## 3. Kostenszenarien (je Seite, wie Protokoll 4.4; Funding aus Binance-Historie als Stellvertreter)

| Name | Gebühr | Schlupf Einstieg / Ziel / Zeit | Schlupf Stop | Funding | Zweck |
|---|---:|---|---:|---|---|
| K0 Protokoll | 0,05 % | 0,03 % | 0,05 % | mit Gutschrift | Reproduktion |
| K1 Bitunix-Basis | 0,06 % (VIP0, unbestätigt) | 0,03 % | 0,05 % | mit Gutschrift | erwartete Kosten |
| K2 Bitunix-konservativ | 0,06 % | 0,06 % | 0,10 % | nur Zahlungen, keine Gutschrift | **Kriterium** |
| K3 Bitunix-pessimistisch | 0,06 % | 0,09 % | 0,15 % | nur Zahlungen, Faktor 1,5 | Stress |
| K4 Maker-Ziel (optimistisch) | 0,06 %; Ziel 0,02 % | Ziel 0; sonst 0,03 % | 0,05 % | mit Gutschrift | Obergrenze, kein Kriterium (Fill-Annahme „Berührung“ ungeprüft) |
| L1 Latenz | wie K1 | Einstieg eine 4h-Kerze später | wie K1 | wie K1 | extremer Verzögerungstest, kein Kriterium |

Unbekannte Gebühren werden nie als null gesetzt. `FEES_VERIFIED = False` im Code (`src/research_lab/bitunix/contract.py`); die VIP0-Werte stammen von Uzi (10.11.2026).

## 4. Tests und Kriterien

Alle Tests laufen für Training und Validierung getrennt (Abschnittsregel 1.2) und gepoolt. Kosten K1, wenn nichts anderes steht. „Besteht“ bedeutet: im Vorfeld festgelegte Schwelle erfüllt.

| Nr. | Test | Frage | Kriterium |
|---|---|---|---|
| T1 | Reproduktion | Stimmt der dokumentierte Code mit den Regeln der Präregistrierung überein? | **Erledigt vor dem Einfrieren**: unabhängige Neuimplementierung gegen alle gespeicherten S7- (3190) und S7b-Trades (1689), Abweichung unter 1e-12 |
| T2 | Kostenszenarien | Hält E[R] unter Bitunix-Kosten? Wo liegt die Bruchstelle? | **G2:** E[R] > 0 unter K2 in Training und Validierung. Zusätzlich: Vielfaches der Kosten (Gebühr und Schlupf), bei dem E[R] = 0 |
| T3 | Zufallsvergleich mit gleicher Richtung | Schlägt der Ausbruchszeitpunkt zufällige Einstiege in SMA200-Richtung (gleiche Stop-/Ziel-Geometrie, gleiche Positionsgrenze, gleiche Kosten)? | **G3:** einseitiges p ≤ 0,05 in Training und Validierung (1 000 Ziehungen, Seed 20261116; Ziehung je Instrument mit der Signalhäufigkeit des Kandidaten, Richtung = Seite des SMA200) |
| T4 | Parameter-Plateau | Liegt der Befund auf einer Hochebene oder einer Spitze? | **G4:** In den 81 Nachbarzellen (Kanal 15/20/30, Ziel 2/3/4 R, ATR-Faktor 1,0/1,5/2,0, Zeitstopp 15/30/60) ist E[R] in mindestens 70 % der Zellen > 0, in Training **und** in Validierung. Das ganze Raster (8 x 5 x 5 x 3) wird berichtet, keine Zelle wird ausgewählt |
| T5 | Komponenten-Entfernung | Welche Teile tragen den Erwartungswert? | Nur Bericht (Evidenzmatrix): ohne SMA200, ohne Mindestrisiko 1 %, ohne Zeitstopp, ohne Positionsgrenze, nur long, nur short, je Instrument, ohne Funding, gespiegelte Reihenfolge |
| T6 | Konzentration und Abhängigkeit | Hängt das Ergebnis an einzelnen Jahren, Instrumenten, Monaten, Extremtrades? | **G5:** gepoolter E[R] bleibt > 0, wenn jedes einzelne Jahr (5) und jedes einzelne Instrument (3) weggelassen wird. Außerdem berichtet: Anteil der besten 5 % Trades an der Gesamtsumme, E[R] ohne die besten 1/3/5/10 Trades, schlechtester und bester Monat |
| T7 | Unsicherheit mit Zeitabhängigkeit | Wie breit ist das Vertrauensband bei Autokorrelation und Clustern? | **G6:** gepoolte Untergrenze des 95-%-Intervalls (Monatsblock-Bootstrap, 10 000 Ziehungen, Seed 20261116) für E[R] > 0 unter K1. Berichtet: Wochen-t-Wert mit Newey-West (4 Verzögerungen), Intervalle für PF, Gesamt-R, größten Rückgang |
| T8 | Mehrfachtest | Übersteht der Befund die Zahl der Versuche in TIM? | **G7:** Deflated Sharpe je Trade (Bailey und López de Prado 2014, Schiefe und Kurtosis aus den Trades) bei N = 64 mindestens 0,95 (Konvention des Labors, `reports/deflated_sharpe_2026-11-11.md`). Berichtet für N = 58, 64, 100, 200 und N = 26 707 (inklusive OFX-Suche). Eigene Rechnung, nicht aus dem Bericht übernommen |
| T9 | Regime und Teilmengen | Wann wirkt es, wann nicht? | Nur Bericht: je Jahr, Halbjahr, Instrument, Seite, Volatilitäts-Terzile (30-Tage-Schwankung BTC), Ausstiegsgrund, gleitender 6-Monats-E[R] |
| T10 | Risikogleiche einfache Referenzen | Schlägt der Kandidat eine einfache Alternative gleichen Risikos? | Nur Bericht (Evidenzmatrix): (R1) Kaufen und Halten BTC/ETH/SOL gleichgewichtet, (R2) Long/Flat nach SMA200 auf demselben Korb, beide auf die Tagesschwankung des Kandidaten skaliert (Hebel höchstens 3), (R3) Bargeld |
| T11 | Carry-Komponente | Trägt Funding-Carry nach Kosten, auch in der Validierung? | **CG1:** Nettorendite auf das eingesetzte Kapital (beide Beine) in Training und Validierung jeweils über dem Geldmarkt-Vergleichswert (ANNAHME, Jahresmittel US-Schatzwechsel 2020: 0,4 %, 2021: 0,05 %, 2022: 2,0 %, 2023: 5,1 %, 2024: 5,0 %; nicht aus TIM-Daten, gerundet aus dem Gedächtnis). **CG2:** größter Rückgang unter 10 % des Kapitals. Berichtet: je Jahr, Basisrisiko, Liquidationsabstand bei Perp-Marge 20 %/50 %/100 % |
| T12 | Gemeinsames Kapitalmodell | Verbessert die Kombination das Risiko-Ertrags-Profil? | **G10 (nur C2):** Tagesrendite-Reihe auf Gesamtkapital; Monatsrenditen-Sharpe und größter Rückgang besser als beim reinen Trendanteil auf demselben Kapital, in Training und Validierung. Berichtet: Korrelation, Allokationen 0/25/50/75 % (nur Sensitivität, die Festlegung bleibt 50 %) |
| T13 | Bitunix-Übertragbarkeit | Ist die Regel auf Bitunix-Kerzen, -Kontrakten und -Büchern ausführbar? (Das Teilergebnis zu den Kerzen, −0,027 R, lag vor dem Einfrieren vor und zählt als berichtet, nicht als vorab festgelegt.) | **G11:** E[R] von C1 auf Bitunix-Kerzen (2022-04-17 bis 2024-12-31) weicht um weniger als 0,05 R von Binance im selben Fenster ab; Mindestmenge und Tick ermöglichen die Positionsgrößen bei 1 % Risiko ab 1 000 USDT Kapital. Unbestätigte Gebühren, Funding-Historie und Ausführung bleiben **offene Voraussetzungen** |
| T14 | Nach der Entwicklung beobachtet | Was sagen Daten nach 2024? | Nur Bericht, kein Kriterium: Vorwärtsjournal S7b (seit 2026-11-01) und der berichtete Probelauf Juli bis Oktober 2026. Beide zählen nicht als Bestätigung: das Journal hat zu wenige Trades, der Probelauf wurde in der Prüfmethode versehentlich gesehen und nicht aufbewahrt |

**Weitere Prüfungen (nicht als Kriterien, aber im Ergebnisordner):** Datenaudit der Binance-Archive (`ergebnisse/datenaudit.json`), Abgleich der Bitunix-Kerzen mit Binance, Orderbuch-Momentaufnahme Bitunix.

## 5. Kriterien-Block und Urteilsregel

Kriterien für „historisch robust“ (alle erforderlich, Schnittmengen-Test, keine Aufblähung der Fehlerrate):

- **G1** Reproduktion bestanden (T1).
- **G2** Kosten (T2): E[R] > 0 unter K2 in beiden Abschnitten.
- **G3** Zufallsvergleich in SMA200-Richtung (T3): p ≤ 0,05 in beiden Abschnitten.
- **G4** Parameter-Plateau (T4): mindestens 70 % der 81 Nachbarzellen positiv, in beiden Abschnitten.
- **G5** Konzentration (T6): gepoolter E[R] > 0 bei Weglassen jedes Jahres und jedes Instruments.
- **G6** Unsicherheit (T7): gepoolte Untergrenze des 95-%-Intervalls > 0 unter K1.
- **G7** Mehrfachtest (T8): DSR bei N = 64 mindestens 0,95.
- **G8** Übertragung auf ein unabhängiges Universum: Die S7b-Regel ist auf dem Punkt-in-Zeit-Universum von 137 Coins (S32, Validierung, ein Lauf) mit Netto-E[R] > 0 bestanden. **Ergebnis liegt vor dem Einfrieren vor: nicht bestanden (Netto −0,0255 R).** G8 gilt unverändert für C1 und C3 und bleibt stehen. Für C2 gilt G8 nur für den Trendanteil
- **G11** Übertragbarkeit auf Bitunix (T13).

Für die Carry-Komponente von C2: **CG1** und **CG2** (T11). Für C2 als Ganzes: **G10** (T12).

Urteilsstufen (nur Papier und Analyse; keine Stufe erlaubt Echtgeld):

1. **KEIN BELASTBARER VORTEIL:** Für jeden der drei Kandidaten scheitert G1 oder G2 (C2: der Trendanteil scheitert an G1/G2 und der Carry an CG1).
2. **INTERESSANTE HYPOTHESE, EVIDENZ UNZUREICHEND:** G1 und G2 bestanden, aber mindestens eines von G3 bis G8, G11 (oder CG1/CG2, G10 für C2) nicht erfüllt.
3. **HISTORISCH ROBUST, PROSPEKTIVER TEST AUSSTEHEND:** alle Kriterien bestanden (G1 bis G8, G11, bei C2 zusätzlich CG1, CG2, G10), aber keine unabhängige Bestätigung außerhalb der Entwicklung.
4. **FÜR BEGRENZTES PAPER-TRADING GEEIGNET:** Stufe 3 **und** vorab festgelegte vorwärts beobachtete Mindestzahl erreicht (mindestens 30 geschlossene Papier-Trades mit E[R] > 0 unter K2 und Zahl der Stopps im erwarteten Bereich) **oder** ein einmaliger, von Uzi und Barti freigegebener Holdout-Lauf mit vorab festgelegten Kriterien bestanden. Das Gesamturteil ist die höchste Stufe, die ein Kandidat erreicht.

## 6. Statistik

- Monatsblock-Bootstrap: Ziehung ganzer Kalendermonate mit Zurücklegen aus den Monaten, in denen der Abschnitt läuft; Trades gehören dem Monat ihres Signals. 10 000 Ziehungen, Seed 20261116.
- Zufallsvergleich T3: je Ziehung für jedes Instrument zufällige Signalkerzen aus den Kerzen mit gültigem Vorlauf; Wahrscheinlichkeit je Kerze = beobachtete Signalhäufigkeit des Kandidaten je Instrument und Abschnitt; Richtung = Seite des SMA200; sonst identisch zum Kandidaten (Stop, Ziel, Zeitstopp, Positionsgrenze, Kosten). p = Anteil der Ziehungen mit E[R] mindestens so groß wie beim Kandidaten (plus 1 im Zähler und Nenner).
- Deflated Sharpe: PSR(SR0) mit SR0 = sqrt(Varianz der Versuchs-Sharpes) x ((1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e))), γ = 0,5772. Varianz der Versuchs-Sharpes = 1/(n − 1) (Nullfall, wie im Labor-Bericht); als Gegenprobe die empirische Streuung der Sharpes über das Parameter-Raster aus T4.
- Alle Zufallszahlen: `numpy.random.default_rng(Seed)`; Seeds im Ergebnisordner.
- Keine p-Wert-Korrektur über T2 bis T14 nötig, weil die Kriterien eine Schnittmenge bilden; Einzelbefunde aus T5, T9, T10 sind beschreibend und werden nicht als Beleg gezählt.

## 7. Optimierungsbudget, Auswahlregel, Abbruch

- **Optimierungsbudget:** null. Kein Parameter wird angepasst. Das Raster in T4 dient nur der Stabilitätsprüfung; seine Zellen zählen zu den Versuchen für die Deflated-Sharpe-Gegenprobe, nicht als Auswahlmenge.
- **Auswahlregel:** keine Auswahl unter den Kandidaten nach Ergebnis. Es werden alle drei mit denselben Kriterien berichtet. Das Gesamturteil ist die höchste Stufe, die ein Kandidat erreicht. Die Kandidaten werden nicht nachträglich umdefiniert.
- **Abbruch:** Reproduktion weicht ab (T1) oder die Datenprüfung zeigt einen Integritätsfehler: Auswertung der betroffenen Reihe stoppt, Befund wird berichtet. Ein Test, der den Holdout bräuchte, wird nicht gerechnet.
- **Nicht entfernt:** Fehlgeschlagene Studien und Varianten bleiben im Register und in der Evidenzmatrix. Korrigierte Ergebnisse stehen getrennt von den ursprünglichen.

## 8. Ergebnisablage und Reproduktion

- Code: `src/research_lab/konsolidierung/`. Ergebnisse: `docs/research_lab/konsolidierung/ergebnisse/`. Grafiken: `grafiken/`.
- Jeder Test schreibt eine JSON-Datei mit Code-Stand (Git-Hash), Daten-Fingerabdruck (`datenaudit.json`), Konfiguration, Befehl, Zeitraum und Status. Das Testlog (`TESTLOG.md`) führt je Test: Code-Version, Datenversion, Konfiguration, Befehl, Zeitraum, Ergebnisdatei, Status, Grenzen.
- Rohdaten (Binance-Archive, Bitunix-Kerzen) liegen nicht im Repo (Größe, Lizenz); Herkunft und SHA-256 stehen im Datenaudit.

## 9. Was als unabhängige Bestätigung zählen würde (Plan, nicht Teil dieses Laufs)

1. **Vorwärtstest (Papier):** S7b-D20-T3 läuft seit 2026-11-01 im Hash-Ketten-Journal (nur Papier). Vorab festgelegte Mindestzahl für Stufe 4: 30 geschlossene Trades unter K2-Kosten, Auswertung genau einmal; endgültiges Urteil bei 100 Trades (Mindestzahl aus S7b-Präregistrierung Abschnitt 5.1), nach der bisherigen Rate von 8 bis 9 Trades im Monat etwa 12 Monate.
2. **Holdout einmalig (nur mit Uzis ausdrücklichem Wort und Bartis Zustimmung):** S7b-D20-T3 mit den hier festgelegten Kosten K1/K2 und Kriterien G2, G6 auf 2025-01-01 bis 2026-09. Der Zeitraum Juli bis Oktober 2026 ist durch den Probelauf bereits gesehen und müsste getrennt ausgewiesen werden.
3. **Neue Daten:** Bitunix-eigene Kerzen und -Bücher ab Kontraktstart (2024-06-26) sind vorhanden, aber kurz; sie ersetzen keinen Test.
