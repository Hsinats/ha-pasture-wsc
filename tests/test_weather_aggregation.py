from datetime import date, datetime, timedelta, timezone
import pytest
from pasture_wsc.weather import (Variable as V, Quality as Q, Interval, SourcePolicy,
    resolve_day, normalize, Reading, readings_to_intervals, counter_intervals, solar_energy_intervals)
from pasture_wsc.astronomy import local_day_bounds

DAY = date(2026,6,1)
A,B = local_day_bounds(DAY,"America/Toronto")


def interval(variable, a, b, value, source="station", quality=Q.OBSERVED):
    units = {V.TEMPERATURE:"°C",V.IRRADIANCE:"W/m²",V.SOLAR_ENERGY:"MJ/m²",V.PRECIPITATION:"mm"}
    return Interval(variable,a,b,value,source,quality,a,units[variable])


def policy(source="station",priority=0,quality=None,age=86400):
    return SourcePolicy(source,priority,age,frozenset({Q.OBSERVED,Q.PROVIDER} if quality is None else {quality}))


def test_station_outage_recovery_and_variable_independence():
    noon, evening = A+timedelta(hours=12), A+timedelta(hours=18)
    raw = [interval(V.TEMPERATURE,A,noon,10),interval(V.TEMPERATURE,evening,B,10),
           interval(V.TEMPERATURE,A,B,20,"provider",Q.PROVIDER),
           interval(V.IRRADIANCE,A,B,100,"solar")]
    result = resolve_day(DAY,"America/Toronto",V.TEMPERATURE,raw,[policy(),policy("provider",1)])
    assert result.value == 12.5
    assert result.coverage == 1
    assert result.fallback_proportion == .25
    assert [i.source for i in result.intervals] == ["station","provider","station"]
    solar = resolve_day(DAY,"America/Toronto",V.IRRADIANCE,raw,[policy("solar")])
    assert solar.value == 8.64


def test_time_weighted_mean_and_no_backwards_fill():
    readings = [Reading(A+timedelta(hours=12),32,"°F"), Reading(A+timedelta(hours=18),20,"°C")]
    raw,flags = readings_to_intervals(V.TEMPERATURE,"station",readings,21600)
    result = resolve_day(DAY,"America/Toronto",V.TEMPERATURE,raw,[policy()],minimum_coverage=.8)
    assert result.value is None
    assert result.partial_value == 10
    assert result.coverage == .5
    assert result.missing[0] == (A,A+timedelta(hours=12))


def test_forecast_requires_opt_in_and_retains_label():
    raw = [interval(V.TEMPERATURE,A,B,20,"met",Q.FORECAST)]
    assert resolve_day(DAY,"America/Toronto",V.TEMPERATURE,raw,[policy("met")]).value is None
    result = resolve_day(DAY,"America/Toronto",V.TEMPERATURE,raw,[policy("met",quality=Q.FORECAST)])
    assert result.value == 20 and "forecast_proxy" in result.flags
    assert result.intervals[0].quality == Q.FORECAST


def test_freshness_and_invalid_events():
    readings = [Reading(A,10,"°C"), Reading(A+timedelta(hours=1),"unavailable","°C"),
                Reading(A+timedelta(hours=2),"bad","°C"),Reading(A+timedelta(hours=3),float('nan'),"°C"),
                Reading(A+timedelta(hours=4),100,"°C"), Reading(A+timedelta(hours=5),None,"°C")]
    raw,flags = readings_to_intervals(V.TEMPERATURE,"station",readings,7200)
    assert len(raw) == 1
    assert set(flags) == {"unavailable","invalid_numeric","physically_implausible","unknown"}
    result = resolve_day(DAY,"America/Toronto",V.TEMPERATURE,raw,[policy(age=1800)])
    assert result.coverage == .5/24
    assert "stale_tail" in result.flags


def test_units_and_hash_determinism():
    assert normalize(V.SOLAR_ENERGY,1000,"Wh/m²") == 3.6
    assert normalize(V.SOLAR_ENERGY,100,"J/cm²") == 1
    assert normalize(V.PRECIPITATION,1,"in") == 25.4
    assert normalize(V.TEMPERATURE,32,"°F",1) == 1
    raw = [interval(V.TEMPERATURE,A,B,20)]
    a = resolve_day(DAY,"America/Toronto",V.TEMPERATURE,raw,[policy()])
    b = resolve_day(DAY,"America/Toronto",V.TEMPERATURE,reversed(raw),[policy()])
    assert a == b
    assert a.source_data_hash != resolve_day(DAY,"America/Toronto",V.TEMPERATURE,raw,[policy(age=3600)]).source_data_hash
    with pytest.raises(ValueError):
        normalize(V.SOLAR_ENERGY,1,"kWh")


