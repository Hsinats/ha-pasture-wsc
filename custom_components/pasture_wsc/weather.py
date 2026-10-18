"""Adapters from HA state/forecast payloads to immutable engine records."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite

from .engine.weather import (Interval, Quality, Reading, SourcePolicy, Variable,
                             counter_intervals, readings_to_intervals, solar_energy_intervals)

WEATHER_ATTRIBUTES = {"temperature":"temperature","cloud_cover":"cloud_coverage","humidity":"humidity","wind_speed":"wind_speed"}


def sources_for(config):
    sources = [dict(s) for s in config["sources"]]
    for source in sources:
        if source["kind"] == "daily_reset":
            source["calendar_timezone"] = config["timezone"]
    explicit = {(s["entity_id"],s["variable"]) for s in sources}
    for rank,entity in enumerate(config["weather_entities"]):
        for variable in WEATHER_ATTRIBUTES:
            if (entity,variable) in explicit:
                continue
            sources.append({"id":f"weather:{entity}:{variable}","entity_id":entity,"variable":variable,
                            "kind":"weather_proxy","priority":100+rank,"freshness":7200,
                            "offset":0,"semantics":"Weather current value; conservatively provider-derived estimate",
                            "unit_override":""})
    return sources


def source_key(source):
    digest = sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()[:16]
    return f"{source['id']}:{digest}"


def capture(source, state, now, *, initial=False):
    """Initial state is forward-only; last_reported is retained for freshness."""
    reported = state.last_reported if state is not None else now
    timestamp = now if initial else reported
    attributes = dict(state.attributes) if state is not None else {}
    status = "valid"
    value = None
    if state is None:
        status = "unavailable"
    elif state.state in ("unknown","unavailable"):
        status = state.state
    elif attributes.get("restored"):
        status = "restored_not_observed"
    elif (now-reported).total_seconds() > source["freshness"]:
        status = "stale"
    elif source["kind"].startswith("weather_"):
        value = attributes.get(WEATHER_ATTRIBUTES[source["variable"]])
    else:
        value = state.state
    unit = source.get("unit_override") or attributes.get("unit_of_measurement","")
    if source["kind"].startswith("weather_"):
        unit = (attributes.get("temperature_unit","") if source["variable"] == "temperature" else
                attributes.get("wind_speed_unit","") if source["variable"] == "wind_speed" else "%")
    device = attributes.get("device_class")
    expected = {"temperature":"temperature","irradiance":"irradiance","humidity":"humidity"}.get(source["variable"])
    if device and expected and device != expected:
        status = "device_class_mismatch"
    if source["kind"] in ("counter","daily_reset") and attributes.get("state_class") not in (None,"total","total_increasing"):
        status = "state_class_mismatch"
    if initial and source["kind"] in ("counter","daily_reset") and status == "valid":
        status = "initial_counter_baseline_unverified"
    if isinstance(value,float) and not isfinite(value):
        value = str(value)
        status = "invalid_numeric"
    if source["variable"] == "soil" and status == "valid":
        try:
            if not isfinite(float(value)):
                raise ValueError
        except (ValueError,TypeError):
            status = "invalid_numeric"
    return {"source":dict(source),"source_key":source_key(source),"timestamp":timestamp.isoformat(),
            "reported":reported.isoformat(),"value":value,"unit":unit,"status":status,
            "device_class":device,"state_class":attributes.get("state_class"),
            "initial_forward_only":initial}


def build_intervals(raw, config):
    groups = {}
    for item in raw:
        groups.setdefault(item["source_key"],[]).append(item)
    result, policies, anomalies = [], {v:[] for v in Variable}, {}
    for key,group in groups.items():
        source = group[0]["source"]
        variable = Variable(source["variable"])
        readings = [Reading(datetime.fromisoformat(r["timestamp"]),r["value"],r["unit"],r["status"]) for r in group]
        quality = Quality.ESTIMATED if source["kind"] == "weather_proxy" else Quality.PROVIDER if source["kind"] == "weather_observation" else Quality.OBSERVED
        if source["kind"] in ("counter","daily_reset"):
            intervals,flags = counter_intervals(variable,key,readings,max_gap_seconds=source["freshness"],
                                               zone=source.get("calendar_timezone",config["timezone"]),daily_reset=source["kind"] == "daily_reset")
        else:
            intervals,flags = readings_to_intervals(variable,key,readings,source["freshness"],quality,source.get("offset",0))
            reported = {r["timestamp"]:datetime.fromisoformat(r["reported"]) for r in group}
            intervals = tuple(replace(i,timestamp=reported[i.start.isoformat()]) for i in intervals)
        if variable == Variable.IRRADIANCE:
            intervals = solar_energy_intervals(intervals)
            variable = Variable.SOLAR_ENERGY
        result.extend(intervals)
        enabled = {Quality.OBSERVED,Quality.PROVIDER}
        if config["allow_estimated"]:
            enabled.add(Quality.ESTIMATED)
        policies[variable].append(SourcePolicy(key,int(source["priority"]),source["freshness"],frozenset(enabled)))
        anomalies[key] = tuple(sorted(set(flags)))
    return result,policies,anomalies


def forecast_records(entity, payload, units, issued):
    """Hourly forecasts only, acquired BEFORE interval start; no invented history.

    A trailing point has no defensible interval and is dropped. Daily high/low
    temperature is deliberately not a daily mean.
    """
    result = []
    ordered = sorted(payload,key=lambda f:f.get("datetime",""))
    for a,b in zip(ordered,ordered[1:]):
        try:
            start = datetime.fromisoformat(a["datetime"].replace("Z","+00:00"))
            end = datetime.fromisoformat(b["datetime"].replace("Z","+00:00"))
            if start.tzinfo is None or end.tzinfo is None:
                raise ValueError("Forecast timestamps require explicit timezone")
            start,end = start.astimezone(timezone.utc),end.astimezone(timezone.utc)
            if start < issued or not timedelta(0) < end-start <= timedelta(hours=1):
                continue
            for variable,attribute in {**WEATHER_ATTRIBUTES,"precipitation":"precipitation"}.items():
                if a.get(attribute) is None:
                    continue
                from .engine.weather import normalize, UNITS
                unit = (units.get("temperature_unit","") if variable == "temperature" else
                        units.get("wind_speed_unit","") if variable == "wind_speed" else
                        units.get("precipitation_unit","") if variable == "precipitation" else "%")
                try:
                    value = normalize(Variable(variable),float(a[attribute]),unit)
                except (ValueError,TypeError):
                    # One unusable field must not discard the hour's other data.
                    continue
                result.append({"variable":variable,"start":start.isoformat(),"end":end.isoformat(),
                               "value":value,"source":f"forecast:{entity}:{variable}","quality":"forecast_proxy",
                               "timestamp":issued.isoformat(),"unit":UNITS[Variable(variable)],
                               "original_value":a[attribute],"original_unit":unit,"flags":[
                                   "hourly_forecast_interval_total_assumption" if variable == "precipitation"
                                   else "hourly_forecast_interval_mean_assumption"]})
        except (ValueError,TypeError,KeyError):
            continue
    return result


def decode_interval(record):
    values = dict(record)
    values["variable"] = Variable(values["variable"])
    values["quality"] = Quality(values["quality"])
    for key in ("start","end","timestamp"):
        values[key] = datetime.fromisoformat(values[key])
    values["flags"] = tuple(values.get("flags",()))
    return Interval(**values)


def serializable(value):
    """JSON-safe immutable snapshot used by Store and content hashes."""
    return json.loads(json.dumps(value,default=lambda x:asdict(x) if hasattr(x,"__dataclass_fields__") else x.isoformat()))
