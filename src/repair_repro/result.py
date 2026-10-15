from dataclasses import dataclass
from enum import Enum
from typing import Any


class ReproStatus(str, Enum):
    REPRODUCED = "REPRODUCED"
    NOT_REPRODUCED = "NOT_REPRODUCED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class ReproResult:
    case_id: str
    status: ReproStatus
    reason: str = ""
    evidence_refs: tuple[str, ...] = ()
    production_touched: bool = False
    real_process_calls: int = 0
    database_connections: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id:
            raise ValueError("case_id must be a non-empty string")
        if not isinstance(self.status, ReproStatus):
            raise ValueError("status must be a ReproStatus")
        if not isinstance(self.reason, str):
            raise ValueError("reason must be a string")
        if not isinstance(self.evidence_refs, tuple) or not all(
            isinstance(ref, str) for ref in self.evidence_refs
        ):
            raise ValueError("evidence_refs must be a tuple of strings")
        if self.status is ReproStatus.REPRODUCED and not self.evidence_refs:
            raise ValueError("REPRODUCED requires evidence_refs")
        if self.status is ReproStatus.INSUFFICIENT_EVIDENCE and not self.reason:
            raise ValueError("INSUFFICIENT_EVIDENCE requires a reason")
        if self.production_touched is not False:
            raise ValueError("production_touched must be False")
        for name, value in (
            ("real_process_calls", self.real_process_calls),
            ("database_connections", self.database_connections),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status.value,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "production_touched": self.production_touched,
            "real_process_calls": self.real_process_calls,
            "database_connections": self.database_connections,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReproResult":
        if not isinstance(data, dict):
            raise ValueError("data must be a dictionary")
        allowed = {
            "case_id",
            "status",
            "reason",
            "evidence_refs",
            "production_touched",
            "real_process_calls",
            "database_connections",
        }
        unknown = set(data) - allowed
        if unknown:
            raise ValueError("unknown keys")
        if "case_id" not in data or "status" not in data:
            raise ValueError("case_id and status are required")

        if not isinstance(data["case_id"], str):
            raise ValueError("case_id must be a string")
        if not isinstance(data["status"], str):
            raise ValueError("status must be a string")
        try:
            status = ReproStatus(data["status"])
        except ValueError as exc:
            raise ValueError("unknown status") from exc

        values: dict[str, Any] = {
            "case_id": data["case_id"],
            "status": status,
        }
        if "reason" in data:
            if not isinstance(data["reason"], str):
                raise ValueError("reason must be a string")
            values["reason"] = data["reason"]
        if "evidence_refs" in data:
            refs = data["evidence_refs"]
            if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
                raise ValueError("evidence_refs must be a list of strings")
            values["evidence_refs"] = tuple(refs)
        if "production_touched" in data:
            if not isinstance(data["production_touched"], bool):
                raise ValueError("production_touched must be a bool")
            values["production_touched"] = data["production_touched"]
        for name in ("real_process_calls", "database_connections"):
            if name in data:
                value = data[name]
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"{name} must be an integer")
                values[name] = value
        return cls(**values)
