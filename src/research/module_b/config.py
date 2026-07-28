from dataclasses import dataclass


@dataclass(frozen=True,slots=True)
class ModuleBConfig:
    enabled:bool=False
    minimum_words:int=2000
    require_citations:bool=True
    allow_network:bool=False
