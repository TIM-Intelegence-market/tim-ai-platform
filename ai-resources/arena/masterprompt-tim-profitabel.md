# Aufgabe: Was fehlt TIM, um ein profitabler Trading-Bot nach Uzis Vision zu werden?

## 1. Die Frage

Uzi, Eigentümer und Entwickler von TIM, fragt wörtlich:

> „Was fehlt TIM, um ein profitabler Trading-Bot mit meiner Vision zu werden?“

Seine Vision beschreibt er so (wörtlich, sinngemäß nur in der Rechtschreibung
geglättet):

> „Meine Vision ist meine Idee, ich habe sie noch nie strukturiert. Ziel ist ein
> Tradingbot, der mit seinem Tradingwissen sich selbst repariert, entwickelt und
> steuert, komplett autonom. Doch die Setups müssen menschlich bestätigt werden.“

Beantworte die Frage vollständig, ehrlich und belegt. Uzi entscheidet nach deiner
Antwort, woran in den nächsten Wochen gearbeitet wird. Die Antwort muss also eine
Entscheidungsgrundlage sein, keine Ermutigung und keine allgemeine Trading-Beratung.
Weil die Vision bisher nicht strukturiert ist, gehört es zur Aufgabe, sie in
prüfbare Fähigkeiten zu zerlegen (Abschnitt 6, Punkt 2).

## 2. Wo TIM liegt

Das Repository ist dein aktuelles Arbeitsverzeichnis, in dieser Umgebung
`/home/user/tim-ai-platform`. Alle Pfade unten sind relativ dazu. Du darfst jede
Datei darin lesen und lesende Befehle ausführen (`ls`, `grep`, `git log`, `git show`,
Python-Skripte, die nur lesen und nichts ins Netz schicken). Du darfst nichts im
Repository ändern, keine Dienste starten und keine Börse oder externe API aufrufen.

Du darfst einzelne vorhandene Tests ausführen, um eine Aussage zu beweisen. Nutze
dafür genau diese Form (eigene Python-Umgebung außerhalb des Repos, keine Cache-
Dateien im Repo):

```bash
PYTHONDONTWRITEBYTECODE=1 /tmp/claude-0/-home-user-tim-ai-platform/7f0c41db-9887-544d-9792-14dfffafda79/scratchpad/venv/bin/python \
  -m pytest -q -p no:cacheprovider -m "not local_env" <Testdatei oder -verzeichnis>
```

Führe nur gezielte Testdateien aus, nie die ganze Suite (sie dauert zu lange).
Tests, die eine Datenbank, Ollama oder Netz brauchen, schlagen hier fehl. Das ist
dann kein Beleg gegen den Code, sondern UNVERIFIED. Fehlt die Python-Umgebung unter
diesem Pfad, prüfe ohne Tests und schreib das in dein Belegprotokoll.

## 3. Uzis Vision: seine Worte und was das Repository dazu enthält

### 3.1 Die Vision in fünf Teilen

Maßgeblich sind Uzis eigene Worte aus Abschnitt 1. Sie enthalten fünf Teile:

| Teil | Uzis Worte | Bedeutung für diese Aufgabe |
|---|---|---|
| V1 Tradingwissen | „mit seinem Tradingwissen“ | TIM handelt auf Grundlage einer Trading-Methode, die es kennt und anwendet |
| V2 Selbstreparatur | „sich selbst repariert“ | TIM erkennt eigene Fehler und behebt sie ohne Menschen |
| V3 Selbstentwicklung | „entwickelt“ | TIM verbessert sein Wissen, seine Regeln oder seinen Code selbst |
| V4 Selbststeuerung | „steuert, komplett autonom“ | TIM betreibt sich selbst: Daten, Analyse, Aufgaben, Betrieb |
| V5 Menschliche Bestätigung | „die Setups müssen menschlich bestätigt werden“ | Kein Trade ohne Bestätigung durch einen Menschen |

Was „Setup“, „bestätigt“ und „komplett autonom“ genau umfassen, hat Uzi nicht
festgelegt. Leg es in deiner Antwort für jeden Teil prüfbar fest, nimm die
naheliegendste Lesart und nenne sie als Annahme.

Prüfe außerdem, wo sich die Teile untereinander oder mit dem Ziel „profitabel“
reiben. Beispiele für solche Reibungen, die du selbst bewerten musst:

