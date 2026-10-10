"""Request confirmation; pressing this button never changes the cycle."""
from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from .entity import PaddockEntity


async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities(NewCycleButton(entry.runtime_data,pid) for pid in entry.runtime_data.store.data["paddocks"])


class NewCycleButton(PaddockEntity,ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "start_new_growth_cycle"

    def __init__(self,coordinator,pid):
        super().__init__(coordinator,pid,"start_new_growth_cycle")

    async def async_press(self):
        await self.coordinator.async_request_cycle(self.pid)
