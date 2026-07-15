"""Tests for the pvnode Energy dashboard solar forecast platform."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pvnode.const import (
    CONF_API_VERSION,
    CONF_FORECAST_DAYS,
    CONF_SITE_ID,
    CONF_TIER,
    DOMAIN,
)
from custom_components.pvnode.energy import async_get_solar_forecast

V2_FORECAST = "custom_components.pvnode.api.PvnodeApiClient.async_get_v2_forecast"

FAKE_V2_TWO_STRINGS = {
    "values": [{"timestamp": "2026-07-13T12:00:00", "pv_power": 1500}],
    "strings": [
        {"string_index": 0, "timestamp": "2026-07-13T12:00:00", "pv_power": 1000},
        {"string_index": 1, "timestamp": "2026-07-13T12:00:00", "pv_power": 500},
    ],
}


async def test_solar_forecast_sums_all_roofs(hass: HomeAssistant) -> None:
    """The energy platform sums watt_hours_period across all roof surfaces."""
    entry = MockConfigEntry(
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
    entry.add_to_hass(hass)

    with patch(V2_FORECAST, return_value=FAKE_V2_TWO_STRINGS):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await async_get_solar_forecast(hass, entry.entry_id)
    assert result is not None
    wh_hours = result["wh_hours"]
    assert len(wh_hours) == 1
    (value,) = wh_hours.values()
    # 1000 W + 500 W over a 15-minute period = 250 Wh + 125 Wh.
    assert value == 375


async def test_solar_forecast_unknown_entry_returns_none(hass: HomeAssistant) -> None:
    """An unknown config entry id returns None instead of raising."""
    result = await async_get_solar_forecast(hass, "does-not-exist")
    assert result is None
