# Was fehlt TIM, um ein profitabler Trading-Bot nach Uzis Vision zu werden?

Stand: Repository `HEAD` 2eafe92 vom 2026-10-02 (B1). Jede Tatsache über TIM trägt eine Kennung (B…); die Belege stehen in Abschnitt 9. Schätzungen sind markiert. Nicht ausgeführt: die ganze Testsuite, Netzzugriffe, Börsenaufrufe. Wo Dokument und Code sich widersprechen, gilt der Code (Tabelle am Ende von Abschnitt 3). Länge: Fließtext der Abschnitte 1 bis 8 außerhalb der Tabellen unter 3.000 Wörtern; die Tabellen tragen den Rest der Begründung und sind länger als Stichpunkte.

## 1. Kurzurteil

1. **Profitabilität:** K1 ist für keine der 48 Varianten belegt, weil alle vor dem Holdout durchfielen, und K5 ist nicht gestartet, weil Kandidat, R7-Code und Papier-Journal fehlen (B2, B3, B4, B5, B6, B7).
2. **Größter Engpass:** Uzis Orderflow-Methode (V1) lief nie über Historie, weil sie nicht als maschinell entscheidbare Regel vorliegt und Bestätigungsregeln, Historiendaten und ein Replay fehlen; ohne das ist K1 für seine Methode nicht messbar (B11, B18, B19, B34, B65).
3. **Abstand zur Vision, nächster zuerst:** V4 und V2 sind angefangen (Betrieb endet bei der Datensammlung, Reparatur nur für bekannte Fehler: B49, B13, B14), V3 und V5 fehlen im Code (B15, B16, B17), und V1 ist der fernste Teil, weil an ihm alle Profitabilität hängt.
4. **Stufenleiter:** TIM steht auf L1, mit zwei Vorbehalten. Das Dokument nennt L1 als höchste belegte Stufe (B20); im Code liegen die genannten L1-Module, der Betriebsaufruf in `main.py` ruft sie auf (B163), und ihre drei Testdateien laufen grün (B162). Ob L1 auf dem Server heute läuft, ist UNVERIFIED. L0 hat eine Datenlücke: Coverage 67,346 % mit Stand 2026-08-01, FAIL (B21, Artefakt, kein heutiger Betrieb; heutiger Serverstand UNVERIFIED). L2 existiert nur als nicht angebundene Bibliothek (B22, B9).
5. **Einordnung von V5:** Uzis Vision entspricht L5, nicht L6 (B23, B24; Annahme, Abschnitt 2).

## 2. Die Vision, strukturiert

**Annahmen zu den offenen Begriffen** (naheliegendste Lesart, Uzi bestätigt oder ändert):

- **Setup:** ein maschinell erzeugter Handelsplan mit Richtung, Einstiegszone, Stop, Zielen, Verfall und Freigabe der Risk Engine. Das ist der `TradePlan`, den der Builder nur aus einem bestätigten Szenario baut (B25); er trägt eine Verfallsbedingung (B26).
- **Bestätigt:** Ein namentlich bekannter Mensch antwortet je Plan mit Ja oder Nein, oder der Plan verfällt. Die Antwort wird mit dem Plan-Hash gespeichert. Ohne gültiges Ja geht keine Order raus. Verfall ist „kein Trade“.
- **Komplett autonom:** Daten, Analyse, Aufgabenplanung, Betrieb und Reparatur laufen ohne Eingriff. Ein Mensch greift nur bei Setup-Freigaben ein und bei Änderungen an Strategie, Risikoregeln und Protokoll.

| Teil | Erfüllt, wenn … | Heutiger Stand | Abstand |
|---|---|---|---|
| **V1 Tradingwissen** | (a) Mindestens ein Setup-Typ wird allein aus Daten entschieden, ohne handgesetzte Bestätigung. (b) Dieselbe Funktion läuft Kerze für Kerze über Training und Validierung mit Protokollkosten; Kürzen der Zukunft ändert keine frühere Entscheidung. (c) Die Varianten stehen vor dem Lauf im Register. | Pipeline aus Datenqualität, Szenarien, Risk Engine und Trade-Plan existiert, Tests grün (B27), aber auf synthetischem Zickzack (B28). Bestätigungen kommen nur als gelieferte Beobachtung (B29), geliefert von der Testeingabe (B30, B12); die Prädikate werden nirgends aufgerufen (B18). Replay ungenutzt, ohne Kosten, ein Balken (B11, B31, B32), selbst „vorläufig“ (B33). Kein Engine-Backtest (B34, B35). Wissensbasis ist „educational context“ (B36). | Methode in Regeln fassen, Bestätigung aus Daten rechnen, Replay und Historiendaten bauen. |
| **V2 Selbstreparatur** | Bei 10 vorab unbekannten, eingespielten Fehlern im erlaubten Bereich (Betrieb, Daten, Infrastruktur) behebt TIM mindestens 8 ohne menschliche Codeänderung, mit grünen Tests; Rest endet in BLOCKED. Dazu eine echte Produktionsstörung. | Drei Läufe: Run 1 mit vorab freigegebener Rezeptur (B37), Run 2 gleicher Fehler aus dem Speicher (B13), Run 3 unbekannter Fehler endet BLOCKED (B14, B38). Fehler vom Skript eingespielt (B39). Die echte Störung ab 30.09. blieb stehen (B40, B41). | Diagnose und Fix für Unbekanntes fehlen; belegt ist nur Wiedererkennen. |
| **V3 Selbstentwicklung** | TIM erzeugt Regel- und Hypothesenvorschläge selbst, legt sie als Registeranträge ab, rechnet Training und Validierung automatisch. Registereintrag, Holdout-Freigabe, Protokolländerung und Merge von Strategiecode bleiben menschlich. | 48 fest verdrahtete Varianten (B42); kein Forschungsagent (B15). `research_intelligence` liefert Kontextregeln (B43) und führt Open Interest, Funding, Liquidationen als nicht verfügbar (B44). `agent_infra` vergibt keine Schreibrechte (B45). Agenten dürfen nicht selbst releasen (B46). 12 Registerplätze frei (B47, B2). | Der gesamte Vorschlagsmechanismus fehlt; knapp ist der Registerplatz, nicht Rechenzeit. |
| **V4 Selbststeuerung** | Der Server sammelt 14 Tage am Stück ohne Eingriff mit mindestens 99,5 % Coverage, Analyse- und Papier-Schleife laufen, Backup und Neustart erledigt TIM selbst, an Uzi gehen nur Freigabeanfragen (B48). | Orchestrator endet bei der Datensammlung (B49). Coverage FAIL (B21). Seit 30.09. 16:35 UTC keine Kerzen (B40); neue Runtime installiert, aber deaktiviert (B50). Systemd-Bausteine liegen im Repo (B51). Heutiger Stand UNVERIFIED. | Server stabilisieren, Messfenster fahren, Analyse- und Papier-Phase ergänzen. |
| **V5 Bestätigung** | Kein Order-Pfad ohne gültigen Freigabedatensatz (Person, Zeit, Plan-Hash, Frist); ein Test erzwingt das; Fristablauf ergibt keinen Trade; Freigabe geht auch außerhalb des Macs. | Menü „Freigabe“ zeigt nur V2-Readiness (B17), schreibt nur Research-Anfragen (B16), nur Loopback (B52). Der Modus-Enum kennt kein LIVE (B53). Kill Switch mit zwei gegensätzlichen Bedeutungen, die ausgearbeitete Fassung ohne Aufrufer (B54, B55, B157, B56). | Freigabe-Dienst, Frist, Protokoll, Kill Switch, Börsenadapter fehlen. |

### Reibungen und Auflösung

| Reibung | Befund | Auflösung |
|---|---|---|
| **V3 gegen Protokoll** | Obergrenze 60 Varianten, verworfene zählen mit (B57, B47). Umparametrieren verboten, neue Parametrierung erhöht m (B58). 12 Plätze frei (B2). | V3 heißt „vorschlagen und vorrechnen“, nicht „Register füllen“. Jeder Eintrag bleibt menschlich. Danach nur mit neuem, späterem Holdout (B47). Selbstentwicklung läuft höchstens so schnell, wie neue ungesehene Daten entstehen. |
| **V4/V5 gegen Stufen** | L5: Freigabe je Order, getrennte Schlüssel (B59). L6: autonom unter Aufsicht (B24). | Annahme: Handel L5, Betrieb autonom. „Komplett autonom“ für Orders wäre L6 und widerspräche V5 (Frage 12). L6 wird nicht gebaut. |
| **V5 gegen Zeitbedarf** | Im Test liegt der Einstieg auf dem Eröffnungskurs der nächsten Kerze (B60). Getestete Regeln erzeugen 0,3 bis 91 Setups je Woche (B61). Mindestfrequenz: Mid 0,33, Short 2,2 je Woche (B62). | Annahme: höchstens etwa 3 Setups je Tag (21 je Woche), Frist eine Signalkerze, höchstens 4 Stunden. Beide Ränder zusammen ergeben ein Fenster für die Setup-Rate: Unten verlangt das Training für Short mindestens 500 Trades in 156,6 Wochen, also 3,19 je Woche (B103, B161); oben gilt die Annahme von 21 je Woche. Darüber liegen 5m-Regeln (90,7 je Woche, B61), sie scheiden wegen V5 aus, nicht wegen K5. Darunter liegen die langsamen Regeln (Mid, Long): Bei 0,29 bis 0,3 Setups je Woche (B61) ergeben 91,1 Holdout-Wochen etwa 26 Trades, also unter K3 mit Mid ≥ 30 (B79, B161). Ihr Urteil wäre KEIN URTEIL (B80), und der Papier-Betrieb lieferte etwa 2 Trades. Für den kritischen Pfad gilt deshalb: Short-Horizont, 3,2 bis 21 Setups je Woche (ABGELEITET aus B103, B161 und der Annahme). Langsame Regeln sind K3-seitig nicht erfüllbar; ob Uzis Methode in dieses Fenster fällt, weiß erst die Zählung nach der Registrierung (A6). |
| **V5 gegen Profit** | Der Mensch ist langsamer als der Backtest; Einstieg und Stichprobe weichen ab. | Zwei Journale: alle TIM-Setups und nur die bestätigten. K5 am bestätigten Journal. Liegt es unter dem vollständigen, ist der Mensch-Filter ein Kostenfaktor und wird so berichtet. |
| **Neue Methode gegen Holdout-Sperre** | Holdout ab 2025-01-01 (B149). Daten ab 2025 zu zählen wäre ein Blick hinein; B129 sperrt nur das Laden (Risiko wie B106). | Beispiele, Fallauswahl, Frequenzzählung, Regelkorrektur nur mit Daten bis 2022-12-31 (siehe nächste Zeile). Mindestfrequenz für den Holdout nur als Datumsrechnung (B62). Wer 2025/2026 gesehen hat, vermerkt es im Änderungsprotokoll (B85). |
| **Neue Methode gegen Validierung (neu)** | Die Validierung (2023-01-01 bis 2024-12-31) bestätigt Kandidaten vor dem Holdout (B158). Kalibrierung an ihr macht sie abhängig, das Register zählt das nicht (B58). R4 nutzte sie für andere Regeln (B2: 6 `failed_validation`). | Alles nur bis 2022-12-31 (B149); Validierung erstmals in A6, ohne Korrektur danach. Uzis Vorwissen vermerkt er im Änderungsprotokoll; ein BESTANDEN gilt dann schwächer (wie B106). |
| **Neue Methode gegen Rastersperre** | Nach Beginn von R4 sind Änderungen an Split, Kriterien, Raster nur strenger erlaubt (B85). Neue Varianten sind ein „neuer Registereintrag“, der m erhöht (B58); Obergrenze 60 (B47). Ob das die Sperre trifft, sagt das Protokoll nicht. | Frage 11 an Uzi. Meine Lesart: Neue Varianten erhöhen m, machen die Schwelle strenger und ändern Split, Kriterien, Raster der 48 nicht. Andere Lesart: Test erst nach neuem Holdout, Verschiebung um Monate. Eintrag vor dem ersten Lauf committen, und vor diesem Lauf keine Zählung. |
| **V2/V3 gegen Gültigkeit der Tests** | Jede Änderung an Strategie-, Risiko- oder Kostencode entwertet frühere Tests. Agenten dürfen nicht selbst releasen (B46). Ohne freigegebene Rezeptur blockiert V2 schon (B38). | Selbstreparatur nur in einer Allowlist (Betrieb, Daten, Infrastruktur). Strategie-, Risiko-, Protokollcode per Hash gesperrt; Fix dort endet in BLOCKED. |
| **V1 gegen Testbarkeit** | Strukturereignisse sind nur Kontext, bis Ort und Orderflow dazukommen (B64). R4 testete BOS, REJECTION, FAILED_CONTINUATION ohne Ort und Orderflow, alle sechs negativ (B65): das widerlegt die Methode nicht, stützt sie nicht. Broncx-Beiträge verschieben Scores um ±0,08 (B66). | Nur Regeln ohne Chart-Augenmaß und ohne fremde Meinung zählen als V1. Broncx-Feed im Test und im Betrieb aus. |
| **Zielbild (nicht still aufgelöst)** | Band 1: „TIM ist kein Trading-Bot“ (B67). Band 10: „nicht der Bau eines Trading-Bots“ (B68), „Trading ist eine Anwendung“ (B69). `docs/VISION_2030.md`: keine API-Schlüssel, Konten, echten Orders (B70). Uzis Vision ist ein autonomer Bot: echter Widerspruch. Vereinbar nur als „Bot als eine Anwendung“. | Uzi entscheidet. Gilt die Vision, brauchen versionierte Änderung: Band 1, Band 10, `docs/VISION_2030.md`, `AUTONOMY_LEVELS.md` (L5 „PROHIBITED“: B71; L5 zu L6 „Not planned“: B72), Roadmap Phase 10 (B73). Die Verfassung erlaubt Weiterentwicklung, verlangt aber erhaltene Grundprinzipien (B74); ob „kein Bot“ eines ist, ist Uzis Auslegung. Die Agentenverfassung sieht Live-Handel mit Freigabe schon vor (B46). |

