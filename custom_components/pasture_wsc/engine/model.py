"""Full precision equations transcribed from the supplied specification.

Coefficients verified against Table 2 of the supplied 1999 paper. No soil conversion.
"""
from dataclasses import dataclass
from enum import StrEnum
from math import exp, isfinite

from . import MODEL_VERSION


class MoistureMode(StrEnum):
    INCREASING = "wi_over_reference_minus_one"
    DECREASING = "one_minus_wi_over_reference"


@dataclass(frozen=True)
class Parameters:
    name: str = "vigor_regrowth_n40_spec_response"
    dry_matter_start_g_m2: float = 20.0
    photoperiod_rate: float = 0.80
    photoperiod_threshold: float = 10.0
    temperature_rate: float = 0.234
    temperature_threshold: float = 4.0
    moisture_offset: float = 0.271
    trend_scale: float = 6.195
    trend_power: float = 0.993
    trend_decay: float = 0.090
    radiation_scale: float = 6.0
    radiation_rate: float = 0.073
    radiation_threshold: float = 2.0
    temperature_scale: float = 8.0
    short_temperature_rate: float = 0.100
    short_temperature_threshold: float = 5.0
    moisture_scale: float = 8.0
    moisture_reference: float = 0.47

    def __post_init__(self):
        values = [v for v in vars(self).values() if isinstance(v, (int, float))]
        if not all(isfinite(v) and v >= 0 for v in values):
            raise ValueError("Parameters must be finite and nonnegative")
        if self.moisture_reference == 0 or self.trend_power == 0:
            raise ValueError("Reference and trend power must be positive")


VIGOR_REGROWTH = Parameters()


@dataclass(frozen=True)
class SoilIndex:
    value: float
    semantics: str
    compatible: bool = False
    assumed: bool = False

    def __post_init__(self):
        if not isfinite(self.value) or not self.semantics.strip():
            raise ValueError("Finite wi and explicit semantics required")


@dataclass(frozen=True)
class Components:
    photoperiod_factor: float | None
    temperature_factor: float | None
    moisture_factor: float | None
    development: float | None
    trend: float | None
    radiation_effect: float | None
    temperature_effect: float | None
    moisture_effect: float | None
    experimental_wsc: float | None
    status: str
    warnings: tuple[str, ...]
    model_version: str = MODEL_VERSION


def calculate(daylength: float | None, temperature: float | None,
              radiation: float | None, spechr: float | None = None,
              soil: SoilIndex | None = None, mode: MoistureMode | None = None,
              *, scenario: bool = False,
              parameters: Parameters = VIGOR_REGROWTH) -> Components:
    """SPECHR is the cumulative value INCLUDING this day's development.

    None remains unavailable; callers must distinguish primary/scenario inputs.
    A compatible flag is a caller attestation, not scientific validation.
    """
    for value in (daylength, temperature, radiation, spechr):
        if value is not None and not isfinite(value):
            raise ValueError("Nonfinite model input")
    if daylength is not None and not 0 <= daylength <= 24:
        raise ValueError("Daylength outside 0..24 h")
    if radiation is not None and radiation < 0 or spechr is not None and spechr < 0:
        raise ValueError("Negative radiation or SPECHR")
    if mode is not None:
        mode = MoistureMode(mode)
    p = parameters
    pf = None if daylength is None else 1 - exp(-p.photoperiod_rate * max(0, daylength - p.photoperiod_threshold))
    tf = None if temperature is None else 1 - exp(-p.temperature_rate * max(0, temperature - p.temperature_threshold))
    usable = soil is not None and soil.compatible and (scenario or not soil.assumed)
    mf = min(1.0, max(0.0, 1 - soil.value + p.moisture_offset)) if usable else None
    dev = pf * tf * mf if pf is not None and tf is not None and mf is not None else None
    trend = None if spechr is None else p.trend_scale * spechr ** p.trend_power * exp(-p.trend_decay * spechr)
    re = None if radiation is None else p.radiation_scale * (1 - exp(-p.radiation_rate * max(0, radiation - p.radiation_threshold)))
    te = None if temperature is None else p.temperature_scale * (1 - exp(-p.short_temperature_rate * max(0, temperature - p.short_temperature_threshold)))
    me = None
    if usable and mode is not None:
        me = p.moisture_scale * (soil.value / p.moisture_reference - 1)
        if mode == MoistureMode.DECREASING:
            me = -me
    complete = all(v is not None for v in (dev, trend, re, te, me))
    wsc = trend + re - te + me if complete else None
    warnings = ["experimental_unvalidated", "spec_moisture_expression_unbounded"]
    if not usable:
        warnings.append("compatible_soil_index_missing")
    if mode is None:
        warnings.append("moisture_response_unspecified")
    if scenario:
        warnings.append("scenario_assumptions")
    if wsc is not None and not 0 <= wsc <= 100:
        warnings.append("implausible_percentage_unclamped")
    return Components(pf, tf, mf, dev, trend, re, te, me, wsc,
                      "scenario" if complete and scenario else "experimental" if complete else "pending",
                      tuple(warnings))
