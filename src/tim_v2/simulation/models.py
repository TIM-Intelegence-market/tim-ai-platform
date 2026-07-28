from dataclasses import dataclass
@dataclass(frozen=True)
class SimulationRun:
    run_id:str; scenario_ref:str; dataset_ref:str; decision_ref:str; configuration_hash:str; seed:str; time_semantics:str; risk_assumptions:str; environment_id:str; termination_reason:str; mode:str="PLANNED_ONLY"
    def issues(self):
        checks=((bool(self.run_id and self.scenario_ref and self.dataset_ref and self.decision_ref and self.configuration_hash and self.seed and self.time_semantics and self.risk_assumptions and self.environment_id and self.termination_reason),"SIMULATION_MANIFEST_INCOMPLETE"),(self.mode=="PLANNED_ONLY","SIMULATION_EXECUTION_FORBIDDEN"))
        return tuple(code for ok,code in checks if not ok)
