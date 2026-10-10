"""Generate consistent English config and entity labels."""
import json
from copy import deepcopy
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
STEPS["paddocks"]["description"] = "Create independently managed paddocks. Each gets a device, results and controls. Initial dates are pragmatic growth-cycle placeholders."
options = {k:deepcopy(v) for k,v in STEPS.items() if k in ("sources","source","edit_source","remove_source")}
options["init"] = {"title":"Pasture WSC configuration","menu_options":{"manage_paddocks":"Manage paddocks","add_paddock":"Add paddock","weather_settings":"Weather settings","sources":"Source mappings","finish":"Save configuration"}}
options["weather_settings"] = deepcopy(STEPS["weather"])
options["sources"]["menu_options"]["manage_paddocks"] = "Manage paddocks"
options["manage_paddocks"] = {"title":"Select paddock","data":{"paddock_id":"Paddock"}}
options["add_paddock"] = {"title":"Add paddock","description":"Save configuration afterward to load its entities.","data":{"name":"Paddock name"}}
options["paddock_menu"] = {"title":"Paddock management","menu_options":{"paddock_settings":"Paddock settings","confirm_cycle":"Start new growth cycle","cancel_cycle_request":"Cancel cycle request","manage_paddocks":"Select another paddock","finish":"Save configuration"}}
options["confirm_cycle"] = {"title":"Confirm new growth cycle","description":"Start a new cycle for {paddock}, replacing the active cycle starting {previous_start}. Previous cycles and results remain archived. Only this paddock is reset. Missing historical inputs remain missing.","data":{"start_date":"New cycle start date","confirm":"Confirm starting a new cycle"}}
options["paddock_settings"] = {"title":"Paddock settings","description":"Settings apply immediately. Save configuration afterward to reload source subscriptions. Generic soil moisture remains diagnostic. A calibrated index requires compatible dimensionless wi and justification. Assumed wi is used only in the explicitly enabled scenario, throughout its cycle.","data":{
    "name":"Paddock name","enabled":"Enable paddock","notes":"Management notes","moisture_kind":"Moisture source type","moisture_entity":"Soil/index sensor","moisture_semantics":"Measurement meaning and calibration","moisture_freshness":"Maximum index freshness (seconds)","index_compatible":"Attest FONSCH-compatible dimensionless index","moisture_mode":"Explicit moisture response expression","moisture_justification":"Scientific justification for index and response","scenario_enabled":"Enable assumed/estimated scenario","assumed_wi":"Scenario assumed wi (0–1)","gdd_base":"Diagnostic GDD base temperature (°C)"}}
ERRORS.update(invalid_paddock_settings="Check paddock name, index compatibility, justification and numeric settings.",cycle_confirmation_required="Confirm the current cycle and a valid start date. Reopen this paddock if its cycle changed.")
SENSOR_NAMES.update({"experimental_wsc":"Experimental WSC","wsc_trend":"WSC daily change","scenario_wsc":"Scenario WSC","scenario_trend":"Scenario WSC daily change","radiation_effect":"FONSCH radiation contribution","temperature_effect":"FONSCH temperature contribution","moisture_effect":"FONSCH moisture contribution","spechr":"Cumulative SPECHR","scenario_spechr":"Scenario cumulative SPECHR","gdd":"Diagnostic growing degree days","scenario_gdd":"Scenario growing degree days","paddock_status":"Paddock model status","scenario_status":"Scenario status","input_quality":"Paddock input quality","history_status":"Development history status","preset":"Model preset","moisture_source":"Moisture source","cycle_id":"Growth cycle ID","reset_status":"New cycle request status","growth_cycle_start":"Growth cycle start","paddock_last_completed_day":"Last completed paddock day"})
DOCUMENT = {"title":"Pasture WSC","config":{"step":STEPS,"error":ERRORS,"abort":{"reconfigure_successful":"Location updated; historical records preserved."}},
            "options":{"step":options,"error":ERRORS},
            "entity":{"sensor":{k:{"name":v} for k,v in SENSOR_NAMES.items()}},
            "services":{"recalculate":{"name":"Recalculate completed weather days","description":"Recompute 1–31 completed dates from retained observations; missing history stays missing.",
                      "fields":{"entry_id":{"name":"Integration entry"},"start_date":{"name":"First local date"},"end_date":{"name":"Last local date"}}}}}
DOCUMENT["options"]["abort"] = {"integration_not_loaded":"Load the integration before managing paddocks."}
for platform, names in {"switch":{"enabled":"Enable paddock","scenario_enabled":"Enable scenario"},"number":{"assumed_wi":"Scenario assumed wi"},"text":{"notes":"Management notes"},"button":{"start_new_growth_cycle":"Request new growth cycle"}}.items():
    DOCUMENT["entity"][platform] = {k:{"name":v} for k,v in names.items()}
DOCUMENT["services"]["start_new_growth_cycle"] = {"name":"Start confirmed growth cycle","description":"Archive the active cycle and start a new cycle for one paddock. Requires explicit confirmation and the current cycle ID.","fields":{k:{"name":v} for k,v in {"entry_id":"Integration entry","paddock_id":"Paddock ID","start_date":"Start date","expected_cycle_id":"Current cycle ID","confirmed":"Confirm new cycle"}.items()}}
for output in (ROOT/"strings.json",ROOT/"translations/en.json"):
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(DOCUMENT,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
