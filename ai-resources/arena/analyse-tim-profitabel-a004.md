# Was fehlt TIM zum profitablen Trading-Bot nach Uzis Vision?

*Stand: HEAD 2eafe92 (2026-10-02). Repository unverändert, kein Netzaufruf. Binance-Rohdaten liegen hier nicht (B1); R4-Zahlen sind nachgerechnet. Kennungen (B…) verweisen auf Abschnitt 9. Prosa der Abschnitte 1 bis 8 ohne Tabellenzeilen: höchstens 3.000 Wörter.*

## 1. Kurzurteil

Von „profitabel“ ist TIM weit entfernt: Keine der 48 getesteten Varianten zeigt K1 (42 scheiterten im Training, 6 in der Validierung), K5 ist nie begonnen (B2, B3, B4); T1 bis T3, TIMs eigene Regeln, sind schon vor Gebühr und Slippage negativ (ABGELEITET: B5 + B6). Von Uzis Vision ist V1 Code, der nie über Historie lief (B7, B8, B9), V2 gilt nur für freigegebene Patches (B10, B11), V3 und V4 fehlen im Kern (B12, B13), V5 gilt nur, weil ich keinen Order-Pfad finde (B14). Der eine größte Engpass: Es gibt keinen Beleg, dass Uzis Orderflow-Methode einen Vorteil hat, weil sie nie über Historie gemessen wurde (B3, B7, B8, B15); solange das fehlt, ist offen, ob es etwas zu automatisieren gibt. Einordnung: Das Dokument nennt L1 (B17); der Code belegt Beobachtungs-Bausteine (B155) und Bausteine bis L3 (B16, B24), unverdrahtet (B9, B25); der Betrieb ist gestört (60,659 % Coverage, keine Kerzen seit 30.09.; B33, B34); ABGELEITET: im Betrieb höchstens L1, die Vision ist L5, nicht L6 (B19), und der UNVERIFIED Serverzustand trägt das Urteil nicht (B20, B34).

## 2. Die Vision, strukturiert

**Begriffe (Annahme, naheliegendste Lesart).** *Setup* = vollständiger Handelsplan wie `TradePlan`: Richtung, Einstiegszone, Stop, Ziele, Invalidierung, Verfall, Risikoentscheid (B22). *Bestätigt* = ein Mensch stimmt dem Plan vor Verfall ausdrücklich zu, nicht der Engine-Status `CONFIRMED` (nur Marktbedingung, B23). *Komplett autonom* = Daten, Analyse, Reparatur, Hypothesentests und Betrieb laufen ohne Menschen, außer bei Setup-Bestätigung, Kapital, Holdout-Freigabe, Verfassungsänderungen.

| Teil | Erfüllt, wenn … | Heute (Beleg) | Abstand |
|---|---|---|---|
| **V1 Tradingwissen** | (a) die Kette Kontext → Ort → Struktur → Orderflow → Reaktion → Szenario → Invalidierung als deterministische, versionierte Regel läuft, (b) sie auf Historie ohne Look-ahead replayt, (c) ein Kandidat PROTOKOLL §8 Schritt 1 bis 3 besteht. | Pipeline mit Szenarien, Plan und Risk-Entscheid existiert, Tests grün (B16, B24). Nie über Historie (B7, B25). Bestätigung wird nirgends berechnet (B8, B15). Wahrscheinlichkeiten heuristisch (B26, B27). | Regel existiert als Code ohne Testweg: Replay-Adapter, Bestätigungsregeln, Strategievertrag fehlen. |
| **V2 Selbstreparatur** | TIM diagnostiziert einen unbekannten Defekt in einer Sandbox, erzeugt den Patch, bringt Tests ohne Abschwächung grün, ändert nur erlaubte Pfade; der Mensch merged. | Der Executor wendet einen freigegebenen Patch mit Hash-Prüfung an (B28). Der Diff der „ersten autonomen Reparatur“ ist zeilengleich mit dem Menschen-Commit 3bb2d62 (B10). Lauf 2 nutzt den gespeicherten Fall, Lauf 3 mit unbekanntem Defekt bleibt BLOCKED (B11, B29). | Diagnose und Patch-Erzeugung für Unbekanntes fehlen. |
| **V3 Selbstentwicklung** | TIM schlägt Hypothesen als Registereinträge vor, führt sie nach PROTOKOLL durch Training und Validierung, hält Budget und „Verworfen bleibt verworfen“ ein und berichtet. | Das Lab läuft nur per Hand-CLI (B30) über 48 von Menschen geschriebene Varianten (B2). In `agents`, `agent_infra`, `research_intelligence` gibt es kein Hypothesen-Modul (B12). Der Review-Agent genehmigt nie (B31). | Vorschlags- und Budgetkreislauf fehlen. |
| **V4 Selbststeuerung** | 14 Tage ohne menschlichen Eingriff laufen Collector, Lückenschluss, Analyse, Berichte und Aufgabenverteilung; Ausfälle werden behoben oder gemeldet; Coverage ≥ 99,5 %. | Der Orchestrator ist ein Wiederherstellungs-Automat für Datenlücken (B13). Letzte gemessene Coverage 60,659 % (B32, B33). Doku (Stand 01.10.): auf dem Server schreibt die alte Runtime seit 30.09. keine Kerzen, die Neuinstallation wartet auf Uzis Go (B34, B103, B20); heutiger Zustand UNVERIFIED. | Dauerbetrieb nicht nachgewiesen; Signale, Papier-Journal, Bestätigungsanfragen sind nicht Teil der Steuerung. |
| **V5 Menschliche Bestätigung** | Jeder Order-Pfad ist nur mit einem Freigabe-Token eines Menschen für genau eine Plan-ID vor Verfall auslösbar; ohne Token geschlossen; auditiert; mit Negativtests. | Ich finde keinen Order-Pfad (B14, B35), also ist „keine Order ohne Mensch“ trivial wahr. Das Dashboard hat einen einzigen POST-Handler, nur für Research-Abfragen (B36, B37); „Freigabestatus“ meint V2-Readiness (B38). Zwei Kill-Switches: einer ungenutzt, einer umgekehrt benannt (B39, B40, B41). | Token, Verfall, Audit und ein einziger Kill-Switch fehlen. |

### 2.1 Reibungen (F1 bis F7) und Auflösung

**F1: V3 gegen das Protokoll.** Erlaubt sind 60 Varianten, 48 sind verbraucht (B42, B2); Verworfenes wird nicht umparametriert (B43), der Holdout läuft einmal (B4). *Auflösung:* Selbstentwicklung heißt „vorschlagen, registrieren (Uzis Go), laufen lassen, berichten“, höchstens 12 weitere Varianten, danach neuer Holdout (B42). Preis: α je Variante sinkt von ≈ 0,00104 (m = 48) auf ≈ 0,00083 bei zwölf neuen Einträgen (B96, B146). Ob Zusatzvarianten unter „Raster“ (B44) fallen, ist offen (Frage 10).

**F2: V2 und V3 gegen die Verfassung.** Die KI darf nicht eigenständig Architektur ändern, Tests abschwächen oder Trading aktivieren (B45); Autonomie wird verdient (B46). *Auflösung:* A1 melden, A2 freigegebenen Patch anwenden (heute), A3 Patch für Unbekanntes vorschlagen, Mensch merged, A4 Auto-Merge fester Pfade nach Bewährung. Ohne Verfassungsänderung ist A3 die Grenze.

**F3: V4 und V5 gegen L0 bis L6.** L5 ist die Live-Order nach ausdrücklicher Freigabe, L6 die autonome Ausführung (B19); beide sind „PROHIBITED“ (B47). Da V5 jede Order freigibt, ist die Vision L5 (ABGELEITET: B19); „komplett autonom“ meint V2 bis V4, nicht L6. Für V2 bis V4 gibt es keine Achse; dafür dienen A1 bis A4. Gates: B48.

**F4: V5 gegen den Zeitbedarf.**
*Menge (ABGELEITET: B156).* Mechanische Short-Regeln erzeugten im Training 4,4 bis 89,9 Trades je Woche (0,6 bis 12,8 je Tag), auf 15m 19,9 bis 86,2 (2,8 bis 12,3 je Tag), auf 1h 5,1 bis 22,5 (0,7 bis 3,2 je Tag). Keine Orderflow-Setups; deren Menge ist UNVERIFIED (B7), Paket 3 zählt sie. Untere Schranke aus K3: 200 Holdout-Trades (B93) in rund 91 Wochen (B94), also mindestens 2,2 je Woche.
*Verfallsfrist.* Der Backtest füllt zur nächsten Eröffnung (B49). Ein Setup verfällt beim frühesten Ereignis: (a) der Preis weicht mehr als 0,06 % vom Testpreis ab (Stress-Slippage, B6; mein Vorschlag, Paket 3 misst den Zeitpunkt); (b) der Invalidierungspreis ist berührt; (c) die nächste Kerze schließt, weil dann ein neues Signal gerechnet wird (B49). Obergrenze: eine Kerze, 15 oder 60 Minuten.
*Urteil (ABGELEITET: B156 + Frist).* Auf 15m müsste Uzi 3 bis 12 Mal am Tag binnen 15 Minuten entscheiden, rund um die Uhr: für eine Einzelperson nicht tragbar. Auf 1h mit höchstens rund 3 Setups je Tag ist V5 machbar, wenn er binnen 60 Minuten erreichbar ist. Schritt 1 setzt deshalb 1h, 15m nur bei Ja auf Frage 5. Arbeitsbedarf (Minuten je Entscheidung sind Annahme):

| Setups je Woche | je Tag | 1 Min. | 5 Min. | 15 Min. |
|---|---|---|---|---|
| 2,2 (Untergrenze K3) | 0,3 | 2 | 11 | 33 |
| 13,2 (T1, 1h) | 1,9 | 13 | 66 | 198 |
| 22,5 (höchster Wert auf 1h) | 3,2 | 23 | 113 | 338 |
| 89,9 (höchster Wert überhaupt) | 12,8 | 90 | 450 | 1.349 |

Das Hindernis ist die Erreichbarkeit, nicht die Minuten. K5 läuft mit Uzi im Loop, sonst misst es einen anderen Bot.

**F5: V5 gegen „profitabel“.** K1 gilt für alle Signale; wählt Uzi aus, gilt der Beleg nicht mehr für das Gehandelte. *Auflösung:* Er darf zunächst nur ablehnen, mit Grund; das Setup läuft als Papier weiter, so zeigt sich der Wert seines Eingriffs.

**F6: Vision gegen Band 10, und nicht nur dagegen.** Band 10 sagt, Ziel sei nicht der Bau eines Trading-Bots (B51, B52). Die oberste Verfassung (B53, als Band 1 gelesen) sagt es ebenfalls (B54), verbietet der KI „Trading aktivieren“ (B45) und hat Vorrang (B55, B56); Vision 2030 schließt Orders aus (B57), die KI-Agenten-Verfassung Live-Trading ohne Freigabe (B58). Der Widerspruch ist real. *Gilt Uzis Vision,* anzupassen: `TIM_CONSTITUTION.md` Zeilen 13 und 94; `TIM_LONG_TERM_EVOLUTION_VISION_CONSTITUTION.md` Zeilen 30 bis 34 und 232; `docs/VISION_2030.md` Zeile 19; `AUTONOMY_LEVELS.md` L5, L6; `IMPLEMENTATION_ROADMAP.md` Phase 10 (B59). Verfahren: Begründung, Review, neue Version (B60), vor dem ersten Micro-Live-Trade (B61).

