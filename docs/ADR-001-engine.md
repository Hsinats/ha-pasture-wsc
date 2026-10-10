# ADR 001: Experimental FONSCH engine and interval weather resolution

Status: implemented Phase 1; scientific review required before integration work.
Reviewed 2026-10-10. No Home Assistant entity, config flow, durable store, network
provider adapter, or helper import is implemented in this phase.

## Evidence and implementation identity

Wulfes, R., Nyman, P., Kornher, A. (1999), *Modelling non-structural
carbohydrates in forage grasses with weather data*, Agricultural Systems 61,
1–16, [DOI 10.1016/S0308-521X(99)00028-1](https://doi.org/10.1016/S0308-521X(99)00028-1).
The user supplied `wulfes1999.pdf`; equations on pp.3–8 and the Vigor N40
regrowth column of Table 2 on p.10 were read, and p.7/p.10 were visually checked.
The copyrighted paper is not redistributed in this repository. Before that
attachment arrived, only the publisher's bibliographic record was accessible.
Source PDF SHA-256:
`2e7de43398891badf75719fb09c62e9685b7b82738ee6cb4b3acb552d64a3b09`.

Implementation identity: `fonsch-spec-vigor-regrowth-0.1.0`, input schema 1;
preset `vigor_regrowth_n40_spec_response`. This is the requested equation subset
with the modifications below, not the complete FONSCH growth/water model.

| Component | Paper location | Implemented expression / coefficients |
| --- | --- | --- |
| Photoperiod pchr | Eq.2, p.3; Table 2 | 1 − exp(−0.80 max(0,L−10)) |
| Temperature tchr | Eq.3, p.3; Table 2 | 1 − exp(−0.234 max(0,T−4)) |
| Moisture michr | Eq.4, p.4; Table 2 | clip(1−wi+0.271,0,1) |
| Daily development | Eq.5, p.4 | pchr × tchr × michr |
| SPECHR | Eq.6, p.4 | Sum of daily development, including current date |
| Trend | Eq.7, p.5; Table 2 | 6.195 S^0.993 exp(−0.090 S) |
| Radiation | Eq.8a/b, pp.5–6; Table 2 | 6[1−exp(−0.073 max(0,R−2))] |
| Temperature fluctuation | Eq.9a/b, pp.6–7; Table 2 | 8[1−exp(−0.100 max(0,T−5))], subtracted |
| Moisture fluctuation | Eq.10a/b/c, p.7; Table 2 | 8(wi/0.47−1) OR 8(1−wi/0.47) |
| Total | Eq.12, p.8 | Trend + radiation − temperature + moisture |
| Crop start | §2.3, pp.8–9; Table 2 | cdmlev 20 g/m²; metadata only, not modeled |

Units are L hours, T °C, R MJ/m² per day, WSC percent of dry matter. The paper's
weather file uses J/cm²; conversion is ×0.01 to MJ/m². WSC is not percent fresh
weight. All internal arithmetic uses full precision; no post-hoc WSC clamp.

## Scientific decisions, assumptions and limitations

1. Output label is **Experimental modeled WSC (% dry matter)**. No horse safety,
   grazing authorization, or laminitis thresholds. Calibration was for ryegrass
   swards and management in northern Germany; this Ontario pasture is unvalidated.
   The fitted errors reported in the paper are not an Ontario confidence interval.
2. Table 2 coefficients are verified; zero-below-threshold response and clipping
   michr are explicit specification choices consistent with described 0–1 rates.
   The printed algebra alone does not show all threshold branches.
3. **Moisture discrepancy:** Fig.7 shows Eq.10 responses plateauing at zero above
   mfkc. The requested specification gives unbounded algebra. V1 follows those
   exact requested expressions, flags `spec_moisture_expression_unbounded`, and
   does not claim full fidelity to the figure outside the stress domain.
   Eq.10a is increasing with *wi* and decreasing with *water stress*; Eq.10b is
   the opposite. Enum names refer to the algebra, not an ambiguous drought label.
   Section 3 on p.10 reports generally using Eq.10b, but primary default remains
   unset as requested. Review should decide whether a future version implements
   the paper's plateau and whether Eq.10b is justified for this pasture.
4. wi comes from the external growth/water-balance model cited in Eq.4 and §2.3
   (Torssell et al. 1982; Fagerberg & Nyman 1994). This paper supplies no generic
   VWC-to-wi calibration. A `SoilIndex` requires semantics and explicit compatible
   attestation; that flag does not validate a user's claim. Generic sensor/manual
   moisture remains diagnostic. No water-balance model or arbitrary conversion.
5. Unknown/incompatible/assumed primary wi blocks development and primary WSC.
   An assumed compatible-scale scenario is separate and explicitly enabled.
   No selected moisture-response mode blocks WSC but permits development when wi
   is otherwise suitable. Valid radiation/temperature components remain visible.
6. Replay's start date and zero initial SPECHR are pragmatic reset approximations.
   Actual paper initialization requires a dry-matter threshold. Early reserve
   depletion is outside the paper's modeled period. No crop-start algorithm here.
   GDD is not SPECHR and is not implemented in Phase 1.
7. Paper §2.4 uses previous-day weather for morning samples (except same-morning
   minima) and allows moving averages. V1 uses mean temperature and radiation for
   a single completed local date, labeled by **input day**, without claiming to
   predict a sample at a particular hour. No moving average or inferred lag.
8. Astronomy uses [FAO-56 chapter 3](https://www.fao.org/4/x0490e/x0490e07.htm),
   Eqs.21,23–25,34: geometric horizon, no refraction/elevation correction, 365-day
   harmonic evaluated with civil ordinal day even in leap years. Polar limits are
   handled. This is a documented algorithm choice, not recovered FONSCH code.
9. Opt-in cloud daily scenario is Ra × 0.75 × (1−0.75 C³), C in 0–1. Only Ra is
   sourced to FAO; transmission and cloud attenuation are explicit uncalibrated
   engineering assumptions. No claim of an error distribution or calibrated
   radiation estimate. Requires upstream daylight-weighted cloud coverage.
   Missing cloud returns unavailable unless explicit clear-sky assumption.
   This produces a daily energy total, not an instantaneous irradiance series;
   no nighttime energy is assigned. Polar night total is zero.

## Ingestion and fallback decisions

Resolve each variable independently on a half-open UTC interval timeline whose
bounds come from local civil midnight. Days can be 23/24/25 hours. Historical
source timestamps remain tied to their original dates, zone and units.

Caller-configured ranks determine selection; default quality eligibility is
observed/provider observation. Adapters must distinguish provider observation
from forecast. Estimated, forecast and assumed classes require explicit opt-in.
Suggested ranks: local calibrated observation, secondary observation, provider
estimate, forecast/scenario. No fallback for the entire station.

Each segment picks one eligible fresh source; recovery immediately restores the
higher rank. Deterministic interval resolution needs no debounce in Phase 1;
optional live UI debounce must never change archived observation validity.
Freshness is evaluated at the represented interval, not today's processing time.
Instantaneous readings are held forwards only to the next event or freshness
limit (an explicit zero-order-hold approximation), never backwards. Unknown,
unavailable and invalid events stop the preceding reading. Physical bounds are
engineering rejection policies, not calibration: temperature −90..65 °C,
irradiance 0..1500 W/m², solar interval energy 0..100 MJ/m², precipitation
0..2000 mm, cloud/humidity 0..100%. Device/state classes must be validated by
future HA adapters; this engine requires explicit semantics and supported units.

Solar power interval means are converted to interval totals before ranking
against energy counters/providers. Means are time weighted; energy and rain are
summed. Totals split across source changes/day boundaries use uniform allocation
within the original interval and carry a flag. Measured missing energy is never
extrapolated to a full day. Coverage threshold defaults to 80%; a result passing
that threshold may still be partial and flagged. Use 100% for strict complete
daily energy; the future UI must show coverage and unresolved gaps.

Counters difference only within the same source/unit. Unknown resets, excessive
gaps, invalid states and unit changes discard the affected interval. Explicit
rollover modulus is supported; no guessed rollover. Daily-reset cross-midnight
intervals are discarded; a zero reading at midnight supplies the new baseline.
If that baseline is absent, the engine cannot recover precipitation between
midnight and the first reading. Observations/baselines must persist in Phase 2.
Overlapping records from one source are rejected until corrected/deduplicated;
overlap across sources selects one and never sums both.

Raw values/units, normalized values, timestamp, quality, source, selected intervals,
missing intervals, coverage, fallback proportion and flags are immutable records.
Daily hashes include relevant raw intervals, policy, local date/zone and input
schema; replay hashes include parameters, mode, version and predecessor hash.
Counter conversion returns anomaly flags separately; future adapters must retain
these and original readings (including rejected observations), not just intervals.
No current weather value can fabricate past observations. Missing radiation
blocks WSC; missing L/T/wi blocks SPECHR for that and all later dates until backfill.

## Future HA boundary, storage and review gate

Current guidance reviewed: [config flows](https://developers.home-assistant.io/docs/core/integration/config_flow/),
[data fetching/coordinator](https://developers.home-assistant.io/docs/integration_fetching_data/),
and [integration structure](https://developers.home-assistant.io/docs/creating_integration_file_structure/).
Future layer uses config entries/options/reconfigure and a typed runtime with
DataUpdateCoordinator, supported weather forecast APIs and state-event ingestion.
Weather entities are not assumed to supply irradiance or historical readings.
No HA imports enter this package; timezone database is the only runtime dependency
on Windows. Phase 1 runs standalone rather than appearing as an installable HA
component without working setup/configuration.

Phase 2 must implement durable shared observations/weather summaries separate
from paddock cycles/results; archive by paddock/date/model version and content
hash, preserve raw versions, atomic persistence independent of recorder, and
deterministic replay after corrections. Source-map edits must not change paddock
identity or cycle start. No JSON store/cycle reset UI is pretended implemented now.
Helper migration later requires preview, backup and confirmation; no auto-import.

Review gates before further phases: accepted moisture-index provenance/calibration;
response plateau/mode choice; crop-start approximation; estimate/cloud method;
coverage/fallback eligibility; input-day timing convention. Coefficient verification
does not resolve these scientific limitations.
