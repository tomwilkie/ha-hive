"""Support for the Hive battery level sensors."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import override

from apyhiveapi import Device, Hive

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HiveConfigEntry
from .entity import HiveEntity

PARALLEL_UPDATES = 0
SCAN_INTERVAL = timedelta(seconds=15)

# The key is the hive type core's integration used, so the unique ID, and
# with it the entity, carries over.
BATTERY_DESCRIPTION = SensorEntityDescription(
    key="Battery",
    native_unit_of_measurement=PERCENTAGE,
    device_class=SensorDeviceClass.BATTERY,
    entity_category=EntityCategory.DIAGNOSTIC,
)

# How a product of each type refreshes its device's props from the last poll.
REFRESH_DEVICE: dict[str, Callable[[Hive, Device], Awaitable[Device]]] = {
    "climate": lambda hive, device: hive.heating.get_climate(device),
    "water_heater": lambda hive, device: hive.hotwater.get_water_heater(device),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hive battery sensors based on a config entry.

    Hive reports the battery level in the props of the thermostat or TRV that
    carries a product. Heating and hot water share their thermostat, so each
    device gets one sensor, through the first product that carries it. A
    mains-powered device reports no battery and gets no sensor.

    The sensor is available while the hardware itself is online
    (``device_online``), not while the product is: a heating zone stays online
    through its receiver after its thermostat's battery has died.
    """

    hive = entry.runtime_data
    seen: set[str] = set()
    entities: list[HiveBatterySensor] = []
    for device_type, refresh_device in REFRESH_DEVICE.items():
        for dev in hive.device_list.get(device_type, []):
            if dev.device_id in seen or "battery" not in dev.device_data:
                continue
            seen.add(dev.device_id)
            entities.append(HiveBatterySensor(hass, entry, hive, dev, refresh_device))
    async_add_entities(entities, True)


class HiveBatterySensor(HiveEntity, SensorEntity):
    """The battery level of a Hive thermostat or TRV."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HiveConfigEntry,
        hive: Hive,
        hive_device: Device,
        refresh_device: Callable[[Hive, Device], Awaitable[Device]],
    ) -> None:
        """Initialise the battery sensor."""
        super().__init__(hass, entry, hive, hive_device)
        self.entity_description = BATTERY_DESCRIPTION
        self._refresh_device = refresh_device
        self._attr_name = f"{hive_device.device_name} Battery Level"
        self._attr_unique_id = f"{hive_device.device_id}-{BATTERY_DESCRIPTION.key}"

    @override
    async def async_update(self) -> None:
        """Update all Node data from Hive."""
        await self.hive.update_data()
        self.device = await self._refresh_device(self.hive, self.device)
        self._attr_available = self.device.device_data.get("device_online")
        if self._attr_available:
            self._attr_native_value = self.device.device_data.get("battery")
