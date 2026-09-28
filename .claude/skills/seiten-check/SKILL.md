---
name: seiten-check
description: Prueft die eigene Webseite auf die Sicherheitsluecken, die beim Bauen mit einer KI regelmaessig entstehen. 25 Pruefungen an der laufenden Seite (offen liegende .env und .git, Schluessel im Browser-Code, Source Maps, fehlende Schutz-Kopfzeilen, Zertifikat, Cookies, Formulare ohne Bremse, Verbindungen zu fremden Anbietern) plus 15 Pruefungen im Quelltext, die von aussen nicht sichtbar sind (Datenbank ohne Zugriffsschutz, Anmeldung umgehbar, Preise vom Kunden gesetzt, KI-Endpunkt ohne Kostendeckel). Nutzen wenn jemand fragt "ist meine Seite sicher", "kann mich da jemand hacken", "check mal meine Webseite", "hab ich irgendwo einen API-Key offen", "ich hab mir was mit Claude gebaut, ist das okay so", oder wenn gerade eine Seite, eine Landingpage oder eine kleine App fertig geworden ist und online geht.
license: MIT
metadata:
  version: "1.0"
  sprache: deutsch
---

# Seiten-Check

Findet die Loecher, die entstehen, wenn eine Seite schnell mit einer KI gebaut
wird. Zwei Teile, die zusammengehoeren:

| Teil | Wie | Was er sieht |
|---|---|---|
| **Die laufende Seite** | `scripts/seiten_check.py` misst von aussen | was jeder Fremde auch sehen kann |
| **Der Quelltext** | Claude liest den Ordner nach `references/code.md` | was von aussen unsichtbar ist |

Der zweite Teil ist der wichtigere. Die haeufigste kritische Luecke, eine
Datenbank ohne Zugriffsschutz, ist von aussen nicht zuverlaessig feststellbar,
im Code dagegen in einer Minute.

---

## Zwei Grenzen, die nicht verhandelbar sind

**1. Nur die eigene Seite.** Fremde Seiten zu pruefen ist in Deutschland nach
§ 202a StGB strafbar, auch wenn nur gelesen wird und nichts kaputtgeht. Das
Skript verlangt deshalb ausdruecklich `--mir-gehoert-die-domain`. Fragt jemand
nach einer Adresse, die ihm nicht gehoert, wird nicht gescannt, sondern genau
das gesagt.

**2. Keine Rechtsberatung.** Der Check stellt technische Tatsachen fest: welche
Verbindung entsteht, welche Datei ist abrufbar, welche Kopfzeile fehlt. Er sagt
NIE, ob etwas gegen die DSGVO, das TDDDG oder sonst ein Gesetz verstoesst, und
er formuliert keine Datenschutzerklaerung. Der Unterschied in einem Satz:

- Erlaubt: "Beim ersten Aufruf geht eine Verbindung an fonts.gstatic.com, dabei
  wird die IP-Adresse des Besuchers uebertragen. Eine Einwilligungsloesung war
  im Quelltext nicht zu finden."
- Nicht erlaubt: "Das ist ein DSGVO-Verstoss" oder "Du brauchst dafuer keine
  Einwilligung."

Wer die Bewertung braucht, braucht jemanden mit Zulassung. Das steht auch in
jedem Bericht unten drunter, und dieser Satz wird nie weggelassen.

---

## Ablauf

### Schritt 1: Klaeren, was geprueft wird

Eine Frage, nicht drei: **Adresse der Seite, und liegt der Quelltext hier?**

Ist beides da, laufen beide Teile. Ist nur die Adresse da, laeuft Teil 1 und im
Bericht steht ausdruecklich, welche vier Sachen deshalb ungeprueft bleiben
(Zugriffsschutz der Datenbank, Anmeldung, Preise, Kostendeckel).

### Schritt 2: Die laufende Seite messen

```bash
python3 scripts/seiten_check.py https://deine-seite.de --mir-gehoert-die-domain
```

Braucht nichts ausser Python 3. Keine Installation, keine Anmeldung, kein
Schluessel. Nur lesende Anfragen, kein Angriff, keine Passwortversuche, keine
Schreibzugriffe. Dauert unter einer Minute.

