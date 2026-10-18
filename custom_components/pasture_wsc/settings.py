"""HA-independent validation of persisted configuration."""
from copy import deepcopy
from datetime import date, time
from math import isfinite
from uuid import uuid4
from zoneinfo import ZoneInfo

from .const import DEFAULTS, VARIABLES, SOIL_TYPES


def settings(entry):
    return validate({**deepcopy(DEFAULTS), **entry.data, **entry.options})


def finite(value, low, high):
    number = float(value)
    if not isfinite(number) or not low <= number <= high:
        raise ValueError("Out of range")
    return number


def validate(data):
    result = {**deepcopy(DEFAULTS), **deepcopy(data)}
    if result["soil_type"] not in SOIL_TYPES:
        raise ValueError("Unknown soil type")
    for key, low, high in (("latitude",-90,90),("longitude",-180,180),("elevation",-500,9000),
                          ("minimum_coverage",.01,1),("solar_minimum_coverage",.01,1),
                          ("soil_freshness",60,86400)):
        result[key] = finite(result[key],low,high)
    ZoneInfo(result["timezone"])
    time.fromisoformat(result["calculation_time"])
    if len(set(result["weather_entities"])) != len(result["weather_entities"]):
        raise ValueError("Duplicate weather entity")
    if any(not e.startswith("weather.") for e in result["weather_entities"]):
        raise ValueError("Weather entities required")
    ids = set()
    for source in result["sources"]:
        validate_source(source)
        if source["id"] in ids:
            raise ValueError("Duplicate source ID")
        ids.add(source["id"])
    if result["soil_entity"] and not result["soil_entity"].startswith("sensor."):
        raise ValueError("Soil must be a sensor")
    if not result["soil_semantics"].strip():
        raise ValueError("Soil semantics required")
    ids = set()
    for paddock in result["paddocks"]:
        if not paddock["name"].strip() or paddock["id"] in ids:
            raise ValueError("Invalid paddock")
        date.fromisoformat(paddock["start_date"])
        ids.add(paddock["id"])
    return result


def validate_source(source):
    if source["variable"] not in VARIABLES + ("irradiance",):
        raise ValueError("Unknown variable")
    if source["kind"] not in ("instantaneous", "counter", "daily_reset", "weather_proxy", "weather_observation"):
        raise ValueError("Unknown source kind")
    entity = source["entity_id"]
    if source["kind"].startswith("weather_"):
        if not entity.startswith("weather.") or source["variable"] not in ("temperature","humidity","cloud_cover","wind_speed"):
            raise ValueError("Unsupported weather attribute")
    elif not entity.startswith("sensor."):
        raise ValueError("Sensor required")
    if source["kind"] in ("counter","daily_reset") and source["variable"] not in ("solar_energy","precipitation"):
        raise ValueError("Counter must measure energy or rain")
    if source["kind"] == "instantaneous" and source["variable"] in ("solar_energy","precipitation"):
        raise ValueError("Use a counter for accumulated totals")
    finite(source["priority"],0,1000)
    finite(source["freshness"],60,86400)
    finite(source.get("offset",0),-100,100)
    if source["kind"] in ("counter","daily_reset") and source.get("offset",0) != 0:
        raise ValueError("Counter offsets are not interval corrections")
    if not source.get("semantics", "").strip():
        raise ValueError("Measurement semantics required")


def paddocks_from_names(text, today):
    names = [n.strip() for n in text.splitlines() if n.strip()]
    if not names or len(names) != len(set(names)):
        raise ValueError("Provide distinct paddock names")
    return [{"id":uuid4().hex,"name":n,"enabled":True,"start_date":today.isoformat(),
             "preset":"vigor_regrowth_n40_spec_response","notes":""} for n in names]