**F7: Getestet gegen gehandelt.** Der Backtest füllt zur nächsten Eröffnung (B49). Der `TradePlan` ist LIMIT_RETEST, sobald das Szenario eine Einstiegszone hat (B158, B100), und die Pipeline reicht kein Einstiegsmodell durch (B159). Sonst maße K5 einen anderen Trade als K1. *Auflösung (Annahme, Frage 13):* ein Strategie-Objekt für Test, Papier und Micro-Live. Es nimmt aus der Pipeline Szenario, Bestätigung, Stop und Risikoentscheid (die Risk Engine läuft dort, B157, und gehört zum getesteten Pfad), steigt zur nächsten Eröffnung ein und setzt das Ziel auf 1,5 R vom tatsächlichen Einstieg (B125). Limit-Retest und Teilgewinne des Plans werden weder getestet noch gehandelt; wer sie will, braucht eine eigene Variante mit Limit-Füllmodell (dem Motor fehlt es, B49) und verbraucht Slots. Ein Paritätstest (Schritt 4) belegt gleiche Signale in Replay und Papier-Feed. Kontostandabhängige Risk-Vetos fehlen im Backtest (B157) und zählen im Papier-Betrieb getrennt.

### 2.2 K1 und K5 gegen K2 bis K4, und der Maßstab

Das Protokoll verlangt alle fünf (B62) und Papier-Betrieb nur nach bestandenem Holdout (B63). K1 und K5 allein sind Wegmarken:

| Fall | Bedeutung | Folge |
|---|---|---|
| K1, K5 ja; K2 nein | Gewinn nicht von Zufalls-Einstiegen zu trennen; bei m = 48 verlangt das Protokoll p < 0,0010 (B64) | nicht profitabel (B62); Papier weiter, kein Geld |
| K1, K5 ja; K3 nein | KEIN URTEIL (B65): der Erwartungswert ruht auf zu wenigen Trades. Nach B63 käme das Setup gar nicht in den Papier-Betrieb; läuft es auf Uzis Wunsch trotzdem, ist ein positives K5 nur eine weitere kleine Stichprobe | nicht profitabel, nicht negativ; Papier verlängern, kein Geld |
| K1 ja; K5 nur „kein Widerspruch“ (unter 20 Papier-Trades) | formal erfüllt, aber keine Bestätigung (B66) | „profitabel mit schwacher Papier-Evidenz“ (B66); Papier auf Wunsch verlängern |
| K1, K5 ja; K4 nein | Drawdown über 20 % bei 1 % Risiko je Trade (B67) | nicht profitabel (B62); ein lockereres K4 ist nach R4 nicht erlaubt (B44) |

Ich messe TIM an K1 bis K5 und halte sie für richtig streng. K1 „größer 0“ ist allein schwach: Der Kostenstress verschiebt den Erwartungswert um 0,015 bis 0,61 R (B68); eine Mindestgröße wäre nach B44 zulässig. K2 und K3 machen Mid und Long fast unprüfbar (Zeile 4), gewollt (B69). K5 „kein Widerspruch“ ist schwach (B66).

### 2.3 Dokument gegen Code (Code gilt)

`CURRENT_STATE_ASSESSMENT` nennt Backtest und Risk-Engine „MISSING“ (B70); beide existieren (B71), unverdrahtet (B9). `DATA_READINESS_MATRIX` nennt Funding „MISSING“ (B73); das Lab lädt es historisch (B74).

## 3. Lückenliste

Zeilen 6, 7, 8, 11, 12 und 17 betreffen den Betrieb wie getestet. Aufwand: S ≤ 2 Tage, M 3 bis 10, L > 10 Tage Agent plus Review (grobe Klassen, B134); Engpass sind Uzis Entscheidungen.

| # | Teil | Bereich | Ist-Zustand | Warum es Profit verhindert oder gefährdet | Schwere | Status | Aufwand, Abhängigkeit |
|---|---|---|---|---|---|---|---|
| 1 | Profitabilität | Edge/Strategie | 0 von 48 Varianten über die Validierung (B2, B3). T1 bis T3 vor Gebühr und Slippage negativ (B5). Kaufen und Halten: +252,7 % und +465,7 % (B78) (Vergleichsgröße, keine Empfehlung). | Ohne Vorteil gibt es nichts zu automatisieren. Gilt für diese 48. | BLOCKIEREND | BELEGT | Ziel der Zeile 2 |
| 2 | V1 | Edge/Strategie | R4 testete nur `src/analysis`-Regeln (B79), nichts aus `orderflow_scenario` (B7). Replay und Journal haben keinen Aufrufer (B25). `ConfirmationUpdate` wird nur in Tests gebaut (B8), die CLI übergibt keines (B15), ohne Update immer NO_TRADE (B16). Drei Prädikat-Funktionen erwarten fertige Wahrheitswerte (B80, B81). | Uzis Methode ist als Regel nicht testbar; die Struktur-Kette ist ungetestet. Der Delta-Baustein allein, in R4 als S1 (Delta/CVD-Divergenz, 5m und 15m), fiel in allen 4 Varianten im Training durch: Erwartungswert −0,68 bis −0,33 R bei 3.223 bis 14.070 Trades, vor Gebühr und Slippage −0,21 bis −0,06 R (B147). Das ist negative Vorab-Evidenz für die Kline-Delta-Form. Ohne berechnete Bestätigung entsteht nie ein Plan. | BLOCKIEREND | BELEGT | M bis L, ab Uzis Definitionen (Frage 3); Zeilen 3, 4, 7 |
| 3 | V1 | Daten | Ohne `trades` sinkt die Konfidenz auf 0,39, die Pipeline bleibt NO_TRADE (B16, B85). Das Lab hat nur Kline-Delta (B86, B87), vom Protokoll als Näherung für Short freigegeben (B140); als Divergenz-Signal ist sie in R4 negativ (B147). OI, Liquidationen, Orderbook fehlen in Matrix und Repo-Code (B88, B73, B89, B74). Auf dem alten Server schreibt ein Feed `venue_trades`, nicht im Repo (B160); Instrument, Tiefe und Startdatum UNVERIFIED. OpenMarket-Seitensemantik UNPROVEN (B90). Der Broncx-Feed wirkt nur 24 Stunden und bestätigt nie (B91). | Ein Test auf Klines braucht einen ausdrücklichen, zu registrierenden Kline-Modus. Echter Footprint-Orderflow braucht aggTrades-Historie; das Protokoll lädt sie nur als Stichprobe (B141); ob die Archive sie in nötiger Tiefe liefern, ist UNVERIFIED (klärt Schritt 2). Ein Server-Feed reicht nur bis zu seinem Start zurück, das Training liegt in 2020 bis 2022 (B118): er ersetzt das Archiv nicht (ABGELEITET). | WICHTIG | BELEGT für Repo und Matrix; UNVERIFIED für den Server-Feed (klärt auf dem Server `\d venue_trades` und min/max der Zeitspalte) | S bis M; Zeile 2 |
| 4 | Profitabilität | Validierung/Statistik | K3: Short ≥ 200, Mid ≥ 30 (B93). Donchian liefert 13 Trades im Jahr (B50), im Holdout von rund 21 Monaten (B94) ≈ 23, also unter 30: KEIN URTEIL (B65); das Protokoll erwartet das für M1 und M2 selbst (B95). Bei sd ≈ 1,3 R (B68) braucht +0,2 R rund 649 Trades (261 ohne Korrektur); 30 Trades erkennen nur ≈ 0,93 R, 200 Trades ≈ 0,36 R (B96) (Normalnäherung). | Zertifizierbar sind nur Regeln mit vielen Trades. | WICHTIG | ABGELEITET: B50 + B93 ⇒ unter K3; B68 + B96 ⇒ Trades-Bedarf | Entwurfsregel für Zeile 2; keine Protokolländerung |
| 5 | Profitabilität | Kosten und Ausführung | Kosten je Trade 0,136 bis 0,61 R bei Short, 0,015 bis 0,085 R bei Mid und Long (B68); T1 bis T3 auf 15m 0,33 bis 0,52 R, auf 1h 0,18 bis 0,31 R (B151). Gebühren pauschal als Taker (B97); Paper-Parameter fest (B98). | Enge Stops machen Kosten in R groß; für Short-Regeln ist das faktisch ausschließend. | WICHTIG | ABGELEITET: B68 ⇒ Kosten in R je Trade | M; 1h kostet weniger als 15m (B151), Stop-Abstand als Entwurfsgröße |
| 6 | Profitabilität | Kosten und Ausführung | Journal nur im Speicher (B18); `PaperAutomation` und Demo-Trader bewerten nur abgeschlossene Research-Cases rückblickend (B82, B83); Shadow-Engine nur Spezifikation (B84). | K5 ist ohne persistenten Papier-Betrieb nicht erreichbar, für jede Strategie. | BLOCKIEREND | BELEGT | M bis L; nach Kandidat |
| 7 | V1 | Edge/Strategie | `TradePlan` ist kein vollständiger Strategievertrag: Haltedauer offen, Teilgewinne (B22), Strategievertrag „MISSING“ (B99). Der Backtest steigt zur nächsten Eröffnung ein (B49), der Plan ist LIMIT_RETEST (B100, B158), die Pipeline reicht kein Einstiegsmodell durch (B159). | Test und Plan beschrieben sonst verschiedene Trades; F7 legt einen Vertrag fest. | WICHTIG | BELEGT | S; Teil von Paket 2 |
| 8 | Profitabilität | Daten | Live-Quelle Spot (B101), getestetes Instrument USD-M (B87). | K5 prüfte sonst anderes Instrument und andere Delta-Definition. | WICHTIG | ABGELEITET: B101 + B87 ⇒ Instrumente verschieden; ob REST-Klines das Taker-Volumen liefern, UNVERIFIED (eine Kerze von `/fapi/v1/klines` abrufen) | S; K5-Feed aus derselben Kline-Quelle wie der Backtest |
| 9 | Profitabilität | Betrieb und Infrastruktur | Coverage im eingefrorenen Fenster 60,659 % (B33); V2-B01 bis V2-B08 offen (B102). | Aggregat-Trade-Signale und 24/7-Papier brauchen stabile Daten; Kline-Signale ab 1h kaum. | WICHTIG | BELEGT | M; Uzi-Betrieb |
| 10 | Profitabilität | Betrieb und Infrastruktur | Ein Server existiert (tim-core-01), die alte Runtime schreibt dort seit 30.09. keine Kerzen (B34); die Neuinstallation wartet auf Uzis Go (B103), ihr Lauf steht aus (B20). Das Protokoll regelt Ausfälle im Papier-Betrieb nicht (B135). | K5 ist 4 bis 8 Wochen durchgehender Betrieb (B66). Ein Host, der Daten verliert, verzögert K5 oder verfälscht es (ABGELEITET: B34 + B66). Gilt für K5, nicht für K1. Das Fehlen eines persistenten Journals blockiert unabhängig davon (Zeile 6). | WICHTIG | UNVERIFIED für den heutigen Zustand; klärt `python3 scripts/tim_server_health.py` auf dem Server, Exit 0 = kein ROT (B104) | M; Uzi mit Remote-Session; Paket 5 |
| 11 | V5 | Governance und Prozess | Kein Freigabe-Mechanismus (B37, B38); `governance.py` ungenutzt (B39); Pipeline-Flag umgekehrt benannt (B40, B41). | Vor Micro-Live zwingend: ohne Token kein Mensch im Loop; zwei Schalter erzeugen falsche Sicherheit. | WICHTIG | BELEGT | M; Zeile 6 |
| 12 | V5 | Mensch (Zeit, Wissen, Entscheidungen) | Latenz und Auswahleffekt ungemessen; Setup-Frequenz der Methode unbekannt (B156, B7). | Späterer Einstieg und Auswahl entwerten K1. | WICHTIG | ABGELEITET: B49 + B156 ⇒ Einstieg wird später als getestet | S; Verfallsregel F4, Veto-Protokoll |
| 13 | Profitabilität | Mensch (Zeit, Wissen, Entscheidungen) | Broncx' Sicht ist im System ausdrücklich nur externe Meinung (B105). Uzis Regeln für Kontext und Ort stehen nicht als Regel im Repo: Die Pipeline leitet Marktzustand aus Kerzen ab und setzt als Ort nur Spanne und die letzten sechs Kerzen (B131, B132); Vortages- und Wochenmarken fehlen. | Ermessen, das sich nicht in Regeln fassen lässt, ist nicht prüfbar. Ob das Uzis „Ort“ ist, ist offen (Frage 3). | WICHTIG | ABGELEITET: B132 | S bis M; Interview mit Uzi |
| 14 | Profitabilität | Validierung/Statistik | T1 bis T3 entstanden 2026, also im Holdout-Zeitraum (B106); der Holdout läuft einmal (B4). | Ein Bestehen dort wäre schwächer belegt; frische Evidenz liefert nur der Papier-Betrieb. | WICHTIG | BELEGT | Prozess |
| 15 | Profitabilität | Governance und Prozess | Dokumente widersprechen Vision und Code (B54, B51, B57, B70). | Wer nach Dokumenten baut, baut Falsches oder blockiert sich. | WICHTIG | BELEGT | S; Freigabe Uzi |
| 16 | V5 | Kosten und Ausführung | Kein Börsen-Adapter, keine Order-Schlüssel (B14); `Mode.LIVE` fehlt absichtlich (B35); Gate L4→L5 (B48); Schlüssel nur ohne Auszahlungsrecht (B107). | Micro-Live unmöglich, bis es gebaut ist. | SPÄTER | BELEGT | L; nach Schritt 9 |
| 17 | Profitabilität | Risiko und Kapital | Drei Risikoverträge (B75, B76, B67). | Vor Micro-Live braucht es einen einzigen. | SPÄTER | BELEGT | S |
| 18 | V2 | Betrieb und Infrastruktur | Reparatur = freigegebener Patch (B29, B28); Umfang des Bugfixer-Executors nur abgeleitete Diagnose-Artefakte (B108). | Betriebsausfälle mit unbekannter Ursache bleiben liegen. | SPÄTER | BELEGT | L |
| 19 | V3 | Governance und Prozess | Kein Vorschlagsmodul (B12); Budget 12 (B42, B2); Verfassung (B45). | Ungebremste Selbstentwicklung entwertet die Mehrfachtest-Korrektur. | SPÄTER | BELEGT | L; nach erstem Kandidaten |
| 20 | V4 | Betrieb und Infrastruktur | Orchestrator nur für Datenlücken (B13). | Kein Betrieb der Handelskette. | SPÄTER | BELEGT | L |
| 21 | Profitabilität | Governance und Prozess | Das Register-Werkzeug schreibt Status nur bei einem Volllauf (B128). Ein Volllauf scheitert an den 48 alten, schon endgültigen Einträgen (B129). Die Obergrenze 60 greift im Code (B130); die Registerdatei ist hash-verkettet (B137); der Holdout-Schutz verlangt Status „candidate“ (B136). Ein Test fixiert genau 48 Varianten (B138, B145). `run` und `ensure_registered` nehmen schon eine Variantenliste an (B142, B143). | Eine neue Hypothese kommt mit dem heutigen Skript nicht protokollkonform bis zum Holdout. Das betrifft den gewählten Weg, nicht den Vorteil selbst. | WICHTIG | BELEGT (B129 selbst ausgeführt) | S; Paket 4. Lösung ohne Änderung von Test und Wächter |

