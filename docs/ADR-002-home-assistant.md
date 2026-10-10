# ADR 002: Home Assistant collection and shared diagnostics

Status: Phase 2 implemented; local contracts verified, real HA suite awaiting Linux execution.
Date: 2026-10-10. Scientific decisions from ADR 001 remain in force.

## Scope and APIs

UI config/options/location reconfigure, stable paddock placeholders, independently
ranked sources, live state collection, hourly forecast archival, HA Store, civil
daily scheduling, shared sensor entities, redacted diagnostics and bounded weather
recalculation. No paddock calculations, WSC entities, reset buttons, soil-number
entities or imports in this phase. Generic soil inputs stay diagnostic.

Reviewed current HA guidance for
[config entries](https://developers.home-assistant.io/docs/config_entries_index/),
[options flows](https://developers.home-assistant.io/docs/core/integration/options_flow/),
[weather entities](https://developers.home-assistant.io/docs/core/entity/weather/),
[coordinators](https://developers.home-assistant.io/docs/integration_fetching_data/),
and public Store/event helpers. Uses runtime_data, OptionsFlowWithReload, modern
entity filters, state change/report events and `weather.get_forecasts` responses.
Schema import uses probatio when available, voluptuous for earlier HA releases.
Engine modules never import HA. Integration code uses Python 3.12-compatible syntax;
real HA runs on its own required Python version.

## Deployment

The authoritative engine remains `pasture_wsc/`. `tools/sync_engine.py` creates a
byte-identical bundle at `custom_components/pasture_wsc/engine`; tests and CI reject
drift. A single custom component folder can be copied without publishing a package.
No network client or vendor-specific station dependency is installed.

## Source semantics and continuity

Selected weather entities create estimated current-temperature/cloud/humidity mappings.
HA weather properties do not guarantee measurements; these mappings need explicit
provider-estimate opt-in. Advanced `weather_observation` mappings require verified
observation/calibration notes. No irradiance or precipitation attribute is assumed.
Hourly forecasts require opt-in and supported features; daily highs/lows are not means.

Observations use last_reported, not polling time, except forward-only initial snapshots.
Initial freshness still expires relative to the source's original report. Restored
state is rejected. Initial counter snapshots are unverified baselines; two new actual
reports are needed to resume increments. An uncertain restart interval remains missing.
Five-minute polling checks outages/retries but never refreshes unchanged report times.
Unknown/unavailable/stale and device/state-class problems remain explicit.

Mappings have stable IDs plus content fingerprints. Raw readings retain mapping
snapshots, units, calibration, rank and daily-reset timezone. Retired mappings end
at reload. Options changes preserve historical calibration semantics and paddock IDs;
a future correction UI must explicitly select which old records to change.

Hourly forecasts are accepted only if acquired before interval start. Successive
points define intervals of at most one hour, with an explicit interval-mean assumption.
Naive timestamps and trailing points are rejected. Latest pre-period issuance replaces
the retained interval; elapsed periods stay frozen. No current forecast fetch provides
missing past observations. Original values/units/issue time are retained, but earlier
superseded forecast issuances are not archived in V1.

## Opt-in solar refinement

The ADR 001 daily cloud formula is allocated on five-minute intervals using positive
solar elevation, latitude, declination and longitude solar noon. FAO daily extraterrestrial
radiation is distributed proportional to positive solar-elevation weights. Each daylight
slot requires supported cloud cover or an explicit clear-sky assumption. Nighttime energy
is zero. Equation-of-time, terrain, horizon and atmospheric calibration are omitted and
flagged; no statistical confidence interval is asserted. Forecast clouds retain forecast
quality; other derived solar is estimated/assumed. Measured solar wins by rank, so only
supported gaps receive the estimate. This is an intentional uncalibrated extension.

## Durability and daily execution

`.storage/pasture_wsc.<entry_id>` uses HA Store schema 1 and atomic writes. Collected
batches are saved and unload flushes the archive. Snapshots serialize outside the event
loop; daily numerical derivation runs in the executor. Failed schema loads leave storage
unwritten, including failed-setup cleanup. HA's own storage error handling still applies.
Observations, selected forecasts, mapping revisions and daily versions persist without
recorder. Archives are not automatically pruned: high-rate sources increase disk size
and write cost. Sharding/retention with explicit export is a future scalability improvement.

Daily key is input date + model version + location/timezone context hash. Equal hashes
are idempotent; changes append versions. Settings changes retain prior summary contexts,
raw input provenance, intervals, gaps and normalized summaries. Paddocks are never
rewritten by options or location reconfiguration. No SPECHR/WSC is accumulated here.

Default run is 00:15 configured local time. Before that clock, regular retries show the
prior eligible date. One-shot UTC timers are derived from the configured timezone:
nonexistent spring times move across the gap, ambiguous fall times use the first fold
once. Five-minute retries cover seven eligible days; manual recalculation accepts 1-31
completed local dates from retained inputs. Historical recalculation cannot move sensors
back from the latest eligible date. Neither recorder nor current state invents backfill.

Weather readiness requires temperature and solar at configured coverage. Estimated,
forecast and assumed inputs produce scenario_only weather readiness. Model status stays
pending_soil_and_paddock_model. Last completed weather day is distinct from last completed
model day, which stays unavailable in Phase 2 even when weather is ready.

## Verification limits

Local tests cover setup/options/reconfigure contracts, archive restarts/versioning,
failed-load cleanup, pending retries, backfill bounds, source failover, forecast provenance,
solar nighttime behavior, DST schedules, sensors and diagnostics redaction. HA-dependent
modules use explicit API test doubles. `tests_ha/` exercises actual config entries,
entities, options, reload and storage through the custom-component pytest plugin on
Linux. CI runs that suite separately. This Windows machine has no HA, Docker or installed
WSL distribution; the real suite and a live UI installation remain unverified locally.
