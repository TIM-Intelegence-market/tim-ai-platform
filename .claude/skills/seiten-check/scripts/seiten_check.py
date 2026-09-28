#!/usr/bin/env python3
"""Seiten-Check: prueft eine LAUFENDE Webseite auf die Loecher, die beim Bauen
mit einer KI regelmaessig entstehen.

Nur Standardbibliothek, keine Installation noetig. Nur lesende GET- und
HEAD-Anfragen, kein Angriff, kein Raten von Passwoertern, keine Schreibzugriffe.

NUR AUF DER EIGENEN DOMAIN AUSFUEHREN. Das Pruefen fremder Seiten kann
strafbar sein (§ 202a StGB, in den USA CFAA). Das Skript verlangt deshalb
--mir-gehoert-die-domain.

Aufruf:
    python3 seiten_check.py https://deine-seite.de --mir-gehoert-die-domain
    python3 seiten_check.py https://deine-seite.de --mir-gehoert-die-domain --json bericht.json
"""

import argparse
import base64
import datetime
import json
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "seiten-check/1.0 (+eigene Seite, nur lesend)"
TIMEOUT = 12

# ---------------------------------------------------------------- Hilfsmittel

BEFUNDE = []


def befund(schwere, nummer, titel, gefunden, warum, beheben):
    BEFUNDE.append({
        "schwere": schwere,          # kritisch | hoch | mittel | niedrig
        "pruefung": nummer,
        "titel": titel,
        "gefunden": gefunden,
        "warum": warum,
        "beheben": beheben,
    })


def hole(url, methode="GET", max_bytes=400_000):
    """Eine Anfrage. Gibt (status, headers, text) zurueck oder (None, {}, '')."""
    req = urllib.request.Request(url, method=methode, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            roh = r.read(max_bytes) if methode == "GET" else b""
            return r.status, dict(r.headers), roh.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        roh = b""
        try:
            roh = e.read(max_bytes)
        except Exception:
            pass
        return e.code, dict(e.headers or {}), roh.decode("utf-8", "replace")
    except Exception:
        return None, {}, ""


def kopf(headers, name):
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


# ------------------------------------------------- Block 1: was offen rumliegt

OFFENE_PFADE = [
    (".env", "kritisch"),
    (".env.local", "kritisch"),
    (".env.production", "kritisch"),
    (".git/config", "kritisch"),
    (".git/HEAD", "kritisch"),
    ("backup.sql", "kritisch"),
    ("dump.sql", "kritisch"),
    ("database.sqlite", "kritisch"),
    ("config.json", "hoch"),
    ("credentials.json", "kritisch"),
    (".DS_Store", "niedrig"),
    ("phpinfo.php", "hoch"),
    ("server-status", "mittel"),
    ("wp-config.php.bak", "kritisch"),
]

# Text, der beweist, dass es die echte Datei ist und nicht die 200er-Fehlerseite
BEWEIS = {
    ".env": re.compile(r"^\s*[A-Z0-9_]{3,}\s*=", re.M),
    ".env.local": re.compile(r"^\s*[A-Z0-9_]{3,}\s*=", re.M),
    ".env.production": re.compile(r"^\s*[A-Z0-9_]{3,}\s*=", re.M),
    ".git/config": re.compile(r"\[core\]|\[remote "),
    ".git/HEAD": re.compile(r"^ref: refs/"),
    "backup.sql": re.compile(r"(?i)(insert into|create table)"),
    "dump.sql": re.compile(r"(?i)(insert into|create table)"),
    "config.json": re.compile(r"^\s*\{"),
    "credentials.json": re.compile(r"^\s*\{"),
    "phpinfo.php": re.compile(r"(?i)phpinfo\(\)|PHP Version"),
    "server-status": re.compile(r"(?i)apache server status"),
}


def pruefe_offene_pfade(basis):
    treffer = []
    for pfad, schwere in OFFENE_PFADE:
        url = urllib.parse.urljoin(basis + "/", pfad)
        status, _, text = hole(url, max_bytes=4000)
        if status != 200 or not text.strip():
            continue
        muster = BEWEIS.get(pfad)
        if muster and not muster.search(text):
            continue          # 200er-Fehlerseite, kein echter Fund
        treffer.append((pfad, schwere, url))
    for pfad, schwere, url in treffer:
        befund(schwere, 1, f"{pfad} ist oeffentlich abrufbar", url,
               "Wer die Adresse aufruft, bekommt den Inhalt ohne Anmeldung. "
               "Bei .env und .git sind das deine Zugangsdaten und deine komplette "
               "Aenderungshistorie, auch geloeschte Dateien.",
               "Beim Hoster jeden Pfad sperren, der mit einem Punkt anfaengt, und "
               "die Datei aus dem oeffentlichen Ordner nehmen. Danach jeden "
               "Schluessel, der drinstand, neu erzeugen. Er gilt als verbrannt.")
    if not treffer:
        befund("ok", 1, "Keine offen liegenden Konfigurations- oder Sicherungsdateien",
               f"{len(OFFENE_PFADE)} Pfade geprueft", "", "")


def pruefe_verzeichnisauflistung(basis):
    fund = []
    for pfad in ["", "assets/", "static/", "uploads/", "images/", "js/", "css/"]:
        url = urllib.parse.urljoin(basis + "/", pfad)
        status, _, text = hole(url, max_bytes=8000)
        if status == 200 and re.search(r"(?i)<title>index of /|Directory listing for", text):
            fund.append(url)
    if fund:
        befund("mittel", 2, "Verzeichnisauflistung ist an", ", ".join(fund),
               "Der Server zeigt jedem den kompletten Inhalt des Ordners, "
               "auch Dateien, auf die keine Seite verlinkt.",
               "Beim Hoster die Auflistung abschalten (nginx autoindex off, "
               "Apache Options -Indexes).")
    else:
        befund("ok", 2, "Keine Verzeichnisauflistung", "7 Ordner geprueft", "", "")


def pruefe_sourcemaps(basis, html):
    skripte = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)
    offen = []
    for s in skripte[:12]:
        js_url = urllib.parse.urljoin(basis + "/", s)
        if urllib.parse.urlparse(js_url).netloc != urllib.parse.urlparse(basis).netloc:
            continue
        status, _, js = hole(js_url, max_bytes=200_000)
        if status != 200:
            continue
        m = re.search(r"sourceMappingURL=([^\s*]+)", js)
        if not m:
            continue
        map_url = urllib.parse.urljoin(js_url, m.group(1).strip())
        st2, _, mp = hole(map_url, max_bytes=4000)
        if st2 == 200 and '"sources"' in mp:
            offen.append(map_url)
    if offen:
        befund("mittel", 3, "Source Maps sind oeffentlich abrufbar", ", ".join(offen[:3]),
               "Damit laesst sich dein zusammengepackter Code zurueck in den "
               "Originalzustand verwandeln, inklusive Kommentaren, Ordnerstruktur "
               "und allem, was du im Frontend fuer unlesbar gehalten hast.",
               "Im Build die Source Maps fuer die Produktion abschalten "
               "(Next.js: productionBrowserSourceMaps false, Vite: build.sourcemap false).")
    else:
        befund("ok", 3, "Keine offenen Source Maps", f"{len(skripte)} Skripte geprueft", "", "")


