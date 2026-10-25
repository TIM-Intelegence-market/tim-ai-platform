# Zeitangabe der Startfreigabe prüfen

`scripts/v2_qualification_start.py` verlangt für `--approved-at` einen
tatsächlich parsebaren, zeitzonenbewussten UTC-Zeitstempel mit abschließendem
`Z`. Ein einzelnes `Z`, ein unmögliches Kalenderdatum oder eine ungültige
Uhrzeit werden schon bei der Argumentprüfung abgelehnt. Sekundenbruchteile
sind erlaubt; die originale gültige Zeichenfolge bleibt im Freigabebeleg
erhalten.

Die Freigabezeit darf außerdem nicht nach der beim Startbefehl gemessenen
aktuellen UTC-Zeit liegen. Dieser Vergleich erfolgt vor Checkout-Prüfung,
Startbericht, Baseline und Dateiausgabe. Bei fehlerhafter lokaler Uhr ist
zuerst die Uhr zu prüfen, nicht die Freigabe rückzudatieren.

Die Änderung validiert die dokumentierte Zeitangabe. Sie authentifiziert
weder die angegebene Person noch den Entscheidungsverweis und ersetzt keine
tatsächlich erteilte menschliche Freigabe. Es wird keine zusätzliche
Altersgrenze für Freigaben eingeführt. Die bestehende Frischeprüfung der
Start-Gates und die weiteren Startbedingungen gelten unverändert.
Der tatsächliche Kampagnenstart bleibt die nächste volle Minute nach dem
expliziten Startbefehl; bestehende Kampagnen werden nicht geändert.
