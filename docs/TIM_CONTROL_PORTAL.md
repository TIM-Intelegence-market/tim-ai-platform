# T.I.M.E.C. — TIM Engineering Console

Das Portal stellt den lokalen Qwen-Worker, seine persistierten Aufgaben, technische Systemwerte, Benutzerkonten, menschliche Bewertungen und kontrollierte Trainingskampagnen dar.

## Sicherheitsmodell

- Der Anwendungsprozess bindet ausschließlich an `127.0.0.1`.
- Der interne HTTPS-Name wird ausschließlich über das private Netz/Tailscale an einen TLS-Reverse-Proxy angebunden. Keine WAN-Freigabe; Ollama, SSH und Datenbank werden nicht über den Portal-Proxy weitergeleitet.
- Registrierung erfolgt nur über einmalige, 24 Stunden gültige Viewer-Einladungen. Höhere Rollen benötigen einen begründeten Antrag und eine Administratorentscheidung.
- Jedes Mitglied wählt sein eigenes Passwort. Passwörter werden mit PBKDF2-HMAC-SHA256, zufälligem Salt und 600.000 Iterationen gespeichert.
- Rollen: `viewer`, `operator`, `admin`.
- Änderungsanträge dokumentieren Grund, geplante Änderung, Ressourcenwirkung und Rollback. Kritische eigene Administratoranträge benötigen einen zweiten Administrator.
- Persönliche API-Schlüssel werden gehasht gespeichert, laufen ab, sind widerrufbar und besitzen enge Scopes. API-Schlüssel dürfen keine Änderung freigeben.
- Der erste Administrator ist Eigentümer. Nur er darf Administratorrechte vergeben oder Administratorkonten deaktivieren. API-Geheimnisse bleiben beim jeweiligen Mitglied; Administratoren können Metadaten prüfen und Schlüssel widerrufen.
- Zustandsänderungen benötigen CSRF-Tokens und werden im Auditprotokoll gespeichert.
- Qwen-Tasks bleiben den vorhandenen lokalen Safety Gates unterworfen. Das Portal akzeptiert nur A0–A2.

## Kontrolliertes Lernen

`APPROVED_FOR_LEARNING` schreibt eine begrenzte, bereinigte Erfahrung nach `experience/approved.jsonl`. Der Worker darf diese Erfahrungen als Kontext verwenden; dadurch werden keine Modellgewichte verändert.

Eine Trainingskampagne dokumentiert Hypothese, Datensatzauswahl und Zielmetriken. Die vorgesehene Freigabekette lautet:

1. Hypothese
2. Datensatzprüfung und Deduplizierung
3. Simulation
4. getrennte Holdout-Evaluation
5. menschliche Freigabe
6. LoRA-Training auf einem getrennten GPU-Runner
7. Shadow-Test gegen das aktive Modell
8. ausdrückliche Aktivierung mit Rollback

Der Dell T330 besitzt keine Compute-GPU. Er kann Datensätze, Simulationen, Auswertungen und Freigaben verwalten, soll das 7B-Finetuning aber nicht selbst ausführen.

## Lokaler Start

```bash
PYTHONPATH=/srv/tim/repo /srv/tim/venv/bin/python /srv/tim/repo/scripts/run_tim_control_portal.py \
  --repo-root /srv/tim/repo \
  --state-root /srv/tim/data/local-first-runtime \
  --db /srv/tim/data/control-portal/portal.sqlite3
```

Der erste Administrator wird einmalig unter `/bootstrap` angelegt. Dazu den lokalen Start explizit um `--bootstrap` ergänzen, ohne Proxy-Hostname oder Secure-Cookie-Betrieb. Anschließend ohne diesen Schalter neu starten. Im normalen Dienst ist die Route auch bei leerer Datenbank gesperrt; nach dem ersten Konto ist sie immer gesperrt.

Die systemd-Vorlage liegt unter `deploy/tim-control-portal.service`. Für eine Domain werden in `/etc/tim/control-portal.env` ausschließlich öffentliche Laufzeitwerte eingetragen:

```text
TIM_PORTAL_ALLOWED_HOSTS=console.timec.home.arpa,127.0.0.1,localhost
TIM_PORTAL_COOKIE_SECURE=1
OLLAMA_BASE_URL=http://127.0.0.2:11434
```

Der Reverse Proxy leitet nur HTTPS an `127.0.0.1:8090` weiter. Port 8090 bleibt auf allen externen Interfaces geschlossen.

Für einen lokalen Test vom Laptop:

```powershell
ssh -i "$HOME\.ssh\tim_server_ed25519" -L 8090:127.0.0.1:8090 tim-server@192.168.10.121
```

Danach die lokale Portaladresse im Browser öffnen. `/bootstrap` ist nur während des expliziten lokalen Erststarts verfügbar.

## Herkunft und aktuelle Betriebsgrenze

Die Portaldateien stammen aus dem geschlossenen PR #80, Commit `41438249e15548d4599eeb5942c5575a1ca42362`, und stimmen dort mit dem deployed Portalstand `2fd86627924147256ede7fb4bcdb0ac0b2a4f009` überein. Sie werden gezielt auf `platform-main` übernommen; die alte Branch wird nicht pauschal gemergt. Die fehlende Verarbeitung freigegebener Erfahrungen im aktuellen Worker wird dabei wieder angebunden, mit Grenzen und ausdrücklicher Kennzeichnung als untrusted Kontext.

Die bestehende Server-Instanz heißt `timec.service`. Die systemd-Vorlage aktiviert keine neue Worker-Instanz. Im aktuellen Betriebsmodell koordiniert der Mac die GitHub-Issues, der Server liefert Modellantworten. Eine im Portal gespeicherte lokale Aufgabe beweist noch keine Abnahme ihrer Verarbeitung durch diesen GitHub-Worker; dafür ist eine gesonderte Anbindung erforderlich.
