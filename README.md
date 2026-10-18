# Pasture WSC — engine and Home Assistant integration

Setup combines measured sensors, weather forecasts and fallbacks on one
**Inputs & fallbacks** page. Skip physical sensors if using a weather provider.
Only selecting **Review advanced settings** opens an additional page for timing,
coverage thresholds and (when a soil sensor is selected) soil reading freshness;
measurement notes are internal and require no user input. A rain gauge's counter type must
match its cumulative or daily-reset behaviour. Advanced source mappings remain
available for accumulated solar energy, calibration, priorities and freshness.
Existing inputs and policies are preserved on upgrade; the new flow does not
turn fallbacks on or off automatically. Clear-sky fallback remains off for new
setups. Existing users can review it under Data gaps & fallbacks.

Experimental pasture water-soluble carbohydrate engine with Home Assistant weather collection and Phase 3
paddock devices, model results and management controls. **No horse grazing safety decision is provided.**
Generic soil moisture is not a calibrated FONSCH water index. Primary and explicitly assumed scenario results are separate.

## Install in Home Assistant

1. Copy the entire `custom_components/pasture_wsc` folder into your HA configuration
   directory under `custom_components/`. The bundled engine is included; no separate
   package is needed. Or extract `dist/pasture_wsc-0.4.7.zip` into that directory.
2. Restart HA. Select **Settings → Devices & services → Add integration → Pasture WSC**.
3. Accept/override HA location and timezone. Choose optional weather providers,
   daily calculation time, completeness thresholds and explicit fallback policies.
4. Enter paddock names and the approximate cut/grazing start date. The initial date
   applies to all paddocks; each can be changed independently afterward.
5. Add any source mappings and choose **Save configuration**. No YAML is required.

Uses recent HA APIs: runtime_data, OptionsFlowWithReload, state reporting and forecast
response services. The local contract tests pass, but this Windows workspace has no
runnable HA/Linux environment. Real HA tests and a live UI installation remain unverified
locally. The separate Linux CI job is provided for that verification.

## Configure weather and station sources

You can begin with `weather.met` or any configured weather entity. Selected providers
create temperature, humidity and cloud mappings where supported. Current values are
conservatively **estimated**, because HA properties do not guarantee measurements.
Explicitly enable **Allow provider-derived weather estimates** to use them in normalized
weather diagnostics. Optional hourly forecasts need a separate opt-in; they are archived
before their target intervals and retain `forecast_proxy` quality. Daily forecast highs
and lows are never converted to a daily mean. Current values cannot fill yesterday.

Solar estimation is a separate opt-in: astronomy plus supported cloud intervals, with
nighttime zero. Missing daytime cloud is not clear sky unless explicitly assumed.
It is an uncalibrated scenario and remains labeled estimated/assumed/forecast-derived.

In **Configure**, independently add/edit/remove each variable's source and rank.
Adding a station preserves historical records and paddock IDs.

| Mapping | Variable | Kind | Units |
| --- | --- | --- | --- |
| Air temperature sensor | temperature | instantaneous | °C, °F or K |
| Irradiance sensor | irradiance | instantaneous | W/m² |
| Accumulating solar energy | solar_energy | counter | Wh/m², kWh/m² or MJ/m² |
| Daily-reset rain gauge | precipitation | daily_reset | mm or in |
| Cloud/humidity sensor | cloud_cover / humidity | instantaneous | % |

Lower rank wins per variable and interval; recovery returns to the better rank.
Freshness bounds held readings. Sensor offsets apply in normalized units; counter
offsets are rejected. Provide explicit semantics/calibration notes. Generic kWh is
ambiguous without area and rejected; unit overrides require defensible mapping.
Use `weather_observation` only when the provider attribute is verified observed data.

Sources never overlap in the summed output. Resets, unit changes and excessive counter
gaps discard uncertain increments. Initial counter snapshots are unverified; two new
actual reports are needed before increments resume. A missing midnight baseline cannot
recover rain between midnight and the first report. Default coverage is 80% for mean
variables and 100% for solar energy; lowering it does not extrapolate missing energy.
Inspect coverage, partial values, fallback proportion and missing interval counts.