## 4. Was nicht fehlt

- **Statistik-Wächter, Protokoll, kausale Engine.** Wächter-Test 7 passed (B109); 0 von 200 Zufallsreihen bestanden, 190 von 200 mit +0,2 R (B110); die Engine zeigt der Strategie nie die Zukunft (B49). Es fehlt nur ein Schreibpfad (Zeile 21).
- **Plan-, Risk-, Paper-Bausteine und Statistik.** 22 Tests grün (B24).
- **ALFRED-Makro-Schicht.** 3.042 von 5.252 Zeilen des Labs (B77), von Hypothesen und Runner nicht importiert (B111); „Engpass ist Edge“ (B112). Einfrieren.
- **Governance- und Readiness-Maschinerie** (B102), Dashboard, `tim_manager`, `task_governance` (8.486 Zeilen, B113): führen nicht zu K1; keine neue Arbeit, der Bestand bleibt. Ausnahme V5: Schritt 8 baut einen Bestätigungs-Stub in `src/paper/`; den POST-Handler des Dashboards (B37) erweitert erst Schritt 12.
- **Weitere Datensammler** (Funding, OI, Orderbook): M2 (Funding) scheiterte mit Archivdaten (B3). **Muster-Hypothesen:** T1 bis T3 nicht umparametrieren (B43). **Live-Adapter, Kapitalleiter, Selbstentwicklung:** warten auf einen Vorteil.

## 5. Kritischer Pfad

**Teil A: erstes Setup mit K1 und K5.**

1. **Entscheidungen und Spezifikation (Uzi, Dokument).** Fragen klären; Hypothese „Orderflow“ mit höchstens 4 Varianten: Intervall 1h (F4), 15m nur bei Ja auf Frage 5 (B87, B115; kein 4h) × Breakout-Acceptance oder Sweep-Reversal (B114, B80). Klasse Short (B148; Mid wäre Tageskerzen, B149), weil K3 dort 200 Holdout-Trades verlangt (B93). Rejection entfällt: zu nah an T2 (B2, B43). Orderflow als Kline-Delta (B140). S1, die Delta-Divergenz, fiel in 4 von 4 Varianten durch (B147); die Hypothese ist nur sinnvoll, wenn Ort und Struktur auslösen und Delta bloß bestätigt, sonst ist sie S1 in neuem Gewand (B43). Kosten: 2 bis 4 der letzten 12 Slots (B42). Stop, Ziel, Zeit-Stopp vorab fest. *Abnahme:* freigegebenes Dokument, Regeln ohne Ermessen. *Abbruch:* nur mit Ermessen schreibbar → Abschnitt 7.
2. **Datengate aggTrades (ein lesender Netzaufruf, Datenweg O2, B152; parallel zu 3 und 4).** Befehl: `curl -sI https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2024-01-01.zip | head -1`, Pfadform UNVERIFIED, je einmal für den frühesten und den letzten Tag. Klärt, ob aggTrades in nötiger Tiefe vorliegen (Zeile 3). *Abnahme:* ja/nein mit Zeitraum im Dokument aus Schritt 1. *Abbruch:* nein → Footprint nur mit selbst gesammelten Daten (Abschnitt 7).
3. **Daten laden, dann Signalzählung, Überlappung, Verfallsprofil, nur Training.** Zuerst `scripts/research_lab_fetch.py --preset r4` (Paket 3). Short verlangt ≥ 500 Trades im Training (B116), von 2020-01 (B117) bis 2022-12-31 (B118), also ≥ 3,2 Signale je Woche, und ≥ 200 im Holdout (B93), also ≥ 2,2. Zu zählen: Überlappung der OF-Signale mit T1 bis T3 und S1 in Kerze und Richtung, Fristanteile und Uhrzeitverteilung (F4). *Abnahme:* diese Zahlen je Variante, keine R-Werte. *Abbruch:* alle Varianten unter K3 (nicht zertifizierbar); Überlappung über 50 % (Vorschlag ohne Datengrundlage) gilt als Umparametrierung (B43); erreicht weniger als die Hälfte der Signale Uzi binnen der Frist, misst K5 einen anderen Bot.
4. **Replay-Adapter, Bestätigungsregeln und Strategie-Objekt nach F7 bauen.** Kontext und Ort aus den Standardableitungen (B131, B132), Fenster vorab fest, nicht getunt. *Abnahme:* Kausalitätstest (Ergebnis bei t bleibt mit angehängten Zukunftskerzen), Determinismus-Hash und Paritätstest (Replay und schrittweiser Papier-Feed liefern für einen Trainingsmonat dieselben Signale) grün. *Abbruch:* Bestätigung nicht ohne Ermessen berechenbar.
5. **Erweiterungspfad, Änderungsprotokoll, Registrierung (Paket 4).** Registrierung nur über `HypothesisRegister.register` (B137). *Abnahme:* Kette gültig, m ≤ 60 (B130), die 48 alten Einträge, alter Test (B145) und Wächter (B128) unverändert grün. *Abbruch:* m würde 60 überschreiten.
6. **R4/R5-Lauf der OF-Varianten, nur Training und Validierung.** *Abnahme:* mindestens ein Kandidat nach PROTOKOLL §8 Schritt 1 und 2. *Abbruch:* kein Kandidat → Abschnitt 7, nicht umparametrieren (B43).
7. **Kandidatenliste einfrieren, Uzis Go, Holdout genau einmal (R6).** *Abnahme:* Urteil K1 bis K4. *Abbruch:* NICHT BESTANDEN ist endgültig (B119).
8. **Papier-Technik und Dauer-Host (parallel ab Schritt 4; hängt von Paket 5 ab).** Persistentes Journal; Feed aus der Kline-Quelle des Backtests mit REST-Nachholen, der dasselbe Strategie-Objekt ruft (F7); Freigabe-Stub mit Verfall (neu `src/paper/approval.py`, Name ist Vorschlag); Veto-Protokoll. Ausfälle regelt das Protokoll nicht (B135); Vorschlag: Verpasstes getrennt nachrechnen, Uzi entscheidet über Neustart von K5. *Abnahme:* 7 Tage auf dem Dauer-Host ohne Integritätsfehler. *Abbruch:* kein Dauer-Host, kein K5.
9. **Papier-Betrieb R7, 4 bis 8 Wochen, Uzi im Loop, nur BESTANDEN-Kandidaten** (B63). *Abnahme:* „bestätigt“ oder „kein Widerspruch“ (B66). *Abbruch:* Papier-Stopp (B120).

