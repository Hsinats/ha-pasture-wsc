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

PRESET = "vigor_regrowth_n40_spec_response"
DEFAULT_PADDOCK = {"enabled":True,"preset":PRESET,"notes":"","moisture_kind":"unknown",
    "moisture_entity":"","moisture_semantics":"Unknown; no soil conversion",
    "moisture_freshness":3600,"index_compatible":False,"moisture_mode":"unset",
    "scenario_enabled":False,"assumed_wi":.47,"gdd_base":5.0}


def validate_paddock(value):
    p = {**deepcopy(DEFAULT_PADDOCK),**deepcopy(value)}
    p.pop("moisture_justification",None)
    if not p.get("id") or not p.get("name","").strip() or len(p["name"]) > 100:
        raise ValueError("Paddock ID and name required")
    date.fromisoformat(p["start_date"])
    if p["preset"] != PRESET or p["moisture_kind"] not in ("unknown","shared_diagnostic","diagnostic_sensor","calibrated_index"):
        raise ValueError("Unknown preset or moisture source")
    if p["moisture_mode"] != "unset":
        MoistureMode(p["moisture_mode"])
    if p["moisture_kind"] in ("diagnostic_sensor","calibrated_index") and not p["moisture_entity"].startswith("sensor."):
        raise ValueError("Select a soil/index sensor")
    for key,low,high in (("assumed_wi",0,1),("moisture_freshness",60,86400),("gdd_base",-10,20)):
        v = float(p[key])
        if not isfinite(v) or not low <= v <= high:
            raise ValueError("Invalid paddock numeric setting")
        p[key] = v
    if len(p["notes"]) > 255 or not p["moisture_semantics"].strip():
        raise ValueError("Notes limited to 255 characters; soil semantics required")
    if p["moisture_kind"] == "calibrated_index" and not p["index_compatible"]:
        raise ValueError("Compatible index attestation required")
    return p


def initialize_paddocks(data, configured, zone, location=None):
    data.setdefault("paddocks",{})
    data.setdefault("paddock_results",{})
    data.setdefault("soil_observations",[])
    for value in configured:
        if value["id"] in data["paddocks"]:
            continue
        p = validate_paddock(value)
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
                           "history_gap":False,"soil":{},"warnings":["experimental_unvalidated",cycle["initialization"]]},"records":[]}
    mode = None if p["moisture_mode"] == "unset" else MoistureMode(p["moisture_mode"])
    primary,scenario,soil_days = {},{},{}
    cumulative_gdd,scenario_gdd,gdd_gap,scenario_gdd_gap = 0.0,0.0,False,False
    gdds,scenario_gdds = {},{}
    for offset in range(max(0,(end-start).days+1)):
        day = start+timedelta(days=offset)
        record = weather.get(day,{})
        if record and (record.get("timezone",cycle["timezone"])!=cycle["timezone"] or
                       cycle.get("location") is not None and record.get("location") != cycle["location"]):
            record = {}
        w = record.get("weather",{})
        temperature = w.get("temperature",{}).get("value")
        radiation = w.get("solar_energy",{}).get("value")
        t_strict = all(i["quality"] in ("observed","provider") for i in w.get("temperature",{}).get("intervals",[]))
        r_strict = all(i["quality"] in ("observed","provider") for i in w.get("solar_energy",{}).get("intervals",[]))
        soil = moisture_day(day,cycle["timezone"],p["id"],soil_observations,config["minimum_coverage"])
        soil_days[day] = soil
        known = p["moisture_kind"] == "calibrated_index" and p["index_compatible"] and soil["value"] is not None
        index = SoilIndex(soil["value"],p["moisture_semantics"],True) if known else None
        hashes = (record.get("hash","missing_weather"),soil["hash"])
        primary[day] = DailyInput(record.get("daylength"),temperature if t_strict else None,
                                  radiation if r_strict else None,index,hashes)
        assumed = index if index is not None else SoilIndex(p["assumed_wi"],"Explicit whole-cycle assumed wi scenario",True,True)
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
        row["hash"] = sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
        rows.append(row)
    return {"latest":rows[-1],"records":rows}