An optional soil sensor requires meaning/calibration notes and freshness. It remains
`fonsch_compatible: false`; its value is diagnostic only. Unknown soil leaves primary FONSCH
moisture/development and completed model day unavailable.

## Shared entities

Entities have stable unique IDs and share an entry device. HA chooses their final IDs.

| Sensor | Meaning |
| --- | --- |
| Daylength | Geometric photoperiod for the input date |
| Daily mean temperature | Time-weighted °C with provenance |
| Daily solar energy | MJ/m² over supported intervals |
| Daily cloud cover / humidity | Time-weighted percent |
| Daily precipitation | Supported rain increments, mm |
| FONSCH photoperiod / temperature factors | Independent equation diagnostics |
| FONSCH moisture / daily development factors | Shared moisture unavailable; development is per paddock |
| Weather status / quality | ready, scenario_only or pending_weather |
| Model status | ready_experimental or pending_paddock_inputs |
| Last completed weather day | Latest strict eligible weather date |
| Last completed model day | Latest day completed by all enabled paddocks |
| Soil diagnostic status | Raw value, units, semantics and freshness |

Weather attributes include input day, timezone, units, source, coverage, fallback share,
quality class, timestamp, warnings, partial value and source hash. Long histories stay
in storage. Diagnostic downloads omit entities, coordinates, raw readings, names and notes.

## Scheduling, persistence and recalculation

The daily run defaults to 00:15 configured local time for the completed previous day.
Five-minute retries cover seven recent eligible days. DST days have their actual
23/24/25-hour duration; ambiguous schedule times run once, nonexistent times advance
across the gap. Location reconfiguration is available in the integration menu.

HA Store `.storage/pasture_wsc.<entry_id>` persists raw samples, mapping snapshots,
forecast inputs and versioned daily summaries independently of recorder. Source options
preserve paddock identity and old calibration semantics. Location/timezone changes retain
old summary contexts. V1 does not prune archives; high-rate sensors increase disk/write cost.

**Developer tools → Actions → pasture_wsc.recalculate** accepts an integration entry and
1–31 completed local dates. It uses retained inputs, preserves previous summary versions,
and never fabricates backfill. Historical recalculation does not move sensors to an older
date. Missing weather stays pending; ready weather still requires compatible paddock inputs to complete a model day.

## Engine and development

Python 3.12+:

```powershell
python -m pip install -e ".[test]"
python -m pytest tests -q
python -m pasture_wsc --daylength 15 --temperature 20 --radiation 18
```

This leaves WSC pending without compatible wi, an explicit moisture mode and SPECHR.
A separately labeled assumed scenario:

```powershell
python -m pasture_wsc --daylength 15 --temperature 20 --radiation 18 --spechr 10 --wi 0.4 --soil-semantics "Assumed compatible-scale scenario; not VWC" --compatible-index --scenario --moisture-mode one_minus_wi_over_reference
```

CLI SPECHR includes the current day. `history.replay` computes it from dated inputs and
blocks at gaps. The authoritative engine in `pasture_wsc/` never imports HA. After editing
it, run `python tools/sync_engine.py`; tests/CI reject drift in the bundled copy. Build an
installation zip with `python tools/build_integration.py`. Engine/model and HA adapter
versions are independent.

Actual HA tests run separately on Linux with HA's required Python version:

```bash
pip install pytest-homeassistant-custom-component
python -m pytest tests_ha -q -o asyncio_mode=auto
```

Local API doubles are explicitly distinguished from those actual HA tests.

## Scientific assumptions, migration and troubleshooting

[ADR 001](docs/ADR-001-engine.md) contains the paper equation/coefficient table and
unresolved soil/initialization choices. [ADR 002](docs/ADR-002-home-assistant.md) documents
HA collection, continuity, storage, the solar approximation and test limits. The paper's
Figure 7 moisture plateau differs from the specification's unbounded expressions; both
requested signs are explicit and neither is default. The external growth/water model
is not recreated. Fitting errors are not Ontario confidence intervals.