*Zeit.* Belegt ist nur die Untergrenze nach dem Holdout: 30 bis 60 Tage Papier-Stabilität (B48) und 4 bis 8 Wochen K5 (B66). Für Schritte 1 bis 7 nenne ich keine Dauer (Code in Tagen machbar, B134; Uzis Antworten offen). Danach bleiben mindestens 8 Varianten (B42, B2).

**Teil B: erster von Uzi bestätigter Micro-Live-Trade. Wartet auf einen BESTANDEN-Kandidaten.**

10. **Bauplan Micro-Live und Verfassungsänderung freigeben** (B61, B60). *Abnahme:* beide freigegeben. *Abbruch:* Uzi lehnt ab → Abschnitt 7.
11. **Shadow, erst nach 30 bis 60 Tagen stabilem Papier-Betrieb** (B48); Umfang als Vorschlag: 20 beabsichtigte Orders (Zahl aus B66). *Abnahme:* gemessene Kosten höchstens im Kostenmodell (B6). *Abbruch:* Kosten über dem Stress-Ansatz (B6).
12. **Börsen-Adapter L5** mit isolierten Zugangsdaten ohne Auszahlungsrecht (B107), Freigabe-Token je Plan-ID mit Verfall (Weg nach Frage 12, etwa der POST-Handler des Dashboards, B37), ein Kill-Switch; die Strategie importiert den Adapter nicht (B121). *Abnahme:* Negativtests grün, unabhängiger Review (B48). *Abbruch:* ein Pfad sendet ohne Token.
13. **Erster Trade:** Uzi bestätigt ein Setup vor Verfall. Kapital setzt Uzi; Konvention ist niedriger Hebel (B122). *Abnahme:* Order-Journal und Börsenbeleg stimmen überein. *Abbruch:* Abweichung über Stress-Ansatz.

**Teil C: V2 bis V4. Beginnt erst nach einem Kandidaten aus Schritt 6.**

14. **V2 auf Stufe A3:** Patch-Vorschlag für Unbekanntes in der Sandbox. *Abnahme (Zahl ohne Datengrundlage, Frage 11):* 3 von 5 verdeckten Defekten richtig, kein abgeschwächter Test. *Abbruch:* ein Pfadverstoß → A2 bleibt.
15. **V4: 14 Tage ohne Eingriff, Coverage ≥ 99,5 %,** gemessen mit `tim_server_campaign evaluate` (B123). *Abnahme:* null Eingriffe. *Abbruch:* Eingriff nötig → Defekt.
16. **V3: ein Kreislauf** Vorschlag → Registrierung (Go) → Lauf → Bericht ohne Codeänderung am Lab. *Abnahme:* Kette lückenlos. *Abbruch:* Vorschlag umgeht das Register.

**Parallel:** Schritte 1 bis 4 mit Paket 5; Schritt 2 neben 3 und 4; Schritt 8 mit 4 bis 7; ohne Paket 5 kein Schritt 9. **Wartet auf einen belegten Vorteil:** Schritte 10 bis 13 (Adapter-Bau ab BESTANDEN, Schaltung nach Audit), Teil C.

## 6. Die nächsten 30 Tage

Alle Pakete erst nach Uzis Go (B124). Paket 1 zuerst; Paket 5 unabhängig; Pakete 2 bis 4 folgen nacheinander.

**Paket 1: Vision, Hypothese, Verfallsregel festschreiben (Uzi entscheidet, Agent schreibt).** *Ziel:* Tabelle aus Abschnitt 2 als `docs/autonomous_trader/VISION_STRUKTURIERT.md`; Hypothese als `docs/research_lab/HYPOTHESE_OF.md` (≤ 4 Zeilen `| OF-…`, Klasse Short, festes Fenster für Kontext und Ort, Verfallsregel F4, Hinweis auf S1, B147); Verfassungsänderung als Entwurf `docs/autonomous_trader/AENDERUNGSENTWURF_TRADING.md`. *Prüfbefehl:* `test "$(grep -c '^| OF-' docs/research_lab/HYPOTHESE_OF.md)" -le 4 && echo OK`; `git status --short` zeigt drei neue Dateien. *Ergebnis:* Dokumente.

**Paket 2: Strategie für die Orderflow-Methode (nach Paket 1).** *Ziel:* eine Strategie im Format von `src/research_lab/backtest/engine.py`, die je Kerze die Pipeline mit Kline-Delta ruft (B133: 1,7 ms je Lauf bei 36 Kerzen), Kontext und Ort aus den Standardableitungen (B131, B132) nimmt und Bestätigungen nach den drei Prädikaten berechnet (B80); es liefert ein `Signal` mit Plan-Stop, Ziel 1,5 R vom tatsächlichen Einstieg (B125) und Zeit-Stopp liefert; Einstieg zur nächsten Eröffnung (B49). Dieses Objekt dient Test, Papier und Micro-Live (F7) und übernimmt den Limit-Retest des Plans (B100) nicht; Qualitäts-Gate mit Kline-Modus, Standard unverändert (B85). *Dateien:* neu `src/research_lab/hypotheses/orderflow_scenario.py`, `src/orderflow_scenario/engines/confirmation_rules.py`, `tests/test_research_lab_orderflow_scenario.py`; geändert `src/orderflow_scenario/engines/data_quality.py` (nur Flag). *Prüfbefehl:* Pytest in der Form von B24 auf `tests/test_research_lab_orderflow_scenario.py tests/test_orderflow_scenario_data_quality.py tests/test_orderflow_pipeline_trade_plan.py`. *Ergebnis:* grün, mit Kausalitäts-, Determinismus-, Paritäts- und NO_TRADE-Standardtest (B16).

**Paket 3: Daten laden und Zählung auf Training (nach Paket 2; Netz zu `data.binance.vision`, Datenweg O2, B152).** *Ziel:* `data/` fehlt hier (B1). `scripts/research_lab_fetch.py --preset r4` lädt alle Archive der 48 Varianten bis 2024-12 (USD-M-Klines 1h, 15m, 5m, Funding), prüft Checksummen und verweigert 2025 und später (B153, B154); Speicher und Dauer UNVERIFIED. Danach ein Skript, das nur Monate vor 2023-01 lädt und je Variante Signale pro Jahr, Überlappung mit T1 bis T3 und S1, Fristanteile (F4) und Verteilung nach UTC-Stunde ausgibt, nie R-Werte. *Dateien:* neu `scripts/research_lab_count_signals.py`, `tests/test_research_lab_count_signals.py` (Validierung und Holdout werden verweigert). *Prüfbefehl:* `python3 scripts/research_lab_fetch.py --preset r4 > /tmp/fetch.log; echo "exit=$?"; tail -1 /tmp/fetch.log` gibt `exit=0` und `dataset hash:`; dann `python3 scripts/research_lab_count_signals.py --split train`. *Ergebnis:* Tabelle der erwarteten Holdout-Trades, Überlappung, Uhrzeitverteilung.

**Paket 4: Erweiterungspfad und Lauf (nach Paket 3 und Uzis Go).** *Ziel:* (a) `src/research_lab/hypotheses/extension.py` mit `EXTENSION_VARIANTS`; `VARIANTS` bleibt bei 48. (b) Skript `scripts/research_lab_run_extension.py`: verweigert den Holdout (B30), registriert mit `--commit-register` über `ensure_registered(register, EXTENSION_VARIANTS)` (B142), rechnet mit `run(..., specs=EXTENSION_VARIANTS)` (B143); altes Skript, Wächter (B128) und Test (B145) bleiben unverändert. (c) Nach Go: Änderungsprotokoll-Zeile (B144), dann Lauf. *Dateien:* neu `tests/test_research_lab_extension.py` (Registerkopie im Temp-Verzeichnis: alte 48 unverändert, 61. Eintrag abgelehnt, B130). *Prüfbefehl:* Pytest in der Form von B24 auf `tests/test_research_lab_hypotheses.py tests/test_research_lab_extension.py tests/test_research_lab_stats.py` (Ausgangslage 52 passed, B139); `git diff --stat docs/research_lab/REGISTER.jsonl` ist vor dem Go leer; danach höchstens 60 Registrierungen (Zählbefehl B2) und der neueste Bericht enthält „Holdout nicht geladen“ (B126). *Ergebnis:* Kandidatenliste oder „kein Vorteil gefunden“ (B3).

**Paket 5: Server-Betrieb und Messfenster (Uzi mit Remote-Session; parallel, Voraussetzung für K5, nicht für K1).** *Dateien:* `docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md`. *Ziel:* Die alte Runtime läuft ohne Kerzen (B34); Migration M0 bis M5 (B127, B103), danach `declare` eines 14-Tage-Fensters (B123). *Prüfbefehl, beide auf dem Server (der Checkout sagt nichts über den Server, B21):* `python3 scripts/tim_server_health.py; echo $?` gibt 0 (B104); `ls docs/autonomous_trader/campaigns` listet die Fensterdatei (B123). *Ergebnis:* stabile Umgebung, Coverage nach 14 Tagen.

## 7. Wann aufhören

Der Test prüft die Struktur-Kette mit Kline-Delta, nicht Footprint; S1 allein ist negativ (B147). Was ein Ergebnis aussagt:

| Ergebnis | Aussage | Nächster Schritt |
|---|---|---|
| Kandidat besteht Schritt 6 | Diese Kline-Regel hat im Training und in der Validierung einen Vorteil | Holdout (Schritt 7) |
| Kein Kandidat | Diese 4 Regeln haben keinen Vorteil; zusammen mit S1 (B147) hat die Kline-Delta-Form insgesamt keinen gezeigt. Die Kette mit Einzeltrade-Footprint bleibt ungetestet, die Vorab-Lage dafür ist aber nicht besser als bei Kline-Delta | Uzi wählt: (a) aggTrades-Test mit den mindestens 8 Rest-Slots, falls das Datengate (Schritt 2) „ja“ ergab und ein Argument benennt, was der Footprint ergänzt (Protokolländerung der Datenliste B141 nötig); (b) neuer, später liegender Holdout nach B42, Preis: Wartezeit auf frische Daten, und jede Variante muss neu bestehen; (c) die Alternative unten |
| Auch der aggTrades-Test negativ, oder nicht durchführbar | V1 trägt in dieser Form nicht | Alternative unten |

Weitere Abbruchgründe:
- **Alle Varianten unter K3.** Zu selektiv für dieses Protokoll: späterer Holdout oder Deklaration als Mid mit schwacher Evidenz. Ebenso bei **Holdout NICHT BESTANDEN oder Papier-Stopp** (B119, B120): endgültig für die Variante und ihre Ableger.
- **Nicht ohne Ermessen kodierbar** (Zeile 13): ein Bot wäre ein anderes Produkt.
- **Bestätigungen verfallen überwiegend** (mehr als die Hälfte) oder abgelehnte Setups schneiden über mindestens 20 Fälle besser ab als bestätigte: Der Mensch im Loop hilft nicht (Frage 11).

