import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from custom_components.pasture_wsc.backfill import recorder_intervals, history_bounds
from custom_components.pasture_wsc.engine.astronomy import local_day_bounds
from custom_components.pasture_wsc.paddocks import calculate_paddock
from custom_components.pasture_wsc.storage import PastureStore
from custom_components.pasture_wsc.weather import capture
from tests.test_ha_phase2 import ha_contract, config, source, MemoryStore
from tests.test_paddocks import state


DAY = date(2026,6,1)
A,B = local_day_bounds(DAY,'America/Toronto')


def local_rows(a=A,b=B,cfg=None):
    cfg = cfg or config()
    cfg = {**cfg,'sources':[source(),source(id='sun',entity_id='sensor.sun',variable='irradiance')]}
    states = {'sensor.station':[], 'sensor.sun':[]}
    for h in range(int((b-a).total_seconds()/3600)):
        t=a+timedelta(hours=h)
        states['sensor.station'].append(SimpleNamespace(state='10',last_updated=t,attributes={'unit_of_measurement':'°C'}))
        states['sensor.sun'].append(SimpleNamespace(state='100',last_updated=t,attributes={'unit_of_measurement':'W/m²'}))
    return recorder_intervals(states,cfg,a,b)


@pytest.mark.parametrize('day,hours',[(date(2026,3,8),23),(date(2026,11,1),25)])
def test_local_history_preserves_dst(day,hours):
    a,b = local_day_bounds(day,'America/Toronto')
    rows = local_rows(a,b)
    solar=[r for r in rows if r['variable']=='solar_energy']
    assert len(solar)==hours
    assert sum(r['value'] for r in solar)==pytest.approx(hours*.36)


def test_history_range_validation():
    now=datetime(2026,6,10,12,tzinfo=timezone.utc)
    assert history_bounds(DAY,DAY,config(),now)==(A,B)
    for start,end in [(date(2026,6,10),date(2026,6,10)),(date(2026,6,9),DAY),(date(2025,1,1),date(2026,6,9))]:
        with pytest.raises(ValueError):
            history_bounds(start,end,config(),now)


def test_weather_attributes_and_outages_are_retained():
    cfg=config(weather_entities=['weather.ranch'])
    rows=[]
    for h in range(24):
        rows.append(SimpleNamespace(state='unavailable' if h==5 else 'cloudy',last_updated=A+timedelta(hours=h),
            attributes={'temperature':12+h/10,'temperature_unit':'°C','cloud_coverage':80,'humidity':70}))
    intervals=recorder_intervals({'weather.ranch':rows},cfg,A,B)
    temperatures=[r for r in intervals if r['variable']=='temperature']
    assert all(r['quality']=='estimated' for r in temperatures)
    assert not any(datetime.fromisoformat(r['start'])<=A+timedelta(hours=5)<datetime.fromisoformat(r['end']) for r in temperatures)
    assert any(r['variable']=='cloud_cover' for r in intervals)
    with pytest.raises(ValueError,match='No usable local history'):
        recorder_intervals({},cfg,A,B)


def test_history_fills_partial_startup_day_preserves_local_values_and_scenario(ha_contract):
    from custom_components.pasture_wsc.coordinator import daily_record
    settings = config(historical_backfill=True)
    history = local_rows(A,B,settings)
    data = {'observations':[],'forecasts':{},'historical_weather':{
        f"{r['source']}|{r['start']}":{'interval':r,'location':{k:settings[k] for k in ('latitude','longitude','elevation')}} for r in history}}
    for h in range(12,24):
        when = A+timedelta(hours=h)
        reading = SimpleNamespace(state='20',last_reported=when,attributes={'unit_of_measurement':'°C'})
        data['observations'].append(capture(source(),reading,when))
    result = daily_record(DAY,settings,data)
    assert result['weather']['temperature']['coverage']==1
    assert result['weather']['temperature']['value']==pytest.approx(15)
    assert result['weather']['solar_energy']['value']==pytest.approx(8.64)
    paddock = state(scenario_enabled=True,moisture_mode='one_minus_wi_over_reference')
    output = calculate_paddock(paddock,DAY,{DAY:result},[],settings)['latest']
    assert output['scenario_status']=='scenario_available'
    assert output['primary']['experimental_wsc'] is None
    assert output['scenario']['experimental_wsc'] is not None
    disabled = daily_record(DAY,{**settings,'historical_backfill':False},data)
    assert disabled['weather']['temperature']['value'] is None
    moved = daily_record(DAY,{**settings,'latitude':44},data)
    assert moved['weather']['temperature']['value'] is None