# ---------------------------------------- Block 2: Schluessel im ausgelieferten Code

SCHLUESSEL = [
    (r"sk-ant-api03-[A-Za-z0-9_\-]{20,}", "Anthropic-Schluessel", "kritisch"),
    (r"sk-proj-[A-Za-z0-9_\-]{20,}", "OpenAI-Projektschluessel", "kritisch"),
    (r"sk-[A-Za-z0-9]{32,}", "OpenAI-Schluessel", "kritisch"),
    (r"AIza[0-9A-Za-z_\-]{35}", "Google-API-Schluessel", "hoch"),
    (r"AKIA[0-9A-Z]{16}", "AWS-Zugangsschluessel", "kritisch"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub-Token", "kritisch"),
    (r"github_pat_[A-Za-z0-9_]{50,}", "GitHub-Token", "kritisch"),
    (r"xkeysib-[A-Za-z0-9]{40,}", "Brevo-Schluessel", "kritisch"),
    (r"sk_live_[A-Za-z0-9]{20,}", "Stripe-Live-Schluessel", "kritisch"),
    (r"rk_live_[A-Za-z0-9]{20,}", "Stripe-Live-Schluessel", "kritisch"),
    (r"xoxb-[0-9A-Za-z\-]{20,}", "Slack-Token", "hoch"),
    (r"SG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}", "SendGrid-Schluessel", "kritisch"),
]


def sammle_code(basis, html):
    """HTML plus die eigenen JS-Dateien als ein Text."""
    teile = [("seite", html)]
    for s in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)[:12]:
        js_url = urllib.parse.urljoin(basis + "/", s)
        if urllib.parse.urlparse(js_url).netloc != urllib.parse.urlparse(basis).netloc:
            continue
        st, _, js = hole(js_url, max_bytes=300_000)
        if st == 200:
            teile.append((s, js))
    return teile


