"""Energy platform for the pvnode integration.

Implements Home Assistant's solar forecast contract (the same one used by
the built-in forecast.solar integration and by Solcast) so a pvnode config
entry can be picked as a "Forecast production" source for a solar panel in
the Energy dashboard.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_solar_forecast(
    hass: HomeAssistant, config_entry_id: str
) -> dict[str, dict[str, float | int]] | None:
    """Get the combined solar forecast (all roof surfaces) for a config entry."""
    entry = hass.config_entries.async_get_entry(config_entry_id)
    if entry is None or entry.domain != DOMAIN or entry.runtime_data is None:
        return None
    coordinator = entry.runtime_data
    if not coordinator.data:
        return None

    wh_hours: dict[str, float] = {}
    for roof in coordinator.data.roofs.values():
        for timestamp, value in roof.forecast.watt_hours_period.items():
            key = timestamp.isoformat()
            wh_hours[key] = wh_hours.get(key, 0) + value

    return {"wh_hours": wh_hours}