### Der Maßstab: was K1 plus K5 allein bedeuten

TIM wird zuerst am Protokoll 1.0 gemessen, alle fünf Bedingungen (B75, B76). Uzis Vorrang für K1 und K5 lese ich als Arbeitsreihenfolge, nicht als Ersatz der übrigen Regeln.

| K1 und K5 erfüllt, aber … | Bedeutung | Folge |
|---|---|---|
| **K2 nicht** | Positiver Erwartungswert, aber nicht von Zufall und Drift unterscheidbar. NICHT BESTANDEN im Holdout ist endgültig für die Variante und ihre abgeleiteten Varianten (B160); Papier-Betrieb nur für BESTANDEN (B5). | „Unbewiesen“, kein Geld (B77). Lockerung kostet die Mehrfachtest-Disziplin; bei m = 48 gilt p < 0,0010 (B78). |
| **K3 nicht** | Zu wenige Trades (B79): KEIN URTEIL (B80). Weder profitabel noch widerlegt. | Kein Geld, mehr Daten abwarten; freiwilliger Papier-Test möglich. |
| **K4 nicht** | Drawdown über 20 % bei 1 % Risiko (B81). | Variante verworfen. Kleinere Positionen wären eine Lockerung. |

**Urteil über den Maßstab.** K2 mit Korrektur ist streng genug. K1 ist zu locker: Es verlangt nur „größer 0 R“, obwohl das Protokoll ein 95-%-Intervall schon rechnet (B82). K5 sagt bei kleiner Tradezahl wenig, das ist im Protokoll angelegt: Das Band kommt aus einem Bootstrap über die Einzeltrades der Variante, nicht aus einer Formel (B109). Wie breit es bei Uzis Methode wird, weiß niemand, bevor Trades vorliegen. Zur Größenordnung eine Veranschaulichung, keine Messung an TIM: Mit einer Normalnäherung und der Streuung der Kline-Regeln (Short 1,37 R, Mid 0,70 R aus der Validierung, B83) liegt ein Band um 0,30 R (Short) bzw. 0,40 R (Mid), den K2-Schwellen aus B105. Das Band ist hier nur ein Platzhalter: Das tatsächliche Band ist ein Bootstrap über die Validierungs- und Holdout-Trades der Variante (B109, im Zitat vollständig), also um deren eigenes Mittel und mit deren eigener Streuung. Die Zeilen mit n = 20 und n = 26 sind mit denselben Formeln gerechnet wie B83 (Ausgabe in B161). Ein Setup ohne jeden Vorteil läge dann im Papier-Band bei:

| Regel (Veranschaulichung) | Papier-Trades n | Anteil Nullvorteil-Läufe im Normalband |
|---|---|---|
| Short, untere Fensterrate 3,2 je Woche (8 Wochen Höchstdauer: B63, B161) | 26 | 70 % |
| Short, 4,83 je Woche (B61): 4 Wochen ergeben 19,3, also weniger als 20, der Betrieb läuft nach B63 weiter bis 20 | 20 | 74 % |
| Short, etwa 3 Setups je Tag (4 Wochen) | 84 | 36 % |
| Short 5m (4 Wochen mal 90,7: B61) | 360 | 1 % |
| Mid (8 Wochen mal 0,29: B61) | 2 / 5 / 20 | 79 % / 64 % / 18 % |

Was daraus folgt und was nicht: Gesichert (ABGELEITET aus B61, B63 und B161) ist nur die Zahl der Papier-Trades, die eine Rate in 4 bis 8 Wochen liefert. Bei Mid sind das einstellig, dort bestätigt K5 höchstens „kein Widerspruch“. Nicht gesichert ist, wie breit das Band wirklich wird; deshalb ist die Tabelle keine Entwurfsregel. Der Ausschluss von 5m-Regeln beruht nicht auf K5, sondern auf V5: 90,7 Setups je Woche (B61) kann ein Mensch nicht einzeln bestätigen. Ein Vergleich mit Kaufen und Halten fehlt (+252,7 % und +465,7 % im selben Zeitraum, nur aus dem Bericht übernommen: B84). Strenger machen ist erlaubt (B85); Vorschlag: untere Grenze des K1-Intervalls mindestens 0 R, und K5 zusätzlich „gemessene Kosten höchstens Modellkosten“.

## 3. Lückenliste

Aufwand: S bis 1 Agententag, M 2 bis 5 Tage, L 1 bis 3 Wochen, XL mehr. Grundlage: Das Labor entstand laut Git an einem Tag (B86); Wartezeiten für Daten, Papier-Betrieb und Uzis Entscheidungen kommen dazu.

| # | Teil | Bereich | Ist-Zustand | Warum es Profitabilität verhindert | Schwere | Status | Aufwand, Abhängigkeit |
|---|---|---|---|---|---|---|---|
| 1 | Profitabilität | Edge/Strategie | 0 von 48 bestehen (B2, B3). Schnelle Regeln S und T (14 Varianten): netto im Median −0,39 R, alle 28 Werte negativ; Brutto-Obergrenze Median −0,09 R gegen Kostenaufschlag 0,31 R (B159, B8, B150); alle sechs T-Regeln negativ (B65). Langsame Regeln L, M1, M2 (20 Varianten): netto in 37 von 40 Werten positiv (Median L +0,30 R, M1/M2 +0,09 R), aber durchgefallen an Tradezahl und p-Wert, z. B. L1-n100-ls: +0,79/+0,40 R, p = 0,21 (B159, B101, B102, B87). M3 (14 Varianten, Wochentage): Median −0,02 R (B159). | Ohne positiven Erwartungswert nach Kosten gibt es nichts zu automatisieren. | BLOCKIEREND | BELEGT (Zählung), ABGELEITET (Zerlegung, Obergrenzen) | offene Forschung; hängt an 2 bis 5 |
| 2 | V1 | Edge/Strategie | Orderflow-Methode nie über Historie getestet: Replay ungenutzt, kostenlos, ein Balken (B11, B31, B32); kein Backtest-Modul (B34, B88). | Der Kern der Vision ist unmessbar. | BLOCKIEREND | BELEGT | L; hängt an 3, 4, 5 |
| 3 | V1 | Edge/Strategie | Bestätigung wird nirgends aus Daten berechnet (B12, B18, B30); Wahrscheinlichkeiten heuristisch (B89, B90); Ziele fest 1,5/2/3 R (B91). | Kein Szenario wird im Betrieb bestätigt, also kein Setup; Konstanten sind Parameter und vorab festzuschreiben. | BLOCKIEREND | BELEGT | M; nach 4 |
| 4 | V1 | Mensch (Wissen) | Methode unstrukturiert; Wissensbasis nur Kontext (B36); externe Beiträge wirken auf Scores (B66). | Ohne eindeutige Regeln keine Vorab-Registrierung; Test und Betrieb weichen ab. | BLOCKIEREND | BELEGT (Dokumente), ABGELEITET (Folge) | S bis M, Uzis Zeit |
| 5 | Profitabilität | Daten | Lab-Loader kennt nur Klines und Funding (B19), Klines nur mit Taker-Volumen (B92); aggTrades im Protokoll optional (B93). Live nur Spot-aggTrades; Futures-aggTrades, Open Interest, Orderbuch fehlen (B94 bis B97). Getestet wurde der USD-M-Perpetual (B98). Strategien sehen nur `Kline`-Felder (B151, B154, B155). | Die Methode braucht Delta und Open Interest; die Historie ist nicht ladbar und für Strategien nicht sichtbar; der Live-Feed ist nicht das getestete Instrument. | BLOCKIEREND | BELEGT; Open-Interest-Archive UNVERIFIED (Probe-Download U2) | M bis L; blockiert 2 |
| 6 | Profitabilität | Daten | Coverage FAIL (B21); seit 30.09. keine Kerzen, Nachhol-Schleife (B40, B41, B99); kein automatisches Nachholen (B100). | Lücken verfälschen Signale und Papier-Betrieb. | BLOCKIEREND für K5 (belegte Stände 2026-08 und 2026-10; heute UNVERIFIED) | BELEGT, heute UNVERIFIED | M; Fenster 14 Tage (B48) |
| 7 | Profitabilität | Validierung/Statistik | M1 hat 35, L1 14 und 17 Trades im Training (B101 bis B103). Training für USD-M ab 2020-01, Spot ab 2017-09 (B104). Kritische Schwelle (α = 0,001, 50 % Power): 0,30 R (Short, n = 200), 0,40 R (Mid, n = 30), 1,53 R (Long, n = 10); mit 80 % Power 0,38/0,50/1,94 R (B105). | Langsame Setups sind kaum zu bestätigen (B152); kleine echte Vorteile bleiben unsichtbar. | WICHTIG | ABGELEITET (Normalnäherung; K2 vergleicht mit Zufallseinstiegen; Streuung aus Kline-Regeln) | Entscheidung: Horizont wählen |
| 8 | Profitabilität | Validierung/Statistik | 12 freie Registerplätze (B47, B2). | Methode und Selbstentwicklung konkurrieren um 12 Plätze. | WICHTIG | BELEGT | Entscheidung Uzi |
| 9 | Profitabilität | Validierung/Statistik | Holdout schwächer (TIM-Regeln 2026 entwickelt: B106); frischer Test ist der Papier-Betrieb (B107); R6- und R7-Code fehlen (B108, B6). | BESTANDEN trägt weniger; K5-Werkzeug fehlt. | WICHTIG | BELEGT | M |
| 10 | Profitabilität | Validierung/Statistik | K5-Band bei kleinem n breit (B109, B83). | K5 bestätigt dort höchstens „kein Widerspruch“ (Veranschaulichung in Abschnitt 2, kein Messwert). | WICHTIG | ABGELEITET | S, Protokollzusatz |
| 11 | Profitabilität | Kosten und Ausführung | Gebührenstufe offen (B110); feste Kostenwerte (B111); keine Orderbuchdaten (B97). | Stresskosten-Aufschlag: bei schnellen Regeln S und T Median 0,31 R, Spanne 0,14 bis 0,61 (B8), das übertrifft deren Brutto-Wert; bei L und M nur 0,02 bis 0,04 R (B159). Falsche Kosten kippen K1 also vor allem bei schnellen Regeln. | WICHTIG | BELEGT (offen) | S bis M; Messung im Shadow |
| 12 | Profitabilität | Kosten und Ausführung | Papier-Journal nur im Speicher, ohne Aufrufer (B112, B113); Demo „PREPARED“ (B7); keine Order-Zustandsmaschine (B114). | K5 ist nicht ausführbar. | BLOCKIEREND für K5 | BELEGT | M bis L |
| 13 | Profitabilität | Kosten und Ausführung | Kein Börsenadapter, keine Order-Endpunkte (B115, B116). | Kein Micro-Live. | BLOCKIEREND für Micro-Live | BELEGT | L; Bauplan und Freigabe Pflicht (B77, B73) |
| 14 | Profitabilität | Risiko und Kapital | Positionslimit teilt Menge durch Dollar-Eigenkapital (B117); Testfall mit 100 % Nominal je Eigenkapital genehmigt, Grenze 10 % (B118). | Die Risk Engine schützt nicht wie beschrieben. | WICHTIG, zwingend vor Micro-Live | BELEGT (ausgeführt) | S |
| 15 | V5 | Risiko und Kapital | Standard `enabled=True` (B157); `blocks_execution` blockiert nur mit Flag und Modus, `block_live_execution` nur im Modus OBSERVE (B55); die Entscheidungs-Engine meldet bei `False` „aktiv“ (B54); `governance.py` ohne Aufrufer, Konfigdatei fehlt (B56). | Kein wirksamer Not-Aus. | WICHTIG, zwingend vor Micro-Live | BELEGT | S bis M |
| 16 | Profitabilität | Risiko und Kapital | Ohne Konto nimmt die Pipeline 10.000 an (B119); Tages-/Wochenlimits ohne Datenquelle. | Verlustgrenzen wirken nicht. | WICHTIG | BELEGT | M, nach Adapter |
| 17 | V5 | Governance und Prozess | Keine Freigabefunktion (B16, B52, B17). | V5 nicht erfüllbar. | BLOCKIEREND für Micro-Live | BELEGT | M |
| 18 | V5 | Mensch (Zeit) | Frist, Setup-Last, Erreichbarkeit, Vertretung offen; Setup-Raten 0,3 bis 91 je Woche (B61). | Zu viele oder zu kurze Setups sind nicht bestätigbar; Verzögerung ändert den Einstieg. | WICHTIG | ABGELEITET | S plus Uzis Entscheidung |
| 19 | V2 | Betrieb und Infrastruktur | Heilung nur für bekannte Fehler (B13, B14); reale Störung blieb offen (B40). | Ausfälle erzeugen Lücken und Fehlsignale. | WICHTIG | BELEGT | L |
| 20 | V4 | Betrieb und Infrastruktur | Orchestrator ohne Analyse- und Papier-Phase (B49). | Keine Schleife von Daten zu Setup und Journal. | WICHTIG (K5-Betrieb) | BELEGT | M |
| 21 | V3 | Edge/Strategie | Kein Hypothesen-Erzeuger (B15, B42). | Ohne Vorteil ist Selbstentwicklung wertlos. | SPÄTER | BELEGT | XL |
| 22 | Profitabilität | Governance und Prozess | Widersprüchliches Zielbild (B67, B68, B70); Dokumente älter als Code (Tabelle unten). | Prüfer und Agenten sperren den Weg zu Recht. | WICHTIG | BELEGT | S (Entscheidung), M (Dokumente) |
| 23 | Profitabilität | Governance und Prozess | Alle 8 V2-Blocker OPEN (B120); V2-B01/B02 schließt der Betriebsplan prospektiv (B121); V2-B08 fehlt (B122). | Unklar, was den Handelsweg sperrt. | WICHTIG | BELEGT, Folgerung ABGELEITET | S, Entscheidung Uzi |