def pruefe_schluessel(teile):
    gefunden = []
    for name, text in teile:
        for muster, was, schwere in SCHLUESSEL:
            for t in re.findall(muster, text):
                gefunden.append((was, schwere, name, t[:12] + "..."))
    if gefunden:
        for was, schwere, wo, kurz in gefunden[:10]:
            befund(schwere, 4, f"{was} liegt im ausgelieferten Code", f"{wo}: {kurz}",
                   "Alles, was der Browser laedt, kann jeder lesen. Ein Schluessel im "
                   "Frontend ist ein Schluessel in fremder Hand, und die Rechnung "
                   "laeuft auf dich.",
                   "Schluessel sofort beim Anbieter loeschen und neu erzeugen. Den "
                   "Aufruf auf einen eigenen Server-Endpunkt verlegen, der den "
                   "Schluessel behaelt und nur das Ergebnis zurueckgibt.")
    else:
        befund("ok", 4, "Keine Anbieter-Schluessel im ausgelieferten Code",
               f"{len(SCHLUESSEL)} Schluesselarten geprueft", "", "")


def pruefe_supabase(teile):
    """Findet Supabase-URL und JWT. Ein service_role-Token im Frontend hebelt
    jeden Zugriffsschutz aus."""
    url_gefunden = None
    rollen = []
    for name, text in teile:
        m = re.search(r"https://[a-z0-9]{20}\.supabase\.co", text)
        if m and not url_gefunden:
            url_gefunden = m.group(0)
        for tok in re.findall(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}", text):
            teil = tok.split(".")[1]
            teil += "=" * (-len(teil) % 4)
            try:
                nutz = json.loads(base64.urlsafe_b64decode(teil))
            except Exception:
                continue
            rolle = nutz.get("role")
            if rolle:
                rollen.append((rolle, name))
    if any(r == "service_role" for r, _ in rollen):
        wo = [n for r, n in rollen if r == "service_role"][0]
        befund("kritisch", 5, "Supabase service_role-Schluessel liegt im Frontend", wo,
               "Dieser Schluessel umgeht jede Zugriffsregel. Wer ihn aus dem Browser "
               "kopiert, kann jede Zeile deiner Datenbank lesen, aendern und loeschen.",
               "Schluessel in Supabase zuruecksetzen, im Frontend den anon-Schluessel "
               "verwenden, service_role nur serverseitig.")
    elif url_gefunden:
        befund("mittel", 5, "Supabase erkannt, anon-Schluessel im Frontend ist normal",
               url_gefunden,
               "Der anon-Schluessel gehoert ins Frontend. Entscheidend ist, ob auf "
               "jeder Tabelle Row Level Security aktiv ist. Das laesst sich von aussen "
               "nicht sicher feststellen.",
               "Im Supabase-Dashboard unter Authentication und Policies pruefen, dass "
               "RLS auf JEDER Tabelle an ist und keine Regel USING (true) lautet.")
    else:
        befund("ok", 5, "Kein Supabase im Frontend gefunden", "", "", "")


def pruefe_oeffentliche_env(teile):
    """NEXT_PUBLIC_ und Co. mit verdaechtigen Namen."""
    verdacht = re.compile(
        r"(NEXT_PUBLIC|VITE|EXPO_PUBLIC|REACT_APP)_[A-Z0-9_]*"
        r"(SECRET|SERVICE|PRIVATE|TOKEN|PASSWORD|API_KEY|ADMIN)[A-Z0-9_]*")
    treffer = set()
    for name, text in teile:
        treffer.update(m.group(0) for m in verdacht.finditer(text))
    if treffer:
        befund("hoch", 6, "Oeffentliche Umgebungsvariable mit Geheimnis-Namen",
               ", ".join(sorted(treffer)[:6]),
               "Alles mit diesen Vorsilben wird beim Bauen fest in den "
               "Browser-Code geschrieben. Das ist kein Versteck, das ist eine "
               "Veroeffentlichung.",
               "Die Vorsilbe entfernen und den Wert nur serverseitig lesen. "
               "Wenn der Wert im Browser gebraucht wird, gehoert er nicht "
               "geheim zu sein.")
    else:
        befund("ok", 6, "Keine oeffentliche Variable mit Geheimnis-Namen", "", "", "")