- V3 gegen die Regeln aus `docs/research_lab/PROTOKOLL.md`: Ein System, das seine
  Regeln selbst weiterentwickelt, testet viele Varianten. Das Protokoll begrenzt
  die Zahl der Varianten und verbietet, Verworfenes umzuparametrieren.
- V4 und V5 gegen die Stufen in `docs/autonomous_trader/AUTONOMY_LEVELS.md`: Dort
  ist L5 ein Live-Auftrag mit menschlicher Freigabe je Order, L6 die überwachte
  Autonomie. Ordne Uzis Vision in diese Stufen ein.
- V5 gegen den Zeitbedarf: Wie viele Setups pro Tag bzw. Woche fallen an, wie
  schnell muss ein Mensch bestätigen, bevor das Setup verfällt?

### 3.2 Was das Repository zu den fünf Teilen enthält

Prüfe für jeden Teil, was es schon gibt. Ausgangspunkte (nicht vollständig):

- V1: `src/orderflow_scenario/`, `src/analysis/`, `src/orderflow/`,
  `docs/knowledge/`.
- V2: `src/bugfixer/`, `docs/bugfixer/`, `docs/evidence/m09-p1-14/` (laut
  Ordnernamen eine erste autonome Reparatur und eine Selbstheilung bei
  Wiederholung; prüfe, was dort wirklich belegt ist).
- V3: `src/research_lab/`, `src/research_intelligence/`, `src/agents/`,
  `src/agent_infra/`.
- V4: `src/orchestration/`, `src/task_engine/`, `src/task_governance/`,
  `src/tim_manager/`, `src/operational/`, `ops/`.
- V5: `src/dashboard/` (Bereich „Freigabe“), `src/orderflow_scenario/governance.py`
  (Kill Switch, Modus-Wächter), `src/orderflow_scenario/engines/decision.py`.

### 3.3 Weitere Dokumente zur Vision

Ergänzend ist die Vision auf mehrere Dokumente verteilt. Sie gehen Uzis eigenen
Worten nicht vor, aber sie zeigen, was er bisher geplant hat:

- `docs/autonomous_trader/DEBIAN_MAC_OPERATING_PLAN.md` (Stand 2026-10-01): TIM auf
  zwei Rechner aufteilen. Ein Debian-Server läuft 24/7 und erzeugt Evidenz, der Mac
  erzeugt Hypothesen. Weg: Datenstabilität → Zusatzdaten (Funding, Open Interest,
  Mark Price, Orderbook) → Hypothesen-Pipeline → harte Validierung → Risk Engine →
  Paper Trading → Shadow → Micro-Live mit minimalem Kapital und niedrigem Hebel
  („Capital Ladder“). Leitplanken dort: „Engpass ist Edge, nicht Governance“, „ein
  Instrument, ein Timeframe, eine Strategie zuerst“, „Die meisten Hypothesen
  scheitern“.
- `docs/autonomous_trader/AUTONOMY_LEVELS.md`,
  `docs/autonomous_trader/TARGET_ARCHITECTURE.md`,
  `docs/autonomous_trader/IMPLEMENTATION_ROADMAP.md`: die Stufen L0 bis L6 (Daten → Beobachtungen →
  Setup-Vorschläge → Paper Orders → Shadow → Limited Live → überwachte Autonomie),
  die Zielarchitektur und die Phasen 0 bis 10 mit ihren Gates.
- `docs/knowledge/BRONCX_BOOTCAMP_KNOWLEDGE.md` und
  `docs/knowledge/BRONCX_DISCORD_FEED.md`: die Trading-Methode, an der sich TIM
  orientiert (Orderflow, Auction Market Theory, Marktstruktur, Liquidität;
  Kette Kontext → Ort → Struktur → Orderflow → Reaktion → Szenario →
  Invalidierung).
- `src/orderflow_scenario/` und `docs/tim_v4_developer_manual/`: die Engine, die
  Märkte „aus Sicht eines professionellen Orderflow-Traders“ deuten soll
  (Szenarien, Bestätigung, Wahrscheinlichkeit, Trade-Plan, Risk Engine, Paper/Shadow).