def test_download_failure_preserves_cycle_and_archive_and_old_store_migrates(ha_contract,monkeypatch):
    import custom_components.pasture_wsc.coordinator as module
    async def run():
        backend = MemoryStore()
        monkeypatch.setattr(module,'PastureStore',lambda hass,entry_id:PastureStore(hass,entry_id,backend))
        async def executor(fn,*args):
            return fn(*args)
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity:None),async_add_executor_job=executor)
        coordinator = module.PastureCoordinator(hass,SimpleNamespace(entry_id='test'),config(paddocks=[state()['settings']]))
        await coordinator.async_start()
        before = deepcopy(coordinator.store.data)
        calls = []
        async def fail(*args):
            calls.append(args)
            raise ValueError('download failed')
        monkeypatch.setattr(module,'fetch_history',fail)
        pid = 'summer'
        cycle_id = before['paddocks'][pid]['cycle']['id']
        with pytest.raises(ValueError):
            await coordinator.async_start_cycle(pid,DAY,cycle_id,confirmed=False,backfill=True)
        assert not calls
        with pytest.raises(ValueError,match='download failed'):
            await coordinator.async_start_cycle(pid,DAY,cycle_id,confirmed=True,backfill=True)
        assert len(calls)==1
        assert coordinator.store.data==before
        await coordinator.async_close()
        backend.data.pop('historical_weather')
        restarted = PastureStore(None,'test',backend)
        await restarted.load()
        assert restarted.data['historical_weather']=={}
        assert restarted.data['daily']==before['daily']
    asyncio.run(run())


def test_automatic_backfill_replays_old_days_and_survives_restart(ha_contract,monkeypatch):
    import custom_components.pasture_wsc.coordinator as module
    class FixedDatetime(datetime):
        @classmethod
        def now(cls,tz=None):
            return (A+timedelta(days=12,minutes=20)).astimezone(tz)
    monkeypatch.setattr(module,'datetime',FixedDatetime)
    async def run():
        backend = MemoryStore()
        monkeypatch.setattr(module,'PastureStore',lambda hass,entry_id:PastureStore(hass,entry_id,backend))
        async def executor(fn,*args):
            return fn(*args)
        calls = []
        async def fetch(hass,start,end,cfg):
            calls.append((start,end))
            a,_ = local_day_bounds(start,cfg['timezone'])
            _,b = local_day_bounds(end,cfg['timezone'])
            return local_rows(a,b,cfg)
        monkeypatch.setattr(module,'fetch_history',fetch)
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity:None),async_add_executor_job=executor)
        cfg = config(historical_backfill=True,paddocks=[state(scenario_enabled=True,
            moisture_mode='one_minus_wi_over_reference')['settings']])
        entry = SimpleNamespace(entry_id='test')
        coordinator = module.PastureCoordinator(hass,entry,cfg)
        await coordinator.async_start()
        assert calls==[(DAY,DAY+timedelta(days=11))]
        assert coordinator.data['paddocks']['summer']['scenario_status']=='scenario_available'
        assert any(rows[-1]['day']==DAY.isoformat() for rows in coordinator.store.data['daily'].values())
        await coordinator.async_refresh()
        assert len(calls)==1
        saved = deepcopy(coordinator.store.data)
        await coordinator.async_close()
        restarted = module.PastureCoordinator(hass,entry,cfg)
        await restarted.async_start()
        assert len(calls)==1  # Full retained coverage needs no network request.
        assert restarted.data['paddocks']['summer']['scenario']==coordinator.data['paddocks']['summer']['scenario']
        assert restarted.store.data['historical_weather']==saved['historical_weather']
        await restarted.async_close()
    asyncio.run(run())


def test_setup_date_selection_and_future_date_rejection(ha_contract):
    from custom_components.pasture_wsc.config_flow import PastureWSCConfigFlow
    async def run():
        flow = PastureWSCConfigFlow()
        flow._values = config()
        today = datetime.now(ZoneInfo('America/Toronto')).date()
        chosen = today-timedelta(days=21)
        result = await flow.async_step_paddocks({'names':'One\nTwo','start_date':chosen.isoformat()})
        assert result['type']=='menu'
        assert all(p['start_date']==chosen.isoformat() for p in flow._values['paddocks'])
        before = deepcopy(flow._values['paddocks'])
        result = await flow.async_step_paddocks({'names':'One','start_date':(today+timedelta(days=1)).isoformat()})
        assert result['errors']=={'base':'invalid_paddocks'}
        assert flow._values['paddocks']==before
    asyncio.run(run())


def test_backfill_form_exposes_failure_and_retains_dates(ha_contract,caplog):
    from custom_components.pasture_wsc.config_flow import PastureWSCOptionsFlow
    async def run():
        async def fail(start,end):
            raise ValueError('No usable local history')
        coordinator = SimpleNamespace(store=SimpleNamespace(data={'paddocks':{}}),async_backfill=fail)
        flow = PastureWSCOptionsFlow()
        flow._values = config()
        flow._coordinator = lambda:coordinator
        values = {'start_date':'2026-10-10','end_date':'2026-10-10'}
        result = await flow.async_step_backfill(values)
        assert result['errors']=={'base':'backfill_failed'}
        assert 'No usable local history' in result['description_placeholders']['error_detail']
        assert result['data_schema']({})==values
        assert 'No usable local history' in caplog.text
    asyncio.run(run())


