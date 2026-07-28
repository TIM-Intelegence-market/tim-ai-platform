from __future__ import annotations
import argparse,asyncio,json,os,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from src.operational.runner import OperationalValidator
PID=ROOT/"data/operational/validator.pid"
def alive(pid:int)->bool:
    try:os.kill(pid,0);return True
    except OSError:return False
def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--start",action="store_true");p.add_argument("--stop",action="store_true");p.add_argument("--status",action="store_true");p.add_argument("--duration",type=int,default=259200);p.add_argument("--interval",type=int,default=60);a=p.parse_args();pid=int(PID.read_text()) if PID.exists() and PID.read_text().strip().isdigit() else None
    if a.status:
        state=ROOT/"data/operational/state.json";print(state.read_text() if state.exists() else json.dumps({"status":"NOT_STARTED"}));return 0
    if a.start:
        if pid and alive(pid):print(json.dumps({"status":"ALREADY_RUNNING","pid":pid}));return 0
        PID.parent.mkdir(parents=True,exist_ok=True);log=(ROOT/"data/operational/process.log").open("a");process=subprocess.Popen([sys.executable,__file__,"--duration",str(a.duration),"--interval",str(a.interval)],cwd=ROOT,stdout=log,stderr=log,start_new_session=True);PID.write_text(str(process.pid));print(json.dumps({"status":"STARTED","pid":process.pid,"duration":a.duration}));return 0
    if a.stop:
        if pid and alive(pid):os.kill(pid,signal.SIGTERM)
        return 0
    validator=OperationalValidator(ROOT,a.duration,a.interval)
    def stop(*_):validator.stop_requested=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:print(json.dumps(asyncio.run(validator.run()),indent=2))
    finally:PID.unlink(missing_ok=True)
    return 0
if __name__=="__main__":raise SystemExit(main())