- `docs/VISION_2030.md` und `TIM_LONG_TERM_EVOLUTION_VISION_CONSTITUTION.md`.
  **Achtung, Spannung:** Band 10 sagt wörtlich: „Das Ziel ist nicht der Bau eines
  Trading-Bots, sondern eines intelligenten Forschungssystems, das Entscheidungen
  nachvollziehbar vorbereitet. Trading ist eine Anwendung, nicht die Identität von
  TIM.“ Uzis Vision zielt dagegen ausdrücklich auf einen autonomen Trading-Bot.
  Löse diesen Widerspruch nicht stillschweigend auf. Benenne ihn und sag, welche
  Dokumente angepasst werden müssten, wenn Uzis Vision gilt.

## 4. Was „profitabel“ hier heißt

Uzi hat im freigegebenen Forschungsprotokoll `docs/research_lab/PROTOKOLL.md`
(Version 1.0, Abschnitt 2) vorab festgelegt, wann ein Setup als profitabel gilt.
Alle fünf Bedingungen müssen erfüllt sein:

- K1: Erwartungswert nach Gebühren, Slippage und Funding > 0 R je Trade im Holdout.
- K2: schlägt zufällige Einstiege, korrigiert nach Holm-Bonferroni über alle
  Registereinträge (Familien-α = 5 %).
- K3: Mindestzahl an Trades im Holdout (Short ≥ 200, Mid ≥ 30, Long ≥ 10).
- K4: maximaler Drawdown ≤ 20 % bei 1 % Risiko je Trade.
- K5: Papier-Betrieb über 4 bis 8 Wochen im erwarteten Band.

Uzi hat dazu gesagt: „K1 und K5 sind die ersten Kriterien.“ Lies das so: Vorrang
haben ein positiver Erwartungswert nach allen Kosten (K1) und die Bestätigung im
Papier-Betrieb (K5). K2 bis K4 bleiben Regeln des freigegebenen Protokolls und
werden weiter geprüft. Sag ausdrücklich, was es bedeutet, wenn ein Setup K1 und K5
erfüllt, aber an K2, K3 oder K4 scheitert.

Hältst du den Maßstab für falsch, zu streng oder zu locker, sag das mit Begründung,
aber miss TIM trotzdem zuerst daran. „Profitabler Bot“ heißt darüber hinaus, dass
das Setup auch im laufenden Betrieb (Daten, Ausführung, Risiko, Überwachung,
menschliche Bestätigung nach V5) so funktioniert, wie es getestet wurde.

## 5. Bekannte Fakten, die du selbst nachprüfen musst

Diese Punkte stehen in den genannten Dateien. Prüfe jeden selbst, bevor du ihn
verwendest. Manche Dokumente sind älter als der Code. Wo Dokument und Code sich
widersprechen, gilt der Code, und du nennst den Widerspruch.

1. **Strategietest R4/R5 (2026-09-29):**
   `docs/research_lab/reports/r4_2026-09-29T2219Z.md` und
   `docs/research_lab/REGISTER.jsonl`. Alle 48 registrierten Varianten sind
   durchgefallen (42 im Training, 6 in der Validierung). Ergebnis laut Bericht:
   „kein Vorteil in Training/Validierung gefunden“, der Holdout wurde nicht
   angefasst. Darunter TIMs eigene Regeln T1 (BOS), T2 (Broncx REJECTION) und
   T3 (Broncx FAILED_CONTINUATION), alle mit negativem Erwartungswert. Kaufen und
   Halten lag im selben Zeitraum bei +252,7 % (Training) und +465,7 % (Validierung).
2. **Register-Obergrenze:** Das Protokoll erlaubt höchstens 60 Varianten für diesen
   Holdout. 48 sind verbraucht (Abschnitte 6 und 10).
3. **Was R4 nicht getestet hat:** Prüfe, ob die Szenario- und Trade-Plan-Logik aus
   `src/orderflow_scenario/` (die eigentliche Orderflow-Methode) jemals über
   historische Daten getestet wurde. Nach Stand dieser Aufgabe ist das nicht belegt
   (UNVERIFIED). Prüfe auch, welche historischen Daten diese Logik bräuchte und ob es
   sie gibt.
4. **Daten:** `docs/autonomous_trader/DATA_READINESS_MATRIX.md` nennt nur Spot-
   AggTrades (Binance BTCUSDT, öffentlicher WebSocket, ohne Catch-up nach
   Reconnect) als vorhandene Live-Daten. Futures-AggTrades, Funding, Open Interest,
   Liquidationen, Orderbook, Mark/Index Price fehlen dort. Das Research Lab nutzt
   zusätzlich öffentliche Binance-Archive (Klines, Funding). Die gemessene
   Continuous Coverage lag im eingefrorenen Fenster vom Juli 2026 bei 60,659 %
   (Ziel Phase 1: ≥ 99,5 %). Ob der Debian-Server inzwischen läuft und wie die
   Coverage heute ist, ist nicht belegt (UNVERIFIED). Siehe `ops/`, `scripts/` und
   die Commits ab 2026-09-30.
