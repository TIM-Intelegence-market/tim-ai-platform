import pytest
from src.tim_v2.simulation.models import SimulationRun
from src.tim_v2.simulation.registry import SimulationRegistry
def run(mode="PLANNED_ONLY"):return SimulationRun("run","scenario","dataset","decision","a"*64,"seed","event","risk","env","planned",mode)
def test_simulation_contract_is_immutable():r=SimulationRegistry();assert r.register(run())==run()
def test_execution_is_rejected():
 with pytest.raises(ValueError,match="SIMULATION_EXECUTION_FORBIDDEN"):SimulationRegistry().register(run("PAPER"))