# ------------------------------------------- Block 3: Transport und Kopfzeilen

HEADER_PRUEFUNGEN = [
    ("Strict-Transport-Security", "hoch", 8,
     "Ohne diese Zeile kann ein Angreifer im selben WLAN die Verbindung auf "
     "unverschluesselt zurueckdrehen und mitlesen.",
     "Strict-Transport-Security: max-age=31536000; includeSubDomains"),
    ("Content-Security-Policy", "hoch", 9,
     "Ohne Regel darf jede eingeschleuste Zeile Code im Browser deiner Besucher "
     "laufen und Eingaben abgreifen.",
     "Mit Content-Security-Policy: default-src 'self' anfangen und erlaubte "
     "Quellen einzeln dazunehmen."),
    ("X-Content-Type-Options", "mittel", 10,
     "Ohne nosniff darf der Browser raten, was eine Datei ist, und ein "
     "hochgeladenes Bild als Skript ausfuehren.",
     "X-Content-Type-Options: nosniff"),
    ("Referrer-Policy", "niedrig", 11,
     "Ohne Regel schickt der Browser die komplette Adresse deiner Seite an jede "
     "fremde Seite weiter, auf die jemand klickt, inklusive allem, was in der "
     "Adresse steht.",
     "Referrer-Policy: strict-origin-when-cross-origin"),
    ("Permissions-Policy", "niedrig", 12,
     "Ohne Regel darf jedes eingebettete fremde Element Kamera, Mikrofon und "
     "Standort anfragen.",
     "Permissions-Policy: camera=(), microphone=(), geolocation=()"),
]


def pruefe_header(basis, headers):
    for name, schwere, nr, warum, wie in HEADER_PRUEFUNGEN:
        wert = kopf(headers, name)
        if not wert:
            befund(schwere, nr, f"Kopfzeile {name} fehlt", "nicht gesetzt", warum,
                   f"Beim Hoster setzen: {wie}")
        elif name == "Content-Security-Policy" and "unsafe-inline" in wert:
            befund("mittel", nr, "Content-Security-Policy erlaubt unsafe-inline",
                   wert[:120],
                   "Mit unsafe-inline ist der wichtigste Teil des Schutzes wieder aus, "
                   "eingeschleuster Code darf laufen.",
                   "Inline-Skripte in eigene Dateien ziehen und unsafe-inline entfernen.")
        else:
            befund("ok", nr, f"Kopfzeile {name} ist gesetzt", wert[:80], "", "")

    # Frame-Schutz: entweder X-Frame-Options oder frame-ancestors in der CSP
    xfo = kopf(headers, "X-Frame-Options")
    csp = kopf(headers, "Content-Security-Policy") or ""
    if not xfo and "frame-ancestors" not in csp:
        befund("mittel", 13, "Kein Schutz gegen Einbetten in fremde Seiten",
               "weder X-Frame-Options noch frame-ancestors",
               "Deine Seite laesst sich unsichtbar in eine fremde Seite legen, sodass "
               "Besucher auf etwas anderes klicken, als sie sehen.",
               "X-Frame-Options: DENY setzen oder frame-ancestors 'none' in die CSP.")
    else:
        befund("ok", 13, "Einbetten in fremde Seiten ist geregelt", xfo or "frame-ancestors", "", "")

    acao = kopf(headers, "Access-Control-Allow-Origin")
    if acao and acao.strip() == "*":
        befund("mittel", 14, "Access-Control-Allow-Origin steht auf *", acao,
               "Jede fremde Seite darf deine Schnittstelle im Namen des Besuchers "
               "aufrufen und die Antwort lesen.",
               "Auf die eigene Domain einschraenken statt Sternchen.")
    else:
        befund("ok", 14, "Keine offene Cross-Origin-Freigabe", acao or "nicht gesetzt", "", "")

    server = kopf(headers, "Server") or ""
    xpb = kopf(headers, "X-Powered-By") or ""
    if re.search(r"\d+\.\d+", server + " " + xpb):
        befund("niedrig", 15, "Server nennt seine genaue Version",
               (server + " " + xpb).strip(),
               "Die Versionsnummer sagt jedem, welche bekannten Luecken bei dir "
               "wahrscheinlich offen sind.",
               "Versionsangabe abschalten (nginx server_tokens off, "
               "X-Powered-By entfernen).")
    else:
        befund("ok", 15, "Keine Versionsnummer in den Serverzeilen",
               (server + " " + xpb).strip() or "nicht gesetzt", "", "")


