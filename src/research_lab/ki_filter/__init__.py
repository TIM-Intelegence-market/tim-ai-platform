"""KI1: a local AI judges each new TIM plan (NEHMEN / AUSLASSEN) in shadow mode.

Paper only. Nothing here touches the live trader, an exchange or an order. Every judgement is
written to an append-only, hash-chained log before the plan's outcome is known; the evaluation
compares the rules alone with rules plus AI on the same plans (docs/research_lab/studien/
KI1_KI_FILTER_PRAEREGISTRIERUNG_ENTWURF.md).
"""
SCHEMA = "tim_ki_filter/1"
PROMPT_VERSION = "ki1-prompt/2"  # /2: without evidence and decision labels
NEHMEN, AUSLASSEN = "NEHMEN", "AUSLASSEN"
DECISIONS = (NEHMEN, AUSLASSEN)
