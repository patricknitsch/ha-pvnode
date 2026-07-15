"""The pvnode integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import API_VERSION_V2, CONF_API_VERSION, DOMAIN, PLATFORMS
from .coordinator import PvnodeConfigEntry, PvnodeDataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: PvnodeConfigEntry) -> bool:
    """Set up pvnode from a config entry."""
    coordinator = PvnodeDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _async_update_v1_deprecation_issue(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PvnodeConfigEntry) -> bool:
    """Unload a pvnode config entry."""
    ir.async_delete_issue(hass, DOMAIN, _v1_deprecation_issue_id(entry))
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: PvnodeConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _v1_deprecation_issue_id(entry: PvnodeConfigEntry) -> str:
    """Return a stable repair-issue id for this entry's v1 deprecation warning."""
    return f"v1_deprecated_{entry.entry_id}"


def _async_update_v1_deprecation_issue(
    hass: HomeAssistant, entry: PvnodeConfigEntry
) -> None:
    """Raise (or clear) a repair issue about the upcoming pvnode API v1 shutdown."""
    issue_id = _v1_deprecation_issue_id(entry)
    if entry.data.get(CONF_API_VERSION) == API_VERSION_V2:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="v1_deprecated",
        learn_more_url="https://pvnode.com",
    )
