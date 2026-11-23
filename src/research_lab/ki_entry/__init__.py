"""R-KI-1: the local AI decides at strong chart zones (paper only, Uzi 23.11.2026 "go KI").

Uzi 23.11.2026: "wenn viele Sachen übereinander lappen muss gewichtet werden ... TIM muss verstehen und nicht
einzelne Regeln testen, wir haben ja theoretisch die KI". Instead of one more fixed entry rule, TIM weights
overlapping chart marks (gamma walls, POCs, day/week/month levels, sessions, liquidation clusters, the busiest
price) into zone strength (``zones``), and when price runs into a strong zone the local model (Ollama, like KI1)
sees the whole picture and answers LONG, SHORT or NICHTS with entry, stop, target and one reason (``decide``).
Every answer is written to an append-only log before its outcome is known; ``decide.settle`` plays the paper
trade forward on later closed candles. Nothing here places orders.
"""

RULE = "R-KI-1/0.1-entwurf"
SCHEMA = "tim_ki_entry_decision/1"
PROMPT_VERSION = "ki-einstieg/1"
ACTIONS = ("LONG", "SHORT", "NICHTS")
