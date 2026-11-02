"""Support for the Hive climate devices."""

import logging
from typing import Any, override

from hiveheating import HeatingProduct

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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HiveConfigEntry, refresh_system
from .entity import HiveEntity, boost_minutes, current_mode, discover

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
MIN_TARGET_TEMPERATURE = 5.0
MAX_TARGET_TEMPERATURE = 32.0
PARALLEL_UPDATES = 0
_LOGGER = logging.getLogger()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hive thermostat based on a config entry."""

    coordinator = entry.runtime_data
    async_add_entities(
        HiveClimateEntity(coordinator, product, device)
        for product, device in discover(coordinator.data, ("heating",))
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
    _attr_min_temp = MIN_TARGET_TEMPERATURE
    _attr_max_temp = MAX_TARGET_TEMPERATURE

    @property
    def heating(self) -> HeatingProduct:
        """Return the heating product from the latest snapshot.

        Only read while the entity is available, so the product is there.
        """
        product = self.product
        assert isinstance(product, HeatingProduct)
        return product

    @property
    @override
    def temperature_unit(self) -> str:
        """Return the account's unit; Hive reports none when it has none set."""
        unit = self.coordinator.data.user.temperature_unit
        return TEMP_UNIT.get(unit or "", UnitOfTemperature.CELSIUS)

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        """Return the mode; a boost heats whatever mode it returns to."""
        if self.heating.boost:
            return HVACMode.HEAT
        return HIVE_TO_HASS_STATE.get(current_mode(self.heating) or "")

    @property
    @override
    def hvac_action(self) -> HVACAction | None:
        """Return whether the zone is calling for heat."""
        return HIVE_TO_HASS_HVAC_ACTION.get(self.heating.working)

    @property
    @override
    def current_temperature(self) -> float | None:
        """Return the measured temperature, to one decimal place."""
        temperature = self.heating.temperature
        return None if temperature is None else round(temperature, 1)

    @property
    @override
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self.heating.target

    @property
    @override
    def preset_mode(self) -> str:
        """Return the boost preset while a boost is active."""
        return PRESET_BOOST if self.heating.boost else PRESET_NONE

    @refresh_system
    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        await self.hive.set_mode(self.heating, HASS_TO_HIVE_STATE[hvac_mode])

    @refresh_system
    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature, and the hvac mode if one is given."""
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_handle_set_hvac_mode_service(hvac_mode)
        new_temperature = kwargs.get(ATTR_TEMPERATURE)
        if new_temperature is not None:
            await self.hive.set_target_temperature(self.heating, new_temperature)

    @refresh_system
    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if preset_mode == PRESET_NONE and self.preset_mode == PRESET_BOOST:
            await self.async_end_boost()
        elif preset_mode == PRESET_BOOST:
            curtemp = round((self.current_temperature or 0) * 2) / 2
            temperature = curtemp + 0.5
            await self._async_boost(30, temperature)

    @refresh_system
    async def async_heating_boost_on(self, time_period, temperature):
        """Handle boost heating service call."""
        await self._async_boost(time_period, temperature)

    @refresh_system
    async def async_heating_boost_off(self) -> None:
        """Handle boost heating service call."""
        await self.async_end_boost()

    async def _async_boost(self, time_period: float, temperature: float) -> None:
        """Boost the heating to *temperature* for *time_period* minutes.

        Raises:
            ServiceValidationError: The boost is shorter than a minute, or
                its temperature is out of range.
        """
        minutes = boost_minutes(time_period)
        target = float(temperature)
        if not MIN_TARGET_TEMPERATURE <= target <= MAX_TARGET_TEMPERATURE:
            raise ServiceValidationError(
                f"Boost temperature must be between {MIN_TARGET_TEMPERATURE} and "
                f"{MAX_TARGET_TEMPERATURE}, not {temperature}"
            )
        await self.hive.set_heating_boost(self.heating, minutes, target)
