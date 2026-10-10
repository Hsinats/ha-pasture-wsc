"""Local adapter contracts using explicit HA test doubles, not a live HA claim."""
import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from custom_components.pasture_wsc.const import DEFAULTS
from custom_components.pasture_wsc.settings import validate, validate_source, paddocks_from_names
from custom_components.pasture_wsc.storage import PastureStore
from custom_components.pasture_wsc.schedule import next_run, scheduled_day
from custom_components.pasture_wsc.weather import (build_intervals,capture,source_key,sources_for,forecast_records)

DAY = date(2026,6,1)
A = datetime(2026,6,1,4,tzinfo=timezone.utc)


def config(**overrides):
    return validate({**deepcopy(DEFAULTS),"latitude":43.7,"longitude":-79.4,"elevation":100,
                     "timezone":"America/Toronto",**overrides})


def source(**overrides):
    return {"id":"stable-source","entity_id":"sensor.station","variable":"temperature","kind":"instantaneous",
            "priority":0,"freshness":3600,"offset":0,"unit_override":"","semantics":"Calibrated air temperature",**overrides}


class MemoryStore:
    def __init__(self):
        self.data = None
    async def async_load(self):
        return deepcopy(self.data)
    async def async_save(self,value):
        self.data = deepcopy(value)


def test_store_restart_idempotency_and_versions():
    async def run():
        backend = MemoryStore()
        store = PastureStore(None,"entry",backend)
        await store.load()
        record = {"source_key":"x","timestamp":A.isoformat()}
        assert store.observation(record)
        assert not store.observation(record)
        assert store.daily("key",{"hash":"one"})
        assert not store.daily("key",{"hash":"one"})
        assert store.daily("key",{"hash":"two"})
        await store.save()
        restarted = PastureStore(None,"entry",backend)
        await restarted.load()
        assert restarted.data == store.data
        assert not restarted.observation(record)
        for n in range(1001):
            restarted.observation({"source_key":str(n),"timestamp":A.isoformat()})
        assert not restarted.observation(record)
        assert len(restarted.data["daily"]["key"]) == 2
        backend.data["schema"] = 999
        with pytest.raises(ValueError):
            await restarted.load()
        untouched = deepcopy(backend.data)
        failed = PastureStore(None,"entry",backend)
        with pytest.raises(ValueError):
            await failed.load()
        await failed.save()
        assert backend.data == untouched
    asyncio.run(run())


def test_capture_forward_only_stale_restored_units():
    s = source()
    state = SimpleNamespace(state="68",last_reported=A-timedelta(minutes=10),attributes={"unit_of_measurement":"°F","device_class":"temperature"})
    raw = capture(s,state,A,initial=True)
    assert raw["timestamp"] == A.isoformat() and raw["reported"] == state.last_reported.isoformat()
    intervals,_,_ = build_intervals([raw],config())
    assert intervals[0].value == 20
    state.last_reported = A-timedelta(hours=2)
    assert capture(s,state,A,initial=True)["status"] == "stale"
    state.attributes["restored"] = True
    assert capture(s,state,A)["status"] == "restored_not_observed"
    state.attributes = {"device_class":"humidity"}
    assert capture(s,state,A)["status"] == "device_class_mismatch"


def test_initial_snapshot_preserves_report_expiry_and_counter_uncertainty():
    from custom_components.pasture_wsc.engine.weather import resolve_day,Variable
    state = SimpleNamespace(state="20",last_reported=A-timedelta(minutes=59),attributes={"unit_of_measurement":"°C"})
    raw = capture(source(),state,A,initial=True)
    intervals,policies,_ = build_intervals([raw],config())
    result = resolve_day(DAY,"America/Toronto",Variable.TEMPERATURE,intervals,policies[Variable.TEMPERATURE])
    assert result.coverage == pytest.approx(60/86400)
    rain = source(variable="precipitation",kind="counter")
    assert capture(rain,state,A,initial=True)["status"] == "initial_counter_baseline_unverified"
    bad = SimpleNamespace(state="sunny",last_reported=A,attributes={"temperature":float('nan'),"temperature_unit":"°C"})
    raw = capture(source(entity_id="weather.met",kind="weather_proxy"),bad,A)
    assert raw["status"] == "invalid_numeric"
    json.dumps(raw,allow_nan=False)


