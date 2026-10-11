"""UI configuration, options and location reconfiguration."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import logging

try:
    import probatio as vol
except ImportError:  # HA releases before its schema-library migration.
    import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DEFAULTS, DOMAIN
from .settings import paddocks_from_names, settings, validate, validate_source
from .paddocks import DEFAULT_PADDOCK, validate_paddock

_LOGGER = logging.getLogger(__name__)


def location_schema(values):
    return vol.Schema({
        vol.Required("latitude",default=values["latitude"]): selector.NumberSelector(selector.NumberSelectorConfig(min=-90,max=90,mode="box")),
        vol.Required("longitude",default=values["longitude"]): selector.NumberSelector(selector.NumberSelectorConfig(min=-180,max=180,mode="box")),
        vol.Required("elevation",default=values["elevation"]): selector.NumberSelector(selector.NumberSelectorConfig(min=-500,max=9000,mode="box")),
        vol.Required("timezone",default=values["timezone"]): selector.TextSelector(),
    })


def policy_schema(values):
    return vol.Schema({
        vol.Optional("weather_entities",default=values["weather_entities"]): selector.EntitySelector(selector.EntitySelectorConfig(filter={"domain":"weather"},multiple=True)),
        vol.Required("calculation_time",default=values["calculation_time"]): selector.TimeSelector(),
        vol.Required("minimum_coverage",default=values["minimum_coverage"]): selector.NumberSelector(selector.NumberSelectorConfig(min=.01,max=1,step=.01,mode="box")),
        vol.Required("solar_minimum_coverage",default=values["solar_minimum_coverage"]): selector.NumberSelector(selector.NumberSelectorConfig(min=.01,max=1,step=.01,mode="box")),
        **{vol.Required(k,default=values[k]): selector.BooleanSelector() for k in ("allow_estimated","allow_forecast","historical_backfill","estimate_solar","assume_clear_sky")},
        vol.Optional("soil_entity"): selector.EntitySelector(selector.EntitySelectorConfig(filter={"domain":"sensor"})),
        vol.Required("soil_semantics",default=values["soil_semantics"]): selector.TextSelector(),
        vol.Required("soil_freshness",default=values["soil_freshness"]): selector.NumberSelector(selector.NumberSelectorConfig(min=60,max=86400,mode="box")),
    })


class SourceSteps:
    """Same source editor for setup and options; stable source IDs on edits."""
    async def async_step_sources(self, user_input=None):
        steps = ["add_source","edit_source","remove_source"]
        if getattr(self,"_is_options",False):
            steps.append("manage_paddocks")
        return self.async_show_menu(step_id="sources",menu_options=steps+["finish"])

    async def async_step_add_source(self, user_input=None):
        self._edit_id = None
        return await self.async_step_source(user_input)

    async def async_step_edit_source(self, user_input=None):
        if not self._values["sources"]:
            return await self.async_step_sources()
        if user_input:
            self._edit_id = user_input["source_id"]
            return await self.async_step_source()
        return self.async_show_form(step_id="edit_source",data_schema=self._source_choice())

    def _source_choice(self):
        options = [{"value":s["id"],"label":f"{s['variable']}: {s['entity_id']} (rank {s['priority']})"} for s in self._values["sources"]]
        return vol.Schema({vol.Required("source_id"): selector.SelectSelector(selector.SelectSelectorConfig(options=options))})

    async def async_step_remove_source(self, user_input=None):
        if not self._values["sources"]:
            return await self.async_step_sources()
        if user_input:
            self._values["sources"] = [s for s in self._values["sources"] if s["id"] != user_input["source_id"]]
            return await self.async_step_sources()
        return self.async_show_form(step_id="remove_source",data_schema=self._source_choice())

    async def async_step_source(self, user_input=None):
        current = next((s for s in self._values["sources"] if s["id"] == self._edit_id),{})
        errors = {}
        if user_input is not None:
            source = {**user_input,"id":self._edit_id or uuid4().hex}
            try:
                validate_source(source)
            except (ValueError,KeyError):
                errors["base"] = "invalid_source"
                current = source
            else:
                self._values["sources"] = [s for s in self._values["sources"] if s["id"] != source["id"]]+[source]
                return await self.async_step_sources()
        schema = vol.Schema({
            vol.Required("entity_id"): selector.EntitySelector(selector.EntitySelectorConfig(filter={"domain":["sensor","weather"]})),
            vol.Required("variable",default=current.get("variable","temperature")): selector.SelectSelector(selector.SelectSelectorConfig(options=["temperature","irradiance","solar_energy","cloud_cover","precipitation","humidity"])),
            vol.Required("kind",default=current.get("kind","instantaneous")): selector.SelectSelector(selector.SelectSelectorConfig(options=["instantaneous","counter","daily_reset","weather_proxy","weather_observation"])),
            vol.Required("priority",default=current.get("priority",0)): selector.NumberSelector(selector.NumberSelectorConfig(min=0,max=1000,mode="box")),
            vol.Required("freshness",default=current.get("freshness",3600)): selector.NumberSelector(selector.NumberSelectorConfig(min=60,max=86400,mode="box")),
            vol.Required("offset",default=current.get("offset",0)): selector.NumberSelector(selector.NumberSelectorConfig(min=-100,max=100,mode="box")),
            vol.Required("semantics",default=current.get("semantics","")): selector.TextSelector(),
            vol.Optional("unit_override",default=current.get("unit_override","")): selector.TextSelector(),
        })
        return self.async_show_form(step_id="source",data_schema=self.add_suggested_values_to_schema(schema,current),errors=errors)


class PastureWSCConfigFlow(SourceSteps, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._values = deepcopy(DEFAULTS)
        self._edit_id = None

    async def async_step_user(self, user_input=None):
        errors = {}
        defaults = {"latitude":self.hass.config.latitude,"longitude":self.hass.config.longitude,
                    "elevation":self.hass.config.elevation,"timezone":self.hass.config.time_zone}
        if user_input is not None:
            try:
                self._values = validate({**self._values,**user_input})
            except (ValueError,KeyError,ZoneInfoNotFoundError):
                errors["base"] = "invalid_settings"
                defaults.update(user_input)
            else:
                return await self.async_step_weather()
        return self.async_show_form(step_id="user",data_schema=location_schema(defaults),errors=errors)

    async def async_step_weather(self,user_input=None):
        if user_input is not None:
            try:
                self._values = validate({**self._values,**user_input})
            except (ValueError,KeyError):
                return self.async_show_form(step_id="weather",data_schema=policy_schema(self._values),errors={"base":"invalid_settings"})
            return await self.async_step_paddocks()
        return self.async_show_form(step_id="weather",data_schema=policy_schema(self._values))

    async def async_step_paddocks(self,user_input=None):
        errors = {}
        if user_input is not None:
            try:
                today = datetime.now(ZoneInfo(self._values["timezone"])).date()
                start = date.fromisoformat(user_input.get("start_date",today.isoformat()))
                if start > today or (today-start).days > 366:
                    raise ValueError("Select a start date within the past year")
                self._values["paddocks"] = paddocks_from_names(user_input["names"],start)
            except ValueError:
                errors["base"] = "invalid_paddocks"
            else:
                return await self.async_step_sources()
        return self.async_show_form(step_id="paddocks",errors=errors,data_schema=vol.Schema({
            vol.Required("names",default="Summer\nWinter\nBack"):selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            vol.Required("start_date",default=datetime.now(ZoneInfo(self._values["timezone"])).date().isoformat()):selector.DateSelector()}))

    async def async_step_finish(self,user_input=None):
        return self.async_create_entry(title="Pasture WSC",data=validate(self._values))

    async def async_step_reconfigure(self,user_input=None):
        entry = self._get_reconfigure_entry()
        values = settings(entry)
        errors = {}
        if user_input is not None:
            try:
                updated = validate({**values,**user_input})
            except (ValueError,ZoneInfoNotFoundError):
                errors["base"] = "invalid_settings"
            else:
                # Move effective location to data, removing any legacy location options.
                options = {k:v for k,v in entry.options.items() if k not in user_input}
                self.hass.config_entries.async_update_entry(entry,options=options)
                return self.async_update_reload_and_abort(entry,data_updates={k:updated[k] for k in user_input})
        return self.async_show_form(step_id="reconfigure",data_schema=location_schema(values),errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PastureWSCOptionsFlow()


class PastureWSCOptionsFlow(SourceSteps, OptionsFlowWithReload):
    async def async_step_init(self,user_input=None):
        if not hasattr(self,"_values"):
            self._values = settings(self.config_entry)
            self._edit_id = None
            self._is_options = True
        if user_input is not None:
            return await self.async_step_weather_settings(user_input)
        return self.async_show_menu(step_id="init",menu_options=["manage_paddocks","add_paddock","backfill","weather_settings","sources","finish"])

    async def async_step_backfill(self,user_input=None):
        coordinator = self._coordinator()
        today = datetime.now(ZoneInfo(self._values["timezone"])).date()
        starts = [p["cycle"]["start_date"] for p in coordinator.store.data["paddocks"].values()]
        yesterday = today-timedelta(days=1)
        default_start = max(min(starts,default=yesterday.isoformat()),(today-timedelta(days=366)).isoformat())
        errors = {}
        error_detail = ""
        if user_input is not None:
            try:
                await coordinator.async_backfill(date.fromisoformat(user_input["start_date"]),
                    date.fromisoformat(user_input["end_date"]))
            except ValueError as error:
                error_detail = str(error)
                _LOGGER.exception("Pasture WSC manual weather backfill failed: %s",error)
                errors["base"] = "backfill_failed"
            else:
                self._values["historical_backfill"] = True
                return await self.async_step_init()
        return self.async_show_form(step_id="backfill",errors=errors,
            description_placeholders={"error_detail":error_detail},data_schema=vol.Schema({
            vol.Required("start_date",default=(user_input or {}).get("start_date",min(default_start,yesterday.isoformat()))):selector.DateSelector(),
            vol.Required("end_date",default=(user_input or {}).get("end_date",yesterday.isoformat())):selector.DateSelector()}))

    async def async_step_weather_settings(self,user_input=None):
        if user_input is not None:
            try:
                self._values = validate({**self._values, "soil_entity":"", **user_input})
            except (ValueError,KeyError):
                return self.async_show_form(step_id="weather_settings",data_schema=policy_schema(self._values),errors={"base":"invalid_settings"})
            return await self.async_step_sources()
        return self.async_show_form(step_id="weather_settings",data_schema=self.add_suggested_values_to_schema(policy_schema(self._values),self._values))

    def _coordinator(self):
        coordinator = getattr(self.config_entry,"runtime_data",None)
        if coordinator is None:
            raise ValueError("Integration must be loaded to manage paddocks")
        return coordinator

    async def async_step_manage_paddocks(self,user_input=None):
        try:
            coordinator = self._coordinator()
        except ValueError:
            return self.async_abort(reason="integration_not_loaded")
        if user_input is not None:
            self._paddock_id = user_input["paddock_id"]
            self._cycle_id = coordinator.store.data["paddocks"][self._paddock_id]["cycle"]["id"]
            return await self.async_step_paddock_menu()
        options = [{"value":pid,"label":p["settings"]["name"]} for pid,p in coordinator.store.data["paddocks"].items()]
        return self.async_show_form(step_id="manage_paddocks",data_schema=vol.Schema({vol.Required("paddock_id"):
            selector.SelectSelector(selector.SelectSelectorConfig(options=options))}))

    async def async_step_paddock_menu(self,user_input=None):
        return self.async_show_menu(step_id="paddock_menu",menu_options=["paddock_settings","confirm_cycle","cancel_cycle_request","manage_paddocks","finish"])

    async def async_step_paddock_settings(self,user_input=None):
        coordinator = self._coordinator()
        p = coordinator.store.data["paddocks"][self._paddock_id]["settings"]
        errors = {}
        if user_input is not None:
            try:
                await coordinator.async_update_paddock(self._paddock_id,
                    {"moisture_entity":"","notes":"",**user_input})
            except ValueError:
                errors["base"] = "invalid_paddock_settings"
            else:
                return await self.async_step_paddock_menu()
        schema = vol.Schema({
            vol.Required("name",default=p["name"]):selector.TextSelector(),
            vol.Required("enabled",default=p["enabled"]):selector.BooleanSelector(),
            vol.Optional("notes",default=p["notes"]):selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            vol.Required("moisture_kind",default=p["moisture_kind"]):selector.SelectSelector(selector.SelectSelectorConfig(options=["unknown","shared_diagnostic","diagnostic_sensor","calibrated_index"])),
            vol.Optional("moisture_entity"):selector.EntitySelector(selector.EntitySelectorConfig(filter={"domain":"sensor"})),
            vol.Required("moisture_semantics",default=p["moisture_semantics"]):selector.TextSelector(),
            vol.Required("moisture_freshness",default=p["moisture_freshness"]):selector.NumberSelector(selector.NumberSelectorConfig(min=60,max=86400,mode="box")),
            vol.Required("index_compatible",default=p["index_compatible"]):selector.BooleanSelector(),
            vol.Required("moisture_mode",default=p["moisture_mode"]):selector.SelectSelector(selector.SelectSelectorConfig(options=[
                {"value":"unset","label":"Not selected — WSC cannot be calculated"},
                {"value":"wi_over_reference_minus_one","label":"Higher moisture index increases the WSC estimate"},
                {"value":"one_minus_wi_over_reference","label":"Higher moisture index decreases the WSC estimate"},
            ])),
            vol.Required("scenario_enabled",default=p["scenario_enabled"]):selector.BooleanSelector(),
            vol.Required("assumed_wi",default=p["assumed_wi"]):selector.NumberSelector(selector.NumberSelectorConfig(min=0,max=1,step=.01,mode="box")),
            vol.Required("gdd_base",default=p["gdd_base"]):selector.NumberSelector(selector.NumberSelectorConfig(min=-10,max=20,mode="box")),
        })
        return self.async_show_form(step_id="paddock_settings",data_schema=self.add_suggested_values_to_schema(schema,p),errors=errors)

    async def async_step_confirm_cycle(self,user_input=None):
        coordinator = self._coordinator()
        p = coordinator.store.data["paddocks"][self._paddock_id]
        today = datetime.now(ZoneInfo(self._values["timezone"])).date()
        errors = {}
        if user_input is not None:
            try:
                await coordinator.async_start_cycle(self._paddock_id,date.fromisoformat(user_input["start_date"]),
                    self._cycle_id,confirmed=user_input["confirm"],backfill=user_input.get("backfill",False))
            except (ValueError,KeyError):
                errors["base"] = "cycle_confirmation_required"
            else:
                self._values["historical_backfill"] = coordinator.config.get("historical_backfill",False)
                self._cycle_id = p["cycle"]["id"]
                return await self.async_step_paddock_menu()
        return self.async_show_form(step_id="confirm_cycle",errors=errors,
            description_placeholders={"paddock":p["settings"]["name"],"previous_start":p["cycle"]["start_date"]},
            data_schema=vol.Schema({vol.Required("start_date",default=today.isoformat()):selector.DateSelector(),
                                   vol.Required("backfill",default=True):selector.BooleanSelector(),
                                   vol.Required("confirm",default=False):selector.BooleanSelector()}))

    async def async_step_cancel_cycle_request(self,user_input=None):
        await self._coordinator().async_cancel_cycle_request(self._paddock_id)
        return await self.async_step_paddock_menu()

    async def async_step_add_paddock(self,user_input=None):
        errors = {}
        if user_input is not None:
            try:
                today = datetime.now(ZoneInfo(self._values["timezone"])).date()
                await self._coordinator().async_add_paddock(user_input["name"],
                    date.fromisoformat(user_input.get("start_date",today.isoformat())))
            except ValueError:
                errors["base"] = "invalid_paddocks"
            else:
                return await self.async_step_manage_paddocks()
        return self.async_show_form(step_id="add_paddock",errors=errors,data_schema=vol.Schema({
            vol.Required("name"):selector.TextSelector(),
            vol.Required("start_date",default=datetime.now(ZoneInfo(self._values["timezone"])).date().isoformat()):selector.DateSelector()}))

    async def async_step_finish(self,user_input=None):
        # Paddocks are never rewritten by source/policy changes.
        editable = set(DEFAULTS)-{"paddocks"}
        return self.async_create_entry(title="",data={k:deepcopy(self._values[k]) for k in editable})
