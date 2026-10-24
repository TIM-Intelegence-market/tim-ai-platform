"""Read data sources for the cockpit with a time budget per source.

The old pilot page rendered thousands of cases and blocked the whole server
for more than 100 seconds. Here every source runs in its own daemon thread and
the page waits at most ``budget`` seconds for it. A slow source turns its tiles
grey ("antwortet nicht") instead of holding the page.

* While a call for a source is still running, a second request waits for that
  same call (with its own budget) instead of starting another one.
* Results are cached for a few seconds so page, fragment and API share a read.
* If a source runs over budget but answered within the last ``stale_seconds``,
  that last answer is shown (marked ``stale``) instead of grey tiles.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(slots=True)
class SourceResult:
    name: str
    ok: bool
    value: Any = None
    error: str = ""
    seconds: float = 0.0
    stale_seconds: float | None = None

    def reason(self) -> str:
        return self.error or ""


class BudgetedSources:
    def __init__(self, cache_seconds: float = 5.0, stale_seconds: float = 60.0) -> None:
        self.cache_seconds = cache_seconds
        self.stale_seconds = stale_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, SourceResult]] = {}
        self._last_good: dict[str, tuple[float, SourceResult]] = {}
        self._running: dict[str, tuple[threading.Thread, dict[str, Any]]] = {}

    def run(self, jobs: dict[str, Callable[[], Any]], budget: float = 1.5) -> dict[str, SourceResult]:
        """Run all jobs in parallel; wait at most ``budget`` seconds in total."""
        now = time.monotonic()
        results: dict[str, SourceResult] = {}
        waiting: dict[str, tuple[threading.Thread, dict[str, Any]]] = {}
        with self._lock:
            for name, job in jobs.items():
                cached = self._cache.get(name)
                if cached and now - cached[0] <= self.cache_seconds:
                    results[name] = cached[1]
                    continue
                running = self._running.get(name)
                if running and running[0].is_alive():
                    waiting[name] = running  # join the call already in flight
                    continue
                box: dict[str, Any] = {}
                thread = threading.Thread(target=self._call, args=(name, job, box), name=f"cockpit-{name}", daemon=True)
                self._running[name] = (thread, box)
                waiting[name] = (thread, box)
                thread.start()
        deadline = now + budget
        for name, (thread, box) in waiting.items():
            thread.join(max(0.0, deadline - time.monotonic()))
            result = box.get("result")
            results[name] = result if result is not None else self._over_budget(name, budget)
        return results

    def _over_budget(self, name: str, budget: float) -> SourceResult:
        with self._lock:
            last = self._last_good.get(name)
        if last:
            age = time.monotonic() - last[0]
            if age <= self.stale_seconds:
                old = last[1]
                return SourceResult(name, True, value=old.value, seconds=old.seconds, stale_seconds=round(age, 1),
                                    error=f"Quelle langsam (über {budget:g} s): Werte von vor {round(age)} s")
        return SourceResult(name, False, error=f"Quelle antwortet nicht innerhalb von {budget:g} s")

    def _call(self, name: str, job: Callable[[], Any], box: dict[str, Any]) -> None:
        began = time.monotonic()
        result = SourceResult(name, False, error="Quelle abgebrochen")
        try:
            result = SourceResult(name, True, value=job())
        except Exception as exc:  # noqa: BLE001 - a broken source becomes a grey tile with its reason
            result = SourceResult(name, False, error=f"Quelle nicht lesbar: {type(exc).__name__}: {str(exc)[:160]}")
        except BaseException as exc:  # noqa: BLE001 - SystemExit/KeyboardInterrupt in a source must not break the page
            result = SourceResult(name, False, error=f"Quelle abgebrochen: {type(exc).__name__}")
        finally:
            result.seconds = round(time.monotonic() - began, 3)
            box["result"] = result
            with self._lock:
                stamp = time.monotonic()
                self._cache[name] = (stamp, result)
                if result.ok:
                    self._last_good[name] = (stamp, result)
                running = self._running.get(name)
                if running and running[0] is threading.current_thread():
                    del self._running[name]
