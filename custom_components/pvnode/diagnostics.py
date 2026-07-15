"""Diagnostics support for the pvnode integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .coordinator import PvnodeConfigEntry

TO_REDACT = {CONF_API_KEY, "site_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PvnodeConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": dict(entry.options),
        "forecast_days": coordinator.forecast_days,
        "known_roof_keys": sorted(coordinator.known_roof_keys),
        "last_update_success": coordinator.last_update_success,
        "roofs": {
            key: {
                "name": roof.name,
                "watts_count": len(roof.forecast.watts),
                "watts_clearsky_count": len(roof.forecast.watts_clearsky),
                "temperature_count": len(roof.forecast.temperature),
                "weather_code_count": len(roof.forecast.weather_code),
                "energy_by_day": {
                    day.isoformat(): value
                    for day, value in roof.forecast.energy_by_day.items()
                },
            }
            for key, roof in (
                coordinator.data.roofs if coordinator.data else {}
            ).items()
        },
        "site": {
            "watts_clearsky_count": len(coordinator.data.site.watts_clearsky)
            if coordinator.data
            else 0,
            "temperature_count": len(coordinator.data.site.temperature)
            if coordinator.data
            else 0,
            "weather_code_count": len(coordinator.data.site.weather_code)
            if coordinator.data
            else 0,
        },
    }
