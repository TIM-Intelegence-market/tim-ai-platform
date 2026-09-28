"""Compatibility layer: the dashboard now lives in several modules.

Existing imports such as ``from src.dashboard.app import DashboardServer`` keep working.
"""

from __future__ import annotations

from src.dashboard.constants import DASHBOARD_VERSION, VISIBLE_LIMIT, ORDERFLOW_VISIBLE_LIMIT, MAX_RESPONSE_BYTES, ALLOWED_TIMELINE_EVENTS  # noqa: F401
from src.dashboard.security import _require_loopback_host, _is_loopback_request_host  # noqa: F401
from src.dashboard.helpers import CASE_STATUS_BADGE, _case_status, _safe, _short, _parse_time, _duration, _age_seconds, _json_block, _status, _required, _status_level, _number  # noqa: F401
from src.dashboard.state import DashboardState  # noqa: F401
from src.dashboard.api import _research_cases_collection  # noqa: F401
from src.dashboard.components import _case_for_observation, _observation_row, _case_row, _issue_windows, _card_markup, _diagnostic_card, _timeline_rows, _quality_exception_rows, _signal_context_rows, _retrospective_outcome_rows, _case_proof_panel  # noqa: F401
from src.dashboard.pages.signals import _signal_research_page, _signal_research_rows  # noqa: F401
from src.dashboard.pages.operations import _data_quality_exceptions_page, _health_timeline_page, _health_center_sections  # noqa: F401
from src.dashboard.pages.setup_path import _setup_chart, _setup_path_page  # noqa: F401
from src.dashboard.layout import CSS, EXTRA_CSS, AUTO_REFRESH_SCRIPT, _content_security_policy, _content_security_policy_for, NAV_GROUPS, _strip_states, _error_page, _layout, _hero  # noqa: F401
from src.dashboard.views import render  # noqa: F401
from src.dashboard.i18n import DE, translate_html  # noqa: F401
from src.dashboard.pages.pilot import PILOT_CASE_FIELDS, render_pilot  # noqa: F401
from src.dashboard.server import DashboardServer  # noqa: F401

__all__ = ["CASE_STATUS_BADGE", "DE", "PILOT_CASE_FIELDS", "_case_proof_panel", "_case_status", "_content_security_policy_for", "render_pilot", "translate_html", "ALLOWED_TIMELINE_EVENTS", "AUTO_REFRESH_SCRIPT", "CSS", "DASHBOARD_VERSION", "DashboardServer", "DashboardState", "EXTRA_CSS", "MAX_RESPONSE_BYTES", "NAV_GROUPS", "ORDERFLOW_VISIBLE_LIMIT", "VISIBLE_LIMIT", "_age_seconds", "_card_markup", "_case_for_observation", "_case_row", "_content_security_policy", "_data_quality_exceptions_page", "_diagnostic_card", "_duration", "_error_page", "_health_center_sections", "_health_timeline_page", "_hero", "_is_loopback_request_host", "_issue_windows", "_json_block", "_layout", "_number", "_observation_row", "_parse_time", "_quality_exception_rows", "_require_loopback_host", "_required", "_research_cases_collection", "_retrospective_outcome_rows", "_safe", "_setup_chart", "_setup_path_page", "_short", "_signal_context_rows", "_signal_research_page", "_signal_research_rows", "_status", "_status_level", "_strip_states", "_timeline_rows", "render"]
