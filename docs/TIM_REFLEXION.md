# TIM-Reflexion (wöchentlich, nur lesend)

Stand 21.10.2026. Bauplan: Claude Doc "Bauplan Reflexionsschleife TIM" (Thread "Wissen und Selbstverbesserung in TIM").

## Was sie tut

Die Reflexion liest die nachgeprüften Orderflow-Beobachtungen einer ISO-Woche
(`orderflow_observations` + `orderflow_validations`, nur `complete`, Ergebnis bis Wochenende bekannt)
und misst jede Beobachtungsart gegen die Basisrate der übrigen Arten derselben Woche.
Ergebnis ist ein Bericht (Markdown + JSON) mit höchstens einem Vorschlag.

- Die Beobachtungen selbst haben keine Richtung. Die Reflexion nutzt eine feste Lesart
  (`READING` in `src/reflection/scorecard.py`, Version 1.0.0): Käufer-Arten = Kurs steigt,
  Verkäufer-Arten = Kurs fällt, Aktivitäts-Arten = Kurs bewegt sich.
- Statistik: exakter einseitiger Binomialtest je Art und Richtung, Holm-Korrektur über alle
  16 möglichen Tests (`src/research_lab/stats/inference.py`), 95-%-Wilson-Band, Test erst ab 30 Fällen.
- Fälle einer Woche überlappen sich; p-Werte sind deshalb eher zu günstig. Ein Vorschlag öffnet nur
  eine Frage für das Research Lab, er entscheidet nichts.

## Was sie nie tut

- Keine Regel, kein Score, keine Order ändert sich. `automatic_rule_change` ist immer `false`.
- Kein Schreiben in die Datenbank: Die Verbindung setzt `default_transaction_read_only=on`,
  PostgreSQL weist jeden Schreibversuch ab (Test `tests/test_reflection_reader.py`).
- Schreibt nur in den Ordner `--out`.

## Befehle

```bash
# Probelauf auf den synthetischen Testdaten (keine Marktdaten)
python -m src.reflection.cli --week 2026-W48 --input tests/fixtures/reflection/export.json --check

# Bericht aus der Datenbank, letzte volle Woche
python -m src.reflection.cli --week last --database --out reports/reflection
```

## Weg eines Vorschlags

1. Uzi prüft den Bericht.
2. Angenommen: Hypothese im Research Lab auf der Binance-Historie testen (Training und Validierung,
   Holdout nur mit Uzis Wort).
3. Besteht sie: neue Regelversion per PR. Die Datenbank erlaubt heute nur `rule_version = '1.0.0'`;
   die Schema-Änderung kommt erst nach Kampagnenende.

## Zeitplan (P4, noch nicht installiert)

Ein wöchentlicher launchd-Job auf dem Mac kommt erst nach Ende der V2-Qualifizierung
(frühestens 23.11.2026 20:34 UTC) und nie in `~/TIM-live` während einer Kampagne.