### Widersprüche zwischen Dokument und Code (Code gilt)

| Dokument | Code | Folge |
|---|---|---|
| „No runtime setup engine“ (B22) | Pipeline und Builder existieren, getestet (B27), nichts im Betrieb ruft sie (B9, B10) | L2 nur als Bibliothek |
| Backtest und Risk „no engine found“ (B123) | Beide Module existieren (B124) | Dokument veraltet |
| Strategie „MISSING“ (B125) | Labor führt 48 Regeln aus (B2) | veraltet; Strategievertrag fehlt trotzdem (B126) |
| Handbuch Backtest „VERIFIED ~92 %“ (B127) | Replay ohne Kosten, ungenutzt, ohne Tests (B31, B11, B88) | „VERIFIED“ heißt „Dokument passt zum Code“ |
| Coverage 60,659 % (eingefroren) | Neuere Messung 67,346 % (B21) | beide unter Ziel |

## 4. Was nicht fehlt

| Was | Warum gut genug oder überbaut | Empfehlung |
|---|---|---|
| **Statistik-Wächter, Register, Holdout-Sperre** | 0 von 200 Zufallsreihen BESTANDEN, 190 von 200 mit +0,2 R (B128); 7 Tests grün (B27); Holdout nur mit Erlaubnis ladbar (B129). | Nur über das Änderungsprotokoll ändern |
| **Makro-Pipeline (CPI)** | 3.042 von 5.252 Zeilen im Labor (B130); 23 Commits seit 15.09. gegen 3 für Backtest, Hypothesen, Statistik (B131); keine der 48 Hypothesen nutzt sie (B132); V1.2 und V2 geplant (B133). | Pausieren bis zum belegten Vorteil |
| **Verwaltungsschichten** (Task-Governance, Manager, Graph, Obsidian, Dashboard) | Zeilen: B134. Der eigene Plan: „Engpass ist Edge, nicht Governance“ (B135). | Keine neuen Ausbaustufen |
| **Weitere schnelle und Kalender-Kline-Regeln** (S, T, M3) | S und T: Brutto-Obergrenze Median −0,09 R, nur 4 von 28 Werten positiv (B8, B159). M3: netto Median −0,02 R, Brutto-Obergrenze +0,02 R (B159). Jeder Eintrag kostet einen der 12 Plätze (B47). | Keine neuen Parametervarianten dieser drei Kline-Familien. Die Regeln aus Uzis Methode (Absorption, Delta-Divergenz am Ort) sind keine Parametervarianten davon, sondern eine neue Familie; sie müssen die Kosten von im Median 0,31 R je Trade bei Short-Regeln erst durch einen Bruttovorteil decken (B8). Langsame L- und M-Regeln (Brutto-Obergrenze +0,15 bis +0,32 R, B159) scheiterten an Stichprobe und p-Wert (B101, B102). Sie bleiben keine Empfehlung: Bei 0,3 Setups je Woche erreicht der Holdout K3 nicht (Abschnitt 2, B161). Welche Varianten eingetragen werden, steht erst nach U1 fest; die Pakete P1 bis P5 tragen keine Variante ein. |
| **Selbstheilungs-Nachweis V2** | Machbarkeit für Bekanntes belegt (B13). | Nicht ausbauen vor einem Edge |
| **Risk Engine und Trade-Plan (Struktur)** | Tests grün (B27). | Nur Lücken 14 bis 16 beheben |
| **Speicherlogik Spot-aggTrades** | Duplikat-, Kollisions-, Restart-, Hash-Tests vorhanden (B136). | Lücke ist Abdeckung und Instrument, nicht die Logik |

## 5. Kritischer Pfad

Zeit bestimmen Uzis Entscheidungen und die Protokollfristen (Papier-Betrieb 4 bis 8 Wochen: B63). Alle Kalibrierung und Zählung nur mit Daten bis 2022-12-31; die Validierung wird erst in A6 gesehen.

### Phase A: bis zum ersten Setup mit K1 und K5

| Nr | Schritt | Abnahme | Abbruch | Ablauf |
|---|---|---|---|---|
| A1 | Setup-Vertrag v1: ein Setup-Typ, ein Zeitrahmen, als Regeln (Daten, Einstieg, Stop, Ziel, Verfall, Ausschluss). Leitplanke: „ein Instrument, ein Timeframe, eine Strategie zuerst“ (B137). | Vertrag gegen JSON-Schema gültig; bei 20 vom System gewählten Fällen mit Datum bis 2022-12-31 deckt sich die Regel in mindestens 80 % mit Uzis Urteil (Vorschlag); kein Fall aus 2023 oder später | Nach drei Runden keine eindeutige Regel | sofort; blockiert A4, A5 |
| A2 | Daten: USD-M-aggTrades und, falls vorhanden, Open Interest aus dem öffentlichen Archiv; Loader mit Checksumme, Hash, Holdout-Sperre; Felder für Strategien sichtbar (P3) | Probe-Monat vollständig, Checksumme PASS, Hash im Änderungsprotokoll | Open Interest nicht beschaffbar: Regel ohne ihn neu fassen (A1), sonst nicht testbar | parallel zu A1, A3 |
| A3 | Server tragfähig: Nachhol-Schleife beheben, Umzug (B138), USD-M-Livefeed, 14-Tage-Fenster | mindestens 99,5 % Coverage im vorab festgelegten Fenster | zwei Fenster in Folge unter 95 %: erst Ursache klären | parallel; Pflicht vor A8 |
| A4 | Replay mit datenbasierter Bestätigung: Pipeline Kerze für Kerze, Protokollkosten, reparierte Risk Engine | Kürzen der Zukunft ändert keine frühere Entscheidung; zwei Läufe, gleicher Hash; Pipeline-Test ohne injizierte Bestätigung | Look-ahead nicht ausschließbar | nach A1, Daten aus A2 |
| A5 | Vorab-Registrierung: Änderungsprotokoll-Eintrag (Daten, Regeln, höchstens 4 Varianten, m höchstens 52; Rastersperre geklärt: B85), Testzahl und Registerskript angepasst (P5). Kein Lauf und keine Zählung vor dem Commit: Die Rate wird nur aus Uzis Beispielen und dem Fenster 3,2 bis 21 je Woche (Abschnitt 2) geschätzt. | Eintrag committet und von Uzi freigegeben, mit Angabe gesehener Daten, vor jedem Lauf; Holdout-Mindestfrequenz nur als Datumsrechnung (B62); Registerplätze im Eintrag benannt: jede Variante verbraucht ihren Platz, auch wenn die Zählung in A6 unter dem Minimum liegt | Rastersperre nicht geklärt (Frage 11): kein Eintrag | nach A4 |
| A6 | Der eine offizielle Lauf auf Training und Validierung nach Protokoll §8 (Validierung erstmals hier). Die Tradezahl entsteht erst hier, im Lauf der registrierten Varianten. | Mindestens eine Variante erreicht in Training mindestens 50 Trades (Mid) bzw. 500 (Short) (B103) und besteht Schritte 1 und 2 samt Walk-Forward | Variante unter Mindestzahl: nicht beurteilbar, ihr Platz bleibt verbraucht; neue Parametrierung nur als neuer Eintrag mit neuem Platz (B58), nie als Korrektur nach Sicht. Keine besteht: „kein Vorteil“, Holdout unberührt, Stopp (Abschnitt 7). Zählung zeigt Daten ab 2023 im Training: Lauf verworfen, vermerkt | nach A5 |
| A7 | Kandidatenliste einfrieren, Holdout genau einmal (R6) | K1 bis K4 BESTANDEN, Stresskosten berichtet | NICHT BESTANDEN: endgültig (B160) | wartet auf A6 und Uzis Go |
| A8 | Papier-Betrieb R7 auf dem Server, 4 bis 8 Wochen: persistentes Journal, Band, zwei Journale | K5 „bestätigt“ (bei „kein Widerspruch“ schwach ausgewiesen) | Papier-Stopp nach Protokoll (B139) | nach A7 und A3; Journal und Freigabe-Oberfläche parallel zu A4 bis A7 baubar |

