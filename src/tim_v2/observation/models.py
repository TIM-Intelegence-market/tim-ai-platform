from dataclasses import dataclass
from datetime import datetime
import hashlib,json,re
SHA=re.compile(r"^[0-9a-f]{64}$")
@dataclass(frozen=True)
class Observation:
    observation_id:str; dataset_key:str; event_time:datetime; observed_at:datetime; processed_at:datetime; value_reference:str; provenance:str; input_sha256:str
    def issues(self):
        checks=((bool(self.observation_id),"OBSERVATION_ID_REQUIRED"),(bool(self.dataset_key),"OBSERVATION_DATASET_REQUIRED"),(self.event_time.tzinfo is not None and self.observed_at.tzinfo is not None and self.processed_at.tzinfo is not None,"OBSERVATION_TIMEZONE_REQUIRED"),(self.event_time<=self.observed_at<=self.processed_at,"OBSERVATION_TIME_ORDER_INVALID"),(bool(self.value_reference),"OBSERVATION_VALUE_REFERENCE_REQUIRED"),(bool(self.provenance),"OBSERVATION_PROVENANCE_REQUIRED"),(bool(SHA.fullmatch(self.input_sha256)),"OBSERVATION_HASH_INVALID"))
        return tuple(code for ok,code in checks if not ok)
    def manifest_sha256(self):return hashlib.sha256(json.dumps(self.__dict__,sort_keys=True,default=lambda x:x.isoformat(),separators=(",",":")).encode()).hexdigest()
