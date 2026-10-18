"""Pure paddock lifecycle/replay helpers; no HA imports or soil conversion."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from math import isfinite
from uuid import uuid4

from .engine import MODEL_VERSION
from .engine.history import DailyInput, replay
from .engine.model import SoilIndex, MoistureMode, calculate
from .engine.astronomy import local_day_bounds
from .soil import estimate_day
from .const import SOIL_TYPES

PRESET = "vigor_regrowth_n40_spec_response"
WSC_ROUTES = ("primary", "scenario")
DEFAULT_PADDOCK = {"root_depth":.5,"crop_coefficient":.85,"wind_height":10.0,"soil_type":"unsure","enabled":True,"preset":PRESET,"notes":"","moisture_kind":"unknown",
    "moisture_entity":"","moisture_semantics":"Unknown; no soil conversion",
    "moisture_freshness":3600,"index_compatible":False,"moisture_mode":"unset",
    "scenario_enabled":False,"assumed_wi":.47,"gdd_base":5.0,"wsc_preference":"primary",
    "carbohydrate_low_cutoff":8.0,"carbohydrate_high_cutoff":12.0}


def validate_paddock(value):
    p = {**deepcopy(DEFAULT_PADDOCK),**deepcopy(value)}
    if p["soil_type"] not in SOIL_TYPES:
        raise ValueError("Unknown soil type")
    p.pop("moisture_justification",None)
    if not p.get("id") or not p.get("name","").strip() or len(p["name"]) > 100:
        raise ValueError("Paddock ID and name required")
    date.fromisoformat(p["start_date"])
    if p["preset"] != PRESET or p["moisture_kind"] not in ("unknown","shared_diagnostic","diagnostic_sensor","calibrated_index"):
        raise ValueError("Unknown preset or moisture source")
    for key in ("carbohydrate_low_cutoff", "carbohydrate_high_cutoff"):
        p[key] = float(p[key])
        if not isfinite(p[key]):
            raise ValueError("Carbohydrate cutoffs must be finite")
    if not 0 < p["carbohydrate_low_cutoff"] < p["carbohydrate_high_cutoff"] <= 100:
        raise ValueError("Carbohydrate cutoffs must be ordered percentages between 0 and 100")
    if p["wsc_preference"] not in WSC_ROUTES:
        raise ValueError("Unknown WSC route preference")
    if p["moisture_mode"] != "unset":
        MoistureMode(p["moisture_mode"])
    if p["moisture_kind"] in ("diagnostic_sensor","calibrated_index") and not p["moisture_entity"].startswith("sensor."):
        raise ValueError("Select a soil/index sensor")
    for key,low,high in (("root_depth",.1,3),("crop_coefficient",.1,1.5),("wind_height",.5,100),("assumed_wi",0,1),("moisture_freshness",60,86400),("gdd_base",-10,20)):
        v = float(p[key])
        if not isfinite(v) or not low <= v <= high:
            raise ValueError("Invalid paddock numeric setting")
        p[key] = v
    if len(p["notes"]) > 255 or not p["moisture_semantics"].strip():
        raise ValueError("Notes limited to 255 characters; soil semantics required")
    if p["moisture_kind"] == "calibrated_index" and not p["index_compatible"]:
        raise ValueError("Compatible index attestation required")
    return p


def selected_wsc(paddock, settings):
    """Choose a current finite result without depending on route sensor entities."""
    if not settings.get("enabled", True):
        return None, None
    preferred = settings.get("wsc_preference", "primary")
    routes = (preferred, "scenario" if preferred == "primary" else "primary")
    for route in routes:
        if route == "scenario" and not settings.get("scenario_enabled", False):
            continue
        value = paddock.get(route, {}).get("experimental_wsc")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
            return route, value
    return None, None


def carbohydrate_level(paddock, settings):
    """Descriptive WSC bands, not animal-specific feeding or safety thresholds."""
    _, value = selected_wsc(paddock, settings)
    if value is None:
        return None
    low = settings.get("carbohydrate_low_cutoff", 8.0)
    high = settings.get("carbohydrate_high_cutoff", 12.0)
    return "low" if value < low else "medium" if value < high else "high"


def diagnostic_summary(paddock, settings):
    """User-facing diagnostics follow the same current route as WSC (auto)."""
    route,value = selected_wsc(paddock,settings)
    method = paddock.get("selected_moisture_method")
    estimate = paddock.get("estimated_soil",{})
    history_gap = paddock.get("scenario_history_gap") if settings.get("scenario_enabled") else paddock.get("history_gap")
    if route == "primary" or method == "measured":
        moisture = "measured"
    elif settings.get("scenario_enabled"):
        moisture = {"measured":"measured","weather_estimate":"fao_estimate",
                    "held_assumption":"held_assumption","fixed_assumption":"starting_assumption"}.get(method,"not_calculated")
    else:
        moisture = "no_sensor_configured" if settings.get("moisture_kind","unknown") != "calibrated_index" else "waiting_for_soil"
    if not settings.get("enabled",True):
        status = "disabled"
    elif value is not None:
        status = "ready_measured" if route == "primary" else "ready_estimated"
    elif paddock.get("status") == "awaiting_first_completed_day":
        status = "waiting_first_day"
    elif settings.get("moisture_mode","unset") == "unset":
        status = "choose_moisture_response"
    elif not settings.get("scenario_enabled") and paddock.get("status") == "pending_soil":
        status = "waiting_for_soil"
    elif history_gap:
        status = "missing_history"
    else:
        status = "waiting_weather"
    assumed = estimate.get("assumed_days",0) if route == "scenario" or (route is None and settings.get("scenario_enabled")) else 0
    missing_development = (paddock.get("scenario_days",0)-paddock.get("scenario_valid_development_days",0)
                           if settings.get("scenario_enabled") and route != "primary" else 0)
    gaps = []
    if assumed:
        gaps.append(f"{assumed} day{'s' if assumed != 1 else ''} used assumed moisture")
    if missing_development:
        gaps.append(f"{missing_development} day{'s' if missing_development != 1 else ''} missing development inputs")
    if not gaps:
        gaps.append("No gaps in selected calculation" if route else "Not calculated yet")
    return {"calculation_status":status,"wsc_method":"measured" if route == "primary" else "estimated" if route else "no_result",
            "moisture_method":moisture,"calculated_through":paddock.get("day") if route else None,
            "data_gaps":"; ".join(gaps),"assumed_moisture_days":assumed,
            "missing_development_days":missing_development}


def initialize_paddocks(data, configured, zone, location=None, soil_type="unsure"):
    data.setdefault("paddocks",{})
    data.setdefault("paddock_results",{})
    data.setdefault("soil_observations",[])
    for existing in data["paddocks"].values():
        existing["settings"].setdefault("soil_type",soil_type)
        for key in ("root_depth","crop_coefficient","wind_height"):
            existing["settings"].setdefault(key,DEFAULT_PADDOCK[key])
    for value in configured:
        if value["id"] in data["paddocks"]:
            continue
        p = validate_paddock({"soil_type":soil_type,**value})
        cycle = {"id":uuid4().hex,"start_date":p["start_date"],"timezone":zone,
                 "location":deepcopy(location),
                 "initialization":"pragmatic_date_reset_not_dry_matter_threshold","archived_at":None}
        data["paddocks"][p["id"]] = {"settings":p,"cycle":cycle,"archives":[],"reset_request":None,"revision":0}


def update_paddock(state, changes):
    if any(k in changes for k in ("id","start_date","cycle")):
        raise ValueError("Growth start changes require a confirmed new cycle")
    state["settings"] = validate_paddock({**state["settings"],**changes})
    state["revision"] += 1


def start_cycle(state, start, now, zone, *, confirmed=False, expected_cycle=None):
    if not confirmed or expected_cycle != state["cycle"]["id"]:
        raise ValueError("Explicit confirmation of the current cycle required")
    if start > now.date() or (now.date()-start).days > 3660:
        raise ValueError("Cycle start must be today or within the preceding 3660 days")
    old = deepcopy(state["cycle"])
    old["archived_at"] = now.isoformat()
    old["settings_at_archive"] = deepcopy(state["settings"])
    state["archives"].append(old)
    state["cycle"] = {"id":uuid4().hex,"start_date":start.isoformat(),"timezone":zone,
        "initialization":"pragmatic_date_reset_not_dry_matter_threshold","archived_at":None}
    state["settings"]["start_date"] = start.isoformat()
    state["reset_request"] = None
    state["revision"] += 1


def moisture_day(day,zone,paddock_id,observations,minimum_coverage):
    """Time-weight compatible dimensionless wi, never VWC or a generic slider."""
    a,b = local_day_bounds(day,zone)
    readings = sorted((r for r in observations if r["paddock_id"]==paddock_id),key=lambda r:r["timestamp"])
    total = covered = 0.0
    sources,flags,raw = set(),set(),[]
    for n,r in enumerate(readings):
        start = datetime.fromisoformat(r["timestamp"])
        end = min(b,datetime.fromisoformat(r["reported"])+timedelta(seconds=r["freshness"]))
        if n+1<len(readings):
            end = min(end,datetime.fromisoformat(readings[n+1]["timestamp"]))
        start = max(start,a)
        if end <= start:
            continue
        raw.append(r)
        if r["status"] != "valid" or not r.get("compatible"):
            flags.add(r["status"] if r["status"]!="valid" else "uncalibrated_soil")
            continue
        try:
            wi = float(r["value"])
            if not isfinite(wi) or not 0<=wi<=1 or r["unit"] not in ("","1","dimensionless"):
                raise ValueError
        except (TypeError,ValueError):
            flags.add("invalid_or_noncompatible_index_units")
            continue
        seconds = (end-start).total_seconds()
        total += wi*seconds
        covered += seconds
        sources.add(r["entity_id"])
    coverage = covered/(b-a).total_seconds()
    if coverage < minimum_coverage:
        flags.add("insufficient_soil_coverage")
    digest = sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest()
    return {"value":total/covered if covered and coverage>=minimum_coverage else None,
            "coverage":coverage,"source":sorted(sources),"flags":sorted(flags),"hash":digest}


def calculate_paddock(state,end,weather,soil_observations,config):
    """Replay active cycle from dated input records; versions retained by caller."""
    p,cycle = state["settings"],state["cycle"]
    start = date.fromisoformat(cycle["start_date"])
    if end<start or not p["enabled"] or (end-start).days>3660:
        return {"latest":{"day":end.isoformat(),"status":"disabled" if not p["enabled"] else "cycle_range_exceeds_limit" if (end-start).days>3660 else "awaiting_first_completed_day",
                           "scenario_status":"off" if not p["scenario_enabled"] else "awaiting_first_completed_day",
                           "primary":{},"scenario":{},"gdd":None,"scenario_gdd":None,"last_completed_day":None,
                           "rain_accumulation":{"value":0.0,"start_date":start.isoformat(),
                               "end_date":None,"days_with_data":0,"missing_days":0,"complete":False},
                           "history_gap":False,"soil":{},"warnings":["experimental_unvalidated",cycle["initialization"]]},"records":[]}
    mode = None if p["moisture_mode"] == "unset" else MoistureMode(p["moisture_mode"])
    primary,scenario,soil_days = {},{},{}
    estimated_soil_days, moisture_routes = {}, {}
    previous_estimate = None
    rain_total, rain_days = 0.0, 0
    rain_summaries = {}
    cumulative_gdd,scenario_gdd,gdd_gap,scenario_gdd_gap = 0.0,0.0,False,False
    gdds,scenario_gdds = {},{}
    for offset in range(max(0,(end-start).days+1)):
        day = start+timedelta(days=offset)
        record = weather.get(day,{})
        if record and (record.get("timezone",cycle["timezone"])!=cycle["timezone"] or
                       cycle.get("location") is not None and record.get("location") != cycle["location"]):
            record = {}
        w = record.get("weather",{})
        rain = w.get("precipitation",{}).get("value")
        rain_valid = isinstance(rain,(int,float)) and not isinstance(rain,bool) and isfinite(rain) and rain >= 0
        if rain_valid:
            rain_total += rain
            rain_days += 1
        rain_summaries[day] = {"value":rain_total,
            "start_date":start.isoformat(),"end_date":day.isoformat(),
            "days_with_data":rain_days,"missing_days":offset+1-rain_days,
            "complete":rain_days == offset+1,"daily_rainfall_mm":rain if rain_valid else None,
            "basis":"available_daily_rainfall_including_forecast_estimates"}
        temperature = w.get("temperature",{}).get("value")
        radiation = w.get("solar_energy",{}).get("value")
        t_strict = all(i["quality"] in ("observed","provider") for i in w.get("temperature",{}).get("intervals",[]))
        r_strict = all(i["quality"] in ("observed","provider") for i in w.get("solar_energy",{}).get("intervals",[]))
        soil = moisture_day(day,cycle["timezone"],p["id"],soil_observations,config["minimum_coverage"])
        soil_days[day] = soil
        known = p["moisture_kind"] == "calibrated_index" and p["index_compatible"] and soil["value"] is not None
        index = SoilIndex(soil["value"],p["moisture_semantics"],True) if known else None
        estimate = estimate_day(previous_estimate,w,p.get("soil_type",config.get("soil_type","unsure")),p["assumed_wi"],
            day=day,latitude=config["latitude"],elevation=config["elevation"],
            root_depth=p.get("root_depth",.5),crop_coefficient=p.get("crop_coefficient",.85),wind_height=p.get("wind_height",10))
        previous_estimate = estimate
        estimated_soil_days[day] = estimate
        soil["measured_value"] = index.value if index is not None else None
        hashes = (record.get("hash","missing_weather"),soil["hash"])
        primary[day] = DailyInput(record.get("daylength"),temperature if t_strict else None,
                                  radiation if r_strict else None,index,hashes)
        assumed = index if index is not None else SoilIndex(p["assumed_wi"],"Explicit whole-cycle assumed wi scenario",True,True)
        moisture_routes[day] = "measured" if index is not None else "fixed_assumption"
        if index is None and estimate["value"] is not None:
            assumed = SoilIndex(estimate["value"],"Uncalibrated rainfall/drying bucket proxy for wi",True,True)
            moisture_routes[day] = "weather_estimate" if estimate["status"] == "weather_estimate" else "held_assumption"
        estimate_hash = sha256(json.dumps(estimate,sort_keys=True).encode()).hexdigest()
        hashes = (*hashes,estimate_hash,moisture_routes[day])
        scenario[day] = DailyInput(record.get("daylength"),temperature,radiation,assumed,hashes,not(t_strict and r_strict))
        if temperature is None or not t_strict:
            gdd_gap = True
        if temperature is None:
            scenario_gdd_gap = True
        if not gdd_gap:
            cumulative_gdd += max(0,temperature-p["gdd_base"])
        if not scenario_gdd_gap:
            scenario_gdd += max(0,temperature-p["gdd_base"])
        gdds[day] = None if gdd_gap else cumulative_gdd
        scenario_gdds[day] = None if scenario_gdd_gap else scenario_gdd
    results = replay(start,end,primary,mode)
    scenarios = replay(start,end,scenario,mode,scenario=True) if p["scenario_enabled"] else ()
    rows,last_complete = [],None
    scenario_valid_days = 0
    scenario_missing_days = []
    for n,r in enumerate(results):
        if scenarios:
            if scenarios[n].components.development is None:
                scenario_missing_days.append(r.day.isoformat())
            else:
                scenario_valid_days += 1
        observed_day = weather.get(r.day,{})
        effects = calculate(observed_day.get("daylength"),observed_day.get("weather",{}).get("temperature",{}).get("value"),
                            observed_day.get("weather",{}).get("solar_energy",{}).get("value"))
        row = {"day":r.day.isoformat(),"cycle_id":cycle["id"],"paddock_id":p["id"],"model_version":MODEL_VERSION,
            "primary":{**asdict(r.components),"spechr":r.spechr},
            "scenario":{**asdict(scenarios[n].components),"spechr":scenarios[n].spechr} if scenarios else {},
            "gdd":gdds[r.day],"scenario_gdd":scenario_gdds[r.day] if scenarios else None,
            "calculated_cycle_start":start.isoformat(),"scenario_days":n+1 if scenarios else 0,
            "scenario_valid_development_days":scenario_valid_days,
            "scenario_missing_development_days":scenario_missing_days[:31].copy(),
            "scenario_history_gap":scenarios[n].incomplete_history if scenarios else None,
            "history_gap":r.incomplete_history,"soil":soil_days[r.day],
            "estimated_soil":estimated_soil_days[r.day],"selected_moisture_method":moisture_routes[r.day],
            "rain_accumulation":rain_summaries[r.day],
            "weather_effects":{"radiation_effect":effects.radiation_effect,"temperature_effect":effects.temperature_effect},
            "weather_quality":sorted({i["quality"] for key in ("temperature","solar_energy") for i in observed_day.get("weather",{}).get(key,{}).get("intervals",[])}),
            "settings":deepcopy(p),"timezone":cycle["timezone"],"initialization":cycle["initialization"],
            "input_hash":r.input_hash,"scenario_input_hash":scenarios[n].input_hash if scenarios else None}
        if r.components.experimental_wsc is not None:
            last_complete = row["day"]
        row["last_completed_day"] = last_complete
        row["status"] = "ready_experimental" if r.components.experimental_wsc is not None else "pending_soil" if primary[r.day].soil is None else "incomplete_history" if r.incomplete_history else "pending_moisture_mode" if mode is None else "pending_weather"
        row["scenario_status"] = "off" if not scenarios else "scenario_available" if scenarios[n].components.experimental_wsc is not None else "scenario_pending"
        row["warnings"] = list(r.components.warnings)+[cycle["initialization"]]
        # Compare the final selected WSC on adjacent days, allowing either route.
        current_wsc = selected_wsc(row, p)[1]
        previous_wsc = selected_wsc(rows[-1], p)[1] if rows else None
        row["daily_change"] = (current_wsc-previous_wsc
                               if current_wsc is not None and previous_wsc is not None else None)
        current_scenario = row["scenario"].get("experimental_wsc")
        previous_scenario = rows[-1]["scenario"].get("experimental_wsc") if rows else None
        row["scenario_daily_change"] = (current_scenario-previous_scenario
                                        if current_scenario is not None and previous_scenario is not None else None)
        row["hash"] = sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
        rows.append(row)
    return {"latest":rows[-1],"records":rows}
