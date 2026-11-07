# Einfluss-Barometer: Einflüsse auf BTC erkennen, messen und erklären (Entwurf)

| Feld | Wert |
|---|---|
| Status | **Entwurf**, gilt erst nach Freigabe durch Barti und Uzi |
| Stand | 06.11.2026 |
| Gehört zu | BTC Research Engine, Stufe V2 „Historical Relationship Analysis“ (`EXTERNAL_DATA.md`, Abschnitt 12) |
| Vorhandener Code | `src/research_lab/external/` (CPI, FOMC), `src/research_lab/forward/macro_filters.py` (Vorwärts-Log F3/F5, Barometer), `src/dashboard/macro_calendar.py` (Chart-Marker) |
| Verwandt | `FORSCHUNGSBEREICH.md` (Werkstatt), `studien/S7B_MAKRO_FILTER.md`, `studien/S1_CPI_VOLATILITAET.md` |

## 1. Warum ein eigener Bereich

Die Forschungswerkstatt (`FORSCHUNGSBEREICH.md`) prüft Handelsregeln: Idee, Anmeldung, Rechnung auf historischen
Marktdaten, Urteil, prospektiver Test. Die Reflexion von TIMs eigenen Trades ist nur ein Teil davon. Die Einfluss-Messung fragt etwas anderes: **Welche Bereiche außerhalb des
Kryptomarkts bewegen BTC, wann und wie stark?** (Treiber aus dem Kryptomarkt selbst: Abschnitt 5b.) Beispiele sind Realzins, Dollar, Liquidität der Notenbank,
CPI- und Fed-Termine, Wahlen und große Nachrichten.

Beides wurde bisher vermischt. F1–F5 waren Filterfragen an S7b (Werkstatt-Art), das Barometer ist eine Beschreibung
(Einfluss-Art). Dieser Entwurf trennt die beiden: Die Einfluss-Messung beschreibt und liefert Hypothesen, die
Werkstatt prüft Regeln.

Kurz gefasst:

- **Ziel:** Einflüsse auf BTC erkennen, messen und erklären.
- **Darf:** beschreiben, Treiber beobachten, Hypothesen formulieren.
- **Darf nicht:** Handelssignale erzeugen oder Trades beeinflussen.
- **Übergang:** Eine Hypothese, die zur Regel werden soll, geht als Idee in die Werkstatt, so wie F5 es getan hat.
- **Zuordnung:** Der Bereich ist der Anfang von V2 der BTC Research Engine („Historical Relationship Analysis“:
  Ereignisstudien, Vor- und Nachlauf, rollierende Zusammenhänge). V2 startet trotzdem erst nach der PRE-V2-Prüfung
  in Abschnitt 6 und Bartis Go.

## 2. Was der Bereich darf und was nicht

Er darf:

- externe Reihen und Ereignisse zeitlich korrekt sammeln (Point-in-Time-Regel, `EXTERNAL_DATA.md` Abschnitt 3),
- beschreiben, wie BTC um Ereignisse und bei Bewegungen der Treiber reagiert hat (Schwankung, Richtung, Lead/Lag,
  rollierende Zusammenhänge),
- ein wöchentliches Barometer und Chart-Marker liefern,
- Hypothesen in die Ideen-Liste der Werkstatt geben.

Er darf nicht:

- Handelsregeln aufstellen, Signale sperren oder freigeben. Eine Regel entsteht nur in der Werkstatt mit eigener
  Anmeldung und eigenem Test.
- BTC-Daten ab 2025-01-01 laden (Holdout, `FORSCHUNGSBEREICH.md`, Feste Grenzen).
- Aus einem einzelnen Ereignis eine Aussage über Ursache und Wirkung machen.
- Echtgeld berühren.

## 3. Datenregeln

1. **BTC-Seite:** historisch nur Daten bis 2024-12-31. Live-Beobachtungen ab November 2026 gelten als eigener,
   neuer Zeitraum und werden nur beschrieben, nie als Holdout ausgewertet.
2. **Treiber-Seite:** Werte nur so, wie sie zum jeweiligen Zeitpunkt bekannt waren. Wo es Vintages gibt (ALFRED),
   werden sie benutzt. Das Live-Log (`macro_filters.py`) hält jeden Abruf mit Zeitstempel und SHA-256 der Rohantwort fest.
3. **Einheiten** je Reihe aus der Quelle lesen, nie annehmen (Beispiel WTREGEN: Millionen statt Milliarden).
4. **Ereigniszeit:** Jedes Ereignis braucht eine belegte Zeit (Quelle + Uhrzeit in UTC). Ohne belegte Zeit kommt es
   nicht in eine Rechnung, nur in den Kalender mit Vermerk „Zeit unbelegt“.
