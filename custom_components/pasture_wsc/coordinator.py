"""Persist observations and derive shared completed-day diagnostics."""
from copy import deepcopy
import asyncio
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
from math import cos, sin, pi
from zoneinfo import ZoneInfo

from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.core import callback
from homeassistant.helpers.event import (async_track_state_change_event, async_track_state_report_event,
                                         async_track_point_in_utc_time, async_track_time_interval)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, MAX_BACKFILL_DAYS, VARIABLES
from .engine import MODEL_VERSION, INPUT_VERSION
from .engine.astronomy import daylength, geometry, local_day_bounds, extraterrestrial_radiation
from .engine.model import calculate
from .engine.weather import Interval, Quality, SourcePolicy, Variable, resolve_day
from .schedule import next_run, scheduled_day
from .storage import PastureStore
from .weather import (build_intervals, capture, decode_interval, forecast_records,
                       serializable, source_key, sources_for)
from .paddocks import initialize_paddocks, calculate_paddock, update_paddock, start_cycle
from .settings import paddocks_from_names

_LOGGER = logging.getLogger(__name__)


def day_observations(raw, start, end):
    """Include one baseline before the day for each source, never future states."""
    previous, selected = {}, []
    for item in sorted(raw,key=lambda r:r["timestamp"]):
        when = datetime.fromisoformat(item["timestamp"])
        if when < start:
            previous[item["source_key"]] = item
        elif when < end:
            selected.append(item)
    return list(previous.values())+selected


def estimated_solar(day, config, cloud):
    """Opt-in 5-minute solar geometry/cloud scenario, zero at night.

    Allocate FAO daily extraterrestrial radiation over positive solar-elevation
    weights using longitude-based solar noon (equation of time omitted).
    Cloud coverage must support each represented daylight interval.
    """
    if not config["estimate_solar"]:
        return []
    start,end = local_day_bounds(day,config["timezone"])
    phi,declination,_ = geometry(day,config["latitude"])
    slots,weight = [],0.0
    point = start
    while point < end:
        stop = min(end,point+timedelta(minutes=5))
        middle = point+(stop-point)/2
        hour = middle.hour+middle.minute/60+middle.second/3600+config["longitude"]/15
        elevation = sin(phi)*sin(declination)+cos(phi)*cos(declination)*cos(pi/12*(hour-12))
        w = max(0,elevation)*(stop-point).total_seconds()
        slots.append((point,stop,w))
        weight += w
        point = stop
    ra = extraterrestrial_radiation(day,config["latitude"])
    result = []
    for a,b,w in slots:
        c = next((i for i in cloud.intervals if i.start <= a and i.end >= b),None)
        if w > 0 and c is None and not config["assume_clear_sky"]:
            continue
        quality = Quality.ASSUMED if c is None and w > 0 else Quality.ESTIMATED
        value = 0 if weight == 0 else ra*w/weight*.75*(1-.75*((c.value if c else 0)/100)**3)
        flags = ("uncalibrated_cloud_radiation","five_minute_solar_geometry","equation_of_time_omitted")
        if quality == Quality.ASSUMED:
            flags += ("explicit_clear_sky_assumption",)
        if c is not None and c.quality == Quality.FORECAST:
            quality = Quality.FORECAST
        result.append(Interval(Variable.SOLAR_ENERGY,a,b,value,"astronomy_cloud",quality,b,"MJ/m²",flags=flags))
    return result


