"""Support for the Hive battery level sensors."""

from typing import override

from apyhiveapi import Device, Product

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HiveConfigEntry
from .coordinator import HiveDataUpdateCoordinator
from .entity import HiveEntity, discover

PARALLEL_UPDATES = 0

# The key is the hive type core's integration used, so the unique ID, and
# with it the entity, carries over.
BATTERY_DESCRIPTION = SensorEntityDescription(
    key="Battery",
    translation_key="battery",
    native_unit_of_measurement=PERCENTAGE,
    device_class=SensorDeviceClass.BATTERY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hive battery sensors based on a config entry.

    Hive reports the battery level on the thermostat that carries a
    product. Heating and hot water share their thermostat, so each device
    gets one sensor, through the first product that carries it. A
    mains-powered device reports no battery and gets no sensor.

    The sensor is available while the hardware itself is online, not while
    the product is: a heating zone stays online through its receiver after
    its thermostat's battery has died.
    """

    coordinator = entry.runtime_data
    seen: set[str] = set()
    entities: list[HiveBatterySensor] = []
    for product, device in discover(coordinator.data, ("heating", "hotwater")):
        if device is None or device.id in seen or device.battery is None:
            continue
        seen.add(device.id)
        entities.append(HiveBatterySensor(coordinator, product, device))
    async_add_entities(entities)


class HiveBatterySensor(HiveEntity, SensorEntity):
    """The battery level of a Hive thermostat."""

    def __init__(
        self,
        coordinator: HiveDataUpdateCoordinator,
        product: Product,
        device: Device,
    ) -> None:
        """Initialise the battery sensor."""
        super().__init__(coordinator, product, device)
        self.entity_description = BATTERY_DESCRIPTION
        self._attr_unique_id = f"{device.id}-{BATTERY_DESCRIPTION.key}"

    @property
    @override
    def available(self) -> bool:
        """Return whether the hardware itself is online."""
        device = self.device
        return device is not None and bool(device.online)

    @property
    def native_value(self) -> int | None:
        """Return the battery level in percent."""
        device = self.device
        return None if device is None else device.battery