@pytest.mark.parametrize("day,hours",[(date(2026,3,8),23),(date(2026,11,1),25)])
def test_dst_integration(day,hours):
    a,b = local_day_bounds(day,"America/Toronto")
    raw = [interval(V.IRRADIANCE,a,b,100)]
    assert resolve_day(day,"America/Toronto",V.IRRADIANCE,raw,[policy(age=90000)]).value == pytest.approx(hours*.36)


def test_counters_restart_rollover_and_unit_changes():
    readings = [Reading(A,100,"Wh/m²"), Reading(A+timedelta(hours=1),200,"Wh/m²"),
                Reading(A+timedelta(hours=2),0,"Wh/m²"), Reading(A+timedelta(hours=3),50,"Wh/m²")]
    raw,flags = counter_intervals(V.SOLAR_ENERGY,"station",readings,max_gap_seconds=3600,zone="America/Toronto")
    assert sum(i.value for i in raw) == pytest.approx(.54)
    assert flags == ("counter_reset_unknown",)
    # Retain last baseline across a restart, then deterministic same result.
    resumed,_ = counter_intervals(V.SOLAR_ENERGY,"station",readings[2:],max_gap_seconds=3600,zone="America/Toronto")
    assert resumed == raw[-1:]
    rolled,_ = counter_intervals(V.PRECIPITATION,"rain",[Reading(A,99,"mm"),Reading(A+timedelta(hours=1),2,"mm")],
                                 max_gap_seconds=3600,zone="America/Toronto",rollover=100)
    assert rolled[0].value == 3
    changed,flags = counter_intervals(V.SOLAR_ENERGY,"station",[Reading(A,1,"Wh/m²"),Reading(B,1,"kWh/m²")],
                                     max_gap_seconds=86400,zone="America/Toronto")
    assert not changed and "counter_unit_change" in flags


def test_daily_reset_midnight_and_missing_baseline():
    readings = [Reading(A-timedelta(hours=1),10,"mm"),Reading(A,0,"mm"),Reading(A+timedelta(hours=1),2,"mm")]
    raw,flags = counter_intervals(V.PRECIPITATION,"rain",readings,max_gap_seconds=3600,zone="America/Toronto",daily_reset=True)
    assert len(raw) == 1 and raw[0].value == 2
    assert "daily_reset_boundary_unknown" in flags


def test_counters_no_double_count_and_missing_fraction():
    raw = [interval(V.SOLAR_ENERGY,A,B,10,"a"),interval(V.SOLAR_ENERGY,A,B,20,"b")]
    result = resolve_day(DAY,"America/Toronto",V.SOLAR_ENERGY,raw,[policy("a"),policy("b",1)])
    assert result.value == 10
    with pytest.raises(ValueError):
        resolve_day(DAY,"America/Toronto",V.SOLAR_ENERGY,raw[:1]*2,[policy("a")])


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        interval(V.TEMPERATURE,datetime(2026,1,1),B,20)


def test_power_and_energy_sources_share_one_resolver():
    noon = A+timedelta(hours=12)
    raw = solar_energy_intervals([interval(V.IRRADIANCE,A,noon,100),
                                 interval(V.SOLAR_ENERGY,A,B,20,"provider",Q.PROVIDER)])
    result = resolve_day(DAY,"America/Toronto",V.SOLAR_ENERGY,raw,[policy(),policy("provider",1)])
    assert result.value == pytest.approx(4.32+10)
    assert result.fallback_proportion == .5
    assert "uniform_interval_allocation" in result.flags


@pytest.mark.parametrize("day,hours",[(date(2026,3,8),23),(date(2026,11,1),25)])
def test_counter_local_days_across_dst(day,hours):
    a,b = local_day_bounds(day,"America/Toronto")
    readings = [Reading(a+timedelta(hours=h),h*100,"Wh/m²") for h in range(hours+1)]
    raw,flags = counter_intervals(V.SOLAR_ENERGY,"energy",readings,max_gap_seconds=3600,zone="America/Toronto")
    result = resolve_day(day,"America/Toronto",V.SOLAR_ENERGY,raw,[policy("energy")],minimum_coverage=1)
    assert not flags and result.coverage == 1
    assert result.value == pytest.approx(hours*.36)