def pruefe_https(basis):
    p = urllib.parse.urlparse(basis)
    if p.scheme != "https":
        befund("kritisch", 7, "Die Seite laeuft nicht ueber HTTPS", basis,
               "Alles, was jemand eintippt, geht im Klartext durchs Netz.",
               "Kostenloses Zertifikat einrichten (Let's Encrypt) und alles auf "
               "https umleiten.")
        return
    http_url = "http://" + p.netloc + (p.path or "/")
    req = urllib.request.Request(http_url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            ziel = r.url
        if ziel.startswith("https://"):
            befund("ok", 7, "HTTP wird auf HTTPS umgeleitet", ziel, "", "")
        else:
            befund("hoch", 7, "HTTP wird nicht auf HTTPS umgeleitet", ziel,
                   "Wer die Adresse ohne https eintippt, bleibt unverschluesselt.",
                   "Beim Hoster eine dauerhafte Umleitung von http auf https setzen.")
    except Exception:
        befund("ok", 7, "Port 80 antwortet nicht, keine unverschluesselte Verbindung "
                        "moeglich", http_url, "", "")


def pruefe_zertifikat(basis):
    host = urllib.parse.urlparse(basis).hostname
    if not host:
        return
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=TIMEOUT) as s:
            with ctx.wrap_socket(s, server_hostname=host) as ss:
                cert = ss.getpeercert()
                version = ss.version()
        bis = datetime.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=datetime.timezone.utc)
        tage = (bis - datetime.datetime.now(datetime.timezone.utc)).days
        if tage < 14:
            befund("hoch", 16, "Zertifikat laeuft in Kuerze ab", f"noch {tage} Tage",
                   "Laeuft es ab, zeigt jeder Browser eine Warnseite statt deiner Seite.",
                   "Automatische Verlaengerung pruefen (certbot renew).")
        else:
            befund("ok", 16, "Zertifikat gueltig", f"noch {tage} Tage, {version}", "", "")
        if version in ("TLSv1", "TLSv1.1"):
            befund("hoch", 17, "Veraltete Verschluesselung", version,
                   "Diese Versionen gelten als gebrochen.",
                   "Beim Hoster mindestens TLS 1.2 erzwingen.")
        else:
            befund("ok", 17, "Aktuelle Verschluesselung", version, "", "")
    except Exception as e:
        befund("mittel", 16, "Zertifikat nicht pruefbar", str(e)[:80], "", "")


def pruefe_cookies(headers):
    rohe = []
    for k, v in headers.items():
        if k.lower() == "set-cookie":
            rohe.append(v)
    if not rohe:
        befund("ok", 18, "Beim ersten Aufruf werden keine Cookies gesetzt", "", "", "")
        return
    schwach = []
    for c in rohe:
        name = c.split("=")[0]
        fehlt = [f for f in ("Secure", "HttpOnly", "SameSite") if f.lower() not in c.lower()]
        if fehlt:
            schwach.append(f"{name} (ohne {', '.join(fehlt)})")
    if schwach:
        befund("mittel", 18, "Cookies ohne Schutzmerkmale", ", ".join(schwach),
               "Ohne Secure geht das Cookie auch unverschluesselt raus, ohne HttpOnly "
               "kann jedes Skript es lesen, ohne SameSite schickt der Browser es auch "
               "mit, wenn der Klick von einer fremden Seite kommt.",
               "An jedes Cookie Secure, HttpOnly und SameSite=Lax anhaengen.")
    else:
        befund("ok", 18, "Cookies tragen Secure, HttpOnly und SameSite",
               f"{len(rohe)} Cookie(s)", "", "")


# ------------------------------------- Block 4: Fehlerseiten und Endpunkte

def pruefe_fehlerseite(basis):
    url = urllib.parse.urljoin(basis + "/", "diese-seite-gibt-es-nicht-4711")
    status, _, text = hole(url, max_bytes=20000)
    spuren = re.findall(
        r"(?i)(Traceback \(most recent call last\)|at [A-Za-z$_]+ \(/|"
        r"Warning: |Fatal error: |Whoops, looks like something went wrong|"
        r"/home/[a-z0-9_\-]+/|/var/www/[a-z0-9_\-/]+|node_modules/)", text)
    if status == 200:
        befund("niedrig", 19, "Unbekannte Adressen antworten mit 200 statt 404", url,
               "Suchmaschinen und Pruefwerkzeuge koennen echte von falschen Seiten "
               "nicht unterscheiden.",
               "Fuer unbekannte Pfade den Status 404 zurueckgeben.")
    elif spuren:
        befund("hoch", 19, "Fehlerseite verraet innere Details", ", ".join(set(spuren))[:100],
               "Pfade auf dem Server, Dateinamen und Zeilennummern sind die Landkarte "
               "fuer einen Angriff.",
               "Debug-Modus in der Produktion ausschalten und eine eigene Fehlerseite "
               "ohne Details ausliefern.")
    else:
        befund("ok", 19, "Fehlerseite verraet nichts", f"Status {status}", "", "")