def test_recorder_executor_reads_attribute_changes_and_clouds_support_solar(ha_contract,monkeypatch):
    import sys
    from types import ModuleType
    from custom_components.pasture_wsc.backfill import fetch_history
    from custom_components.pasture_wsc.coordinator import daily_record
    called=[]
    states={'weather.ranch':[SimpleNamespace(state='cloudy',last_updated=A+timedelta(hours=h),
        attributes={'temperature':12,'temperature_unit':'°C','cloud_coverage':70,'humidity':80}) for h in range(24)]}
    def query(hass,a,b,**kwargs):
        called.append((a,b,kwargs))
        assert kwargs['significant_changes_only'] is False
        assert kwargs['include_start_time_state'] is False
        assert kwargs['no_attributes'] is False
        assert kwargs['entity_ids']==['weather.ranch']
        return states
    history=ModuleType('homeassistant.components.recorder.history')
    history.get_significant_states=query
    helper=ModuleType('homeassistant.helpers.recorder')
    async def executor(fn):
        return fn()
    helper.get_instance=lambda hass:SimpleNamespace(async_add_executor_job=executor)
    monkeypatch.setitem(sys.modules,history.__name__,history)
    monkeypatch.setitem(sys.modules,helper.__name__,helper)
    async def run():
        cfg=config(weather_entities=['weather.ranch'],historical_backfill=True,estimate_solar=True)
        records=await fetch_history(None,DAY,DAY,cfg)
        assert len(called)==1
        assert called[0][0]<A and called[0][1]>B
        assert all(r['source'].startswith('recorder:') for r in records)
        data={'observations':[],'forecasts':{},'historical_weather':{f"{r['source']}|{r['start']}":{
            'interval':r,'location':{k:cfg[k] for k in ('latitude','longitude','elevation')}} for r in records}}
        result=daily_record(DAY,cfg,data)
        assert result['weather']['temperature']['coverage']==1
        assert result['weather']['temperature']['value']==12
        assert result['weather']['solar_energy']['coverage']==1
        assert result['weather']['solar_energy']['value']>0
        assert 'explicit_clear_sky_assumption' not in result['weather']['solar_energy']['flags']
    asyncio.run(run())


def test_cycle_date_change_publishes_full_replay_even_when_refresh_is_debounced(ha_contract,monkeypatch):
    import custom_components.pasture_wsc.coordinator as module
    class FixedDatetime(datetime):
        @classmethod
        def now(cls,tz=None):
            return (A+timedelta(days=12,minutes=20)).astimezone(tz)
    monkeypatch.setattr(module,'datetime',FixedDatetime)
    async def run():
        backend=MemoryStore()
        monkeypatch.setattr(module,'PastureStore',lambda hass,entry_id:PastureStore(hass,entry_id,backend))
        async def executor(fn,*args):
            return fn(*args)
        async def fetch(hass,start,end,cfg):
            a,_=local_day_bounds(start,cfg['timezone'])
            _,b=local_day_bounds(end,cfg['timezone'])
            return local_rows(a,b,cfg)
        monkeypatch.setattr(module,'fetch_history',fetch)
        hass=SimpleNamespace(states=SimpleNamespace(get=lambda entity:None),async_add_executor_job=executor,
            config_entries=SimpleNamespace(async_update_entry=lambda entry,options:setattr(entry,'options',options)))
        end=DAY+timedelta(days=11)
        cfg=config(historical_backfill=True,paddocks=[state(start_date=end.isoformat(),scenario_enabled=True,
            moisture_mode='one_minus_wi_over_reference')['settings']])
        coordinator=module.PastureCoordinator(hass,SimpleNamespace(entry_id='test',options={}),cfg)
        await coordinator.async_start()
        old=deepcopy(coordinator.data['paddocks']['summer'])
        async def debounced():
            pass
        coordinator.async_refresh=debounced
        await coordinator.async_start_cycle('summer',DAY,old['cycle']['id'],confirmed=True,backfill=True)
        new=coordinator.data['paddocks']['summer']
        assert new['cycle']['start_date']==DAY.isoformat()
        assert new['calculated_cycle_start']==DAY.isoformat()
        assert new['scenario_days']==new['scenario_valid_development_days']==12
        assert new['scenario_missing_development_days']==[]
        # Photoperiod changes each day, so the total is not exactly 12 copies
        # of the final day's increment. It must include substantially more history.
        assert new['scenario']['spechr']>old['scenario']['spechr']*10
        assert new['scenario']['experimental_wsc']!=old['scenario']['experimental_wsc']
        await coordinator.async_close()
    asyncio.run(run())
