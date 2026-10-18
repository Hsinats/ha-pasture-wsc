"""Live rain totals, separated by measured and estimated provenance."""
from dataclasses import replace
from datetime import date, datetime, timedelta

from .engine.astronomy import local_day_bounds
from .engine.weather import Quality, SourcePolicy, Variable, resolve_day
from .weather import build_intervals, decode_interval


def live_rain(data, config, cycle, now):
    start = date.fromisoformat(cycle["start_date"])
    zone = cycle["timezone"]
    from zoneinfo import ZoneInfo
    today = now.astimezone(ZoneInfo(zone)).date()
    first, _ = local_day_bounds(start,zone)
    base = {"start_date":start.isoformat(),"through":now.isoformat(),
            "includes_today":True,"missing_data_is_not_zero_rain":True}
    if today < start or (today-start).days > 3660:
        return {route:{**base,"value":0.0,"coverage":0.0,"complete":False}
                for route in ("measured","estimated")}
    # Do not attach weather from a different location to an archived cycle.
    current_location = {k:config[k] for k in ("latitude","longitude","elevation")}
    compatible = zone == config["timezone"] and cycle.get("location") in (None,current_location)
    intervals, policies, _ = build_intervals(data.get("observations",[]) if compatible else [],config)
    intervals = [i for i in intervals if i.variable == Variable.PRECIPITATION]
    rain_policies = list(policies[Variable.PRECIPITATION])
    if config.get("historical_backfill"):
        for item in data.get("historical_weather",{}).values():
            if item["location"] != (cycle.get("location") or current_location):
                continue
            interval = decode_interval(item["interval"])
            if interval.variable == Variable.PRECIPITATION:
                intervals.append(interval)
                if not any(p.source == interval.source for p in rain_policies):
                    rain_policies.append(SourcePolicy(interval.source,1100,86400,
                        frozenset({Quality.OBSERVED,Quality.PROVIDER,Quality.ESTIMATED})))
    if compatible and config.get("allow_forecast"):
        for item in data.get("forecasts",{}).values():
            if item["variable"] != "precipitation":
                continue
            interval = decode_interval(item)
            intervals.append(interval)
            if not any(p.source == interval.source for p in rain_policies):
                entity = interval.source[len("forecast:"):].rsplit(":",1)[0]
                rank = config["weather_entities"].index(entity) if entity in config["weather_entities"] else 1000
                rain_policies.append(SourcePolicy(interval.source,1500+rank,86400,frozenset({Quality.FORECAST})))
    # Clip totals proportionally to now; never include an hour's future portion.
    clipped = []
    for interval in intervals:
        if interval.start >= now or interval.end <= first:
            continue
        stop = min(interval.end,now)
        if stop < interval.end:
            interval = replace(interval,end=stop,
                value=interval.value*(stop-interval.start).total_seconds()/(interval.end-interval.start).total_seconds(),
                flags=(*interval.flags,"uniform_elapsed_interval_estimate"))
        clipped.append(interval)
    result = {}
    for route,qualities in (("measured",{Quality.OBSERVED,Quality.PROVIDER}),
                            ("estimated",{Quality.ESTIMATED,Quality.FORECAST,Quality.ASSUMED})):
        selected_policies = [replace(p,enabled_qualities=frozenset(p.enabled_qualities & qualities)) for p in rain_policies]
        candidates = [i for i in clipped if i.quality in qualities]
        total = covered = 0.0
        sources,flags = set(),set()
        for offset in range((today-start).days+1):
            day = start+timedelta(days=offset)
            summary = resolve_day(day,zone,Variable.PRECIPITATION,candidates,selected_policies)
            total += summary.partial_value or 0.0
            covered += sum((i.end-i.start).total_seconds() for i in summary.intervals)
            sources.update(i.source for i in summary.intervals)
            flags.update(flag for i in summary.intervals for flag in i.flags)
        elapsed = max(0,(now-first).total_seconds())
        result[route] = {**base,"value":total,"coverage":covered/elapsed if elapsed else 0.0,
                        "complete":elapsed > 0 and covered >= elapsed,
                        "covered_hours":covered/3600,"missing_hours":max(0,elapsed-covered)/3600,
                        "sources":sorted(sources),"flags":sorted(flags),
                        "basis":"forecast_amounts_uniformly_distributed" if route == "estimated" else "measured_intervals"}
    return result