def pruefe_pflichtseiten(basis, html):
    treffer = {"impressum": False, "datenschutz": False}
    for wort in treffer:
        if re.search(wort, html, re.I):
            treffer[wort] = True
            continue
        for kandidat in (f"{wort}", f"{wort}.html", f"{wort}/"):
            st, _, _ = hole(urllib.parse.urljoin(basis + "/", kandidat), max_bytes=2000)
            if st == 200:
                treffer[wort] = True
                break
    fehlt = [w for w, da in treffer.items() if not da]
    if fehlt:
        befund("mittel", 20, "Pflichtseite nicht gefunden", ", ".join(fehlt),
               "Technische Feststellung, keine rechtliche Bewertung: auf der "
               "Startseite und unter den ueblichen Adressen war dazu nichts "
               "erreichbar.",
               "Wenn die Seite geschaeftlich genutzt wird, gehoeren Impressum und "
               "Datenschutzerklaerung dazu. Inhalt und Pflicht klaert jemand mit "
               "Zulassung, nicht dieses Skript.")
    else:
        befund("ok", 20, "Impressum und Datenschutzerklaerung sind erreichbar", "", "", "")


def pruefe_mixed_content(basis, html):
    if not basis.startswith("https://"):
        return
    unsicher = set()
    for m in re.finditer(r'(?:src|href)=["\'](http://[^"\']+)["\']', html):
        unsicher.add(urllib.parse.urlparse(m.group(1)).netloc)
    if unsicher:
        befund("mittel", 22, "Die Seite laedt Inhalte unverschluesselt nach",
               ", ".join(sorted(unsicher)[:5]),
               "Eine verschluesselte Seite, die unverschluesselte Teile nachlaedt, "
               "ist an dieser Stelle wieder mitlesbar und aenderbar. Browser "
               "blockieren das teilweise still, dann fehlt der Teil einfach.",
               "Alle Adressen auf https umstellen oder die Datei selbst ausliefern.")
    else:
        befund("ok", 22, "Keine unverschluesselt nachgeladenen Inhalte", "", "", "")


def pruefe_formulare(basis, html):
    formulare = re.findall(r"<form[^>]*>", html, re.I)
    if not formulare:
        befund("ok", 23, "Kein Formular auf der Startseite", "", "", "")
        return
    schutz = bool(re.search(r"(?i)(recaptcha|hcaptcha|turnstile|honeypot|csrf|"
                            r"friendlycaptcha|altcha)", html))
    ohne_post = [f for f in formulare if "post" not in f.lower()]
    hinweise = []
    if not schutz:
        hinweise.append("kein Captcha, kein Honeypot, kein CSRF-Feld im Quelltext")
    if ohne_post:
        hinweise.append(f"{len(ohne_post)} Formular(e) senden nicht per POST")
    if hinweise:
        befund("mittel", 23, f"{len(formulare)} Formular(e) ohne erkennbaren Missbrauchsschutz",
               "; ".join(hinweise),
               "Ein Formular ohne Bremse laesst sich in Schleife absenden. Bei einem "
               "Kontaktformular kostet das Nerven, bei einem Endpunkt, der eine Mail "
               "verschickt oder eine KI aufruft, kostet es Geld: ein einziger Nutzer "
               "kann dein Monatsbudget in Minuten leerziehen.",
               "Auf dem Server ein Limit pro IP und pro Nutzer setzen, dazu ein "
               "verstecktes Feld als Falle. Bei KI- und Mail-Endpunkten zusaetzlich "
               "einen harten Kostendeckel beim Anbieter eintragen.")
    else:
        befund("ok", 23, f"{len(formulare)} Formular(e) mit erkennbarem Schutz", "", "", "")


