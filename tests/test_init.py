"""Tests for the Hive integration __init__."""

from unittest.mock import AsyncMock, MagicMock, patch

from apyhiveapi import (
    Device,
    HiveApiError,
    HiveConnectionError,
    HiveDeviceOffline,
    HiveError,
    HiveInvalidPassword,
    HiveReauthRequired,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hive.const import (
    ATTR_ONOFF,
    ATTR_TIME_PERIOD,
    DOMAIN,
    SERVICE_BOOST_HEATING_OFF,
    SERVICE_BOOST_HEATING_ON,
    SERVICE_BOOST_HOT_WATER,
)
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    HVACMode,
)
from homeassistant.components.water_heater import (
    DOMAIN as WATER_HEATER_DOMAIN,
    STATE_ECO,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

_ENTRY_DATA = {
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "password",
    "tokens": {
        "AuthenticationResult": {
            "AccessToken": "mock-access-token",
            "RefreshToken": "mock-refresh-token",
        },
        "ChallengeName": "SUCCESS",
    },
}

_THERMOSTAT_PROPS = {
    "model": "SLT3",
    "version": "1.2.3",
    "manufacturer": "Hive",
    "online": True,
}


def _hub(**props: str) -> Device:
    """Return the hub, which the library lists under "parent"."""
    return Device(
        hive_id="hive-hub-id",
        hive_name="Hive Hub",
        hive_type="hub",
        ha_type="parent",
        device_id="hive-hub-id",
        device_name="Hive Hub",
        device_data={
            "model": "Hub",
            "version": "1.2.3",
            "manufacturer": "Hive",
            "online": True,
            **props,
        },
        parent_device="hive-hub-id",
        ha_name="Hive Hub",
    )


def _climate(parent_device: str | None = "hive-hub-id") -> Device:
    """Return a heating zone carried by a thermostat on the hub."""
    return Device(
        hive_id="hive-heating-id",
        hive_name="Heating",
        hive_type="heating",
        ha_type="climate",
        device_id="hive-thermostat-id",
        device_name="Thermostat",
        device_data=dict(_THERMOSTAT_PROPS),
        parent_device=parent_device,
        ha_name="Heating",
        temperature_unit="C",
        status={
            "current_temperature": 19.5,
            "target_temperature": 21.0,
            "action": True,
            "mode": "SCHEDULE",
            "boost": "OFF",
        },
        min_temp=5.0,
        max_temp=32.0,
    )


def _water_heater() -> Device:
    """Return the hot water, carried by the same thermostat."""
    return Device(
        hive_id="hive-hotwater-id",
        hive_name="Hot Water",
        hive_type="hotwater",
        ha_type="water_heater",
        device_id="hive-thermostat-id",
        device_name="Thermostat",
        device_data=dict(_THERMOSTAT_PROPS),
        parent_device="hive-hub-id",
        ha_name="Hot Water",
        status={"current_operation": "SCHEDULE"},
    )


def _devices(
    *,
    hub: Device | None,
    climate: list[Device] | None = None,
    water_heater: list[Device] | None = None,
) -> dict[str, list[Device]]:
    """Return a device list as start_session builds it."""
    return {
        "parent": [hub] if hub else [],
        "climate": climate or [],
        "water_heater": water_heater or [],
    }


def _make_mock_hive(devices: dict[str, list[Device]]) -> MagicMock:
    """Return a mocked Hive whose polls hand the devices back unchanged."""
    mock_hive = MagicMock()
    mock_hive.start_session = AsyncMock(return_value=devices)
    mock_hive.device_list = devices
    mock_hive.update_data = AsyncMock(return_value=True)
    mock_hive.heating.get_climate = AsyncMock(side_effect=lambda device: device)
    mock_hive.hotwater.get_water_heater = AsyncMock(side_effect=lambda device: device)
    return mock_hive


async def _setup_entry(hass: HomeAssistant, mock_hive: MagicMock) -> MockConfigEntry:
    """Add a config entry backed by mock_hive and set it up."""
    entry = MockConfigEntry(domain=DOMAIN, data=_ENTRY_DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.hive.Hive", return_value=mock_hive):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_hub_device_registers_mac_connection(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Hub device entry carries the hardware details Hive reports for it."""
    mock_hive = _make_mock_hive(_devices(hub=_hub(macAddress="00:1C:2B:1C:2E:68")))

    entry = await _setup_entry(hass, mock_hive)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, "hive-hub-id"), entry.entry_id
    )
    assert device is not None
    assert (dr.CONNECTION_NETWORK_MAC, "00:1c:2b:1c:2e:68") in device.connections
    assert device.name == "Hive Hub"
    assert device.model == "Hub"
    assert device.sw_version == "1.2.3"
    assert device.manufacturer == "Hive"


