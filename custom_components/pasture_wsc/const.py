"""Integration constants."""
DOMAIN = "pasture_wsc"
VERSION = "0.2.0"
STORE_VERSION = 1
MAX_BACKFILL_DAYS = 31
VARIABLES = ("temperature", "solar_energy", "cloud_cover", "precipitation", "humidity")
DEFAULTS = {
    "weather_entities": [], "sources": [], "calculation_time": "00:15:00",
    "minimum_coverage": 0.8, "solar_minimum_coverage": 1.0,
    "allow_estimated": False, "allow_forecast": False,
    "estimate_solar": False, "assume_clear_sky": False,
    "soil_entity": "", "soil_semantics": "Unknown; diagnostic only",
    "soil_freshness": 3600, "paddocks": [],
}
