"""Generate consistent English config and entity labels."""
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]/"custom_components/pasture_wsc"
LABELS = {
    "soil_type":"Soil type",
    "latitude":"Latitude","longitude":"Longitude","elevation":"Elevation (m)","timezone":"Time zone",
    "weather_entities":"Weather providers","calculation_time":"Daily calculation time (configured local time)",
    "minimum_coverage":"Minimum temperature/cloud/humidity daily coverage (0–1)",
    "solar_minimum_coverage":"Minimum daily solar coverage (0–1)",
    "allow_estimated":"Allow provider-derived weather estimates (clearly labeled)",
    "allow_forecast":"Archive and use hourly forecast proxies (clearly labeled)",
    "historical_backfill":"Fill missing past weather from local Home Assistant history",
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
for step in ("user", "reconfigure"):
    STEPS[step]["data"]["soil_type"] = LABELS["soil_type"]
STEPS["weather"]["data"]["historical_backfill"] = LABELS["historical_backfill"]
STEPS["weather"]["description"] += " Historical backfill reads the configured weather entities and sensors from Home Assistant recorder. It makes no external requests. Cloud history can support the enabled solar estimate."
STEPS["paddocks"]["data"]["start_date"] = "Last cut"
ERRORS = {"invalid_settings":"Check location, timezone, units and policy values.",
          "invalid_source":"Check source entity domain, variable, semantics, units and counter settings.",
          "invalid_paddocks":"Enter distinct, non-empty paddock names and a growth start date within the past year, no later than today."}
SENSOR_NAMES = {"daylength":"Daylength","temperature":"Daily mean temperature","solar_energy":"Daily solar energy",
                "cloud_cover":"Daily cloud cover","humidity":"Daily humidity","precipitation":"Daily precipitation",
                "photoperiod_factor":"FONSCH photoperiod factor","temperature_factor":"FONSCH temperature factor",
                "moisture_factor":"FONSCH moisture factor","development":"FONSCH daily development factor",
                "model_status":"Model status","weather_status":"Weather status","quality":"Weather quality",
                "last_completed_day":"Last completed model day","last_weather_completed_day":"Last completed weather day",
                "soil_diagnostic":"Soil diagnostic status"}
STEPS["paddocks"]["description"] = "Choose an approximate cut or grazing date within the past year. It initially applies to all paddocks; each date can be changed later. Enable historical backfill in weather settings to retrieve weather before installation."
options = {k:deepcopy(v) for k,v in STEPS.items() if k in ("sources","source","edit_source","remove_source")}
options["init"] = {"title":"Pasture WSC configuration","menu_options":{"manage_paddocks":"Manage paddocks","add_paddock":"Add paddock","weather_settings":"Weather settings","sources":"Source mappings","finish":"Save configuration"}}
options["init"]["menu_options"]["backfill"] = "Backfill weather"
options["backfill"] = {"title":"Backfill weather","description":"Read the configured weather entities and sensors from Home Assistant's local recorder for 1–366 completed days. No external requests are made. Only retained history can be recovered. Enable the solar estimate in weather settings to use recorded cloud cover when radiation was not measured. This also enables automatic local backfill for later gaps.\n\n{error_detail}","data":{"start_date":"First date","end_date":"Last completed date"}}
options["weather_settings"] = deepcopy(STEPS["weather"])
options["sources"]["menu_options"]["manage_paddocks"] = "Manage paddocks"
options["manage_paddocks"] = {"title":"Select paddock","data":{"paddock_id":"Paddock"}}
options["add_paddock"] = {"title":"Add paddock","description":"Choose the last cut date within the past year to start the regrowth calculation. Save configuration afterward to load its entities. Enable historical backfill in weather settings to retrieve earlier weather.","data":{"name":"Paddock name","start_date":"Last cut"}}
options["add_paddock"]["data"]["soil_type"] = "Soil type"
options["paddock_menu"] = {"title":"Paddock management","menu_options":{"paddock_settings":"Paddock settings","manage_paddocks":"Select another paddock","finish":"Save configuration"}}
options["paddock_settings"] = {"title":"Paddock settings","description":"Settings apply immediately. Carbohydrate cutoffs define descriptive water-soluble carbohydrate levels, not animal-specific safety limits. Save configuration afterward to reload source subscriptions. Generic soil moisture remains diagnostic. A calibrated index requires compatible dimensionless wi. Assumed wi is used only in the explicitly enabled scenario, throughout its cycle.","data":{
    "name":"Paddock name","enabled":"Enable paddock","notes":"Management notes","moisture_kind":"Moisture source type","moisture_entity":"Soil/index sensor","moisture_semantics":"Measurement meaning and calibration","moisture_freshness":"Maximum index freshness (seconds)","index_compatible":"Attest FONSCH-compatible dimensionless index","moisture_mode":"How the moisture index affects the WSC estimate","scenario_enabled":"Enable assumed/estimated scenario","assumed_wi":"Scenario assumed wi (0–1)","gdd_base":"Diagnostic GDD base temperature (°C)","carbohydrate_low_cutoff":"Low-to-medium carbohydrate cutoff (% dry matter)","carbohydrate_high_cutoff":"Medium-to-high carbohydrate cutoff (% dry matter)"}}
ERRORS.update(invalid_paddock_settings="Check paddock name, index compatibility and numeric settings. The low carbohydrate cutoff must be less than the high cutoff.")
ERRORS["backfill_failed"] = "Local weather history could not be imported. See the reason above or the Home Assistant logs."
SENSOR_NAMES.update({"carbohydrate_level":"Pasture carbohydrate level","wsc":"Water-soluble carbohydrates","experimental_wsc":"Experimental water-soluble carbohydrates","wsc_trend":"Water-soluble carbohydrate daily change","scenario_wsc":"Scenario water-soluble carbohydrates","scenario_trend":"Scenario water-soluble carbohydrate daily change","radiation_effect":"FONSCH radiation contribution","temperature_effect":"FONSCH temperature contribution","moisture_effect":"FONSCH moisture contribution","spechr":"Cumulative SPECHR","scenario_spechr":"Scenario cumulative SPECHR","gdd":"Diagnostic growing degree days","scenario_gdd":"Scenario growing degree days","paddock_status":"Paddock model status","scenario_status":"Scenario status","input_quality":"Paddock input quality","history_status":"Development history status","preset":"Model preset","moisture_source":"Moisture source","cycle_id":"Growth cycle ID","paddock_last_completed_day":"Last completed paddock day"})
SENSOR_NAMES.update({
    "rain_accumulation": "Rain accumulation (since last cut)",
    "rain_accumulation_measured": "Rain accumulation (measured)",
    "rain_accumulation_estimated": "Rain accumulation (estimated)",
    "soil_moisture_measured": "Soil moisture (measured)",
    "soil_moisture_estimated": "Soil moisture (estimated)",
    "scenario_moisture_effect": "Moisture contribution (estimated inputs)",
    "scenario_moisture_factor": "Moisture factor (estimated inputs)",
    "scenario_development": "Daily development (estimated inputs)",
    "paddock_status":"Calculation status",
    "input_quality":"WSC method",
    "moisture_source":"Moisture method",
    "paddock_last_completed_day":"Calculated through",
    "history_status":"Development history (measured inputs)",
    "measured_model_status":"Model status (measured inputs)",
    "data_gaps":"Data gaps",
    "carbohydrate_level": "WSC level (auto)",
    "wsc": "WSC (auto)",
    "experimental_wsc": "WSC (measured inputs)",
    "wsc_trend": "WSC daily change (auto)",
    "scenario_wsc": "WSC (estimated inputs)",
    "scenario_trend": "WSC daily change (estimated inputs)",
    "spechr": "SPECHR (measured inputs)",
    "scenario_spechr": "SPECHR (estimated inputs)",
    "gdd": "GDD (measured inputs)",
    "scenario_gdd": "GDD (estimated inputs)",
    "radiation_effect": "Solar contribution (weather inputs)",
    "temperature_effect": "Temperature contribution (weather inputs)",
    "moisture_effect": "Moisture contribution (measured inputs)",
    "photoperiod_factor": "Daylength factor (calculated)",
    "temperature_factor": "Temperature factor (weather inputs)",
    "moisture_factor": "Moisture factor (measured inputs)",
    "development": "Daily development (measured inputs)",
    "scenario_status": "Model status (estimated inputs)",
})
options["paddock_settings"]["data"].update({
    "root_depth":"Effective rooting depth (m)",
    "crop_coefficient":"Pasture water-use coefficient (Kc)",
    "wind_height":"Weather wind measurement height (m)",
    "soil_type": "Soil type",
    "scenario_enabled": "Enable estimated inputs model",
    "assumed_wi": "Initial / fallback moisture index (0–1)",
    "gdd_base": "GDD base temperature (°C)",
    "carbohydrate_low_cutoff": "Low-to-medium WSC cutoff (% dry matter)",
    "carbohydrate_high_cutoff": "Medium-to-high WSC cutoff (% dry matter)",
})
options["paddock_settings"]["data"].pop("notes",None)
options["paddock_settings"]["data"].pop("assumed_wi",None)
options["paddock_settings"]["description"] = (
    "Settings apply immediately. WSC cutoffs define descriptive levels, not animal-specific safety limits. "
    "Save configuration afterward to reload source subscriptions. Generic soil moisture remains diagnostic. "
    "A calibrated index requires compatible dimensionless wi. The estimated inputs model can use measured "
    "weather, estimates and forecasts. Moisture prefers a compatible measured index, then a rainfall/drying "
    "FAO-56 estimate using soil type, rooting depth and pasture Kc. Check wind height against your provider. "
    "Defaults and missing wind/humidity are assumptions reported by the moisture sensor. An internal starting "
    "moisture level seeds the estimate; missing weather holds the previous level. The estimate is not sensor moisture percent."
)
SETUP_PAGES = {
    "measured_inputs":{"title":"Measured inputs (optional)",
        "description":"Connect any physical sensors you have, or leave them empty and continue to weather estimates and forecasts. Sunlight expects irradiance (W/m²); rain expects a cumulative counter or daily-reset total. Rain counter type only applies if a rain sensor is selected. A generic soil moisture sensor is diagnostic only; it does not become a compatible model index automatically. Advanced source mappings are preserved and can be edited under Source mappings.",
        "data":{"temperature":"Temperature sensor","irradiance":"Sunlight sensor (irradiance)",
            "precipitation":"Rain gauge","rain_kind":"Rain counter type","humidity":"Humidity sensor",
            "wind_speed":"Wind sensor","soil_entity":"Soil moisture sensor (diagnostic only)"}},
    "soil_details":{"title":"Optional soil sensor details",
        "description":"This setting applies only to the soil sensor you selected. One-hour freshness is a starting default: increase it if the sensor normally reports less often. This sensor is diagnostic; compatible model indices are configured per paddock.",
        "data":{"soil_freshness":"Reading expires after (seconds)"}},
    "weather":{"title":"Weather provider & forecasts",
        "description":"Choose your weather integration. Current weather estimates and hourly forecasts can both supply estimated inputs. You can skip the provider when using your own sensors. Forecast collection begins now and cannot recover yesterday's predictions. Methods are shown on the paddock's WSC method and Moisture method diagnostics.",
        "data":{"weather_entities":"Weather provider (estimates and forecasts)",
            "allow_estimated":"Use current weather estimates","allow_forecast":"Use hourly forecasts"}},
    "policies":{"title":"Data gaps & fallbacks",
        "description":"Use saved Home Assistant history where available. Without a sunlight sensor, cloud-based sunlight is an approximation. Assuming clear sky when cloud data is missing can overestimate sunlight; leave it off unless you want that fallback. Missing moisture weather holds the previous level and is reported under Data gaps. Advanced settings contain calculation time and coverage thresholds; the defaults are practical settings, not accuracy guarantees.",
        "data":{"historical_backfill":"Import recorded weather history","estimate_solar":"Estimate sunlight from cloud cover",
            "assume_clear_sky":"Assume clear sky if cloud data is missing","advanced":"Review advanced settings"}},
    "advanced_policies":{"title":"Advanced data settings",
        "description":"00:15 calculates the previous day in your configured time zone; pending data is retried. Weather coverage 0.8 requires 80% of a day's temperature, humidity, cloud, rain and wind intervals. Solar coverage 1.0 requires complete daily coverage. These are operational thresholds, not validated accuracy limits. Lower thresholds do not reconstruct missing sunlight or rain. Live rain totals instead expose their actual coverage.",
        "data":{"calculation_time":"Daily calculation time","minimum_coverage":"Minimum daily weather coverage (0–1)",
            "solar_minimum_coverage":"Minimum daily sunlight coverage (0–1)"}},
}
for step,page in SETUP_PAGES.items():
    STEPS[step] = deepcopy(page)
    options[step] = deepcopy(page)
combined = deepcopy(SETUP_PAGES["measured_inputs"])
combined["title"] = "Inputs & fallbacks"
combined["description"] = "Choose any measured sensors first, then your weather provider and fallbacks below. Physical sensors are optional. Sunlight expects irradiance (W/m²); match rain counter type to your gauge. Weather estimates and forecasts remain labelled estimated. Cloud-based sunlight is approximate; leave clear-sky fallback off unless you want missing cloud data treated as clear. Recorded history can fill retained past inputs. Default timing and coverage are ready to use; advanced settings are optional."
combined["data"].update(SETUP_PAGES["weather"]["data"])
combined["data"].update(SETUP_PAGES["policies"]["data"])
combined["data"].update({
    "allow_estimated":"Use current weather estimates",
    "allow_forecast":"Use hourly weather forecasts",
    "historical_backfill":"Fill gaps using recorded weather history",
    "estimate_solar":"Estimate sunlight from cloud cover",
    "assume_clear_sky":"Assume clear skies when cloud data is missing",
    "advanced":"Show advanced settings",
    "soil_entity":"Soil moisture sensor (for reference only)",
})
combined["description"] += " An ordinary soil moisture reading is shown for reference only: its percentage is not the moisture index used by the WSC model. Estimated soil moisture instead uses rainfall, weather and your paddock's soil type."
STEPS["measured_inputs"] = deepcopy(combined)
options["measured_inputs"] = deepcopy(combined)
options["advanced_policies"]["data"]["soil_freshness"] = "Soil reading expires after (seconds)"
STEPS["advanced_policies"]["data"]["soil_freshness"] = "Soil reading expires after (seconds)"
options["weather_settings"] = deepcopy(combined)
options["init"]["menu_options"].update({"measured_inputs":"Measured inputs",
    "weather_settings":"Weather provider & forecasts","policies":"Data gaps & fallbacks","sources":"Advanced source mappings"})
options["init"]["menu_options"]["weather_settings"] = "Inputs & fallbacks"
# Remove implementation-oriented wording from the advanced source editor too.
for steps in (STEPS,options):
    steps["source"]["description"] = "Map a measured sensor or a weather attribute. Choose instantaneous for temperature, sunlight irradiance, humidity, cloud or wind. Choose counter/daily reset for rain or accumulated solar energy. A weather observation must represent verified observations; otherwise use weather proxy. Existing records are preserved."
DOCUMENT = {"title":"Pasture WSC","config":{"step":STEPS,"error":ERRORS,"abort":{"reconfigure_successful":"Location updated; historical records preserved."}},
            "options":{"step":options,"error":ERRORS},
            "entity":{"sensor":{k:{"name":v} for k,v in SENSOR_NAMES.items()}},
            "services":{"recalculate":{"name":"Recalculate completed weather days","description":"Recompute 1–31 completed dates from retained observations; missing history stays missing.",
                      "fields":{"entry_id":{"name":"Integration entry"},"start_date":{"name":"First local date"},"end_date":{"name":"Last local date"}}}}}
DOCUMENT["entity"]["sensor"]["carbohydrate_level"]["state"] = {
    "low": "Low", "medium": "Medium", "high": "High",
}
for key,states in {
    "paddock_status":{"disabled":"Disabled","ready_measured":"Ready with measured inputs",
        "ready_estimated":"Ready with estimates","waiting_first_day":"Waiting for first completed day",
        "choose_moisture_response":"Choose moisture response in settings","missing_history":"Missing development history",
        "waiting_for_soil":"Waiting for compatible soil data","waiting_weather":"Waiting for weather data"},
    "input_quality":{"measured":"Measured inputs","estimated":"Estimated inputs","no_result":"No result yet"},
    "moisture_source":{"measured":"Measured index","fao_estimate":"FAO estimate",
        "held_assumption":"Assumed moisture held during data gaps","starting_assumption":"Assumed starting level",
        "not_calculated":"Not calculated yet","no_sensor_configured":"No soil sensor configured","waiting_for_soil":"Waiting for compatible soil data"},
    "scenario_status":{"off":"Disabled","scenario_available":"Ready with estimates",
        "scenario_pending":"Waiting for inputs","awaiting_first_completed_day":"Waiting for first completed day"},
}.items():
    DOCUMENT["entity"]["sensor"][key]["state"] = states
DOCUMENT["options"]["abort"] = {"integration_not_loaded":"Load the integration before managing paddocks."}
for platform, names in {"switch":{"enabled":"Enable paddock","scenario_enabled":"Enable estimated inputs model"},"date":{"growth_cycle_start":"Last cut"}}.items():
    DOCUMENT["entity"][platform] = {k:{"name":v} for k,v in names.items()}
DOCUMENT["entity"]["select"] = {"wsc_preference": {
    "name": "Preferred WSC method",
    "state": {"primary": "Measured inputs", "scenario": "Estimated inputs"},
}}
DOCUMENT["entity"]["select"]["soil_type"] = {
    "name":"Soil type",
    "state":{"unsure":"Unsure","sandy":"Sandy","loam":"Loam","clay":"Clay"},
}
DOCUMENT["entity"]["button"] = {"mark_paddock_cut":{"name":"Mark paddock cut"}}
DOCUMENT["services"]["start_new_growth_cycle"] = {"name":"Start confirmed growth cycle","description":"Archive the active cycle and start a new cycle for one paddock. Requires explicit confirmation and the current cycle ID.","fields":{k:{"name":v} for k,v in {"entry_id":"Integration entry","paddock_id":"Paddock ID","start_date":"Start date","expected_cycle_id":"Current cycle ID","confirmed":"Confirm new cycle"}.items()}}
DOCUMENT["services"]["start_new_growth_cycle"]["fields"]["backfill"] = {"name":"Backfill weather from the selected date"}
DOCUMENT["services"]["backfill_weather"] = {"name":"Backfill completed weather days","description":"Import 1–366 completed days from local Home Assistant recorder and enable automatic local backfill. No external requests. Retained live readings take priority.","fields":{k:{"name":v} for k,v in {"entry_id":"Integration entry","start_date":"First local date","end_date":"Last local date"}.items()}}
for output in (ROOT/"strings.json",ROOT/"translations/en.json"):
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(DOCUMENT,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
