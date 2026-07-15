"""Tests for pvnode sensor entities and device/entity cleanup."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pvnode.const import (
    CONF_API_VERSION,
    CONF_FORECAST_DAYS,
    CONF_ROOF_AZIMUTH,
    CONF_ROOF_ID,
    CONF_ROOF_NAME,
    CONF_ROOF_PEAK_POWER,
    CONF_ROOF_TILT,
    CONF_ROOFS,
    CONF_SITE_ID,
    CONF_TIER,
    DOMAIN,
)

V2_FORECAST = "custom_components.pvnode.api.PvnodeApiClient.async_get_v2_forecast"
V1_FORECAST = "custom_components.pvnode.api.PvnodeApiClient.async_get_v1_forecast"

FAKE_V2_TWO_STRINGS = {
    "values": [
        {
            "timestamp": "2026-07-13T12:00:00",
            "pv_power": 1500,
            "pv_power_clearsky": 1800,
            "temp": 21.0,
            "weather_code": 1,
        }
    ],
    "strings": [
        {"string_index": 0, "timestamp": "2026-07-13T12:00:00", "pv_power": 1000},
        {"string_index": 1, "timestamp": "2026-07-13T12:00:00", "pv_power": 500},
    ],
}
FAKE_V2_ONE_STRING = {
    "values": [{"timestamp": "2026-07-13T12:00:00", "pv_power": 1000}],
    "strings": [
        {"string_index": 0, "timestamp": "2026-07-13T12:00:00", "pv_power": 1000}
    ],
}
FAKE_V1_RESPONSE = {
    "values": [
        {
            "dtm": "2026-07-13T12:00:00Z",
            "pv_watts": 500,
            "pv_watts_clearsky": 600,
            "temp": 20.0,
            "weather_code": 0,
        }
    ]
}


def _v2_entry(forecast_days: int = 2, tier: str = "free") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="pvnode",
        unique_id="v2_site_abc",
        data={
            "name": "pvnode",
            CONF_API_VERSION: "v2",
            CONF_API_KEY: "key123",
            CONF_SITE_ID: "site_abc",
        },
        options={CONF_TIER: tier, CONF_FORECAST_DAYS: forecast_days},
    )


async def test_v2_two_strings_creates_expected_entities(hass: HomeAssistant) -> None:
    """Two strings produce two roof devices plus a site overview device."""
    entry = _v2_entry(forecast_days=2)
    entry.add_to_hass(hass)

    with patch(V2_FORECAST, return_value=FAKE_V2_TWO_STRINGS):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    entity_ids = {e.entity_id for e in entities}

    # 2 roofs x (power + 2 energy-day sensors) = 6, no per-roof clear-sky for v2.
    assert "sensor.dachflache_1_power_forecast" in entity_ids
    assert "sensor.dachflache_2_power_forecast" in entity_ids
    assert not any("clear_sky" in e for e in entity_ids if "dachflache" in e)

    # Site overview: total power + 2 energy-day + clearsky + temperature + weather_code.
    assert "sensor.pvnode_total_power_forecast" in entity_ids
    assert "sensor.pvnode_total_clear_sky_power" in entity_ids
    assert "sensor.pvnode_temperature_forecast" in entity_ids
    assert "sensor.pvnode_weather_code" in entity_ids

    power_state = hass.states.get("sensor.dachflache_1_power_forecast")
    assert power_state.state == "1000"
    total_state = hass.states.get("sensor.pvnode_total_power_forecast")
    assert total_state.state == "1500.0"


async def test_forecast_days_controls_energy_sensor_count(hass: HomeAssistant) -> None:
    """Increasing forecast_days creates one energy sensor per extra day."""
    entry = _v2_entry(forecast_days=4, tier="plus")
    entry.add_to_hass(hass)

    with patch(V2_FORECAST, return_value=FAKE_V2_ONE_STRING):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    energy_ids = [
        e.entity_id
        for e in entities
        if "energy_forecast" in e.entity_id and "dachflache" in e.entity_id
    ]
    assert len(energy_ids) == 4


async def test_v1_roof_has_clearsky_sensor(hass: HomeAssistant) -> None:
    """API v1 roof surfaces get their own clear-sky power sensor."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="v1_abc",
        data={"name": "pvnode", CONF_API_VERSION: "v1", CONF_API_KEY: "key123"},
        options={
            CONF_TIER: "free",
            CONF_FORECAST_DAYS: 2,
            CONF_ROOFS: [
                {
                    CONF_ROOF_ID: "roof1",
                    CONF_ROOF_NAME: "Süd",
                    CONF_ROOF_AZIMUTH: 0,
                    CONF_ROOF_TILT: 30,
                    CONF_ROOF_PEAK_POWER: 5,
                }
            ],
        },
    )
    entry.add_to_hass(hass)

    with patch(V1_FORECAST, return_value=FAKE_V1_RESPONSE):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.sud_clear_sky_power")
    assert state is not None
    assert state.state == "600"


async def test_stale_roof_device_removed_when_string_disappears(
    hass: HomeAssistant,
) -> None:
    """A device for a v2 string is removed once that string stops being reported."""
    entry = _v2_entry(forecast_days=2)
    entry.add_to_hass(hass)

    with patch(V2_FORECAST, return_value=FAKE_V2_TWO_STRINGS):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    devices_before = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices_before) == 3  # 2 roofs + overview device

    with patch(V2_FORECAST, return_value=FAKE_V2_ONE_STRING):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    devices_after = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices_after) == 2  # 1 roof + overview device
    remaining_names = {device.name for device in devices_after}
    assert "Dachfläche 2" not in remaining_names
