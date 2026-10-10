# Pasture WSC — Phase 1

Pure Python engine for **Experimental modeled WSC (% dry matter)** using the
Vigor N40 regrowth coefficients of Wulfes, Nyman & Kornher (1999). This is an
unvalidated pasture estimate and supplies no horse-grazing safety decision.

This repository implements the requested **Phase 1 only**: model components,
astronomy, per-variable weather normalization/resolution, deterministic replay,
CLI and tests. It is not yet an installable Home Assistant integration. No HA
entities, helpers, automations or existing configuration are changed.

## Run

Python 3.12+:

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
python -m pasture_wsc --daylength 15 --temperature 20 --radiation 18
```

That example produces weather factors while WSC remains pending without wi,
a chosen moisture response and cumulative SPECHR. An explicit assumed scenario:

```powershell
python -m pasture_wsc --daylength 15 --temperature 20 --radiation 18 --spechr 10 --wi 0.4 --soil-semantics "Assumed FONSCH-compatible scenario; not VWC" --compatible-index --scenario --moisture-mode one_minus_wi_over_reference
```

The CLI's supplied SPECHR must include the current day. Prefer `history.replay`
for a dated sequence; it computes the cumulative value itself. None means missing,
not zero. Numbers are never automatically interpreted as a soil-water index.

## Engine use

`model.calculate` returns separate factors, development, trend, radiation,
temperature, moisture, WSC, status, warnings and model version. Parameter sets
are immutable and explicit; the default coefficients were verified against the
supplied paper's Table 2. `SoilIndex.compatible` is a caller attestation requiring
documented semantics, not a calibrated conversion. Assumed inputs can only
produce scenario outputs. Keep scenario and primary replay calls separate.

`weather.readings_to_intervals` normalizes timestamped sensor readings, applies
forward bounded holds, and returns anomaly flags. `counter_intervals` supports
energy/rain deltas, explicitly configured rollover and conservative reset/gap
handling. Retain its original readings and rejected-event flags for future replay.
`solar_energy_intervals` unifies W/m² and MJ/m² sources before energy resolution.
`resolve_day` accepts independently ranked sources for each variable, chooses one
per interval, and returns coverage, fallback share, immutable interval provenance,
gaps, partial value and hash. Enabled forecast records retain `forecast_proxy`.
No historical data is downloaded or fabricated; Met.no or station readings must
be supplied by future HA adapters as properly labeled intervals.

`astronomy.daylength` handles poles and leap dates; `local_day_bounds` handles DST.
`cloud_radiation` is an opt-in uncalibrated daily scenario, unavailable with unknown
cloud cover by default. It needs adequate daylight cloud coverage supplied by the
caller; it does not generate instantaneous nighttime irradiance.

`history.replay` takes a mapping of dates to immutable `DailyInput` and an inclusive
range (maximum 3661 days). Retries return the same result. Corrections recompute
subsequent SPECHR and hashes. Missing development blocks all later accumulation;
missing radiation alone preserves development but blocks that day's WSC. Adding
station sources changes weather inputs/policies, not cycle identity. Persistence
and independently resettable paddock lifecycle are planned for later phases.

## Review and troubleshooting

Read [ADR 001](docs/ADR-001-engine.md) for the source-equation table, every scientific
assumption, fallback policy and remaining review question. In particular, the
paper's Figure 7 moisture plateau differs from the unbounded expressions requested
in the specification; both requested signs are explicit and neither is default.
The paper's external water-balance and dry-matter initialization are not recreated.

Pending WSC: inspect missing wi, semantics/compatibility, moisture mode, weather
coverage and history gaps. Stale/unavailable station: inspect per-interval flags
and fallback proportions. Missing rain after midnight: supply the recorded reset
baseline; it cannot be inferred. Unsupported units: explicitly normalize/match
semantics rather than converting a total energy sensor to irradiance by guessing.
Windows timezone error: install the declared `tzdata` dependency.

HA installation/configuration, entity list, options UI, durable storage, bounded
service backfill, CSV/JSON export and confirmed helper migration will be documented
when those later phases exist. No helper import is available in Phase 1.
