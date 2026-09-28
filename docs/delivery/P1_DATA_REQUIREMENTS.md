# P1 — verbindliche Datenanforderungen

Quelle: docs/mission07_research_intelligence.md und docs/mission08_verified_expansion.md, abgeglichen am 2026-09-10T04:53:43.947409+00:00. Bestehende Schwellen bleiben unverändert; sie sind Forschungsregeln, kein Rentabilitätsnachweis.

| Bereich | Verbindliche Bedingung | Noch fehlender Nachweis |
|---|---|---|
| SHORT | 60 konsekutive Minuten, zwei volle UTC-Stunden, vollständiges 60-Minuten-Profil | Kontinuierliche Kampagne; vorhandene dokumentierte Segmente umfassen nur acht vollständige Minuten |
| MID | 168 Stunden, 10080 Minuten, 4h/Daily-Kontext und Profil | Durchgehende verifizierte Historie |
| LONG | 90 Tage, Weekly und zwei volle Kalendermonate, 129600 Minuten | Historie und eigenständige Monatsabdeckung |
| Zusätzliche Evidenz | valide Quotes/Orderbuch, OI/Funding/Liquidationen, Spot-vs-Perp, längerfristige Nachfrage | Dokumentierte fehlende Quellen bleiben MISSING, keine Ersatzwerte |
| Betriebsfreigabe | aktuelle Sicherung, geladene Revision/Schema, Integrität und frische Verarbeitung | Synthetischer Restore ersetzt keinen Produktionsnachweis |

Die bisherige Journalgrenze beträgt 300 Sekunden/10000 Events je Segment. Wiederholte Verbindungen beweisen keine Kontinuität. Der nächste Implementierungsschritt ist eine getrennte, begrenzte Kampagnensteuerung: ein Socket, geordnete Segmente, durchgehende Receipt-/Trade-ID-Kette, Gesamtzeit-/Eventlimit, Ressourcenprüfung und fail-closed Abbruch. Vor Netzwerkbetrieb sind künstliche Grenzfalltests erforderlich. Keine Aktivierung in diesem Audit.

Eine gültige Historienübernahme kann Wartezeit verkürzen, benötigt aber belegte Herkunft, Vollständigkeit und zeitliche Verfügbarkeit. 90 Tage Live-Sammeln sind nicht automatisch notwendig; vorhandene Altbestände sind ebenso wenig automatisch ausreichend. Der neue Kampagnenadapter darf die stabilen Journal-/Queue-/Recovery-Regeln nicht verändern.