5. **Offene Blocker:** `TIM_V2_BLOCKER_REGISTER.md` listet V2-B01 bis V2-B08, alle
   OPEN.
6. **Ausführung:** Es gibt keinen Live-Adapter zur Börse und keine API-Schlüssel
   für Orders. Prüfe, wie weit Paper- und Shadow-Ausführung
   (`src/orderflow_scenario/execution/`, `src/paper/`) tatsächlich reichen.
7. **Bekannte Lücken der Doku:** `docs/tim_v4_developer_manual/IMPLEMENTATION_GAP.md`
   und `docs/tim_v4_developer_manual/VERIFICATION_REPORT.md`.

Weitere lesenswerte Dateien: `docs/research_lab/EXTERNAL_DATA.md` (Makrodaten,
V1.1), `docs/autonomous_trader/STRATEGY_READINESS_MATRIX.md`,
`docs/autonomous_trader/LIVE_EXECUTION_RISK_REGISTER.md`, `CHANGELOG.md`, `git log`.

## 6. Was deine Antwort enthalten muss

Schreib auf Deutsch, in klaren, kurzen Sätzen, höchstens 3.000 Wörter plus Tabellen.
Gliedere genau so:

1. **Kurzurteil** (höchstens 5 Sätze): Wie weit ist TIM heute von „profitabel“
   entfernt (K1 und K5 zuerst), wie weit von Uzis Vision, und was ist der eine
   größte Engpass? Gib eine Einordnung auf der Stufenleiter L0 bis L6 an, mit Beleg.
2. **Die Vision, strukturiert.** Eine Tabelle mit V1 bis V5. Je Teil: eine prüfbare
   Definition („erfüllt, wenn …“), der heutige Stand mit Beleg, und der Abstand in
   einem Satz. Darunter die Reibungen zwischen den Teilen und mit „profitabel“
   (Abschnitt 3.1) und wie du sie auflösen würdest. Uzi soll diese Tabelle als
   seine erste strukturierte Fassung der Vision übernehmen können.
3. **Lückenliste** als Tabelle. Je Lücke eine Zeile mit:
   - Visionsteil: V1 bis V5, oder „Profitabilität“, wenn die Lücke keinen
     Visionsteil betrifft;
   - Bereich: Edge/Strategie, Daten, Validierung/Statistik, Kosten und Ausführung,
     Risiko und Kapital, Betrieb und Infrastruktur, Governance und Prozess,
     Mensch (Zeit, Wissen, Entscheidungen);
   - Ist-Zustand mit Belegkennung(en) aus dem Belegprotokoll;
   - warum genau diese Lücke Profitabilität verhindert oder gefährdet;
   - Schwere: BLOCKIEREND (ohne das gibt es keinen profitablen Bot),
     WICHTIG (schmälert oder gefährdet den Gewinn), SPÄTER (erst nach einem Vorteil
     relevant);
   - Belegstatus: BELEGT, ABGELEITET oder UNVERIFIED;
   - grober Aufwand und Abhängigkeiten.
4. **Was nicht fehlt.** Was ist schon gut genug oder überbaut und sollte jetzt
   keine Zeit mehr bekommen? Mit Begründung.
5. **Kritischer Pfad** zum ersten Setup, das K1 und K5 erfüllt, danach zum ersten
   von Uzi bestätigten Micro-Live-Trade, danach zu einem Betrieb, in dem TIM sich
   nach V2 bis V4 selbst repariert, entwickelt und steuert. Sag, was davon parallel
   laufen kann und was warten muss, bis ein Vorteil belegt ist. Nummerierte
   Schritte in Reihenfolge. Je Schritt ein prüfbares Abnahmekriterium und ein
   Abbruchkriterium.
6. **Die nächsten 30 Tage:** höchstens fünf konkrete Arbeitspakete, so beschrieben,
   dass man sie direkt als Aufgabe an einen Coding-Agenten geben kann: Ziel,
   betroffene Dateien oder Module, Prüfbefehl, Ergebnis.
