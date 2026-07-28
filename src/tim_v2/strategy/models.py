from dataclasses import dataclass

@dataclass(frozen=True)
class StrategyCandidate:
    strategy_id: str
    version: str
    policy_reference: str
    feature_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    risk_assumptions: str
    evaluation_state: str = "EVALUATION_REQUIRED"
    def issues(self):
        checks=((bool(self.strategy_id),"STRATEGY_ID_REQUIRED"),(bool(self.version),"STRATEGY_VERSION_REQUIRED"),(bool(self.policy_reference),"STRATEGY_POLICY_REQUIRED"),(bool(self.feature_refs),"STRATEGY_FEATURES_REQUIRED"),(bool(self.evidence_refs),"STRATEGY_EVIDENCE_REQUIRED"),(bool(self.risk_assumptions),"STRATEGY_RISK_REQUIRED"),(self.evaluation_state=="EVALUATION_REQUIRED","STRATEGY_EXECUTION_FORBIDDEN"))
        return tuple(code for ok,code in checks if not ok)