Ergebnis Phase A: das erste Setup mit K1 bis K5, frühestens vier Wochen nach dem Holdout-Lauf (B63).

### Phase B: bis zum ersten bestätigten Micro-Live-Trade (nur nach A8)

| Nr | Schritt | Abnahme | Abbruch | Ablauf |
|---|---|---|---|---|
| M1 | Sicherheitsbasis: Freigabe-Dienst (Person, Frist, Plan-Hash), ein Kill Switch mit einer Bedeutung, Risk-Limit in Nominalwert, Kontostand aus Quelle | Order-Aufruf ohne gültigen Datensatz wirft; Kill Switch sperrt jeden Pfad; Testfall B118 verworfen | Order-Pfad technisch nicht sperrbar: kein Live | parallel zu A4 bis A8; Abnahme vor M3 |
| M2 | Shadow: Plan gegen echten Markt vergleichen (Füllquote, Slippage), ohne Order; eigene Freigabe (B140) | Gemessene Kosten höchstens Modellkosten; K1 mit gemessenen Kosten größer 0 | K1 kleiner oder gleich 0: Stopp | nach A8 |
| M3 | Börsenadapter, getrennte Schlüssel, Order-Zustandsmaschine, Abgleich, unabhängige Sicherheitsprüfung | Prüfbericht ohne offenen kritischen Befund | Umgehung nicht schließbar | nach M1, M2, Uzis Freigabe, eigener Bauplan (B77) |
| M4 | Erster Micro-Live-Trade: Uzi gibt einen Plan frei, Kapital legt Uzi fest | Trade mit Freigabedatensatz; Börse und Journal stimmen überein | Verletzung von Limit oder Kill Switch: Stopp | zuletzt |

### Phase C: V2 bis V4 (warten, bis ein Vorteil belegt ist)

| Nr | Schritt | Abnahme | Abbruch | Ablauf |
|---|---|---|---|---|
| C1 | V2 für unbekannte Fehler: 10 eingespielte Fehler im erlaubten Bereich | mindestens 8 von 10 ohne menschliche Codeänderung, Rest BLOCKED | unter 5 von 10: V2 bleibt „Vorschlag plus Merge“ | nach A8 |
| C2 | V4: Orchestrator um Analyse- und Papier-Phase | 14 Tage ohne Eingriff, Coverage mindestens 99,5 %, nur Freigabeanfragen | Eingriff nötig: Ursache beheben, Fenster neu | Teile in A8, Rest danach |
| C3 | V3: Vorschlagswarteschlange mit Platzzähler und Epochenregel | Ein Zyklus Vorschlag, Rechnung, Uzis Entscheidung; Zähler höchstens 60 | Plätze verbraucht, kein neuer Holdout | nach belegtem Vorteil |

**Parallel:** A1, A2, A3 sofort; M1 und Papier-Infrastruktur neben A4 bis A7. **Warten:** A5 auf A4, A7 auf A6 und Uzis Go, A8 auf A7 und A3, Phase B und C auf A8 (die Server-Heilung für A3 ausgenommen).

## 6. Die nächsten 30 Tage

Fünf Pakete, jedes reiner Code mit Tests, offline prüfbar und einzeln an einen Coding-Agenten übergebbar. Was Uzi, den Server oder das Netz braucht, kann kein Coding-Agent als Aufgabe übernehmen. Es steht danach als Schritt U1 bis U4 und ist kein Arbeitspaket im Sinn der Aufgabe. Ehrlich dazu: Diese vier Schritte fallen in dieselben 30 Tage und sind für A1 bis A6 Voraussetzung. Die fünf Pakete schließen die Lücken 3 und 4 (beide BLOCKIEREND) nicht allein. Sie liefern die Werkzeuge. Geschlossen sind die Lücken erst, wenn U1 den Vertrag mit Uzis Inhalt füllt und A4 darauf läuft. Dateibesitz: Jede Datei gehört genau einem Paket; `runner.py` gehört P3, `scripts/research_lab_run.py` P5. P1, P3, P4 starten sofort. P2 startet, sobald das Schema aus P1 gemergt ist. P5 startet nach P3. `<py>` ist die Python-Umgebung der Aufgabe, ohne Cache im Repo. Reicht der Monat nicht, zählt die Reihenfolge P3, P1, P2, P5, P4.

| Paket | Ziel | Dateien | Prüfbefehl | Ergebnis |
|---|---|---|---|---|
| **P1 Vertragsgerüst** (S) | Format für den Setup-Vertrag v1 (Daten, Einstieg, Stop, Ziel, Verfall, Ausschluss, benötigte Daten; Felder wie die Readiness-Matrix sie fordert, alle MISSING: B126) mit Prüfer. Der Prüfer lehnt jeden Beispielfall mit Datum ab 2023-01-01 ab (B149). Der Inhalt kommt später von Uzi (U1), nicht vom Agenten. | neu: `schemas/setup_contract_v1.schema.json`, `src/orderflow_scenario/contract.py`, `tests/test_setup_contract.py`, `docs/autonomous_trader/SETUP_CONTRACT_V1.md` (Leervorlage mit Feldbeschreibung) | `<py> -m pytest -q -p no:cacheprovider -m "not local_env" tests/test_setup_contract.py` | Test zeigt: gültiger synthetischer Vertrag wird angenommen; Vertrag mit fehlendem Feld und Vertrag mit Beispiel ab 2023-01-01 werden abgelehnt |
| **P2 Datenbasierte Bestätigung und Risk-Fix** (M, nach P1-Schema) | Die Wahrheitswerte, die die vorhandenen Prädikate `mandatory_fulfilled_for_breakout`, `_reversal` und `_rejection` als Eingabe verlangen (B164), werden aus Balken berechnet, statt injiziert. Der Agent erfindet keine Semantik: Die Namen der Eingaben (`close_above_trigger`, `retest_holds`, `liquidity_swept` und die übrigen) stehen im Code (B164). Jede Schwelle ist ein Pflichtparameter ohne Standardwert, im Test aus einem synthetischen Vertrag (P1). Daraus entsteht eine deterministische Funktion für den Labor-Runner (`Strategy = Callable[[History], Signal | None]`, B151). Zuerst nur, was Klines hergeben (Bar-Delta: `Kline.delta`, B155). Eingaben, die Klines nicht hergeben (z. B. `liquidity_swept` ohne aggTrades), meldet der Test ausdrücklich als „nicht berechenbar“ mit Namen; aggTrades und Open Interest folgen nach P3. Dazu Lücke 14: Risk-Limit in Nominalwert. Grenze des Ergebnisses: P2 beweist, dass die Mechanik deterministisch läuft und ohne Look-ahead. Ob Uzis Methode in diesen Eingaben abbildbar ist, zeigt erst U1; die Liste „nicht berechenbar“ ist die Eingabe dafür. | neu: `src/research_lab/hypotheses/method.py`, `src/orderflow_scenario/engines/confirmation_rules.py`, `tests/test_method_strategy.py`, `tests/test_orderflow_risk_cap.py`; ändern: `src/orderflow_scenario/engines/risk.py` Zeile 123; lesen: `src/research_lab/backtest/engine.py` (History, Zeile 17). Der alte `src/orderflow_scenario/backtest.py` (B31, B32) wird nicht erweitert. | `<py> -m pytest -q -p no:cacheprovider -m "not local_env" tests/test_method_strategy.py tests/test_orderflow_risk_cap.py tests/test_orderflow_pipeline_trade_plan.py` | Test beweist: Kürzen der Zukunft ändert keine frühere Entscheidung, zwei Läufe gleicher Hash, der 100-%-Fall wird verworfen (B118); die Strategie läuft auf synthetischen Balken im Labor-Backtest mit Protokollkosten; der Test gibt die Liste der mit Klines nicht berechenbaren Eingaben aus |
| **P3 Datenfelder und Lader** (M) | `Kline` bekommt Felder für Delta aus aggTrades und Open Interest mit Standardwert, damit alle bestehenden Aufrufe gültig bleiben (B156); `History` reicht sie durch (B154). `scripts/research_lab_fetch.py` bekommt `--dataset` für aggTrades und Open Interest (heute nur `--funding`: B141). Lader mit Prüfsumme und Hash; Holdout-Monate werden verweigert (B129); Archivreferenzen in `data_refs` (B153). | ändern: `src/research_lab/data/parse.py` (`Kline`, Zeile 19), `src/research_lab/backtest/engine.py` (History, Zeile 17), `src/research_lab/data/archive.py`, `src/research_lab/runner.py` (Zeile 76), `scripts/research_lab_fetch.py`; ergänzen: `tests/test_research_lab_data.py`, `tests/test_research_lab_backtest.py` | `<py> -m pytest -q -p no:cacheprovider -m "not local_env" tests/test_research_lab_data.py tests/test_research_lab_backtest.py tests/test_research_lab_hypotheses.py` und `<py> scripts/research_lab_fetch.py --help` (zeigt `--dataset`) | Test mit synthetischen Archivdateien: Strategie sieht die neuen Felder; alte Aufrufe unverändert grün; Holdout-Monat wird verweigert; Prüfsummenfehler wird erkannt |
| **P4 Nachhol-Schleife** (M) | Die Nachhol-Schleife bleibt nicht mehr am Seitenlimit stehen (B99) und holt Lücken automatisch nach (B100). Ob Nachholen zur Core-1.0-Logik gehört, ist vorab zu klären (B142); gehört es dazu, endet das Paket mit einem Vorschlag statt einer Änderung. | ändern: `src/data_ingestion/catchup.py` (Zeile 251), `scripts/tim_catchup.py`; ergänzen: `tests/test_catchup_backfill.py` | `<py> -m pytest -q -p no:cacheprovider -m "not local_env" tests/test_catchup_backfill.py tests/test_binance_recovery_v2.py` | Neuer Test mit einer Lücke größer als das Seitenlimit: nach dem Lauf ist sie geschlossen und der Lauf endet im Zustand „erreicht“ nur bei echtem Ende |
| **P5 Registermodus** (S, nach P3) | Neue Varianten ins Register aufnehmen können, ohne die 48 Einträge anzufassen: `scripts/research_lab_run.py` lehnt heute `--commit-register` mit `--only` ab (B148); neuer Modus, der nur Varianten hinzufügt, die im Änderungsprotokoll stehen. Der Test auf genau 48 Varianten (B147) prüft stattdessen den Wert aus dem Protokoll. P5 trägt selbst keine Variante ein. | ändern: `scripts/research_lab_run.py`, `src/research_lab/hypotheses/registry.py`, `tests/test_research_lab_hypotheses.py` (Zeilen 22 und 23); `docs/research_lab/REGISTER.jsonl` bleibt unberührt | `<py> -m pytest -q -p no:cacheprovider -m "not local_env" tests/test_research_lab_hypotheses.py tests/test_research_lab_guard.py` | Test: Modus fügt eine Testvariante in eine Kopie des Registers ein, die 48 vorhandenen Zeilen bleiben byteweise gleich, Holdout-Split wird weiter abgelehnt (B108) |

