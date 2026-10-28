"""Tests for the Hive integration __init__."""

from unittest.mock import AsyncMock, MagicMock, call, patch

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

from custom_components.hive import async_remove_config_entry_device
from custom_components.hive.const import (
    ATTR_ONOFF,
    ATTR_TIME_PERIOD,
    DOMAIN,
    SERVICE_BOOST_HEATING_OFF,
    SERVICE_BOOST_HEATING_ON,
    SERVICE_BOOST_HOT_WATER,
)
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    PRESET_BOOST,
    PRESET_NONE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.water_heater import (
    ATTR_OPERATION_MODE,
    DOMAIN as WATER_HEATER_DOMAIN,
    SERVICE_SET_OPERATION_MODE,
    STATE_ECO,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from tests.common import (
    BATTERY_UNIQUE_ID,
    CLIMATE_UNIQUE_ID,
    DEVICE_DATA,
    ENTRY_DATA,
    HEATING_BOOST_UNIQUE_ID,
    HOT_WATER_BOOST_UNIQUE_ID,
    HUB_ID,
    THERMOSTAT_ID,
    WATER_HEATER_UNIQUE_ID,
    make_climate,
    make_devices,
    make_hub,
    make_water_heater,
    setup_entry,
)


async def test_hub_device_carries_hive_hardware_details(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The hub's device entry has the name, model, version, manufacturer and MAC Hive reports."""
    mock_hive.device_list = make_devices(hub=make_hub(macAddress="00:1C:2B:1C:2E:68"))

    await setup_entry(hass, mock_config_entry)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, HUB_ID), mock_config_entry.entry_id
    )
    assert device is not None
    assert device.name == "Hive Hub"
    assert device.model == "Hub"
    assert device.sw_version == "1.2.3"
    assert device.manufacturer == "Hive"
    assert (dr.CONNECTION_NETWORK_MAC, "00:1c:2b:1c:2e:68") in device.connections


