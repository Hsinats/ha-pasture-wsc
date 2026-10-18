"""Explicit scenario assumption; never an observed soil sensor."""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from .entity import PaddockEntity


async def async_setup_entry(hass,entry,async_add_entities):
    # Initial moisture remains an internal assumption; retire its numeric UI.
    async_add_entities([])


class AssumedMoistureNumber(PaddockEntity,NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "assumed_wi"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 1.0
    _attr_native_step = .01
    _attr_mode = NumberMode.BOX

    def __init__(self,coordinator,pid):
        super().__init__(coordinator,pid,"assumed_wi")

    @property
    def native_value(self):
        return self.settings["assumed_wi"]

    @property
    def available(self):
        return self.coordinator.last_update_success and self.settings["scenario_enabled"]

    async def async_set_native_value(self,value):
        await self.coordinator.async_update_paddock(self.pid,{"assumed_wi":value})