**Schritte für Menschen, Server und Netz (keine Pakete):**

| Nr | Wer | Schritt | Voraussetzung | Ergebnis |
|---|---|---|---|---|
| U1 | Uzi, mit einem Agenten als Schreiber (drei Termine) | Vertrag füllen: ein Setup-Typ, ein Zeitrahmen im Fenster 3,2 bis 21 Setups je Woche (Abschnitt 2; ein Zeitrahmen darunter erreicht K3 nicht), je fünf gute und schlechte Beispiele mit Datum bis 2022-12-31; Unklares als offene Frage | P1 gemergt | gültiger Vertrag (A1) |
| U2 | Uzi auf dem Mac mit Netz | Probe-Download: `python scripts/research_lab_fetch.py --market futures/um --dataset aggTrades --from 2024-01 --to 2024-01`, danach Open Interest | P3 gemergt | Befundzeile: vorhanden, Größe, Prüfsumme PASS, Hash; Entscheidung zu Open Interest (A2) |
| U3 | Uzi am Server | P4 einspielen, `python scripts/tim_server_health.py`, USD-M-Livefeed einrichten, 72 h beobachten (B143), dann 14-Tage-Fenster | P4 gemergt, Serverzugang | Health GRÜN, mindestens 99,5 % im Fenster (A3) |
| U4 | Uzi | Entscheidung zu Frage 11 (Rastersperre), dann Änderungsprotokoll-Eintrag mit Datensatz, Regeln, höchstens 4 Varianten (m höchstens 52), gesehenen Daten; vor jedem Lauf committen (B85, B160). Es gibt keinen Probelauf: Der erste Lauf nach dem Commit ist der offizielle, auch er verbraucht die Plätze. | P1 bis P3, P5, U1, U2 | Eintrag freigegeben (A5); danach genau ein Lauf im neuen Registermodus: `python scripts/research_lab_run.py --split train,validation` (A6) |

## 7. Wann aufhören

| Ergebnis | Was es zeigt | Folge |
|---|---|---|
| Uzi legt nach drei Runden kein Setup ohne Augenmaß fest (A1) | V1 trägt als Maschinenregel nicht | Alternative unten |
| Open-Interest- oder Delta-Historie nicht beschaffbar, Regel ohne sie nicht definierbar (A2) | Methode nicht testbar; nur Vorwärtstest, der langsam ist: bei 0,29 Setups je Woche dauern 30 Trades rund 100 Wochen (B61, ABGELEITET) | vereinfachen oder aufgeben |
| Setup-Rate im Training unter Minimum oder außerhalb 3,2 bis 21 je Woche (A6) | nicht beurteilbar bzw. für V5 nicht bestätigbar; der Platz ist verbraucht | Zeitrahmen ändern nur als neuer Eintrag mit neuem Platz (B58), höchstens die 4 vorgesehenen Plätze, danach aufgeben |
| Training und Validierung ohne Kandidat wie in R4 (A6) | kein Beleg für die Methode; bei 60 Einträgen ist Schluss (B47) | Stopp, Holdout unberührt |
| Holdout NICHT BESTANDEN (A7) | endgültig für die Variante und alle aus ihr abgeleiteten (B160) | „Profitabler Bot“ ist für diese Methode widerlegt; neue Prüfung nur mit neuem Holdout |
| Gemessene Kosten machen K1 kleiner oder gleich 0 (M2) | nicht profitabel | kein Live |
| V2: unter 5 von 10 unbekannten Fehlern behoben (C1) | vollautonome Reparatur trägt nicht | V2 als Vorschlag plus menschlicher Merge |

**Ehrliche Alternative:** TIM bleibt ein Forschungs- und Entscheidungssystem nach Band 10 (B68) mit autonomem Betrieb (V2 bis V4). Uzi trifft die Trade-Entscheidungen selbst; TIM liefert Kontext, Szenarien, Risiko-Check und Journal. Das braucht keine Verfassungsänderung, enthält aber keine Profitabilitätsaussage.

## 8. Annahmen und offene Fragen an Uzi

**Annahmen**

1. Setup, bestätigt, komplett autonom wie in Abschnitt 2.
2. Instrument BTCUSDT als USD-M-Perpetual (B98); der Live-Feed ist heute Spot (B94).
3. Protokoll 1.0 ist der Maßstab; Vorrang für K1 und K5 ist Arbeitsreihenfolge.
4. Vorschläge ohne Datenbasis: Frist eine Kerze (höchstens 4 Stunden), höchstens etwa 3 Setups je Tag (obere Grenze des Fensters), 80 % Übereinstimmung in A1, 8 von 10 in C1, höchstens 4 Registerplätze.
5. Effektgrößen in Zeile 7 und die K5-Tabelle sind Normalnäherungen mit der Streuung der Kline-Regeln, keine Messung an Uzis Methode.
6. Aufwand beruht auf dem Git-Datum des Labors (B86) und ist grob.

**UNVERIFIED, mit Weg zur Klärung**

1. Serverstand nach dem 01.10.: `scripts/tim_server_health.py` und `timctl status` auf dem Server.
2. Open-Interest-Archive: Probe-Download (Schritt U2).
3. Historientiefe und Aggressor-Semantik der OpenMarket-REST-Daten (B144).
4. Reale Gebührenstufe (B110).
5. Kaufen-und-Halten-Zahlen: Rohdaten nicht im Repo (B84).
6. Ob die Börse eine Testumgebung für Orders anbietet.
7. Der Feed `venue_trades` liegt nur auf dem Server (B145); ob er Futures-Daten enthält, ist offen.

**Entscheidungen, die nur Uzi trifft**

1. Welches Setup zuerst, auf welchem Zeitrahmen (Fenster 3,2 bis 21 Setups je Woche, Abschnitt 2)? Je fünf gute und schlechte Beispiele mit Datum, alle bis 2022-12-31.
2. Welche Börse und welches Produkt? Der Betriebsplan fragt selbst nach Bybit (B146).
3. Zielbild: Bot als Anwendung (Dokumente ändern) oder Forschungssystem ohne Bot?
4. V5 praktisch: Gerät, Erreichbarkeit, Frist, Vertretung, Höchstzahl je Tag, Verhalten bei Abwesenheit.
5. V2/V3: Darf TIM in der Allowlist selbst mergen oder nur vorschlagen? Wer vergibt Registerplätze?
6. Broncx-Feed im Betrieb nutzen (dann nicht testbar) oder weglassen?
7. Kapitalrahmen und Verlustgrenze für Micro-Live: keine Empfehlung hier.
8. Zählt „profitabel“ auch, wenn Halten im selben Zeitraum mehr bringt?
9. V2-Blocker V2-B03 bis V2-B08 abschließen, ablösen oder offen lassen?
10. Wie viele der 12 freien Plätze bekommt die Methode (Vorschlag: höchstens 4)? Preis: Jede Variante verbraucht ihren Platz, auch wenn die Zählung in A6 unter dem Minimum liegt; es gibt keine Vorab-Zählung, die das verhindert.
11. Rastersperre: Zählt das Hinzufügen von höchstens 4 Varianten als „strenger“ (m steigt: B58) oder als Rasteränderung (B85)? Davon hängt ab, ob der Eintrag (U4) jetzt erfolgen darf; die Pakete P1 bis P5 sind davon unabhängig.
12. „Komplett autonom“: auch für Orders (dann L6, im Widerspruch zu V5) oder nur für den Betrieb?
13. Darf Uzi die Methode auf Beispiele bis 2022-12-31 beschränken, obwohl er 2023 bis 2026 kennt? Wenn nein: Wie vermerkt er sein Vorwissen?

## 9. Belegprotokoll

Datei-Belege nennen `pfad:zeile`, Befehle sind aus dem Repository-Wurzelverzeichnis wiederholbar. `<py>` im Text steht für die Python-Umgebung aus der Aufgabe. Die Pytest-Ausgaben in dieser Liste stammen aus meinen Läufen in dieser Sitzung.

1. **B1** Befehl: `git rev-parse --short HEAD; git log -1 --format=%ad --date=short`  
   Ausgabe: `2eafe92 ⏎ 2026-10-02`
2. **B2** Befehl: `python3 -c "import json,collections;r=[json.loads(l) for l in open('docs/research_lab/REGISTER.jsonl')];print(len(r),dict(collections.Counter(x['kind'] for x in r)),dict(collections.Counter(x.get('status') for x in r if x['kind']=='status')))"`  
   Ausgabe: `96 {'register': 48, 'status': 48} {'failed_validation': 6, 'failed_train': 42}`
3. **B3** Datei `docs/research_lab/reports/r4_2026-09-29T2219Z.md:5`: „**Kandidaten für den Holdout:** keine – kein Vorteil in Training/Validierung gefunden“
4. **B4** Datei `docs/research_lab/reports/r4_2026-09-29T2219Z.md:3`: „Holdout nicht geladen.“
5. **B5** Datei `docs/research_lab/PROTOKOLL.md:291`: „5. **Papier-Betrieb (R7)** nur für BESTANDEN-Kandidaten.“
6. **B6** Befehl: `grep -rliE "r7|papier" --include=*.py src/research_lab | wc -l`  
   Ausgabe: `0`
7. **B7** Datei `config/paper_demo.json:4`: „"status": "PREPARED_DATA_QUALITY_GATE_PENDING",“
8. **B8** (Obergrenzen-Rechnung, siehe B150; nur die Familien S und T, 14 Varianten; die übrigen Familien in B159) Befehl: `python3 -c "import json,statistics as s;V=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants'];R=[(v[p]['summary']['expectancy_r'],v['stress_'+p]['expectancy_r']) for k,v in V.items() if k[0] in 'ST' for p in ('train','validation')];c=[b-t for b,t in R];g=[2*b-t for b,t in R];print(len(R),'Werte; Kosten je Trade in R: Median',round(s.median(c),2),'Spanne',round(min(c),2),round(max(c),2));print('Brutto-E[R] Median',round(s.median(g),2),'Max',round(max(g),2),'positive Werte',sum(x>0 for x in g))"`  
   Ausgabe: `28 Werte; Kosten je Trade in R: Median 0.31 Spanne 0.14 0.61 ⏎ Brutto-E[R] Median -0.09 Max 0.15 positive Werte 4`
9. **B9** Befehl: `grep -rln "orderflow_scenario" --include=*.py src scripts main.py | grep -v "^src/orderflow_scenario/"`  
   Ausgabe: `src/market_data/providers/openmarket/mapper.py ⏎ scripts/openmarket_api_proof.py`
10. **B10** Datei `src/market_data/providers/openmarket/mapper.py:24`: „# OpenMarket interval -> TIM timeframe label (orderflow_scenario uses“
11. **B11** Befehl: `grep -rn "ForwardOnlyReplay" --include=*.py src scripts tests main.py`  
   Ausgabe: `src/orderflow_scenario/backtest.py:68:class ForwardOnlyReplay:`
12. **B12** Befehl: `grep -rn "ConfirmationUpdate(" --include=*.py src scripts tests main.py`  
   Ausgabe: `tests/test_orderflow_pipeline_trade_plan.py:44:    update = ConfirmationUpdate(long.scenario_id, long.mandatory_confirmations, (), ())`
13. **B13** Datei `docs/evidence/m09-p1-14/summary.json:60-61`: „"run2_inputs": "no recipe, no root cause", / "run2_used_known_case": true,“
14. **B14** Datei `docs/evidence/m09-p1-14/summary.json:62-63`: „"run3_blocker": "UNKNOWN_DEFECT_NO_APPROVED_RECIPE: fingerprint 548bd09f292063b9", / "run3_state": "BLOCKED",“
15. **B15** Befehl: `ls src/agents | grep -v pycache | tr '\n' ' '`  
   Ausgabe: `__init__.py contract.py monitoring.py project_manager.py review.py`
