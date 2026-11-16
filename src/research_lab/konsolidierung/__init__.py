"""Konsolidierung der TIM-Studien (Nachrechnung, Datenaudit, einheitliche Kennzahlen).

Dieses Paket ist bewusst unabhängig von ``src.research_lab.backtest``: Die Nachrechnung von
S7b wird aus der Präregistrierung neu geschrieben und gegen die gespeicherten Trades
verglichen. Nur numpy wird benötigt. Der Holdout (ab 2025-01-01) wird von keinem Modul
geladen; ``daten.laden`` verweigert Zeitstempel ab dem Holdout-Beginn.
"""
