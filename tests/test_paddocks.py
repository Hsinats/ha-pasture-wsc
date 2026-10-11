from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import pytest

from custom_components.pasture_wsc.paddocks import (initialize_paddocks,update_paddock,start_cycle,
                                                   calculate_paddock,moisture_day,validate_paddock)
from custom_components.pasture_wsc.storage import PastureStore
from tests.test_ha_phase2 import config,MemoryStore

DAY = date(2026,6,1)
A = datetime(2026,6,1,4,tzinfo=timezone.utc)


def state(**changes):
    data = {}
    initialize_paddocks(data,[{"id":"summer","name":"Summer","start_date":DAY.isoformat(),**changes}],"America/Toronto")
    return data["paddocks"]["summer"]


def weather(days=2,quality="observed"):
    return {DAY+timedelta(days=n):{"daylength":15,"hash":str(n),"timezone":"America/Toronto",
        "weather":{"temperature":{"value":20,"intervals":[{"quality":quality}]},
                   "solar_energy":{"value":20,"intervals":[{"quality":quality}]}}} for n in range(days)}


def soils(days=2,value=.4,unit="1"):
    return [{"paddock_id":"summer","timestamp":(A+timedelta(hours=h)).isoformat(),
             "reported":(A+timedelta(hours=h)).isoformat(),"freshness":3600,"value":value,"unit":unit,
             "status":"valid","compatible":True,"entity_id":"sensor.wi","semantics":"Documented balance index"}
            for h in range(24*days)]


def calibrated(**extra):
    return state(moisture_kind="calibrated_index",moisture_entity="sensor.wi",index_compatible=True,
        moisture_mode="one_minus_wi_over_reference",**extra)


def test_old_paddocks_initialize_once_without_losing_ids():
    data = {}
    p = {"id":"old","name":"Back","start_date":"2026-06-01"}
    initialize_paddocks(data,[p],"America/Toronto")
    cycle = deepcopy(data["paddocks"]["old"]["cycle"])
    initialize_paddocks(data,[p],"America/Winnipeg")
    assert data["paddocks"]["old"]["cycle"] == cycle
    assert data["paddocks"]["old"]["settings"]["scenario_enabled"] is False


def test_unknown_soil_never_zero_primary_but_components_continue():
    result = calculate_paddock(state(),DAY,weather(),[],config())["latest"]
    assert result["primary"]["spechr"] is result["primary"]["experimental_wsc"] is None
    assert result["status"] == "pending_soil"
    assert result["scenario"] == {}
    assert result["weather_effects"]["radiation_effect"] > 0


def test_primary_and_scenario_separate_with_estimated_weather():
    p = state(scenario_enabled=True,moisture_mode="one_minus_wi_over_reference")
    end = DAY+timedelta(days=1)
    result = calculate_paddock(p,end,weather(quality="estimated"),[],config())["latest"]
    assert result["primary"]["spechr"] is result["primary"]["experimental_wsc"] is None
    assert result["scenario"]["spechr"] > 0 and result["scenario"]["experimental_wsc"] is not None
    assert result["scenario"]["status"] == "scenario"
    assert result["gdd"] is None and result["scenario_gdd"] == 30


def test_complete_replay_idempotency_and_correction_propagation():
    p = calibrated()
    end = DAY+timedelta(days=1)
    result = calculate_paddock(p,end,weather(),soils(),config())
    assert result == calculate_paddock(p,end,weather(),soils(),config())
    assert result["records"][1]["primary"]["spechr"] == pytest.approx(2*result["records"][0]["primary"]["spechr"])
    assert result["latest"]["status"] == "ready_experimental"
    changed = weather()
    changed[DAY]["weather"]["temperature"]["value"] = 4
    changed[DAY]["hash"] = "corrected"
    corrected = calculate_paddock(p,end,changed,soils(),config())
    assert corrected["latest"]["primary"]["spechr"] < result["latest"]["primary"]["spechr"]
    assert corrected["latest"]["hash"] != result["latest"]["hash"]


