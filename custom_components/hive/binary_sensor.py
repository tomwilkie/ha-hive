"""Support for the Hive boost binary sensors."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import override

from apyhiveapi import Device, Hive

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HiveConfigEntry
from .entity import HiveEntity

PARALLEL_UPDATES = 0
SCAN_INTERVAL = timedelta(seconds=15)


@dataclass(frozen=True, kw_only=True)
class HiveBoostEntityDescription(BinarySensorEntityDescription):
    """Describes a Hive boost binary sensor.

    The key is the hive type core's integration used, so the unique ID, and
    with it the entity, carries over.
    """

    device_type: str
    update_fn: Callable[[Hive, Device], Awaitable[Device]]


BOOST_TYPES: tuple[HiveBoostEntityDescription, ...] = (
    HiveBoostEntityDescription(
        key="Heating_Boost",
        translation_key="heating",
        device_type="climate",
        update_fn=lambda hive, device: hive.heating.get_climate(device),
    ),
    HiveBoostEntityDescription(
        key="Hotwater_Boost",
        translation_key="hot_water",
        device_type="water_heater",
        update_fn=lambda hive, device: hive.hotwater.get_water_heater(device),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hive boost binary sensors based on a config entry."""

    hive = entry.runtime_data
    async_add_entities(
        (
            HiveBoostBinarySensor(hass, entry, hive, dev, description)
            for description in BOOST_TYPES
            for dev in hive.device_list.get(description.device_type, [])
        ),
        True,
    )


class HiveBoostBinarySensor(HiveEntity, BinarySensorEntity):
    """Whether a Hive heating zone or the hot water is boosting."""

    entity_description: HiveBoostEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HiveConfigEntry,
        hive: Hive,
        hive_device: Device,
        entity_description: HiveBoostEntityDescription,
    ) -> None:
        """Initialise the boost binary sensor."""
        super().__init__(hass, entry, hive, hive_device)
        self.entity_description = entity_description
        self._attr_unique_id = f"{hive_device.hive_id}-{entity_description.key}"

    @override
    async def async_update(self) -> None:
        """Update all Node data from Hive."""
        await self.hive.update_data()
        self.device = await self.entity_description.update_fn(self.hive, self.device)
        self._attr_available = self.device.device_data.get("online")
        if self._attr_available:
            # The library reports None when Hive did not say.
            boost = self.device.status["boost"]
            self._attr_is_on = None if boost is None else boost == "ON"
