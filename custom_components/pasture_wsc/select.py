"""Preferred route for each paddock's default WSC sensor."""
from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .entity import PaddockEntity
from .paddocks import WSC_ROUTES
from .const import SOIL_TYPES


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(entity(entry.runtime_data, pid)
                       for pid in entry.runtime_data.store.data["paddocks"]
                       for entity in (WSCPreferenceSelect, SoilTypeSelect))


class SoilTypeSelect(PaddockEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "soil_type"
    _attr_options = list(SOIL_TYPES)

    def __init__(self, coordinator, pid):
        super().__init__(coordinator, pid, "soil_type")

    @property
    def current_option(self):
        return self.settings.get("soil_type", "unsure")

    async def async_select_option(self, option):
        if option not in SOIL_TYPES:
            raise HomeAssistantError("Choose unsure, sandy, loam or clay")
        await self.coordinator.async_update_paddock(self.pid, {"soil_type": option})


class WSCPreferenceSelect(PaddockEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "wsc_preference"
    _attr_options = list(WSC_ROUTES)

    def __init__(self, coordinator, pid):
        super().__init__(coordinator, pid, "wsc_preference")

    @property
    def current_option(self):
        return self.settings.get("wsc_preference", "primary")

    async def async_select_option(self, option):
        if option not in WSC_ROUTES:
            raise HomeAssistantError("Choose primary or scenario")
        await self.coordinator.async_update_paddock(self.pid, {"wsc_preference": option})
