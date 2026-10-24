# Tagesbelege an den geladenen Kampagneninhalt binden

Der tägliche Collector prüft bei einer aktiven Kampagne den gespeicherten
`preregistration_hash` gegen den vollständigen geladenen Kampagneninhalt, bevor
er Daten sammelt oder Tagesdateien schreibt. Auch direkte Aufrufe von
`build_daily_manifest` führen diese Prüfung durch. Fehlt der Hash oder stimmt
er nicht, wird der Lauf mit einem Fehler abgebrochen.

Verwendet wird das bestehende Format aus `activate_campaign`: SHA256 über
sortiertes kompaktes JSON ohne das Feld `preregistration_hash`. Die Prüfung
bindet damit auch verschachtelte Regeln, Startzeit, Software- und
Konfigurationsstand sowie die vor der Aktivierung angefügten Approval- und
Startbericht-Metadaten. Korrekt erzeugte aktive Kampagnen brauchen keine
Migration. Die Prüfung verändert weder Kampagnen noch bestehende Tagesbelege
und berechnet keinen Ersatzhash für inkonsistente Dateien.

Ein Fehler ist ein Anlass, das Original und seine Herkunft zu prüfen. Ein
nachträglich neu berechneter Hash ist keine Reparatur einer Freigabe. Der
Hash beweist Inhaltskonsistenz, keine Identität, Signatur, unabhängige
Freigabe oder Übereinstimmung mit der laufenden Prozesskonfiguration.
Eine absichtlich geänderte und neu gehashte Datei wird damit nicht erkannt.
Kampagnenstart, Qualifikationsregeln, Runtime-Zähler und die Bewertung der
Tagesmetriken werden durch diese Änderung nicht verändert.

Die Regressionstests verändern einzelne und verschachtelte Kampagnenfelder,
prüfen fehlende/falsche Hashwerte und verhindern Datensammlung und Dateiausgabe
bei einer inkonsistenten aktiven Kampagne. Ein unveränderter JSON-Roundtrip
einer mit Approval-Metadaten erzeugten Kampagne bleibt gültig.
