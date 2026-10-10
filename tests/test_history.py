from datetime import date, timedelta
from pasture_wsc.history import DailyInput, replay
from pasture_wsc.model import SoilIndex, MoistureMode

A = date(2026,6,1)
INPUT = DailyInput(15,20,20,SoilIndex(.4,"external model wi",True), ("raw_hash",))
MODE = MoistureMode.DECREASING


def test_replay_idempotent_and_correction_propagates():
    inputs = {A:INPUT,A+timedelta(days=1):INPUT}
    result = replay(A,A+timedelta(days=1),inputs,MODE)
    assert result == replay(A,A+timedelta(days=1),inputs,MODE)
    assert result[1].spechr == 2*result[0].spechr
    corrected = dict(inputs)
    corrected[A] = DailyInput(10,20,20,INPUT.soil)
    new = replay(A,A+timedelta(days=1),corrected,MODE)
    assert new[1].spechr == result[0].spechr
    assert new[0].input_hash != result[0].input_hash
    assert new[1].input_hash != result[1].input_hash


def test_gap_blocks_all_later_accumulation_and_backfill_resolves():
    end = A+timedelta(days=2)
    inputs = {A:INPUT,end:INPUT}
    results = replay(A,end,inputs,MODE)
    assert results[0].spechr is not None
    assert results[1].spechr is results[2].spechr is None
    assert results[2].incomplete_history
    assert results[2].components.radiation_effect is not None
    inputs[A+timedelta(days=1)] = INPUT
    assert replay(A,end,inputs,MODE)[2].spechr is not None


def test_unknown_soil_and_scenario_separation():
    unknown = DailyInput(15,20,20)
    assert replay(A,A,{A:unknown},MODE)[0].spechr is None
    assumed = DailyInput(15,20,20,SoilIndex(.4,"explicit scenario",True,True), assumed_weather=True)
    assert replay(A,A,{A:assumed},MODE)[0].spechr is None
    result = replay(A,A,{A:assumed},MODE,scenario=True)[0]
    assert result.spechr is not None and result.components.status == "scenario"


def test_missing_radiation_blocks_wsc_but_not_development():
    entry = DailyInput(15,20,None,INPUT.soil)
    result = replay(A,A,{A:entry},MODE)[0]
    assert result.spechr is not None and result.components.experimental_wsc is None
