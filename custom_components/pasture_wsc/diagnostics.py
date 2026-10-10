"""Redacted diagnostics without raw readings, names, IDs or coordinates."""
from .const import VERSION


async def async_get_config_entry_diagnostics(hass,entry):
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    return {
        "integration_version":VERSION,"model_version":data.get("model_version"),
        "input_version":data.get("input_version"),"day":data.get("day"),
        "status":data.get("model_status"),"weather_status":data.get("weather_status"),
        "last_weather_completed_day":data.get("last_weather_completed_day"),
        "source_count":len(coordinator.sources),"paddock_count":len(coordinator.store.data.get("paddocks",coordinator.config["paddocks"])),
        "paddock_status_counts":{status:sum(p.get("status")==status for p in data.get("paddocks",{}).values())
            for status in sorted({p.get("status","pending") for p in data.get("paddocks",{}).values()})},
        "archived_cycle_count":sum(len(p["archives"]) for p in coordinator.store.data.get("paddocks",{}).values()),
        "observation_count":len(coordinator.store.data["observations"]),
        "stored_day_count":len(coordinator.store.data["daily"]),
        "stored_version_count":sum(len(v) for v in coordinator.store.data["daily"].values()),
        "collector_issue_types":sorted(set(data.get("collector_issues",{}).values())),
        "weather":{k:{"coverage":v["coverage"],"fallback_proportion":v["fallback_proportion"],
                      "flags":v["flags"],"missing_interval_count":len(v["missing"]),
                      "quality_classes":sorted({i["quality"] for i in v["intervals"]})}
                   for k,v in data.get("weather",{}).items()},
    }
