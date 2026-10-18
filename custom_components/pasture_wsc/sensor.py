"""Shared weather and per-paddock model sensors."""
from dataclasses import dataclass, replace
from datetime import date

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .entity import PaddockEntity
from .paddocks import selected_wsc, carbohydrate_level, diagnostic_summary


@dataclass(frozen=True,kw_only=True)
class PastureSensorDescription(SensorEntityDescription):
    weather_key: str | None = None


SENSORS = (
    PastureSensorDescription(key="daylength",translation_key="daylength",native_unit_of_measurement="h"),
    PastureSensorDescription(key="temperature",translation_key="temperature",weather_key="temperature",native_unit_of_measurement="°C",device_class=SensorDeviceClass.TEMPERATURE),
    PastureSensorDescription(key="solar_energy",translation_key="solar_energy",weather_key="solar_energy",native_unit_of_measurement="MJ/m²"),
    PastureSensorDescription(key="cloud_cover",translation_key="cloud_cover",weather_key="cloud_cover",native_unit_of_measurement="%"),
    PastureSensorDescription(key="humidity",translation_key="humidity",weather_key="humidity",native_unit_of_measurement="%",device_class=SensorDeviceClass.HUMIDITY),
    PastureSensorDescription(key="precipitation",translation_key="precipitation",weather_key="precipitation",native_unit_of_measurement="mm"),
    *(PastureSensorDescription(key=k,translation_key=k,entity_category=EntityCategory.DIAGNOSTIC)
      for k in ("photoperiod_factor","temperature_factor","moisture_factor","development","model_status","weather_status","quality")),
    PastureSensorDescription(key="last_completed_day",translation_key="last_completed_day",device_class=SensorDeviceClass.DATE,entity_category=EntityCategory.DIAGNOSTIC),
    PastureSensorDescription(key="last_weather_completed_day",translation_key="last_weather_completed_day",device_class=SensorDeviceClass.DATE,entity_category=EntityCategory.DIAGNOSTIC),
    PastureSensorDescription(key="soil_diagnostic",translation_key="soil_diagnostic",entity_category=EntityCategory.DIAGNOSTIC),
)


# Keep precision stable for each quantity, including when a reading is pending.
FRACTION_SENSORS = {"photoperiod_factor", "temperature_factor", "moisture_factor", "development"}
FRACTION_SENSORS |= {"soil_moisture_measured", "soil_moisture_estimated"}
FRACTION_SENSORS |= {"scenario_moisture_factor", "scenario_development"}
NUMERIC_SENSORS = FRACTION_SENSORS | {
    "rain_accumulation",
    "rain_accumulation_measured", "rain_accumulation_estimated",
    "daylength", "temperature", "solar_energy", "cloud_cover", "humidity", "precipitation",
    "wsc", "experimental_wsc", "wsc_trend", "scenario_wsc", "scenario_trend",
    "radiation_effect", "temperature_effect", "moisture_effect",
    "scenario_moisture_effect",
    "spechr", "scenario_spechr", "gdd", "scenario_gdd",
}
COMPLETED_DAY_SENSORS = {"last_completed_day", "last_weather_completed_day", "paddock_last_completed_day"}
DISABLED_DEFAULT_SENSORS = COMPLETED_DAY_SENSORS | {
    "cycle_id", "preset", "history_status", "scenario_status", "measured_model_status",
    "photoperiod_factor", "temperature_factor", "moisture_factor", "development",
    "scenario_moisture_factor", "scenario_development",
    "radiation_effect", "temperature_effect", "moisture_effect", "scenario_moisture_effect",
    "experimental_wsc", "scenario_wsc", "scenario_trend",
    "spechr", "scenario_spechr", "gdd", "scenario_gdd", "rain_accumulation",
}


def presentation(description):
    changes = {}
    options = {
        "paddock_status":["disabled","ready_measured","ready_estimated","waiting_first_day","choose_moisture_response","missing_history","waiting_for_soil","waiting_weather"],
        "input_quality":["measured","estimated","no_result"],
        "moisture_source":["measured","fao_estimate","held_assumption","starting_assumption","not_calculated","no_sensor_configured","waiting_for_soil"],
        "scenario_status":["off","scenario_available","scenario_pending","awaiting_first_completed_day"],
    }
    if description.key in options:
        changes.update(device_class=SensorDeviceClass.ENUM,options=options[description.key])
    if description.key in NUMERIC_SENSORS:
        changes["suggested_display_precision"] = 3 if description.key in FRACTION_SENSORS else 1
    if description.key in DISABLED_DEFAULT_SENSORS:
        changes["entity_registry_enabled_default"] = False
    if description.key == "paddock_last_completed_day":
        changes["entity_registry_enabled_default"] = True
    return replace(description, **changes)


