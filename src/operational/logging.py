from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

class StructuredLog:
    def __init__(self,path:Path)->None:self.path=path;path.parent.mkdir(parents=True,exist_ok=True)
    def write(self,event:str,severity:str="INFO",**fields:Any)->None:
        row={"timestamp":datetime.now(timezone.utc).isoformat(),"event":event,"severity":severity,**fields}
        with self.path.open("a",encoding="utf-8") as handle:handle.write(json.dumps(row,sort_keys=True,default=str)+"\n");handle.flush();os.fsync(handle.fileno())
