"""Stable paddock device/entity identity shared by all platforms."""
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, VERSION


class PaddockEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self,coordinator,pid,key):
        super().__init__(coordinator)
        self.pid = pid
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{pid}_{key}"
        name = coordinator.store.data["paddocks"][pid]["settings"]["name"]
        self._attr_device_info = {"identifiers":{(DOMAIN,f"{coordinator.entry.entry_id}_{pid}")},
            "name":name,"manufacturer":"Pasture WSC","model":"Experimental paddock model","sw_version":VERSION,
            "via_device":(DOMAIN,coordinator.entry.entry_id)}

    @property
    def paddock(self):
        return (self.coordinator.data or {}).get("paddocks",{}).get(self.pid,{})

    @property
    def settings(self):
        return self.coordinator.store.data["paddocks"][self.pid]["settings"]
