# Die 15 Pruefungen im Quelltext

Was von aussen nicht sichtbar ist. Nur die Abschnitte laden, deren Technik im
Projekt vorkommt. Jede Pruefung hat ein Suchmuster, damit nichts uebersehen
wird, aber der Fund wird immer im Zusammenhang gelesen: ein Treffer im
Suchmuster ist ein Verdacht, kein Befund.

---

## A. Schluessel und Umgebung

### 1. Schluessel steht direkt im Code

Suchen nach: `sk-`, `sk_live_`, `AKIA`, `AIza`, `ghp_`, `xkeysib-`, `Bearer `,
dazu `password =`, `secret =`, `apiKey:` mit einer Zeichenkette dahinter statt
einer Variablen.

Fund, wenn der Wert im Code steht statt aus der Umgebung gelesen zu werden.

```
// so nicht
const client = new OpenAI({ apiKey: "sk-proj-abc123..." })

// so
const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY })
```

Der Schluessel im Beispiel ist verbrannt, auch nach dem Loeschen. Neu erzeugen.

### 2. Die .env liegt im Repository

Pruefen: `git ls-files | grep -i env` und ob `.env` in der `.gitignore` steht.
Zusaetzlich `git log --all --full-history -- .env`. Steht sie in der Historie,
reicht Loeschen nicht, denn jeder Klon hat sie noch.

### 3. Oeffentliche Variable mit geheimem Inhalt

Suchen nach `NEXT_PUBLIC_`, `VITE_`, `EXPO_PUBLIC_`, `REACT_APP_` in
Kombination mit `SECRET`, `SERVICE`, `PRIVATE`, `TOKEN`, `PASSWORD`, `ADMIN`.

Alles mit diesen Vorsilben wird beim Bauen fest in den Browser-Code
geschrieben. Es ist kein Versteck, es ist eine Veroeffentlichung. Wenn der Wert
im Browser gebraucht wird, darf er nicht geheim sein. Ist er geheim, gehoert
der Aufruf auf den Server.

---

## B. Datenbank

Die haeufigste kritische Luecke ueberhaupt. Wenn hier etwas offen ist, sind
alle anderen Punkte zweitrangig.

### 4. Supabase: Row Level Security aus oder wirkungslos

Suchen in `supabase/migrations/*.sql` und im Dashboard:

- Tabelle ohne `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`
- Regel mit `USING (true)` oder `WITH CHECK (true)`
- `FOR ALL` fuer die Rolle `anon`
- `INSERT`- oder `UPDATE`-Regel ohne `WITH CHECK` (dann darf jeder schreiben,
  was er will, auch wenn er nur seine eigenen Zeilen lesen darf)

```sql
-- so nicht
CREATE POLICY "alle" ON auftraege FOR ALL USING (true);

-- so
ALTER TABLE auftraege ENABLE ROW LEVEL SECURITY;
CREATE POLICY "nur eigene" ON auftraege
  FOR SELECT USING (auth.uid() = benutzer_id);
CREATE POLICY "nur eigene anlegen" ON auftraege
  FOR INSERT WITH CHECK (auth.uid() = benutzer_id);
```

Ohne RLS ist der anon-Schluessel, der im Browser steht und dort auch hingehoert,
ein Vollzugriff auf die Tabelle.

### 5. Firebase: offene Regeln

Suchen in `firestore.rules` und `storage.rules` nach
`allow read, write: if true` oder `if request.auth != null` ohne weitere
Bedingung. Der zweite Fall heisst: jeder angemeldete Nutzer darf an alle Daten,
auch an fremde.

### 6. Der Admin-Client laeuft im Browser

Suchen nach `createClient(` mit `SERVICE_ROLE`, `service_role`,
`firebase-admin`, `adminAuth` in Dateien, die im Browser landen (alles ausser
`/api`, `/server`, `app/**/route.ts`, Server Actions, Cloud Functions).

Der service_role-Schluessel umgeht jede Zugriffsregel. Er darf den Server nie
verlassen.

---

## C. Anmeldung

### 7. Token wird gelesen, aber nicht geprueft

Suchen nach `jwt.decode(`, `jwtDecode(`, `atob(` auf einem Token,
`JSON.parse(atob(`.

`decode` liest den Inhalt, `verify` prueft die Unterschrift. Wer nur dekodiert,
glaubt dem Token alles, auch ein selbst gebautes mit `"rolle": "admin"`.

```
// so nicht
const nutzer = jwt.decode(token)
if (nutzer.rolle === "admin") { ... }

// so
const nutzer = jwt.verify(token, process.env.JWT_SECRET)
```

### 8. Schutz haengt nur an der Middleware

Suchen nach `middleware.ts` mit einem `matcher`, und dann pruefen, ob die
geschuetzten Endpunkte den Nutzer nochmal selbst pruefen.

