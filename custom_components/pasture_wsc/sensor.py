"""Shared completed-day sensors; no paddock/WSC entities in Phase 2."""
from dataclasses import dataclass
from datetime import date

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .entity import PaddockEntity


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
            result["collector_issue_count"] = len(data.get("collector_issues",{}))
            result["collector_issue_types"] = sorted(set(data.get("collector_issues",{}).values()))[:20]
        return result


PADDOCK_SENSORS = (
    *(PastureSensorDescription(key=k,translation_key=k,native_unit_of_measurement="%") for k in
      ("experimental_wsc","wsc_trend","scenario_wsc","scenario_trend","radiation_effect","temperature_effect","moisture_effect")),
    *(PastureSensorDescription(key=k,translation_key=k) for k in
      ("spechr","scenario_spechr","development","moisture_factor")),
    *(PastureSensorDescription(key=k,translation_key=k,native_unit_of_measurement="°C·d") for k in ("gdd","scenario_gdd")),
    *(PastureSensorDescription(key=k,translation_key=k,entity_category=EntityCategory.DIAGNOSTIC) for k in
      ("paddock_status","scenario_status","input_quality","history_status","preset","moisture_source","cycle_id","reset_status")),
    PastureSensorDescription(key="growth_cycle_start",translation_key="growth_cycle_start",device_class=SensorDeviceClass.DATE,entity_category=EntityCategory.DIAGNOSTIC),
    PastureSensorDescription(key="paddock_last_completed_day",translation_key="paddock_last_completed_day",device_class=SensorDeviceClass.DATE,entity_category=EntityCategory.DIAGNOSTIC),
)


class PaddockSensor(PaddockEntity,SensorEntity):
    def __init__(self,coordinator,pid,description):
        super().__init__(coordinator,pid,description.key)
        self.entity_description = description

    @property
    def native_value(self):
        key = self.entity_description.key
        p = self.paddock
        primary,scenario = p.get("primary",{}),p.get("scenario",{})
        if key in ("experimental_wsc","development","moisture_factor","moisture_effect","spechr"):
            return primary.get(key)
        if key == "wsc_trend":
            return primary.get("trend")
        if key.startswith("scenario_") and key != "scenario_status" and key != "scenario_gdd":
            return scenario.get({"scenario_wsc":"experimental_wsc","scenario_trend":"trend","scenario_spechr":"spechr"}[key])
        if key in ("radiation_effect","temperature_effect"):
            return p.get("weather_effects",{}).get(key,primary.get(key))
        if key in ("gdd","scenario_gdd"):
            return p.get(key)
        if key == "paddock_status":
            return p.get("status","pending")
        if key == "scenario_status":
            return p.get(key,"off")
        if key == "input_quality":
            return "observed_or_provider" if p.get("status")=="ready_experimental" else "incomplete_or_assumed"
        if key == "history_status":
            return "incomplete" if p.get("history_gap") else "awaiting_data" if not primary else "complete_development_history"
        if key == "preset":
            return self.settings["preset"]
        if key == "moisture_source":
            return self.settings["moisture_kind"]
        if key == "cycle_id":
            return p.get("cycle",{}).get("id")
        if key == "reset_status":
            return "confirmation_requested" if p.get("reset_requested") else "no_request"
        value = p.get("cycle",{}).get("start_date") if key=="growth_cycle_start" else p.get("last_completed_day")
        return date.fromisoformat(value) if value else None

    @property
    def extra_state_attributes(self):
        p = self.paddock
        return {"day":p.get("day"),"paddock_id":self.pid,"cycle_id":p.get("cycle",{}).get("id"),
            "model_version":p.get("model_version"),"experimental":True,
            "wsc_basis":"percent_of_dry_matter",
            "timezone":p.get("cycle",{}).get("timezone"),"warnings":p.get("warnings",[])[:20],
            "scenario_enabled":self.settings["scenario_enabled"],"assumed_wi":self.settings["assumed_wi"] if self.settings["scenario_enabled"] else None,
            "moisture_mode":self.settings["moisture_mode"],"soil_coverage":p.get("soil",{}).get("coverage"),
            "gdd_base_c":self.settings["gdd_base"],"gdd_is_not_spechr":True,
            "weather_quality":p.get("weather_quality",[]),"source_data_hash":p.get("input_hash"),
            "scenario_warnings":p.get("scenario",{}).get("warnings",[])[:20]}
