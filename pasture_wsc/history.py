"""Pure deterministic daily replay, not durable storage or HA lifecycle."""
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
import json
from typing import Mapping

from .model import Components, SoilIndex, MoistureMode, Parameters, VIGOR_REGROWTH, calculate


@dataclass(frozen=True)
class DailyInput:
    daylength_h: float | None
    temperature_c: float | None
    radiation_mj_m2: float | None
    soil: SoilIndex | None = None
    source_hashes: tuple[str, ...] = ()
    assumed_weather: bool = False


@dataclass(frozen=True)
class DailyResult:
    day: date
    spechr: float | None
    components: Components
    incomplete_history: bool
    input_hash: str


def replay(start: date, end: date, inputs: Mapping[date, DailyInput],
           mode: MoistureMode | None = None, *, scenario: bool = False,
           parameters: Parameters = VIGOR_REGROWTH) -> tuple[DailyResult, ...]:
    """Inclusive date range, no skipping gaps and no mutable accumulator.

    Start is a pragmatic cycle approximation, not a dry-matter start model.
    SPECHR needs L,T,wi; missing radiation blocks WSC, not development.
    Source hashes must include policies, calibration and immutable observations.
    """
    if end < start or (end - start).days > 3660:
        raise ValueError("Range must be ordered and at most 3661 days")
    from dataclasses import asdict
    cumulative, gap, results = 0.0, False, []
    previous_hash = "cycle_start"
    day = start
    while day <= end:
        entry = inputs.get(day, DailyInput(None, None, None))
        if entry.assumed_weather and not scenario:
            entry = DailyInput(entry.daylength_h, None, None, entry.soil, entry.source_hashes, True)
        development = calculate(entry.daylength_h, entry.temperature_c, entry.radiation_mj_m2,
                                soil=entry.soil, mode=mode, scenario=scenario, parameters=parameters).development
        if development is None:
            gap = True
        if not gap:
            cumulative += development
        components = calculate(entry.daylength_h, entry.temperature_c, entry.radiation_mj_m2,
                               None if gap else cumulative, entry.soil, mode,
                               scenario=scenario, parameters=parameters)
        payload = {"day": day.isoformat(), "input": asdict(entry), "mode": mode,
                   "scenario": scenario, "parameters": asdict(parameters),
                   "model_version": components.model_version, "start": start.isoformat(),
                   "previous_hash": previous_hash}
        digest = sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        previous_hash = digest
        results.append(DailyResult(day, None if gap else cumulative, components, gap, digest))
        day += timedelta(days=1)
    return tuple(results)
