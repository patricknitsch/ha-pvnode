"""Tests for setting up and unloading the pvnode integration."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
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

FAKE_V2_RESPONSE = {
    "values": [{"timestamp": "2026-07-13T12:00:00", "pv_power": 1000}],
    "strings": [
        {"string_index": 0, "timestamp": "2026-07-13T12:00:00", "pv_power": 1000}
    ],
}
FAKE_V1_RESPONSE = {"values": [{"dtm": "2026-07-13T12:00:00Z", "pv_watts": 500}]}


def _v2_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="v2_site_abc",
        data={
            "name": "pvnode",
            CONF_API_VERSION: "v2",
            CONF_API_KEY: "key123",
            CONF_SITE_ID: "site_abc",
        },
        options={CONF_TIER: "free", CONF_FORECAST_DAYS: 2},
    )


def _v1_entry() -> MockConfigEntry:
    return MockConfigEntry(
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


async def test_setup_and_unload_v2(hass: HomeAssistant) -> None:
    """A v2 entry loads, stores runtime_data, and unloads cleanly."""
    entry = _v2_entry()
    entry.add_to_hass(hass)

    with patch(V2_FORECAST, return_value=FAKE_V2_RESPONSE):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None
    assert "string_0" in entry.runtime_data.data.roofs

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_v1_deprecation_issue_created_and_cleared(hass: HomeAssistant) -> None:
    """A v1 entry raises a repair issue; a v2 entry doesn't (cleared on unload)."""
    v1_entry = _v1_entry()
    v1_entry.add_to_hass(hass)

    with patch(V1_FORECAST, return_value=FAKE_V1_RESPONSE):
        assert await hass.config_entries.async_setup(v1_entry.entry_id)
        await hass.async_block_till_done()

    issue_registry = ir.async_get(hass)
    issue_id = f"v1_deprecated_{v1_entry.entry_id}"
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None

    await hass.config_entries.async_unload(v1_entry.entry_id)
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    v2_entry = _v2_entry()
    v2_entry.add_to_hass(hass)
    with patch(V2_FORECAST, return_value=FAKE_V2_RESPONSE):
        assert await hass.config_entries.async_setup(v2_entry.entry_id)
        await hass.async_block_till_done()

    assert (
        issue_registry.async_get_issue(DOMAIN, f"v1_deprecated_{v2_entry.entry_id}")
        is None
    )


async def test_v1_hard_shutdown_blocks_setup(hass: HomeAssistant) -> None:
    """After the v1 hard-shutdown date, setup fails and retries."""
    entry = _v1_entry()
    entry.add_to_hass(hass)

    with (
        patch(V1_FORECAST, return_value=FAKE_V1_RESPONSE),
        patch.object(
            dt_util,
            "now",
            return_value=dt_util.parse_datetime("2027-01-02T00:00:00+00:00"),
        ),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