Eine Middleware ist eine Tuer, kein Schloss. Wird ein Endpunkt direkt
aufgerufen oder greift der `matcher` einen Pfad nicht, laeuft er ungeschuetzt.
Jede Server Action und jeder API-Endpunkt prueft selbst, wer da ist.

### 9. Anmelde-Token im localStorage

Suchen nach `localStorage.setItem` mit `token`, `session`, `jwt`, `auth`, dazu
`AsyncStorage.setItem` in mobilen Projekten.

Jedes Skript auf der Seite kann den localStorage lesen, auch ein
eingeschleustes. Anmeldedaten gehoeren in ein Cookie mit `HttpOnly`, `Secure`
und `SameSite`, an das Skripte nicht herankommen.

---

## D. Missbrauch und Kosten

Das ist der Block, der Geld kostet, ohne dass jemand einbricht.

### 10. Kein Limit auf teuren Endpunkten

Jeder dieser Endpunkte braucht eine Bremse, und eine KI baut sie fast nie von
allein ein:

- Anmelden, Registrieren, Passwort vergessen, Einmalcode
- jeder Aufruf an OpenAI, Anthropic oder ein anderes Modell
- Mail- und SMS-Versand
- Datei-Upload und alles, was Dateien umrechnet

Suchen nach `ratelimit`, `rateLimit`, `Ratelimit`, `throttle`, `limiter`. Kein
Treffer bei vorhandenen Endpunkten dieser Art ist ein Befund.

### 11. Kein harter Kostendeckel beim Anbieter

Nicht im Code sichtbar, trotzdem Teil der Pruefung: im Konto bei OpenAI oder
Anthropic ein hartes Ausgabenlimit setzen, nicht nur eine Warnung per Mail.
Eine Warnung kommt an, waehrend die Rechnung weiterlaeuft.

Ein einzelner Nutzer kann ohne Limit ein Monatsbudget in Minuten leerziehen.
Das ist der haeufigste teure Schaden bei schnell gebauten Seiten, und es ist
kein Einbruch, sondern eine ganz normale Benutzung ohne Bremse.

### 12. Der Zaehler steht in einer oeffentlichen Tabelle

Suchen nach einer Tabelle wie `rate_limits`, `usage`, `credits`, die per
Supabase-REST oder Firebase erreichbar ist.

Steht der Zaehler dort, wo der Nutzer schreiben darf, setzt er ihn selbst
zurueck. Der Zaehler gehoert in ein privates Schema, in Redis oder in die
Middleware.

---

## E. Geld und Eingaben

### 13. Der Preis kommt aus dem Browser

Suchen in Zahlungs-Endpunkten nach `req.body.price`, `amount` oder `betrag`
aus der Anfrage.

```
// so nicht
const session = await stripe.checkout.sessions.create({
  line_items: [{ price_data: { unit_amount: req.body.preis } }]
})

// so
const produkt = await db.produkte.findUnique({ where: { id: req.body.produktId } })
const session = await stripe.checkout.sessions.create({
  line_items: [{ price_data: { unit_amount: produkt.preis_in_cent } }]
})
```

Der Browser schickt, was er will. Der Preis wird auf dem Server nachgeschlagen.

### 14. Webhook ohne Unterschriftspruefung

Suchen nach `/webhook`, `/api/stripe`, `constructEvent`, `verifyHeader`.

Ohne Pruefung der Unterschrift kann jeder eine Nachricht an deinen Endpunkt
schicken, in der steht, dass bezahlt wurde. Bei Stripe ist das
`stripe.webhooks.constructEvent` mit dem Webhook-Geheimnis, nicht
`JSON.parse(body)`.

### 15. Abfrage zusammengebaut statt eingesetzt

Suchen nach `$queryRawUnsafe`, `queryRaw` mit Backticks und `${`, String-Addition
in SQL, `execute(f"..."` in Python, dazu bei Prisma und Mongo direkt
uebernommene Filter-Objekte aus `req.body` (damit lassen sich Operatoren wie
`$ne` einschleusen).

```
// so nicht
db.$queryRawUnsafe(`SELECT * FROM nutzer WHERE mail = '${eingabe}'`)

// so
db.$queryRaw`SELECT * FROM nutzer WHERE mail = ${eingabe}`
```

---

## Was NICHT als Befund gemeldet wird

- Stil, Formatierung, fehlende Typen, Performance. Das ist kein Sicherheitsfund.
- Der Supabase-anon-Schluessel im Frontend. Der gehoert dorthin. Der Befund ist
  die fehlende Zugriffsregel, nicht der Schluessel.
- Ein oeffentlicher Stripe-Schluessel (`pk_`). Auch der gehoert ins Frontend.
- Eine Technik, die im Projekt gar nicht vorkommt. Kein Supabase, kein
  Supabase-Abschnitt im Bericht.
- Alles, was eine rechtliche Bewertung waere. Siehe die zweite Grenze in
  `SKILL.md`.