def test_gap_blocks_later_primary_and_scenario_until_backfill():
    p = calibrated(scenario_enabled=True)
    end = DAY+timedelta(days=2)
    w = weather(3)
    w.pop(DAY+timedelta(days=1))
    result = calculate_paddock(p,end,w,soils(3),config())["latest"]
    assert result["history_gap"]
    assert result["primary"]["spechr"] is result["scenario"]["spechr"] is None
    assert result["gdd"] is None
    assert calculate_paddock(p,end,weather(3),soils(3),config())["latest"]["primary"]["spechr"] is not None


def test_moisture_semantics_units_mode_and_freshness():
    p = calibrated()
    assert calculate_paddock(p,DAY,weather(),soils(unit="%"),config())["latest"]["primary"]["experimental_wsc"] is None
    assert moisture_day(DAY,"America/Toronto","summer",soils()[:1],.8)["value"] is None
    update_paddock(p,{"moisture_mode":"unset"})
    result = calculate_paddock(p,DAY,weather(),soils(),config())["latest"]
    assert result["primary"]["spechr"] is not None and result["primary"]["experimental_wsc"] is None
    with pytest.raises(ValueError):
        validate_paddock({**p["settings"],"index_compatible":False})


def test_independent_confirmed_reset_archives_and_rejects_repeat():
    a,b = calibrated(),state()
    other = deepcopy(b)
    old = a["cycle"]["id"]
    now = A+timedelta(days=1)
    for confirmed,expected in ((False,old),(True,"wrong")):
        with pytest.raises(ValueError):
            start_cycle(a,DAY,now,"America/Toronto",confirmed=confirmed,expected_cycle=expected)
    assert a["cycle"]["id"] == old
    start_cycle(a,DAY+timedelta(days=1),now,"America/Toronto",confirmed=True,expected_cycle=old)
    assert a["cycle"]["id"] != old and a["archives"][0]["id"] == old
    assert b == other
    with pytest.raises(ValueError):
        start_cycle(a,DAY,now,"America/Toronto",confirmed=True,expected_cycle=old)
    assert calculate_paddock(a,DAY,weather(),soils(),config())["latest"]["status"] == "awaiting_first_completed_day"


def test_soil_dst_weighted_coverage():
    from custom_components.pasture_wsc.engine.astronomy import local_day_bounds
    for day,hours in ((date(2026,3,8),23),(date(2026,11,1),25)):
        a,b = local_day_bounds(day,"America/Toronto")
        rows = [{**soils(1)[0],"timestamp":(a+timedelta(hours=h)).isoformat(),"reported":(a+timedelta(hours=h)).isoformat()} for h in range(hours)]
        result = moisture_day(day,"America/Toronto","summer",rows,1)
        assert result["coverage"] == 1 and result["value"] == pytest.approx(.4)


def test_disabled_unchanged_cycle_and_reenable_replays():
    p = calibrated()
    cycle = deepcopy(p["cycle"])
    update_paddock(p,{"enabled":False})
    assert calculate_paddock(p,DAY,weather(),soils(),config())["latest"]["status"] == "disabled"
    update_paddock(p,{"enabled":True})
    assert p["cycle"] == cycle
    assert calculate_paddock(p,DAY,weather(),soils(),config())["latest"]["primary"]["spechr"] is not None


def test_results_versions_and_additive_storage_migration():
    import asyncio
    async def run():
        backend = MemoryStore()
        store = PastureStore(None,"entry",backend)
        await store.load()
        await store.save()
        for key in ("paddocks","paddock_results","soil_observations"):
            backend.data.pop(key)
        await store.load()
        assert store.data["paddocks"] == {}
        result = calculate_paddock(calibrated(),DAY,weather(),soils(),config())["latest"]
        assert store.paddock_result(result)
        assert not store.paddock_result(result)
        await store.save()
        restored = PastureStore(None,"entry",backend)
        await restored.load()
        assert restored.data["paddock_results"] == store.data["paddock_results"]
    asyncio.run(run())
