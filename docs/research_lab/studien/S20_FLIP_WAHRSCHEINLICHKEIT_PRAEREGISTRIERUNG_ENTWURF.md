# S20: Flip-Wahrscheinlichkeit aus der Kerzenstruktur: Sagen Körper, Dochte, Spanne und die Kerzen davor voraus, ob eine gebrochene Linie als neues Level hält, und wie viele Kerzen braucht man dafür? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S20 (nächste freie Nummer nach S19, 09.11.2026) |
| Version | **0.2, Entwurf.** Regeln als Code: `src/research_lab/studies/s20.py`, Tests `tests/test_research_lab_s20.py`. Keine Daten geladen, kein Zähllauf. `evaluate` verweigert den Lauf, solange die Version mit 0 beginnt |
| Anlass | Barti 09.11.2026: „Kann man aus einer Kombination aus den Candles, also den Hochs, den Tiefs, auch den Dochten, eine Wahrscheinlichkeit für den Flip berechnen?“ und „wie viele berücksichtigte Kerzen liefern das beste Ergebnis?“ |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Daten | Binance Spot BTCUSDT, 1h-Kerzen aus dem öffentlichen Archiv (`data.binance.vision`), 2017-08 bis 2024-12, Prüfsumme je Monatsdatei (`ArchiveStore`) |
| Holdout | ab 2025-01-01, wird nicht geladen (`refs()` endet 2024-12, `section_of` kennt 2025 nicht). Training bis 2022-12-31, Validierung 2023-01-01 bis 2024-12-31 |
| Einordnung | **Beobachtungsstudie ohne Trades, ohne Registerplatz** (wie S15/S17/S19, Entscheidung Uzi beim Einfrieren). Sie misst, ob eine Wahrscheinlichkeit trägt. Kein Setup, kein Edge-Nachweis in R, keine Holdout-Erlaubnis, kein Filter für S7b (Abschnitt 8) |

## 1. Fragestellung

Ein **Flip** ist: Eine Kerze schließt klar jenseits einer wichtigen Linie, und die Linie hält danach als neues
Level (alter Widerstand wird Unterstützung oder umgekehrt). Ein **Fehlausbruch** ist: Der Kurs schließt kurz
danach wieder auf der alten Seite.

1. **H1: Sagt die Kerzenstruktur beim Bruch den Flip besser voraus als der bloße Abstand zur Linie?** Ein
   Modell aus Merkmalen der Bruchkerze und der Kerzen davor gibt jedem Bruch eine Flip-Wahrscheinlichkeit. Es
   muss in der Validierung 2023–2024 einen kleineren Log-Verlust haben als das **Mechanik-Modell**, das nur
   den Abstand des Schlusses zur Linie in ATR kennt. Begründung: Auch bei einem reinen Zufallspfad hält ein
   weit überschrittenes Level öfter als ein knapp überschrittenes. Das ist Mechanik, keine Kerzenstruktur.
   Ein Vergleich nur gegen die Basisrate würde diesen trivialen Effekt als Erfolg zählen (am synthetischen
   Zufallspfad nachgeprüft, Abschnitt 7).
2. **H2: Bringen die Kerzen vor dem Bruch etwas über die Bruchkerze hinaus, und wie viele?** Raster
   N = 5, 10, 20, 50 Kerzen. Welches N gilt, entscheidet **nur das Training**; die Validierung sieht genau
   ein N und prüft, ob das Fenster-Modell besser ist als das Modell nur aus der Bruchkerze.

Nicht geprüft: Einstieg, Stop, Ziel, Kosten, Gewinn in R, Kombination mit Makro-Treibern oder Orderflow.
Das wäre eine eigene Studie mit eigener Präregistrierung (Abschnitt 8).

## 2. Vorbelastung

- **S7/S7b** (Donchian-Ausbruch auf 4h, BTC/ETH/SOL 2017–2024): Ausbrüche über das 20-Kerzen-Hoch sind
  verwandt mit Brüchen von Swing-Hochs. Ergebnisse in R von S7/S7b und die Makro-Filter F1–F5 sind gesehen.
  Belastend: Wer die S7-Berichte kennt, weiß grob, wie oft BTC-Ausbrüche 2017–2024 weiterlaufen. Daten
  von BTC 2017–2024 sind damit nicht frisch; den frischen Test liefert erst der Holdout oder der Vorwärtslauf.