SENSORS = tuple(presentation(description) for description in SENSORS)


async def async_setup_entry(hass,entry,async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([*(PastureSensor(coordinator,description) for description in SENSORS),
        *(PaddockSensor(coordinator,pid,d) for pid in coordinator.store.data["paddocks"] for d in PADDOCK_SENSORS)])


class PastureSensor(CoordinatorEntity,SensorEntity):
    _attr_has_entity_name = True

    def __init__(self,coordinator,description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._attr_device_info = {"identifiers":{(DOMAIN,coordinator.entry.entry_id)},"name":"Pasture WSC",
                                  "manufacturer":"Pasture WSC","model":"Experimental weather diagnostics","sw_version":VERSION}

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if self.entity_description.weather_key:
            return data.get("weather",{}).get(key,{}).get("value")
        if key == "quality":
            return data.get("weather_status","pending_weather")
        if key == "soil_diagnostic":
            soil = data.get("soil")
            return "unknown" if not soil else soil["status"]
        value = data.get(key)
        if key in ("last_completed_day","last_weather_completed_day"):
            return date.fromisoformat(value) if value else None
        return value

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        result = {"day":data.get("day"),"timezone":data.get("timezone"),
                  "model_version":data.get("model_version"),"input_version":data.get("input_version"),
                  "experimental":True}
        key = self.entity_description.weather_key
        if key:
            summary = data.get("weather",{}).get(key,{})
            intervals = summary.get("intervals",[])
            anomalies = {flag for source,flags in data.get("anomalies",{}).items()
                         if data.get("source_variables",{}).get(source) == key for flag in flags}
            result.update({"coverage":summary.get("coverage"),"fallback_proportion":summary.get("fallback_proportion"),
                           "source":sorted({data.get("source_entities",{}).get(i["source"],i["source"]) for i in intervals})[:12],
                           "quality_class":sorted({i["quality"] for i in intervals}),
                           "timestamp":max((i["timestamp"] for i in intervals),default=None),
                           "units":summary.get("unit"),"warnings":sorted(set(summary.get("flags",[]))|anomalies)[:20],
                           "missing_interval_count":len(summary.get("missing",[])),"partial_value":summary.get("partial_value"),
                           "source_data_hash":summary.get("source_data_hash")})
        if self.entity_description.key == "soil_diagnostic":
            soil = data.get("soil") or {}
            result.update({"value":soil.get("value"),"units":soil.get("unit"),"timestamp":soil.get("reported"),
                           "semantics":soil.get("semantics","Unknown"),"fonsch_compatible":False})
        if self.entity_description.key in ("model_status","quality","weather_status"):
            result["warnings"] = ["experimental_unvalidated","soil_diagnostic_only","development_is_per_paddock"]
            result["last_completed_day"] = data.get("last_completed_day")
            result["last_weather_completed_day"] = data.get("last_weather_completed_day")
            result["collector_issue_count"] = len(data.get("collector_issues",{}))
            result["collector_issue_types"] = sorted(set(data.get("collector_issues",{}).values()))[:20]
        return result


PADDOCK_SENSORS = (
    *(PastureSensorDescription(key=k,translation_key=k,native_unit_of_measurement="mm",
                              state_class=SensorStateClass.MEASUREMENT)
      for k in ("rain_accumulation_measured","rain_accumulation_estimated")),
    PastureSensorDescription(key="rain_accumulation",translation_key="rain_accumulation",
                             native_unit_of_measurement="mm",state_class=SensorStateClass.MEASUREMENT),
    *(PastureSensorDescription(key=k,translation_key=k,state_class=SensorStateClass.MEASUREMENT)
      for k in ("soil_moisture_measured", "soil_moisture_estimated")),
    PastureSensorDescription(key="carbohydrate_level",translation_key="carbohydrate_level",
                             device_class=SensorDeviceClass.ENUM,options=["low", "medium", "high"]),
    *(PastureSensorDescription(key=k,translation_key=k,native_unit_of_measurement="%") for k in
      ("wsc","experimental_wsc","wsc_trend","scenario_wsc","scenario_trend","radiation_effect","temperature_effect","moisture_effect","scenario_moisture_effect")),
    *(PastureSensorDescription(key=k,translation_key=k,state_class=SensorStateClass.MEASUREMENT)
      for k in ("spechr","scenario_spechr")),
    *(PastureSensorDescription(key=k,translation_key=k) for k in ("development","moisture_factor")),
    *(PastureSensorDescription(key=k,translation_key=k,state_class=SensorStateClass.MEASUREMENT)
      for k in ("scenario_moisture_factor","scenario_development")),
    *(PastureSensorDescription(key=k,translation_key=k,native_unit_of_measurement="°C·d") for k in ("gdd","scenario_gdd")),
    *(PastureSensorDescription(key=k,translation_key=k,entity_category=EntityCategory.DIAGNOSTIC) for k in
      ("paddock_status","scenario_status","input_quality","history_status","preset","moisture_source","cycle_id","measured_model_status","data_gaps")),
    PastureSensorDescription(key="paddock_last_completed_day",translation_key="paddock_last_completed_day",device_class=SensorDeviceClass.DATE,entity_category=EntityCategory.DIAGNOSTIC),
)


PADDOCK_SENSORS = tuple(presentation(description) for description in PADDOCK_SENSORS)


class PaddockSensor(PaddockEntity,SensorEntity):
    def __init__(self,coordinator,pid,description):
        super().__init__(coordinator,pid,description.key)
        self.entity_description = description

    @property
    def available(self):
        if self.entity_description.key in ("wsc", "carbohydrate_level"):
            return self.coordinator.last_update_success and selected_wsc(self.paddock, self.settings)[1] is not None
        return self.coordinator.last_update_success

    @property
    def native_value(self):
        key = self.entity_description.key
        p = self.paddock
        if key in ("rain_accumulation_measured","rain_accumulation_estimated"):
            return p.get("live_rain",{}).get(key.removeprefix("rain_accumulation_"),{}).get("value",0.0)
        if key == "rain_accumulation":
            return p.get("rain_accumulation",{}).get("value")
        if key == "soil_moisture_measured":
            return p.get("soil",{}).get("measured_value")
        if key == "soil_moisture_estimated":
            return p.get("estimated_soil",{}).get("value")
        if key == "carbohydrate_level":
            return carbohydrate_level(p, self.settings)
        if key == "wsc":
            return selected_wsc(p, self.settings)[1]
        primary,scenario = p.get("primary",{}),p.get("scenario",{})
        if key in ("experimental_wsc","development","moisture_factor","moisture_effect","spechr"):
            return primary.get(key)
        if key == "wsc_trend":
            return p.get("daily_change")
        if key == "scenario_trend":
            return p.get("scenario_daily_change")
        if key == "scenario_moisture_effect":
            return scenario.get("moisture_effect")
        if key in ("scenario_moisture_factor", "scenario_development"):
            return scenario.get(key.removeprefix("scenario_"))
        if key.startswith("scenario_") and key != "scenario_status" and key != "scenario_gdd":
            return scenario.get({"scenario_wsc":"experimental_wsc","scenario_trend":"trend","scenario_spechr":"spechr"}[key])
        if key in ("radiation_effect","temperature_effect"):
            return p.get("weather_effects",{}).get(key,primary.get(key))
        if key in ("gdd","scenario_gdd"):
            return p.get(key)
        if key == "paddock_status":
            return diagnostic_summary(p,self.settings)["calculation_status"]
        if key == "measured_model_status":
            return p.get("status","pending")
        if key == "data_gaps":
            return diagnostic_summary(p,self.settings)["data_gaps"]
        if key == "scenario_status":
            return p.get(key,"off")
        if key == "input_quality":
            return diagnostic_summary(p,self.settings)["wsc_method"]
        if key == "history_status":
            return "incomplete" if p.get("history_gap") else "awaiting_data" if not primary else "complete_development_history"
        if key == "preset":
            return self.settings["preset"]
        if key == "moisture_source":
            return diagnostic_summary(p,self.settings)["moisture_method"]
        if key == "cycle_id":
            return p.get("cycle",{}).get("id")
        value = diagnostic_summary(p,self.settings)["calculated_through"]
        return date.fromisoformat(value) if value else None

    @property
    def extra_state_attributes(self):
        p = self.paddock
        if self.entity_description.key in ("paddock_status","input_quality","moisture_source","paddock_last_completed_day","data_gaps"):
            return {**diagnostic_summary(p,self.settings),"raw_measured_status":p.get("status"),
                    "raw_estimated_status":p.get("scenario_status"),"experimental":True}
        if self.entity_description.key in ("rain_accumulation_measured","rain_accumulation_estimated"):
            route = self.entity_description.key.removeprefix("rain_accumulation_")
            return {"cycle_id":p.get("cycle_id"),**p.get("live_rain",{}).get(route,{})}
        if self.entity_description.key == "rain_accumulation":
            return {"day":p.get("day"),"cycle_id":p.get("cycle_id"),
                    **p.get("rain_accumulation",{})}
        if self.entity_description.key in ("soil_moisture_measured", "soil_moisture_estimated"):
            measured = self.entity_description.key == "soil_moisture_measured"
            details = p.get("soil" if measured else "estimated_soil",{})
            return {"day":p.get("day"),"selected_moisture_method":p.get("selected_moisture_method"),
                    "experimental":True,**details}
        if self.entity_description.key in ("wsc", "carbohydrate_level"):
            route, value = selected_wsc(p, self.settings)
            result = p.get(route, {}) if route else {}
            scenario = route == "scenario"
            attributes = {
                "selected_route": route,
                "preferred_route": self.settings.get("wsc_preference", "primary"),
                "fallback_used": route is not None and route != self.settings.get("wsc_preference", "primary"),
                "day": p.get("day"),
                "experimental": True,
                "wsc_basis": "percent_of_dry_matter",
                "warnings": result.get("warnings", [])[:20],
                "source_data_hash": p.get("scenario_input_hash" if scenario else "input_hash"),
                "history_gap": p.get("scenario_history_gap" if scenario else "history_gap"),
                "assumed_wi": self.settings["assumed_wi"] if scenario else None,
                "selected_moisture_method": p.get("selected_moisture_method"),
                "moisture_estimate_warnings": p.get("estimated_soil",{}).get("flags",[]),
            }
            if self.entity_description.key == "carbohydrate_level":
                attributes.update({
                    "estimated_percentage": value,
                    "low_cutoff_percent": self.settings.get("carbohydrate_low_cutoff", 8.0),
                    "high_cutoff_percent": self.settings.get("carbohydrate_high_cutoff", 12.0),
                    "classification_basis": "descriptive_wsc_bands",
                })
            return attributes
        attributes = {"day":p.get("day"),"paddock_id":self.pid,"cycle_id":p.get("cycle",{}).get("id"),
            "model_version":p.get("model_version"),"experimental":True,
            "wsc_basis":"percent_of_dry_matter",
            "timezone":p.get("cycle",{}).get("timezone"),"warnings":p.get("warnings",[])[:20],
            "scenario_enabled":self.settings["scenario_enabled"],"assumed_wi":self.settings["assumed_wi"] if self.settings["scenario_enabled"] else None,
            "moisture_mode":self.settings["moisture_mode"],"soil_coverage":p.get("soil",{}).get("coverage"),
            "gdd_base_c":self.settings["gdd_base"],"gdd_is_not_spechr":True,
            "weather_quality":p.get("weather_quality",[]),"source_data_hash":p.get("input_hash"),
            "scenario_warnings":p.get("scenario",{}).get("warnings",[])[:20],
            "calculated_cycle_start":p.get("calculated_cycle_start"),
            "scenario_days":p.get("scenario_days"),
            "scenario_valid_development_days":p.get("scenario_valid_development_days"),
            "scenario_missing_development_days":p.get("scenario_missing_development_days",[]),
            "scenario_history_gap":p.get("scenario_history_gap"),
            "scenario_source_data_hash":p.get("scenario_input_hash")}
        attributes["selected_moisture_method"] = p.get("selected_moisture_method")
        attributes["moisture_estimate_warnings"] = p.get("estimated_soil",{}).get("flags",[])

        if self.entity_description.key in ("paddock_status", "history_status"):
            attributes["last_completed_day"] = p.get("last_completed_day")
        return attributes
