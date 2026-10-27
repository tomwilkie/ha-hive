"""Support for the Hive devices and services."""

from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any, Concatenate

from apyhiveapi import Auth, Hive, HiveConnectionError, HiveError, HiveReauthRequired

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import (
    aiohttp_client,
    config_validation as cv,
    device_registry as dr,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .entity import HiveEntity
from .services import async_setup_services

type HiveConfigEntry = ConfigEntry[Hive]


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Hive integration."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HiveConfigEntry) -> bool:
    """Set up Hive from a config entry."""
    web_session = aiohttp_client.async_get_clientsession(hass)
    hive_config = dict(entry.data)
    hive = Hive(web_session)

    entry.runtime_data = hive

    try:
        devices = await hive.start_session(hive_config)
    except HiveReauthRequired as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except HiveConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    except HiveError as err:
        raise ConfigEntryError(str(err)) from err

    # The hub is missing when Hive did not report one; the library logs that.
    if devices["parent"]:
        hub_data = devices["parent"][0]
        hub_props = hub_data.device_data
        connections: set[tuple[str, str]] = set()
        if mac := hub_props.get("macAddress"):
            connections.add((dr.CONNECTION_NETWORK_MAC, mac))

        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, hub_data.device_id)},
            connections=connections,
            name=hub_data.hive_name,
            model=hub_props.get("model"),
            sw_version=hub_props.get("version"),
            manufacturer=hub_props.get("manufacturer"),
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: HiveConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: HiveConfigEntry) -> None:
    """Remove a config entry."""
    hive = Auth(entry.data["username"], entry.data["password"])
    await hive.forget_device(
        entry.data["tokens"]["AuthenticationResult"]["AccessToken"],
        entry.data["device_data"][1],
    )


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: HiveConfigEntry, device_entry: dr.AnyDeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True


def refresh_system[_HiveEntityT: HiveEntity, **_P](
    func: Callable[Concatenate[_HiveEntityT, _P], Awaitable[Any]],
) -> Callable[Concatenate[_HiveEntityT, _P], Coroutine[Any, Any, None]]:
    """Report a failed command, or force update all entities after state change.

    The library's commands return nothing and raise a HiveError when the
    change could not be made, or a ValueError for an invalid argument.
    """

    @wraps(func)
    async def wrapper(self: _HiveEntityT, *args: _P.args, **kwargs: _P.kwargs) -> None:
        try:
            await func(self, *args, **kwargs)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        except HiveError as err:
            raise HomeAssistantError(str(err)) from err
        async_dispatcher_send(self.hass, DOMAIN)

    return wrapper
