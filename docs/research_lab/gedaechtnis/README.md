# TIM-Gedächtnis (G1/G2, Stand 12.11.2026)

Liste der Aussagen, auf die sich TIM stützt, mit Status, Nutzung, Beleg und Code-Stelle. Sie ist Daten und Auswertung:
**Sie ändert keine Regel, kein Journal und keinen Plan.** Änderungen an TIMs Verhalten gibt es nur auf Uzis Wort.

- Daten: `aussagen.jsonl` (eine Aussage je Zeile)
- Auswertung und Prüfung: `python -m src.research_lab.gedaechtnis` (Gruppen), `--gruppe N`, `--pruefen`
- Test: `tests/test_research_lab_gedaechtnis.py` prüft Schema, doppelte Nummern und dass jeder Code-Pfad existiert

## Felder

| Feld | Bedeutung |
|---|---|
| status | `belegt` (Studie bestanden oder Messung), `hinweis` (Richtung stimmt, Test knapp oder einzeln), `ungeprueft` (keine Rechnung oder nicht testbar), `widerlegt` (nicht bestanden oder Richtung verkehrt; vorläufig bei einem Test) |
| nutzung | `entscheidet` (ändert Plan oder lässt ihn weg), `papier` (Regel der Papier-Journale), `schatten`, `anzeige`, `ruhend` (im Code, schreibt aber keine Pläne), `vorschlag`, `unklar`, `keine` |
| beleg | Studie, Bericht oder Messung mit Zahl. Berichte, die nicht im Repo liegen, sind als solche vermerkt |
| code | Datei und Stelle, an der TIM die Aussage benutzt; `-` bei Aussagen ohne Nutzung; `Mac:` für Code außerhalb des Repos |

## Gruppen

1. Live benutzt und widerlegt
2. Live benutzt, ungeprüft oder nur Hinweis (auch `unklar`)
3. Belegt oder Hinweis, nur Schatten, Anzeige oder ungenutzt
4. Widerlegt, nicht für Entscheidungen genutzt (Negativwissen)
5. Live benutzt und belegt
6. Ungeprüft, nur Schatten, Anzeige, ruhend oder ungenutzt

„Live“ heißt `entscheidet` oder `papier`. Das Chart-Urteil (`chart_verdict.py`) ist Schatten und Anzeige und entscheidet nichts.

## Grenzen

- Gelesen, nicht nachgerechnet: Zahlen stammen aus Berichten, Logbuch und den Journal-Dateien am Mac (Stand 12.11.2026).
- Die Liste ist grob (52 Zeilen). Feiner gezählt gibt es am Mac 64 Live-Annahmen im Code und 90 externe Aussagen
  (Entwurf, noch nicht im Repo); sie werden unter denselben Nummern ergänzt.
- Studien sind auf BTC 2020 bis 2024 gerechnet; die Validierung 2023–2024 ist mehrfach benutzt. Neue Belege brauchen
  frische Daten (Vorwärtsläufe) oder den Holdout 2025, einmalig und nur mit Uzis Wort.
- Ein Status „widerlegt“ aus einer einzelnen Studie ist vorläufig.
- C23 (CPI-Sperre) ist noch an keine Code-Stelle gebunden.

## Pflege

Eine Aussage bekommt einen neuen Status nur mit Beleg und Datum (`geprueft`). Neue Studien tragen ihre Aussagen hier
ein, bevor sie als abgeschlossen gelten. Ein Statuswechsel ist ein Commit.

## Feinliste v0 (Mac, 12.11.2026)

`v0/belief_register_v0.jsonl` ist die feinere Mac-Liste mit 253 Aussagen (eigene Nummern, eigenes Schema),
dazu Zusammenfassung, Mac-Inventur und die erste lesende Journal-Prüfung. Sie ist Rohmaterial für G2/G3
und wird nicht von `gedaechtnis.py --pruefen` geprüft. Die 52 Aussagen in `aussagen.jsonl` bleiben die
geprüfte Hauptliste; Abgleich beider Listen folgt in G3.
