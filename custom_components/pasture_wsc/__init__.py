"""Home Assistant setup boundary; engine imports remain independent."""
from typing import TYPE_CHECKING
import logging

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from .coordinator import PastureCoordinator
    PastureConfigEntry = ConfigEntry[PastureCoordinator]


async def async_setup(hass,config):
    from datetime import date
    try:
        import probatio as vol
    except ImportError:
        import voluptuous as vol
    from homeassistant.exceptions import HomeAssistantError
    from .const import DOMAIN

    async def recalculate(call):
        entry = hass.config_entries.async_get_entry(call.data["entry_id"])
        if entry is None or entry.domain != DOMAIN or not getattr(entry,"runtime_data",None):
            raise HomeAssistantError("Pasture WSC entry is not loaded")
        try:
            start,end = date.fromisoformat(call.data["start_date"]),date.fromisoformat(call.data["end_date"])
            await entry.runtime_data.async_recalculate(start,end)
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error

    hass.services.async_register(DOMAIN,"recalculate",recalculate,schema=vol.Schema({
        vol.Required("entry_id"):str,vol.Required("start_date"):str,vol.Required("end_date"):str}))

    async def backfill(call):
        entry = hass.config_entries.async_get_entry(call.data["entry_id"])
        if entry is None or entry.domain!=DOMAIN or not getattr(entry,"runtime_data",None):
            raise HomeAssistantError("Pasture WSC entry is not loaded")
        try:
            await entry.runtime_data.async_backfill(date.fromisoformat(call.data["start_date"]),
                date.fromisoformat(call.data["end_date"]))
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error

    hass.services.async_register(DOMAIN,"backfill_weather",backfill,schema=vol.Schema({
        vol.Required("entry_id"):str,vol.Required("start_date"):str,vol.Required("end_date"):str}))

    async def new_cycle(call):
        entry = hass.config_entries.async_get_entry(call.data["entry_id"])
        if entry is None or entry.domain!=DOMAIN or not getattr(entry,"runtime_data",None):
            raise HomeAssistantError("Pasture WSC entry is not loaded")
        try:
            await entry.runtime_data.async_start_cycle(call.data["paddock_id"],date.fromisoformat(call.data["start_date"]),
                call.data["expected_cycle_id"],confirmed=call.data["confirmed"],backfill=call.data.get("backfill",False))
        except (ValueError,KeyError) as error:
            raise HomeAssistantError("Confirm a valid current paddock cycle and start date") from error

    hass.services.async_register(DOMAIN,"start_new_growth_cycle",new_cycle,schema=vol.Schema({
        vol.Required("entry_id"):str,vol.Required("paddock_id"):str,vol.Required("start_date"):str,
        vol.Required("expected_cycle_id"):str,vol.Required("confirmed",default=False):bool,
        vol.Optional("backfill",default=False):bool}))
    return True


async def async_setup_entry(hass,entry):
    from homeassistant.const import Platform
    from homeassistant.exceptions import ConfigEntryNotReady
    from .coordinator import PastureCoordinator
    from .settings import settings
    coordinator = PastureCoordinator(hass,entry,settings(entry))
    entry.runtime_data = coordinator
    try:
        await coordinator.async_start()
        # Retire controls replaced by the editable date without leaving unavailable entities.
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(hass)
        for pid in coordinator.store.data["paddocks"]:
            for platform, key in (("sensor", "growth_cycle_start"), ("sensor", "reset_status"),
                                  ("button", "start_new_growth_cycle"), ("text", "notes"), ("number", "assumed_wi")):
                entity_id = registry.async_get_entity_id(platform, "pasture_wsc", f"{entry.entry_id}_{pid}_{key}")
                if entity_id is not None:
                    registry.async_remove(entity_id)
        await hass.config_entries.async_forward_entry_setups(entry,[Platform.SENSOR,Platform.SWITCH,Platform.DATE,Platform.SELECT,Platform.BUTTON])
    except Exception as error:
        _LOGGER.exception("Pasture WSC setup failed; retained archive is preserved")
        await coordinator.async_close()
        raise ConfigEntryNotReady(f"Pasture WSC setup failed: {type(error).__name__}") from error
    return True


async def async_unload_entry(hass,entry):
    from homeassistant.const import Platform
    if await hass.config_entries.async_unload_platforms(entry,[Platform.SENSOR,Platform.SWITCH,Platform.DATE,Platform.SELECT,Platform.BUTTON]):
        await entry.runtime_data.async_close()
        return True
    return False
