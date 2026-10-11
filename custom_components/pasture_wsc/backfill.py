"""Backfill from Home Assistant recorder only; no external weather requests."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from .engine.astronomy import local_day_bounds
from .weather import build_intervals, capture, serializable, sources_for

MAX_HISTORY_DAYS = 366


def location(config):
    return {k:config[k] for k in ('latitude','longitude','elevation')}


def history_bounds(start,end,config,now):
    today = now.astimezone(ZoneInfo(config['timezone'])).date()
    if end < start or end >= today or (end-start).days >= MAX_HISTORY_DAYS:
        raise ValueError('Select 1–366 completed local dates')
    a,_ = local_day_bounds(start,config['timezone'])
    _,b = local_day_bounds(end,config['timezone'])
    return a,b


def recorder_intervals(states,config,start,end):
    """Keep real update times, attributes, outages, units and freshness limits."""
    raw = []
    for source in sources_for(config):
        for state in states.get(source['entity_id'],[]):
            when = state.last_updated
            if when is None or when.tzinfo is None:
                continue
            # Recorder does not always retain last_reported. Do not invent it.
            snapshot = SimpleNamespace(state=state.state,attributes=dict(state.attributes),last_reported=when)
            raw.append(capture(source,snapshot,when))
    intervals,_,_ = build_intervals(raw,{**config,'allow_estimated':True})
    result = []
    for interval in intervals:
        a,b = max(start,interval.start),min(end,interval.end)
        if a >= b:
            continue
        # Preserve stable original interval bounds across overlapping imports.
        # The daily resolver clips and apportions totals at local-day boundaries.
        result.append(serializable(replace(interval,
            source=f'recorder:{interval.source}',flags=interval.flags+('local_recorder_backfill',))))
    if not result:
        raise ValueError('No usable local history for the configured weather entities or sensors. '
                         'Check recorder retention, excluded entities and source mappings.')
    return result


def _read_history(hass,start,end,config,now):
    from homeassistant.components.recorder.history import get_significant_states
    sources = sources_for(config)
    entities = sorted({s['entity_id'] for s in sources})
    if not entities:
        raise ValueError('Select a weather provider or sensor source before backfilling')
    margin = timedelta(seconds=max(s['freshness'] for s in sources))
    # Real baseline updates preserve freshness; synthetic start states do not.
    states = get_significant_states(hass,start-margin-timedelta(microseconds=1),min(end+margin,now),
        entity_ids=entities,include_start_time_state=False,significant_changes_only=False,
        minimal_response=False,no_attributes=False)
    return recorder_intervals(states,config,start,end)


async def fetch_history(hass,start,end,config):
    now = datetime.now(timezone.utc)
    a,b = history_bounds(start,end,config,now)
    try:
        from homeassistant.helpers.recorder import get_instance
    except ImportError:
        from homeassistant.components.recorder import get_instance
    try:
        recorder = get_instance(hass)
        # Database access and lazy-state materialization stay on recorder's executor.
        return await recorder.async_add_executor_job(partial(_read_history,hass,a,b,config,now))
    except ValueError:
        raise
    except Exception as error:
        raise ValueError('Home Assistant recorder history could not be read. '
                         'Ensure recorder is enabled; see the logs for details.') from error
