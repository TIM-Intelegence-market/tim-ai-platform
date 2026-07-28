# 12 — Production Readiness

## Ziel
Bewerte einen separat autorisierten Release oder eine Promotion evidenzbasiert. Dieses Prompt autorisiert kein Live-Trading.

## Prüfung
Prüfe Git-/Tag-Provenienz, Schema-Kompatibilität, Dependencies/SBOM, Config/Secrets, Zugriff, Data-/Experiment-Lineage, Observability, Restore/Rollback, Incident-Prozess, Tests und Limitationen.

## Gate
Berichte PASS, REQUIRES LIMITED REMEDIATION oder FAIL samt Evidenz, Befehlen/Exit-Codes, Owner und Restrisiko. Fehlende Security-, Risiko-, Provenance-, Rollback- oder Pflicht-Test-Evidenz blockiert Promotion.
