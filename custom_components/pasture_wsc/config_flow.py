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

from .const import DEFAULTS, DOMAIN, SOIL_TYPES
from .settings import paddocks_from_names, settings, validate, validate_source
from .paddocks import DEFAULT_PADDOCK, validate_paddock

_LOGGER = logging.getLogger(__name__)


def soil_type_selector():
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=[{"value":value,"label":value.capitalize()} for value in SOIL_TYPES],mode="dropdown"))


def location_schema(values):
    return vol.Schema({
        vol.Required("latitude",default=values["latitude"]): selector.NumberSelector(selector.NumberSelectorConfig(min=-90,max=90,mode="box")),
        vol.Required("longitude",default=values["longitude"]): selector.NumberSelector(selector.NumberSelectorConfig(min=-180,max=180,mode="box")),
        vol.Required("elevation",default=values["elevation"]): selector.NumberSelector(selector.NumberSelectorConfig(min=-500,max=9000,mode="box")),
        vol.Required("timezone",default=values["timezone"]): selector.TextSelector(),
        vol.Required("soil_type",default=values.get("soil_type", "unsure")): soil_type_selector(),
    })


def policy_schema(values):
    return vol.Schema({
        **{vol.Required(k,default=values[k]): selector.BooleanSelector() for k in ("historical_backfill","estimate_solar","assume_clear_sky")},
        vol.Optional("advanced",default=False):selector.BooleanSelector(),
    })


def weather_schema(values):
    return vol.Schema({
        vol.Optional("weather_entities",default=values["weather_entities"]):selector.EntitySelector(selector.EntitySelectorConfig(filter={"domain":"weather"},multiple=True)),
        **{vol.Required(k,default=values[k]):selector.BooleanSelector() for k in ("allow_estimated","allow_forecast")},
    })


MEASURED_INPUTS = ("temperature","irradiance","precipitation","humidity","wind_speed")


def measured_schema(values):
    fields = {}
    for variable in MEASURED_INPUTS:
        existing = next((s for s in values["sources"] if s["id"] == f"setup_{variable}"),None)
        marker = vol.Optional(variable,default=existing["entity_id"]) if existing else vol.Optional(variable)
        fields[marker] = selector.EntitySelector(selector.EntitySelectorConfig(filter={"domain":"sensor"}))
    fields[vol.Required("rain_kind",default=next((s["kind"] for s in values["sources"] if s["id"] == "setup_precipitation"),"counter"))] = selector.SelectSelector(selector.SelectSelectorConfig(options=[
        {"value":"counter","label":"Cumulative rain counter"},{"value":"daily_reset","label":"Rain total that resets daily"}]))
    marker = vol.Optional("soil_entity",default=values["soil_entity"]) if values["soil_entity"] else vol.Optional("soil_entity")
    fields[marker] = selector.EntitySelector(selector.EntitySelectorConfig(filter={"domain":"sensor"}))
    fields.update(weather_schema(values).schema)
    fields.update(policy_schema(values).schema)
    return vol.Schema(fields)