Mit `--json bericht.json` kommt der Befund zusaetzlich als Datei, damit man
nach dem Beheben denselben Lauf nochmal machen und vergleichen kann.

### Schritt 3: Den Quelltext lesen

`references/code.md` abarbeiten. Nur die Abschnitte laden, deren Technik im
Projekt wirklich vorkommt: kein Supabase im Projekt, kein Supabase-Abschnitt.
Was nicht da ist, wird nicht erfunden.

### Schritt 4: Berichten

Zusammen ausgeben, nach Schwere sortiert, nicht nach Reihenfolge der Pruefung.
Pro Befund vier Zeilen und kein Wort mehr:

1. **Wo**, mit Datei und Zeile oder mit der Adresse.
2. **Was**, in einem Satz ohne Fachwort.
3. **Was jemand damit machen kann**, konkret. Nicht "Risiko fuer die
   Vertraulichkeit", sondern "wer die Adresse aufruft, sieht deine
   Datenbankdaten und kann alles loeschen".
4. **Der Fix**, als Handgriff oder als Zeile zum Kopieren.

Danach ein Satz, was zuerst drankommt. Nicht alles auf einmal, sondern die
eine Sache mit dem groessten Schaden.

### Schritt 5: Beheben anbieten, nicht heimlich machen

Fixes werden vorgeschlagen und einzeln bestaetigt. Zwei Sachen werden
**niemals** automatisch gemacht, weil sie ausserhalb des Rechners passieren:

- einen verbrannten Schluessel beim Anbieter loeschen und neu erzeugen
- eine Zugriffsregel in der Datenbank aendern

Bei beidem gibt es eine Anleitung, ausgefuehrt wird es vom Besitzer.

---

## Was ein verbrannter Schluessel heisst

Steht ein Schluessel einmal im ausgelieferten Code oder in einem
oeffentlichen Repository, ist er verbrannt. Auch nach dem Loeschen. Er steckt
in der Aenderungshistorie, in Zwischenspeichern, in Kopien, die automatisch
Repositories absuchen. Aus dem Code entfernen reicht nicht. Er muss beim
Anbieter zurueckgezogen und neu erzeugt werden, sonst ist der Fix nur ein
Gefuehl.

Das gilt fuer alle: OpenAI, Anthropic, Stripe, Supabase, AWS, GitHub, Brevo.

---

## Die haeufigste Reihenfolge der Funde

Nach Schaden sortiert, wenn eine Seite schnell mit einer KI gebaut wurde:

1. Datenbank ohne Zugriffsschutz. Jede Zeile lesbar und aenderbar, oft ohne
   dass irgendwo eine Fehlermeldung auftaucht.
2. Schluessel im Browser-Code. Fremde Rechnung auf deinen Namen.
3. `.env` oder `.git` oeffentlich abrufbar. Alles auf einmal.
4. Kein Limit auf Anmeldung, Mailversand oder KI-Aufruf. Kostet Geld, ohne
   dass jemand einbricht.
5. Preise, die vom Browser mitgeschickt werden. Kunde bestimmt, was er zahlt.
6. Fehlende Schutz-Kopfzeilen. Wichtig, aber selten der erste Schaden.

---

## Referenzen

| Datei | Wofuer |
|---|---|
| `references/code.md` | die 15 Pruefungen im Quelltext, nach Technik sortiert |
| `references/beheben.md` | Fixes zum Kopieren, nach Hoster und Framework |
| `HERKUNFT.md` | woher die Pruefliste kommt, mit Quellen und Datum |

## Was dieser Check NICHT ist

Kein Penetrationstest. Er misst, was von aussen sichtbar ist, und liest
Quelltext. Er greift nichts an, probiert keine Passwoerter durch und findet
keine Luecke, die erst beim Ausnutzen sichtbar wird. Fuer eine Anwendung, an der
Geld oder Gesundheitsdaten haengen, ist ein echter Test durch Menschen die
Untergrenze, nicht dieses Skript.
