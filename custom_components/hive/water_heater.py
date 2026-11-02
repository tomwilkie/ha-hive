"""Support for hive water heaters."""

from typing import Any, override

from hiveheating import HotWaterProduct

from homeassistant.components.water_heater import (
    STATE_ECO,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import STATE_OFF, STATE_ON, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HiveConfigEntry, refresh_system
from .entity import HiveEntity, boost_minutes, current_mode, discover

HOTWATER_NAME = "Hot Water"
PARALLEL_UPDATES = 0
# Hive's MANUAL is "on" for hot water.
HIVE_TO_HASS_STATE = {
    "SCHEDULE": STATE_ECO,
    "MANUAL": STATE_ON,
    "OFF": STATE_OFF,
}

HASS_TO_HIVE_STATE = {
    STATE_ECO: "SCHEDULE",
    STATE_ON: "MANUAL",
    STATE_OFF: "OFF",
}

SUPPORT_WATER_HEATER = [STATE_ECO, STATE_ON, STATE_OFF]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hive thermostat based on a config entry."""

    coordinator = entry.runtime_data
    async_add_entities(
        HiveWaterHeater(coordinator, product, device)
        for product, device in discover(coordinator.data, ("hotwater",))
    )


class HiveWaterHeater(HiveEntity, WaterHeaterEntity):
    """Hive Water Heater Device."""

    # The hot water shares its thermostat with the heating zone, which is the
    # device's main entity, so this one carries a name of its own.
    _attr_translation_key = "hot_water"
    _attr_supported_features = (
        WaterHeaterEntityFeature.ON_OFF | WaterHeaterEntityFeature.OPERATION_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_operation_list = SUPPORT_WATER_HEATER

    @property
    def hot_water(self) -> HotWaterProduct:
        """Return the hot water product from the latest snapshot.

        Only read while the entity is available, so the product is there.
        """
        product = self.product
        assert isinstance(product, HotWaterProduct)
        return product

    @property
    @override
    def current_operation(self) -> str | None:
        """Return the operation; a boost reports the mode it returns to."""
        return HIVE_TO_HASS_STATE.get(current_mode(self.hot_water) or "")

    @refresh_system
    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on hotwater."""
        await self.hive.set_mode(self.hot_water, "MANUAL")

    @refresh_system
    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn on hotwater."""
        await self.hive.set_mode(self.hot_water, "OFF")

    @refresh_system
    @override
    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set operation mode."""
        new_mode = HASS_TO_HIVE_STATE[operation_mode]
        await self.hive.set_mode(self.hot_water, new_mode)

    @refresh_system
    async def async_hot_water_boost(self, time_period: int, on_off: str) -> None:
        """Handle the service call."""
        if on_off == "on":
            await self.hive.set_hot_water_boost(
                self.hot_water, boost_minutes(time_period)
            )
        elif on_off == "off":
            await self.async_end_boost()