*Ehrliche Alternative:* TIM bleibt, was Band 10 beschreibt (B51): Strukturanalyse, Setup-Tagebuch und Auswertung von Uzis Entscheidungen nach demselben Protokoll, ohne Ausführung.

## 8. Annahmen und offene Fragen an Uzi

**Annahmen.** (1) Zusatzvarianten bis m = 60 sind nach B42 vorgesehen; ob B44 sie als „Raster“ erfasst, ist offen (Frage 10). (2) Der Holdout umfasst rund 21 Monate, wenn R6 im Oktober 2026 liefe (B94). (3) Keine neuen Intervalle: 1h Standard, 15m optional (Frage 5), beide im Protokoll geladen (B87) und von T1 bis T3 genutzt (B115); 4h berührte Datenraster und Split (B44). (4) Serverzustand wie am 2026-10-01 (B34). (5) Die oberste Verfassung ist Band 1. (6) Die Grenze 0,06 % ist die Stress-Slippage (B6), mein Vorschlag. (7) Test, Papier und Micro-Live nutzen ein Strategie-Objekt (F7).

**UNVERIFIED und was es klärt.** Serverzustand: `python3 scripts/tim_server_health.py` auf dem Server. Lokale Rohdaten: `ls data/research_lab`. aggTrades-, OI-Archive, Taker-Volumen der REST-Klines: je ein Abruf bei Binance (Schritt 2). Server-Feed `venue_trades`: `\d venue_trades` und min/max der Zeitspalte. Setup-Frequenz: Paket 3.

**Fragen.** 1. Wird Trading offiziell Anwendungsfall von TIM, mit Verfassungsänderung (F6)? 2. Gilt die Kline-Delta-Form als erster Test der Vision, obwohl S1 schon durchfiel (B147), oder besteht Uzi auf aggTrades? 3. Wer legt die Bestätigungsprädikate fest, Uzi oder Broncx (B80, B105)? Genügen als „Ort“ die Pipeline-Standardwerte (B132), oder braucht er Vortages- und Wochenmarken? 4. Ist 1h als Horizont akzeptabel? 5. Wie viele Minuten braucht Uzi je Entscheidung, und ist er auch nachts binnen 60 Minuten erreichbar (für 15m: binnen 15)? 6. Liegen die Binance-Archive lokal vor, und wie ist der Server heute? 7. Darf der Holdout über den Guard geladen werden, sobald ein Kandidat feststeht? 8. Höchstverlust im Micro-Live? 9. Darf TIM Patches fester Pfade selbst mergen (A4)? 10. Fallen bis zu 12 Zusatzvarianten unter die Obergrenze 60 (B42) oder unter „Raster“ (B44), mit Eintrag und Preis aus F1? 11. Gelten meine Schwellen ohne Datengrundlage (0,06 %, 50 % Überlappung, 50 % Verfall, 20 Fälle, 20 Shadow-Orders, 3 von 5 Defekten) oder setzt Uzi eigene? 12. Wie bestätigt Uzi ein Setup: CLI, Dashboard (B37) oder anders? 13. Genügt der Markt-Einstieg zur nächsten Eröffnung (F7), oder will Uzi den Limit-Retest des Plans als eigene Variante?

## 9. Belegprotokoll

Befehle im Repo-Wurzelverzeichnis `/home/user/tim-ai-platform` ausführen. Python-Aufrufe nutzen die in der Aufgabe vorgegebene Umgebung. Gelesen heißt: die Stelle selbst geöffnet; ausgeführt heißt: der Befehl lief hier mit der angegebenen Ausgabe.

**B1** · Befehl
```
ls data; echo "exit=$?"
```
Ausgabe:
```
ls: cannot access 'data': No such file or directory
exit=2
```

**B2** · Befehl
```
python3 -c "import json,collections;r=[json.loads(l) for l in open('docs/research_lab/REGISTER.jsonl')];print(collections.Counter(x['status'] for x in r if x['kind']=='status'),sum(x['kind']=='register' for x in r))"
```
Ausgabe:
```
Counter({'failed_train': 42, 'failed_validation': 6}) 48
```

**B3** · Datei `docs/research_lab/reports/r4_2026-09-29T2219Z.md:5`
> **Kandidaten für den Holdout:** keine – kein Vorteil in Training/Validierung gefunden  

**B4** · Datei `docs/research_lab/PROTOKOLL.md:100-101`
> eröffnet wurden. Holdout-Daten werden vor R6 nicht geladen, nicht geplottet und  
> nicht zusammengefasst. Der Loader verweigert sie ohne Holdout-Freigabe.  

**B5** · Befehl (Ergebnis = Erwartungswert ohne Gebühr und Slippage: 2 × Basis − Stress; Stress verdoppelt nur Gebühr und Slippage, das Funding bleibt, B6 und B150)
```
python3 -c "import json;d=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants'];f=lambda k,p,s:round(2*d[k][p]['summary']['expectancy_r']-d[k][s]['expectancy_r'],3);print([(k,f(k,'train','stress_train'),f(k,'validation','stress_validation')) for k in d if k[0]=='T'])"
```
Ausgabe:
```
[('T1-bos-15m', -0.091, -0.134), ('T2-rejection-15m', -0.126, -0.232), ('T3-failedcont-15m', -0.204, -0.321), ('T1-bos-1h', -0.066, -0.003), ('T2-rejection-1h', -0.063, -0.074), ('T3-failedcont-1h', -0.109, -0.155)]
```

**B6** · Datei `docs/research_lab/PROTOKOLL.md:148-149`
> | Gebühr | 0,05 % je Seite (Taker, USD-M Standardstufe) | 0,10 % je Seite |  
> | Slippage | 0,03 % je Seite, Stop-Ausführungen 0,05 % | verdoppelt |  

**B7** · Befehl
```
grep -rn "orderflow_scenario" src/research_lab main.py; echo "exit=$?"
```
Ausgabe:
```
exit=1
```

**B8** · Befehl
```
grep -rn "ConfirmationUpdate(" src scripts main.py; echo "exit=$?"; grep -rln "ConfirmationUpdate(" tests
```
Ausgabe:
```
exit=1
tests/test_orderflow_pipeline_trade_plan.py
```

**B9** · Befehl
```
grep -n "orderflow_scenario\|research_lab\|src.paper" main.py; echo "exit=$?"
```
Ausgabe:
```
exit=1
```

**B10** · Befehl (3bb2d62 = 'fix(binance-ws): handle a clean server close as a disconnect', Autor Rastaman-engineer, 2026-09-29)
```
bash -c "diff <(git show 3bb2d62 -- src/data_ingestion/binance_ws.py | grep '^[+-]' | grep -v '^+++\|^---') <(grep '^[+-]' docs/evidence/m09-p1-14/run1_first_autonomous_repair/engine_repair.diff | grep -v '^+++\|^---') && echo IDENTICAL"
```
Ausgabe:
```
IDENTICAL
```

**B11** · Datei `docs/evidence/m09-p1-14/summary.json:61-63`
> "run2_used_known_case": true,  
> "run3_blocker": "UNKNOWN_DEFECT_NO_APPROVED_RECIPE: fingerprint 548bd09f292063b9",  

**B12** · Befehl
```
grep -rli "hypothes" src/agents src/agent_infra src/research_intelligence; echo "exit=$?"
```
Ausgabe:
```
exit=1
```

**B13** · Datei `src/orchestration/core.py:20-24`
> M01_RECOVERY = "MISSION_01_OPERATIONAL_RECOVERY"  
> M05_GAP_CLASSIFICATION = "MISSION_05_GAP_CLASSIFICATION"  

**B14** · Befehl
```
grep -rniE "/fapi/v1/order|/api/v3/order|X-MBX-APIKEY|newOrder|create_order|place_order" --include=*.py src scripts main.py
```
Ausgabe:
```
src/tim_manager/workspace_gateway.py:70:        "create_order",
```

**B15** · Befehl
```
grep -n "confirmation" src/orderflow_scenario/cli.py; echo "exit=$?"
```
Ausgabe:
```
exit=1
```

**B16** · Befehl
```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:tests /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python - <<'E'
import dataclasses, test_orderflow_pipeline_trade_plan as t
from src.orderflow_scenario.domain import Direction
from src.orderflow_scenario.engines.confirmation import ConfirmationUpdate
from src.orderflow_scenario.engines.pipeline import Pipeline
b = t.inputs(); p = Pipeline().run(b)
L = next(s for s in p.scenarios if s.direction == Direction.LONG)
u = ConfirmationUpdate(L.scenario_id, L.mandatory_confirmations, (), ())
r = lambda x: (x.decision.status.value, x.decision.reason_codes, x.data_quality.status, str(x.data_quality.confidence))
print("A ohne Bestaetigung :", r(p))
print("B mit Bestaetigung  :", r(Pipeline().run(dataclasses.replace(b, confirmation_updates=(u,)))))
print("C ohne trades       :", r(Pipeline().run(dataclasses.replace(b, trades=None, confirmation_updates=(u,)))))
E
```
Ausgabe:
```
A ohne Bestaetigung : ('NO_TRADE', ('NO_SCENARIO_CONFIRMED',), 'PASS', '0.90')
B mit Bestaetigung  : ('TRADE_PLAN', (), 'PASS', '0.90')
C ohne trades       : ('NO_TRADE', ('DATA_QUALITY_TOO_LOW', 'TRADE_PLAN_NOT_BUILDABLE'), 'PARTIAL', '0.390')
```

**B17** · Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:24`
> **Highest evidenced level: L1.**  

**B18** · Datei `src/orderflow_scenario/execution/paper.py:77`
> """Stores paper/shadow records in memory. Never submits orders."""  

**B19** · Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:19-20`
> | L5 — Limited live | Send a bounded live order after explicit human approval |  
> | L6 — Supervised autonomy | Execute bounded orders autonomously under continuous supervision |  

**B20** · Datei `docs/autonomous_trader/DEBIAN_SERVER_SETUP_TASK_PACKAGE.md:5`
> Server-Lauf steht aus. Keine privaten Exchange-Aufrufe, kein Trading. Nur  

**B21** · Befehl
```
ls docs/autonomous_trader/campaigns; echo "exit=$?"
```
Ausgabe:
```
ls: cannot access 'docs/autonomous_trader/campaigns': No such file or directory
exit=2
```

**B22** · Datei `src/orderflow_scenario/engines/trade_plan.py:149-151`
> maximum_hold_time="defined_by_management_plan",  
> partial_take_profit_plan="reduce one third at target 1 and one third at target 2",  

**B23** · Datei `src/orderflow_scenario/engines/pipeline.py:210`
> updates_by_id = {update.scenario_id: update for update in inputs.confirmation_updates}  

**B24** · Befehl (selbst ausgeführt)
```
PYTHONDONTWRITEBYTECODE=1 /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python -m pytest -q -p no:cacheprovider -m "not local_env" tests/test_orderflow_pipeline_trade_plan.py tests/test_orderflow_trade_plan_builder.py tests/test_research_lab_stats.py tests/test_paper_automation.py
```
Ausgabe:
```
22 passed in 0.81s
```

