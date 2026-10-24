"""Support for hive water heaters."""

from datetime import timedelta
from typing import Any, override

import probatio

from homeassistant.components.water_heater import (
    STATE_ECO,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import STATE_OFF, STATE_ON, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HiveConfigEntry, refresh_system
from .const import (
    ATTR_ONOFF,
    ATTR_TIME_PERIOD,
    SERVICE_BOOST_HOT_WATER,
    WATER_HEATER_MODES,
)
from .entity import HiveEntity

HOTWATER_NAME = "Hot Water"
PARALLEL_UPDATES = 0
SCAN_INTERVAL = timedelta(seconds=15)
HIVE_TO_HASS_STATE = {
    "SCHEDULE": STATE_ECO,
    "ON": STATE_ON,
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

    hive = entry.runtime_data
    devices = hive.device_list.get("water_heater")
    if devices:
        async_add_entities(
            (HiveWaterHeater(hass, entry, hive, dev) for dev in devices), True
        )

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_BOOST_HOT_WATER,
        {
            probatio.Optional(ATTR_TIME_PERIOD, default="00:30:00"): probatio.All(
                cv.time_period,
                cv.positive_timedelta,
                lambda td: td.total_seconds() // 60,
            ),
            probatio.Required(ATTR_ONOFF): probatio.In(WATER_HEATER_MODES),
        },
        "async_hot_water_boost",
    )


class HiveWaterHeater(HiveEntity, WaterHeaterEntity):
    """Hive Water Heater Device."""

    _attr_supported_features = (
        WaterHeaterEntityFeature.ON_OFF | WaterHeaterEntityFeature.OPERATION_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_operation_list = SUPPORT_WATER_HEATER

    @refresh_system
    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on hotwater."""
        await self.hive.hotwater.set_mode(self.device, "MANUAL")

    @refresh_system
    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn on hotwater."""
        await self.hive.hotwater.set_mode(self.device, "OFF")

    @refresh_system
    @override
    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set operation mode."""
        new_mode = HASS_TO_HIVE_STATE[operation_mode]
        await self.hive.hotwater.set_mode(self.device, new_mode)

    @refresh_system
    async def async_hot_water_boost(self, time_period: int, on_off: str) -> None:
        """Handle the service call."""
        if on_off == "on":
            await self.hive.hotwater.set_boost_on(self.device, time_period)
        elif on_off == "off":
            await self.hive.hotwater.set_boost_off(self.device)

    async def async_update(self) -> None:
        """Update all Node data from Hive."""
        await self.hive.update_data()
        self.device = await self.hive.hotwater.get_water_heater(self.device)
        self._attr_available = self.device["device_data"].get("online")
        if self._attr_available:
            # The library reports None when Hive did not say.
            self._attr_current_operation = HIVE_TO_HASS_STATE.get(
                self.device["status"]["current_operation"]
            )
