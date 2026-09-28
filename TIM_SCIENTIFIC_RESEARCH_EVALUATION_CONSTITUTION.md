# TIM Constitution Band 8 — Scientific Research & Evaluation

Version: **TIM Constitution Band 8**
Status: **Authoritative Scientific Research Constitution**

Dieses Dokument definiert die verbindlichen Regeln für wissenschaftliche
Forschung, Experimente, Hypothesen, Evidenz, Evaluation, Reproduzierbarkeit,
Validierung, Publikation und statistische Auswertung im TIM-Ökosystem.

TIM entwickelt keine Meinungen. TIM entwickelt reproduzierbares Wissen.

Band 8 besitzt verbindlichen Constitution-Status. Für die Konfliktauflösung
gilt die etablierte Reihenfolge:

1. TIM Constitution Band 1
2. TIM Constitution Band 2
3. TIM Constitution Band 3
4. TIM Constitution Band 4
5. TIM Constitution Band 5
6. TIM Constitution Band 6
7. TIM Constitution Band 7
8. TIM Constitution Band 8
9. Master Prompts
10. Implementierung

## Mission

Wissenschaftliche Forschung in TIM dient nicht der Bestätigung bestehender
Meinungen. Sie prüft objektiv, ob eine Hypothese durch Evidenz gestützt wird.
Jede Forschungsarbeit muss objektiv, reproduzierbar, nachvollziehbar,
auditierbar und falsifizierbar sein.

## Scientific Method

Jede Forschungsarbeit folgt exakt diesem Ablauf:

1. Observation
2. Question
3. Hypothesis
4. Experiment Design
5. Dataset Selection
6. Research Execution
7. Evidence Collection
8. Statistical Evaluation
9. Peer Review
10. Acceptance
11. Publication

Keine Phase darf übersprungen werden. Nicht anwendbare Schritte müssen
begründet und sichtbar dokumentiert werden; sie dürfen nicht stillschweigend
als bestanden gelten.

## Observations

Eine Observation ist eine neutrale Feststellung, keine Interpretation und
keine Strategie. Sie besitzt:

- Observation ID;
- Timestamp;
- Dataset;
- Quelle;
- Beschreibung;
- Confidence;
- Version;
- Hash;
- Lineage.

## Questions

Jede Research Session beginnt mit einer klaren, begrenzten und beantwortbaren
Frage. Unscharfe Fragestellungen sind unzulässig.

## Hypotheses

Jede Hypothese muss messbar, widerlegbar und eindeutig sein. Aussagen wie
„Feature X ist gut“ sind ungültig. Eine gültige Hypothese benennt eine messbare
Kennzahl und die Bedingungen, unter denen eine Veränderung erwartet wird.

## Experiment Design

Vor jedem Experiment werden mindestens dokumentiert:

- Ziel;
- Hypothese;
- Dataset;
- Dataset-Version;
- Zeitraum;
- Methodik;
- Features;
- Metriken;
- Akzeptanzkriterien;
- Abbruchkriterien;
- Randomisierung, falls relevant.

## Dataset Rules

Es dürfen ausschließlich registrierte Datasets verwendet werden.
Dataset-Version und Dataset-Hash müssen dokumentiert werden. Stille
Datasetänderungen sind verboten.

## Features

Alle verwendeten Features müssen versioniert, registriert, dokumentiert und
reproduzierbar sein. Feature Engineering ist Teil des Experiments und muss in
dessen Provenienz abgebildet werden.

## Evidence

Jede Evidence besitzt:

- Evidence ID;
- Quelle;
- Hash;
- Confidence;
- Lineage;
- Version;
- Beschreibung.

Keine Behauptung ist ohne zugeordnete Evidence zulässig.

## Confidence

Confidence beschreibt die Belastbarkeit einer Aussage und ist keine
Wahrscheinlichkeit. Sie berücksichtigt mindestens:

