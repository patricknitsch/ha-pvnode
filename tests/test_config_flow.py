"""Tests for the pvnode config flow (setup, reauth, reconfigure, options)."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pvnode.api import PvnodeAuthError, PvnodeConnectionError
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


async def test_v2_happy_path(hass: HomeAssistant) -> None:
    """A full user -> site walkthrough creates a v2 entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "pvnode", CONF_API_VERSION: "v2", CONF_API_KEY: "key123"},
    )
    assert result["step_id"] == "site"

    with patch(V2_FORECAST, return_value=FAKE_V2_RESPONSE):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SITE_ID: "site_abc", CONF_TIER: "free", CONF_FORECAST_DAYS: 2},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_VERSION] == "v2"
    assert result["data"][CONF_SITE_ID] == "site_abc"
    assert result["options"][CONF_TIER] == "free"


async def test_v2_site_errors(hass: HomeAssistant) -> None:
    """Auth/connection/unknown errors on the site step show the right error code."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "pvnode", CONF_API_VERSION: "v2", CONF_API_KEY: "key123"},
    )

    with patch(V2_FORECAST, side_effect=PvnodeAuthError("bad key")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SITE_ID: "site_abc", CONF_TIER: "free", CONF_FORECAST_DAYS: 2},
        )
    assert result["errors"] == {"base": "invalid_auth"}

    with patch(V2_FORECAST, side_effect=PvnodeConnectionError("timeout")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SITE_ID: "site_abc", CONF_TIER: "free", CONF_FORECAST_DAYS: 2},
        )
    assert result["errors"] == {"base": "cannot_connect"}

    with patch(V2_FORECAST, side_effect=RuntimeError("boom")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SITE_ID: "site_abc", CONF_TIER: "free", CONF_FORECAST_DAYS: 2},
        )
    assert result["type"] is FlowResultType.FORM


async def test_v2_duplicate_site_aborts(hass: HomeAssistant) -> None:
    """Configuring the same Site-ID twice aborts as already configured."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="v2_site_abc",
        data={
            "name": "pvnode",
            CONF_API_VERSION: "v2",
            CONF_API_KEY: "key123",
            CONF_SITE_ID: "site_abc",
        },
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "pvnode 2", CONF_API_VERSION: "v2", CONF_API_KEY: "key456"},
    )
    with patch(V2_FORECAST, return_value=FAKE_V2_RESPONSE):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SITE_ID: "site_abc", CONF_TIER: "free", CONF_FORECAST_DAYS: 2},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_v1_happy_path_two_roofs(hass: HomeAssistant) -> None:
    """A user -> roof (x2) -> general walkthrough creates a v1 entry with 2 roofs."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "pvnode", CONF_API_VERSION: "v1", CONF_API_KEY: "key123"},
    )
    assert result["step_id"] == "roof"

    with patch(V1_FORECAST, return_value=FAKE_V1_RESPONSE):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_ROOF_NAME: "Süd",
                CONF_ROOF_AZIMUTH: 0,
                CONF_ROOF_TILT: 30,
                CONF_ROOF_PEAK_POWER: 5,
                "add_another": True,
            },
        )
    assert result["step_id"] == "roof"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ROOF_NAME: "Ost",
            CONF_ROOF_AZIMUTH: -90,
            CONF_ROOF_TILT: 40,
            CONF_ROOF_PEAK_POWER: 3,
            "add_another": False,
        },
    )
    assert result["step_id"] == "general"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TIER: "free", CONF_FORECAST_DAYS: 2}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(result["options"][CONF_ROOFS]) == 2
    assert (
        result["options"][CONF_ROOFS][0][CONF_ROOF_ID]
        != result["options"][CONF_ROOFS][1][CONF_ROOF_ID]
    )


async def test_v1_roof_errors(hass: HomeAssistant) -> None:
    """Auth/connection errors on the first roof are surfaced before it is stored."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "pvnode", CONF_API_VERSION: "v1", CONF_API_KEY: "key123"},
    )

    with patch(V1_FORECAST, side_effect=PvnodeAuthError("bad key")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_ROOF_NAME: "Süd",
                CONF_ROOF_AZIMUTH: 0,
                CONF_ROOF_TILT: 30,
                CONF_ROOF_PEAK_POWER: 5,
                "add_another": False,
            },
        )
    assert result["errors"] == {"base": "invalid_auth"}
    assert result["step_id"] == "roof"


async def test_reauth_flow(hass: HomeAssistant) -> None:
    """Reauth updates the stored API key after a successful test call."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="v2_site_abc",
        data={
            "name": "pvnode",
            CONF_API_VERSION: "v2",
            CONF_API_KEY: "old-key",
            CONF_SITE_ID: "site_abc",
        },
        options={CONF_TIER: "free", CONF_FORECAST_DAYS: 2},
    )
    entry.add_to_hass(hass)

    with patch(V2_FORECAST, return_value=FAKE_V2_RESPONSE):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key"


async def test_reconfigure_flow_v2(hass: HomeAssistant) -> None:
    """Reconfigure updates the API key and Site-ID for a v2 entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="v2_site_abc",
        data={
            "name": "pvnode",
            CONF_API_VERSION: "v2",
            CONF_API_KEY: "old-key",
            CONF_SITE_ID: "site_abc",
        },
        options={CONF_TIER: "free", CONF_FORECAST_DAYS: 2},
    )
    entry.add_to_hass(hass)

    with patch(V2_FORECAST, return_value=FAKE_V2_RESPONSE):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "new-key", CONF_SITE_ID: "site_xyz"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_API_KEY] == "new-key"
    assert entry.data[CONF_SITE_ID] == "site_xyz"


async def test_options_flow_general_and_roofs(hass: HomeAssistant) -> None:
    """The options flow can edit tier/forecast_days and add/remove v1 roofs."""
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
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {"general", "add_roof", "remove_roof"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_roof"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ROOF_NAME: "Ost",
            CONF_ROOF_AZIMUTH: -90,
            CONF_ROOF_TILT: 40,
            CONF_ROOF_PEAK_POWER: 3,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(entry.options[CONF_ROOFS]) == 2

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_roof"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ROOFS: ["roof1"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(entry.options[CONF_ROOFS]) == 1
    assert entry.options[CONF_ROOFS][0][CONF_ROOF_NAME] == "Ost"


async def test_options_flow_remove_roof_aborts_when_empty(hass: HomeAssistant) -> None:
    """Removing roofs when none are configured aborts the flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="v1_empty",
        data={"name": "pvnode", CONF_API_VERSION: "v1", CONF_API_KEY: "key123"},
        options={CONF_TIER: "free", CONF_FORECAST_DAYS: 2, CONF_ROOFS: []},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_roof"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_roofs"