def daily_record(day, config, data):
    start,end = local_day_bounds(day,config["timezone"])
    raw = day_observations(data["observations"],start,end)
    intervals,policies,anomalies = build_intervals(raw,config)
    if config["allow_forecast"]:
        for item in data["forecasts"].values():
            interval = decode_interval(item)
            if interval.start < end and interval.end > start:
                intervals.append(interval)
                variable = interval.variable
                if not any(p.source == interval.source for p in policies[variable]):
                    entity = interval.source[len("forecast:"):].rsplit(":",1)[0]
                    rank = config["weather_entities"].index(entity) if entity in config["weather_entities"] else 1000
                    policies[variable].append(SourcePolicy(interval.source,500+rank,86400,frozenset({Quality.FORECAST})))
    summaries = {}
    for name in ("temperature","cloud_cover","humidity","precipitation"):
        variable = Variable(name)
        summaries[name] = resolve_day(day,config["timezone"],variable,intervals,policies[variable],minimum_coverage=config["minimum_coverage"])
    estimates = estimated_solar(day,config,summaries["cloud_cover"])
    if estimates:
        intervals.extend(estimates)
        policies[Variable.SOLAR_ENERGY].append(SourcePolicy("astronomy_cloud",900,86400,
            frozenset({Quality.ESTIMATED,Quality.ASSUMED,Quality.FORECAST})))
    summaries["solar_energy"] = resolve_day(day,config["timezone"],Variable.SOLAR_ENERGY,intervals,
        policies[Variable.SOLAR_ENERGY],minimum_coverage=config["solar_minimum_coverage"])
    length = daylength(day,config["latitude"])
    factors = calculate(length,summaries["temperature"].value,summaries["solar_energy"].value)
    ready = summaries["temperature"].value is not None and summaries["solar_energy"].value is not None
    strict = ready and all(i.quality in (Quality.OBSERVED,Quality.PROVIDER)
                          for name in ("temperature","solar_energy") for i in summaries[name].intervals)
    record = serializable({"day":day,"timezone":config["timezone"],"location":{k:config[k] for k in ("latitude","longitude","elevation")},
        "weather":summaries,"daylength":length,"photoperiod_factor":factors.photoperiod_factor,
        "temperature_factor":factors.temperature_factor,"moisture_factor":None,"development":None,
        "model_status":"pending_soil_and_paddock_model","weather_status":"ready" if strict else "scenario_only" if ready else "pending_weather",
        "complete":False,"weather_complete":strict,"anomalies":anomalies,
        "source_entities":{r["source_key"]:r["source"]["entity_id"] for r in raw},
        "source_variables":{r["source_key"]:("solar_energy" if r["source"]["variable"] == "irradiance" else r["source"]["variable"]) for r in raw},
        "model_version":MODEL_VERSION,"input_version":INPUT_VERSION,
        "policy":{k:v for k,v in config.items() if k not in ("paddocks","soil_entity","soil_semantics")}})
    record["hash"] = sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()
    return record


