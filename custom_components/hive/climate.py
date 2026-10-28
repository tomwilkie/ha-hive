"""Support for the Hive climate devices."""

from datetime import timedelta
import logging
from typing import Any, override

from apyhiveapi import Device, Hive

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    PRESET_BOOST,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HiveConfigEntry, refresh_system
from .entity import HiveEntity

HIVE_TO_HASS_STATE = {
    "SCHEDULE": HVACMode.AUTO,
    "MANUAL": HVACMode.HEAT,
    "OFF": HVACMode.OFF,
}

HASS_TO_HIVE_STATE = {
    HVACMode.AUTO: "SCHEDULE",
    HVACMode.HEAT: "MANUAL",
    HVACMode.OFF: "OFF",
}

HIVE_TO_HASS_HVAC_ACTION = {
    "UNKNOWN": HVACAction.OFF,
    False: HVACAction.IDLE,
    True: HVACAction.HEATING,
}

TEMP_UNIT = {
    "C": UnitOfTemperature.CELSIUS,
    "F": UnitOfTemperature.FAHRENHEIT,
}
PARALLEL_UPDATES = 0
SCAN_INTERVAL = timedelta(seconds=15)
_LOGGER = logging.getLogger()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hive thermostat based on a config entry."""

    hive = entry.runtime_data
    devices = hive.device_list.get("climate")
    if devices:
        async_add_entities(
            (HiveClimateEntity(hass, entry, hive, dev) for dev in devices), True
        )


class HiveClimateEntity(HiveEntity, ClimateEntity):
    """Hive Climate Device."""

    # The main entity of its device, so it takes the device's name alone.
    _attr_name = None
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_BOOST, PRESET_NONE]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HiveConfigEntry,
        hive: Hive,
        hive_device: Device,
    ) -> None:
        """Initialize the Climate device."""
        super().__init__(hass, entry, hive, hive_device)
        self.thermostat_node_id = hive_device.device_id
        # Hive reports no unit when the account has none set.
        self._attr_temperature_unit = TEMP_UNIT.get(
            hive_device.temperature_unit, UnitOfTemperature.CELSIUS
        )

    @refresh_system
    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        new_mode = HASS_TO_HIVE_STATE[hvac_mode]
        await self.hive.heating.set_mode(self.device, new_mode)

    @refresh_system
    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature, and the hvac mode if one is given."""
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_handle_set_hvac_mode_service(hvac_mode)
        new_temperature = kwargs.get(ATTR_TEMPERATURE)
        if new_temperature is not None:
            await self.hive.heating.set_target_temperature(self.device, new_temperature)

    @refresh_system
    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if preset_mode == PRESET_NONE and self.preset_mode == PRESET_BOOST:
            await self.hive.heating.set_boost_off(self.device)
        elif preset_mode == PRESET_BOOST:
            curtemp = round((self.current_temperature or 0) * 2) / 2
            temperature = curtemp + 0.5
            await self.hive.heating.set_boost_on(self.device, 30, temperature)

    @refresh_system
    async def async_heating_boost_on(self, time_period, temperature):
        """Handle boost heating service call."""
        await self.hive.heating.set_boost_on(self.device, time_period, temperature)

    @refresh_system
    async def async_heating_boost_off(self) -> None:
        """Handle boost heating service call."""
        await self.hive.heating.set_boost_off(self.device)

    async def async_update(self) -> None:
        """Update all Node data from Hive."""
        await self.hive.update_data()
        self.device = await self.hive.heating.get_climate(self.device)
        self._attr_available = self.device.device_data.get("online")
        if self._attr_available:
            status = self.device.status
            self._attr_hvac_mode = HIVE_TO_HASS_STATE.get(status["mode"])
            self._attr_hvac_action = HIVE_TO_HASS_HVAC_ACTION.get(status["action"])
            self._attr_current_temperature = status["current_temperature"]
            self._attr_target_temperature = status["target_temperature"]
            self._attr_min_temp = self.device.min_temp
            self._attr_max_temp = self.device.max_temp
            if status["boost"] == "ON":
                self._attr_preset_mode = PRESET_BOOST
                self._attr_hvac_mode = HVACMode.HEAT
            else:
                self._attr_preset_mode = PRESET_NONE