def pruefe_robots(basis):
    st, _, text = hole(urllib.parse.urljoin(basis + "/", "robots.txt"), max_bytes=8000)
    if st != 200:
        befund("ok", 24, "Keine robots.txt", "", "", "")
        return
    heikel = [z.split(":", 1)[1].strip() for z in text.splitlines()
              if z.lower().startswith("disallow:")
              and re.search(r"(?i)(admin|login|intern|privat|backup|test|staging|api|dev)",
                            z)]
    if heikel:
        befund("niedrig", 24, "robots.txt nennt Pfade, die nicht gefunden werden sollen",
               ", ".join(heikel[:6]),
               "Die Datei ist oeffentlich. Wer wissen will, wo dein Adminbereich "
               "liegt, liest zuerst hier nach. Ein Disallow ist keine Sperre, "
               "sondern ein Hinweisschild.",
               "Heikle Pfade aus der robots.txt nehmen und stattdessen mit einem "
               "Passwort schuetzen.")
    else:
        befund("ok", 24, "robots.txt verraet keine heiklen Pfade", "", "", "")


ADMIN_PFADE = ["admin", "admin/", "wp-admin/", "login", "dashboard", "phpmyadmin/",
               "adminer.php", ".well-known/security.txt"]


def pruefe_adminbereiche(basis):
    offen = []
    for pfad in ADMIN_PFADE:
        if pfad == ".well-known/security.txt":
            continue
        st, _, text = hole(urllib.parse.urljoin(basis + "/", pfad), max_bytes=6000)
        if st == 200 and re.search(r"(?i)(<form|passwor|anmeld|login|sign in)", text):
            offen.append(pfad)
    if offen:
        befund("niedrig", 25, "Anmeldebereich ist oeffentlich erreichbar", ", ".join(offen),
               "Kein Fehler an sich, aber jeder Anmeldebereich im offenen Netz wird "
               "automatisiert durchprobiert. Ohne Limit auf den Anmeldeversuchen ist "
               "das nur eine Frage der Zeit.",
               "Anmeldeversuche pro IP begrenzen, Zwei-Faktor einschalten, und wenn "
               "nur du dich anmeldest, den Pfad zusaetzlich per Serverregel auf deine "
               "IP begrenzen.")
    else:
        befund("ok", 25, "Kein offen erreichbarer Anmeldebereich gefunden",
               f"{len(ADMIN_PFADE) - 1} Pfade geprueft", "", "")


# ------------------------------------- Block 5: Datenspuren beim ersten Aufruf

BEKANNTE_DRITTE = {
    "google-analytics.com": "Google Analytics",
    "googletagmanager.com": "Google Tag Manager",
    "fonts.googleapis.com": "Google Fonts",
    "fonts.gstatic.com": "Google Fonts",
    "connect.facebook.net": "Meta-Pixel",
    "facebook.com": "Meta",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "doubleclick.net": "Google-Werbung",
    "hotjar.com": "Hotjar",
    "clarity.ms": "Microsoft Clarity",
    "tiktok.com": "TikTok-Pixel",
    "linkedin.com/px": "LinkedIn-Pixel",
    "cdn.jsdelivr.net": "jsDelivr",
    "unpkg.com": "unpkg",
    "cdnjs.cloudflare.com": "cdnjs",
}


def pruefe_datenspuren(basis, html):
    eigen = urllib.parse.urlparse(basis).netloc
    fremde = set()
    for m in re.finditer(r'(?:src|href)=["\']([^"\']+)["\']', html):
        ziel = m.group(1)
        if ziel.startswith("//"):
            ziel = "https:" + ziel
        if not ziel.startswith("http"):
            continue
        host = urllib.parse.urlparse(ziel).netloc
        if host and host != eigen:
            for schnipsel, name in BEKANNTE_DRITTE.items():
                if schnipsel in ziel:
                    fremde.add(name)
                    break
            else:
                fremde.add(host)
    banner = bool(re.search(r"(?i)(cookie|consent|einwilligung)[-_a-z]*(banner|consent|manager|"
                            r"notice|klaro|usercentrics|cookiebot|borlabs)", html))
    if fremde:
        befund("mittel" if not banner else "niedrig", 21,
               "Beim ersten Aufruf gehen Verbindungen zu fremden Anbietern",
               ", ".join(sorted(fremde)[:8]) +
               ("  |  Einwilligungsloesung erkannt" if banner else
                "  |  keine Einwilligungsloesung im Quelltext gefunden"),
               "Technische Feststellung, keine rechtliche Bewertung: diese "
               "Verbindungen entstehen, sobald jemand die Seite oeffnet, und dabei "
               "geht die IP-Adresse des Besuchers an den jeweiligen Anbieter.",
               "Was davon vor einer Einwilligung laufen darf, entscheidet nicht "
               "dieses Skript. Technisch laesst sich jede dieser Dateien selbst "
               "ausliefern, dann entsteht die Verbindung gar nicht erst. "
               "Schriften zum Beispiel lokal einbinden statt von Google.")
    else:
        befund("ok", 21, "Keine Verbindungen zu fremden Anbietern beim ersten Aufruf",
               "", "", "")


