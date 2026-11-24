"""R-KI-1: the local AI decides at strong chart zones (paper only, Uzi 23.11.2026 "go KI").

Uzi 23.11.2026: "wenn viele Sachen übereinander lappen muss gewichtet werden ... TIM muss verstehen und nicht
einzelne Regeln testen, wir haben ja theoretisch die KI". Instead of one more fixed entry rule, TIM weights
overlapping chart marks (gamma walls, POCs, day/week/month levels, sessions, liquidation clusters, the busiest
price) into zone strength (``zones``), and when price runs into a strong zone the local model (Ollama, like KI1)
sees the whole picture and answers LONG, SHORT or NICHTS with entry, stop, target and one reason (``decide``).
Every answer is written to an append-only log before its outcome is known; ``decide.settle`` plays the paper
trade forward on later closed candles. Nothing here places orders.

0.2 (Uzi 24.11.2026 "die KI sollte smart money und das London sell off sehen"): the picture also holds the
trading session (Asia range, London/New York open, move since the open, Asia high/low taken) and smart-money
signs (spot vs perp CVD, OI 1h/4h, liquidations, liquidation clusters, big orders by side, premium); a new
session may ask again at a zone already asked about.
"""

RULE = "R-KI-1/0.2-entwurf"
RULE_DEEPSEEK = "R-KI-2/0.1-entwurf"   # DeepSeek decides itself, own log and paper account (Uzi 24.11.2026 "go deepseek")
SCHEMA = "tim_ki_entry_decision/1"
PROMPT_VERSION = "ki-einstieg/2"
ACTIONS = ("LONG", "SHORT", "NICHTS")
READINGS = ("HAELT", "BRICHT", "UNKLAR")   # 0.2: the AI states its reading before the action
