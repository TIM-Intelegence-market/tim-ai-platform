from dataclasses import dataclass
from enum import Enum


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    SKIP = "skip"


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: GateStatus
    reason: str = ""
    evidence_refs: tuple[str, ...] = ()
    git_sha: str | None = None
    config_hash: str | None = None

    def __post_init__(self) -> None:
        if type(self.gate) is not str or not self.gate:
            raise ValueError("gate must be a non-empty string")
        if not isinstance(self.status, GateStatus):
            raise ValueError("status must be a GateStatus")
        if type(self.reason) is not str:
            raise ValueError("reason must be a string")
        if type(self.evidence_refs) is not tuple or any(
            type(ref) is not str for ref in self.evidence_refs
        ):
            raise ValueError("evidence_refs must be a tuple of strings")
        if self.git_sha is not None and type(self.git_sha) is not str:
            raise ValueError("git_sha must be a string or None")
        if self.config_hash is not None and type(self.config_hash) is not str:
            raise ValueError("config_hash must be a string or None")
        if self.status is not GateStatus.PASS and not self.reason:
            raise ValueError("reason is required for non-pass results")

    def to_dict(self) -> dict[str, object]:
        return {
            "gate": self.gate,
            "status": self.status.value,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "git_sha": self.git_sha,
            "config_hash": self.config_hash,
        }

    @classmethod
    def from_dict(cls, data: object) -> "GateResult":
        if not isinstance(data, dict):
            raise ValueError("data must be a dictionary")

        allowed = {"gate", "status", "reason", "evidence_refs", "git_sha", "config_hash"}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError("unknown keys")
        if "gate" not in data or "status" not in data:
            raise ValueError("gate and status are required")

        gate = data["gate"]
        status = data["status"]
        reason = data.get("reason", "")
        evidence_refs = data.get("evidence_refs", [])
        git_sha = data.get("git_sha")
        config_hash = data.get("config_hash")

        if type(gate) is not str or not gate:
            raise ValueError("gate must be a non-empty string")
        if type(status) is not str:
            raise ValueError("status must be a string")
        try:
            parsed_status = GateStatus(status)
        except ValueError as exc:
            raise ValueError("unknown status") from exc
        if type(reason) is not str:
            raise ValueError("reason must be a string")
        if type(evidence_refs) is not list or any(
            type(ref) is not str for ref in evidence_refs
        ):
            raise ValueError("evidence_refs must be a list of strings")
        if git_sha is not None and type(git_sha) is not str:
            raise ValueError("git_sha must be a string or None")
        if config_hash is not None and type(config_hash) is not str:
            raise ValueError("config_hash must be a string or None")
        if parsed_status is not GateStatus.PASS and not reason:
            raise ValueError("reason is required for non-pass results")

        return cls(
            gate=gate,
            status=parsed_status,
            reason=reason,
            evidence_refs=tuple(evidence_refs),
            git_sha=git_sha,
            config_hash=config_hash,
        )
