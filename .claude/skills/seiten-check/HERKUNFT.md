# Herkunft der Pruefliste

Gebaut am 09.09.2026. Jede Pruefung sitzt auf einer Quelle, nicht auf einem
Bauchgefuehl. Wer eine Pruefung aendern will, prueft vorher hier, worauf sie
sitzt.

## Warum es diesen Skill gibt

Bestehende Werkzeuge decken jeweils eine Haelfte ab:

| Werkzeug | Sterne (09.09.2026) | Deckt ab | Fehlt |
|---|---:|---|---|
| [raroque/vibe-security-skill](https://github.com/raroque/vibe-security-skill) | 1.004 | Quelltext, englisch | die laufende Seite wird nie aufgerufen |
| [usestrix/strix](https://github.com/usestrix/strix) | 61.501 | echter Angriff auf die laufende Seite | braucht Docker und einen kostenpflichtigen Modell-Schluessel |
| [Pantheon-Security/medusa](https://github.com/Pantheon-Security/medusa) | 979 | Lieferketten und Chatverlaeufe | nicht auf Webseiten ausgerichtet |
| [Mozilla Observatory](https://developer.mozilla.org/en-US/observatory) | Dienst | Kopfzeilen, TLS, Cookies | kein Quelltext, keine offen liegenden Dateien |

Dieser Skill misst beides und braucht dafuer nichts ausser Python 3. Kein
Docker, kein zusaetzlicher Schluessel, keine Anmeldung. Das ist der Grund fuer
den Eigenbau, nicht Unzufriedenheit mit den anderen.

Der Aufbau der Quelltext-Pruefung folgt in der Gliederung dem Ansatz von Chris
Raroque (MIT-Lizenz, Aufteilung nach Technik statt nach Schwachstellenklasse,
damit nur geladen wird, was im Projekt wirklich vorkommt). Die Regeln, die
Beispiele und der gesamte Text sind neu geschrieben, auf Deutsch, und um den
Kostendeckel-Block sowie die Datenspuren-Pruefung erweitert.

## Zahlen, auf die sich die Pruefungen berufen

- **Carnegie Mellon, SusVibes-Benchmark:** 61 Prozent der Loesungen eines
  KI-Agenten funktionieren, 10,5 Prozent sind sicher. Ueber 80 Prozent des
  funktionierenden Codes traegt eine Schwachstelle. 200 Aufgaben aus 108
  Open-Source-Projekten, 77 Schwachstellenklassen.
- **Escape.tech, State of Security of Vibe Coded Apps:** 1.400 oeffentlich
  erreichbare, mit KI gebaute Anwendungen gescannt, 2.038 kritische Befunde,
  ueber 400 offen liegende Zugangsschluessel, 175 Faelle mit personenbezogenen
  Daten bis hin zu Bankverbindungen. Alles in laufenden Systemen.
  (Zur Vorsicht: mehrere Sekundaerquellen nennen 5.600 gescannte Anwendungen.
  Auf der Seite des Anbieters steht 1.400. Es gilt die kleinere, belegte Zahl.)
- **Lovable, April 2026:** 48 Tage lang konnte jeder mit einem Gratiskonto
  ueber wenige Aufrufe fremde Projekte, deren Quelltext und deren
  Datenbankzugaenge oeffnen. Gemeldet am 3. Maerz, geschlossen am 20. April.
  Zuerst berichtet von Business Insider.
- **Kopfzeilen-Verbreitung:** eine Erhebung ueber die eine Million
  meistbesuchten Seiten fand bei weniger als 25 Prozent eine brauchbar
  konfigurierte Content-Security-Policy, bei ueber 40 Prozent fehlte HSTS
  vollstaendig.

## Rechtliche Grundlagen der beiden harten Grenzen

- **Nur die eigene Seite:** § 202a StGB (Ausspaehen von Daten) stellt schon das
  Verschaffen des Zugangs zu fremden, besonders gesicherten Daten unter Strafe.
  Auf einen Schaden kommt es nicht an. In den USA greift der Computer Fraud and
  Abuse Act.
- **Keine Rechtsberatung:** das Rechtsdienstleistungsgesetz erlaubt die
  rechtliche Pruefung eines Einzelfalls nur bestimmten Berufsgruppen. Eine
  technische Feststellung ("diese Verbindung entsteht") ist keine
  Rechtsdienstleistung, eine Bewertung ("das ist zulaessig") waere eine.
  Deshalb steht in jedem Bericht, was gemessen wurde, und nie, wie es
  rechtlich zu bewerten ist.

## Erster echter Lauf

09.09.2026 gegen `https://titusharmann.com`: 25 Pruefungen gelaufen, 7 Befunde,
davon 0 kritisch, 2 hoch (HSTS und CSP fehlen), 3 mittel, 2 niedrig. Laufzeit
unter einer Minute.
