"""Immutable per-variable interval resolver; no provider or HA dependency.

Intervals are half-open UTC. Values are interval means or interval totals,
never current snapshots retroactively applied to historical dates.
"""
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from hashlib import sha256
import json
from math import isfinite
from typing import Iterable

from . import INPUT_VERSION
from .astronomy import local_day_bounds


class Quality(StrEnum):
    OBSERVED = "observed"
    PROVIDER = "provider"
    ESTIMATED = "estimated"
    FORECAST = "forecast_proxy"
    ASSUMED = "assumed"


class Variable(StrEnum):
    TEMPERATURE = "temperature"
    IRRADIANCE = "irradiance"
    SOLAR_ENERGY = "solar_energy"
    PRECIPITATION = "precipitation"
    HUMIDITY = "humidity"
    CLOUD = "cloud_cover"


UNITS = {Variable.TEMPERATURE: "°C", Variable.IRRADIANCE: "W/m²",
         Variable.SOLAR_ENERGY: "MJ/m²", Variable.PRECIPITATION: "mm",
         Variable.HUMIDITY: "%", Variable.CLOUD: "%"}
LIMITS = {Variable.TEMPERATURE: (-90, 65), Variable.IRRADIANCE: (0, 1500),
          Variable.SOLAR_ENERGY: (0, 100), Variable.PRECIPITATION: (0, 2000),
          Variable.HUMIDITY: (0, 100), Variable.CLOUD: (0, 100)}
TOTALS = {Variable.SOLAR_ENERGY, Variable.PRECIPITATION}


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps required")
    return value.astimezone(timezone.utc)


def normalize(variable: Variable, value: float, unit: str, offset: float = 0) -> float:
    if not isfinite(value) or not isfinite(offset):
        raise ValueError("invalid_numeric")
    if variable == Variable.TEMPERATURE:
        if unit in ("°F", "F"):
            value = (value - 32) * 5 / 9
        elif unit == "K":
            value -= 273.15
        elif unit not in ("°C", "C"):
            raise ValueError("ambiguous_unit")
    elif variable == Variable.SOLAR_ENERGY:
        factors = {"MJ/m²": 1, "Wh/m²": .0036, "kWh/m²": 3.6, "J/cm²": .01}
        if unit not in factors:
            raise ValueError("ambiguous_unit")
        value *= factors[unit]
    elif variable == Variable.PRECIPITATION and unit == "in":
        value *= 25.4
    elif unit != UNITS[variable]:
        raise ValueError("ambiguous_unit")
    value += offset
    low, high = LIMITS[variable]
    if not low <= value <= high:
        raise ValueError("physically_implausible")
    return value


@dataclass(frozen=True)
class Interval:
    variable: Variable
    start: datetime
    end: datetime
    value: float
    source: str
    quality: Quality
    timestamp: datetime
    unit: str
    original_value: float | None = None
    original_unit: str | None = None
    flags: tuple[str, ...] = ()

    def __post_init__(self):
        for field in ("start", "end", "timestamp"):
            object.__setattr__(self, field, utc(getattr(self, field)))
        if self.start >= self.end or not self.source:
            raise ValueError("Positive interval and source required")
        if self.unit != UNITS[self.variable]:
            raise ValueError("Normalize before constructing interval")
        normalize(self.variable, self.value, self.unit)


@dataclass(frozen=True)
class SourcePolicy:
    source: str
    priority: int
    max_age_seconds: float
    enabled_qualities: frozenset[Quality] = frozenset({Quality.OBSERVED, Quality.PROVIDER})

    def __post_init__(self):
        if not isfinite(self.max_age_seconds) or self.max_age_seconds <= 0:
            raise ValueError("Positive freshness required")


@dataclass(frozen=True)
class DailySummary:
    day: date
    variable: Variable
    value: float | None
    partial_value: float | None
    unit: str
    coverage: float
    fallback_proportion: float
    intervals: tuple[Interval, ...]
    missing: tuple[tuple[datetime, datetime], ...]
    flags: tuple[str, ...]
    source_data_hash: str
    input_version: int = INPUT_VERSION