async def test_hub_device_has_no_mac_connection_when_hive_reports_none(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A hub without a macAddress prop gets no MAC connection."""
    await setup_entry(hass, mock_config_entry)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, HUB_ID), mock_config_entry.entry_id
    )
    assert device is not None
    assert not any(
        conn_type == dr.CONNECTION_NETWORK_MAC for conn_type, _ in device.connections
    )


async def test_thermostat_device_links_to_hub(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The thermostat's device entry points at the hub as its via device."""
    await setup_entry(hass, mock_config_entry)

    hub = device_registry.async_get_device_by_identifier(
        (DOMAIN, HUB_ID), mock_config_entry.entry_id
    )
    thermostat = device_registry.async_get_device_by_identifier(
        (DOMAIN, THERMOSTAT_ID), mock_config_entry.entry_id
    )
    assert hub is not None
    assert thermostat is not None
    assert thermostat.via_device_id == hub.id


async def test_entities_are_set_up_without_a_hub(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """When Hive reports no hub the entry still loads, with no via device."""
    mock_hive.device_list = make_devices(
        hub=None, climate=[make_climate(parent_device=None)]
    )

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    thermostat = device_registry.async_get_device_by_identifier(
        (DOMAIN, THERMOSTAT_ID), mock_config_entry.entry_id
    )
    assert thermostat is not None
    assert thermostat.via_device_id is None


@pytest.mark.parametrize(
    ("climate", "state", "preset", "current_temperature"),
    [
        pytest.param(make_climate(), HVACMode.AUTO, PRESET_NONE, 19.5, id="schedule"),
        pytest.param(
            make_climate(boost="ON"), HVACMode.HEAT, PRESET_BOOST, 19.5, id="boosting"
        ),
        pytest.param(
            make_climate(online=False), STATE_UNAVAILABLE, None, None, id="offline"
        ),
    ],
)
async def test_climate_state_reflects_hive(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    climate: Device,
    state: str,
    preset: str | None,
    current_temperature: float | None,
) -> None:
    """The climate entity reports the mode, preset and temperature the library gives it."""
    mock_hive.device_list = make_devices(hub=make_hub(), climate=[climate])

    await setup_entry(hass, mock_config_entry)

    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, CLIMATE_UNIQUE_ID
    )
    assert entity_id
    entity_state = hass.states.get(entity_id)
    assert entity_state
    assert entity_state.state == state
    assert entity_state.attributes.get(ATTR_PRESET_MODE) == preset
    assert entity_state.attributes.get(ATTR_CURRENT_TEMPERATURE) == current_temperature


@pytest.mark.parametrize(
    ("water_heater", "state"),
    [
        pytest.param(make_water_heater(), STATE_ECO, id="schedule"),
        pytest.param(make_water_heater(online=False), STATE_UNAVAILABLE, id="offline"),
    ],
)
async def test_water_heater_state_reflects_hive(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    water_heater: Device,
    state: str,
) -> None:
    """The water heater entity reports the operation the library gives it."""
    mock_hive.device_list = make_devices(hub=make_hub(), water_heater=[water_heater])

    await setup_entry(hass, mock_config_entry)

    entity_id = entity_registry.async_get_entity_id(
        WATER_HEATER_DOMAIN, DOMAIN, WATER_HEATER_UNIQUE_ID
    )
    assert entity_id
    entity_state = hass.states.get(entity_id)
    assert entity_state
    assert entity_state.state == state


@pytest.mark.parametrize(
    ("climate", "water_heater", "unique_id", "state"),
    [
        pytest.param(
            make_climate(boost="ON"),
            make_water_heater(),
            HEATING_BOOST_UNIQUE_ID,
            STATE_ON,
            id="heating-boosting",
        ),
        pytest.param(
            make_climate(),
            make_water_heater(),
            HEATING_BOOST_UNIQUE_ID,
            STATE_OFF,
            id="heating-not-boosting",
        ),
        pytest.param(
            make_climate(),
            make_water_heater(boost="ON"),
            HOT_WATER_BOOST_UNIQUE_ID,
            STATE_ON,
            id="hot-water-boosting",
        ),
        pytest.param(
            make_climate(),
            make_water_heater(boost=None),
            HOT_WATER_BOOST_UNIQUE_ID,
            STATE_UNKNOWN,
            id="hot-water-unknown",
        ),
        pytest.param(
            make_climate(),
            make_water_heater(online=False),
            HOT_WATER_BOOST_UNIQUE_ID,
            STATE_UNAVAILABLE,
            id="hot-water-offline",
        ),
    ],
)
async def test_boost_binary_sensor_reflects_hive(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    climate: Device,
    water_heater: Device,
    unique_id: str,
    state: str,
) -> None:
    """Each boost binary sensor reports the boost status the library gives it.

    The unique IDs are core's, so the entities core created carry over.
    """
    mock_hive.device_list = make_devices(
        hub=make_hub(), climate=[climate], water_heater=[water_heater]
    )

    await setup_entry(hass, mock_config_entry)

    entity_id = entity_registry.async_get_entity_id(
        BINARY_SENSOR_DOMAIN, DOMAIN, unique_id
    )
    assert entity_id
    entity_state = hass.states.get(entity_id)
    assert entity_state
    assert entity_state.state == state


@pytest.mark.parametrize(
    ("climate", "state"),
    [
        pytest.param(make_climate(), "80", id="charged"),
        pytest.param(make_climate(battery=15), "15", id="low"),
        # The receiver is unreachable but the thermostat still reports.
        pytest.param(make_climate(online=False), "80", id="zone-offline"),
        # The zone stays online through its receiver when the thermostat dies.
        pytest.param(
            make_climate(device_online=False),
            STATE_UNAVAILABLE,
            id="thermostat-offline",
        ),
    ],
)
async def test_battery_sensor_reflects_hive(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    climate: Device,
    state: str,
) -> None:
    """The battery sensor reports the level of the thermostat that carries the heating zone.

    It follows the thermostat's own online flag, not the zone's. The unique
    ID is core's, so the entity core created carries over.
    """
    mock_hive.device_list = make_devices(hub=make_hub(), climate=[climate])

    await setup_entry(hass, mock_config_entry)

    entity_id = entity_registry.async_get_entity_id(
        SENSOR_DOMAIN, DOMAIN, BATTERY_UNIQUE_ID
    )
    assert entity_id
    entity_state = hass.states.get(entity_id)
    assert entity_state
    assert entity_state.state == state


@pytest.mark.parametrize(
    ("climate", "water_heater", "unique_ids"),
    [
        pytest.param(
            [make_climate()],
            [make_water_heater()],
            [BATTERY_UNIQUE_ID],
            id="shared-thermostat",
        ),
        pytest.param(
            [], [make_water_heater()], [BATTERY_UNIQUE_ID], id="hot-water-only"
        ),
        pytest.param([make_climate(battery=None)], [], [], id="mains-powered"),
    ],
)
async def test_battery_sensors_are_created_per_device(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    climate: list[Device],
    water_heater: list[Device],
    unique_ids: list[str],
) -> None:
    """A thermostat gets one battery sensor however many products it carries, and none without a battery."""
    mock_hive.device_list = make_devices(
        hub=make_hub(), climate=climate, water_heater=water_heater
    )

    await setup_entry(hass, mock_config_entry)

    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    assert [
        entry.unique_id for entry in entries if entry.domain == SENSOR_DOMAIN
    ] == unique_ids


@pytest.mark.parametrize(
    ("error", "state", "flow_sources"),
    [
        pytest.param(
            HiveReauthRequired("Hive asked for an SMS code"),
            ConfigEntryState.SETUP_ERROR,
            [SOURCE_REAUTH],
            id="reauth-required",
        ),
        pytest.param(
            HiveConnectionError("Timed out calling Hive"),
            ConfigEntryState.SETUP_RETRY,
            [],
            id="connection-error",
        ),
        pytest.param(
            HiveApiError("Hive returned no products or devices"),
            ConfigEntryState.SETUP_ERROR,
            [],
            id="refused",
        ),
    ],
)
async def test_failed_session_start_sets_the_entry_state(
    hass: HomeAssistant,
    mock_hive: MagicMock,
    mock_auth: MagicMock,
    mock_config_entry: MockConfigEntry,
    error: HiveError,
    state: ConfigEntryState,
    flow_sources: list[str],
) -> None:
    """A rejected login starts a reauth flow, a transient failure is retried, anything else is a setup error."""
    mock_hive.start_session.side_effect = error
    # The reauth flow logs in straight away with the saved credentials.
    mock_auth.login.side_effect = HiveInvalidPassword()

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is state
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == flow_sources


@pytest.mark.parametrize(
    ("domain", "service", "data", "method", "args"),
    [
        pytest.param(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_HVAC_MODE: HVACMode.HEAT},
            "set_mode",
            ("MANUAL",),
            id="hvac-mode",
        ),
        pytest.param(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_TEMPERATURE: 20.5},
            "set_target_temperature",
            (20.5,),
            id="target-temperature",
        ),
        # The boost preset runs for 30 minutes at half a degree above the current 19.5.
        pytest.param(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_PRESET_MODE: PRESET_BOOST},
            "set_boost_on",
            (30, 20.0),
            id="boost-preset",
        ),
        pytest.param(
            DOMAIN,
            SERVICE_BOOST_HEATING_ON,
            {ATTR_TIME_PERIOD: "01:00:00", ATTR_TEMPERATURE: 22.0},
            "set_boost_on",
            (60.0, 22.0),
            id="boost-heating-on",
        ),
        pytest.param(
            DOMAIN,
            SERVICE_BOOST_HEATING_OFF,
            {},
            "set_boost_off",
            (),
            id="boost-heating-off",
        ),
    ],
)
async def test_climate_service_calls_the_heating_command(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    domain: str,
    service: str,
    data: dict[str, object],
    method: str,
    args: tuple[object, ...],
) -> None:
    """A climate service call becomes the matching library command, in Hive's units."""
    await setup_entry(hass, mock_config_entry)
    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, CLIMATE_UNIQUE_ID
    )
    command = AsyncMock()
    setattr(mock_hive.heating, method, command)

    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )

    command.assert_awaited_once_with(mock_hive.device_list["climate"][0], *args)


