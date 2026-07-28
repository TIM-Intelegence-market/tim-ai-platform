from __future__ import annotations

from dataclasses import dataclass

from .models import ExperimentPlan, ExperimentResult, Hypothesis, PeerReview, ResearchArtifact, ResearchJob, ResearchSession, ResearchStatus


@dataclass(frozen=True)
class ReplayResult:
    plan_id: str
    manifest_sha256: str
    state: str


class ResearchRegistry:
    """Metadata registry only. It cannot execute a study or write to TIM-IM."""
    def __init__(self) -> None:
        self._hypotheses: dict[str, Hypothesis] = {}
        self._plans: dict[str, ExperimentPlan] = {}
        self._sessions: dict[str, ResearchSession] = {}
        self._jobs: dict[str, ResearchJob] = {}
        self._artifacts: dict[str, ResearchArtifact] = {}
        self._results: dict[str, ExperimentResult] = {}
        self._reviews: dict[str, PeerReview] = {}

    def add_hypothesis(self, value: Hypothesis) -> Hypothesis:
        if not value.proposition.strip() or not value.evidence_ids or not 0 <= value.confidence <= 1 or value.valid_from > value.valid_until:
            raise ValueError("HYPOTHESIS_INVALID")
        return self._insert(self._hypotheses, value.hypothesis_id, value)

    def add_plan(self, value: ExperimentPlan) -> ExperimentPlan:
        if value.hypothesis_id not in self._hypotheses or not all((value.dataset_key, value.metric, value.split_manifest, value.leakage_control, value.code_version, value.configuration_hash)):
            raise ValueError("EXPERIMENT_PLAN_INVALID")
        return self._insert(self._plans, value.plan_id, value)

    def add_session(self, value: ResearchSession) -> ResearchSession:
        if value.plan_id not in self._plans or value.created_at.tzinfo is None or not value.environment_id:
            raise ValueError("RESEARCH_SESSION_INVALID")
        return self._insert(self._sessions, value.session_id, value)

    def add_job(self, value: ResearchJob) -> ResearchJob:
        if value.session_id not in self._sessions or value.status != "PLANNED":
            raise ValueError("RESEARCH_JOB_INVALID")
        return self._insert(self._jobs, value.job_id, value)

    def add_artifact(self, value: ResearchArtifact) -> ResearchArtifact:
        if value.job_id not in self._jobs or len(value.content_sha256) != 64 or not value.kind:
            raise ValueError("RESEARCH_ARTIFACT_INVALID")
        return self._insert(self._artifacts, value.artifact_id, value)

    def add_result(self, value: ExperimentResult) -> ExperimentResult:
        if value.plan_id not in self._plans or any(key not in self._artifacts for key in value.artifact_ids) or not value.statistic_reference or len(value.reproducibility_hash) != 64:
            raise ValueError("EXPERIMENT_RESULT_INVALID")
        return self._insert(self._results, value.result_id, value)

    def add_review(self, value: PeerReview) -> PeerReview:
        if value.result_id not in self._results or not value.reviewer or not value.outcome:
            raise ValueError("PEER_REVIEW_INVALID")
        return self._insert(self._reviews, value.review_id, value)

    def replay(self, plan_id: str) -> ReplayResult:
        plan = self._plans.get(plan_id)
        if plan is None:
            return ReplayResult(plan_id, "", "ABSTAIN")
        return ReplayResult(plan_id, plan.manifest_sha256(), "PLANNED_REPLAY_ONLY")

    @staticmethod
    def _insert(store: dict[str, object], key: str, value: object):
        existing = store.get(key)
        if existing is None:
            store[key] = value
        elif existing != value:
            raise ValueError(f"IMMUTABLE_RECORD_CONFLICT:{key}")
        return value
