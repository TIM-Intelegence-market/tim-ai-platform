"""Research run that ties the delivered evidence pieces together (#144).

One run collects web sources through a provider chain (Crawl4AI first, a browser provider only as a
policy-controlled fallback), turns documents into the canonical `Evidence` model with lineage, records telemetry
for every tool call, and accepts a research result only when every claim cites evidence of this run.

External capabilities stay opt-in: without `TIM_RESEARCH_WEB_ENABLED=1` no web fetch happens, and the browser
fallback additionally needs an enabled `BrowserPolicy` (off in CI and production). Remote content is data:
nothing in it can change the policy, and a policy refusal never falls through to another provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable
from urllib.parse import urlparse

from src.research_evidence.browser_policy import BrowserBudget, BrowserPolicy
from src.research_evidence.documents import DocumentError, DocumentProcessor
from src.research_evidence.model import Evidence, make_evidence
from src.research_evidence.result import validate_research_result
from src.research_evidence.url_policy import UrlPolicy, check_url
from src.research_evidence.web import FetchError, WebResearchProvider

# A refusal by policy is final; only these provider failures may try the fallback.
FALLBACK_CODES = frozenset({'transport', 'parse', 'http_403', 'http_429', 'http_500', 'http_502', 'http_503',
                            'http_504', 'empty'})


@dataclass
class ResearchRun:
    run_id: str
    evidence: dict[str, Evidence] = field(default_factory=dict)
    telemetry: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)


class ResearchOrchestrator:
    def __init__(self, *, url_policy: UrlPolicy, primary: WebResearchProvider | None = None,
                 fallback: WebResearchProvider | None = None, browser_policy: BrowserPolicy | None = None,
                 env: dict | None = None, clock: Callable[[], float], timeout_seconds: float = 30.0) -> None:
        self.url_policy = url_policy
        self.primary = primary
        self.fallback = fallback
        self.browser_policy = browser_policy or BrowserPolicy()
        self.web_enabled = (env or {}).get('TIM_RESEARCH_WEB_ENABLED') == '1'
        self.clock = clock
        self.timeout_seconds = timeout_seconds

    def start(self, question: str) -> ResearchRun:
        if not isinstance(question, str) or not question.strip():
            raise ValueError('question must be a non-empty string')
        return ResearchRun(run_id='run_' + sha256(f'{question}\n{self.clock()}'.encode()).hexdigest()[:16])

    def _call(self, run: ResearchRun, tool: str, provider: str, target: str, action):
        started = self.clock()
        entry = {'run_id': run.run_id, 'tool': tool, 'provider': provider, 'target': target, 'start': started}
        try:
            result = action()
        except (FetchError, DocumentError) as exc:
            entry.update(ok=False, error=exc.code, end=self.clock())
            run.telemetry.append(entry)
            raise
        except Exception as exc:          # unexpected provider behaviour is a classified failure, not a crash
            entry.update(ok=False, error='provider_error', end=self.clock())
            run.telemetry.append(entry)
            raise FetchError('provider_error') from exc
        entry.update(ok=True, end=self.clock(), bytes=len(result.content.encode()) if isinstance(result, Evidence) else None)
        run.telemetry.append(entry)
        return result

    def fetch_web(self, run: ResearchRun, url: str) -> Evidence | None:
        """Fetch one source; a failure is recorded on the run and never corrupts the evidence collected so far."""
        domain = (urlparse(url).hostname or '') if isinstance(url, str) else ''
        if not self.web_enabled:
            run.failures.append({'url_domain': domain, 'code': 'web_disabled'})
            return None
        allowed, reason = check_url(url, self.url_policy)
        if not allowed:
            run.failures.append({'url_domain': domain, 'code': 'policy', 'reason': reason})
            return None
        if self.primary is None:
            run.failures.append({'url_domain': domain, 'code': 'no_provider'})
            return None
        try:
            evidence = self._call(run, 'fetch_web_source', self.primary.name, domain,
                                  lambda: self.primary.fetch(url, timeout_seconds=self.timeout_seconds))
        except FetchError as exc:
            if exc.code not in FALLBACK_CODES or not self._fallback_allowed(run, url, domain, exc.code):
                run.failures.append({'url_domain': domain, 'code': exc.code, 'provider': self.primary.name})
                return None
            try:
                evidence = self._call(run, 'fetch_web_source', self.fallback.name, domain,
                                      lambda: self.fallback.fetch(url, timeout_seconds=self.timeout_seconds))
            except FetchError as second:
                run.failures.append({'url_domain': domain, 'code': second.code, 'provider': self.fallback.name,
                                     'fallback_reason': exc.code})
                return None
        return self._keep(run, evidence, url)

    def _fallback_allowed(self, run: ResearchRun, url: str, domain: str, code: str) -> bool:
        if self.fallback is None:
            return False
        budget = BrowserBudget(self.browser_policy, self.clock)
        try:
            budget.start()
        except PermissionError:
            run.telemetry.append({'run_id': run.run_id, 'tool': 'browser_fallback', 'target': domain,
                                  'ok': False, 'error': 'fallback_disabled', 'fallback_reason': code})
            return False
        allowed = budget.navigate(url)
        run.telemetry.append({'run_id': run.run_id, 'tool': 'browser_fallback', 'target': domain, 'ok': allowed,
                              'fallback_reason': code, 'audit': budget.audit()})
        return allowed

    def _keep(self, run: ResearchRun, evidence, url: str) -> Evidence | None:
        domain = urlparse(url).hostname or ''
        if not isinstance(evidence, Evidence):
            run.failures.append({'url_domain': domain, 'code': 'not_evidence'})
            return None
        final = evidence.metadata.get('final_url', evidence.source_uri)
        if not check_url(str(final), self.url_policy)[0]:        # a redirect to a private/denied target is dropped
            run.failures.append({'url_domain': domain, 'code': 'redirect_policy'})
            return None
        run.evidence[evidence.evidence_id] = evidence
        return evidence

    def process_document(self, run: ResearchRun, processor: DocumentProcessor, data: bytes, *,
                         filename: str) -> Evidence | None:
        """Turn a processor result into canonical evidence whose lineage names the original file hash."""
        try:
            raw = self._call(run, 'process_document', processor.name, filename,
                             lambda: processor.extract_text(data, filename=filename, timeout_seconds=self.timeout_seconds))
        except (FetchError, DocumentError) as exc:
            run.failures.append({'document': filename, 'code': exc.code, 'provider': processor.name})
            return None
        original = 'sha256:' + sha256(data).hexdigest()
        metadata = {k: v for k, v in dict(raw.metadata).items() if type(v) in (str, int, float, bool)}
        evidence = make_evidence(source_uri=raw.source_uri, source_type=raw.source_type, provider=raw.provider,
                                 extraction_method=raw.extraction_method, title=raw.title, content=raw.text,
                                 retrieved_at=self._iso(), metadata={**metadata, 'original_file_hash': original},
                                 parent_ids=(original,))
        run.evidence[evidence.evidence_id] = evidence
        return evidence

    def _iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), tz=timezone.utc).isoformat()

    def finish(self, run: ResearchRun, result) -> dict:
        """Accept the result only when every claim cites evidence collected in this run."""
        check = validate_research_result(result, run.evidence.keys())
        return {'run_id': run.run_id, 'accepted': check['ok'], 'errors': check['errors'],
                'result': result if check['ok'] else None,
                'evidence': [e.to_dict() for e in sorted(run.evidence.values(), key=lambda e: e.evidence_id)],
                'failures': list(run.failures), 'telemetry': list(run.telemetry)}
