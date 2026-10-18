"""Record a cut today on an individual paddock."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .entity import PaddockEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(MarkPaddockCutButton(entry.runtime_data,pid)
                       for pid in entry.runtime_data.store.data["paddocks"])


class MarkPaddockCutButton(PaddockEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "mark_paddock_cut"
    _attr_icon = "mdi:grass"

    def __init__(self, coordinator, pid):
        super().__init__(coordinator,pid,"mark_paddock_cut")

    async def async_press(self):
        cycle = self.coordinator.store.data["paddocks"][self.pid]["cycle"]
        today = datetime.now(ZoneInfo(self.coordinator.config["timezone"])).date()
        if date.fromisoformat(cycle["start_date"]) == today:
            return
        try:
            await self.coordinator.async_start_cycle(self.pid,today,cycle["id"],confirmed=True)
        except (ValueError,KeyError) as error:
            raise HomeAssistantError(str(error)) from error
