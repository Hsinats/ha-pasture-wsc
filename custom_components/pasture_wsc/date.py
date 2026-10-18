"""Editable growth-cycle start dates on paddock devices."""
from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .entity import PaddockEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(GrowthCycleDate(entry.runtime_data, pid)
                       for pid in entry.runtime_data.store.data["paddocks"])


class GrowthCycleDate(PaddockEntity, DateEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "growth_cycle_start"

    def __init__(self, coordinator, pid):
        super().__init__(coordinator, pid, "growth_cycle_start")

    @property
    def native_value(self):
        cycle = self.coordinator.store.data["paddocks"][self.pid]["cycle"]
        return date.fromisoformat(cycle["start_date"])

    async def async_set_value(self, value):
        cycle = self.coordinator.store.data["paddocks"][self.pid]["cycle"]
        if value == date.fromisoformat(cycle["start_date"]):
            return
        try:
            await self.coordinator.async_start_cycle(
                self.pid, value, cycle["id"], confirmed=True)
        except (ValueError, KeyError) as error:
            raise HomeAssistantError(str(error)) from error