**B25** · Befehl
```
grep -rn "ForwardOnlyReplay\|PaperExecutionJournal\|compute_calibration" --include=*.py src scripts main.py | grep -v "src/orderflow_scenario/backtest.py\|src/orderflow_scenario/execution/"; echo "exit=$?"
```
Ausgabe:
```
exit=1
```

**B26** · Datei `src/orderflow_scenario/engines/probability.py:3-4`
> Scores scenarios without fabricating statistical precision. Unless empirical  
> calibration exists, every score is labelled HEURISTIC_SCORE or  

**B27** · Befehl
```
grep -rn "empirical_hit_rate" --include=*.py src scripts | grep -v "src/orderflow_scenario/engines/probability.py\|src/orderflow_scenario/backtest.py"; echo "exit=$?"
```
Ausgabe:
```
exit=1
```

**B28** · Datei `src/task_engine/repair_executor.py:40`
> """An approved repair: a patch limited to allowlisted files with expected hashes."""  

**B29** · Datei `src/task_engine/self_heal.py:8-9`
> Without a known case or an explicitly approved recipe the task is BLOCKED;  
> nothing is improvised.  

**B30** · Datei `scripts/research_lab_run.py:7`
> The holdout (R6) is refused here; it runs exactly once, later, after Uzi's go.  

**B31** · Datei `src/agents/review.py:8-9`
> ``NO_FINDINGS`` and never an approval; the agent cannot approve, merge or  

**B32** · Datei `docs/autonomous_trader/DATA_READINESS_MATRIX.md:54-55`
> - expected 1m intervals: 1,093;  
> - persisted: 663;  

**B33** · Befehl (663 und 1.093: DATA_READINESS_MATRIX.md:54-55)
```
python3 -c "print(663/1093*100, 1093-663)"
```
Ausgabe:
```
60.658737419945105 430
```

**B34** · Datei `docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md:16`
> Befund: Seit 30.09. 16:35 UTC entstehen keine Kerzen.  

**B35** · Datei `src/orderflow_scenario/domain.py:48`
> """Operational modes. LIVE is intentionally absent: no enum value may map to live order execution."""  

**B36** · Befehl
```
grep -rn "def do_POST" src main.py
```
Ausgabe:
```
src/dashboard/server.py:230:            def do_POST(self):
```

**B37** · Datei `src/dashboard/server.py:234`
> if path not in {"/api/research/quick", "/api/research/deep"}:  

