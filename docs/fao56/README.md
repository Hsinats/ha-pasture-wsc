# FAO-56 soil-moisture setup

The estimated moisture route now uses **daily FAO-56 Penman–Monteith reference
evapotranspiration (ET₀)** and a simplified root-zone water balance. It replaces
the earlier `0.15 × solar + 0.03 × temperature` drying rule. This is an estimate
of plant-available water, not measured soil moisture or a validated WSC prediction.

## Set up Home Assistant

1. Install the updated `custom_components/pasture_wsc` folder and reload the
   integration. Existing paddocks receive the new settings automatically.
2. Open **Configure → Inputs & fallbacks**. Physical sensors, weather providers
   and fallback switches share one page. Select any physical sensors or skip them,
   then select your weather entity below.
   Enable **Use hourly forecasts** to archive forecasts and **Use current weather
   estimates** if you want the weather entity's current conditions used.
3. Supply daily solar energy using a sensor mapping, or enable the existing
   cloud solar estimate on the same page. That estimate is a separate approximation,
   not a FAO radiation observation. Clear-sky assumptions are separately enabled.
4. Under **Configure → Manage paddocks → select paddock → Paddock settings**, check:

   | Setting | Default | What to review |
   |---|---:|---|
   | Soil type | Unsure | Choose sandy, loam or clay; unsure uses loam properties |
   | Effective rooting depth | 0.5 m | Depth of the active root zone, not grass height |
   | Pasture water-use coefficient, Kc | 0.85 | Constant pasture approximation; review for cover and management |
   | Weather wind measurement height | 10 m | Match your weather provider or anemometer; use 2 m for a 2 m instrument |
   | Estimated inputs model | Off for new paddocks | Enable to allow this moisture route to contribute to WSC |

   Initial moisture is an internal starting assumption (0.47 for new paddocks),
   not a user-facing control. Previously saved starting values are preserved.
   Soil type also has a dropdown on the paddock device. Other FAO parameters are
   editable in Paddock settings. They apply to the whole active replay period.

5. Check **Last cut** and your existing moisture-response setting. FAO does not
   choose which of the original WSC model's two response directions to use.
6. Open **Soil moisture (estimated)** and inspect its attributes after reload.
   If history is missing, it will initially hold the internal starting level.

No lab test or new account is required. These are representative starting settings,
not measurements of your paddock. The app cannot inspect your installed weather
provider from this repository, so verify its data and wind height in Home Assistant.

## Weather inputs and fallbacks

The integration collects temperature, humidity and wind from selected weather
entities and their hourly forecasts. Wind source mappings also support sensor
values in m/s, km/h, mph and knots. A single configured wind height applies to all
wind inputs for a paddock; normalize sources first if their measurement heights differ.

Rain uses configured gauges or archived hourly precipitation amounts. Forecast
probability is not a rainfall amount. Solar energy is resolved independently.
Collection does not reconstruct old forecasts; recorder backfill only retrieves
history that Home Assistant actually retained.

Daily temperature minima and maxima come from the resolved temperature interval
series. They are extrema of interval values, not necessarily instrument-recorded
absolute extremes; the sensor flags that approximation. Missing daily temperature
coverage or missing extrema holds moisture rather than substituting the mean twice.

FAO's temporary missing-wind option is **2 m/s at 2 m**. Available wind is converted
from the configured measurement height to 2 m. The adapter uses mean humidity when
available; otherwise it estimates actual vapour pressure by treating Tmin as dewpoint.
That humidity fallback is appropriate only as a reviewed humid-climate approximation.
These choices are exposed as flags, never presented as measured weather.

Missing rain, solar, temperature or usable geometry holds the previous moisture
level for that day. It does not mean zero rain. Tracking resumes on complete days,
with cumulative `assumed_days` retained. Days whose maximum temperature is at or
below freezing also hold state. This is a gap policy, not a snow or frozen-soil model.

## What is calculated

Reference ET uses FAO-56 Eq. 6 with daily soil heat flux set to zero, shortwave
albedo 0.23, estimated net longwave radiation, elevation-derived pressure and
2 m wind. Pasture demand is `Kc × ET₀`. This implementation uses a constant Kc,
not a crop-stage curve or separate soil-evaporation coefficient.

