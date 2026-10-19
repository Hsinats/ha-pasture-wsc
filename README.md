# Pasture WSC

A Home Assistant integration that estimates pasture grass sugar levels from local weather data.

## Purpose

Follow changes in estimated pasture water-soluble carbohydrates (WSC) and compare
paddocks on your Home Assistant dashboard. Built to support pasture monitoring for
horses prone to laminitis.

These experimental estimates are not measurements or a grazing-safety assessment.
Use forage testing and veterinary advice for feeding and grazing decisions.

## Features

- Estimated WSC percentage of dry matter, daily change, and configurable Low / Medium / High bands.
- Multiple paddocks with separate soil settings, cutting dates and growth cycles.
- Inputs from on-property sensors or existing Home Assistant weather integrations.
- Optional weather-based solar and soil water estimates; no dedicated soil moisture sensor required.
- Rainfall totals and status sensors showing missing data and assumptions.
- Retained history, recalculation and backfill from local Home Assistant recorder history.
- Configuration through the Home Assistant UI; no YAML required.

## Setup

1. Copy `custom_components/pasture_wsc` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant, then add **Pasture WSC** under **Settings → Devices & services → Add integration**.
3. Select your weather inputs, add your paddocks, and enable any estimates you want to use.

See the [setup and technical guide](docs/guide.md) for detailed configuration.

## Science

The integration implements the **FONSCH model** from Wulfes et al. (1999), using
temperature, solar radiation, day length, soil water availability and development
through the regrowth cycle to estimate grass WSC.

Optional soil water estimation uses **FAO-56 Penman–Monteith evapotranspiration** and
a root-zone water balance driven by rainfall and weather. Its output is an
**unvalidated proxy** for the original FONSCH soil water input. See the
[soil water model notes](docs/fao56/README.md) for assumptions.

The model was developed for specific forage grasses and has not been validated
against our pasture. WSC includes fructans; the integration does not estimate
starch or total nonstructural carbohydrates (NSC).

Default bands are **Low below 8%, Medium from 8% to below 12%, and High at 12% or above**,
all on a dry-matter basis. These are application choices, not validated safety thresholds.
The 8% cutoff leaves a nominal allowance for unmeasured starch relative to a 10% NSC
target; actual starch and model error are unknown. **Low does not mean safe to graze.**
Existing paddocks retain their saved cutoffs.

## References

1. Wulfes, R., Nyman, P., & Kornher, A. (1999). *Modelling non-structural carbohydrates in forage grasses with weather data.* [Paper](https://doi.org/10.1016/S0308-521X%2899%2900028-1).
2. Allen, R. G., Pereira, L. S., Raes, D., & Smith, M. (1998). *Crop Evapotranspiration: Guidelines for Computing Crop Water Requirements.* [FAO Irrigation and Drainage Paper 56](https://www.fao.org/4/X0490E/X0490E00.htm).
3. Durham et al. (2019). *ECEIM consensus statement on equine metabolic syndrome.* [Consensus statement](https://pmc.ncbi.nlm.nih.gov/articles/PMC6430910/).
4. University of Minnesota Extension. *Understanding your hay analysis.* [WSC, starch and NSC guidance](https://extension.umn.edu/agriculture/animals-and-livestock/horse/understanding-your-hay-analysis).
