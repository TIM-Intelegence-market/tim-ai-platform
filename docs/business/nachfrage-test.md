# Nachfrage-Test: nachprüfbare Research-Belege für Coaches und Signal-Anbieter

Paket 0 aus dem Beirat-Plan (28.09.2026). Ziel: in 48 Stunden prüfen, ob die riskanteste
Annahme stimmt, bevor weitere Funktionen gebaut werden.

**Annahme:** Trading-Coaches und Betreiber von Signal- oder Research-Kanälen zahlen für einen
Beleg, mit dem ihre Follower prüfen können, dass eine Marktanalyse zu einem bestimmten
Zeitpunkt so vorlag.

## Vorbereitung

1. Einen echten, abgeschlossenen Research-Fall auswählen (Dashboard → Research Cases).
2. Beleg erzeugen, während TIM läuft:
   ```bash
   python3 scripts/export_case.py <case_id> --out exports/
   python3 scripts/verify_case.py exports/<case_id>.json   # muss "OK" melden
   ```
3. `exports/<case_id>.html` auf einem statischen Host ablegen (z. B. GitHub Pages, Netlify)
   und den Link einmal im Browser öffnen: oben muss „✓ Inhalt stimmt mit dem Hash überein" stehen.
4. Den Output-Hash zusätzlich mit Datum öffentlich posten (z. B. auf X). Erst diese frühe
   Veröffentlichung macht den Zeitpunkt nachweisbar; der Hash allein beweist nur, dass der
   Inhalt nicht verändert wurde.

## Nachricht (Vorlage, anpassen)

> Hi <Name>, du teilst regelmäßig BTC-Analysen mit deiner Community. Ich habe ein Werkzeug gebaut,
> mit dem jede Analyse einen prüfbaren Beleg bekommt: Zeitstempel, verwendete Daten und ein
> Fingerabdruck (Hash), den jeder nachrechnen kann. Beispiel: <Link>. Damit können deine Follower
> sehen, dass deine Einschätzung vorher so dastand, und nicht erst im Nachhinein.
> Ich suche zwei Pilotpartner für 300 € im Monat, erster Monat mit Geld-zurück-Garantie.
> Hast du 15 Minuten für ein kurzes Gespräch?

Keine Gewinnversprechen, keine Aussagen zu künftigen Kursen.

## Wen anschreiben (10 Kontakte)

Trading-Coaches mit eigener Community, Betreiber von Signal- oder Research-Kanälen
(Telegram, Discord, X, YouTube), kleine Research-Newsletter. Kriterium: veröffentlicht
regelmäßig BTC-Einschätzungen und verdient daran Geld.

## Protokoll

| # | Datum | Kontakt (Kanal, Größe) | Antwort ja/nein | Gespräch | Einwand wörtlich | Pilot-Zusage | Preis genannt |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |
| 6 | | | | | | | |
| 7 | | | | | | | |
| 8 | | | | | | | |
| 9 | | | | | | | |
| 10 | | | | | | | |

Keine privaten Kontaktdaten in dieses Repository schreiben, nur Kanalname und Größe.

## Auswertung

- **Bestanden:** mindestens 2 Gespräche und mindestens 1 Pilot-Zusage → Paket 2 (Rückblick im
  Marktgedächtnis) und Paket 3 (Monatsbericht für Piloten) bauen.
- **Durchgefallen:** 0 Antworten → Botschaft oder Käufergruppe ändern, nichts weiter bauen.
- **Dazwischen:** Einwände auswerten und die Nachricht einmal überarbeiten, dann 10 weitere Kontakte.

Danach den Beirat mit den echten Zahlen erneut einberufen.
