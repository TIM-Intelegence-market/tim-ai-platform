"""In-memory registry for immutable dataset manifests."""

from __future__ import annotations

from dataclasses import dataclass

from .models import DatasetVersion, ValidationState


@dataclass(frozen=True)
class RegistrationResult:
    dataset: DatasetVersion
    state: ValidationState
    issues: tuple[str, ...]
    manifest_sha256: str


class DatasetRegistry:
    """Catalogs metadata only; it never opens a source URI or copies data."""

    def __init__(self) -> None:
        self._entries: dict[str, RegistrationResult] = {}

    def register(self, dataset: DatasetVersion) -> RegistrationResult:
        if dataset.key in self._entries:
            raise ValueError(f"dataset version already registered: {dataset.key}")
        issues = list(dataset.issues())
        for reference in dataset.lineage:
            if reference not in self._entries:
                issues.append(f"LINEAGE_REFERENCE_NOT_FOUND:{reference}")
        if dataset.supersedes:
            predecessor = self._entries.get(dataset.supersedes)
            if predecessor is None:
                issues.append(f"SUPERSESSION_REFERENCE_NOT_FOUND:{dataset.supersedes}")
            elif predecessor.dataset.dataset_id != dataset.dataset_id:
                issues.append("SUPERSESSION_DATASET_ID_MISMATCH")
        result = RegistrationResult(
            dataset=dataset,
            state=ValidationState.VALID if not issues else ValidationState.QUARANTINED,
            issues=tuple(issues),
            manifest_sha256=dataset.manifest_sha256(),
        )
        self._entries[dataset.key] = result
        return result

    def get(self, key: str) -> RegistrationResult | None:
        return self._entries.get(key)

    def entries(self) -> tuple[RegistrationResult, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))
