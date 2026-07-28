# 07 — Simulation Platform

## Ziel
Entwirf isolierte Replay-, Historical-, Scenario-, Stress-, Chaos- und Failure-Injection-Verträge.

## Manifest und Grenze
Jeder Run referenziert Szenario, Dataset, Decision/Model-Version, Config, Seed, Zeitsemantik, Risikoannahmen, Umgebung, Artefakte und Abbruchgrund. Paper nutzt simulierte Ausführung; Shadow beobachtet Live-Inputs und sendet null Orders. Kein Broker, Credential, Live-Adapter oder automatischer Auftrag.
