"""Paddock enabled and explicit scenario controls."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from .entity import PaddockEntity


async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities(PaddockSwitch(entry.runtime_data,pid,key) for pid in entry.runtime_data.store.data["paddocks"]
                       for key in ("enabled","scenario_enabled"))


class PaddockSwitch(PaddockEntity,SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self,coordinator,pid,key):
        super().__init__(coordinator,pid,key)
        self.key = key
        self._attr_translation_key = key

    @property
    def is_on(self):
        return self.settings[self.key]

    async def async_turn_on(self,**kwargs):
        await self.coordinator.async_update_paddock(self.pid,{self.key:True})

    async def async_turn_off(self,**kwargs):
        await self.coordinator.async_update_paddock(self.pid,{self.key:False})