Existing helpers and automations are untouched. Back up HA/export existing history before
a future one-time import. Preview and confirmation are deferred; no auto-import exists.

- No yesterday's data after installation: wait for collection of a complete local day.
- Met.no missing: provider estimates default off; opt in explicitly and inspect coverage.
  Cloud attributes may be absent, and forecast support is not assumed.
- Solar missing: supply measured power/energy or enable the documented solar scenario.
- Station outage: inspect coverage, fallback and collector issues; no fake observed data.
- Store failure: preserve the archive and restore backup. Failed-load cleanup cannot
  overwrite an unread archive. Do not delete history to fix an unavailable sensor.
- Integration missing from the list: check folder placement, restart HA and inspect logs.

## Phase 3 upgrade and paddock management

Overwrite the existing `custom_components/pasture_wsc` folder with the 0.3.0
package and restart HA. Keep the integration entry: its paddock IDs, collected weather
and histories are retained. Each named paddock appears as its own device, linked to
the shared Pasture WSC weather device.

Each paddock has experimental WSC and daily change, cumulative SPECHR, diagnostic GDD,
separate scenario results, component contributions, statuses, cycle dates and IDs.
Rain accumulation (since last cut) sums available daily rainfall in mm through the
latest completed day, including allowed forecast estimates. Attributes report
days with data, missing days and completeness. The total starts at 0 mm even
before rain data arrives; missing days remain excluded and marked incomplete.
Zero with no data does not mean confirmed dry weather. Changing Last cut resets the range;
backfills and corrections replay the total.
Separate Rain accumulation (measured) and Rain accumulation (estimated) sensors
include today through the current time, starting at Last cut. Measured totals
use observed/provider intervals; estimated totals use estimated/forecast inputs
independently, with no measured fallback or double counting overlapping sources.
They update on source reports and every minute, with forecast retrieval remaining
hourly. The current hour's forecast amount is distributed uniformly across its
elapsed portion, so the estimate can move each minute without claiming actual
minute-by-minute rainfall. Missing intervals are excluded; coverage and missing
hours are attributes. Both totals initialize at zero. The original combined daily
sensor remains available and still ends at yesterday.
Initial setup includes a default soil type dropdown: Unsure (default), Sandy,
Loam or Clay. Each paddock has its own Soil type dropdown in its device's
Configuration section and in Configure → Manage paddocks → Paddock settings.
New paddocks inherit the onboarding default. Existing paddocks inherit the
previous site setting once, preserving any subsequent per-paddock choices.
Soil type controls the experimental daily
rainfall/drying bucket estimate. Per-paddock Soil moisture (measured) and Soil
moisture (estimated) sensors report dimensionless indices on 0–1, not VWC percent.
Measured requires an attested compatible index with sufficient daily coverage.
The estimated-inputs WSC route prefers that index, then the weather estimate,
then the explicit initial/fallback moisture index when weather history is missing.
The default WSC preference still selects the measured-inputs route first.

The moisture estimate now uses FAO-56 daily Penman–Monteith reference ET and a
single-coefficient root-zone water balance. The previous heuristic drying formula
has been removed. See [FAO setup, assumptions and references](docs/fao56/README.md).
Per-paddock settings include effective rooting depth (default 0.5 m), pasture Kc
(0.85), and wind measurement height (10 m). Representative soil properties within
FAO ranges replace the old fixed capacities. The initial moisture index (default
0.47) seeds relative available water on Last cut. Missing wind uses a flagged
temporary 2 m/s at 2 m; missing humidity uses a flagged Tmin/dewpoint approximation.
The storage fraction remains an unvalidated proxy for the original WSC model wi.
Snowmelt, irrigation and runoff are not simulated; days with Tmax ≤ 0 °C hold state.
Missing rain, temperature or solar holds the previous moisture level (initially
the configured initial/fallback index) without applying rainfall or drying.
Tracking resumes on the next complete day. Missing rain remains null, not zero.
The estimate exposes `status: held_assumption`, cumulative `assumed_days` and
warnings; WSC exposes the method in its `selected_moisture_method` attribute.
Hourly forecast precipitation amounts are archived when forecast use is enabled,
converted from the provider's mm/in units, and summed over completed local days.
Rain probability is never substituted for an amount. These forecasts cannot fill
dates before collection started. Sensor attributes expose inputs, capacity,
drying, drainage and warnings. Replay reconstructs estimates after restart;
corrected weather, soil type or initial index recalculates the active cycle.
Daily change is the final WSC minus the previous day's final WSC, in percentage
points, using the configured preference and fallbacks independently for each day.
It is unknown on the first day or when either day's WSC is missing. The separate
scenario daily change compares scenario WSC values only.
Controls include enable/disable, estimated-inputs opt-in, soil type and an editable
Last cut date that starts the regrowth cycle. Initial moisture is internal: new
paddocks start at 0.47; existing saved assumptions are preserved. Its numeric
control is retired automatically on reload.

