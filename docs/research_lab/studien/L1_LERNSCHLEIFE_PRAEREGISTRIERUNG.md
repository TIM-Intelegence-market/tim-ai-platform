# L1: Lernschleife Champion/Herausforderer für die Orderflow-KI – Präregistrierung

**Status: ENTWURF 0.1, Familie noch nicht im Lernregister eingetragen.** Keine Auswertung, keine Ergebnisse.
Grundlage: Bauplan „TIM lernt aktiv aus seinen Trades“ (30.10.2026), Uzis „go“ am 31.10.2026 14:03 Ortszeit
mit den Vorschlägen E1–E6. Dieses Dokument legt die Regeln der Lernschleife fest, **bevor** ein Herausforderer
trainiert oder ein Testfenster angesehen wird. Es ändert weder das Protokoll (1.3) noch S8.

## 1. Frage

Wird ein regelmäßig neu trainiertes S8-Modell (gleiche Konfiguration, wachsendes Datenfenster) auf frischen,
vorher ungesehenen Live-Daten besser als der laufende Champion? Gewechselt wird nur bei einem vorab festgelegten
Mindestvorteil mit Sicherheitsabstand. Gemessen wird Prognosegüte, kein Nettoertrag (S8 Abschnitt 1).

## 2. Einordnung

- Eigene prospektive Familie wie S8 (Uzis Karte 26.10.), außerhalb des Holdout-Registers: keine Registerplätze
  (m bleibt 58 von 60), keine Holdout-Erlaubnis, keine Setup-Evidenz.
- Abhängigkeit: S8 P3 (Trainer) und P4 (Prognose-Journal). Ohne sie wird kein Herausforderer angemeldet.
- Der Journal-Lernweg (Plan-Journal → `journal_review` → Ideen) liegt im Forschungsbereich (Paket F1,
  `src/research_lab/workshop/`) und ändert nie selbst eine Regel.

## 3. Daten und Sperren

| Quelle | erlaubt | Durchsetzung |
|---|---|---|
| Archiv 2020-01-01 bis 2024-12-31 (S8-Speicher) | Training | `ModelRegister.register_challenger` |
| Archiv ab 2025-01-01 (Holdout) | **nie** | Abweisung, dazu S8-Sperre vor dem Abruf |
| Live-Daten vor dem prospektiven Start | **nie** (geschlossene Lücke) | Abweisung |
| Live-Daten ab prospektivem Start bis zum Stichtag T | Training | Abweisung, wenn eine Quelle über T reicht |
| Live-Daten im Testfenster | nur Bewertung, genau einmal | eine Bewertung je Herausforderer |

Purging: Training endet mindestens einen Horizont (5 Minuten) vor dem Testfenster. Live-Merkmale werden aus dem
gebildet, was zur Minute angekommen war (S8 P4), nicht aus nachgeladenen Archiven.

## 4. Feste Regeln der Familie `S8-L1`

| Regel | Wert | Herkunft |
|---|---|---|
| `config_id` | die eine registrierte S8-Konfiguration (S8 Abschnitt 6) | Modellart und Einstellungen ändern sich nie automatisch |
| Rhythmus | höchstens 1 Herausforderer je ISO-Woche, 12 je Quartal; jeder angemeldete zählt | E1, E5 |
| Testfenster | mindestens 14 Tage und 10 000 gültige Prognoseminuten; darunter `NO_VERDICT` | E3 |
| Messgröße | Log-Loss-Differenz Champion − Herausforderer auf denselben Minuten | S8 Primärmetrik |
| Intervall | Block-Bootstrap über Tage, zweiseitig 99,5 % (einseitig 0,25 %; über 12 Versuche je Quartal ≤ 3 %, Bonferroni) | Mehrfachtest |
| kleinster Effekt | **offen**, wird vor dem prospektiven Start aus der Streuung der Trainingsdaten vorgeschlagen und per Karte festgelegt | E4 |
| Qualität | Fenster mit Datenlücken über der S8-Grenze → `NO_VERDICT`, nie still „neutral“ | S8 Abschnitt 1 |
| Kalibrierung | Kalibrierung und Güte je Klasse nicht schlechter als Toleranz (Wert mit dem kleinsten Effekt) | Bauplan 5.4 |
| Erster Champion | Klassen-Basisrate aus dem Training | S8 Referenz |
| Wechsel | nur Urteil `ELIGIBLE` **und** Uzis OK per Karte; nur Papier | E2 |
| Rückfall | automatisch erlaubt, nur zu einem Champion von vor dem letzten Wechsel | Bauplan 5.8 |
| Stopp | Vorschlag: nach 4 Quartalen ohne Wechsel Bericht an Uzi, Schleife ruht bis zu seiner Entscheidung | wird mit 1.0 bestätigt |

