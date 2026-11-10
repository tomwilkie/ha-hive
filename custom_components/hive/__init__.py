"""Support for the Hive devices and services."""

from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
import logging
from typing import Any, Concatenate

from hiveheating import Auth, Hive, HiveError, HiveReauthRequired

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import (
    aiohttp_client,
    config_validation as cv,
    device_registry as dr,
)
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .coordinator import HiveConfigEntry, HiveDataUpdateCoordinator
from .entity import HiveEntity, display_name, find_hub
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Hive integration."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HiveConfigEntry) -> bool:
    """Set up Hive from a config entry."""
    web_session = aiohttp_client.async_get_clientsession(hass)
    hive = Hive(web_session)
    try:
        hive.new_session(dict(entry.data))
    except HiveReauthRequired as err:
        raise ConfigEntryAuthFailed(str(err)) from err

    coordinator = HiveDataUpdateCoordinator(hass, entry, hive)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    if (hub := find_hub(coordinator.data)) is not None:
        connections: set[tuple[str, str]] = set()
        if hub.mac_address:
            connections.add((dr.CONNECTION_NETWORK_MAC, hub.mac_address))

        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, hub.id)},
            connections=connections,
            name=display_name(hub.name),
            model=hub.model,
            sw_version=hub.version,
            manufacturer=hub.manufacturer,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: HiveConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: HiveConfigEntry) -> None:
    """Remove a config entry, and ask Hive to forget its trusted device.

    The access token saved at setup has usually expired, so the refresh
    token, which is tied to the trusted device, gets a fresh one first. The
    entry is removed even when Hive cannot be told.
    """
    device_data = entry.data.get("device_data") or []
    device_key = device_data[1] if len(device_data) > 1 else None
    refresh_token = (
        entry.data.get("tokens", {}).get("AuthenticationResult", {}).get("RefreshToken")
    )
    if not device_key or not refresh_token:
        _LOGGER.warning(
            "Could not ask Hive to forget the device: the entry has no saved "
            "device credentials. Remove it in the Hive app"
        )
        return

    auth = Auth(
        entry.data["username"],
        entry.data["password"],
        device_key=device_key,
        websession=aiohttp_client.async_get_clientsession(hass),
    )
    try:
        await auth.refresh_token(refresh_token)
        await auth.forget_device(auth.access_token, device_key)
    except HiveError as err:
        _LOGGER.warning(
            "Could not ask Hive to forget the device: %s. Remove it in the Hive app",
            err,
        )


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: HiveConfigEntry, device_entry: dr.AnyDeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True


def refresh_system[_HiveEntityT: HiveEntity, **_P](
    func: Callable[Concatenate[_HiveEntityT, _P], Awaitable[Any]],
) -> Callable[Concatenate[_HiveEntityT, _P], Coroutine[Any, Any, None]]:
    """Report a failed command, or refresh every entity after a state change.

    The library's commands return nothing and raise a HiveError when the
    change could not be made. The refresh is debounced, so a burst of
    commands does not run into Hive's request limit.
    """

    @wraps(func)
    async def wrapper(self: _HiveEntityT, *args: _P.args, **kwargs: _P.kwargs) -> None:
        try:
            await func(self, *args, **kwargs)
        except HiveError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()

    return wrapper
