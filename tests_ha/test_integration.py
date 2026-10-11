"""Tests against HA APIs, separate from locally executable contract doubles."""
from copy import deepcopy
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.config_entries import SOURCE_USER, SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import FlowResultType

from custom_components.pasture_wsc.const import DEFAULTS,DOMAIN
from custom_components.pasture_wsc.settings import paddocks_from_names
from datetime import date


def entry_data():
    return {**deepcopy(DEFAULTS),"latitude":43.7,"longitude":-79.4,"elevation":100,
            "timezone":"America/Toronto","paddocks":paddocks_from_names("Summer\nWinter\nBack",date(2026,6,1))}


@pytest.mark.asyncio
async def test_flow_creates_three_paddocks(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN,context={"source":SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"],{k:entry_data()[k] for k in ("latitude","longitude","elevation","timezone")})
    assert result["step_id"] == "weather"
    policy = {k:entry_data()[k] for k in ("weather_entities","calculation_time","minimum_coverage","solar_minimum_coverage",
                                        "allow_estimated","allow_forecast","historical_backfill","estimate_solar","assume_clear_sky","soil_semantics","soil_freshness")}
    result = await hass.config_entries.flow.async_configure(result["flow_id"],policy)
    assert result["step_id"] == "paddocks"
    result = await hass.config_entries.flow.async_configure(result["flow_id"],{"names":"Summer\nWinter\nBack","start_date":date.today().isoformat()})
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(result["flow_id"],{"next_step_id":"finish"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert len(result["data"]["paddocks"]) == 3
    await hass.async_block_till_done()
    if result["result"].runtime_data:
        await hass.config_entries.async_unload(result["result"].entry_id)


@pytest.mark.asyncio
async def test_setup_reload_pending_entities_and_store(hass):
    entry = MockConfigEntry(domain=DOMAIN,title="Pasture WSC",data=entry_data(),version=1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.data["moisture_factor"] is None
    assert entry.runtime_data.data["last_completed_day"] is None
    sensors = hass.states.async_all("sensor")
    from custom_components.pasture_wsc.sensor import PADDOCK_SENSORS
    assert len(sensors) == 16 + 3 * len(PADDOCK_SENSORS)
    assert len(hass.states.async_all("switch")) == 6
    assert len(hass.states.async_all("button")) == 3
    saved = deepcopy(entry.runtime_data.store.data["daily"])
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.store.data["daily"] == saved
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_options_and_reconfigure_preserve_paddocks(hass):
    entry = MockConfigEntry(domain=DOMAIN,title="Pasture WSC",data=entry_data(),version=1)
    entry.add_to_hass(hass)
    before = deepcopy(entry.data["paddocks"])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"],{"next_step_id":"weather_settings"})
    policy = {k:entry_data()[k] for k in ("weather_entities","calculation_time","minimum_coverage","solar_minimum_coverage",
                                        "allow_estimated","allow_forecast","historical_backfill","estimate_solar","assume_clear_sky","soil_semantics","soil_freshness")}
    result = await hass.config_entries.options.async_configure(result["flow_id"],{**policy,"allow_estimated":True})
    result = await hass.config_entries.options.async_configure(result["flow_id"],{"next_step_id":"finish"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.data["paddocks"] == before
    result = await hass.config_entries.flow.async_init(DOMAIN,context={"source":SOURCE_RECONFIGURE,"entry_id":entry.entry_id})
    result = await hass.config_entries.flow.async_configure(result["flow_id"],{k:("America/Winnipeg" if k=="timezone" else entry.data[k]) for k in ("latitude","longitude","elevation","timezone")})
    assert result["type"] == FlowResultType.ABORT
    assert entry.data["paddocks"] == before
    await hass.async_block_till_done()
    if entry.runtime_data:
        await hass.config_entries.async_unload(entry.entry_id)
