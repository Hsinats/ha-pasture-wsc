"""Persistent management notes."""
from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from .entity import PaddockEntity


async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities(PaddockNotes(entry.runtime_data,pid) for pid in entry.runtime_data.store.data["paddocks"])


class PaddockNotes(PaddockEntity,TextEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "notes"
    _attr_native_max = 255

    def __init__(self,coordinator,pid):
        super().__init__(coordinator,pid,"notes")

    @property
    def native_value(self):
        return self.settings["notes"]

    async def async_set_value(self,value):
        await self.coordinator.async_update_paddock(self.pid,{"notes":value})