Available storage is calculated from `1000 × (field capacity − wilting point) × rooting depth`.
Representative selections within the published soil-property ranges are:

| Dropdown | Field capacity | Wilting point | Capacity at default 0.5 m |
|---|---:|---:|---:|
| Sandy | 0.12 | 0.04 | 40 mm |
| Loam / Unsure | 0.27 | 0.12 | 75 mm |
| Clay | 0.36 | 0.22 | 70 mm |

Clay can retain more total water while leaving less available to plants than loam.
The chosen values are presets, not universal soil constants.

Rain is applied before the day's water use; remaining excess drains below the root zone.
The single-Kc stress approximation reduces demand as available storage falls. Its
depletion threshold starts at 0.60 and is adjusted for daily demand using FAO's
formula. Actual removal cannot exceed available water. Runoff, irrigation and
groundwater contribution are assumed zero. Root depth and Kc remain constant;
cutting changes the replay start, not an automatically generated Kc curve.

The sensor reports **remaining available water / total available water**, from 0–1.
It is not volumetric water content. At 0 the modeled available storage is exhausted;
at 1 it is full. Soil may still contain water unavailable to plants at index 0.

## Inspecting the result

Useful attributes on **Soil moisture (estimated)** include:

- `method: fao56-pm-v1`, `status`, `missing_inputs`, `flags`, `assumed_days`.
- `capacity_mm`, `field_capacity`, `wilting_point`, `root_depth_m`.
- `rainfall_mm`, `eto_mm`, `potential_crop_et_mm`, `drying_mm`, `drainage_mm`.
- `crop_coefficient`, `stress_coefficient`, `wind_height_m`, `wind_2m_m_s`.

`eto_mm` is reference atmospheric demand; `drying_mm` is the modeled water removed
after Kc, stress and available-water limits. Neither is a measured loss.
Moisture remains a **completed-day** calculation. The separate measured and
estimated rain accumulations include elapsed intervals today and refresh every minute.

Replay uses retained observations and forecasts after restart. Corrected weather,
soil type or settings changes recalculate the active cycle. Consequently a FAO
upgrade can change historical estimated moisture and WSC; stored result versions
remain available. Measured-index WSC equations and measured soil inputs are unchanged.

## Relationship to the WSC paper

Wulfes, Nyman and Kornher (1999), *Modelling non-structural carbohydrates in forage
grasses with weather data*, Agricultural Systems 61, 1–16, sections 2.1 and 2.2.1,
uses a soil-water index supplied by another growth model. The supplied paper does
not specify enough of that water-balance implementation to establish equivalence
to this available-storage fraction.

For continuity, the estimated WSC route uses our fraction as an **unvalidated proxy
for wi**, explicitly flagged `approximate_wi_mapping`. FAO supports the water-balance
approach; it does not validate this bridge to FONSCH or the resulting WSC percentage.
Measured compatible indices retain priority in the estimated-inputs route. The
default automatic WSC preference selects the measured-inputs result first.

## References and checks

- [FAO-56 Chapter 3](https://www.fao.org/4/X0490E/x0490e07.htm): meteorological
  calculations, missing-data approximations and wind-height conversion.
- [FAO-56 Chapter 4](https://www.fao.org/4/X0490E/x0490e08.htm): daily Penman–Monteith
  ET; the regression test reproduces Example 18, **3.88 mm/day**, within 0.01 mm/day.
- [FAO-56 Chapter 6](https://www.fao.org/4/X0490E/x0490e0b.htm): Kc approach and
  grazing-pasture coefficient ranges; 0.85 is a selected constant preset.
- [FAO-56 Chapter 7, Table 19](https://www.fao.org/4/X0490E/x0490e0c.htm): soil-property ranges.
- [FAO-56 Chapter 8](https://www.fao.org/4/X0490E/x0490e0e.htm): root-zone storage,
  pasture rooting-depth ranges, stress adjustment and daily water balance.

Tests also cover water conservation, rooting depth, missing-input holds, freezing,
wind conversion, replay corrections and separation from measured-index results.
Run `python -m pytest -q` and `python tools/sync_engine.py --check` locally.
