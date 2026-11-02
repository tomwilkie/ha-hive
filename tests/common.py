"""Helpers shared by the Hive test modules.

The Hive snapshot the mocked session returns, built from the library's own
dataclasses so that a renamed field fails the tests, and the config entry
setup. Fixtures live in conftest.py.
"""

from collections.abc import Iterable

from freezegun.api import FrozenDateTimeFactory
from hiveheating import Device, HeatingProduct, HotWaterProduct, Nodes, Product, User
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.hive.coordinator import SCAN_INTERVAL
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
ZONE_ID = "hive-zone-id"
CLIMATE_UNIQUE_ID = f"{HEATING_ID}-heating"
WATER_HEATER_UNIQUE_ID = f"{HOT_WATER_ID}-hotwater"
HEATING_BOOST_UNIQUE_ID = f"{HEATING_ID}-Heating_Boost"
HOT_WATER_BOOST_UNIQUE_ID = f"{HOT_WATER_ID}-Hotwater_Boost"
BATTERY_UNIQUE_ID = f"{THERMOSTAT_ID}-Battery"

HUB = Device(
    id=HUB_ID,
    type="hub",
    name="Hive Hub",
    online=True,
    model="Hub",
    manufacturer="Hive",
    version="1.2.3",
    zone=None,
    battery=None,
    mac_address=None,
)

# The thermostat in the heating zone, with its battery at 80%.
THERMOSTAT = Device(
    id=THERMOSTAT_ID,
    type="thermostatui",
    name="Thermostat",
    online=True,
    model="SLT3",
    manufacturer="Hive",
    version="1.2.3",
    zone=ZONE_ID,
    battery=80,
    mac_address=None,
)

# A heating zone, run by its receiver: it reads 19.54 °C, is set to 21 °C,
# is calling for heat and follows its schedule.
HEATING = HeatingProduct(
    id=HEATING_ID,
    type="heating",
    name="Heating",
    online=True,
    model="SLR2",
    version="2.1.0",
    zone=ZONE_ID,
    temperature=19.54,
    working=True,
    mode="SCHEDULE",
    target=21.0,
    boost=None,
    previous_mode=None,
    previous_target=None,
)

# The hot water, run by the same receiver, on its schedule.
HOT_WATER = HotWaterProduct(
    id=HOT_WATER_ID,
    type="hotwater",
    name="Hot Water",
    online=True,
    model="SLR2",
    version="2.1.0",
    zone=ZONE_ID,
    mode="SCHEDULE",
    status="OFF",
    boost=None,
    previous_mode=None,
)


def make_nodes(
    products: Iterable[Product] = (HEATING, HOT_WATER),
    devices: Iterable[Device] = (HUB, THERMOSTAT),
    temperature_unit: str | None = "C",
) -> Nodes:
    """Return a GET /nodes/all snapshot, by default a hub, one zone and hot water."""
    return Nodes(
        user=User(temperature_unit=temperature_unit),
        products={product.id: product for product in products},
        devices={device.id: device for device in devices},
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the config entry to Home Assistant and set it up."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let one poll interval pass, so the coordinator fetches Hive again."""
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
