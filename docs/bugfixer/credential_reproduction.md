# Credential-Defekt: Nachweis und nächster sicherer Fix

`reproduce_known_case('KEYCHAIN_ARGV_EXPOSURE_V1')` extrahiert die bekannte
Quellfunktion `store_keychain` aus dem aktuellen Quelltext, validiert deren AST
gegen eine enge Liste und führt sie mit einem simulierten Prozessadapter aus.
Kein generischer Python-Sandbox, keine beliebigen Scripts oder Fallnamen.

Beobachtung: Das künstliche Testsecret ist im Argumentvektor. Ergebnis und
Quellhash stehen in `work/mission09_1/known_defect_reproduction.json`.
Die gespeicherte Ausgabe enthält weder das Testsecret noch den Argumentvektor.

Der bestehende Test erwartet `security ... -w` und genau eine stdin-Zeile.
Diese Annahme genügt nicht als Implementierungsbeweis: Die lokale
`security help add-generic-password`-Ausgabe empfiehlt das abschließende `-w`
zum Prompten. Apples veröffentlichte Implementierung verwendet jedoch in
`promptForPasswordData` zwei `getpass`-Aufrufe (Eingabe und Wiederholung).
Ein bloßes Entfernen des Passwortarguments mit einer stdin-Zeile wäre daher
kein belastbar verifizierter Ersatz.

Primärquelle, eingesehen am 9. September 2026:
[Apple SecurityTool: keychain_add.c](https://github.com/apple-oss-distributions/Security/blob/main/SecurityTool/macOS/keychain_add.c)
(`promptForPasswordData`, `keychain_add_generic_password`).

Nächster Fix benötigt einen eindeutig definierten geheimnisfreien
Prozessargumentvertrag und einen getesteten Adapter (gegebenenfalls native
Keychain-Schnittstelle in einem separaten Helper mit stdin-Datenvertrag).
Bisher keine echte Credential-Operation und keine Änderung dieses Helpers.
Ein korrigierter Mock muss die Sicherheit verschärfen und zum tatsächlichen
Adapter passen; kein Test darf nur zum Erreichen von PASS abgeschwächt werden.
