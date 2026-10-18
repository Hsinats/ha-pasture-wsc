from copy import deepcopy
from datetime import timedelta

import pytest

from custom_components.pasture_wsc.soil import estimate_day as estimate_soil
from custom_components.pasture_wsc.paddocks import calculate_paddock
from tests.test_paddocks import DAY, calibrated, state, weather, soils
from tests.test_ha_phase2 import config


def estimate_day(previous, weather, soil_type, initial_wi):
    return estimate_soil(previous,weather,soil_type,initial_wi,day=DAY,latitude=43.7,elevation=100)


def inputs(rain=0, temperature=20, solar=20):
    return {"precipitation":{"value":rain}, "temperature":{"value":temperature,"minimum":temperature-5,"maximum":temperature+5},
            "solar_energy":{"value":solar}}


def test_rain_wets_dry_days_dry_and_bucket_is_bounded():
    dry = estimate_day(None,inputs(),"loam",.47)
    wet = estimate_day(None,inputs(rain=20),"loam",.47)
    assert 0 < dry["value"] < .47 < wet["value"] < 1
    following = estimate_day(wet,inputs(),"loam",.47)
    assert following["value"] < wet["value"]
    flooded = estimate_day(None,inputs(rain=1000),"loam",.47)
    assert .9 < flooded["value"] <= 1 and flooded["drainage_mm"] > 0
    empty = estimate_day(None,inputs(),"loam",0)
    assert empty["value"] == 0


def test_soil_type_and_explicit_unsure_assumption():
    sandy = estimate_day(None,inputs(),"sandy",.47)
    clay = estimate_day(None,inputs(),"clay",.47)
    unsure = estimate_day(None,inputs(),"unsure",.47)
    loam = estimate_day(None,inputs(),"loam",.47)
    assert sandy["capacity_mm"] < clay["capacity_mm"] < loam["capacity_mm"]
    assert sandy["value"] < clay["value"] < loam["value"]
    assert unsure["value"] == loam["value"]
    assert "loam_properties_assumed" in unsure["flags"]


@pytest.mark.parametrize("key,bad", [("precipitation",None),("temperature",None),
                                   ("solar_energy",None),("precipitation",-1),
                                   ("precipitation",float("nan")),("solar_energy",float("inf"))])
def test_missing_or_invalid_weather_holds_then_resumes(key,bad):
    w = inputs()
    w[key]["value"] = bad
    gap = estimate_day(None,w,"loam",.47)
    assert gap["value"] == .47
    assert gap["status"] == "held_assumption"
    assert gap["drying_mm"] is None
    following = estimate_day(gap,inputs(rain=10),"loam",.47)
    assert following["value"] > .47
    assert following["status"] == "weather_estimate"
    assert following["assumed_days"] == 1
    assert "assumed_weather_history" in following["flags"]


def rain_weather(days=3):
    records = weather(days)
    for n,record in enumerate(records.values()):
        record["weather"]["precipitation"] = {"value":10 if n == 1 else 0}
        record["weather"]["temperature"].update(minimum=15,maximum=25)
    return records


def test_estimate_feeds_wsc_and_measured_takes_priority():
    p = state(scenario_enabled=True,moisture_mode="one_minus_wi_over_reference")
    end = DAY+timedelta(days=2)
    rows = calculate_paddock(p,end,rain_weather(),[],config())["records"]
    assert all(row["selected_moisture_method"] == "weather_estimate" for row in rows)
    assert all(row["scenario"]["experimental_wsc"] is not None for row in rows)
    assert all(row["soil"]["measured_value"] is None for row in rows)
    fixed_weather = rain_weather()
    for record in fixed_weather.values():
        record["weather"].pop("precipitation")
    fixed = calculate_paddock(p,end,fixed_weather,[],config())["latest"]
    assert fixed["selected_moisture_method"] == "held_assumption"
    assert fixed["estimated_soil"]["value"] == .47
    assert rows[-1]["scenario"]["experimental_wsc"] != fixed["scenario"]["experimental_wsc"]
    measured = calculate_paddock(calibrated(scenario_enabled=True),end,rain_weather(),soils(3),config())["latest"]
    assert measured["selected_moisture_method"] == "measured"
    assert measured["soil"]["measured_value"] == pytest.approx(.4)
    assert measured["scenario"]["experimental_wsc"] == measured["primary"]["experimental_wsc"]


def test_backfill_replay_restart_and_soil_changes_propagate():
    p = state(scenario_enabled=True,moisture_mode="one_minus_wi_over_reference")
    end = DAY+timedelta(days=2)
    complete = rain_weather()
    missing = deepcopy(complete)
    missing[DAY+timedelta(days=1)]["weather"].pop("precipitation")
    gap = calculate_paddock(p,end,missing,[],config())
    assert gap["latest"]["estimated_soil"]["value"] is not None
    assert gap["latest"]["estimated_soil"]["assumed_days"] == 1
    repaired = calculate_paddock(p,end,complete,[],config())
    assert repaired["latest"]["estimated_soil"]["value"] is not None
    assert repaired["latest"]["estimated_soil"]["assumed_days"] == 0
    assert repaired == calculate_paddock(deepcopy(p),end,deepcopy(complete),[],config())
    assert repaired["latest"]["scenario_input_hash"] != gap["latest"]["scenario_input_hash"]
    sandy_paddock = deepcopy(p)
    sandy_paddock["settings"]["soil_type"] = "sandy"
    sandy = calculate_paddock(sandy_paddock,end,complete,[],config())
    assert sandy["latest"]["scenario_input_hash"] != repaired["latest"]["scenario_input_hash"]
    assert sandy["latest"]["primary"] == repaired["latest"]["primary"]


def test_disabled_scenario_does_not_supply_auto_wsc():
    from custom_components.pasture_wsc.paddocks import selected_wsc
    p = state()
    row = calculate_paddock(p,DAY,rain_weather(),[],config())["latest"]
    assert row["estimated_soil"]["value"] is not None
    assert row["scenario"] == {}
    assert selected_wsc(row,p["settings"]) == (None,None)


def test_rain_accumulation_missing_zero_backfill_and_last_cut():
    p = state()
    end = DAY+timedelta(days=2)
    w = rain_weather()
    rows = calculate_paddock(p,end,w,[],config())["records"]
    assert [row["rain_accumulation"]["value"] for row in rows] == [0,10,10]
    assert rows[-1]["rain_accumulation"]["complete"]
    w[DAY]["weather"].pop("precipitation")
    w[end]["weather"].pop("precipitation")
    rows = calculate_paddock(p,end,w,[],config())["records"]
    assert rows[0]["rain_accumulation"]["value"] == 0
    assert rows[0]["rain_accumulation"]["days_with_data"] == 0
    assert not rows[0]["rain_accumulation"]["complete"]
    assert rows[-1]["rain_accumulation"]["value"] == 10
    assert rows[-1]["rain_accumulation"]["missing_days"] == 2
    assert rows[-1]["rain_accumulation"]["days_with_data"] == 1
    assert not rows[-1]["rain_accumulation"]["complete"]
    corrected = rain_weather()
    corrected[DAY]["weather"]["precipitation"]["value"] = 5
    assert calculate_paddock(p,end,corrected,[],config())["latest"]["rain_accumulation"]["value"] == 15
    p["cycle"]["start_date"] = end.isoformat()
    total = calculate_paddock(p,end,corrected,[],config())["latest"]["rain_accumulation"]
    assert total["value"] == 0 and total["days_with_data"] == 1
