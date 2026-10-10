# Pasture WSC — engine and Home Assistant integration

Experimental pasture water-soluble carbohydrate engine with a Phase 2 Home Assistant
collection and diagnostics layer. **No horse grazing safety decision is provided.**
Generic soil moisture is not a calibrated FONSCH water index. Paddock WSC/SPECHR,
confirmed resets and scenario controls remain Phase 3 work.

## Install in Home Assistant

1. Copy the entire `custom_components/pasture_wsc` folder into your HA configuration
   directory under `custom_components/`. The bundled engine is included; no separate
   package is needed. Or extract `dist/pasture_wsc-0.2.0.zip` into that directory.
2. Restart HA. Select **Settings → Devices & services → Add integration → Pasture WSC**.
3. Accept/override HA location and timezone. Choose optional weather providers,
   daily calculation time, completeness thresholds and explicit fallback policies.
4. Enter paddock names, one per line. Summer, Winter and Back are editable examples;
   stable IDs are reserved now, with growth calculations coming in Phase 3.
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
`fonsch_compatible: false`; its value is diagnostic only. Unknown soil leaves FONSCH
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
| FONSCH moisture / daily development factors | Unavailable pending compatible index and Phase 3 |
| Weather status / quality | ready, scenario_only or pending_weather |
| Model status | pending_soil_and_paddock_model |
| Last completed weather day | Latest strict eligible weather date |
| Last completed model day | Unavailable in Phase 2 |
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
date. Missing weather stays pending; even ready weather does not mark a model day complete.

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