7. **Wann aufhören:** Welches Ergebnis würde zeigen, dass die Vision in dieser Form
   nicht trägt, und was wäre dann die ehrliche Alternative?
8. **Annahmen und offene Fragen an Uzi:** Was du nicht klären konntest und was er
   entscheiden muss.
9. **Belegprotokoll.** Nummerierte Liste aller Belege, auf die sich die Antwort
   stützt. Je Beleg eine Kennung (B1, B2, …), und genau eins von beidem:
   - Datei: `pfad:zeile` oder `pfad:von-bis` und das wörtliche Zitat der
     entscheidenden Stelle (höchstens zwei Zeilen);
   - Befehl: der exakte Befehl, so dass ihn jeder wiederholen kann, und die
     entscheidende Ausgabe wörtlich (höchstens drei Zeilen).
   In den Abschnitten 1 bis 8 verweist jede Tatsachenaussage über TIM auf eine
   Kennung, zum Beispiel „(B7)“. Das Belegprotokoll zählt nicht zur Wortgrenze.

## 7. Regeln für die Antwort

Uzi will am Ende eine **bewiesene Analyse**, keine Meinung. Daraus folgen diese
Regeln, und sie gehen allen anderen vor:

- **Jede Tatsache hat einen Beleg im Belegprotokoll.** Eine Aussage über TIM ohne
  Kennung (B…) gilt als nicht gemacht.
- **Drei Stufen, streng getrennt:**
  - BELEGT: du hast die Stelle selbst gelesen oder den Befehl selbst ausgeführt,
    und der Beleg zeigt es direkt.
  - ABGELEITET: folgt aus mehreren Belegen. Nenne die Kette, zum Beispiel
    „B3 + B9 ⇒ …“.
  - UNVERIFIED: du konntest es nicht prüfen. Sag, welcher Befehl oder welche Datei
    es klären würde.
- **Das Kurzurteil und jede Einstufung BLOCKIEREND stützen sich nur auf BELEGT oder
  ABGELEITET.** Hängt ein Urteil an etwas UNVERIFIED, sag das im selben Satz.
- **Zahlen selbst nachrechnen.** Übernimm keine Zahl aus einem Bericht, ohne sie zu
  prüfen, wo das möglich ist. Beispiel: Zähle die Status in
  `docs/research_lab/REGISTER.jsonl` mit einem Befehl, statt die Zahl aus Abschnitt 5
  abzuschreiben. Weicht deine Zählung ab, gilt deine Zählung, und du nennst die
  Abweichung.
- **Code schlägt Dokument.** Ein Dokument belegt nur, was im Dokument steht. Dass
  etwas im Code existiert oder funktioniert, belegt nur der Code selbst oder ein
  Test, den du ausgeführt hast.
- **Keine Belege erfinden.** Zitiere nur, was wörtlich dasteht, mit der richtigen
  Zeilennummer. Ein falscher Beleg wiegt schwerer als ein fehlender.
- **Keine erfundenen Zahlen.** Keine geschätzten Renditen, Trefferquoten oder
  Gewinnchancen ohne Datengrundlage. Wenn du schätzt, sag, worauf die Schätzung
  beruht.
- **Kein Gewinnversprechen und keine Anlageberatung.** Keine Empfehlung für Hebel,
  Positionsgrößen oder Einsätze mit echtem Geld über das hinaus, was in TIMs eigenen
  Dokumenten als Forschungskonvention steht.
- **Die Regeln des Protokolls gelten.** Schlag nichts vor, was
  `docs/research_lab/PROTOKOLL.md` bricht (zum Beispiel Holdout-Daten vorab ansehen, verworfene Varianten
  umparametrieren, die Obergrenze von 60 Varianten umgehen). Wenn du eine Änderung
  am Protokoll für nötig hältst, sag es offen und nenne den Preis.
- **Keine neuen Anforderungen erfinden.** Halte dich an Uzis Vision: zuerst seine
  Worte aus Abschnitt 1, dann die Dokumente aus Abschnitt 3.3. Wo sie unklar oder
  widersprüchlich ist, benenne das als offene Frage.
- **Konkret statt allgemein.** „Mehr Daten sammeln“ oder „Strategie verbessern“
  reicht nicht. Sag welche Daten, woher, wofür, und woran man merkt, dass es
  geklappt hat.
- **Keine Zugangsdaten.** Schreib keine Schlüssel, Tokens oder Passwörter in die
  Antwort, auch nicht als Beispiel.