async def test_hub_device_no_mac_connection_when_absent(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Hub device entry has no MAC connection when macAddress is absent."""
    mock_hive = _make_mock_hive(_devices(hub=_hub()))  # no macAddress prop

    entry = await _setup_entry(hass, mock_hive)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, "hive-hub-id"), entry.entry_id
    )
    assert device is not None
    assert not any(
        conn_type == dr.CONNECTION_NETWORK_MAC for conn_type, _ in device.connections
    )


async def test_climate_device_links_to_hub(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """A thermostat's device points at the hub and its entity reports Hive's state."""
    mock_hive = _make_mock_hive(_devices(hub=_hub(), climate=[_climate()]))

    entry = await _setup_entry(hass, mock_hive)

    hub_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, "hive-hub-id"), entry.entry_id
    )
    thermostat = device_registry.async_get_device_by_identifier(
        (DOMAIN, "hive-thermostat-id"), entry.entry_id
    )
    assert hub_device is not None
    assert thermostat is not None
    assert thermostat.via_device_id == hub_device.id

    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, "hive-heating-id-heating"
    )
    assert entity_id
    state = hass.states.get(entity_id)
    assert state
    assert state.state == HVACMode.AUTO
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == 19.5
    assert state.attributes[ATTR_TEMPERATURE] == 21.0


async def test_setup_without_hub(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Entities are set up, with no via device, when Hive reports no hub."""
    mock_hive = _make_mock_hive(
        _devices(hub=None, climate=[_climate(parent_device=None)])
    )

    entry = await _setup_entry(hass, mock_hive)

    assert entry.state is ConfigEntryState.LOADED
    thermostat = device_registry.async_get_device_by_identifier(
        (DOMAIN, "hive-thermostat-id"), entry.entry_id
    )
    assert thermostat is not None
    assert thermostat.via_device_id is None


async def test_water_heater_entity(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """The water heater entity reports Hive's hot water mode."""
    mock_hive = _make_mock_hive(_devices(hub=_hub(), water_heater=[_water_heater()]))

    await _setup_entry(hass, mock_hive)

    entity_id = entity_registry.async_get_entity_id(
        WATER_HEATER_DOMAIN, DOMAIN, "hive-hotwater-id-hotwater"
    )
    assert entity_id
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_ECO


@pytest.mark.parametrize(
    ("error", "state", "reauth"),
    [
        (
            HiveReauthRequired("Hive asked for an SMS code"),
            ConfigEntryState.SETUP_ERROR,
            True,
        ),
        (
            HiveConnectionError("Timed out calling Hive"),
            ConfigEntryState.SETUP_RETRY,
            False,
        ),
        (
            HiveApiError("Hive returned no products or devices"),
            ConfigEntryState.SETUP_ERROR,
            False,
        ),
    ],
    ids=["reauth_required", "connection_error", "api_error"],
)
async def test_setup_entry_failure(
    hass: HomeAssistant,
    error: HiveError,
    state: ConfigEntryState,
    reauth: bool,
) -> None:
    """A failed session start lands in the state that makes HA react right.

    A rejected login starts a reauth flow, a transient failure is retried
    and anything else is a permanent error.
    """
    mock_hive = MagicMock()
    mock_hive.start_session = AsyncMock(side_effect=error)
    entry = MockConfigEntry(domain=DOMAIN, data=_ENTRY_DATA)
    entry.add_to_hass(hass)

    with (
        patch("custom_components.hive.Hive", return_value=mock_hive),
        # The reauth flow logs in straight away with the saved credentials.
        patch(
            "custom_components.hive.config_flow.Auth.login",
            side_effect=HiveInvalidPassword(),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is state
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == (
        [SOURCE_REAUTH] if reauth else []
    )


async def test_command_failure_raises_home_assistant_error(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """A command the library could not carry out fails the service call."""
    climate = _climate()
    mock_hive = _make_mock_hive(_devices(hub=_hub(), climate=[climate]))
    mock_hive.heating.set_mode = AsyncMock(
        side_effect=HiveDeviceOffline("Heating is offline")
    )
    await _setup_entry(hass, mock_hive)
    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, "hive-heating-id-heating"
    )

    with pytest.raises(HomeAssistantError, match="Heating is offline"):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.HEAT},
            blocking=True,
        )
    mock_hive.heating.set_mode.assert_awaited_once_with(climate, "MANUAL")


async def test_invalid_command_argument_raises_validation_error(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """An argument the library rejects is reported as a validation error."""
    climate = _climate()
    mock_hive = _make_mock_hive(_devices(hub=_hub(), climate=[climate]))
    mock_hive.heating.set_boost_on = AsyncMock(
        side_effect=ValueError("Boost minutes must be positive, not 0.0")
    )
    await _setup_entry(hass, mock_hive)
    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, "hive-heating-id-heating"
    )

    with pytest.raises(ServiceValidationError, match="Boost minutes must be positive"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_BOOST_HEATING_ON,
            {
                ATTR_ENTITY_ID: entity_id,
                ATTR_TIME_PERIOD: "00:00:30",
                ATTR_TEMPERATURE: 20.0,
            },
            blocking=True,
        )
    mock_hive.heating.set_boost_on.assert_awaited_once_with(climate, 0.0, 20.0)


async def test_hot_water_boost_service(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """The boost service passes the period to the library in minutes."""
    water_heater = _water_heater()
    mock_hive = _make_mock_hive(_devices(hub=_hub(), water_heater=[water_heater]))
    mock_hive.hotwater.set_boost_on = AsyncMock()
    await _setup_entry(hass, mock_hive)
    entity_id = entity_registry.async_get_entity_id(
        WATER_HEATER_DOMAIN, DOMAIN, "hive-hotwater-id-hotwater"
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_BOOST_HOT_WATER,
        {ATTR_ENTITY_ID: entity_id, ATTR_TIME_PERIOD: "01:30:00", ATTR_ONOFF: "on"},
        blocking=True,
    )

    mock_hive.hotwater.set_boost_on.assert_awaited_once_with(water_heater, 90.0)


async def test_services_registered_without_devices(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The entry loads and reloads, with its services, on a device-less account."""
    entry = MockConfigEntry(domain=DOMAIN, data=_ENTRY_DATA)
    entry.add_to_hass(hass)

    mock_hive = _make_mock_hive(_devices(hub=_hub()))

    with patch(
        "custom_components.hive.Hive",
        return_value=mock_hive,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        # Entity services must not depend on device discovery.
        assert hass.services.has_service(DOMAIN, SERVICE_BOOST_HOT_WATER)
        assert hass.services.has_service(DOMAIN, SERVICE_BOOST_HEATING_ON)
        assert hass.services.has_service(DOMAIN, SERVICE_BOOST_HEATING_OFF)

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert "Error setting up entry" not in caplog.text
    assert "Error unloading entry" not in caplog.text
