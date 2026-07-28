from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimeMetrics:
    timestamp: datetime
    pid: int
    rss_mb: float
    cpu_percent: float
    disk_free_mb: float
    disk_used_percent: float

    def to_dict(self) -> dict:
        result=asdict(self);result["timestamp"]=self.timestamp.isoformat();return result


class MetricsCollector:
    def __init__(self,path:Path,pid:int|None=None)->None:self.path=path;self.pid=pid or os.getpid()
    def collect(self)->RuntimeMetrics:
        rss=cpu=0.0
        try:
            output=subprocess.check_output(["ps","-o","rss=,%cpu=","-p",str(self.pid)],text=True,timeout=3).strip().split();rss=float(output[0])/1024;cpu=float(output[1])
        except (OSError,ValueError,IndexError,subprocess.SubprocessError):pass
        usage=shutil.disk_usage(self.path);used=(usage.total-usage.free)/usage.total*100 if usage.total else 0
        return RuntimeMetrics(datetime.now(timezone.utc),self.pid,round(rss,3),round(cpu,3),round(usage.free/1024/1024,3),round(used,3))
