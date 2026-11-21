# Modell-Router

Regel: zuerst das günstige Modell, nur bei Bedarf hochstufen. Der Router empfiehlt nur
(`src/llm/model_router.py`, Regeln in `config/model_router/routes.json`), er ruft kein Modell auf
und braucht keine Schlüssel.

```python
from src.llm.model_router import route, escalate
r = route("status")            # lokal_klein (qwen3.5:9b)
r = route(hat_bild=True)       # vision
r = route("studie")            # reasoning
r = route(privat=True)         # nur lokal, nie Cloud
escalate(r.stufe)              # nächste Stufe oder None
```

| Stufe | Modell | Wofür |
|---|---|---|
| lokal_klein | qwen3.5:9b | Status, Klassifizieren, Zusammenfassen, Masse (≥20 Aufrufe) |
| lokal_gross | qwen3-coder:30b | privat (Keys, Strategien, Rohdaten) |
| mittel | claude-sonnet-5-5 | Routine, Code, Standard |
| vision | claude-sonnet-5-5 | Bilder |
| reasoning | claude-opus-5-5 | Studien, Architektur, kritischer Review, ≥4 Schritte |

Vorrang: privat > Bild > Reasoning > Aufgabenart > Masse > Standard. Fällt lokal aus, geht
Nicht-Privates auf Cloud zurück; Privates bricht ab statt zu senden.
Passt zu den Subagenten in `.claude/agents/` (Sonnet Routine, Opus Studien) und zum
Qwen-Rückfall in `src/local_first/`. Änderungen der Zuordnung nur in `routes.json`.
Prüfen: `pytest tests/test_model_router.py`.
