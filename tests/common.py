"""Helpers shared by the Hive test modules.

The device factories, the mocked Hive session and the config entry setup.
Fixtures live in conftest.py.
"""

from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock

from apyhiveapi import Device
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

USERNAME = "user@example.com"
PASSWORD = "password"
TOKENS = {
    "AuthenticationResult": {
        "AccessToken": "mock-access-token",
        "RefreshToken": "mock-refresh-token",
    },
    "ChallengeName": "SUCCESS",
}
DEVICE_DATA = ["mock-device-group-key", "mock-device-key", "mock-device-password"]
ENTRY_DATA = {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD, "tokens": TOKENS}

HUB_ID = "hive-hub-id"
THERMOSTAT_ID = "hive-thermostat-id"
HEATING_ID = "hive-heating-id"
HOT_WATER_ID = "hive-hotwater-id"
CLIMATE_UNIQUE_ID = f"{HEATING_ID}-heating"
WATER_HEATER_UNIQUE_ID = f"{HOT_WATER_ID}-hotwater"
HEATING_BOOST_UNIQUE_ID = f"{HEATING_ID}-Heating_Boost"
HOT_WATER_BOOST_UNIQUE_ID = f"{HOT_WATER_ID}-Hotwater_Boost"
BATTERY_UNIQUE_ID = f"{THERMOSTAT_ID}-Battery"

_HUB_PROPS = {"model": "Hub", "version": "1.2.3", "manufacturer": "Hive"}
_THERMOSTAT_PROPS = {"model": "SLT3", "version": "1.2.3", "manufacturer": "Hive"}


def _thermostat_props(
    *, online: bool, device_online: bool, battery: int | None
) -> dict[str, object]:
    """Return the thermostat's props as the library copies them into device_data.

    ``online`` is the product's availability, ``device_online`` the
    thermostat's own. A mains-powered device reports no battery at all.
    """
    props: dict[str, object] = {
        **_THERMOSTAT_PROPS,
        "online": online,
        "device_online": device_online,
    }
    if battery is not None:
        props["battery"] = battery
    return props


def make_hub(**props: str) -> Device:
    """Return the hub, which the library lists under "parent"."""
    return Device(
        hive_id=HUB_ID,
        hive_name="Hive Hub",
        hive_type="hub",
        ha_type="parent",
        device_id=HUB_ID,
        device_name="Hive Hub",
        device_data={**_HUB_PROPS, "online": True, **props},
        parent_device=HUB_ID,
        ha_name="Hive Hub",
    )


def make_climate(
    *,
    parent_device: str | None = HUB_ID,
    online: bool = True,
    device_online: bool = True,
    boost: str | None = "OFF",
    battery: int | None = 80,
) -> Device:
    """Return a heating zone carried by the thermostat.

    It reads 19.5 °C, is set to 21 °C and follows its schedule; the
    thermostat's battery is at 80%.
    """
    return Device(
        hive_id=HEATING_ID,
        hive_name="Heating",
        hive_type="heating",
        ha_type="climate",
        device_id=THERMOSTAT_ID,
        device_name="Thermostat",
        device_data=_thermostat_props(
            online=online, device_online=device_online, battery=battery
        ),
        parent_device=parent_device,
        ha_name="Heating",
        temperature_unit="C",
        status={
            "current_temperature": 19.5,
            "target_temperature": 21.0,
            "action": True,
            "mode": "SCHEDULE",
            "boost": boost,
        },
        min_temp=5.0,
        max_temp=32.0,
    )


def make_water_heater(
    *,
    online: bool = True,
    device_online: bool = True,
    boost: str | None = "OFF",
    battery: int | None = 80,
) -> Device:
    """Return the hot water, carried by the same thermostat, on its schedule."""
    return Device(
        hive_id=HOT_WATER_ID,
        hive_name="Hot Water",
        hive_type="hotwater",
        ha_type="water_heater",
        device_id=THERMOSTAT_ID,
        device_name="Thermostat",
        device_data=_thermostat_props(
            online=online, device_online=device_online, battery=battery
        ),
        parent_device=HUB_ID,
        ha_name="Hot Water",
        status={"current_operation": "SCHEDULE", "boost": boost},
    )


def make_devices(
    *,
    hub: Device | None,
    climate: Sequence[Device] = (),
    water_heater: Sequence[Device] = (),
) -> dict[str, list[Device]]:
    """Return a device list as start_session builds it."""
    return {
        "parent": [hub] if hub else [],
        "climate": list(climate),
        "water_heater": list(water_heater),
    }


def make_mock_hive(devices: dict[str, list[Device]]) -> MagicMock:
    """Return a Hive session mock whose polls hand the devices back unchanged.

    start_session returns whatever device_list holds at the time, so a test
    can replace the devices before setting up the entry.
    """
    mock_hive = MagicMock()
    mock_hive.device_list = devices
    mock_hive.start_session = AsyncMock(
        side_effect=lambda config: mock_hive.device_list
    )
    mock_hive.update_data = AsyncMock(return_value=True)
    mock_hive.heating.get_climate = AsyncMock(side_effect=lambda device: device)
    mock_hive.hotwater.get_water_heater = AsyncMock(side_effect=lambda device: device)
    return mock_hive


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the config entry to Home Assistant and set it up."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