- **S9** (CHoCH → Retest, 15m) und **S10** (IB-Ausbruch → POC-Retest): beide am Machbarkeits-Gate beendet,
  ohne Ergebnis. Lehre: Ereignisregeln mit vielen Bedingungen liefern zu wenige Fälle. S20 hält die Regel
  deshalb bewusst einfach (eine Pivot-Regel, eine Bruch-Schwelle, ein Haltefenster).
- **S19** (Orderflow-Schwellen, Entwurf): misst Richtungsneigung nach Flags, nicht Halten eines Levels.
- **Gesehen vom Autor:** keine Statistik zu Flip-Quoten von Swing-Levels an BTC. Barti kennt Flips aus dem
  Chart (Lehrbuch-Wissen „Support wird Resistance“), das ist die Herkunft der Idee.

**Gegenargument:** Ob ein Ausbruch hält, hängt stark von Markt-Regime und Nachrichten ab, die in der Kerze
nicht stehen. Kerzenmuster haben in der Literatur meist kleine, instabile Effekte. Ein Modell kann außerdem
nur „Volatilität“ lernen (große Kerze → großer Abstand zur Linie → hält öfter), was trivial wäre.
Deshalb misst H1 gegen das Mechanik-Modell und nicht gegen die Basisrate, und das Urteil verlangt
zusätzlich einen Mindest-Abstand zwischen oberem und unterem Fünftel (Abschnitt 5).

## 3. Ereignisse (vorab festgelegt)

| Regel | Festlegung | Konstante |
|---|---|---|
| Linie | Swing-Hoch: Hoch der Kerze i liegt **über** den 24 Kerzen davor und **mindestens so hoch** wie die 24 danach. Swing-Tief spiegelbildlich. Keine Lücke in den 49 Kerzen | `PIVOT_K = 24` |
| Bekannt ab | Schluss der Kerze i + 24 (keine Vorausschau); aktiv ab Kerze i + 25 | |
| Lebensdauer | 30 Tage nach Bestätigung | `LEVEL_MAX_AGE = 720` |
| Bruch (Ereignis) | erster Schluss mindestens 0,25 × ATR14 jenseits der Linie („klar“). Ein Schluss knapp jenseits lässt die Linie leben. Mit dem klaren Bruch ist die Linie verbraucht. Brechen mehrere Linien zugleich klar, zählt die dem Schluss nächste, die anderen sind ebenfalls verbraucht | `BREAK_ATR = 0.25` |
| Flip (Label 1) | in den 24 Kerzen nach dem Bruch **kein** Schluss zurück auf der alten Seite (bei Bruch nach oben: jeder Schluss > Linie) | `HOLD_BARS = 24` |
| Fehlausbruch (Label 0) | mindestens ein Schluss zurück auf der alten Seite in diesen 24 Kerzen | |
| Ausschluss | Lücke in den 65 Kerzen davor oder den 24 danach; Haltefenster über das Abschnittsende; zweites Ereignis derselben Richtung innerhalb von 24 Kerzen nach dem letzten (Entprellung) | |

Die Ereignismenge ist für alle Fenstergrößen **dieselbe** (Rücklauf immer 50 + 15 Kerzen). Damit vergleicht
das Raster nur Merkmale, nicht unterschiedliche Stichproben.

## 4. Merkmale, Modell und Fensterwahl

### 4.1 Merkmale (am Schluss der Bruchkerze, in Bruchrichtung gespiegelt)

Bruchkerze (7, ohne Fenster): Körper/Spanne mit Vorzeichen; Docht gegen die Bruchrichtung/Spanne; Abstand
Schluss–Linie in ATR; Spanne in ATR; Taker-Saldo (Käufer minus Verkäufer durch Volumen); Alter der Linie;
Richtung (oben = 1).

Fenster der N Kerzen davor (5): Log-Volumenverhältnis Bruchkerze zu Fenstermittel; Anteil Kerzen, die die
Linie bis auf 0,25 ATR getestet haben; Momentum (Schluss heute minus Schluss vor N, in ATR·√N); Kompression
(Fenster-Spanne in ATR·√N); mittlerer Abweisungsdocht auf der Seite der Linie in ATR.

