from copy import deepcopy
from datetime import timedelta

import pytest

from custom_components.pasture_wsc.rain import live_rain
from custom_components.pasture_wsc.weather import forecast_records
from tests.test_ha_phase2 import A, DAY, config


CYCLE = {"start_date":DAY.isoformat(),"timezone":"America/Toronto"}


def data():
    rows = [{"datetime":(A+timedelta(hours=h)).isoformat(),"precipitation":4} for h in range(4)]
    forecasts = forecast_records("weather.met",rows,{"precipitation_unit":"mm"},A)
    observed = {**forecasts[0],"source":"historical_gauge","quality":"observed",
                "value":2,"timestamp":(A+timedelta(hours=1)).isoformat()}
    location = {k:config()[k] for k in ("latitude","longitude","elevation")}
    return {"observations":[],"forecasts":{str(n):r for n,r in enumerate(forecasts)},
            "historical_weather":{"one":{"location":location,"interval":observed}}}


def test_separate_totals_elapsed_hour_and_future_exclusion():
    c = config(allow_forecast=True,historical_backfill=True,weather_entities=["weather.met"])
    result = live_rain(data(),c,CYCLE,A+timedelta(minutes=30))
    assert result["estimated"]["value"] == 2  # half of 4 mm forecast hour
    assert result["measured"]["value"] == 1  # half of observed interval total
    assert result["estimated"]["coverage"] == 1
    assert "uniform_elapsed_interval_estimate" in result["estimated"]["flags"]
    later = live_rain(data(),c,CYCLE,A+timedelta(hours=1,minutes=30))
    assert later["estimated"]["value"] == 6
    assert later["measured"]["value"] == 2
    assert later["measured"]["missing_hours"] == .5
    assert not later["measured"]["complete"]


def test_no_fallback_between_flavors_and_permissions_respected():
    d = data()
    result = live_rain(d,config(),CYCLE,A+timedelta(hours=1))
    assert result["estimated"]["value"] == result["measured"]["value"] == 0
    assert result["estimated"]["coverage"] == 0
    result = live_rain(d,config(allow_forecast=True),CYCLE,A+timedelta(hours=1))
    assert result["estimated"]["value"] == 4
    assert result["measured"]["value"] == 0


def test_overlapping_forecast_sources_not_double_counted_and_reset_range():
    d = data()
    for key,r in list(d["forecasts"].items()):
        d["forecasts"]["other"+key] = {**r,"source":"forecast:weather.other:precipitation","value":20}
    c = config(allow_forecast=True,weather_entities=["weather.met","weather.other"])
    result = live_rain(d,c,CYCLE,A+timedelta(hours=1))
    assert result["estimated"]["value"] == 4
    assert result == live_rain(deepcopy(d),c,deepcopy(CYCLE),A+timedelta(hours=1))
    reset = {**CYCLE,"start_date":(DAY+timedelta(days=1)).isoformat()}
    assert live_rain(d,c,reset,A+timedelta(hours=1))["estimated"]["value"] == 0


def test_forecast_rain_clipped_at_local_midnight():
    d = data()
    r = next(iter(d["forecasts"].values()))
    d["forecasts"] = {"cross":{**r,"start":(A-timedelta(minutes=30)).isoformat(),
                              "end":(A+timedelta(minutes=30)).isoformat(),"value":6}}
    result = live_rain(d,config(allow_forecast=True),CYCLE,A+timedelta(minutes=30))
    assert result["estimated"]["value"] == pytest.approx(3)
