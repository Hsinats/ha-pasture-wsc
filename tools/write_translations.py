"""Generate consistent English config and entity labels."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]/"custom_components/pasture_wsc"
LABELS = {
    "latitude":"Latitude","longitude":"Longitude","elevation":"Elevation (m)","timezone":"Time zone",
    "weather_entities":"Weather providers","calculation_time":"Daily calculation time (configured local time)",
    "minimum_coverage":"Minimum temperature/cloud/humidity daily coverage (0–1)",
    "solar_minimum_coverage":"Minimum daily solar coverage (0–1)",
    "allow_estimated":"Allow provider-derived weather estimates (clearly labeled)",
    "allow_forecast":"Archive and use hourly forecast proxies (clearly labeled)",
    "estimate_solar":"Enable uncalibrated astronomy/cloud solar scenario",
    "assume_clear_sky":"Explicitly assume clear sky for missing daylight cloud coverage",
    "soil_entity":"Optional soil sensor (diagnostic only)","soil_semantics":"Soil measurement meaning/calibration notes",
    "soil_freshness":"Soil freshness (seconds)","names":"Paddock names (one per line)",
    "entity_id":"Source entity","variable":"Measured variable","kind":"Source semantics",
    "priority":"Priority (lower ranks first)","freshness":"Freshness / maximum counter gap (seconds)",
    "offset":"Calibration offset in normalized units (instantaneous sources only)",
    "semantics":"Measurement/calibration notes; attest observed weather only if verified",
    "unit_override":"Explicit unit mapping (blank uses entity unit)","source_id":"Source mapping",
}
STEPS = {
    "user":{"title":"Pasture location","description":"Experimental weather/model diagnostics. No horse-grazing safety decision. Defaults come from Home Assistant."},
    "weather":{"title":"Weather and completeness policies","description":"Weather providers are conservatively labeled estimated. Estimates and forecasts require opt-in. Collection begins now; current values cannot fill yesterday's history. Soil sensors remain diagnostic only."},
    "paddocks":{"title":"Reserve paddock identities","description":"Default names are examples. Stable IDs are created now; growth calculations and confirmed resets arrive in Phase 3. Start dates are pragmatic initialization placeholders."},
    "sources":{"title":"Independent source mappings","menu_options":{"add_source":"Add source","edit_source":"Edit source","remove_source":"Remove mapping","finish":"Save configuration"}},
    "source":{"title":"Weather or station source","description":"Use instantaneous for temperature, irradiance, cloud or humidity; counter/daily_reset for energy or rain. Weather proxy is estimated; weather observation requires verified observation semantics. Changes preserve past records."},
    "edit_source":{"title":"Edit source mapping"},
    "remove_source":{"title":"Remove active mapping","description":"Historical records remain archived."},
    "reconfigure":{"title":"Reconfigure location","description":"Prior timezone/location summaries remain archived under their original context. New boundaries are calculated separately."},
}
FIELDS = {
    "user":["latitude","longitude","elevation","timezone"],
    "weather":["weather_entities","calculation_time","minimum_coverage","solar_minimum_coverage","allow_estimated","allow_forecast","estimate_solar","assume_clear_sky","soil_entity","soil_semantics","soil_freshness"],
    "paddocks":["names"],"source":["entity_id","variable","kind","priority","freshness","offset","semantics","unit_override"],
    "edit_source":["source_id"],"remove_source":["source_id"],"reconfigure":["latitude","longitude","elevation","timezone"],
}
for key,fields in FIELDS.items():
    STEPS[key]["data"] = {field:LABELS[field] for field in fields}
ERRORS = {"invalid_settings":"Check location, timezone, units and policy values.",
          "invalid_source":"Check source entity domain, variable, semantics, units and counter settings.",
          "invalid_paddocks":"Enter distinct, non-empty paddock names, one per line."}
SENSOR_NAMES = {"daylength":"Daylength","temperature":"Daily mean temperature","solar_energy":"Daily solar energy",
                "cloud_cover":"Daily cloud cover","humidity":"Daily humidity","precipitation":"Daily precipitation",
                "photoperiod_factor":"FONSCH photoperiod factor","temperature_factor":"FONSCH temperature factor",
                "moisture_factor":"FONSCH moisture factor","development":"FONSCH daily development factor",
                "model_status":"Model status","weather_status":"Weather status","quality":"Weather quality",
                "last_completed_day":"Last completed model day","last_weather_completed_day":"Last completed weather day",
                "soil_diagnostic":"Soil diagnostic status"}
options = {k:v for k,v in STEPS.items() if k in ("sources","source","edit_source","remove_source")}
options["init"] = STEPS["weather"]
DOCUMENT = {"title":"Pasture WSC","config":{"step":STEPS,"error":ERRORS,"abort":{"reconfigure_successful":"Location updated; historical records preserved."}},
            "options":{"step":options,"error":ERRORS},
            "entity":{"sensor":{k:{"name":v} for k,v in SENSOR_NAMES.items()}},
            "services":{"recalculate":{"name":"Recalculate completed weather days","description":"Recompute 1–31 completed dates from retained observations; missing history stays missing.",
                      "fields":{"entry_id":{"name":"Integration entry"},"start_date":{"name":"First local date"},"end_date":{"name":"Last local date"}}}}}
for output in (ROOT/"strings.json",ROOT/"translations/en.json"):
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(DOCUMENT,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