Keine weiteren Merkmale, keine Interaktionen, keine Transformationen nach Sicht auf Ergebnisse.

### 4.2 Modell und Fensterwahl

- Logistische Regression mit festem L2-Strafterm 1,0 auf standardisierten Merkmalen (Achsenabschnitt frei),
  Standardisierung nur aus den Anpassungsdaten. Kein Tuning des Strafterms, kein zweites Modell im Urteil.
  Ein Entscheidungsbaum wurde erwogen und verworfen: mehr Stellschrauben (Tiefe, Blattgröße), höheres Risiko
  von Curve-Fitting bei rund 1 000–2 000 Ereignissen.
- **Fensterwahl nur im Training:** vorwärts verkettete Kreuzvalidierung über die Jahre 2019, 2020, 2021,
  2022 (anpassen auf allen Ereignissen vor dem Jahr, bewerten im Jahr), Kriterium mittlerer Log-Verlust.
  Gewählt wird **das kleinste N, dessen Verlust höchstens 0,0005 über dem besten liegt** (Einfachheit vor
  Randwert). Die Kreuzvalidierungs-Zahlen aller N werden berichtet.
- Danach **eine** Anpassung auf dem ganzen Training mit dem gewählten N und eine Anpassung des
  Nur-Kerze-Modells, dann **ein** Blick auf die Validierung.

## 5. Erfolgskriterien

Statistik je Hypothese: mittlerer Unterschied des Log-Verlusts je Ereignis in der Validierung, p einseitig
aus einem Block-Bootstrap über Ereignis-Wochen (Blocklänge 4 Wochen, 9 999 Ziehungen, Seed 20). Holm über
H1 und H2 zusammen (m = 2), Familien-α = 5 %.

**H1 gilt als bestanden**, wenn in der Validierung alles zugleich gilt:

| # | Kriterium |
|---|---|
| 1 | Machbarkeits-Gate 5.1 bestanden |
| 2 | Log-Verlust mindestens 1 % unter dem Mechanik-Modell (Abstand zur Linie allein, im Training angepasst) |
| 3 | Holm-korrigiert p < 0,05 |
| 4 | AUC ≥ 0,55 |
| 5 | Flip-Quote im oberen Fünftel der Vorhersagen mindestens 10 Prozentpunkte über dem unteren Fünftel |
| 6 | **Glückstest** p < 0,05: Die Labels werden je Abschnitt im Kreis gegen die Merkmale verschoben (mindestens 100 bzw. 50 Ereignisse), und die **ganze** Kette läuft neu: Fensterwahl im Training, Anpassung, Validierung. 199 Verschiebungen, Seed 20. p = Anteil der Verschiebungen, deren Gewinn gegen das Mechanik-Modell den beobachteten erreicht |

**H2 gilt als bestanden**, wenn H1 bestanden ist, das Fenster-Modell in der Validierung einen kleineren
Log-Verlust hat als das Nur-Kerze-Modell und das Holm-korrigierte p < 0,05 ist. Dann lautet die Antwort auf
Bartis Frage „N Kerzen“; sonst „die Kerzen vor dem Bruch bringen nichts über die Bruchkerze hinaus“.

Ergebnis: „BESTANDEN (Kandidat)“ mit oder ohne Fenster, oder „NICHT BESTANDEN“. Auch „bestanden“ heißt
nur: Kandidat für einen Vorwärtslauf. Es wird nichts in die Engine übernommen (Abschnitt 8).

### 5.1 Machbarkeits-Gate (ergebnisblind, vor jedem Label)

Zähllauf (`count`) nur mit Ereigniszahlen, Wochen, Richtungen, Jahren und Ausschlussgründen, ohne Label.
Mindestens 400 Ereignisse und 100 Wochen im Training, 150 Ereignisse und 50 Wochen in der Validierung.
Das Gate wird nicht gelockert; fällt es durch, heißt das Ergebnis „nicht testbar“, und die Regeln in 3 werden
**nicht** nachträglich gelockert, um mehr Ereignisse zu bekommen.

### 5.2 Beschreibend, ohne Urteil

Flip-Quote je Abschnitt, Jahr und Richtung; Gewinn von Modell und Mechanik-Modell gegen die Basisrate;
Kalibrierung in Zehnteln; Brier-Skill; standardisierte Koeffizienten. Daraus wird kein Bestehen abgeleitet und keine Regel geändert.