Das Urteil rechnet das Register selbst aus den gemeldeten Zahlen (`ModelRegister.verdict`), es wird nicht
übergeben. Eine andere Konfiguration, ein anderer Horizont oder andere Merkmale sind eine **neue Familie** und
damit eine neue Registrierung.

## 5. Lernregister (Paket L1, gebaut)

`src/research_lab/learning/registry.py`, Tests `tests/test_learning_registry.py`. Append-only JSON-Lines mit
derselben Hash-Kette wie `REGISTER.jsonl`. Ereignisse: `family` (Regeln, einmalig), `baseline` (erster Champion),
`challenger` (Anmeldung vor dem Testfenster mit Stichtag, Datenquellen, Code-Commit, Merkmals-, Label-, Daten- und
Modell-Hash), `evaluation` (einmal, nach Fensterende), `promotion` (mit Namen der Freigabe), `rollback`.
Weitere Sperren (nach der adversarialen Prüfung vom 31.10. ergänzt):

- Jeder Eintrag trägt die echte Uhrzeit (Toleranz 15 Minuten) und darf nicht vor dem letzten liegen: Ein
  Herausforderer lässt sich weder nachträglich für ein schon gesehenes Fenster anmelden noch vordatieren.
- Alle Zahlen müssen endlich sein (NaN oder unendlich besteht keine Prüfung); das Intervall muss den Schätzwert
  enthalten; gemeldete Tage dürfen das registrierte Fenster nicht übersteigen.
- Das Budget zählt je Konfiguration über alle Familien; eine zweite Familie mit derselben Konfiguration umgeht es nicht.
- Modell-Ids sind im ganzen Register eindeutig. Wechsel nur mit einem in der Familie eingetragenen Freigebenden
  (`approvers`, Vorschlag: nur Uzi).
- Rückfall nur streng rückwärts: zu einem Champion, der vor dem ersten Antritt des aktuellen galt. Ein so
  abgesetztes Modell kommt auf diesem Weg nicht zurück (kein Hin und Her ohne Freigabe).
- Herausforderer, deren Fenster ohne Bewertung abgelaufen ist, werden als „überfällig“ angezeigt.
- Grenze: Abgeschnittene Zeilen am Dateiende hinterlassen eine gültige Kette. Deshalb liegt das Register in Git,
  und jeder Bericht nennt den Kopf-Hash (`head`). Die Angabe „Archiv“ oder „Live“ einer Datenquelle ist eine
  Meldung des Trainers; geprüft wird sie über den Daten-Hash im S8-Split-Manifest.

Lesen: `python -m src.research_lab.learning status --register <Datei>` (Kette, Zustand, Kopf-Hash, überfällige).

Der Ort der Registerdatei (Vorschlag `docs/research_lab/LERNREGISTER.jsonl`, in Git wie das Hypothesenregister)
wird mit Version 1.0 festgelegt; vorher wird nichts eingetragen.

## 6. Offen bis Version 1.0

1. Kleinster Effekt und Kalibrierungstoleranz (E4).
2. Prospektiver Starttermin (frühestens, wenn S8 P3/P4 laufen).
3. ~~Einordnungssatz im Protokoll-Änderungsprotokoll~~ erledigt am 31.10. (Protokoll 1.3, Eintrag „Lernschleife L1“).

## Änderungsprotokoll

| Datum | Version | Änderung | Bis dahin gesehene Daten |
|---|---|---|---|
| 2026-10-31 | 0.1 | Entwurf: Frage, Einordnung, Sperren, feste Regeln (E1–E3, E5, E6), Lernregister L1 | keine; nur synthetische Testdaten |
| 2026-10-31 | 0.1 | Einordnung im Protokoll-Änderungsprotokoll eingetragen (keine Regeländerung) | unverändert |