# ------------------------------------------------------------------- Ausgabe

REIHE = {"kritisch": 0, "hoch": 1, "mittel": 2, "niedrig": 3, "ok": 4}
ZEICHEN = {"kritisch": "!!", "hoch": "! ", "mittel": "~ ", "niedrig": ". ", "ok": "ok"}


def ausgabe(basis):
    BEFUNDE.sort(key=lambda b: (REIHE[b["schwere"]], b["pruefung"]))
    echte = [b for b in BEFUNDE if b["schwere"] != "ok"]
    print()
    print("=" * 72)
    print(f"  SEITEN-CHECK  {basis}")
    print(f"  {datetime.datetime.now():%d.%m.%Y %H:%M}")
    print("=" * 72)
    for b in BEFUNDE:
        if b["schwere"] == "ok":
            continue
        print(f"\n[{ZEICHEN[b['schwere']]}] {b['schwere'].upper()}  Pruefung {b['pruefung']}: {b['titel']}")
        if b["gefunden"]:
            print(f"     Gefunden: {b['gefunden']}")
        if b["warum"]:
            print(f"     Warum das zaehlt: {b['warum']}")
        if b["beheben"]:
            print(f"     Beheben: {b['beheben']}")
    print("\n" + "-" * 72)
    print("  Ohne Befund durchgelaufen:")
    for b in BEFUNDE:
        if b["schwere"] == "ok":
            zusatz = f" ({b['gefunden']})" if b["gefunden"] else ""
            print(f"     ok  {b['titel']}{zusatz}")
    print("-" * 72)
    zaehler = {s: len([b for b in BEFUNDE if b["schwere"] == s]) for s in REIHE}
    print(f"\n  {len(BEFUNDE)} Pruefungen gelaufen, {len(echte)} Befunde: "
          f"{zaehler['kritisch']} kritisch, {zaehler['hoch']} hoch, "
          f"{zaehler['mittel']} mittel, {zaehler['niedrig']} niedrig.")
    print("\n  Das ist eine technische Pruefung von aussen. Sie ersetzt keinen "
          "Penetrationstest\n  und keine Rechtsberatung.\n")


def main():
    p = argparse.ArgumentParser(description="Seiten-Check, nur fuer die eigene Domain")
    p.add_argument("url")
    p.add_argument("--mir-gehoert-die-domain", action="store_true",
                   help="Bestaetigung, dass die Seite dir gehoert oder du beauftragt bist")
    p.add_argument("--json", metavar="DATEI", help="Bericht zusaetzlich als JSON")
    a = p.parse_args()

    if not a.mir_gehoert_die_domain:
        print("Abbruch: fremde Seiten zu pruefen kann strafbar sein (§ 202a StGB).\n"
              "Wenn die Seite dir gehoert, haeng --mir-gehoert-die-domain an.")
        sys.exit(2)

    basis = a.url.rstrip("/")
    if not basis.startswith("http"):
        basis = "https://" + basis

    status, headers, html = hole(basis)
    if status is None:
        print(f"Abbruch: {basis} ist nicht erreichbar.")
        sys.exit(1)

    teile = sammle_code(basis, html)

    pruefe_offene_pfade(basis)
    pruefe_verzeichnisauflistung(basis)
    pruefe_sourcemaps(basis, html)
    pruefe_schluessel(teile)
    pruefe_supabase(teile)
    pruefe_oeffentliche_env(teile)
    pruefe_https(basis)
    pruefe_header(basis, headers)
    pruefe_zertifikat(basis)
    pruefe_cookies(headers)
    pruefe_fehlerseite(basis)
    pruefe_pflichtseiten(basis, html)
    pruefe_mixed_content(basis, html)
    pruefe_formulare(basis, html)
    pruefe_robots(basis)
    pruefe_adminbereiche(basis)
    pruefe_datenspuren(basis, html)

    ausgabe(basis)

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"seite": basis, "zeitpunkt": datetime.datetime.now().isoformat(),
                       "befunde": BEFUNDE}, f, ensure_ascii=False, indent=2)
        print(f"  Bericht geschrieben: {a.json}\n")


if __name__ == "__main__":
    main()