def test_mapping_revisions_and_paddocks_remain_stable():
    paddocks = paddocks_from_names("Summer\nWinter\nBack",DAY)
    c = config(paddocks=paddocks,weather_entities=["weather.met"])
    before = deepcopy(c["paddocks"])
    c = config(**{**c,"sources":[source()]})
    assert c["paddocks"] == before
    assert source_key(source()) != source_key(source(offset=1))
    defaults = sources_for(c)
    assert len(defaults) == 4
    assert all(s["kind"] == "weather_proxy" for s in defaults[1:])
    with pytest.raises(ValueError):
        validate_source(source(variable="solar_energy"))


def test_forecast_issued_before_target_and_no_daily_mean_fabrication():
    rows = [{"datetime":(A+timedelta(hours=h)).isoformat(),"temperature":68,"cloud_coverage":20} for h in range(4)]
    records = forecast_records("weather.met",rows,{"temperature_unit":"°F"},A+timedelta(minutes=1))
    assert len(records) == 4  # two future intervals, temperature and cloud.
    assert all(r["quality"] == "forecast_proxy" and r["start"] > A.isoformat() for r in records)
    daily = [rows[0],{**rows[1],"datetime":(A+timedelta(days=1)).isoformat()}]
    assert not forecast_records("weather.met",daily,{"temperature_unit":"°F"},A)


def test_schedule_timezone_dst_and_selected_clock():
    now = datetime(2026,3,8,5,tzinfo=timezone.utc)
    assert next_run(now,"America/Toronto","02:30:00") == datetime(2026,3,8,7,30,tzinfo=timezone.utc)
    now = datetime(2026,11,1,4,tzinfo=timezone.utc)
    first = next_run(now,"America/Toronto","01:30:00")
    assert first == datetime(2026,11,1,5,30,tzinfo=timezone.utc)
    assert next_run(first+timedelta(minutes=1),"America/Toronto","01:30:00").date() == date(2026,11,2)
    assert scheduled_day(A+timedelta(minutes=5),"America/Toronto","00:15:00") == date(2026,5,30)
    assert scheduled_day(A+timedelta(minutes=16),"America/Toronto","00:15:00") == date(2026,5,31)