Detailed factors, contributions, SPECHR/GDD, duplicate WSC route outputs and the
legacy daily rain total are disabled by default for new entities. Main automatic
WSC, daily change, WSC level, both moisture outputs and both live rain totals stay
enabled. Existing entity enablement is preserved. Disable existing extras in Home
Assistant's entity settings, or hide them if you want to retain their history.
Calculations use coordinator data, not output entities: disabling outputs does not
stop the model. Disabling stops state/history recording for that entity; hiding
only changes presentation. Input weather/rain sensors must remain available.

Main paddock diagnostics now follow WSC (auto): Calculation status, WSC method,
Moisture method, Calculated through and Data gaps. A usable estimated result is
shown as Ready with estimates even if the measured route is pending soil. The
date is the current selected WSC result's date, not a historical measured success.
Data gaps counts days with held moisture and missing development inputs; zero
reported gaps does not validate assumed soil properties or the FAO/WSC proxy.
Cycle ID, preset, measured history/status and separate estimated status are
disabled by default for new entities. Existing registry settings are preserved;
hide or disable existing technical entities manually if desired.

Open **Configure → Manage paddocks → select paddock → Paddock settings** to choose
moisture semantics and an explicit moisture response. Defaults leave moisture unknown
and scenarios off. A percent soil sensor remains diagnostic; calibrated primary input
requires an attested FONSCH-compatible dimensionless index on 0–1, not a VWC conversion.
For an exploratory scenario, enable it and choose an explicit moisture expression.
Initial/fallback wi seeds that scenario's current cycle; gaps hold the previous
moisture level. Changing settings replays the cycle and retains previous result
versions. Estimated weather stays labeled as such.

Change **Last cut** directly on the paddock device to choose its cut/grazing
date. Saving a different date archives the active cycle and replays retained history;
Alternatively, press **Mark paddock cut** in the paddock Configuration panel to
set Last cut to today in the integration's configured timezone and start a new
cycle. The previous cycle is archived. Repeat presses on that same date do
nothing. New-cycle WSC waits for a completed day; rain accumulation starts at zero.
saving the same date does nothing. Future dates and dates over 3660 days old are rejected.
Only that paddock changes. Settings apply immediately; choose **Save configuration**
after changing source subscriptions or adding paddocks to reload their entities.
Disabling a paddock keeps its history, and reenabling replays retained weather.

### Weather backfill and selecting the growth start

Open **Configure → Backfill weather** to retrieve 1–366 completed local dates, including
the partial installation day. This also enables automatic backfill for later gaps.
Alternatively, enable **Fill missing past weather from local Home Assistant history** in weather settings.
On startup and hourly retries, enabled backfill checks active cycles (up to 366 days
through the scheduled completed date), imports missing temperature/radiation coverage,
and replays all fetched dates. Complete retained coverage needs no network request.
Older cycles may require separate manual date ranges. Today is calculated after its
scheduled completion time, not as a partial day.

For an existing paddock, edit its **Growth cycle start** date entity directly; no
configuration screen or request button is needed. Earlier weather uses retained history.
Enable automatic local backfill or use the backfill weather configuration screen when
additional recorder history is needed. Missing history remains marked incomplete.
Setup and adding a paddock also provide a date picker; per-paddock dates can differ.

