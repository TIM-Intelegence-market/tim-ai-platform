# 05 — Feature Platform

## Ziel
Definiere Feature-Verträge; berechne keine Features ohne separaten Auftrag.

## Pflichtfelder
ID/Version, Definition, Quelle, Zeit-Alignment, Berechnung, Dependency-DAG, Code/Config-Identität, Determinismus, Lookahead-Policy, Qualität, Kosten, Owner, Gültigkeit und Deprecation.

## Gates
Verwerfe unbekannte Provenienz, Schema-Mismatch, Zyklen und unklare Zeitlogik. Materialisierte Werte referenzieren unveränderliche Input-/Code-/Config-Manifeste. Features wählen keine Strategie und führen nichts aus.