16. **B16** Datei `src/dashboard/server.py:234`: „if path not in {"/api/research/quick", "/api/research/deep"}:“
17. **B17** Datei `src/dashboard/layout.py:102-103`: „("FREIGABE", [ / ("V2 Readiness", "/v2-readiness"),“
18. **B18** Befehl: `grep -rn "mandatory_fulfilled_for_" --include=*.py src scripts tests main.py | grep -v "def " | wc -l`  
   Ausgabe: `0`
19. **B19** Datei `src/research_lab/data/archive.py:33-34`: „KLINES = "klines" / FUNDING = "fundingRate"“
20. **B20** Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:24`: „**Highest evidenced level: L1.**“
21. **B21** Befehl: `python3 -c "import json;d=json.load(open('artifacts/v2_readiness/coverage_final.json'));a=d['product_calculation'];f=d['frozen_published_reproduction']['audit'];p=lambda m,e:round(100*(1-m/e),3);print(p(a['missing_observations'],a['expected_observations']),d['gate_status'],d['evidence_cutoff_utc'],'| eingefroren',p(f['missing_observations'],f['expected_observations']))"`  
   Ausgabe: `67.346 FAIL 2026-08-01T15:01:00Z | eingefroren 60.659`
22. **B22** Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:16`: „No runtime setup engine, complete strategy contract, decision ID or risk approval“
23. **B23** Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:19`: „Send a bounded live order after explicit human approval“
24. **B24** Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:20`: „Execute bounded orders autonomously under continuous supervision“
25. **B25** Datei `src/orderflow_scenario/engines/trade_plan.py:3-4`: „Builds a structured, risk-aware trade plan ONLY from a CONFIRMED scenario. / The plan is a DRAFT until the Risk Engine decides. Position sizing and risk“
26. **B26** Datei `src/orderflow_scenario/engines/decision.py:133`: „expiration_condition=plan.expiration_condition,“
27. **B27** Befehl: `for t in tests/test_orderflow_pipeline_trade_plan.py tests/test_orderflow_trade_plan_builder.py tests/test_research_lab_guard.py; do PYTHONDONTWRITEBYTECODE=1 /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python -m pytest -q -p no:cacheprovider -m "not local_env" $t | tail -1; done`  
   Ausgabe: `2 passed in 0.15s ⏎ 6 passed in 0.11s ⏎ 7 passed in 205.67s (0:03:25)`
28. **B28** Datei `tests/test_orderflow_pipeline_trade_plan.py:17`: „wave = (0, 2, 4, 3, 1, 2)“
29. **B29** Datei `src/orderflow_scenario/engines/confirmation.py:5-6`: „or PROPOSED -> INVALIDATED / EXPIRED. Confirmations and invalidations are / provided as deterministic observations; this engine only advances state.“
30. **B30** Datei `tests/test_orderflow_pipeline_trade_plan.py:44`: „update = ConfirmationUpdate(long.scenario_id, long.mandatory_confirmations, (), ())“
31. **B31** Befehl: `grep -c -i "fee\|slippage\|funding" src/orderflow_scenario/backtest.py`  
   Ausgabe: `0`
32. **B32** Datei `src/orderflow_scenario/backtest.py:89`: „return True, (lead.close - lead.open) / lead.open if lead.open > 0 else None“
33. **B33** Datei `src/orderflow_scenario/backtest.py:6-7`: „are provisional and MUST NOT be claimed as a profitable strategy without / out-of-sample proof on a separate test period.“
34. **B34** Datei `docs/tim_v4_developer_manual/IMPLEMENTATION_GAP.md:28`: „- Quelle: `tools/`, `src/strategy/`, `src/backtest/`, `src/orderflow_scenario/engines/backtest/` existieren nicht.“
35. **B35** Befehl: `ls src/orderflow_scenario/engines | grep -v pycache | tr '\n' ' '`  
   Ausgabe: `__init__.py confirmation.py data_quality.py decision.py market_state.py orderflow_interpretation.py pipeline.py probability.py risk.py scenario_generator.py trade_plan.py`
36. **B36** (Quelle nicht öffentlich)
37. **B37** Datei `scripts/m09_p1_14_self_heal_proof.py:4-5`: „re-created by this harness; the engine repairs it with the recipe / approved in P1.10 (commits --approved-base..--approved-repair).“
38. **B38** Datei `src/task_engine/self_heal.py:8-9`: „Without a known case or an explicitly approved recipe the task is BLOCKED; / nothing is improvised. Nothing here creates or syncs GitHub issues (#68).“
39. **B39** Datei `scripts/m09_p1_14_self_heal_proof.py:11-12`: „Defects are injected before the engine is called; nobody edits code during a / run. Disposable clones live in the temp dir and have no remote; the task store“
40. **B40** Datei `docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md:16-17`: „Befund: Seit 30.09. 16:35 UTC entstehen keine Kerzen. Ursache war ein Netzausfall Richtung / Binance (`Errno 113` zu Port 9443, 09:27–17:56 UTC). Seitdem hängt die alte Runtime beim“
41. **B41** Datei `docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md:19-20`: „reached`) und geht nie zurück in den Live-Betrieb. Der Watchdog startet nicht neu, weil / `venue_trades` noch fließt. Dieselbe Nachhol-Logik steckt auch in `/opt/tim`“
42. **B42** Datei `src/research_lab/hypotheses/registry.py:76`: „VARIANTS: tuple[VariantSpec, ...] = tuple(_specs())“
43. **B43** Datei `src/research_intelligence/engine.py:1`: „"""Versioned conservative research rules; confidence is evidence, not probability."""“
44. **B44** Datei `src/research_intelligence/expansion.py:20`: „# No observed derivative feed or storage adapter exists in this deployment.“
45. **B45** Datei `src/agent_infra/router.py:4-5`: „the same RoutingDecision (verified by decision hash). The router chooses / CONTEXT TOOLS only — it never grants write or production authority."""“
46. **B46** Datei `TIM_AI_AGENT_CONSTITUTION.md:147-148`: „- Releases eigenständig freigeben; / - Live Trading ohne explizite menschliche Freigabe aktivieren.“
47. **B47** Datei `docs/research_lab/PROTOKOLL.md:219-220`: „**Obergrenze: 60 Varianten.** Wird sie erreicht, sind weitere Hypothesen erst mit / einem neuen, später liegenden Holdout-Zeitraum zulässig.“
48. **B48** Datei `docs/autonomous_trader/DEBIAN_SERVER_SETUP_TASK_PACKAGE.md:63`: „14 Tage, Start frühestens 48 h nach Abnahme von Schritt 1“
49. **B49** Datei `src/orchestration/core.py:215-216`: „if state.phase is MissionPhase.M04_COLLECTION: / self._job_once(state, "bounded_collection", limit=self.config.collection_max_events)“
50. **B50** Datei `docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md:10`: „Units deaktiviert“
51. **B51** Befehl: `ls ops/systemd | grep -c service; ls ops/systemd | grep -c timer`  
   Ausgabe: `9 ⏎ 7`
52. **B52** Datei `src/dashboard/server.py:59`: „return self.respond(421, b'{"error":"loopback Host header required"}', "application/json")“
53. **B53** Datei `src/orderflow_scenario/domain.py:48`: „"""Operational modes. LIVE is intentionally absent: no enum value may map to live order execution."""“
54. **B54** Datei `src/orderflow_scenario/engines/decision.py:48`: „if inputs.kill_switch_enabled is False:“
55. **B55** Datei `src/orderflow_scenario/governance.py:215`: „if self.kill_switch.enabled and self.kill_switch.block_live_execution and mode == Mode.OBSERVE:“
56. **B56** Befehl: `grep -rnF -e "orderflow_scenario.governance" -e "from .governance" --include=*.py src scripts tests main.py | wc -l; ls config/orderflow_scenario_governance.json 2>&1 | tail -1`  
   Ausgabe: `0 ⏎ ls: cannot access 'config/orderflow_scenario_governance.json': No such file or directory`
57. **B57** Datei `docs/research_lab/PROTOKOLL.md:218`: „**Startbestand: m = 48 Varianten** (L 12, M 22, S 8, T 6).“
58. **B58** Datei `docs/research_lab/PROTOKOLL.md:316-317`: „Validierung, wird sie nicht umparametriert. Eine neue Parametrierung ist ein / neuer Registereintrag über das Änderungsprotokoll und erhöht m.“
59. **B59** Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:63`: „| L4 → L5 | Separate explicit authorization, independent security/safety audit, manual approval per order and isolated credentials |“
60. **B60** Datei `docs/research_lab/PROTOKOLL.md:117`: „- Einstieg zum **Eröffnungskurs der nächsten Kerze**.“
61. **B61** Befehl: `python3 -c "import json;V=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants'];print(' | '.join(k+' '+str(round(V[k]['validation']['summary']['trades']/(731/7),2)) for k in ('S1-N20-5m','T1-bos-15m','T1-bos-1h','S2-london-r30','M1-N20-k2','L2-L30-ls','L1-n100-ls')),'(Trades je Woche, Validierung 2023-24)')"`  
   Ausgabe: `S1-N20-5m 90.7 | T1-bos-15m 52.19 | T1-bos-1h 13.3 | S2-london-r30 4.83 | M1-N20-k2 0.29 | L2-L30-ls 1.01 | L1-n100-ls 0.3 (Trades je Woche, Validierung 2023-24)`
62. **B62** Befehl: `python3 -c "import datetime as d;w=lambda a,b:(b-a).days/7;print('Trades je Woche mindestens: Mid Training',round(50/w(d.date(2020,1,1),d.date(2023,1,1)),2),'| Mid Holdout',round(30/w(d.date(2025,1,1),d.date(2026,10,1)),2),'| Short Holdout',round(200/w(d.date(2025,1,1),d.date(2026,10,1)),2))"`  
   Ausgabe: `Trades je Woche mindestens: Mid Training 0.32 | Mid Holdout 0.33 | Short Holdout 2.19`
63. **B63** Datei `docs/research_lab/PROTOKOLL.md:303-304`: „- **Laufzeit:** mindestens 4 Wochen, verlängert bis höchstens 8 Wochen, solange / weniger als 20 Trades (Short, Mid) angefallen sind.“
64. **B64** (Quelle nicht öffentlich)
65. **B65** Befehl: `python3 -c "import json;V=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants'];print({k:(round(v['train']['summary']['expectancy_r'],2),round(v['validation']['summary']['expectancy_r'],2)) for k,v in V.items() if k[0]=='T'})"`  
   Ausgabe: `{'T1-bos-15m': (-0.44, -0.61), 'T2-rejection-15m': (-0.45, -0.67), 'T3-failedcont-15m': (-0.61, -0.84), 'T1-bos-1h': (-0.25, -0.28), 'T2-rejection-1h': (-0.25, -0.33), 'T3-failedcont-1h': (-0.37, -0.46)}`
66. **B66** Datei `docs/knowledge/BRONCX_DISCORD_FEED.md:11`: „Scores gewichten: Szenarien in seiner Richtung +0,08, Gegenszenarien −0,08“
67. **B67** Datei `TIM_CONSTITUTION.md:13-14`: „TIM ist kein Trading-Bot, keine Ansammlung einzelner KI-Agenten und kein / Experiment. TIM ist eine deterministische, reproduzierbare und wissenschaftlich“
68. **B68** Datei `TIM_LONG_TERM_EVOLUTION_VISION_CONSTITUTION.md:30-31`: „vertrauenswürdige KI-Forschungsplattform entwickelt. Das Ziel ist nicht der Bau / eines Trading-Bots, sondern eines intelligenten Forschungssystems, das“
69. **B69** Datei `TIM_LONG_TERM_EVOLUTION_VISION_CONSTITUTION.md:34`: „Trading ist eine Anwendung, nicht die Identität von TIM.“
70. **B70** Datei `docs/VISION_2030.md:19`: „- No API keys, exchange accounts, wallets, real orders or execution paths belong in the research architecture.“
71. **B71** Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:19`: „NOT REACHED / PROHIBITED“
72. **B72** Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:64`: „Not planned by this baseline“
73. **B73** Datei `docs/autonomous_trader/IMPLEMENTATION_ROADMAP.md:22`: „10 Limited live | explicitly not authorized“
74. **B74** Datei `TIM_LONG_TERM_EVOLUTION_VISION_CONSTITUTION.md:225-226`: „Die Constitution darf kontrolliert weiterentwickelt werden. Ihre / Grundprinzipien bleiben erhalten. „Unveränderliche Grundlage“ bedeutet Schutz“
75. **B75** Datei `docs/research_lab/PROTOKOLL.md:34`: „Ein Setup gilt als profitabel, wenn es **alle fünf** Bedingungen erfüllt:“
76. **B76** Datei `docs/research_lab/PROTOKOLL.md:42`: „| K5 | Papier-Betrieb im erwarteten Band | R7, 4–8 Wochen | „bestätigt“ oder „kein Widerspruch“ (Abschnitt 9) |“
77. **B77** Datei `docs/research_lab/PROTOKOLL.md:327-328`: „- **Kein echtes Geld** vor Abschluss von R7 und einem eigenen, freigegebenen / Bauplan dafür.“
78. **B78** Datei `docs/research_lab/PROTOKOLL.md:222`: „Zur Einordnung: Bei m = 48 muss der beste Kandidat im Holdout p < 0,05 / 48 ≈ 0,0010“
79. **B79** Datei `docs/research_lab/PROTOKOLL.md:40`: „Short ≥ 200, Mid ≥ 30, Long ≥ 10“
80. **B80** Datei `docs/research_lab/PROTOKOLL.md:44-45`: „Unterschreitet ein Setup K3, lautet das Urteil **KEIN URTEIL**, nicht BESTANDEN. / Für M1 mit N = 55 und für M2 ist das im Holdout von rund 20 Monaten wahrscheinlich,“
81. **B81** Datei `docs/research_lab/PROTOKOLL.md:41`: „| K4 | maximaler Drawdown | Holdout | ≤ **20 %** bei 1 % Risiko je Trade |“
82. **B82** Datei `docs/research_lab/PROTOKOLL.md:164`: „95-%-Konfidenzintervall des Erwartungswerts (Block-Bootstrap über“
83. **B83** Befehl: `python3 -c "import json,statistics as s;from statistics import NormalDist as N;V=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants'];f=lambda m,sd,n:round(N().cdf(m*n**.5/sd+1.645)-N().cdf(m*n**.5/sd-1.645),2);sd={h:s.median([v['validation']['summary']['std_r'] for v in V.values() if v['horizon']==h]) for h in ('short','mid')};print('short n=19,84,360 bei 0.30 R:',[f(0.30,sd['short'],n) for n in (19,84,360)]);print('mid n=2,5,20 bei 0.40 R:',[f(0.40,sd['mid'],n) for n in (2,5,20)])"`  
   Ausgabe: `short n=19,84,360 bei 0.30 R: [0.75, 0.36, 0.01] ⏎ mid n=2,5,20 bei 0.40 R: [0.79, 0.64, 0.18]` (Anteil der Nullvorteil-Läufe im 90-%-Normalband um das Holdout-Mittel; Normalnäherung, kein Bootstrap; Streuung Short 1,37 R, Mid 0,70 R aus dem Median der Validierungs-Streuung der Regeln gleichen Horizonts; das Mittel 0,30 bzw. 0,40 R ist die K2-Schwelle aus B105, also der günstigste Fall für ein bestandenes Setup)
84. **B84** Datei `docs/research_lab/reports/r4_2026-09-29T2219Z.md:109`: „Kaufen und Halten Spot (Vergleich, kein Kriterium): Training 252,7 %, Validierung 465,7 %.“
85. **B85** Datei `docs/research_lab/PROTOKOLL.md:346-347`: „Nur anhängen, nie überschreiben. Nach Beginn von R4 sind Änderungen an Datensplit, / Kriterien und Raster nur noch erlaubt, wenn sie strenger machen.“
86. **B86** Befehl: `git log --format=%ad --date=short -- src/research_lab/backtest src/research_lab/hypotheses src/research_lab/stats | sort -u`  
   Ausgabe: `2026-09-29`
87. **B87** Datei `docs/research_lab/reports/r4_2026-09-29T2219Z.md:10`: „| L1-n100-ls | 61/31 | 0,794 | 0,396 | 0,748/0,371 | 0,0461 | 0,2075 |“
88. **B88** Datei `docs/tim_v4_developer_manual/VERIFICATION_REPORT.md:149`: „- Fehlende Tests: keine eigene Backtestdatei.“
89. **B89** Datei `src/orderflow_scenario/engines/probability.py:3-4`: „Scores scenarios without fabricating statistical precision. Unless empirical / calibration exists, every score is labelled HEURISTIC_SCORE or“
90. **B90** Datei `src/orderflow_scenario/engines/pipeline.py:200-201`: „orderflow=orderflow, / data_quality_confidence=quality.confidence,“
91. **B91** Datei `src/orderflow_scenario/engines/trade_plan.py:36-37`: „# 1.5R tier minimum (decision 2026-09-30); below it no plan was ever built. / TARGET_R = (Decimal("1.5"), Decimal("2"), Decimal("3"))“
92. **B92** Datei `src/research_lab/data/parse.py:27`: „taker_buy_volume: float“
93. **B93** Datei `docs/research_lab/PROTOKOLL.md:63`: „| aggTrades BTCUSDT | USD-M Perpetual | – | optional, nur Stichproben zur Prüfung der Delta-Näherung |“
94. **B94** Datei `docs/autonomous_trader/DATA_READINESS_MATRIX.md:19`: „Binance Spot BTCUSDT public `@aggTrade`“
95. **B95** Datei `docs/autonomous_trader/DATA_READINESS_MATRIX.md:20`: „Futures AggTrades | MISSING“
96. **B96** Datei `docs/autonomous_trader/DATA_READINESS_MATRIX.md:24`: „Open interest | MISSING“
97. **B97** Datei `docs/autonomous_trader/DATA_READINESS_MATRIX.md:26`: „Order-book snapshots | MISSING“
98. **B98** Datei `docs/research_lab/PROTOKOLL.md:60`: „| Klines BTCUSDT | USD-M Perpetual | 1d, 1h, 15m, 5m | Handelsinstrument für Mid und Short |“
99. **B99** Datei `src/data_ingestion/catchup.py:251`: „reason = f"bounded catch-up page limit {self.max_pages} reached"“
100. **B100** Datei `docs/autonomous_trader/DATA_READINESS_MATRIX.md:80`: „- no automatic historical catch-up;“
101. **B101** Datei `docs/research_lab/reports/r4_2026-09-29T2219Z.md:72`: „- **M1-N20-k2:** Training: 35 < 50 Trades; Training: p >= 0,10 gegen Zufall“
102. **B102** Datei `docs/research_lab/reports/r4_2026-09-29T2219Z.md:62`: „- **L1-n150-l:** Training: 17 < 20 Trades; Training: p >= 0,10 gegen Zufall“
103. **B103** Datei `docs/research_lab/PROTOKOLL.md:280`: „Mindesttrades erreicht (Short ≥ 500, Mid ≥ 50, Long ≥ 20)“
104. **B104** Datei `src/research_lab/runner.py:40-41`: „SPOT_SIGNALS_MS = _utc_ms(2017, 9, 1) / USDM_LOAD = (2020, 1)“
105. **B105** Befehl: `python3 -c "import json,math,statistics as s;V=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants'];print({h:(round(3.09*s.median([v['validation']['summary']['std_r'] for v in V.values() if v['horizon']==h])/math.sqrt(n),2),round(3.93*s.median([v['validation']['summary']['std_r'] for v in V.values() if v['horizon']==h])/math.sqrt(n),2)) for h,n in (('short',200),('mid',30),('long',10))})"`  
   Ausgabe: `{'short': (0.3, 0.38), 'mid': (0.4, 0.5), 'long': (1.53, 1.94)}` (Paare: kritischer Wert bei α = 0,001 und Effekt bei 80 % Power, z = 3,09 und 3,09 + 0,84)
106. **B106** Datei `docs/research_lab/PROTOKOLL.md:107-108`: „Zeitraum abgeleitet. Für TIMs eigene Regeln (T1–T3) gilt das nicht sicher, weil sie / 2026 entwickelt wurden, also im Holdout-Zeitraum. Ein BESTANDEN dort ist schwächer“
107. **B107** Datei `docs/research_lab/PROTOKOLL.md:109-110`: „belegt und wird so ausgewiesen. Den wirklich frischen Test liefert der / Papier-Betrieb (R7).“
108. **B108** Datei `scripts/research_lab_run.py:38-39`: „if "holdout" in args.split.split(","): / parser.error("holdout is R6 and runs exactly once after an explicit go; not available here")“
109. **B109** Datei `docs/research_lab/PROTOKOLL.md:299-301`: „angefallene Tradezahl, gezogen per einfachem Bootstrap (Trades einzeln) aus den / Validierungs- und Holdout-Trades der Variante.“
110. **B110** Datei `docs/research_lab/PROTOKOLL.md:342`: „Offen: Gebührenstufe“
111. **B111** Datei `src/research_lab/protocol.py:40-41`: „fee: float = 0.0005 / slippage: float = 0.0003“
112. **B112** Datei `src/orderflow_scenario/execution/paper.py:77`: „"""Stores paper/shadow records in memory. Never submits orders."""“
113. **B113** Befehl: `grep -rn "PaperExecutionJournal" --include=*.py src scripts tests main.py | grep -v "^src/orderflow_scenario/execution/" | wc -l`  
   Ausgabe: `0`
114. **B114** Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:17`: „No paper order state machine, broker, fills, positions, rejection/partial-fill lifecycle or runtime wiring“
115. **B115** Datei `docs/autonomous_trader/LIVE_EXECUTION_RISK_REGISTER.md:14`: „NO_LIVE_EXECUTION_PATH_FOUND“
116. **B116** Befehl: `grep -rniE "newOrder|fapi/v1/order|api/v3/order|place_order|X-MBX-APIKEY|ccxt" --include=*.py src scripts main.py config | wc -l`  
   Ausgabe: `0`
117. **B117** Datei `src/orderflow_scenario/engines/risk.py:123`: „if position_size / account.equity > limits.max_account_fraction_per_position:“
118. **B118** Befehl: `PYTHONDONTWRITEBYTECODE=1 /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python -I -c "import sys; sys.path.insert(0,'.'); from decimal import Decimal as D; from tests.test_orderflow_pipeline_trade_plan import confirmed_run; d=confirmed_run()[1].to_dict()['decision']; p=d['trade_plan']; print(d['risk']['status'], 'Nominal/Eigenkapital =', float(D(str(p['position_size']))*D(str(p['entry_zone_low']))/D('10000')), '(Grenze im Code: 0.1)')"`  
   Ausgabe: `APPROVED Nominal/Eigenkapital = 1.0 (Grenze im Code: 0.1)`
119. **B119** Datei `src/orderflow_scenario/engines/pipeline.py:242`: „account = inputs.account or AccountState(equity=Decimal("10000"), free_margin=Decimal("10000"))“
120. **B120** Befehl: `grep "^| V2-B0" TIM_V2_BLOCKER_REGISTER.md | grep -c "OPEN"`  
   Ausgabe: `8`
121. **B121** Datei `docs/autonomous_trader/DEBIAN_MAC_OPERATING_PLAN.md:68`: „schließt V2-B01/B02 prospektiv“
122. **B122** Datei `TIM_V2_BLOCKER_REGISTER.md:33`: „| V2-B08 | Formal V2 responsibility matrix absent | P0 | Governance Lead | Named role assignments | **OPEN** |“
123. **B123** Datei `docs/autonomous_trader/CURRENT_STATE_ASSESSMENT.md:41-42`: „| Backtest/walk-forward | no engine found | — | — | MISSING | / | Risk/order/position management | no engine found | — | — | MISSING |“
124. **B124** Befehl: `ls src/research_lab/backtest/engine.py src/orderflow_scenario/engines/risk.py`  
   Ausgabe: `src/orderflow_scenario/engines/risk.py ⏎ src/research_lab/backtest/engine.py`
125. **B125** Datei `docs/autonomous_trader/STRATEGY_READINESS_MATRIX.md:86`: „**MISSING.**“
126. **B126** Datei `docs/autonomous_trader/STRATEGY_READINESS_MATRIX.md:72`: „| strategy_id/version | MISSING |“
127. **B127** Datei `docs/tim_v4_developer_manual/VERIFICATION_REPORT.md:147`: „Implementierungsgrad: `VERIFIED ~92 % · PARTIAL ~8 %`.“
128. **B128** Datei `docs/research_lab/PROTOKOLL.md:353`: „Ergebnis: 0 von 200 Zufallsreihen BESTANDEN, 190 von 200 Reihen mit +0,2 R BESTANDEN“
129. **B129** Datei `src/research_lab/data/store.py:4-5`: „by git). The store refuses holdout months unless the caller holds a holdout / permission, so holdout data cannot be loaded by accident before R6.“
130. **B130** Befehl: `for d in src/research_lab/external src/research_lab; do find $d -name '*.py' -not -path '*/__pycache__/*' | xargs cat | wc -l; done`  
   Ausgabe: `3042 ⏎ 5252`
131. **B131** Befehl: `for d in src/research_lab/external "src/research_lab/hypotheses src/research_lab/backtest src/research_lab/stats"; do git log --since=2026-09-15 --format=%h -- $d | wc -l; done`  
   Ausgabe: `23 ⏎ 3`
132. **B132** Befehl: `grep -rliE "research_lab\.external|cpi" src/research_lab/hypotheses src/research_lab/runner.py src/research_lab/backtest src/research_lab/stats | wc -l`  
   Ausgabe: `0`
133. **B133** Datei `docs/research_lab/EXTERNAL_DATA.md:295`: „Reihenfolge der BTC Research Engine: **V1 (#128) → V1.1 (#139) → V1.2 → V2**.“
134. **B134** Befehl: `for d in src/task_governance src/tim_manager src/graph_mcp src/obsidian_vault src/dashboard; do printf "%s=%s " $d $(find $d -name '*.py' -not -path '*/__pycache__/*' | xargs cat | wc -l); done; echo`  
   Ausgabe: `src/task_governance=1162 src/tim_manager=3147 src/graph_mcp=2225 src/obsidian_vault=669 src/dashboard=4177`
135. **B135** Datei `docs/autonomous_trader/DEBIAN_MAC_OPERATING_PLAN.md:78-79`: „- **Engpass ist Edge, nicht Governance:** Governance nur so weit ausbauen, wie / das nächste Gate es verlangt.“
136. **B136** Datei `docs/autonomous_trader/DATA_READINESS_MATRIX.md:19`: „duplicate/collision/restart/hash tests in `test_agg_trade_persistence.py`“
137. **B137** Datei `docs/autonomous_trader/DEBIAN_MAC_OPERATING_PLAN.md:80`: „- **Scope:** ein Instrument, ein Timeframe, eine Strategie zuerst.“
138. **B138** Datei `docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md:1`: „# Umzug auf tim-core-01: `/srv/tim` → `/opt/tim`“
139. **B139** Datei `docs/research_lab/PROTOKOLL.md:324-325`: „- **Papier-Stopp:** Liegt der Live-Erwartungswert nach mindestens 20 Trades unter / dem 5. Perzentil des Bands oder überschreitet der Drawdown die Grenze aus K4,“
140. **B140** Datei `docs/autonomous_trader/IMPLEMENTATION_ROADMAP.md:21`: „9 Shadow | separate future approval only“
141. **B141** Datei `scripts/research_lab_fetch.py:33`: „parser.add_argument("--funding", action="store_true", help="fetch funding rates instead of klines")“
142. **B142** Datei `docs/autonomous_trader/DEBIAN_MAC_OPERATING_PLAN.md:90`: „ohne Änderung an Core-1.0-Logik“
143. **B143** Datei `docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md:68`: „Danach 72 h Beobachtung. Erst dann wird das Messfenster deklariert (P7).“
144. **B144** Datei `src/orderflow_scenario/adapters/openmarket.py:14`: „confirms it; by default they stay missing (REST_SIDE_AGGRESSOR_SEMANTICS=UNPROVEN).“
145. **B145** Datei `docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md:11`: „schreibt `venue_trades`, nicht auf GitHub“
146. **B146** Datei `docs/autonomous_trader/DEBIAN_MAC_OPERATING_PLAN.md:95`: „- Bleibt Binance Spot die Primärquelle, oder kommt Bybit (wie in Bronxc) hinzu?“
147. **B147** Datei `tests/test_research_lab_hypotheses.py:22`: „    assert len(VARIANTS) == 48“
148. **B148** Datei `scripts/research_lab_run.py:47`: „parser.error("--commit-register needs the full run without --only")“
149. **B149** Datei `docs/research_lab/PROTOKOLL.md:89`: „| Holdout | 2025-01-01 bis Ende des letzten vollständigen Monats vor dem R6-Lauf | genau ein Lauf (R6) |“ (Training bis 2022-12-31 und Validierung 2023-01-01 bis 2024-12-31 stehen in den Zeilen davor)
150. **B150** Datei `src/research_lab/protocol.py:50`: „return CostModel(self.fee * 2, self.slippage * 2, self.stop_slippage * 2, funding_credits_allowed=False)“ (Folge: B8 misst Kostenverdopplung plus Wegfall der Funding-Gutschriften. Mit Basiskosten c und entgangenen Gutschriften L ≥ 0 ist die Differenz b − t = c + L und 2b − t = Brutto + L: beide Werte sind Obergrenzen.)
151. **B151** Datei `src/research_lab/backtest/engine.py:73`: „Strategy = Callable[[History], Signal | None]“
152. **B152** Datei `docs/research_lab/PROTOKOLL.md:223-224`: „gegen zufällige Einstiege erreichen. Mit wenigen Trades (vor allem Long) ist das / kaum zu schaffen. Das ist gewollt“
153. **B153** Datei `src/research_lab/runner.py:76`: „return [ArchiveRef(spec.market, Dataset.KLINES, y, m, spec.interval) for y, m in months(start, LAST_MONTH)]“
154. **B154** Datei `src/research_lab/backtest/engine.py:17-18`: „class History(Sequence[Kline]): / """Read-only view of bars[0..t]; the future does not exist for a strategy."""“
155. **B155** Datei `src/research_lab/data/parse.py:30-31`: „def delta(self) -> float: / """Taker buy minus taker sell volume (protocol section 3.1)."""“
156. **B156** Datei `tests/test_research_lab_backtest.py:21`: „return Kline(t0 + i * H, o, h, l, c, 10.0, t0 + (i + 1) * H - 1, 5.0)“ (positionale Aufrufe mit acht Feldern: neue Felder brauchen Standardwerte)
157. **B157** Datei `src/orderflow_scenario/governance.py:265`: „enabled=True,“ (Standardwert des Kill Switch)
158. **B158** Datei `docs/research_lab/PROTOKOLL.md:88`: „| Validierung | 2023-01-01 bis 2024-12-31 | Kandidaten bestätigen, Auswahl für Holdout |“
159. **B159** Befehl: `python3 -c "import json,statistics as s;V=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants'];G={'ST':lambda k:k[0] in 'ST','L':lambda k:k[0]=='L','M12':lambda k:k[:2] in('M1','M2'),'M3':lambda k:k[:2]=='M3'}
for g,f in G.items():
    R=[(v[p]['summary']['expectancy_r'],v['stress_'+p]['expectancy_r']) for k,v in V.items() if f(k) for p in ('train','validation')];print(g,len(R),'Werte; Netto-E[R] Median',round(s.median([b for b,t in R]),2),'positiv',sum(b>0 for b,t in R),'; Kostenaufschlag Median',round(s.median([b-t for b,t in R]),2),'; Brutto-Obergrenze Median',round(s.median([2*b-t for b,t in R]),2))"`  
    Ausgabe: `ST 28 Werte; Netto-E[R] Median -0.39 positiv 0 ; Kostenaufschlag Median 0.31 ; Brutto-Obergrenze Median -0.09 ⏎ L 24 Werte; Netto-E[R] Median 0.3 positiv 24 ; Kostenaufschlag Median 0.02 ; Brutto-Obergrenze Median 0.32 ⏎ M12 16 Werte; Netto-E[R] Median 0.09 positiv 13 ; Kostenaufschlag Median 0.04 ; Brutto-Obergrenze Median 0.15 ⏎ M3 28 Werte; Netto-E[R] Median -0.02 positiv 7 ; Kostenaufschlag Median 0.04 ; Brutto-Obergrenze Median 0.02` (Je Familie Training und Validierung; Netto heißt: mit den Basiskosten des Protokolls, wie im Bericht. Alle Werte sind In-Sample-Werte vor dem Holdout und beweisen keinen Vorteil: alle 48 Varianten sind durchgefallen.)
160. **B160** Datei `docs/research_lab/PROTOKOLL.md:318-319`: „- **Kein Nachbessern am Holdout:** Ein NICHT BESTANDEN im Holdout ist endgültig / für diese Variante und alle Varianten, die aus ihr abgeleitet werden.“
161. **B161** Befehl: `python3 -c "import datetime as d;w=lambda a,b:(b-a).days/7;t=w(d.date(2020,1,1),d.date(2023,1,1));h=w(d.date(2025,1,1),d.date(2026,10,1));print('Trainingswochen',round(t,1),'| Short Training min/Woche',round(500/t,2),'| Holdout-Wochen',round(h,1),'| 0,29/Woche im Holdout',round(0.29*h,1),'Trades')"`  
    Ausgabe: `Trainingswochen 156.6 | Short Training min/Woche 3.19 | Holdout-Wochen 91.1 | 0,29/Woche im Holdout 26.4 Trades` (Zusatz: gleiche Formel wie B83 für Short, Streuung 1,37 R, Mittel 0,30 R, n = 20, 26, 84, 360 ergibt Anteil 0,74, 0,70, 0,36, 0,01.)
162. **B162** Befehl: `for t in tests/test_observation_engine.py tests/test_orderflow_observations.py tests/test_orderflow_metrics.py; do PYTHONDONTWRITEBYTECODE=1 /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python -m pytest -q -p no:cacheprovider -m "not local_env" $t | tail -1; done`  
    Ausgabe: `2 passed in 0.09s ⏎ 4 passed, 1 skipped in 0.10s ⏎ 7 passed in 0.10s`
163. **B163** Datei `main.py:155-156`: „if candle.timeframe=="1m": / await self.process_orderflow_window(candle.open_time,candle.close_time)“ (Aufruf im Kerzen-Pfad der Anwendung; ob der Server diesen Pfad heute fährt: UNVERIFIED)
164. **B164** Datei `src/orderflow_scenario/engines/confirmation.py:65`: „def mandatory_fulfilled_for_breakout(close_above_trigger: bool, retest_holds: bool, constructive: bool, no_fall_back: bool) -> bool:“ (Zeilen 69 und 73 tragen die Eingaben für Umkehr und Ablehnung, z. B. `liquidity_swept`, `retest_fails`.)