class SourceSteps:
    """Same source editor for setup and options; stable source IDs on edits."""
    async def async_step_measured_inputs(self,user_input=None):
        if user_input is not None:
            sources = [s for s in self._values["sources"] if s["id"] not in {f"setup_{v}" for v in MEASURED_INPUTS}]
            for variable in MEASURED_INPUTS:
                entity = user_input.get(variable)
                if entity:
                    previous = next((s for s in self._values["sources"] if s["id"] == f"setup_{variable}" and s["entity_id"] == entity),{})
                    sources.append({"priority":0,"freshness":3600,"offset":0,"unit_override":"",
                        "semantics":"User-selected measured input",**previous,
                        "id":f"setup_{variable}","entity_id":entity,"variable":variable,
                        "kind":user_input.get("rain_kind","counter") if variable == "precipitation" else "instantaneous",
                        })
            try:
                policies = {k:v for k,v in user_input.items() if k in DEFAULTS and k not in ("sources","paddocks","soil_type")}
                self._values = validate({**self._values,**policies,"sources":sources,"soil_entity":user_input.get("soil_entity","")})
            except (ValueError,KeyError):
                return self.async_show_form(step_id="measured_inputs",data_schema=measured_schema(self._values),errors={"base":"invalid_settings"})
            if user_input.get("advanced",False):
                return await self.async_step_advanced_policies()
            return await self._after_policies()
        return self.async_show_form(step_id="measured_inputs",data_schema=measured_schema(self._values))

    async def _weather_page(self):
        return await (self.async_step_weather_settings() if getattr(self,"_is_options",False) else self.async_step_weather())

    async def async_step_soil_details(self,user_input=None):
        if user_input is not None:
            try:
                self._values = validate({**self._values,**user_input})
            except (ValueError,KeyError):
                return self.async_show_form(step_id="soil_details",errors={"base":"invalid_settings"},data_schema=self._soil_schema())
            return await self._weather_page()
        return self.async_show_form(step_id="soil_details",data_schema=self._soil_schema())

    def _soil_schema(self):
        return vol.Schema({
            vol.Required("soil_freshness",default=self._values["soil_freshness"]):selector.NumberSelector(selector.NumberSelectorConfig(min=60,max=86400,mode="box")),
        })

    async def async_step_policies(self,user_input=None):
        if user_input is not None:
            advanced = user_input.get("advanced",False)
            try:
                self._values = validate({**self._values,**{k:v for k,v in user_input.items() if k != "advanced"}})
            except (ValueError,KeyError):
                return self.async_show_form(step_id="policies",data_schema=policy_schema(self._values),errors={"base":"invalid_settings"})
            if advanced:
                return await self.async_step_advanced_policies()
            return await self._after_policies()
        return self.async_show_form(step_id="policies",data_schema=policy_schema(self._values))

    async def _after_policies(self):
        return await (self.async_step_init() if getattr(self,"_is_options",False) else self.async_step_paddocks())

    async def async_step_advanced_policies(self,user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self._values = validate({**self._values,**user_input})
            except (ValueError,KeyError):
                errors["base"] = "invalid_settings"
            else:
                return await self._after_policies()
        return self.async_show_form(step_id="advanced_policies",errors=errors,data_schema=vol.Schema({
            **({vol.Required("soil_freshness",default=self._values["soil_freshness"]):selector.NumberSelector(selector.NumberSelectorConfig(min=60,max=86400,mode="box"))} if self._values["soil_entity"] else {}),
            vol.Required("calculation_time",default=self._values["calculation_time"]):selector.TimeSelector(),
            **{vol.Required(k,default=self._values[k]):selector.NumberSelector(selector.NumberSelectorConfig(min=.01,max=1,step=.01,mode="box"))
               for k in ("minimum_coverage","solar_minimum_coverage")},
        }))
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
            vol.Required("variable",default=current.get("variable","temperature")): selector.SelectSelector(selector.SelectSelectorConfig(options=["temperature","irradiance","solar_energy","cloud_cover","precipitation","humidity","wind_speed"])),
            vol.Required("kind",default=current.get("kind","instantaneous")): selector.SelectSelector(selector.SelectSelectorConfig(options=["instantaneous","counter","daily_reset","weather_proxy","weather_observation"])),
            vol.Required("priority",default=current.get("priority",0)): selector.NumberSelector(selector.NumberSelectorConfig(min=0,max=1000,mode="box")),
            vol.Required("freshness",default=current.get("freshness",3600)): selector.NumberSelector(selector.NumberSelectorConfig(min=60,max=86400,mode="box")),
            vol.Required("offset",default=current.get("offset",0)): selector.NumberSelector(selector.NumberSelectorConfig(min=-100,max=100,mode="box")),
            vol.Required("semantics",default=current.get("semantics","User-selected source; verify measurement meaning")): selector.TextSelector(),
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
                return await self.async_step_measured_inputs()
        return self.async_show_form(step_id="user",data_schema=location_schema(defaults),errors=errors)

    async def async_step_weather(self,user_input=None):
        if user_input is not None:
            try:
                self._values = validate({**self._values,**user_input})
            except (ValueError,KeyError):
                return self.async_show_form(step_id="weather",data_schema=weather_schema(self._values),errors={"base":"invalid_settings"})
            return await self.async_step_policies()
        return self.async_show_form(step_id="weather",data_schema=weather_schema(self._values))

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
        return self.async_show_menu(step_id="init",menu_options=["manage_paddocks","add_paddock","weather_settings","backfill","sources","finish"])

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
        return await self.async_step_measured_inputs(user_input)

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
            return await self.async_step_paddock_menu()
        options = [{"value":pid,"label":p["settings"]["name"]} for pid,p in coordinator.store.data["paddocks"].items()]
        return self.async_show_form(step_id="manage_paddocks",data_schema=vol.Schema({vol.Required("paddock_id"):
            selector.SelectSelector(selector.SelectSelectorConfig(options=options))}))

    async def async_step_paddock_menu(self,user_input=None):
        return self.async_show_menu(step_id="paddock_menu",menu_options=["paddock_settings","manage_paddocks","finish"])

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
            vol.Required("soil_type",default=p.get("soil_type","unsure")):soil_type_selector(),
            vol.Required("root_depth",default=p.get("root_depth",.5)):selector.NumberSelector(selector.NumberSelectorConfig(min=.1,max=3,step=.1,mode="box")),
            vol.Required("crop_coefficient",default=p.get("crop_coefficient",.85)):selector.NumberSelector(selector.NumberSelectorConfig(min=.1,max=1.5,step=.05,mode="box")),
            vol.Required("wind_height",default=p.get("wind_height",10)):selector.NumberSelector(selector.NumberSelectorConfig(min=.5,max=100,step=.5,mode="box")),
            vol.Required("enabled",default=p["enabled"]):selector.BooleanSelector(),
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
            vol.Required("carbohydrate_low_cutoff",default=p.get("carbohydrate_low_cutoff",8.0)):selector.NumberSelector(selector.NumberSelectorConfig(min=.1,max=99.9,step=.1,mode="box")),
            vol.Required("carbohydrate_high_cutoff",default=p.get("carbohydrate_high_cutoff",12.0)):selector.NumberSelector(selector.NumberSelectorConfig(min=.1,max=100,step=.1,mode="box")),
            vol.Required("gdd_base",default=p["gdd_base"]):selector.NumberSelector(selector.NumberSelectorConfig(min=-10,max=20,mode="box")),
        })
        return self.async_show_form(step_id="paddock_settings",data_schema=self.add_suggested_values_to_schema(schema,p),errors=errors)

    async def async_step_add_paddock(self,user_input=None):
        errors = {}
        if user_input is not None:
            try:
                today = datetime.now(ZoneInfo(self._values["timezone"])).date()
                await self._coordinator().async_add_paddock(user_input["name"],
                    date.fromisoformat(user_input.get("start_date",today.isoformat())),
                    soil_type=user_input.get("soil_type","unsure"))
            except ValueError:
                errors["base"] = "invalid_paddocks"
            else:
                return await self.async_step_manage_paddocks()
        return self.async_show_form(step_id="add_paddock",errors=errors,data_schema=vol.Schema({
            vol.Required("name"):selector.TextSelector(),
            vol.Required("soil_type",default="unsure"):soil_type_selector(),
            vol.Required("start_date",default=datetime.now(ZoneInfo(self._values["timezone"])).date().isoformat()):selector.DateSelector()}))

    async def async_step_finish(self,user_input=None):
        # Paddocks are never rewritten by source/policy changes.
        editable = set(DEFAULTS)-{"paddocks"}
        return self.async_create_entry(title="",data={k:deepcopy(self._values[k]) for k in editable})
