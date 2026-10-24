"""Support for the Hive devices and services."""

from typing import TYPE_CHECKING, override

from apyhiveapi import Device, Hive

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN

if TYPE_CHECKING:
    from . import HiveConfigEntry


class HiveEntity(Entity):
    """Initiate Hive Base Class."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HiveConfigEntry,
        hive: Hive,
        hive_device: Device,
    ) -> None:
        """Initialize the instance."""
        self.hive = hive
        self.device = hive_device
        self._attr_name = self.device["ha_name"]
        self._attr_unique_id = f"{self.device['hive_id']}-{self.device['hive_type']}"
        device_id = self.device["device_id"]
        # A product with no device of its own carries its own props, which
        # lack the manufacturer.
        device_data = self.device["device_data"]
        device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            model=device_data.get("model"),
            manufacturer=device_data.get("manufacturer"),
            name=self.device["device_name"],
            sw_version=device_data.get("version"),
        )
        # Hive reports the hub itself as its parent, and no parent at all
        # when it did not report a hub.
        parent_device = self.device["parent_device"]
        if parent_device and parent_device != device_id:
            device_info["via_device_id"] = dr.async_get_device_id_by_identifier(
                hass,
                (DOMAIN, parent_device),
                config_entry_id=entry.entry_id,
            )
        self._attr_device_info = device_info

    @override
    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, DOMAIN, self.async_write_ha_state)
        )