@pytest.fixture
def ha_contract(monkeypatch):
    modules = ["homeassistant","homeassistant.components","homeassistant.components.weather","homeassistant.core",
               "homeassistant.helpers","homeassistant.helpers.event","homeassistant.helpers.update_coordinator",
               "homeassistant.components.sensor","homeassistant.const","homeassistant.config_entries","homeassistant.helpers.selector"]
    for name in modules:
        monkeypatch.setitem(sys.modules,name,ModuleType(name))
    sys.modules["homeassistant.components.weather"].WeatherEntityFeature = SimpleNamespace(FORECAST_HOURLY=2)
    sys.modules["homeassistant.core"].callback = lambda f:f
    for name in ("async_track_state_change_event","async_track_state_report_event","async_track_point_in_utc_time","async_track_time_interval"):
        setattr(sys.modules["homeassistant.helpers.event"],name,lambda *args:lambda:None)
    class Coordinator:
        def __init__(self,hass,*args,**kwargs):
            self.hass,self.data = hass,None
            self.last_update_success = True
        def async_set_updated_data(self,data):
            self.data = data
        async def async_refresh(self):
            self.data = await self._async_update_data()
    class Entity:
        def __init__(self,coordinator):
            self.coordinator = coordinator
    class Description:
        def __init__(self,**kwargs):
            vars(self).update(kwargs)
    # Dataclass subclass requires real dataclass base for inherited description keys.
    from dataclasses import make_dataclass
    Description = make_dataclass("Description",[("key",str),("translation_key",str),("native_unit_of_measurement",str,None),
                     ("device_class",str,None),("entity_category",str,None)],frozen=True,kw_only=True)
    update = sys.modules["homeassistant.helpers.update_coordinator"]
    update.DataUpdateCoordinator,update.CoordinatorEntity = Coordinator,Entity
    sensor = sys.modules["homeassistant.components.sensor"]
    sensor.SensorEntity,sensor.SensorEntityDescription = type("SensorEntity",(),{}),Description
    sensor.SensorDeviceClass = SimpleNamespace(TEMPERATURE="temperature",HUMIDITY="humidity",DATE="date")
    sys.modules["homeassistant.const"].EntityCategory = SimpleNamespace(DIAGNOSTIC="diagnostic")
    class Flow:
        def __init_subclass__(cls,**kwargs):
            pass
        def async_show_form(self,**kwargs):
            return {"type":"form",**kwargs}
        def async_show_menu(self,**kwargs):
            return {"type":"menu",**kwargs}
        def async_create_entry(self,**kwargs):
            return {"type":"create_entry",**kwargs}
        def add_suggested_values_to_schema(self,schema,values):
            return schema
        def _get_reconfigure_entry(self):
            return self.config_entry
        def async_update_reload_and_abort(self,entry,data_updates):
            entry.data.update(data_updates)
            return {"type":"abort","reason":"reconfigure_successful"}
    sys.modules["homeassistant.config_entries"].ConfigFlow = Flow
    sys.modules["homeassistant.config_entries"].OptionsFlowWithReload = Flow
    class Selector:
        def __init__(self,*args,**kwargs):
            pass
        def __call__(self,value):
            return value
    for name in ("NumberSelector","NumberSelectorConfig","TextSelector","TextSelectorConfig","EntitySelector","EntitySelectorConfig",
                 "SelectSelector","SelectSelectorConfig","TimeSelector","BooleanSelector","DateSelector"):
        setattr(sys.modules["homeassistant.helpers.selector"],name,Selector)
    sys.modules["homeassistant.helpers"].selector = sys.modules["homeassistant.helpers.selector"]
    for platform,cls in (("switch","SwitchEntity"),("number","NumberEntity"),("text","TextEntity"),("button","ButtonEntity")):
        name = f"homeassistant.components.{platform}"
        monkeypatch.setitem(sys.modules,name,ModuleType(name))
        setattr(sys.modules[name],cls,type(cls,(),{}))
    sys.modules["homeassistant.components.number"].NumberMode = SimpleNamespace(BOX="box")
    sys.modules["homeassistant.const"].EntityCategory.CONFIG = "config"
    notification = ModuleType("homeassistant.components.persistent_notification")
    notification.async_create = lambda *args,**kwargs:None
    monkeypatch.setitem(sys.modules,notification.__name__,notification)
    sys.modules["homeassistant.components"].persistent_notification = notification
    yield
    for name in ("custom_components.pasture_wsc.coordinator","custom_components.pasture_wsc.sensor","custom_components.pasture_wsc.config_flow",
                 "custom_components.pasture_wsc.entity","custom_components.pasture_wsc.switch","custom_components.pasture_wsc.number",
                 "custom_components.pasture_wsc.text","custom_components.pasture_wsc.button"):
        sys.modules.pop(name,None)


def test_config_flow_options_and_reconfigure_preserve_identity(ha_contract):
    from custom_components.pasture_wsc.config_flow import PastureWSCConfigFlow,PastureWSCOptionsFlow
    async def run():
        hass = SimpleNamespace(config=SimpleNamespace(latitude=43.7,longitude=-79.4,elevation=100,time_zone="America/Toronto"),
            config_entries=SimpleNamespace(async_update_entry=lambda e,options:setattr(e,"options",options)))
        flow = PastureWSCConfigFlow()
        flow.hass = hass
        assert (await flow.async_step_user())["step_id"] == "user"
        location = {k:config()[k] for k in ("latitude","longitude","elevation","timezone")}
        assert (await flow.async_step_user(location))["step_id"] == "weather"
        assert (await flow.async_step_weather({"weather_entities":["weather.met"]}))["step_id"] == "paddocks"
        assert (await flow.async_step_paddocks({"names":"Summer\nWinter\nBack"}))["type"] == "menu"
        assert (await flow.async_step_add_source())["step_id"] == "source"
        assert (await flow.async_step_source({k:v for k,v in source().items() if k!="id"}))["type"] == "menu"
        result = await flow.async_step_finish()
        entry = SimpleNamespace(data=result["data"],options={})
        saved_paddocks = deepcopy(entry.data["paddocks"])
        options = PastureWSCOptionsFlow()
        options.config_entry = entry
        assert (await options.async_step_init())["step_id"] == "init"
        await options.async_step_init({"allow_estimated":True})
        sid = options._values["sources"][0]["id"]
        await options.async_step_edit_source({"source_id":sid})
        await options.async_step_source({**{k:v for k,v in source().items() if k!="id"},"offset":1})
        result = await options.async_step_finish()
        entry.options = result["data"]
        assert entry.options["sources"][0]["id"] == sid
        assert "paddocks" not in entry.options
        flow.config_entry = entry
        result = await flow.async_step_reconfigure({**location,"timezone":"America/Winnipeg"})
        assert result["reason"] == "reconfigure_successful"
        assert entry.data["paddocks"] == saved_paddocks
        assert entry.data["timezone"] == "America/Winnipeg"
    asyncio.run(run())