class PastureCoordinator(DataUpdateCoordinator):
    def __init__(self,hass,entry,config):
        super().__init__(hass,_LOGGER,name=DOMAIN,config_entry=entry,always_update=False)
        self.entry,self.config = entry,config
        self.store = PastureStore(hass,entry.entry_id)
        self.sources = sources_for(config)
        self.unsubs = []
        self.timer = None
        self.last_forecast = None
        self.closed = False
        self._seen = {}
        self._operation_lock = asyncio.Lock()

    async def async_start(self):
        await self.store.load()
        initialize_paddocks(self.store.data,self.config["paddocks"],self.config["timezone"],{k:self.config[k] for k in ("latitude","longitude","elevation")})
        self.store.data["settings_revisions"].append({"at":datetime.now(timezone.utc).isoformat(),"settings":deepcopy(self.config)})
        now = datetime.now(timezone.utc)
        active = {source_key(s) for s in self.sources}
        # End retired mappings; avoid carrying their held values into a new mapping.
        retired = {}
        for item in self.store.data["observations"]:
            if item["source_key"] not in active:
                retired[item["source_key"]] = item
        for item in retired.values():
            if item["status"] != "mapping_retired":
                self.store.observation({**item,"timestamp":now.isoformat(),"status":"mapping_retired","value":None})
        await self.async_collect(initial=True)
        entities = {s["entity_id"] for s in self.sources}
        if self.config["soil_entity"]:
            entities.add(self.config["soil_entity"])
        entities.update(p["settings"]["moisture_entity"] for p in self.store.data["paddocks"].values() if p["settings"]["moisture_entity"])
        self.unsubs.extend([
            async_track_state_change_event(self.hass,entities,self._state_event),
            async_track_state_report_event(self.hass,entities,self._state_event),
            async_track_time_interval(self.hass,self._tick,timedelta(minutes=5)),
        ])
        await self.async_refresh()
        self._schedule()

    @callback
    def _state_event(self,event):
        self.entry.async_create_background_task(self.hass,self.async_collect(),"pasture observation")

    async def async_collect(self,initial=False):
        async with self._operation_lock:
            if self.closed:
                return
            now = datetime.now(timezone.utc)
            for source in self.sources:
                state = self.hass.states.get(source["entity_id"])
                health = capture(source,state,now,initial=False)
                issue_key = source_key(source)
                if health["status"] != "valid":
                    self.store.data["collector_issues"][issue_key] = health["status"]
                else:
                    self.store.data["collector_issues"].pop(issue_key,None)
                marker = state.last_reported.isoformat() if state is not None else "unavailable"
                key = source_key(source)
                if not initial and self._seen.get(key) == marker:
                    continue
                self._seen[key] = marker
                self.store.observation(capture(source,state,now,initial=initial))
            if self.config["soil_entity"]:
                source = {"id":"soil_diagnostic","entity_id":self.config["soil_entity"],"variable":"soil", "kind":"diagnostic",
                          "priority":0,"freshness":self.config["soil_freshness"],"semantics":self.config["soil_semantics"]}
                item = capture(source,self.hass.states.get(source["entity_id"]),now,initial=initial)
                item["semantics"] = self.config["soil_semantics"]
                item["fonsch_compatible"] = False
                self.store.data["soil"] = item
            for pid,paddock in self.store.data["paddocks"].items():
                p = paddock["settings"]
                if p["moisture_kind"] not in ("diagnostic_sensor","calibrated_index"):
                    continue
                state = self.hass.states.get(p["moisture_entity"])
                marker = state.last_reported.isoformat() if state is not None else "unavailable"
                key = f"paddock_soil:{pid}:{paddock['revision']}"
                if not initial and self._seen.get(key) == marker:
                    continue
                self._seen[key] = marker
                source = {"id":key,"entity_id":p["moisture_entity"],"variable":"soil","kind":"diagnostic",
                    "priority":0,"freshness":p["moisture_freshness"],"semantics":p["moisture_semantics"]}
                item = capture(source,state,now,initial=initial)
                item.update({"paddock_id":pid,"entity_id":p["moisture_entity"],"freshness":p["moisture_freshness"],
                    "compatible":p["moisture_kind"] == "calibrated_index" and p["index_compatible"],
                    "semantics":p["moisture_semantics"],"justification":p["moisture_justification"]})
                self.store.data["soil_observations"].append(item)
            if self.config["allow_forecast"] and (self.last_forecast is None or now-self.last_forecast >= timedelta(hours=1)):
                await self._collect_forecasts(now)
                self.last_forecast = now
            await self.store.save()

    async def _collect_forecasts(self,now):
        for entity in self.config["weather_entities"]:
            state = self.hass.states.get(entity)
            if state is None or not int(state.attributes.get("supported_features",0)) & WeatherEntityFeature.FORECAST_HOURLY:
                self.store.data["collector_issues"][entity] = "hourly_forecast_unsupported_or_unavailable"
                continue
            try:
                response = await self.hass.services.async_call("weather","get_forecasts",{"entity_id":entity,"type":"hourly"},
                    blocking=True,return_response=True)
                records = forecast_records(entity,response[entity].get("forecast",[]),state.attributes,now)
                self.store.forecasts(records)
                self.store.data["collector_issues"].pop(entity,None)
            except Exception as error:
                # Weather failure must not destroy collection or invent observed data.
                self.store.data["collector_issues"][entity] = type(error).__name__
                _LOGGER.debug("Forecast collection unavailable for %s: %s",entity,type(error).__name__)

    async def _tick(self,now):
        await self.async_collect()
        # Retry pending days using retained inputs, never today's value as yesterday's.
        await self.async_refresh()

    def _schedule(self):
        if self.timer:
            self.timer()
        self.timer = async_track_point_in_utc_time(self.hass,self._daily_run,
            next_run(datetime.now(timezone.utc),self.config["timezone"],self.config["calculation_time"]))

    async def _daily_run(self,now):
        try:
            await self.async_collect()
            await self.async_refresh()
        finally:
            if not self.closed:
                self._schedule()

    async def _async_update_data(self):
        now = datetime.now(timezone.utc)
        day = scheduled_day(now,self.config["timezone"],self.config["calculation_time"])
        return await self.async_recalculate(day-timedelta(days=6),day,publish=False)

    async def async_recalculate(self,start,end,*,publish=True):
        if end < start or (end-start).days >= MAX_BACKFILL_DAYS:
            raise ValueError("Date range must contain 1..31 days")
        today = datetime.now(timezone.utc).astimezone(ZoneInfo(self.config["timezone"])).date()
        if end >= today:
            raise ValueError("Only completed local dates may be calculated")
        async with self._operation_lock:
            snapshot = deepcopy(self.store.data)
            record = None
            for offset in range((end-start).days+1):
                day = start+timedelta(days=offset)
                record = await self.hass.async_add_executor_job(daily_record,day,self.config,snapshot)
                context = sha256(json.dumps({k:self.config[k] for k in ("timezone","latitude","longitude","elevation")},sort_keys=True).encode()).hexdigest()[:16]
                key = f"{day}|{MODEL_VERSION}|{context}"
                self.store.daily(key,record)
            await self.store.save()
            # Recalculating historical ranges never changes sensors to an older date.
            latest_day = max(end,scheduled_day(datetime.now(timezone.utc),self.config["timezone"],self.config["calculation_time"]))
            if end < latest_day:
                record = await self.hass.async_add_executor_job(daily_record,latest_day,self.config,snapshot)
                key = f"{latest_day}|{MODEL_VERSION}|{context}"
                self.store.daily(key,record)
            records = [versions[-1] for versions in self.store.data["daily"].values() if versions and
                       versions[-1]["timezone"] == self.config["timezone"] and versions[-1]["location"] == record["location"]]
            last_weather = max((r["day"] for r in records if r["weather_complete"]),default=None)
            result = {**record,"last_completed_day":None,"last_weather_completed_day":last_weather,
                      "collector_issues":deepcopy(self.store.data["collector_issues"]),"soil":deepcopy(self.store.data["soil"])}
            paddock_outputs = {}
            for pid,state in self.store.data["paddocks"].items():
                cycle = state["cycle"]
                cycle_records = [versions[-1] for versions in self.store.data["daily"].values() if versions and
                    versions[-1]["timezone"] == cycle["timezone"] and
                    (cycle.get("location") is None or versions[-1]["location"] == cycle["location"])]
                by_date = {date.fromisoformat(r["day"]):r for r in cycle_records}
                output = await self.hass.async_add_executor_job(calculate_paddock,deepcopy(state),latest_day,by_date,
                    deepcopy(self.store.data["soil_observations"]),self.config)
                for row in output["records"]:
                    self.store.paddock_result(row)
                paddock_outputs[pid] = {**output["latest"],"settings":deepcopy(state["settings"]),
                    "cycle":deepcopy(state["cycle"]),"reset_requested":state["reset_request"] is not None}
            result["paddocks"] = paddock_outputs
            enabled = [p for p in paddock_outputs.values() if p["settings"]["enabled"]]
            result["model_status"] = "ready_experimental" if enabled and all(p["status"]=="ready_experimental" for p in enabled) else "pending_paddock_inputs"
            result["last_completed_day"] = min((p["last_completed_day"] for p in enabled),default=None) if enabled and all(p["last_completed_day"] for p in enabled) else None
            result["complete"] = bool(enabled) and all(p["status"]=="ready_experimental" for p in enabled)
            await self.store.save()
        if publish:
            self.async_set_updated_data(result)
        return result

    async def async_update_paddock(self,pid,changes):
        async with self._operation_lock:
            update_paddock(self.store.data["paddocks"][pid],changes)
            await self.store.save()
        await self.async_refresh()

    async def async_request_cycle(self,pid):
        async with self._operation_lock:
            state = self.store.data["paddocks"][pid]
            state["reset_request"] = {"cycle_id":state["cycle"]["id"],"at":datetime.now(timezone.utc).isoformat()}
            await self.store.save()
        from homeassistant.components import persistent_notification
        persistent_notification.async_create(self.hass,
            f"To start a new growth cycle for {state['settings']['name']}, open Pasture WSC Configure → Manage paddocks → select this paddock → Start new growth cycle. Review the date and confirm. The current cycle has not changed.",
            title="Confirm paddock growth cycle",notification_id=f"pasture_reset_{self.entry.entry_id}_{pid}")
        await self.async_refresh()

    async def async_start_cycle(self,pid,start,expected_cycle,confirmed=False):
        async with self._operation_lock:
            now = datetime.now(timezone.utc).astimezone(ZoneInfo(self.config["timezone"]))
            start_cycle(self.store.data["paddocks"][pid],start,now,self.config["timezone"],confirmed=confirmed,expected_cycle=expected_cycle)
            self.store.data["paddocks"][pid]["cycle"]["location"] = {k:self.config[k] for k in ("latitude","longitude","elevation")}
            await self.store.save()
        await self.async_refresh()

    async def async_cancel_cycle_request(self,pid):
        async with self._operation_lock:
            self.store.data["paddocks"][pid]["reset_request"] = None
            await self.store.save()
        await self.async_refresh()

    async def async_add_paddock(self,name):
        async with self._operation_lock:
            if not name.strip() or name.strip() in {p["settings"]["name"] for p in self.store.data["paddocks"].values()}:
                raise ValueError("Distinct paddock name required")
            today = datetime.now(timezone.utc).astimezone(ZoneInfo(self.config["timezone"])).date()
            new = paddocks_from_names(name,today)
            if len(new)!=1:
                raise ValueError("One name required")
            initialize_paddocks(self.store.data,new,self.config["timezone"],{k:self.config[k] for k in ("latitude","longitude","elevation")})
            self.config["paddocks"] = self.config["paddocks"]+new
            self.hass.config_entries.async_update_entry(self.entry,data={**self.entry.data,"paddocks":self.config["paddocks"]})
            await self.store.save()

    async def async_close(self):
        self.closed = True
        if self.timer:
            self.timer()
            self.timer = None
        for unsub in self.unsubs:
            unsub()
        self.unsubs.clear()
        async with self._operation_lock:
            await self.store.save()
