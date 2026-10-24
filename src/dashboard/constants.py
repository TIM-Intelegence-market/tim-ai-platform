from __future__ import annotations


DASHBOARD_VERSION = "4.1.0"


VISIBLE_LIMIT = 50


ORDERFLOW_VISIBLE_LIMIT = 100


CHART_CANDLE_LIMIT = 500  # /chart: newest candles kept per timeframe (same depth as runtime history)


HISTORY_LIMIT = 2000  # /api/orderflow/history: newest observations and validations each
MAX_RESPONSE_BYTES = 2_000_000


ALLOWED_TIMELINE_EVENTS = {
    "RUNTIME_START",
    "VALIDATION_CYCLE",
    "RESEARCH_CYCLE_CHECK",
    "ACCEPTANCE_CHECK",
    "CONTROLLED_API_FAILURE",
    "UNCONTROLLED_API_FAILURE",
    "VALIDATOR_RECOVERY",
    "DATA_GAP",
    "RESTART",
}
