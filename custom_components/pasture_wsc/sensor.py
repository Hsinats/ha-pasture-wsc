"""Shared completed-day sensors; no paddock/WSC entities in Phase 2."""
from dataclasses import dataclass
from datetime import date

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION


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
    async_add_entities(PastureSensor(entry.runtime_data,description) for description in SENSORS)


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
            result["warnings"] = ["experimental_unvalidated","soil_diagnostic_only","paddock_model_phase_3"]
            result["collector_issue_count"] = len(data.get("collector_issues",{}))
            result["collector_issue_types"] = sorted(set(data.get("collector_issues",{}).values()))[:20]
        return result