def resolve_day(day: date, zone: str, variable: Variable,
                observations: Iterable[Interval], policies: Iterable[SourcePolicy],
                *, minimum_coverage: float = .8) -> DailySummary:
    if not isfinite(minimum_coverage) or not 0 < minimum_coverage <= 1:
        raise ValueError("Coverage threshold outside (0,1]")
    start, end = local_day_bounds(day, zone)
    policy_list = tuple(policies)
    mapping = {p.source: p for p in policy_list}
    if len(mapping) != len(policy_list):
        raise ValueError("Duplicate source policies")
    raw = tuple(sorted((i for i in observations if i.variable == variable and i.start < end and i.end > start),
                       key=lambda i: (i.source, i.start, i.end, i.timestamp, i.value)))
    # Ambiguous overlapping intervals from a single source must be corrected upstream.
    for source in {i.source for i in raw}:
        group = [i for i in raw if i.source == source]
        if any(a.end > b.start for a, b in zip(group, group[1:])):
            raise ValueError("Overlapping intervals from same source")
    candidates = []
    flags = set()
    points = {start, end}
    for i in raw:
        policy = mapping.get(i.source)
        if policy is None or i.quality not in policy.enabled_qualities:
            flags.add("source_or_quality_disabled")
            continue
        # Provider interval observations may be published after their interval.
        # Forecasts explicitly opted in are valid for their stated future interval.
        expiry = i.end if i.quality == Quality.FORECAST else i.timestamp + timedelta(seconds=policy.max_age_seconds)
        valid_end = min(i.end, expiry)
        if valid_end <= max(start, i.start):
            flags.add("stale")
            continue
        if valid_end < i.end:
            flags.add("stale_tail")
        candidates.append((i, valid_end))
        points.update((max(start, i.start), min(end, valid_end)))
    selected, missing = [], []
    covered = weighted = fallback = 0.0
    best = min((p.priority for p in policy_list), default=0)
    timeline = sorted(points)
    for a, b in zip(timeline, timeline[1:]):
        valid = [i for i, stop in candidates if i.start <= a and stop >= b]
        if not valid:
            missing.append((a, b))
            continue
        chosen = min(valid, key=lambda i: (mapping[i.source].priority, i.source))
        seconds = (b - a).total_seconds()
        value = chosen.value
        interval_flags = chosen.flags
        if variable in TOTALS and (a != chosen.start or b != chosen.end):
            value *= seconds / (chosen.end - chosen.start).total_seconds()
            interval_flags += ("uniform_interval_allocation",)
        selected.append(Interval(variable, a, b, value, chosen.source, chosen.quality,
                                 chosen.timestamp, chosen.unit, chosen.original_value,
                                 chosen.original_unit, interval_flags))
        covered += seconds
        weighted += value if variable in TOTALS else value * seconds
        fallback += seconds if mapping[chosen.source].priority != best else 0
        flags.update(interval_flags)
        if chosen.quality not in (Quality.OBSERVED, Quality.PROVIDER):
            flags.add(chosen.quality.value)
    coverage = covered / (end - start).total_seconds()
    partial = None if covered == 0 else weighted if variable in TOTALS else weighted / covered
    if variable == Variable.IRRADIANCE:
        partial = weighted / 1_000_000 if covered else None
    if coverage < 1:
        flags.add("missing_intervals")
    if coverage < minimum_coverage:
        flags.add("insufficient_coverage")
    payload = {"observations": [asdict(i) for i in raw],
               "policies": [{**asdict(p), "enabled_qualities": sorted(p.enabled_qualities)} for p in policy_list],
               "zone": zone, "day": day.isoformat(), "threshold": minimum_coverage,
               "input_version": INPUT_VERSION}
    digest = sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return DailySummary(day, variable, partial if coverage >= minimum_coverage else None,
                        partial, "MJ/m²" if variable == Variable.IRRADIANCE else UNITS[variable],
                        coverage, fallback / covered if covered else 0, tuple(selected),
                        tuple(missing), tuple(sorted(flags)), digest)


@dataclass(frozen=True)
class Reading:
    timestamp: datetime
    value: float | str | None
    unit: str
    status: str = "valid"


