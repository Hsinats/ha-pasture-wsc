"""Versioned HA Store, independent of recorder; no silent corrupt-store reset."""
from copy import deepcopy
from datetime import datetime, timezone
import asyncio

from .const import DOMAIN, STORE_VERSION


class PastureStore:
    def __init__(self,hass,entry_id,backend=None):
        if backend is None:
            from homeassistant.helpers.storage import Store
            backend = Store(hass,STORE_VERSION,f"{DOMAIN}.{entry_id}",atomic_writes=True,
                            serialize_in_event_loop=False)
        self.backend = backend
        self.loaded = False
        self._observation_keys = set()
        self.lock = asyncio.Lock()
        self.data = {"schema":STORE_VERSION,"started_at":datetime.now(timezone.utc).isoformat(),
                     "observations":[],"forecasts":{},"daily":{},"paddock_archive":{},"settings_revisions":[],
                     "collector_issues":{},"soil":None,"paddocks":{},"paddock_results":{},"soil_observations":[]}

    async def load(self):
        self.loaded = False
        stored = await self.backend.async_load()
        if stored is not None:
            if stored.get("schema") == STORE_VERSION:
                for key in ("paddocks","paddock_results","soil_observations"):
                    stored.setdefault(key,deepcopy(self.data[key]))
            if stored.get("schema") != STORE_VERSION or any(key not in stored for key in self.data):
                raise ValueError("Unsupported or incomplete Pasture WSC storage; preserve file and restore backup")
            self.data = stored
        self._observation_keys = {(r["source_key"],r["timestamp"]) for r in self.data["observations"]}
        self.loaded = True

    async def save(self):
        if not self.loaded:
            # Cleanup after a failed load must never overwrite an unread archive.
            return
        async with self.lock:
            await self.backend.async_save(deepcopy(self.data))

    def observation(self,item):
        # Repeated state-change/report callbacks and periodic reads are idempotent.
        key = (item["source_key"],item["timestamp"])
        if key in self._observation_keys:
            return False
        self._observation_keys.add(key)
        self.data["observations"].append(item)
        return True

    def forecasts(self,records):
        for item in records:
            key = f"{item['source']}|{item['start']}"
            old = self.data["forecasts"].get(key)
            # Only future interval updates reach this method; completed periods stay frozen.
            if old is None or item["timestamp"] > old["timestamp"]:
                self.data["forecasts"][key] = item

    def daily(self,key,record):
        versions = self.data["daily"].setdefault(key,[])
        if versions and versions[-1]["hash"] == record["hash"]:
            return False
        versions.append(record)
        return True

    def paddock_result(self,record):
        key = f"{record['paddock_id']}|{record['cycle_id']}|{record['day']}|{record['model_version']}"
        versions = self.data["paddock_results"].setdefault(key,[])
        if versions and versions[-1]["hash"] == record["hash"]:
            return False
        versions.append(record)
        return True