**B38** · Datei `src/dashboard/pages/operations.py:151`
> mk("release_status", "Freigabestatus", "Governance Health"  

**B39** · Befehl
```
grep -rln "load_governance_config\|default_governance_config\|OrderflowScenarioGovernance" --include=*.py src tests scripts main.py test_governance_validation.py
```
Ausgabe:
```
src/orderflow_scenario/governance.py
test_governance_validation.py
```

**B40** · Datei `src/orderflow_scenario/engines/decision.py:48-49`
> if inputs.kill_switch_enabled is False:  
> reason_codes.append("KILL_SWITCH_ACTIVE")  

**B41** · Datei `src/orderflow_scenario/governance.py:36`
> An enabled kill switch must block ALL execution-capable paths.  

**B42** · Datei `docs/research_lab/PROTOKOLL.md:219-220`
> **Obergrenze: 60 Varianten.** Wird sie erreicht, sind weitere Hypothesen erst mit  
> einem neuen, später liegenden Holdout-Zeitraum zulässig.  

**B43** · Datei `docs/research_lab/PROTOKOLL.md:315-316`
> - **Verworfen bleibt verworfen:** Scheitert eine Variante im Training oder in der  
> Validierung, wird sie nicht umparametriert.  

**B44** · Datei `docs/research_lab/PROTOKOLL.md:346-347`
> Nur anhängen, nie überschreiben. Nach Beginn von R4 sind Änderungen an Datensplit,  
> Kriterien und Raster nur noch erlaubt, wenn sie strenger machen.  

**B45** · Befehl (Einleitung Zeile 87: „KI darf niemals eigenständig:“)
```
sed -n '89p;91p;94p' TIM_CONSTITUTION.md
```
Ausgabe:
```
- Architektur verändern;
- Tests abschwächen;
- Trading aktivieren;
```

**B46** · Datei `TIM_LONG_TERM_EVOLUTION_VISION_CONSTITUTION.md:121-130`
> Automatisierung wird schrittweise erweitert. Jede neue Autonomieebene benötigt:  
> Autonomie wird durch Evidenz verdient und niemals vorausgesetzt.  

**B47** · Befehl (Zeile 19 = L5, Zeile 20 = L6)
```
sed -n '19p;20p' docs/autonomous_trader/AUTONOMY_LEVELS.md | grep -o 'NOT REACHED / PROHIBITED'
```
Ausgabe:
```
NOT REACHED / PROHIBITED
NOT REACHED / PROHIBITED
```

**B48** · Datei `docs/autonomous_trader/AUTONOMY_LEVELS.md:62-63`
> | L3 → L4 | 30–60 days of technically stable paper operation, deterministic replay and independent review |  
> | L4 → L5 | Separate explicit authorization, independent security/safety audit, manual approval per order and isolated credentials |  

**B49** · Datei `src/research_lab/backtest/engine.py:4`
> reading a later bar raises IndexError. Entries fill at the next bar's open.  

**B50** · Befehl
```
python3 -c "
import json
d=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants']
def yr(k):
    n={}
    for p in ('train','validation'):
        for y,(c,e) in d[k][p]['summary']['expectancy_by_year'].items(): n[y]=c
    full=[c for y,c in n.items() if y>='2020']
    return round(sum(full)/len(full))
print({k:(yr(k),round(yr(k)/52,1)) for k in ['L1-n100-ls','L2-L30-ls','M1-N20-k2','M3-mo-long','S2-london-r30','T1-bos-1h','T3-failedcont-1h','S1-N50-15m']})
"
```
Ausgabe:
```
{'L1-n100-ls': (13, 0.2), 'L2-L30-ls': (52, 1.0), 'M1-N20-k2': (13, 0.2), 'M3-mo-long': (52, 1.0), 'S2-london-r30': (252, 4.8), 'T1-bos-1h': (691, 13.3), 'T3-failedcont-1h': (1126, 21.7), 'S1-N50-15m': (1070, 20.6)}
```

**B51** · Datei `TIM_LONG_TERM_EVOLUTION_VISION_CONSTITUTION.md:30-34`
> eines Trading-Bots, sondern eines intelligenten Forschungssystems, das  
> Trading ist eine Anwendung, nicht die Identität von TIM.  

**B52** · Datei `TIM_LONG_TERM_EVOLUTION_VISION_CONSTITUTION.md:232`
> TIM ist kein einzelnes Modell, kein einzelner Agent und kein Trading-Bot. TIM  

**B53** · Datei `TIM_CONSTITUTION.md:1`
> # TIM Constitution V1  

**B54** · Datei `TIM_CONSTITUTION.md:13`
> TIM ist kein Trading-Bot, keine Ansammlung einzelner KI-Agenten und kein  

**B55** · Datei `TIM_CONSTITUTION.md:6-9`
> Agenten, Implementierungen und Releases müssen mit diesem Dokument vereinbar  
> sein. Bei Konflikten besitzt dieses Dokument Vorrang.  

**B56** · Datei `TIM_LONG_TERM_EVOLUTION_VISION_CONSTITUTION.md:11-14`
> gilt die etablierte Reihenfolge:  
> 1. TIM Constitution Band 1  

**B57** · Datei `docs/VISION_2030.md:19`
> - No API keys, exchange accounts, wallets, real orders or execution paths belong in the research architecture.  

**B58** · Datei `TIM_AI_AGENT_CONSTITUTION.md:148`
> - Live Trading ohne explizite menschliche Freigabe aktivieren.  

**B59** · Datei `docs/autonomous_trader/IMPLEMENTATION_ROADMAP.md:20-22`
> | 8 Paper trading | Phases 0–7 PASS |  
> | 10 Limited live | explicitly not authorized |  

**B60** · Datei `TIM_LONG_TERM_EVOLUTION_VISION_CONSTITUTION.md:215-218`
> Änderungen an der Constitution sind nur zulässig, wenn:  
> - eine nachvollziehbare Begründung vorliegt;  

**B61** · Datei `docs/research_lab/PROTOKOLL.md:327-328`
> - **Kein echtes Geld** vor Abschluss von R7 und einem eigenen, freigegebenen  
> Bauplan dafür.  

**B62** · Datei `docs/research_lab/PROTOKOLL.md:34`
> Ein Setup gilt als profitabel, wenn es **alle fünf** Bedingungen erfüllt:  

**B63** · Datei `docs/research_lab/PROTOKOLL.md:291`
> 5. **Papier-Betrieb (R7)** nur für BESTANDEN-Kandidaten.  

**B64** · Datei `docs/research_lab/PROTOKOLL.md:222-223`
> Zur Einordnung: Bei m = 48 muss der beste Kandidat im Holdout p < 0,05 / 48 ≈ 0,0010  
> gegen zufällige Einstiege erreichen.  

**B65** · Datei `docs/research_lab/PROTOKOLL.md:44`
> Unterschreitet ein Setup K3, lautet das Urteil **KEIN URTEIL**, nicht BESTANDEN.  

**B66** · Datei `docs/research_lab/PROTOKOLL.md:307-308`
> - **Kein Widerspruch**, wenn nach 8 Wochen weniger als 20 Trades angefallen sind  
> (fast immer bei Long, oft bei Mid), der Live-Erwartungswert im Band liegt und der  

**B67** · Datei `src/research_lab/protocol.py:62-63`
> RISK_PER_TRADE = 0.01  
> MAX_DRAWDOWN_LIMIT = 0.20  

**B68** · Befehl (Kosten je Trade = Basis-Erwartungswert minus Stress-Erwartungswert (Stresskosten sind laut PROTOKOLL.md:148-151 die doppelte Gebühr und Slippage))
```
python3 -c "
import json
d=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants']
def rng(keys):
    c=[d[k][p]['summary']['expectancy_r']-d[k][s]['expectancy_r'] for k in keys for p,s in (('train','stress_train'),('validation','stress_validation'))]
    return round(min(c),3),round(max(c),3)
st=[k for k in d if k[0] in 'ST']; lm=[k for k in d if k[0] in 'LM']
print('Kosten je Trade in R, S/T:',rng(st),'| L/M:',rng(lm))
sd=[d[k]['train']['summary']['std_r'] for k in st]
print('std_r Training S/T:',round(min(sd),2),round(max(sd),2))
"
```
Ausgabe:
```
Kosten je Trade in R, S/T: (0.136, 0.61) | L/M: (0.015, 0.085)
std_r Training S/T: 0.98 1.43
```

**B69** · Datei `docs/research_lab/PROTOKOLL.md:223-224`
> Mit wenigen Trades (vor allem Long) ist das  
> kaum zu schaffen. Das ist gewollt und der Preis für die Ehrlichkeit der Korrektur.  

**B70** · Datei `docs/autonomous_trader/CURRENT_STATE_ASSESSMENT.md:41-42`
> | Backtest/walk-forward | no engine found | — | — | MISSING |  
> | Risk/order/position management | no engine found | — | — | MISSING |  

**B71** · Befehl
```
ls src/research_lab/backtest/engine.py src/orderflow_scenario/engines/risk.py
```
Ausgabe:
```
src/orderflow_scenario/engines/risk.py
src/research_lab/backtest/engine.py
```

**B72** · Datei `docs/tim_v4_developer_manual/VERIFICATION_REPORT.md:30`
> - Fehlende Tests: kein dedizierter Governance-Test; nur `test_repository_governance.py`.  

**B73** · Datei `docs/autonomous_trader/DATA_READINESS_MATRIX.md:23-24`
> | Funding rate | MISSING |  
> | Open interest | MISSING |  

**B74** · Befehl
```
grep -rln "fapi\|openInterest\|fundingRate\|premiumIndex\|forceOrder" --include=*.py src scripts config
```
Ausgabe:
```
src/research_lab/data/archive.py
```

**B75** · Datei `docs/autonomous_trader/IMPLEMENTATION_ROADMAP.md:24-25`
> Research parameters such as 0.25% per-trade risk, 1% daily loss, maximum three  
> trades and stop after three losses  

**B76** · Datei `src/orderflow_scenario/config.py:161-166`
> RiskTier("CONSERVATIVE", Decimal("0.0025"), Decimal("5"), Decimal("1.5")),  
> daily_loss_fraction=Decimal("0.03"),  

**B77** · Befehl
```
find src/research_lab/external -name '*.py' | xargs cat | wc -l; find src/research_lab -name '*.py' | xargs cat | wc -l
```
Ausgabe:
```
3042
5252
```

**B78** · Befehl
```
python3 -c "import json;print(json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['buy_and_hold'])"
```
Ausgabe:
```
{'train': 2.527246907709989, 'validation': 4.6569520674027025}
```

**B79** · Datei `src/research_lab/hypotheses/strategies.py:13-14`
> from src.analysis.bos_detector import BOSDetector  
> from src.analysis.bronxc_rules import BroncxRules  

**B80** · Befehl
```
grep -c "def mandatory_fulfilled_for" src/orderflow_scenario/engines/confirmation.py
```
Ausgabe:
```
3
```

**B81** · Datei `src/orderflow_scenario/engines/confirmation.py:65`
> def mandatory_fulfilled_for_breakout(close_above_trigger: bool, retest_holds: bool, constructive: bool, no_fall_back: bool) -> bool:  

**B82** · Datei `src/paper/automation.py:54`
> raise ValueError("Research case must be closed with a documented outcome")  

**B83** · Befehl
```
grep -rln "DemoTrader" --include=*.py src scripts main.py
```
Ausgabe:
```
src/paper/demo_trader_v1.py
scripts/demo_trader_report.py
```

**B84** · Datei `docs/tim_v4_developer_manual/IMPLEMENTATION_GAP.md:104`
> - eigene Liquiditäts-Engine, PortfolioState/Allokation, Shadow-Engine, Review-Engine.  

**B85** · Datei `src/orderflow_scenario/engines/data_quality.py:107-108`
> if not inputs.trades:  
> confidence = confidence * Decimal("0.5")  

**B86** · Datei `src/research_lab/data/parse.py:27-31`
> taker_buy_volume: float  
> """Taker buy minus taker sell volume (protocol section 3.1)."""  

**B87** · Datei `docs/research_lab/PROTOKOLL.md:60`
> | Klines BTCUSDT | USD-M Perpetual | 1d, 1h, 15m, 5m | Handelsinstrument für Mid und Short |  

**B88** · Datei `docs/autonomous_trader/DATA_READINESS_MATRIX.md:20-26`
> | Futures AggTrades | MISSING |  
> | Order-book snapshots | MISSING |  

**B89** · Datei `src/research_intelligence/expansion.py:21`
> 'reason': 'NO_CONFIGURED_VALIDATED_DERIVATIVE_FEED'  

**B90** · Datei `src/orderflow_scenario/adapters/openmarket.py:14`
> confirms it; by default they stay missing (REST_SIDE_AGGRESSOR_SEMANTICS=UNPROVEN).  

**B91** · Datei `docs/knowledge/BRONCX_DISCORD_FEED.md:13`
> älter als die Frist (Standard 24 h) noch wirken  

**B92** · Datei `src/orderflow_scenario/engines/pipeline.py:59-66`
> trades: Sequence[Trade] | None = None  
> open_interest_trend: str | None = None  

**B93** · Datei `src/research_lab/protocol.py:66`
> MIN_TRADES_HOLDOUT = {"short": 200, "mid": 30, "long": 10}  

**B94** · Datei `docs/research_lab/PROTOKOLL.md:89`
> | Holdout | 2025-01-01 bis Ende des letzten vollständigen Monats vor dem R6-Lauf | genau ein Lauf (R6) |  

**B95** · Datei `docs/research_lab/PROTOKOLL.md:45-46`
> Für M1 mit N = 55 und für M2 ist das im Holdout von rund 20 Monaten wahrscheinlich,  
> das steht hier vorab fest.  

**B96** · Befehl
```
python3 -c "
from statistics import NormalDist as N
z=N().inv_cdf
n=lambda d,s,a:round(((z(1-a)+z(.8))*s/d)**2)
m=lambda k,s,a:round((z(1-a)+z(.8))*s/k**.5,2)
print('alpha_Holm m=48:',round(.05/48,6),'| n fuer +0.2R, sd 1.3:',n(.2,1.3,.05/48),'| MDE n=30:',m(30,1.3,.05/48),'| MDE n=200:',m(200,1.3,.05/48))
print('ohne Korrektur (alpha .05): n fuer +0.2R, sd 1.3:',n(.2,1.3,.05),'| m=60: alpha',round(.05/60,6),'n',n(.2,1.3,.05/60))
"
```
Ausgabe:
```
alpha_Holm m=48: 0.001042 | n fuer +0.2R, sd 1.3: 649 | MDE n=30: 0.93 | MDE n=200: 0.36
ohne Korrektur (alpha .05): n fuer +0.2R, sd 1.3: 261 | m=60: alpha 0.000833 n 671
```

**B97** · Datei `docs/research_lab/PROTOKOLL.md:153`
> Gebühren werden als Taker gerechnet, auch wenn ein Limit-Einstieg denkbar wäre.  

**B98** · Datei `docs/autonomous_trader/DATA_READINESS_MATRIX.md:30-31`
> | Fees | PARTIAL | fixed TEST_ONLY paper parameter |  
> | Slippage | PARTIAL | fixed TEST_ONLY paper parameter |  

**B99** · Datei `docs/autonomous_trader/STRATEGY_READINESS_MATRIX.md:84-86`
> ## Overall strategy status  
> **MISSING.**  

**B100** · Datei `tests/test_orderflow_pipeline_trade_plan.py:57`
> assert plan["entry_model"] == "LIMIT_RETEST"  

**B101** · Datei `config/settings.py:27`
> wss://stream.binance.com:9443/ws  

**B102** · Befehl
```
sed -n 26,33p TIM_V2_BLOCKER_REGISTER.md | grep -c "\*\*OPEN\*\*"
```
Ausgabe:
```
8
```

**B103** · Datei `docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md:3`
> Stand 2026-10-01. Entwurf, am Server wird erst nach Uzis Go etwas geändert.  

**B104** · Datei `scripts/tim_server_health.py:4-7`
> Exit code  
> 0 means no RED check, 2 means at least one RED check.  

**B105** · Datei `docs/knowledge/BRONCX_DISCORD_FEED.md:3`
> Status: externe Meinung, fließt gewichtet in die Analyse ein. Ergänzt den  

**B106** · Datei `docs/research_lab/PROTOKOLL.md:107-108`
> Zeitraum abgeleitet. Für TIMs eigene Regeln (T1–T3) gilt das nicht sicher, weil sie  
> 2026 entwickelt wurden, also im Holdout-Zeitraum.  

**B107** · Datei `docs/autonomous_trader/DEBIAN_MAC_OPERATING_PLAN.md:52`
> API-Keys ohne Withdraw-Recht und IP-Whitelist.  

**B108** · Datei `src/bugfixer/executor.py:23`
> SCOPE = 'LOCAL_DERIVED_DIAGNOSTIC_ARTIFACT_ONLY'  

**B109** · Befehl (selbst ausgeführt, Laufzeit rund 3 min)
```
PYTHONDONTWRITEBYTECODE=1 /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python -m pytest -q -p no:cacheprovider -m "not local_env" tests/test_research_lab_guard.py
```
Ausgabe:
```
7 passed in 198.90s (0:03:18)
```

**B110** · Datei `docs/research_lab/PROTOKOLL.md:353`
> Ergebnis: 0 von 200 Zufallsreihen BESTANDEN, 190 von 200 Reihen mit +0,2 R BESTANDEN  

**B111** · Befehl
```
git log --since=2026-09-29 --oneline | grep -c research_lab; grep -rn "research_lab.external" src/research_lab/hypotheses src/research_lab/runner.py scripts/research_lab_run.py; echo "exit=$?"
```
Ausgabe:
```
24
exit=1
```

**B112** · Datei `docs/autonomous_trader/DEBIAN_MAC_OPERATING_PLAN.md:78`
> - **Engpass ist Edge, nicht Governance:** Governance nur so weit ausbauen, wie  

**B113** · Befehl
```
for d in src/tim_manager src/task_governance src/dashboard; do echo "$d $(find $d -name '*.py' | xargs cat | wc -l)"; done
```
Ausgabe:
```
src/tim_manager 3147
src/task_governance 1162
src/dashboard 4177
```

**B114** · Befehl
```
sed -n 113,115p src/orderflow_scenario/domain.py
```
Ausgabe:
```
BREAKOUT_ACCEPTANCE = "BREAKOUT_ACCEPTANCE"
LIQUIDITY_SWEEP_REVERSAL = "LIQUIDITY_SWEEP_REVERSAL"
REJECTION_FAILED_BREAKOUT = "REJECTION_FAILED_BREAKOUT"
```

**B115** · Datei `docs/research_lab/PROTOKOLL.md:210`
> Stop 1 × ATR(14), Ziel 2 R, Zeit-Stop 24 Kerzen  

**B116** · Datei `src/research_lab/protocol.py:65`
> MIN_TRADES_TRAIN = {"short": 500, "mid": 50, "long": 20}  

**B117** · Datei `src/research_lab/runner.py:41-42`
> USDM_LOAD = (2020, 1)  
> USDM_SIGNALS_MS = _utc_ms(2020, 1, 1)  

**B118** · Datei `docs/research_lab/PROTOKOLL.md:87`
> | Training | Datenbeginn bis 2022-12-31 | Hypothesen rechnen, Raster auswerten |  

**B119** · Datei `docs/research_lab/PROTOKOLL.md:318-319`
> - **Kein Nachbessern am Holdout:** Ein NICHT BESTANDEN im Holdout ist endgültig  
> für diese Variante und alle Varianten, die aus ihr abgeleitet werden.  

**B120** · Datei `docs/research_lab/PROTOKOLL.md:324-325`
> - **Papier-Stopp:** Liegt der Live-Erwartungswert nach mindestens 20 Trades unter  
> dem 5. Perzentil des Bands oder überschreitet der Drawdown die Grenze aus K4,  

**B121** · Datei `docs/autonomous_trader/TARGET_ARCHITECTURE.md:87`
> 9. Strategy cannot import or call an exchange adapter directly.  

**B122** · Datei `docs/autonomous_trader/DEBIAN_MAC_OPERATING_PLAN.md:81`
> - **Hebel:** konservativ. Hohe Hebel sind mit der Capital Ladder unvereinbar.  

**B123** · Datei `scripts/tim_server_campaign.py:4-6`
> declare   write docs/autonomous_trader/campaigns/debian_campaign_<start>.json before the  
> evaluate  measure closed 1m candle coverage inside a declared window (read-only).  

**B124** · Datei `CLAUDE.md:9-10`
> - Größere Aufgaben: erst Ziel, Erfolgskriterium, Nicht-Ziele, Abhängigkeiten und Risiken klären,  
> in überprüfbare Pakete mit konkretem Prüfbefehl teilen, Plan zeigen und auf Go warten.  

**B125** · Datei `tests/test_orderflow_pipeline_trade_plan.py:1`
> """A confirmed scenario reaches a DRAFT trade plan whose first target is 1.5R (decided 2026-09-30)."""  

**B126** · Datei `docs/research_lab/reports/r4_2026-09-29T2219Z.md:3`
> Register m = 48. Holdout nicht geladen.  

**B127** · Befehl (Schritte M0 bis M5)
```
grep -c "^\*\*M[0-5]" docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md
```
Ausgabe:
```
6
```

**B128** · Datei `scripts/research_lab_run.py:46-47`
> if args.commit_register:
>     parser.error("--commit-register needs the full run without --only")

**B129** · Befehl (selbst ausgeführt, auf einer Kopie des Registers; das Repository blieb unberührt)
```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python -c "import shutil;from src.research_lab.stats.register import HypothesisRegister as H;shutil.copy('docs/research_lab/REGISTER.jsonl','/tmp/r.jsonl');r=H('/tmp/r.jsonl');print(r.m);r.set_status('T1-bos-1h','failed_train')"
```
Ausgabe (Fehlerzeile wörtlich):
```
48
RegisterError: T1-bos-1h already has a final status
```

**B130** · Befehl (selbst ausgeführt auf einer Kopie des Registers in einem Verzeichnis außerhalb des Repos; 12 neue Einträge `OF-0` bis `OF-11`, dann ein 13.)
```
f=$(mktemp); cp docs/research_lab/REGISTER.jsonl $f; PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python -c "import sys;from src.research_lab.stats.register import HypothesisRegister as H;r=H(sys.argv[1]);[r.register(f'OF-{i}','OF',{}) for i in range(12)];print(r.m);r.register('OF-x','OF',{})" $f
```
Ausgabe:
```
60
RegisterError: register limit of 60 reached; a new holdout period is needed
```

**B131** · Datei `src/orderflow_scenario/engines/pipeline.py:191`
> levels = inputs.levels or self._levels_from_candles(inputs.candles, inputs.price_now)

**B132** · Datei `src/orderflow_scenario/engines/pipeline.py:337`
> session_high=Decimal(max(c.high for c in candles[-6:])),

**B133** · Befehl (selbst ausgeführt; `t.inputs()` aus `tests/test_orderflow_pipeline_trade_plan.py`, 36 Kerzen)
```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:tests /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python -c "import time,test_orderflow_pipeline_trade_plan as t;from src.orderflow_scenario.engines.pipeline import Pipeline;b=t.inputs();P=Pipeline();s=time.time();[P.run(b) for _ in range(200)];print((time.time()-s)/200*1000)"
```
Ausgabe: `1.7` (ms je Lauf, gerundet; Maschine und Fenster 36 Kerzen).

**B134** · Befehl
```
git show -s --format='%ad %h %s' --date=iso 2f5f9bd
```
Ausgabe:
```
2026-09-29 20:52:17 +0000 2f5f9bd feat(research-lab): R1 Datenloader, R2 Backtest-Motor, R3 Statistik-Wächter
```
Der R4-Bericht trägt den Zeitstempel `r4_2026-09-29T2219Z` im Dateinamen (B3).

**B135** · Befehl
```
sed -n 296,312p docs/research_lab/PROTOKOLL.md | grep -ci "ausfall\|lücke\|unterbrech"
```
Ausgabe: `0`

**B136** · Datei `src/research_lab/stats/register.py:105`
> not_candidates = [c for c in candidates if variants[c]["status"] != "candidate"]

**B137** · Datei `src/research_lab/stats/register.py:42`
> raise RegisterError("register hash chain is broken; the file was edited")

**B138** · Datei `tests/test_research_lab_hypotheses.py:22`
> assert len(VARIANTS) == 48

**B139** · Befehl (selbst ausgeführt)
```
PYTHONDONTWRITEBYTECODE=1 /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python -m pytest -q -p no:cacheprovider -m "not local_env" tests/test_research_lab_hypotheses.py
```
Ausgabe: `52 passed in 25.40s`

**B140** · Datei `docs/research_lab/PROTOKOLL.md:65-66`
> **Abweichung vom Bauplan:** Der Short-Horizont nutzt statt aggTrades die Spalte
> „taker buy base volume“ der Klines.

**B141** · Datei `docs/research_lab/PROTOKOLL.md:63`
> | aggTrades BTCUSDT | USD-M Perpetual | – | optional, nur Stichproben zur Prüfung der Delta-Näherung |

**B142** · Datei `src/research_lab/runner.py:231`
> def ensure_registered(register: HypothesisRegister, specs: Sequence[VariantSpec] = VARIANTS) -> None:

**B143** · Datei `src/research_lab/runner.py:204`
> def run(store: ArchiveStore, *, specs: Sequence[VariantSpec] = VARIANTS, config: RunConfig = RunConfig(),

**B144** · Datei `docs/research_lab/PROTOKOLL.md:349`
> | Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |

**B145** · Datei `tests/test_research_lab_hypotheses.py:24`
> assert per_prefix == {"L": 12, "M": 22, "S": 8, "T": 6}

**B146** · Befehl
```
python3 -c "print(0.05/48, 0.05/52, 0.05/60, 200/91)"
```
Ausgabe:
```
0.0010416666666666667 0.0009615384615384616 0.0008333333333333334 2.197802197802198
```

**B147** · Befehle
```
python3 -c "import json;d=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants'];print([(k,round(d[k]['train']['summary']['expectancy_r'],2),d[k]['train']['summary']['trades'],round(2*d[k]['train']['summary']['expectancy_r']-d[k]['stress_train']['expectancy_r'],2)) for k in d if k.startswith('S1')])"
grep -n "^| S1 " docs/research_lab/PROTOKOLL.md | cut -c1-50
```
Ausgabe (Name, Erwartungswert in R, Trades, Erwartungswert ohne Gebühr und Slippage; S1 ist im Protokoll Delta/CVD-Divergenz auf 5m und 15m, alle vier im Register `failed_train`, geprüft über `docs/research_lab/REGISTER.jsonl`):
```
[('S1-N20-5m', -0.68, 14070, -0.21), ('S1-N20-15m', -0.39, 5540, -0.08), ('S1-N50-5m', -0.61, 9476, -0.17), ('S1-N50-15m', -0.33, 3223, -0.06)]
203:| S1 | Delta/CVD-Divergenz | Neues N-Kerzen-Hoch, CVD über N Kerzen ohne neues Hoch → Short
```

**B148** · Datei `docs/research_lab/PROTOKOLL.md:199`
> ### Short (Minuten bis Stunden, Perpetual-Klines)

**B149** · Datei `docs/research_lab/PROTOKOLL.md:191`
> ### Mid (Tage, Signale auf Tageskerzen)

**B150** · Datei `docs/research_lab/PROTOKOLL.md:150`
> | Funding | historische Perpetual-Rate zum jeweiligen Zeitpunkt (00/08/16 UTC), wenn die Position dann offen ist ... | Rate unverändert, aber nie zugunsten des Setups gebucht |

**B151** · Befehl
```
python3 -c "import json;d=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants'];r=lambda k:[round(d[k][p]['summary']['expectancy_r']-d[k][s]['expectancy_r'],2) for p,s in (('train','stress_train'),('validation','stress_validation'))]
for i in ('15m','1h'):
    c=[x for k in d if k[0]=='T' and k.endswith(i) for x in r(k)];print(i,min(c),max(c))"
```
Ausgabe:
```
15m 0.33 0.52
1h 0.18 0.31
```

**B152** · Datei `docs/research_lab/PROTOKOLL.md:341`
> | O2 | Datenweg: (a) Domains in der Umgebung freigeben oder (b) Download auf dem Mac | Uzi |

**B153** · Datei `scripts/research_lab_fetch.py:6`
> Needs network access to data.binance.vision. Holdout months (2025+) are refused.

**B154** · Datei `scripts/research_lab_fetch.py:30`
> parser.add_argument("--preset", choices=["r4"], help="fetch every archive the R4 run needs (up to 2024-12)")

**B155** · Befehl (selbst ausgeführt)
```
PYTHONDONTWRITEBYTECODE=1 /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python -m pytest -q -p no:cacheprovider -m "not local_env" tests/test_observation_engine.py tests/test_orderflow_observations.py
```
Ausgabe:
```
6 passed, 1 skipped in 0.12s
```

**B156** · Befehl (Trades je Woche im Training; 365,25 × 3 / 7 = 156,5 Wochen für 2020-01 bis 2022-12, B117, B118; S und T sind die Short-Regeln, 15m und 1h nach Namensende)
```
python3 -c "
import json
d=json.load(open('docs/research_lab/reports/r4_2026-09-29T2219Z.json'))['variants']
w=365.25*3/7
r={k:round(d[k]['train']['summary']['trades']/w,1) for k in d if k[0] in 'ST'}
print(min(r.values()),max(r.values()))
for i in ('15m','1h'):
    c=[v for k,v in r.items() if k.endswith(i)];print(i,min(c),max(c))
"
```
Ausgabe:
```
4.4 89.9
15m 19.9 86.2
1h 5.1 22.5
```

**B157** · Datei `src/orderflow_scenario/engines/pipeline.py:242-243`
> account = inputs.account or AccountState(equity=Decimal("10000"), free_margin=Decimal("10000"))
> risk_output = self.risk_engine.evaluate(trade_plan, account, inputs.risk_tier_name)

**B158** · Datei `src/orderflow_scenario/engines/scenario_generator.py:168`
> entry_model=EntryModel.LIMIT_RETEST if entry_low is not None else EntryModel.MARKET_AFTER_CONFIRMATION,

**B159** · Befehl
```
grep -n "entry_model" src/orderflow_scenario/engines/pipeline.py
```
Ausgabe:
```
367:        entry_model=plan.entry_model,
```

**B160** · Datei `docs/autonomous_trader/SERVER_MIGRATION_SRV_TO_OPT.md:11`
> `market-feeds/code`, Branch `agent/broncx-orderflow` (9bcede7), schreibt `venue_trades`, nicht auf GitHub
