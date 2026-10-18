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


def test_soil_type_inherits_once_and_is_independent_per_paddock():
    data = {}
    configured = [{"id":pid,"name":pid,"start_date":DAY.isoformat()} for pid in ("a","b")]
    initialize_paddocks(data,configured,"America/Toronto",soil_type="clay")
    assert all(p["settings"]["soil_type"] == "clay" for p in data["paddocks"].values())
    update_paddock(data["paddocks"]["a"],{"soil_type":"sandy"})
    data["paddocks"]["b"]["settings"].pop("soil_type")
    initialize_paddocks(data,configured,"America/Toronto",soil_type="loam")
    assert data["paddocks"]["a"]["settings"]["soil_type"] == "sandy"
    assert data["paddocks"]["b"]["settings"]["soil_type"] == "loam"
    with pytest.raises(ValueError,match="Unknown soil type"):
        update_paddock(data["paddocks"]["a"],{"soil_type":"invalid"})


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


def test_daily_change_uses_final_wsc_with_fallback_and_route_changes():
    from custom_components.pasture_wsc.paddocks import selected_wsc
    p = calibrated(scenario_enabled=True)
    w = weather(3)
    # Estimated radiation forces only the middle day onto the scenario route,
    # without breaking primary development history.
    w[DAY+timedelta(days=1)]["weather"]["solar_energy"]["intervals"] = [{"quality":"estimated"}]
    rows = calculate_paddock(p,DAY+timedelta(days=2),w,soils(3),config())["records"]
    assert [selected_wsc(row,p["settings"])[0] for row in rows] == ["primary","scenario","primary"]
    assert rows[0]["daily_change"] is None
    assert rows[0]["scenario_daily_change"] is None
    for previous,current in zip(rows,rows[1:]):
        assert current["daily_change"] == pytest.approx(
            selected_wsc(current,p["settings"])[1]-selected_wsc(previous,p["settings"])[1])
        assert current["scenario_daily_change"] == pytest.approx(
            current["scenario"]["experimental_wsc"]-previous["scenario"]["experimental_wsc"])


def test_daily_change_does_not_bridge_missing_wsc_and_backfill_repairs_it():
    p = calibrated(scenario_enabled=True)
    w = weather(4)
    w[DAY+timedelta(days=1)]["weather"]["solar_energy"]["value"] = None
    rows = calculate_paddock(p,DAY+timedelta(days=3),w,soils(4),config())["records"]
    assert rows[1]["daily_change"] is rows[2]["daily_change"] is None
    assert rows[1]["scenario_daily_change"] is rows[2]["scenario_daily_change"] is None
    assert rows[3]["daily_change"] is not None
    repaired = calculate_paddock(p,DAY+timedelta(days=3),weather(4),soils(4),config())["records"]
    assert repaired[1]["daily_change"] is not None
    assert repaired[2]["daily_change"] is not None


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


@pytest.mark.parametrize("preference,primary,scenario,scenario_enabled,enabled,expected", [
    ("primary", 12.0, 14.0, True, True, ("primary", 12.0)),
    ("scenario", 12.0, 14.0, True, True, ("scenario", 14.0)),
    ("primary", None, 14.0, True, True, ("scenario", 14.0)),
    ("scenario", 12.0, None, True, True, ("primary", 12.0)),
    ("scenario", 12.0, 14.0, False, True, ("primary", 12.0)),
    ("primary", None, 14.0, False, True, (None, None)),
    ("primary", None, None, True, True, (None, None)),
    ("primary", 0.0, 14.0, True, True, ("primary", 0.0)),
    ("primary", float("nan"), 14.0, True, True, ("scenario", 14.0)),
    ("scenario", 12.0, float("inf"), True, True, ("primary", 12.0)),
    ("primary", 12.0, 14.0, True, False, (None, None)),
])
def test_default_wsc_route_selection(preference, primary, scenario, scenario_enabled, enabled, expected):
    from custom_components.pasture_wsc.paddocks import selected_wsc
    result = {"primary": {"experimental_wsc": primary}, "scenario": {"experimental_wsc": scenario}}
    settings = {"wsc_preference": preference, "scenario_enabled": scenario_enabled, "enabled": enabled}
    assert selected_wsc(result, settings) == expected


def test_wsc_preference_persists_and_invalid_preference_rejected():
    async def run():
        backend = MemoryStore()
        store = PastureStore(None, "entry", backend)
        await store.load()
        initialize_paddocks(store.data, [{"id": "summer", "name": "Summer", "start_date": DAY.isoformat()}], "America/Toronto")
        paddock = store.data["paddocks"]["summer"]
        cycle = deepcopy(paddock["cycle"])
        update_paddock(paddock, {"wsc_preference": "scenario"})
        assert paddock["settings"]["scenario_enabled"] is False
        assert paddock["cycle"] == cycle
        with pytest.raises(ValueError, match="Unknown WSC route"):
            update_paddock(paddock, {"wsc_preference": "invalid"})
        await store.save()
        restarted = PastureStore(None, "entry", backend)
        await restarted.load()
        assert restarted.data["paddocks"]["summer"]["settings"]["wsc_preference"] == "scenario"
    import asyncio
    asyncio.run(run())


@pytest.mark.parametrize("value,expected", [(0, "low"), (7.999, "low"), (8, "medium"),
                                            (11.999, "medium"), (12, "high"), (25, "high"),
                                            (None, None), (float("nan"), None)])
def test_carbohydrate_level_boundaries(value, expected):
    from custom_components.pasture_wsc.paddocks import carbohydrate_level
    result = {"primary": {"experimental_wsc": value}}
    assert carbohydrate_level(result, {}) == expected


def test_carbohydrate_levels_follow_route_and_custom_cutoffs():
    from custom_components.pasture_wsc.paddocks import carbohydrate_level
    result = {"primary": {"experimental_wsc": 7}, "scenario": {"experimental_wsc": 17}}
    settings = {"scenario_enabled": True, "wsc_preference": "scenario",
                "carbohydrate_low_cutoff": 8, "carbohydrate_high_cutoff": 16}
    assert carbohydrate_level(result, settings) == "high"
    settings["scenario_enabled"] = False
    assert carbohydrate_level(result, settings) == "low"
    settings["enabled"] = False
    assert carbohydrate_level(result, settings) is None


@pytest.mark.parametrize("low,high", [(0,20), (20,20), (21,20), (10,101), (float("nan"),20), (10,float("inf"))])
def test_invalid_carbohydrate_cutoffs_rejected(low, high):
    paddock = state()
    original = deepcopy(paddock)
    with pytest.raises(ValueError, match="Carbohydrate cutoffs"):
        update_paddock(paddock, {"carbohydrate_low_cutoff": low, "carbohydrate_high_cutoff": high})
    assert paddock == original