@pytest.mark.parametrize(
    ("data", "mode_calls"),
    [
        pytest.param({ATTR_TEMPERATURE: 24.0}, [], id="temperature-only"),
        pytest.param(
            {ATTR_HVAC_MODE: HVACMode.HEAT, ATTR_TEMPERATURE: 24.0},
            ["MANUAL"],
            id="with-hvac-mode",
        ),
    ],
)
async def test_set_temperature_sets_the_hvac_mode_first(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    data: dict[str, object],
    mode_calls: list[str],
) -> None:
    """Setting the temperature with an hvac mode sets the mode, then the temperature."""
    await setup_entry(hass, mock_config_entry)
    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, CLIMATE_UNIQUE_ID
    )
    # One parent mock records the order of the two commands.
    commands = MagicMock()
    for method in ("set_mode", "set_target_temperature"):
        command = AsyncMock()
        setattr(mock_hive.heating, method, command)
        commands.attach_mock(command, method)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: entity_id, **data},
        blocking=True,
    )

    device = mock_hive.device_list["climate"][0]
    assert commands.mock_calls == [
        *(call.set_mode(device, mode) for mode in mode_calls),
        call.set_target_temperature(device, 24.0),
    ]


async def test_ending_the_boost_preset_calls_set_boost_off(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Setting the preset back to none while boosting ends the boost."""
    mock_hive.device_list = make_devices(
        hub=make_hub(), climate=[make_climate(boost="ON")]
    )
    await setup_entry(hass, mock_config_entry)
    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, CLIMATE_UNIQUE_ID
    )
    mock_hive.heating.set_boost_off = AsyncMock()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: PRESET_NONE},
        blocking=True,
    )

    mock_hive.heating.set_boost_off.assert_awaited_once_with(
        mock_hive.device_list["climate"][0]
    )


@pytest.mark.parametrize(
    ("domain", "service", "data", "method", "args"),
    [
        pytest.param(
            WATER_HEATER_DOMAIN,
            SERVICE_TURN_ON,
            {},
            "set_mode",
            ("MANUAL",),
            id="turn-on",
        ),
        pytest.param(
            WATER_HEATER_DOMAIN,
            SERVICE_TURN_OFF,
            {},
            "set_mode",
            ("OFF",),
            id="turn-off",
        ),
        pytest.param(
            WATER_HEATER_DOMAIN,
            SERVICE_SET_OPERATION_MODE,
            {ATTR_OPERATION_MODE: STATE_ECO},
            "set_mode",
            ("SCHEDULE",),
            id="operation-mode",
        ),
        pytest.param(
            DOMAIN,
            SERVICE_BOOST_HOT_WATER,
            {ATTR_TIME_PERIOD: "01:30:00", ATTR_ONOFF: "on"},
            "set_boost_on",
            (90.0,),
            id="boost-on",
        ),
        pytest.param(
            DOMAIN,
            SERVICE_BOOST_HOT_WATER,
            {ATTR_ONOFF: "off"},
            "set_boost_off",
            (),
            id="boost-off",
        ),
    ],
)
async def test_water_heater_service_calls_the_hot_water_command(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    domain: str,
    service: str,
    data: dict[str, object],
    method: str,
    args: tuple[object, ...],
) -> None:
    """A water heater service call becomes the matching library command."""
    await setup_entry(hass, mock_config_entry)
    entity_id = entity_registry.async_get_entity_id(
        WATER_HEATER_DOMAIN, DOMAIN, WATER_HEATER_UNIQUE_ID
    )
    command = AsyncMock()
    setattr(mock_hive.hotwater, method, command)

    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )

    command.assert_awaited_once_with(mock_hive.device_list["water_heater"][0], *args)


async def test_failed_command_raises_home_assistant_error(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A command the library could not carry out fails the service call with its message."""
    await setup_entry(hass, mock_config_entry)
    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, CLIMATE_UNIQUE_ID
    )
    mock_hive.heating.set_mode = AsyncMock(
        side_effect=HiveDeviceOffline("Heating is offline")
    )

    with pytest.raises(HomeAssistantError, match="Heating is offline"):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.HEAT},
            blocking=True,
        )


