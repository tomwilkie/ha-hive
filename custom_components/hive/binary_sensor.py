"""Support for the Hive boost binary sensors."""

from dataclasses import dataclass

from hiveheating import Device, Product

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HiveConfigEntry
from .coordinator import HiveDataUpdateCoordinator
from .entity import HiveEntity, discover

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HiveBoostEntityDescription(BinarySensorEntityDescription):
    """Describes a Hive boost binary sensor.

    The key is the hive type core's integration used, so the unique ID, and
    with it the entity, carries over.
    """

    product_types: tuple[str, ...]


BOOST_TYPES: tuple[HiveBoostEntityDescription, ...] = (
    HiveBoostEntityDescription(
        key="Heating_Boost",
        translation_key="heating",
        product_types=("heating",),
    ),
    HiveBoostEntityDescription(
        key="Hotwater_Boost",
        translation_key="hot_water",
        product_types=("hotwater",),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hive boost binary sensors based on a config entry."""

    coordinator = entry.runtime_data
    async_add_entities(
        HiveBoostBinarySensor(coordinator, product, device, description)
        for description in BOOST_TYPES
        for product, device in discover(coordinator.data, description.product_types)
    )


class HiveBoostBinarySensor(HiveEntity, BinarySensorEntity):
    """Whether a Hive heating zone or the hot water is boosting."""

    entity_description: HiveBoostEntityDescription

    def __init__(
        self,
        coordinator: HiveDataUpdateCoordinator,
        product: Product,
        device: Device | None,
        entity_description: HiveBoostEntityDescription,
    ) -> None:
        """Initialise the boost binary sensor."""
        super().__init__(coordinator, product, device)
        self.entity_description = entity_description
        self._attr_unique_id = f"{product.id}-{entity_description.key}"

    @property
    def is_on(self) -> bool:
        """Return whether a boost is active."""
        product = self.product
        return product is not None and bool(product.boost)
