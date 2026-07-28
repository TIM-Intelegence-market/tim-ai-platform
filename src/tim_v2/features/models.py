from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib, json, re
SEMVER=re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
@dataclass(frozen=True)
class FeatureValidity:
    start: datetime
    end: datetime
    def valid(self)->bool:return self.start.tzinfo is not None and self.end.tzinfo is not None and self.start<=self.end
@dataclass(frozen=True)
class FeatureDefinition:
    feature_id:str; version:str; definition:str; source_dataset_key:str; source_fields:tuple[str,...]; time_alignment:str; computation_contract:str; dependencies:tuple[str,...]; code_version:str; configuration_hash:str; deterministic:bool; lookahead_policy:str; quality_policy:str; estimated_cost:str; owner:str; validity:FeatureValidity; deprecated:bool=False
    def manifest_sha256(self)->str:
        value=asdict(self);value["validity"]={k:v.isoformat() for k,v in value["validity"].items()}
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    def issues(self)->tuple[str,...]:
        items=((bool(self.feature_id),"FEATURE_ID_REQUIRED"),(bool(SEMVER.fullmatch(self.version)),"FEATURE_VERSION_INVALID"),(bool(self.definition),"FEATURE_DEFINITION_REQUIRED"),(bool(self.source_dataset_key),"FEATURE_SOURCE_REQUIRED"),(bool(self.source_fields),"FEATURE_FIELDS_REQUIRED"),(bool(self.time_alignment),"FEATURE_TIME_ALIGNMENT_REQUIRED"),(bool(self.computation_contract),"FEATURE_COMPUTATION_REQUIRED"),(self.deterministic,"FEATURE_DETERMINISM_REQUIRED"),(bool(self.lookahead_policy),"FEATURE_LOOKAHEAD_REQUIRED"),(bool(self.quality_policy),"FEATURE_QUALITY_REQUIRED"),(bool(self.estimated_cost),"FEATURE_COST_REQUIRED"),(bool(self.owner),"FEATURE_OWNER_REQUIRED"),(self.validity.valid(),"FEATURE_VALIDITY_INVALID"),(len(set(self.dependencies))==len(self.dependencies),"FEATURE_DEPENDENCY_DUPLICATE"))
        return tuple(code for ok,code in items if not ok)