5. **Mehrfachtests:** Jede beschreibende Auswertung wird mit Datum ins Register eingetragen. Wer später daraus eine
   Regel macht, muss die Zahl der vorher angeschauten Treiber angeben (siehe Glückstest in `S7B_MAKRO_FILTER.md`).

## 4. Ereignisarten

### 4.1 Geplante Ereignisse

Das Datum steht vorher fest. Sie können vorab in den Kalender und als Marker in den Chart.

| Ereignis | Beispiel | Messung |
|---|---|---|
| US-CPI | monatlich, 08:30 ET | vorhanden (S1, V1/V1.1) |
| FOMC-Entscheidung | 8× im Jahr, 14:00 ET | vorhanden (V1.2) |
| US-Wahlen | Midterms 2018, 2022, 2026; Präsidentschaft 2020, 2024 | Schwankung und Richtung am Tag und in der Nacht der Auszählung gegen normale Tage |
| Arbeitsmarktbericht (NFP) | erster Freitag im Monat, 08:30 ET | wie CPI |
| Jackson Hole, wichtige Fed-Reden | jährlich bzw. nach Kalender der Fed | wie FOMC, Zeit = Redebeginn |
| SEC-Fristen zu Krypto-ETFs | Entscheidungstermine laut Federal Register | Reaktion am Fristtag |
| Halving, große Options-Verfallstage, Auszahlungen (z. B. Mt. Gox) | nach festem Plan | Reaktion am Termin |

### 4.2 Ungeplante Nachrichten

Börsen-Hacks, Regulierungsschläge, Kriege, plötzliche politische Entscheidungen. Sie lassen sich nur hinterher messen.
Dafür braucht es eine Quelle mit genauen Veröffentlichungszeiten (Kandidat: GDELT, kostenlos). Ohne eine solche Quelle
sucht man mit dem Wissen von heute die passenden Fälle heraus, und das Ergebnis wäre geschönt. Diese Familie ist
deshalb der aufwendigere Teil und kommt zuletzt.

### 4.3 Ehrliche Grenzen

- Wahlen sind selten. Bis Ende 2024 gibt es je nach Datenbeginn vier bis fünf US-Wahltage. Das reicht für eine
  Beschreibung, nicht für einen Beweis.
- Der Kursrückgang um die Midterms am 03.11.2026 liegt im Live-Zeitraum. Er wird als Live-Ereignis beschrieben.
  Ob er an der Wahl lag oder an etwas anderem in derselben Woche (zum Beispiel dem steigenden Realzins), lässt sich
  an einem Fall nicht trennen. Dafür ist die Messung über viele Ereignisse da.

## 5. Ergebnisse des Bereichs

1. **Wöchentliches Barometer** (läuft seit 04.11.2026 als `macro_filters barometer`, montags 09:30 auf dem Mac):
   Stand der Treiber und ihre historische Wirkung bis 2024, ausdrücklich keine Prognose.