async def test_rejected_command_argument_raises_validation_error(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An argument the library rejects is reported as a validation error, not a crash."""
    await setup_entry(hass, mock_config_entry)
    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, CLIMATE_UNIQUE_ID
    )
    mock_hive.heating.set_boost_on = AsyncMock(
        side_effect=ValueError("Boost minutes must be positive, not 0.0")
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


async def test_services_are_registered_without_devices(
    hass: HomeAssistant,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The entry loads and reloads, with its services, on an account with only a hub."""
    mock_hive.device_list = make_devices(hub=make_hub())

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    # Entity services must not depend on device discovery.
    assert hass.services.has_service(DOMAIN, SERVICE_BOOST_HOT_WATER)
    assert hass.services.has_service(DOMAIN, SERVICE_BOOST_HEATING_ON)
    assert hass.services.has_service(DOMAIN, SERVICE_BOOST_HEATING_OFF)

    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert "Error setting up entry" not in caplog.text
    assert "Error unloading entry" not in caplog.text


async def test_removing_the_entry_forgets_the_hive_device(
    hass: HomeAssistant,
    mock_hive: MagicMock,
) -> None:
    """Removing the entry tells Hive to forget the registered device."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={**ENTRY_DATA, "device_data": DEVICE_DATA}
    )
    await setup_entry(hass, entry)

    with patch("custom_components.hive.Auth", autospec=True) as mock_auth_class:
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []
    mock_auth_class.return_value.forget_device.assert_awaited_once_with(
        "mock-access-token", "mock-device-key"
    )


async def test_devices_can_be_removed_from_the_entry(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The device registry may remove any of the integration's devices."""
    await setup_entry(hass, mock_config_entry)
    thermostat = device_registry.async_get_device_by_identifier(
        (DOMAIN, THERMOSTAT_ID), mock_config_entry.entry_id
    )
    assert thermostat is not None

    assert await async_remove_config_entry_device(hass, mock_config_entry, thermostat)