def readings_to_intervals(variable: Variable, source: str, readings: Iterable[Reading],
                          freshness_seconds: float, quality: Quality = Quality.OBSERVED,
                          offset: float = 0) -> tuple[tuple[Interval, ...], tuple[str, ...]]:
    """Forward zero-order hold, bounded by freshness and next state event.

    Invalid/unavailable events terminate previous readings; no backwards fill.
    """
    if not isfinite(freshness_seconds) or freshness_seconds <= 0:
        raise ValueError("Positive freshness required")
    ordered = sorted(readings, key=lambda r: utc(r.timestamp))
    result, flags = [], []
    for n, reading in enumerate(ordered):
        start = utc(reading.timestamp)
        end = start + timedelta(seconds=freshness_seconds)
        if n + 1 < len(ordered):
            end = min(end, utc(ordered[n + 1].timestamp))
        if reading.status != "valid":
            flags.append(reading.status)
            continue
        if reading.value in (None, "unknown", "unavailable"):
            flags.append("unknown" if reading.value is None else str(reading.value))
            continue
        try:
            value = normalize(variable, float(reading.value), reading.unit, offset)
        except (ValueError, TypeError) as error:
            flags.append(str(error) if str(error) in ("invalid_numeric", "ambiguous_unit", "physically_implausible") else "invalid_numeric")
            continue
        if end > start:
            result.append(Interval(variable, start, end, value, source, quality, start,
                                   UNITS[variable], float(reading.value), reading.unit))
    return tuple(result), tuple(flags)


def counter_intervals(variable: Variable, source: str, readings: Iterable[Reading],
                      *, max_gap_seconds: float, zone: str,
                      daily_reset: bool = False, rollover: float | None = None) -> tuple[tuple[Interval, ...], tuple[str, ...]]:
    """Differences only within one source and unit; uncertain reset intervals lost.

    Cross-midnight daily-reset intervals are discarded; a midnight zero reading
    is the next day's baseline. Rollover modulus is in original sensor units.
    No guessing of increments before an unknown reset.
    """
    from zoneinfo import ZoneInfo
    if variable not in TOTALS or not isfinite(max_gap_seconds) or max_gap_seconds <= 0:
        raise ValueError("Counter requires total variable and positive max gap")
    if rollover is not None and (not isfinite(rollover) or rollover <= 0):
        raise ValueError("Positive rollover modulus required")
    ordered = sorted(readings, key=lambda r: utc(r.timestamp))
    result, flags = [], []
    for a, b in zip(ordered, ordered[1:]):
        start, end = utc(a.timestamp), utc(b.timestamp)
        if a.status != "valid" or b.status != "valid":
            flags.append("invalid_counter_state")
            continue
        if not 0 < (end - start).total_seconds() <= max_gap_seconds:
            flags.append("counter_gap")
            continue
        if a.unit != b.unit:
            flags.append("counter_unit_change")
            continue
        try:
            av, bv = float(a.value), float(b.value)
            if not all(isfinite(v) and v >= 0 for v in (av, bv)):
                raise ValueError
            delta = bv - av
            local = end.astimezone(ZoneInfo(zone))
            if daily_reset and start.astimezone(ZoneInfo(zone)).date() != local.date():
                flags.append("daily_reset_boundary_unknown")
                continue
            interval_flags = ()
            if delta < 0:
                if rollover is None or not av < rollover or not bv < rollover:
                    flags.append("counter_reset_unknown")
                    continue
                delta += rollover
                interval_flags = ("explicit_rollover",)
            value = normalize(variable, delta, b.unit)
        except (ValueError, TypeError):
            flags.append("invalid_counter_value")
            continue
        result.append(Interval(variable, start, end, value, source, Quality.OBSERVED,
                               end, UNITS[variable], delta, b.unit, interval_flags))
    return tuple(result), tuple(flags)


def solar_energy_intervals(intervals: Iterable[Interval]) -> tuple[Interval, ...]:
    """Unify measured power and provider/counter energy BEFORE source ranking.

    Interval-mean W/m² * elapsed seconds / 1e6 = MJ/m². Source adapters must
    provide defensible interval means; no assumed interpolation across gaps.
    """
    result = []
    for i in intervals:
        if i.variable == Variable.SOLAR_ENERGY:
            result.append(i)
        elif i.variable == Variable.IRRADIANCE:
            result.append(Interval(Variable.SOLAR_ENERGY,i.start,i.end,
                                   i.value*(i.end-i.start).total_seconds()/1e6,
                                   i.source,i.quality,i.timestamp,"MJ/m²",
                                   i.original_value if i.original_value is not None else i.value,
                                   i.original_unit or i.unit,i.flags+("power_interval_integration",)))
        else:
            raise ValueError("Solar inputs only")
    return tuple(result)