2. **Treiber-Katalog:** je Treiber Quelle, Einheit, Zeitregel, historische Beschreibung und Datum der Auswertung.
3. **Ereigniskalender** für den Chart (`data/macro/calendar.json`). Heute kennt der Chart nur CPI und FOMC
   (`KINDS` in `src/dashboard/macro_calendar.py`, auch die kommenden Termine aus #127). Vorschlag: weitere Arten
   `ELECTION` und `NFP` als erstes Paket, damit Ereignisse wie die Midterms vorher im Chart stehen.
4. **Hypothesen-Liste:** Was auffällt, geht als Idee an die Werkstatt, mit Zahl der angeschauten Treiber.
   Hypothesen, die BTC gar nicht berühren, bleiben hier und brauchen keinen Registerplatz. Beispiel: die
   Öl-Hypothese Stufe 1 (Öl → Inflationserwartung → Realzins); erst eine Stufe mit BTC ginge an die Werkstatt.

## 5a. Treiber-Research (Wunsch Uzi, 07.11.2026)

Das Barometer zeigt heute feste Zahlen je Treiber (`HISTORY` in `macro_filters.py`, einmal 2017–2024 gerechnet).
Ziel ist, den Einfluss **jedes** vermuteten Treibers selbst untersuchen zu können, nicht nur die heute eingebauten.

1. **Treiber-Katalog als Liste:** Jeder Treiber (Dollar, Realzins, 10J-Rendite, S&P 500, Nasdaq, Gold, Öl, VIX,
   Liquidität, M2, Spread …) steht mit Quelle, Einheit, Zeitregel und Datenbeginn an einer Stelle. Ein neuer Treiber
   ist ein neuer Eintrag, kein neuer Code.
2. **Gleiche Auswertung für alle:** Für jeden Treiber dieselben beschreibenden Kennzahlen auf BTC bis 2024-12-31:
   BTC-Rendite in Phasen „gestiegen“ und „gefallen“ (13 Wochen), Gleichlauf (Korrelation der Wochenrenditen),
   Vorlauf/Nachlauf (1–4 Wochen) und rollierende Korrelation (52 Wochen), damit sichtbar wird, ob ein Zusammenhang
   stabil ist oder nur in einem Regime (z. B. 2022) auftritt.
3. **Ergebnis je Treiber** als Bericht mit Datum der Auswertung und Zahl der bis dahin angeschauten Treiber
   (Mehrfachtests, Abschnitt 3 Punkt 5). Das Barometer liest seine historischen Zahlen dann aus diesen Berichten
   statt aus fest eingetragenen Werten.
4. **Grenze bleibt:** Die Auswertung beschreibt nur. Wer aus einem Treiber eine Handelsregel machen will, meldet sie
   in der Werkstatt an, wie bei F5.

Das ist Teil von V2 und startet erst nach Abschnitt 6 und Bartis Go.

## 5b. Treiber aus dem Kryptomarkt (Vorschlag Uzi, 07.11.2026)

Die Grenze zwischen diesem Bereich und der Werkstatt ist „beschreiben oder Regel“, nicht „außerhalb oder innerhalb
des Kryptomarkts“. Treiber aus dem Kryptomarkt (ETF-Zuflüsse, Stablecoin-Menge, Dominanz, Funding, Open Interest,
Liquidationen) dürfen deshalb hier beschrieben werden, unter denselben Regeln wie alle anderen.

Zusatzregel für Reihen, die dem Kurs selbst folgen (Funding, Open Interest, Liquidationen): Sie gelten nur dann als
Treiber, wenn sie sich messbar **vor** der BTC-Bewegung bewegen (Vorlauf, Abschnitt 5a Punkt 2). Ein reiner Gleichlauf
wird als „folgt dem Kurs“ berichtet, nicht als Einfluss. Eine Handelsregel aus einer dieser Reihen geht weiter als
Idee in die Werkstatt.

## 6. PRE-V2-Prüfung der Datenfamilien

Regel von Barti (23.10.2026): V2 beginnt nie automatisch. Jede Datenfamilie bekommt nach Prüfung von Quelle, Lizenz,
Historie und Point-in-Time einen Status IMPLEMENTED, DEFERRED oder REJECTED mit Begründung. DEFERRED und REJECTED
gelten erst mit Bartis Zustimmung, eine offene Familie blockiert V2. Ohne Bartis Go danach gilt `V2_START_ALLOWED=NO`.

Die Tabelle unten ist ein **Vorschlag** und noch nicht vollständig. Das Inventar aller Treiber-Familien liegt außerhalb
des Repos; die übrigen Familien werden in der Prüfung ergänzt. Bis dahin: `V2_START_ALLOWED=NO`.

| Familie | Status | Begründung |
|---|---|---|
| US-CPI (ALFRED, Vintages) | IMPLEMENTED | V1/V1.1, Point-in-Time geprüft, echtes Fixture |
| FOMC-Erklärungen und Zinsspannen | IMPLEMENTED | V1.2 |
| Realzins, Dollar, 10J-Rendite, Öl, Breakeven, VIX (FRED) | IMPLEMENTED (live) | Vorwärts-Log und Barometer seit 04.11.2026; historisch nur letzte Werte, keine Vintages, Revisionen bei diesen Reihen gering |
| Netto-Liquidität (WALCL − WTREGEN − RRPONTSYD) | IMPLEMENTED (live) | F3-Log; Einheiten je Reihe aus FRED |
| Chart-Kalender CPI/FOMC | IMPLEMENTED | #73, #127 |
| US-Wahlen | DEFERRED | erstes neues Paket: Termine sind amtlich, wenige Fälle |
| Arbeitsmarktbericht (NFP) | DEFERRED | Termine bei BLS, gleiche Bauart wie CPI |
| Fed-Reden, Jackson Hole | DEFERRED | Zeiten aus dem Kalender der Fed, Auswahl „wichtig“ muss vorher feststehen |
| SEC-ETF-Fristen, Halving, Options-Verfall, Auszahlungen | DEFERRED | Quellen je Art noch zu prüfen |
| Ungeplante Nachrichten (z. B. GDELT) | DEFERRED | braucht Zeitstempel-Regel und Prüfung der Quelle |
| COT, 13F, ETF-Flüsse | DEFERRED | aus dem Plan vom 02.11., noch nicht angeschaut |
| Aktienmarkt: S&P 500, Nasdaq | DEFERRED, Vorschlag Uzi 07.11. | Nasdaq (FRED `NASDAQCOM`) läuft schon in der Makro-Leiste, aber nicht im Barometer. S&P 500 auf FRED (`SP500`) reicht nur rund zehn Jahre zurück und steht unter Lizenz von S&P; Quelle und Historie ab 2017 prüfen. Handelszeiten beachten (Schluss 16:00 ET, Wochenende fehlt) |
| Yen (USD/JPY, FRED `DEXJPUS`) | DEFERRED, Vorschlag | Auflösung von Yen-Carry-Trades fiel mit BTC-Einbrüchen zusammen (z. B. August 2024); Tageswerte, Zeitregel prüfen |
| Globale Liquidität: Bilanzen EZB und Bank of Japan | DEFERRED, Vorschlag | FRED `ECBASSETSW` (wöchentlich), `JPNASSETS` (monatlich), in Landeswährung, Umrechnung und Veröffentlichungszeit prüfen |
| Gold | DEFERRED, Vorschlag Uzi 07.11. | in der Makro-Leiste vorhanden (PAXG), Quelle für Historie bis 2017 prüfen |
| Geldmenge M2, Kreditrisiko (High-Yield-Spread) | DEFERRED, Vorschlag | FRED `M2SL` (monatlich, Revisionen, Vintages in ALFRED) und `BAMLH0A0HYM2`; Lizenz des Spreads prüfen |
| ETF-Zuflüsse (Spot-BTC-ETFs) | DEFERRED, Vorschlag Uzi 07.11. | vermutlich größter Treiber seit 2024; freie Quelle (Farside) war im Oktober gesperrt, Quelle mit Tageszeitstempel prüfen |
| Stablecoin-Menge, BTC-Dominanz | DEFERRED, Vorschlag Uzi 07.11. | DefiLlama frei; Dominanz wird erst seit 27.10.2026 gesammelt, Historie fehlt |
| Options-Volatilität (Deribit DVOL) | DEFERRED, nur mit Vorlauf-Regel (5b) | frei abrufbar, Historie ab 2021; Kryptomarkt-intern |
| On-Chain (Börsenbestände, Hashrate, Miner-Abflüsse) | DEFERRED | Börsenbestände meist kostenpflichtig (Glassnode, CryptoQuant); Hashrate frei, aber geschätzt und nachträglich geglättet, Point-in-Time prüfen |
| Funding, Open Interest, Liquidationen (Binance) | DEFERRED, nur mit Vorlauf-Regel (5b) | folgen oft dem Kurs selbst; als Handelsregel gehört Funding weiter in die Werkstatt (F2 nicht bestanden) |

## 7. Reihenfolge

1. Diesen Entwurf freigeben (Barti und Uzi).
2. PRE-V2-Prüfung vervollständigen (alle Familien aus dem Inventar), danach Bartis Go oder Nein.
3. Treiber-Research (Abschnitt 5a) für die freigegebenen Familien bauen.
4. Chart-Kalender um `ELECTION` und `NFP` erweitern (Code-PR, mit Uzi abgestimmt, weil #127 von ihm ist).
5. Beschreibende Ereignisstudie Wahlen und NFP mit BTC-Daten bis 2024.
6. Danach ungeplante Nachrichten, erst nach Prüfung einer Quelle.

## Änderungsprotokoll

| Datum | Änderung |
|---|---|
| 06.11.2026 | Entwurf angelegt (Barti: Bereich abgrenzen, Barometer der Engine zuordnen, PRE-V2-Prüfung nachholen, News und Wahlen aufnehmen) |
| 07.11.2026 | Vorschlag Uzi: Abschnitt 5b Krypto-Treiber im Barometer (Funding/OI/Liquidationen nur mit Vorlauf-Regel), ETF-Zuflüsse, Stablecoins, Yen, EZB/BoJ-Bilanzen, DVOL und On-Chain in Abschnitt 6 |
| 07.11.2026 | Vorschlag Uzi: Abschnitt 5a Treiber-Research für alle vermuteten Treiber; S&P 500, Nasdaq, Gold, M2 und Spread in Abschnitt 6 aufgenommen |
