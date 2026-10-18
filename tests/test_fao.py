from copy import deepcopy
from datetime import date, timedelta

import pytest

from custom_components.pasture_wsc.fao import reference_et
from custom_components.pasture_wsc.soil import estimate_day
from custom_components.pasture_wsc.engine.weather import normalize, Variable
from custom_components.pasture_wsc.weather import forecast_records, capture
from custom_components.pasture_wsc.paddocks import calculate_paddock, validate_paddock
from tests.test_soil import rain_weather
from tests.test_paddocks import DAY, state
from tests.test_ha_phase2 import A, config, source


def test_fao56_published_example_18_brussels():
    # FAO-56 chapter 4 example 18, non-leap J187; published ET0 = 3.88 mm/d.
    result = reference_et(date(1997,7,6),50.8,100,12.3,21.5,22.07,
                          rhmin=63,rhmax=84,wind=10/3.6,wind_height=10)
    assert result["eto_mm"] == pytest.approx(3.88,abs=.01)
    assert result["net_radiation_mj_m2"] == pytest.approx(13.28,abs=.02)
    assert result["wind_2m_m_s"] == pytest.approx(2.078,abs=.001)
    assert result["flags"] == []


def test_fao_missing_wind_humidity_and_invalid_extremes():
    result = reference_et(DAY,43.7,100,15,25,20)
    assert result["eto_mm"] > 0
    assert "wind_2m_s_assumed_at_2m" in result["flags"]
    assert "dewpoint_equals_tmin_assumed_eq48" in result["flags"]
    with pytest.raises(ValueError):
        reference_et(DAY,43.7,100,25,15,20)
    with pytest.raises(ValueError):
        reference_et(DAY,43.7,100,float("nan"),25,20)


def test_water_balance_mass_conservation_root_depth_and_stress():
    w = rain_weather()[DAY]["weather"]
    w["precipitation"]["value"] = 50
    result = estimate_day(None,w,"sandy",.47,day=DAY,latitude=43.7,elevation=100)
    capacity = result["capacity_mm"]
    assert capacity == pytest.approx(40)
    assert .47*capacity+50 == pytest.approx(result["value"]*capacity+result["drying_mm"]+result["drainage_mm"])
    assert result["value"] == 1  # FAO Eq 88: excess after ET drains.
    deeper = estimate_day(None,w,"sandy",.47,day=DAY,latitude=43.7,root_depth=1)
    assert deeper["capacity_mm"] == pytest.approx(80)
    w["precipitation"]["value"] = 0
    dry = estimate_day(None,w,"sandy",.01,day=DAY,latitude=43.7)
    assert 0 <= dry["stress_coefficient"] < 1
    assert dry["drying_mm"] <= .01*dry["capacity_mm"]


def test_missing_temperature_extremes_hold_not_fabricated_from_mean():
    w = rain_weather()[DAY]["weather"]
    w["temperature"].pop("minimum")
    w["temperature"].pop("maximum")
    result = estimate_day(None,w,"loam",.47,day=DAY,latitude=43.7)
    assert result["value"] == .47
    assert result["status"] == "held_assumption"
    assert "temperature_minimum" in result["missing_inputs"]


def test_freezing_days_hold_and_resume():
    w = rain_weather()[DAY]["weather"]
    w["temperature"].update(value=-5,minimum=-10,maximum=-1)
    frozen = estimate_day(None,w,"loam",.47,day=DAY,latitude=43.7)
    assert frozen["value"] == .47
    assert "frozen_day_unsupported" in frozen["missing_inputs"]
    w["temperature"].update(value=20,minimum=15,maximum=25)
    warm = estimate_day(frozen,w,"loam",.47,day=DAY+timedelta(days=1),latitude=43.7)
    assert warm["status"] == "weather_estimate"
    assert warm["assumed_days"] == 1


@pytest.mark.parametrize("unit,value",[("m/s",10),("km/h",36),("mph",10/.44704),("kn",10/.514444)])
def test_wind_units(unit,value):
    assert normalize(Variable.WIND,value,unit) == pytest.approx(10)


def test_wind_forecast_capture_and_replay_change_estimate():
    from types import SimpleNamespace
    rows = [{"datetime":(A+timedelta(hours=h)).isoformat(),"wind_speed":36} for h in range(2)]
    records = forecast_records("weather.met",rows,{"wind_speed_unit":"km/h"},A)
    assert records[0]["value"] == 10 and records[0]["unit"] == "m/s"
    for row in rows:
        row.update(wind_speed="bad",precipitation=2)
    good_rain = forecast_records("weather.met",rows,{"wind_speed_unit":"km/h","precipitation_unit":"mm"},A)
    assert len(good_rain) == 1 and good_rain[0]["variable"] == "precipitation"
    reading = capture(source(variable="wind_speed",kind="weather_proxy",entity_id="weather.met"),
        SimpleNamespace(last_reported=A,state="sunny",attributes={"wind_speed":36,"wind_speed_unit":"km/h"}),A)
    assert reading["value"] == 36 and reading["unit"] == "km/h"
    p = state(scenario_enabled=True,moisture_mode="one_minus_wi_over_reference")
    w = rain_weather()
    original = calculate_paddock(p,DAY,w,[],config())["latest"]
    w[DAY]["weather"].update(wind_speed={"value":8},humidity={"value":40})
    corrected = calculate_paddock(p,DAY,w,[],config())["latest"]
    assert original["estimated_soil"]["method"] == "fao56-pm-v1"
    assert corrected["estimated_soil"]["eto_mm"] != original["estimated_soil"]["eto_mm"]
    assert corrected["scenario_input_hash"] != original["scenario_input_hash"]
    assert corrected["primary"] == original["primary"]


@pytest.mark.parametrize("field,value",[("root_depth",0),("crop_coefficient",2),("wind_height",0)])
def test_invalid_fao_paddock_settings_rejected(field,value):
    p = deepcopy(state()["settings"])
    with pytest.raises(ValueError):
        validate_paddock({**p,field:value})
