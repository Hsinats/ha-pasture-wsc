"""FAO-56 daily single-Kc water balance; WSC wi linkage remains a proxy."""
from .fao import numeric, reference_et

VERSION = "fao56-pm-v1"
# Representative choices within FAO-56 Table 19 ranges, not site measurements.
SOIL_WATER = {"sandy":(.12,.04),"loam":(.27,.12),"clay":(.36,.22),"unsure":(.27,.12)}


def estimate_day(previous, weather, soil_type, initial_wi, *, day=None, latitude=None,
                 elevation=0, root_depth=.5, crop_coefficient=.85, wind_height=10):
    """Equations 58, 81–86: rain before ET, zero runoff/irrigation/capillary rise.

    Hold storage over gaps. Storage / TAW is NOT a verified FONSCH index.
    """
    fc,wp = SOIL_WATER[soil_type]
    if not numeric(root_depth) or not .1 <= root_depth <= 3 or not numeric(crop_coefficient) or not .1 <= crop_coefficient <= 1.5:
        raise ValueError("Invalid root depth or crop coefficient")
    capacity = 1000*(fc-wp)*root_depth
    flags = ["soil_properties_assumed","constant_kc_assumption","approximate_wi_mapping",
             "zero_runoff_irrigation_capillary_rise_assumed"]
    if soil_type == "unsure":
        flags.append("loam_properties_assumed")
    rain = weather.get("precipitation",{}).get("value")
    temperature = weather.get("temperature",{})
    solar = weather.get("solar_energy",{}).get("value")
    series = [i["value"] for i in temperature.get("intervals",[]) if numeric(i.get("value"))]
    tmin = temperature.get("minimum", min(series) if series else None)
    tmax = temperature.get("maximum", max(series) if series else None)
    if series and ("minimum" not in temperature or "maximum" not in temperature):
        flags.append("temperature_extrema_from_interval_series")
    missing = []
    for key,value in (("precipitation",rain),("temperature_minimum",tmin),("temperature_maximum",tmax),("solar_energy",solar)):
        if not numeric(value) or (key in ("precipitation","solar_energy") and value < 0):
            missing.append(key)
    if temperature.get("value") is None:
        missing.append("temperature_coverage")
    prior = initial_wi if previous is None or previous.get("value") is None else previous["value"]
    if not numeric(prior) or not 0 <= prior <= 1:
        raise ValueError("Initial moisture must be between 0 and 1")
    if previous is None:
        flags.append("initial_moisture_assumed")
    et = {}
    if not missing:
        try:
            et = reference_et(day,latitude,elevation,tmin,tmax,solar,
                humidity=weather.get("humidity",{}).get("value"),
                wind=weather.get("wind_speed",{}).get("value"),wind_height=wind_height)
        except (ValueError,TypeError,AttributeError):
            missing.append("fao_inputs_or_location")
    if numeric(tmax) and tmax <= 0:
        missing.append("frozen_day_unsupported")
    valid = not missing
    flags.extend(et.get("flags",[]))
    if numeric(weather.get("wind_speed",{}).get("value")):
        flags.append("configured_wind_height_assumed")
    assumed_days = (previous or {}).get("assumed_days",0)+int(not valid)
    if assumed_days:
        flags.append("assumed_weather_history")
    value = prior
    drying = drainage = ks = potential = None
    if valid:
        available = prior*capacity+rain
        stored = min(capacity,available)
        potential = crop_coefficient*et["eto_mm"]
        p = max(.1,min(.8,.6+.04*(5-potential)))
        depletion = capacity-stored
        ks = 1 if depletion <= p*capacity else stored/((1-p)*capacity)
        drying = min(stored,ks*potential)
        # FAO-56 Eq 88: excess rain after ET drains below the root zone.
        drainage = max(0,available-drying-capacity)
        value = min(capacity,max(0,available-drying-drainage))/capacity
    else:
        flags.extend(("missing_or_invalid_weather","moisture_held_missing_weather"))
    return {"value":value,"method":VERSION,"soil_type":soil_type,"capacity_mm":capacity,
            "field_capacity":fc,"wilting_point":wp,"root_depth_m":root_depth,"crop_coefficient":crop_coefficient,
            "rainfall_mm":rain,"drying_mm":drying,"drainage_mm":drainage,"initial_wi":initial_wi,
            "eto_mm":et.get("eto_mm"),"potential_crop_et_mm":potential,"stress_coefficient":ks,
            "wind_height_m":wind_height,"wind_2m_m_s":et.get("wind_2m_m_s"),
            "assumed_days":assumed_days,"status":"weather_estimate" if valid else "held_assumption",
            "missing_inputs":missing,"flags":flags,"basis":"plant_available_water_fraction_not_vwc"}
