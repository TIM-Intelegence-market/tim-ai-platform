from dataclasses import dataclass
@dataclass(frozen=True)
class EvaluationPlan:
    evaluation_id:str; candidate_ref:str; hypothesis_ref:str; dataset_manifest:str; split_manifest:str; event_time_policy:str; metrics:tuple[str,...]; benchmark:str; seed_policy:str; cost_assumptions:str; robustness_plan:str; limitations:tuple[str,...]; promotion_rule:str; methods:tuple[str,...]; leakage_safe:bool; holdout_safe:bool; provenance_complete:bool; risk_constraints_present:bool
    def issues(self):
        checks=((bool(self.evaluation_id),"EVALUATION_ID_REQUIRED"),(bool(self.candidate_ref),"EVALUATION_CANDIDATE_REQUIRED"),(bool(self.hypothesis_ref),"EVALUATION_HYPOTHESIS_REQUIRED"),(bool(self.dataset_manifest and self.split_manifest),"EVALUATION_MANIFEST_REQUIRED"),(bool(self.event_time_policy and self.metrics and self.benchmark and self.seed_policy and self.cost_assumptions and self.robustness_plan and self.promotion_rule),"EVALUATION_PLAN_INCOMPLETE"),(self.leakage_safe,"EVALUATION_LEAKAGE_BLOCK"),(self.holdout_safe,"EVALUATION_HOLDOUT_BLOCK"),(self.provenance_complete,"EVALUATION_PROVENANCE_BLOCK"),(self.risk_constraints_present,"EVALUATION_RISK_BLOCK"))
        return tuple(code for ok,code in checks if not ok)