def test_coordinator_restart_retry_backfill_and_bounds(ha_contract,monkeypatch):
    import custom_components.pasture_wsc.coordinator as module
    class FixedDatetime(datetime):
        @classmethod
        def now(cls,tz=None):
            return (A+timedelta(days=1,minutes=20)).astimezone(tz) if tz else A+timedelta(days=1,minutes=20)
    monkeypatch.setattr(module,"datetime",FixedDatetime)
    async def run():
        backend = MemoryStore()
        monkeypatch.setattr(module,"PastureStore",lambda hass,entry_id:PastureStore(hass,entry_id,backend))
        async def executor(fn,*args):
            return fn(*args)
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity:None),async_add_executor_job=executor)
        entry = SimpleNamespace(entry_id="entry")
        coordinator = module.PastureCoordinator(hass,entry,config(sources=[source()]))
        await coordinator.async_start()
        assert coordinator.data["day"] == "2026-06-01"
        assert not coordinator.data["weather_complete"]
        first_versions = sum(len(v) for v in coordinator.store.data["daily"].values())
        await coordinator.async_refresh()
        assert sum(len(v) for v in coordinator.store.data["daily"].values()) == first_versions
        await coordinator.async_close()
        restarted = module.PastureCoordinator(hass,entry,config(sources=[source()]))
        await restarted.async_start()
        assert restarted.store.data["daily"] == coordinator.store.data["daily"]
        # Complete historical readings can be backfilled without a second accumulator.
        for h in range(24):
            when = A+timedelta(hours=h)
            state = SimpleNamespace(state="20",last_reported=when,attributes={"unit_of_measurement":"°C"})
            restarted.store.observation(capture(source(),state,when))
        await restarted.async_recalculate(DAY,DAY)
        assert restarted.data["weather"]["temperature"]["value"] == 20
        assert not restarted.data["complete"]
        with pytest.raises(ValueError):
            await restarted.async_recalculate(DAY,DAY+timedelta(days=31))
        with pytest.raises(ValueError):
            await restarted.async_recalculate(DAY,DAY+timedelta(days=1))
        await restarted.async_close()
    asyncio.run(run())


def test_daily_strict_missing_soil_and_station_failover(ha_contract):
    from custom_components.pasture_wsc.coordinator import daily_record
    station = source()
    second = source(id="secondary",entity_id="sensor.second",priority=1)
    solar = source(id="solar",entity_id="sensor.sun",variable="irradiance",freshness=3600)
    raw = []
    for h in range(24):
        when = A+timedelta(hours=h)
        for s,value in ((station,"10"),(second,"20"),(solar,"100")):
            state = SimpleNamespace(state=value,last_reported=when,attributes={"unit_of_measurement":"W/m²" if s==solar else "°C"})
            if s==station and 12 <= h < 18:
                state.state = "unavailable"
            raw.append(capture(s,state,when))
    c = config(sources=[station,second,solar])
    data = {"observations":raw,"forecasts":{}}
    record = daily_record(DAY,c,data)
    assert record["weather"]["temperature"]["value"] == 12.5
    assert record["weather"]["temperature"]["fallback_proportion"] == .25
    assert record["weather"]["solar_energy"]["value"] == pytest.approx(8.64)
    assert record["weather_complete"] and not record["complete"]
    assert record["moisture_factor"] is record["development"] is None
    assert daily_record(DAY,c,data) == record


