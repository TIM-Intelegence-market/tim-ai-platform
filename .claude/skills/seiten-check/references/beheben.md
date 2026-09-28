# Beheben

Fixes zum Kopieren. Immer erst den Befund lesen, dann den passenden Block
nehmen. Nach jedem Fix denselben Lauf nochmal machen und die beiden
JSON-Berichte vergleichen, sonst ist der Fix ein Gefuehl.

---

## Reihenfolge

1. Verbrannte Schluessel neu erzeugen. Alles andere ist wertlos, solange ein
   fremder Schluessel gueltig ist.
2. Zugriffsschutz auf der Datenbank.
3. Offen liegende Dateien schliessen (`.env`, `.git`, Sicherungen).
4. Limits und Kostendeckel.
5. Kopfzeilen.

---

## 1. Schluessel neu erzeugen

| Anbieter | Wo |
|---|---|
| OpenAI | platform.openai.com, API keys, alten widerrufen, neuen anlegen |
| Anthropic | console.anthropic.com, API Keys |
| Stripe | Dashboard, Entwickler, API-Schluessel, "Roll key" |
| Supabase | Projekt, Settings, API, "Reset service_role" |
| AWS | IAM, Nutzer, Zugangsschluessel deaktivieren, dann loeschen |
| GitHub | Settings, Developer settings, Tokens |
| Brevo | SMTP & API, Schluessel loeschen |

Danach den neuen Wert nur in die Umgebungsvariablen des Hosters eintragen,
nie in den Code.

Steckt der Schluessel in der Git-Historie, hilft ein neuer Commit nicht. Neu
erzeugen ist Pflicht, das Saeubern der Historie (`git filter-repo`) ist
Kosmetik danach.

---

## 2. Datenbank

### Supabase

```sql
-- Auf JEDER Tabelle, ohne Ausnahme
ALTER TABLE meine_tabelle ENABLE ROW LEVEL SECURITY;

-- Lesen: nur die eigenen Zeilen
CREATE POLICY "eigene lesen" ON meine_tabelle
  FOR SELECT USING (auth.uid() = benutzer_id);

-- Schreiben: nur mit der eigenen Kennung, WITH CHECK nicht vergessen
CREATE POLICY "eigene anlegen" ON meine_tabelle
  FOR INSERT WITH CHECK (auth.uid() = benutzer_id);

CREATE POLICY "eigene aendern" ON meine_tabelle
  FOR UPDATE USING (auth.uid() = benutzer_id)
             WITH CHECK (auth.uid() = benutzer_id);
```

Pruefen, welche Tabelle noch offen ist:

```sql
SELECT tablename, rowsecurity FROM pg_tables
WHERE schemaname = 'public' ORDER BY rowsecurity, tablename;
```

Alles mit `rowsecurity = false` ist offen.

### Firebase

```
// so nicht
allow read, write: if true;

// so
match /auftraege/{id} {
  allow read:  if request.auth != null && resource.data.besitzer == request.auth.uid;
  allow write: if request.auth != null && request.resource.data.besitzer == request.auth.uid;
}
```

---

## 3. Offene Dateien schliessen

### Caddy

```
example.de {
    root * /var/www/seite
    @versteckt path /.* /*/.*
    respond @versteckt 404
    file_server
}
```

### nginx

```
location ~ /\. { deny all; return 404; }
location ~* \.(sql|bak|zip|tar|gz|env)$ { deny all; return 404; }
autoindex off;
server_tokens off;
```

### Apache

```
<FilesMatch "^\.|\.(sql|bak|zip|env)$">
    Require all denied
</FilesMatch>
Options -Indexes
ServerTokens Prod
ServerSignature Off
```

### Vercel und Netlify

Dotfiles werden nicht ausgeliefert. Der haeufigere Fehler dort ist, dass die
Datei ins `public/`-Verzeichnis kopiert wurde. Dann liegt sie absichtlich
offen und muss dort weg.

### Source Maps abschalten

```js
// next.config.js
module.exports = { productionBrowserSourceMaps: false }

// vite.config.js
export default { build: { sourcemap: false } }
```

---

## 4. Limits und Kostendeckel

### Ein Limit, das nicht manipulierbar ist

```ts
import { Ratelimit } from "@upstash/ratelimit"
import { Redis } from "@upstash/redis"

const limit = new Ratelimit({
  redis: Redis.fromEnv(),
  limiter: Ratelimit.slidingWindow(5, "60 s"),
})

export async function POST(req: Request) {
  const ip = req.headers.get("x-forwarded-for") ?? "unbekannt"
  const { success } = await limit.limit(ip)
  if (!success) return new Response("Zu viele Anfragen", { status: 429 })
  // ...
}
```

Pro IP allein reicht nicht (IPs wechseln), pro Konto allein auch nicht (Konten
sind schnell angelegt). Beides zusammen.

### Der harte Deckel

- OpenAI: Settings, Limits, "Hard limit" setzen, nicht nur "Soft limit"
- Anthropic: Console, Plans & Billing, Ausgabenlimit
- Vercel, AWS, GCP: Budget-Alarm UND harte Obergrenze

Ein Alarm ist keine Bremse. Er sagt dir nur, wie hoch die Rechnung war, als
sie schon lief.

---

## 5. Kopfzeilen

### Caddy

```
header {
    Strict-Transport-Security "max-age=31536000; includeSubDomains"
    X-Content-Type-Options "nosniff"
    X-Frame-Options "DENY"
    Referrer-Policy "strict-origin-when-cross-origin"
    Permissions-Policy "camera=(), microphone=(), geolocation=()"
    Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
    -Server
}
```

### Next.js

```js
// next.config.js
const kopfzeilen = [
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
]
module.exports = {
  async headers() {
    return [{ source: "/:pfad*", headers: kopfzeilen }]
  },
}
```

### Zur CSP

Die Content-Security-Policy ist die einzige Kopfzeile, die eine Seite kaputt
machen kann, wenn man sie blind setzt. Vorgehen: erst mit
`Content-Security-Policy-Report-Only` starten, ein paar Tage die Meldungen in
der Browser-Konsole ansehen, erlaubte Quellen ergaenzen, dann scharf schalten.

`'unsafe-inline'` bei `script-src` hebt den wichtigsten Teil des Schutzes
wieder auf. Bei `style-src` ist es meistens vertretbar.

---

## 6. Cookies

```ts
cookies().set("sitzung", wert, {
  httpOnly: true,
  secure: true,
  sameSite: "lax",
  path: "/",
  maxAge: 60 * 60 * 24 * 7,
})
```

---

## 7. Verbindungen zu fremden Anbietern

Technisch laesst sich fast jede fremde Datei selbst ausliefern, dann entsteht
die Verbindung gar nicht erst.

**Schriften lokal einbinden** statt von Google laden:

1. Die Schrift bei fonts.google.com herunterladen oder in Next.js
   `next/font/local` verwenden.
2. Die `woff2`-Dateien ins eigene Projekt legen.
3. Das `<link>` auf `fonts.googleapis.com` entfernen.

Dasselbe Prinzip gilt fuer Bibliotheken von jsDelivr, unpkg und cdnjs: Datei
herunterladen, selbst ausliefern.

Ob eine bestimmte Verbindung eine Einwilligung braucht, entscheidet dieser
Skill nicht. Er sagt nur, dass sie entsteht.
