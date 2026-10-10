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

    async def new_cycle(call):
        entry = hass.config_entries.async_get_entry(call.data["entry_id"])
        if entry is None or entry.domain!=DOMAIN or not getattr(entry,"runtime_data",None):
            raise HomeAssistantError("Pasture WSC entry is not loaded")
        try:
            await entry.runtime_data.async_start_cycle(call.data["paddock_id"],date.fromisoformat(call.data["start_date"]),
                call.data["expected_cycle_id"],confirmed=call.data["confirmed"])
        except (ValueError,KeyError) as error:
            raise HomeAssistantError("Confirm a valid current paddock cycle and start date") from error

    hass.services.async_register(DOMAIN,"start_new_growth_cycle",new_cycle,schema=vol.Schema({
        vol.Required("entry_id"):str,vol.Required("paddock_id"):str,vol.Required("start_date"):str,
        vol.Required("expected_cycle_id"):str,vol.Required("confirmed",default=False):bool}))
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
        await hass.config_entries.async_forward_entry_setups(entry,[Platform.SENSOR,Platform.SWITCH,Platform.NUMBER,Platform.TEXT,Platform.BUTTON])
    except Exception as error:
        _LOGGER.exception("Pasture WSC setup failed; retained archive is preserved")
        await coordinator.async_close()
        raise ConfigEntryNotReady(f"Pasture WSC setup failed: {type(error).__name__}") from error
    return True


async def async_unload_entry(hass,entry):
    from homeassistant.const import Platform
    if await hass.config_entries.async_unload_platforms(entry,[Platform.SENSOR,Platform.SWITCH,Platform.NUMBER,Platform.TEXT,Platform.BUTTON]):
        await entry.runtime_data.async_close()
        return True
    return False
