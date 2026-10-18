"""Persistent management notes."""
from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from .entity import PaddockEntity


async def async_setup_entry(hass,entry,async_add_entities):
    # Retired UI control; retained stored notes are left intact.
    async_add_entities([])


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