def test_cloud_scenario_night_missing_and_labels(ha_contract):
    from custom_components.pasture_wsc.coordinator import daily_record
    data = {"observations":[],"forecasts":{}}
    c = config(estimate_solar=True)
    result = daily_record(DAY,c,data)
    assert result["weather"]["solar_energy"]["value"] is None
    assert all(i["value"] == 0 for i in result["weather"]["solar_energy"]["intervals"])
    c = config(estimate_solar=True,assume_clear_sky=True)
    result = daily_record(DAY,c,data)
    assert result["weather"]["solar_energy"]["value"] > 0
    assert "assumed" in result["weather"]["solar_energy"]["flags"]
    assert not result["weather_complete"]


def test_sensor_bounded_attributes_and_pending_availability(ha_contract):
    from custom_components.pasture_wsc.sensor import PastureSensor,SENSORS
    coordinator = SimpleNamespace(entry=SimpleNamespace(entry_id="entry"),data={"day":"2026-06-01","weather":{"temperature":{
        "value":None,"coverage":.2,"fallback_proportion":0,"flags":["insufficient_coverage"],"intervals":[],"missing":[1]*100}}})
    entity = PastureSensor(coordinator,next(d for d in SENSORS if d.key=="temperature"))
    assert entity.native_value is None
    assert entity.extra_state_attributes["missing_interval_count"] == 100
    assert "missing" not in entity.extra_state_attributes
    assert entity._attr_unique_id == "entry_temperature"


def test_diagnostics_redact_entities_coordinates_names():
    from custom_components.pasture_wsc.diagnostics import async_get_config_entry_diagnostics
    coordinator = SimpleNamespace(data={"day":"2026-06-01","weather":{},"collector_issues":{"weather.private":"Outage"}},sources=[source()],
        config=config(paddocks=[{"id":"secret","name":"Private field","start_date":"2026-06-01"}]),
        store=SimpleNamespace(data={"observations":[],"daily":{}}))
    result = asyncio.run(async_get_config_entry_diagnostics(None,SimpleNamespace(runtime_data=coordinator)))
    text = json.dumps(result)
    assert "private" not in text.lower() and "secret" not in text and "latitude" not in text and "entity_id" not in text


def test_bundle_and_translations():
    root = Path(__file__).resolve().parents[1]
    for original in (root/"pasture_wsc").glob("*.py"):
        assert original.read_bytes() == (root/"custom_components/pasture_wsc/engine"/original.name).read_bytes()
    assert json.loads((root/"custom_components/pasture_wsc/strings.json").read_text(encoding="utf-8")) == json.loads((root/"custom_components/pasture_wsc/translations/en.json").read_text(encoding="utf-8"))


def test_paddock_platforms_group_by_stable_device_and_request_only(ha_contract):
    from unittest.mock import AsyncMock
    from custom_components.pasture_wsc.paddocks import initialize_paddocks
    from custom_components.pasture_wsc import sensor, switch, number, text, button
    data = {}
    initialize_paddocks(data,paddocks_from_names("Summer\nWinter",DAY),"America/Toronto")
    coordinator = SimpleNamespace(entry=SimpleNamespace(entry_id="entry"),store=SimpleNamespace(data=data),
        data={"paddocks":{}},last_update_success=True,async_request_cycle=AsyncMock())
    entry = SimpleNamespace(runtime_data=coordinator)
    entities = []
    async def run():
        for platform in (sensor,switch,number,text,button):
            await platform.async_setup_entry(None,entry,lambda new:entities.extend(new))
    asyncio.run(run())
    paddock_entities = [e for e in entities if hasattr(e,"pid")]
    assert len(paddock_entities) == 2*(len(sensor.PADDOCK_SENSORS)+5)
    assert len({e._attr_unique_id for e in entities}) == len(entities)
    for e in paddock_entities:
        assert e._attr_device_info["identifiers"] == {("pasture_wsc",f"entry_{e.pid}")}
        assert e._attr_device_info["via_device"] == ("pasture_wsc","entry")
    before = deepcopy(data)
    b = next(e for e in paddock_entities if isinstance(e,button.NewCycleButton))
    asyncio.run(b.async_press())
    coordinator.async_request_cycle.assert_awaited_once_with(b.pid)
    assert data == before
    assert all(not e.available for e in paddock_entities if isinstance(e,number.AssumedMoistureNumber))