- Datenqualität;
- Anzahl der Experimente;
- Reproduzierbarkeit;
- Konsistenz;
- Peer Review;
- methodische Qualität.

## Reproducibility

Ein Experiment muss vollständig reproduzierbar sein. Dafür werden mindestens
festgehalten:

- Dataset und Version;
- Features und Versionen;
- Parameter;
- Code;
- Commit;
- Branch;
- Schemas;
- Konfiguration;
- Seeds, falls verwendet.

## Statistics

Statistische Aussagen dokumentieren mindestens:

- Stichprobengröße;
- Mittelwert;
- Median;
- Standardabweichung;
- Varianz;
- Konfidenzintervall, falls relevant;
- Effektgröße, falls relevant;
- Annahmen und Einschränkungen.

Irreführende Darstellungen statistischer Ergebnisse sind verboten.

## Validation

Validierung umfasst, soweit methodisch anwendbar:

- Replay;
- Cross Validation;
- Walk Forward;
- Out-of-Sample Tests;
- Regression;
- Robustheitsanalyse;
- Sensitivitätsanalyse.

Jede nicht anwendbare Methode wird begründet dokumentiert.

## Peer Review

Vor Veröffentlichung wird jede Forschungsarbeit geprüft. Der Review umfasst:

- Methodik;
- Code;
- Daten;
- Statistik;
- Interpretation;
- Dokumentation;
- Reproduzierbarkeit.

## Interpretation

Interpretationen müssen klar von Beobachtungen getrennt werden:

| Ebene | Bedeutung |
|---|---|
| Observation | neutrale Feststellung |
| Fact | evidenzgestützte, validierte Aussage |
| Interpretation | Modell oder Deutung |
| Hypothesis | testbare Behauptung |

Diese Ebenen dürfen niemals vermischt werden.

## Publication

Eine veröffentlichte Research-Arbeit enthält mindestens:

- Titel;
- Abstract;
- Fragestellung;
- Hypothese;
- Methodik;
- Datasets und Versionen;
- Feature-Versionen;
- Ergebnisse;
- Statistik;
- Limitationen;
- Confidence;
- Reproduzierbarkeitsnachweis;
- Review-Status.

## Negative Results

Negative Ergebnisse werden dokumentiert. Nicht bestätigte oder widerlegte
Hypothesen werden nicht gelöscht; sie sind Teil des wissenschaftlichen Wissens.

## Bias

Research prüft aktiv auf:

- Selection Bias;
- Confirmation Bias;
- Look-Ahead Bias;
- Survivorship Bias;
- Data Leakage;
- Overfitting;
- Informationsleckagen.

Erkannte oder nicht ausschließbare Verzerrungen werden dokumentiert.

## Research Ethics

Research verfolgt keine gewünschten, sondern korrekte Ergebnisse. Eine
widerlegte Hypothese ist ein wissenschaftlicher Erfolg.

## Knowledge Transition

Bestätigte Forschung geht in die Knowledge Platform über, niemals direkt in
Strategy oder Decision. Zwischen Forschung und Anwendung liegt immer eine
dokumentierte Validierungsphase.

## Definition of Done

Eine Forschungsarbeit ist nur abgeschlossen, wenn:

- Fragestellung dokumentiert;
- Hypothese dokumentiert;
- Experiment dokumentiert;
- Dataset referenziert und versioniert;
- Features versioniert;
- Evidence vollständig;
- Statistik vollständig;
- Replay erfolgreich;
- Review bestanden;
- Dokumentation vollständig;
- Veröffentlichung erstellt.

## Closing

Band 8 definiert den wissenschaftlichen Standard des gesamten TIM-Ökosystems.
Keine Strategie, kein Feature, keine Entscheidung, kein Modell und keine
KI-Komponente darf wissenschaftliche Aussagen treffen, ohne diesem Dokument zu
entsprechen.

TIM entwickelt keine Meinungen. TIM entwickelt reproduzierbares Wissen.