Backfill reads the configured weather entities and sensor mappings from Home Assistant's
local recorder database. It makes no external requests. Attribute-only weather changes
are included, so retained temperature, cloud cover and humidity can be recovered even
when the weather condition text did not change. Existing live observations take priority.
Recorded sensor units, timestamps, unknown/unavailable periods and configured freshness
limits are respected. UTC intervals preserve local DST boundaries. Recorder queries run
on its database executor, including materialization of historical attributes.

When no irradiance/energy sensor was recorded, enable the existing astronomy/cloud solar
estimate in weather settings to derive radiation from recorded cloud cover. Backfill does
not automatically enable a clear-sky assumption or change model coefficients. Weather
provider proxies stay estimated; verified sensor mappings keep their existing quality.
Historical mapping semantics come from the current configured mappings, so only import
periods for which those semantics/calibrations apply.

Only retained recorder history can be recovered. Excluded entities, purged dates, and
readings never recorded remain missing. Backfill does not retrieve past forecasts from
weather services or contact Open-Meteo. The separate existing forecast opt-in is unchanged.
Imported intervals and prior daily versions persist across restarts. Changing location
will not reuse imported intervals from another configured location. Diagnostics include
the imported interval count and local-history errors.

GDD uses a configurable base (default 5 °C) and is diagnostic, independent of SPECHR.
Cycles retain their original location and timezone; start a new confirmed cycle to adopt
a reconfigured location. See [ADR 003](docs/ADR-003-paddocks.md).


### Sensor presentation

Completed model/weather day sensors (including the per-paddock completed day) are
disabled by default for new entities. Their dates remain available on status/history
sensor attributes, even with the date entities disabled: calculations read the shared
coordinator and retained archive directly. Existing installations keep their entity
registry choices; disable these date sensors manually to hide them. Disabling a
configured external weather/soil source can still remove input data.

Numeric sensors suggest one decimal place for weather, WSC, trends, effects, cumulative
SPECHR and GDD, and three decimal places for fractions/model factors and daily development.
Precision follows the quantity's scale, rather than changing when a value crosses 1.
Calculations retain full precision, and Home Assistant's user-selected display precision
continues to take priority.


Each paddock has a numeric **Water-soluble carbohydrates** sensor for the default result, displayed to one decimal
place. Set **Preferred carbohydrate estimate** on the paddock device to Primary model (the initial default)
or Scenario model. The sensor uses that route when it has a finite result for the current model day,
then falls back to the other available route. The scenario must be explicitly enabled;
choosing it as the preference does not enable it. A disabled paddock or two missing
results makes WSC unavailable. It never substitutes zero or an older day's result.

WSC attributes identify the selected/preferred route, fallback, date, warnings and
whether scenario assumptions apply. Both route-specific sensors remain available,
and disabling those display entities does not affect WSC's choice. The preference is
saved per paddock and survives reloads.


### Plain-language carbohydrate level

**Pasture carbohydrate level** uses the same preferred-route selection and fallback as
**Water-soluble carbohydrates**, displaying Low below 10%, Medium from 10% to below
20%, and High at 20% or above. Values are percentages of dry matter. Missing estimates
make this sensor unavailable; they are never classified as Low. Classification uses
full precision before display rounding. The percentage, route and cutoffs remain in
its attributes. Edit both cutoffs under paddock settings; the lower must be positive
and below the upper, and the upper cannot exceed 100%.

These are application-defined descriptive bands, based on the 10–20% typical grass
WSC range at harvest in [NC State Extension's forage conservation guide](https://content.ces.ncsu.edu/forage-conservation-techniques-silage-and-haylage-production).
They are not a published universal three-level classification or grazing-safety limits.
The commonly cited 10–12% guidance for susceptible horses concerns nonstructural
carbohydrates (WSC plus starch), as explained by [University of Minnesota Extension](https://extension.umn.edu/agriculture/animals-and-livestock/horse/understanding-your-hay-analysis).
This experimental model estimates WSC alone and does not measure starch or establish
animal-specific safety.