## 6. Was nicht geändert wird

- Keine anderen Pivot-, Bruch- oder Haltewerte als in 3, kein weiteres Fenster als 5/10/20/50, keine
  weiteren Merkmale, kein zweiter Modelltyp im Urteil.
- Zwischenstände werden vor dem vollständigen Lauf nicht angesehen. Kein Lauf auf ETH/SOL als „zweiter
  Versuch“; das wäre eine neue Studie.
- Chart, Engine, S7b-Schatten und Vorwärts-Logs bleiben bis zum Ergebnis unverändert.

## 7. Ablauf bis 1.0

1. Code und Tests (0.2, erledigt): Pivots ohne Vorausschau, Bruch/Ereignis/Label, Merkmale je Fenster,
   logistische Regression ohne Fremdpakete, Kreuzvalidierung, Block-Bootstrap, Holm, Glückstest mit
   Fensterwahl, Sperre von `evaluate` vor 1.0. Tests mit synthetischen Kerzen: Pivot erst nach 24 Kerzen
   bekannt, Lücke, klarer/unklarer Bruch, Fehlausbruch, Merkmale unabhängig von Kerzen nach dem Bruch,
   Abschnittsende, Entprellung, Holdout, Fensterwahl, gepflanztes Signal besteht, Rauschen fällt durch,
   reiner Abstands-Effekt fällt durch. Gegenprobe am synthetischen Zufallspfad (BTC-ähnliche 1h-Kerzen
   2017-08 bis 2024, keine echten Daten): 602/223 Ereignisse, Fenster-Wahl 5, Gewinn gegen Mechanik −0,6 %,
   Urteil NICHT BESTANDEN, wie es bei Zufall sein muss. Laufzeit der Auswertung mit 19 Verschiebungen: 5 s.
2. Zähllauf auf PS5 oder Mac:
   `python -m src.research_lab.studies.s20 count --root data/research_lab --out ~/tim-research/results/s20 --fetch`
   Ergebnis nur mit Zahlen; `evaluate` ist vor 1.0 im Code gesperrt.
3. Uzis Wort (und Bartis): Einfrieren als 1.0 mit Commit (`VERSION = "1.0"`), Einordnung ins Protokoll.
4. Ergebnislauf: `python -m src.research_lab.studies.s20 evaluate --root data/research_lab --out ... --workers 16`.
   Bericht nach Abschnitt 5.

## 8. Einordnung ins Gesamtsystem

- **Was es wäre:** ein preisbasierter Baustein neben den Makro-Treibern (F5 Realzins, F3 Netto-Liquidität)
  und dem Einfluss-Barometer. Die Makro-Treiber sagen „Rückenwind oder Gegenwind über Wochen“, S20 würde
  sagen „hält dieser einzelne Bruch eher oder nicht“ auf Stunden.
- **Natürlicher Ort:** S7b handelt Ausbrüche. Eine Flip-Wahrscheinlichkeit wäre dort ein Filter („nur
  Ausbrüche mit hoher Halte-Wahrscheinlichkeit“), im Setup-Pfad ein Hinweis zur Setup-Güte.
- **Grenze aus dem Register:** Für S7b sind die vorregistrierten Filterfragen auf 2017–2024 verbraucht
  (F1–F5, Glückstest 02.11.2026 nicht bestanden). Ein S20-Filter auf S7b wäre eine weitere Frage auf
  denselben Daten. Deshalb: Auch ein bestandenes S20 geht **nicht** direkt in S7b, sondern höchstens in einen
  vorab festgelegten Vorwärtslauf (wie das F3/F5-Log) oder in den Holdout, wenn Uzi und Barti ihn freigeben.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-09 | 0.1 | Entwurf aus Bartis Frage. Kein Code, keine Daten geladen, kein Registereintrag. |
| 2026-11-09 | 0.2 | Code und Tests (`s20.py`, 19 Tests). Knapper Schluss lässt die Linie leben; H1 misst gegen das Mechanik-Modell statt gegen die Basisrate (Zufallspfad-Gegenprobe hatte gezeigt, dass schon der Abstand allein die Basisrate schlägt). Noch kein Zähllauf, keine echten Daten geladen. |
