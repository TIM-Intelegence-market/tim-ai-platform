# Snapshot-Zeit im Tagesbeleg erhalten

Der Health-Produzent `scripts/tim_server_health.py` schreibt den Zeitpunkt
seiner Prüfung unter `timestamp`. Der Tagescollector übernahm bislang nur
`generated_at_utc`; dadurch ging die vorhandene Snapshot-Zeit verloren.

`daily_metrics` erhält jetzt eine vorhandene `generated_at_utc` unverändert.
Ist sie nicht vorhanden oder `None`, wird `timestamp` aus demselben Health-
Objekt übernommen. Fehlen beide, bleibt die Zeit unbekannt (`None`). Es wird
weder die aktuelle Uhrzeit noch die Tagesgrenze als Ersatz eingesetzt.
Status, Modus und Aktionszähler sowie das Eingabeobjekt bleiben unverändert.

Das ist eine Feldzuordnung, keine neue Format-/Frischeprüfung, Signatur oder
Rückrechnung. Die Zeit bezeichnet den gelieferten Health-Snapshot, auch wenn
er nach dem ausgewerteten UTC-Tag erzeugt wurde. Sie beweist keine lückenlose
Überwachung des gesamten Tages und macht einen roten Status nicht grün.

Bereits geschriebene Tagesmanifeste werden weder ergänzt noch neu gehasht.
Der eingefrorene Live-Checkout und seine Kampagne werden durch diesen PR
nicht geändert. Eine spätere Installation muss die bestehenden Freeze- und
Kampagnenregeln beachten; Merge ist kein Rollout.
