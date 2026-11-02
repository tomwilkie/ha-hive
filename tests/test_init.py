"""Tests for the Hive integration."""

from dataclasses import replace
from unittest.mock import MagicMock, call, patch

from freezegun.api import FrozenDateTimeFactory
from hiveheating import (
    Device,
    HiveApiError,
    HiveConnectionError,
    HiveError,
    HiveInvalidPassword,
    HiveReauthRequired,
    Nodes,
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
from custom_components.hive.coordinator import MAX_DEGRADED_POLLS
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    PRESET_BOOST,
    PRESET_NONE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
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
    ATTR_FRIENDLY_NAME,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from tests.common import (
    BATTERY_UNIQUE_ID,
    CLIMATE_UNIQUE_ID,
    DEVICE_DATA,
    ENTRY_DATA,
    HEATING,
    HEATING_BOOST_UNIQUE_ID,
    HEATING_ID,
    HOT_WATER,
    HOT_WATER_BOOST_UNIQUE_ID,
    HUB,
    HUB_ID,
    THERMOSTAT,
    THERMOSTAT_ID,
    WATER_HEATER_UNIQUE_ID,
    make_nodes,
    poll,
    setup_entry,
)

# Hive's reply when it sends a product's state with only its name
# (hiveheating issue #20): the state fields are None and it reads offline.
DEGRADED_HEATING = replace(
    HEATING,
    online=False,
    mode=None,
    target=None,
    boost=None,
    previous_mode=None,
    previous_target=None,
)


def get_state(
    hass: HomeAssistant, entity_registry: er.EntityRegistry, domain: str, unique_id: str
) -> State:
    """Return the state of the entity with the unique ID."""
    entity_id = entity_registry.async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id
    state = hass.states.get(entity_id)
    assert state
    return state


async def call_service(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    target: tuple[str, str],
    service: tuple[str, str],
    data: dict[str, object],
) -> None:
    """Call a service on the entity with the given domain and unique ID."""
    entity_id = entity_registry.async_get_entity_id(target[0], DOMAIN, target[1])
    assert entity_id
    await hass.services.async_call(
        service[0], service[1], {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


def get_device(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry, device_id: str
) -> dr.DeviceEntry:
    """Return the registry entry of the Hive device."""
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, device_id), entry.entry_id
    )
    assert device is not None
    return device


async def test_hub_device_carries_hive_hardware_details(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The hub's device entry has the name, model, version, manufacturer and MAC Hive reports."""
    mock_hive.get_nodes.return_value = make_nodes(
        products=[], devices=[replace(HUB, mac_address="00:1C:2B:1C:2E:68")]
    )

    await setup_entry(hass, mock_config_entry)

    device = get_device(device_registry, mock_config_entry, HUB_ID)
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
    """A hub without a MAC address gets no MAC connection."""
    await setup_entry(hass, mock_config_entry)

    device = get_device(device_registry, mock_config_entry, HUB_ID)
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

    hub = get_device(device_registry, mock_config_entry, HUB_ID)
    thermostat = get_device(device_registry, mock_config_entry, THERMOSTAT_ID)
    assert thermostat.via_device_id == hub.id


async def test_entities_are_set_up_without_a_hub(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """When Hive reports no hub the entry still loads, with no via device."""
    mock_hive.get_nodes.return_value = make_nodes(devices=[THERMOSTAT])

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    thermostat = get_device(device_registry, mock_config_entry, THERMOSTAT_ID)
    assert thermostat.via_device_id is None


@pytest.mark.parametrize(
    ("nodes", "unique_id", "device_id", "name", "model", "manufacturer", "sw_version"),
    [
        pytest.param(
            make_nodes(),
            CLIMATE_UNIQUE_ID,
            THERMOSTAT_ID,
            "Thermostat",
            "SLT3",
            "Hive",
            "1.2.3",
            id="heating-on-the-thermostat-in-its-zone",
        ),
        pytest.param(
            make_nodes(products=[HEATING], devices=[HUB]),
            CLIMATE_UNIQUE_ID,
            HEATING_ID,
            "Heating",
            "SLR2",
            None,
            "2.1.0",
            id="heating-without-a-thermostat-is-its-own-device",
        ),
        pytest.param(
            make_nodes(products=[replace(HEATING, zone=None)]),
            CLIMATE_UNIQUE_ID,
            HEATING_ID,
            "Heating",
            "SLR2",
            None,
            "2.1.0",
            id="heating-without-a-zone-is-its-own-device",
        ),
        pytest.param(
            make_nodes(products=[replace(HEATING, name="Receiver")], devices=[HUB]),
            CLIMATE_UNIQUE_ID,
            HEATING_ID,
            "Heating",
            "SLR2",
            None,
            "2.1.0",
            id="receiver-shown-as-heating",
        ),
    ],
)
async def test_climate_entity_belongs_to_the_hardware_that_carries_it(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    nodes: Nodes,
    unique_id: str,
    device_id: str,
    name: str,
    model: str,
    manufacturer: str | None,
    sw_version: str,
) -> None:
    """A product's device is its thermostat, or the product itself, linked to the hub."""
    mock_hive.get_nodes.return_value = nodes

    await setup_entry(hass, mock_config_entry)

    entity_id = entity_registry.async_get_entity_id(CLIMATE_DOMAIN, DOMAIN, unique_id)
    assert entity_id
    entry = entity_registry.async_get(entity_id)
    assert entry
    device = get_device(device_registry, mock_config_entry, device_id)
    assert entry.device_id == device.id
    assert (device.name, device.model, device.manufacturer, device.sw_version) == (
        name,
        model,
        manufacturer,
        sw_version,
    )
    assert (
        device.via_device_id
        == get_device(device_registry, mock_config_entry, HUB_ID).id
    )


async def test_products_that_appear_later_are_added_on_reload(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Entities are discovered from the first refresh only; a reload picks up new products."""
    mock_hive.get_nodes.return_value = make_nodes(products=[HEATING])
    await setup_entry(hass, mock_config_entry)
    mock_hive.get_nodes.return_value = make_nodes()

    await poll(hass, freezer)

    assert not entity_registry.async_get_entity_id(
        WATER_HEATER_DOMAIN, DOMAIN, WATER_HEATER_UNIQUE_ID
    )

    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get_entity_id(
        WATER_HEATER_DOMAIN, DOMAIN, WATER_HEATER_UNIQUE_ID
    )


@pytest.mark.parametrize(
    ("heating", "state", "preset", "action"),
    [
        pytest.param(
            HEATING, HVACMode.AUTO, PRESET_NONE, HVACAction.HEATING, id="schedule"
        ),
        pytest.param(
            replace(HEATING, mode="MANUAL", working=False),
            HVACMode.HEAT,
            PRESET_NONE,
            HVACAction.IDLE,
            id="manual",
        ),
        pytest.param(
            replace(HEATING, mode="OFF", working=False),
            HVACMode.OFF,
            PRESET_NONE,
            HVACAction.IDLE,
            id="off",
        ),
        pytest.param(
            replace(HEATING, mode="BOOST", boost=30, previous_mode=False),
            HVACMode.HEAT,
            PRESET_BOOST,
            HVACAction.HEATING,
            id="boosting",
        ),
    ],
)
async def test_climate_state_reflects_hive(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    heating: Device,
    state: str,
    preset: str,
    action: HVACAction,
) -> None:
    """The climate entity reports the mode, preset, action and temperatures Hive reports."""
    mock_hive.get_nodes.return_value = make_nodes(products=[heating])

    await setup_entry(hass, mock_config_entry)

    entity_state = get_state(hass, entity_registry, CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID)
    assert entity_state.state == state
    assert entity_state.attributes[ATTR_PRESET_MODE] == preset
    assert entity_state.attributes[ATTR_HVAC_ACTION] == action
    assert entity_state.attributes[ATTR_CURRENT_TEMPERATURE] == 19.5
    assert entity_state.attributes[ATTR_TEMPERATURE] == 21.0


async def test_climate_uses_the_account_temperature_unit(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Temperatures are read in the account's unit and shown in Home Assistant's."""
    mock_hive.get_nodes.return_value = make_nodes(
        products=[replace(HEATING, temperature=68.0, target=77.0)],
        temperature_unit="F",
    )

    await setup_entry(hass, mock_config_entry)

    entity_state = get_state(hass, entity_registry, CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID)
    assert entity_state.attributes[ATTR_CURRENT_TEMPERATURE] == 20.0
    assert entity_state.attributes[ATTR_TEMPERATURE] == 25.0


@pytest.mark.parametrize(
    ("nodes", "unique_id", "state"),
    [
        pytest.param(
            make_nodes(products=[replace(HEATING, online=False)]),
            CLIMATE_UNIQUE_ID,
            STATE_UNAVAILABLE,
            id="zone-offline",
        ),
        # The zone stays online through its receiver when the thermostat dies.
        pytest.param(
            make_nodes(devices=[HUB, replace(THERMOSTAT, online=False)]),
            CLIMATE_UNIQUE_ID,
            HVACMode.AUTO,
            id="thermostat-offline",
        ),
    ],
)
async def test_climate_availability_follows_the_product(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    nodes: Nodes,
    unique_id: str,
    state: str,
) -> None:
    """A zone is available while its product is online, whatever its thermostat reports."""
    mock_hive.get_nodes.return_value = nodes

    await setup_entry(hass, mock_config_entry)

    assert get_state(hass, entity_registry, CLIMATE_DOMAIN, unique_id).state == state


@pytest.mark.parametrize(
    ("hot_water", "state"),
    [
        pytest.param(HOT_WATER, STATE_ECO, id="schedule"),
        pytest.param(replace(HOT_WATER, mode="MANUAL"), STATE_ON, id="manual-is-on"),
        pytest.param(replace(HOT_WATER, mode="OFF"), STATE_OFF, id="off"),
        pytest.param(
            replace(HOT_WATER, mode="BOOST", boost=30, previous_mode=False),
            STATE_OFF,
            id="boosting-from-off",
        ),
        pytest.param(
            replace(HOT_WATER, mode="BOOST", boost=30, previous_mode="MANUAL"),
            STATE_ON,
            id="boosting-from-manual",
        ),
        pytest.param(replace(HOT_WATER, online=False), STATE_UNAVAILABLE, id="offline"),
    ],
)
async def test_water_heater_state_reflects_hive(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    hot_water: Device,
    state: str,
) -> None:
    """The water heater reports the operation Hive reports, or the one a boost returns to."""
    mock_hive.get_nodes.return_value = make_nodes(products=[hot_water])

    await setup_entry(hass, mock_config_entry)

    entity_state = get_state(
        hass, entity_registry, WATER_HEATER_DOMAIN, WATER_HEATER_UNIQUE_ID
    )
    assert entity_state.state == state


@pytest.mark.parametrize(
    ("nodes", "unique_id", "state"),
    [
        pytest.param(
            make_nodes(products=[replace(HEATING, mode="BOOST", boost=30)]),
            HEATING_BOOST_UNIQUE_ID,
            STATE_ON,
            id="heating-boosting",
        ),
        pytest.param(
            make_nodes(), HEATING_BOOST_UNIQUE_ID, STATE_OFF, id="heating-not-boosting"
        ),
        pytest.param(
            make_nodes(products=[replace(HOT_WATER, mode="BOOST", boost=30)]),
            HOT_WATER_BOOST_UNIQUE_ID,
            STATE_ON,
            id="hot-water-boosting",
        ),
        pytest.param(
            make_nodes(products=[replace(HOT_WATER, online=False)]),
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
    nodes: Nodes,
    unique_id: str,
    state: str,
) -> None:
    """Each boost binary sensor is on while Hive reports boost minutes.

    The unique IDs are core's, so the entities core created carry over.
    """
    mock_hive.get_nodes.return_value = nodes

    await setup_entry(hass, mock_config_entry)

    assert (
        get_state(hass, entity_registry, BINARY_SENSOR_DOMAIN, unique_id).state == state
    )


@pytest.mark.parametrize(
    ("nodes", "state"),
    [
        pytest.param(make_nodes(), "80", id="charged"),
        pytest.param(
            make_nodes(devices=[HUB, replace(THERMOSTAT, battery=15)]), "15", id="low"
        ),
        # The receiver is unreachable but the thermostat still reports.
        pytest.param(
            make_nodes(products=[replace(HEATING, online=False)]),
            "80",
            id="zone-offline",
        ),
        # The zone stays online through its receiver when the thermostat dies.
        pytest.param(
            make_nodes(devices=[HUB, replace(THERMOSTAT, online=False)]),
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
    nodes: Nodes,
    state: str,
) -> None:
    """The battery sensor reports the level of the thermostat that carries the heating zone.

    It follows the thermostat's own online flag, not the zone's. The unique
    ID is core's, so the entity core created carries over.
    """
    mock_hive.get_nodes.return_value = nodes

    await setup_entry(hass, mock_config_entry)

    assert (
        get_state(hass, entity_registry, SENSOR_DOMAIN, BATTERY_UNIQUE_ID).state
        == state
    )


@pytest.mark.parametrize(
    ("nodes", "unique_ids"),
    [
        pytest.param(make_nodes(), [BATTERY_UNIQUE_ID], id="shared-thermostat"),
        pytest.param(
            make_nodes(products=[HOT_WATER]), [BATTERY_UNIQUE_ID], id="hot-water-only"
        ),
        pytest.param(
            make_nodes(devices=[HUB, replace(THERMOSTAT, battery=None)]),
            [],
            id="mains-powered",
        ),
        pytest.param(make_nodes(devices=[HUB]), [], id="no-hardware"),
    ],
)
async def test_battery_sensors_are_created_per_device(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    nodes: Nodes,
    unique_ids: list[str],
) -> None:
    """A thermostat gets one battery sensor however many products it carries, and none without a battery."""
    mock_hive.get_nodes.return_value = nodes

    await setup_entry(hass, mock_config_entry)

    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    assert [
        entry.unique_id for entry in entries if entry.domain == SENSOR_DOMAIN
    ] == unique_ids


@pytest.mark.parametrize(
    ("domain", "unique_id", "friendly_name"),
    [
        pytest.param(CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID, "Thermostat", id="climate"),
        pytest.param(
            WATER_HEATER_DOMAIN,
            WATER_HEATER_UNIQUE_ID,
            "Thermostat Hot water",
            id="hot-water",
        ),
        pytest.param(
            BINARY_SENSOR_DOMAIN,
            HEATING_BOOST_UNIQUE_ID,
            "Thermostat Boost",
            id="heating-boost",
        ),
        pytest.param(
            BINARY_SENSOR_DOMAIN,
            HOT_WATER_BOOST_UNIQUE_ID,
            "Thermostat Hot water boost",
            id="hot-water-boost",
        ),
        pytest.param(
            SENSOR_DOMAIN, BATTERY_UNIQUE_ID, "Thermostat Battery level", id="battery"
        ),
    ],
)
async def test_entities_are_named_from_their_device(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    domain: str,
    unique_id: str,
    friendly_name: str,
) -> None:
    """Home Assistant composes each friendly name from the device's name and the entity's own."""
    await setup_entry(hass, mock_config_entry)

    entity_id = entity_registry.async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id
    entry = entity_registry.async_get(entity_id)
    assert entry
    assert entry.has_entity_name is True
    entity_state = hass.states.get(entity_id)
    assert entity_state
    assert entity_state.attributes[ATTR_FRIENDLY_NAME] == friendly_name


async def test_renaming_the_device_renames_its_entities(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A device name set by the user carries into its entities' friendly names, with no entity override."""
    await setup_entry(hass, mock_config_entry)
    device = get_device(device_registry, mock_config_entry, THERMOSTAT_ID)

    device_registry.async_update_device(device.id, name_by_user="Hallway - Hive")
    await hass.async_block_till_done()

    entity_state = get_state(hass, entity_registry, SENSOR_DOMAIN, BATTERY_UNIQUE_ID)
    assert entity_state.attributes[ATTR_FRIENDLY_NAME] == "Hallway - Hive Battery level"


@pytest.mark.parametrize(
    ("new_session_error", "get_nodes_error", "state", "flow_sources"),
    [
        pytest.param(
            HiveReauthRequired("The config has no tokens"),
            None,
            ConfigEntryState.SETUP_ERROR,
            [SOURCE_REAUTH],
            id="no-tokens",
        ),
        pytest.param(
            None,
            HiveReauthRequired("Hive asked for an SMS code"),
            ConfigEntryState.SETUP_ERROR,
            [SOURCE_REAUTH],
            id="reauth-required",
        ),
        pytest.param(
            None,
            HiveConnectionError("Timed out calling Hive"),
            ConfigEntryState.SETUP_RETRY,
            [],
            id="connection-error",
        ),
        pytest.param(
            None,
            HiveApiError("Hive refused the request"),
            ConfigEntryState.SETUP_ERROR,
            [],
            id="refused",
        ),
    ],
)
async def test_failed_setup_sets_the_entry_state(
    hass: HomeAssistant,
    mock_hive: MagicMock,
    mock_auth: MagicMock,
    mock_config_entry: MockConfigEntry,
    new_session_error: HiveError | None,
    get_nodes_error: HiveError | None,
    state: ConfigEntryState,
    flow_sources: list[str],
) -> None:
    """A rejected login starts a reauth flow, a transient failure is retried, anything else is a setup error."""
    mock_hive.new_session.side_effect = new_session_error
    mock_hive.get_nodes.side_effect = get_nodes_error
    # The reauth flow logs in straight away with the saved credentials.
    mock_auth.login.side_effect = HiveInvalidPassword()

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is state
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == flow_sources


async def test_session_loads_the_config_entry(
    hass: HomeAssistant,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The session is given the entry's credentials, tokens and device data."""
    await setup_entry(hass, mock_config_entry)

    mock_hive.new_session.assert_called_once_with(ENTRY_DATA)


async def test_poll_updates_the_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Every poll interval the coordinator fetches Hive again and the states follow."""
    await setup_entry(hass, mock_config_entry)
    mock_hive.get_nodes.return_value = make_nodes(
        products=[replace(HEATING, mode="OFF"), HOT_WATER]
    )

    await poll(hass, freezer)

    assert mock_hive.get_nodes.await_count == 2
    entity_state = get_state(hass, entity_registry, CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID)
    assert entity_state.state == HVACMode.OFF


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            HiveConnectionError("Timed out calling Hive"), id="connection-error"
        ),
        pytest.param(HiveApiError("Hive refused the request"), id="refused"),
    ],
)
async def test_failed_poll_keeps_the_last_state(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    error: HiveError,
) -> None:
    """A failed poll leaves every entity with its last state rather than unavailable."""
    await setup_entry(hass, mock_config_entry)
    mock_hive.get_nodes.side_effect = error

    await poll(hass, freezer)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    entity_state = get_state(hass, entity_registry, CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID)
    assert entity_state.state == HVACMode.AUTO


async def test_rejected_login_while_polling_starts_reauth(
    hass: HomeAssistant,
    mock_hive: MagicMock,
    mock_auth: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A poll that needs the user to log in again starts the reauth flow."""
    await setup_entry(hass, mock_config_entry)
    mock_hive.get_nodes.side_effect = HiveReauthRequired("Hive asked for an SMS code")
    mock_auth.login.side_effect = HiveInvalidPassword()

    await poll(hass, freezer)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_degraded_reply_keeps_the_last_product(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A product Hive sends with only its name keeps its last state, up to the cap, then shows as sent."""
    await setup_entry(hass, mock_config_entry)
    mock_hive.get_nodes.return_value = make_nodes(
        products=[DEGRADED_HEATING, HOT_WATER]
    )

    for _ in range(MAX_DEGRADED_POLLS):
        await poll(hass, freezer)

    entity_state = get_state(hass, entity_registry, CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID)
    assert entity_state.state == HVACMode.AUTO

    await poll(hass, freezer)

    entity_state = get_state(hass, entity_registry, CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID)
    assert entity_state.state == STATE_UNAVAILABLE


async def test_good_reply_resets_the_degraded_count(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Degraded replies are counted in a row: a good reply in between starts the count again."""
    await setup_entry(hass, mock_config_entry)
    degraded = make_nodes(products=[DEGRADED_HEATING, HOT_WATER])
    mock_hive.get_nodes.return_value = degraded
    for _ in range(MAX_DEGRADED_POLLS):
        await poll(hass, freezer)
    mock_hive.get_nodes.return_value = make_nodes()
    await poll(hass, freezer)
    mock_hive.get_nodes.return_value = degraded

    await poll(hass, freezer)

    entity_state = get_state(hass, entity_registry, CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID)
    assert entity_state.state == HVACMode.AUTO


async def test_degraded_first_reply_is_shown_as_sent(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """With no earlier snapshot to keep, a degraded product is shown as Hive sent it."""
    mock_hive.get_nodes.return_value = make_nodes(products=[DEGRADED_HEATING])

    await setup_entry(hass, mock_config_entry)

    entity_state = get_state(hass, entity_registry, CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID)
    assert entity_state.state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("service", "data", "command"),
    [
        pytest.param(
            (CLIMATE_DOMAIN, SERVICE_SET_HVAC_MODE),
            {ATTR_HVAC_MODE: HVACMode.HEAT},
            call.set_mode(HEATING, "MANUAL"),
            id="hvac-mode",
        ),
        pytest.param(
            (CLIMATE_DOMAIN, SERVICE_SET_TEMPERATURE),
            {ATTR_TEMPERATURE: 20.5},
            call.set_target_temperature(HEATING, 20.5),
            id="target-temperature",
        ),
        # The boost preset runs for 30 minutes at half a degree above the current 19.5.
        pytest.param(
            (CLIMATE_DOMAIN, SERVICE_SET_PRESET_MODE),
            {ATTR_PRESET_MODE: PRESET_BOOST},
            call.set_heating_boost(HEATING, 30, 20.0),
            id="boost-preset",
        ),
        pytest.param(
            (DOMAIN, SERVICE_BOOST_HEATING_ON),
            {ATTR_TIME_PERIOD: "01:00:00", ATTR_TEMPERATURE: 22.0},
            call.set_heating_boost(HEATING, 60, 22.0),
            id="boost-heating-on",
        ),
    ],
)
async def test_climate_service_sends_the_heating_command(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    service: tuple[str, str],
    data: dict[str, object],
    command: object,
) -> None:
    """A climate service call becomes the matching library command, in Hive's units."""
    await setup_entry(hass, mock_config_entry)

    await call_service(
        hass, entity_registry, (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID), service, data
    )

    assert [c for c in mock_hive.mock_calls if c[0].startswith("set_")] == [command]


@pytest.mark.parametrize(
    ("data", "commands"),
    [
        pytest.param(
            {ATTR_TEMPERATURE: 24.0},
            [call.set_target_temperature(HEATING, 24.0)],
            id="temperature-only",
        ),
        pytest.param(
            {ATTR_HVAC_MODE: HVACMode.HEAT, ATTR_TEMPERATURE: 24.0},
            [
                call.set_mode(HEATING, "MANUAL"),
                call.set_target_temperature(HEATING, 24.0),
            ],
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
    commands: list[object],
) -> None:
    """Setting the temperature with an hvac mode sets the mode, then the temperature."""
    await setup_entry(hass, mock_config_entry)

    await call_service(
        hass,
        entity_registry,
        (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
        (CLIMATE_DOMAIN, SERVICE_SET_TEMPERATURE),
        data,
    )

    assert [c for c in mock_hive.mock_calls if c[0].startswith("set_")] == commands


@pytest.mark.parametrize(
    ("product", "target", "service", "data"),
    [
        pytest.param(
            replace(HEATING, mode="BOOST", boost=30, previous_mode="SCHEDULE"),
            (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
            (CLIMATE_DOMAIN, SERVICE_SET_PRESET_MODE),
            {ATTR_PRESET_MODE: PRESET_NONE},
            id="heating-preset-none",
        ),
        pytest.param(
            replace(HEATING, mode="BOOST", boost=30, previous_mode="SCHEDULE"),
            (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
            (DOMAIN, SERVICE_BOOST_HEATING_OFF),
            {},
            id="boost-heating-off",
        ),
        pytest.param(
            replace(HOT_WATER, mode="BOOST", boost=30, previous_mode="SCHEDULE"),
            (WATER_HEATER_DOMAIN, WATER_HEATER_UNIQUE_ID),
            (DOMAIN, SERVICE_BOOST_HOT_WATER),
            {ATTR_ONOFF: "off"},
            id="boost-hot-water-off",
        ),
    ],
)
async def test_ending_a_boost_restores_the_previous_mode(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    product: Device,
    target: tuple[str, str],
    service: tuple[str, str],
    data: dict[str, object],
) -> None:
    """Ending a boost sets the mode Hive reports it returns to."""
    mock_hive.get_nodes.return_value = make_nodes(products=[product])
    await setup_entry(hass, mock_config_entry)

    await call_service(hass, entity_registry, target, service, data)

    mock_hive.set_mode.assert_awaited_once_with(product, "SCHEDULE")


async def test_ending_a_boost_from_off_sets_off(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Hive reports a boost that returns to off with a previous mode of False."""
    heating = replace(HEATING, mode="BOOST", boost=30, previous_mode=False)
    mock_hive.get_nodes.return_value = make_nodes(products=[heating])
    await setup_entry(hass, mock_config_entry)

    await call_service(
        hass,
        entity_registry,
        (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
        (DOMAIN, SERVICE_BOOST_HEATING_OFF),
        {},
    )

    mock_hive.set_mode.assert_awaited_once_with(heating, "OFF")


async def test_ending_a_boost_that_is_not_active_sends_nothing(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Turning off a boost that is not running makes no request to Hive."""
    await setup_entry(hass, mock_config_entry)

    await call_service(
        hass,
        entity_registry,
        (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
        (DOMAIN, SERVICE_BOOST_HEATING_OFF),
        {},
    )

    mock_hive.set_mode.assert_not_awaited()


async def test_ending_a_boost_without_a_previous_mode_fails(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A boost whose return mode Hive did not report cannot be ended."""
    mock_hive.get_nodes.return_value = make_nodes(
        products=[replace(HEATING, mode="BOOST", boost=30)]
    )
    await setup_entry(hass, mock_config_entry)

    with pytest.raises(HomeAssistantError, match="did not report the mode to restore"):
        await call_service(
            hass,
            entity_registry,
            (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
            (DOMAIN, SERVICE_BOOST_HEATING_OFF),
            {},
        )

    mock_hive.set_mode.assert_not_awaited()


@pytest.mark.parametrize(
    ("service", "data", "command"),
    [
        pytest.param(
            (WATER_HEATER_DOMAIN, SERVICE_TURN_ON),
            {},
            call.set_mode(HOT_WATER, "MANUAL"),
            id="turn-on",
        ),
        pytest.param(
            (WATER_HEATER_DOMAIN, SERVICE_TURN_OFF),
            {},
            call.set_mode(HOT_WATER, "OFF"),
            id="turn-off",
        ),
        pytest.param(
            (WATER_HEATER_DOMAIN, SERVICE_SET_OPERATION_MODE),
            {ATTR_OPERATION_MODE: STATE_ECO},
            call.set_mode(HOT_WATER, "SCHEDULE"),
            id="operation-mode",
        ),
        pytest.param(
            (DOMAIN, SERVICE_BOOST_HOT_WATER),
            {ATTR_TIME_PERIOD: "01:30:00", ATTR_ONOFF: "on"},
            call.set_hot_water_boost(HOT_WATER, 90),
            id="boost-on",
        ),
    ],
)
async def test_water_heater_service_sends_the_hot_water_command(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    service: tuple[str, str],
    data: dict[str, object],
    command: object,
) -> None:
    """A water heater service call becomes the matching library command."""
    await setup_entry(hass, mock_config_entry)

    await call_service(
        hass,
        entity_registry,
        (WATER_HEATER_DOMAIN, WATER_HEATER_UNIQUE_ID),
        service,
        data,
    )

    assert [c for c in mock_hive.mock_calls if c[0].startswith("set_")] == [command]


async def test_command_refreshes_the_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """After a command the coordinator fetches Hive again, so the change shows."""
    await setup_entry(hass, mock_config_entry)
    mock_hive.get_nodes.return_value = make_nodes(
        products=[replace(HEATING, mode="MANUAL"), HOT_WATER]
    )

    await call_service(
        hass,
        entity_registry,
        (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
        (CLIMATE_DOMAIN, SERVICE_SET_HVAC_MODE),
        {ATTR_HVAC_MODE: HVACMode.HEAT},
    )
    await hass.async_block_till_done()

    assert mock_hive.get_nodes.await_count == 2
    entity_state = get_state(hass, entity_registry, CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID)
    assert entity_state.state == HVACMode.HEAT


async def test_failed_command_raises_home_assistant_error(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A command the library could not carry out fails the service call with its message."""
    await setup_entry(hass, mock_config_entry)
    mock_hive.set_mode.side_effect = HiveApiError("Hive refused the change")

    with pytest.raises(HomeAssistantError, match="Hive refused the change"):
        await call_service(
            hass,
            entity_registry,
            (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
            (CLIMATE_DOMAIN, SERVICE_SET_HVAC_MODE),
            {ATTR_HVAC_MODE: HVACMode.HEAT},
        )


@pytest.mark.parametrize(
    ("target", "service", "data", "match"),
    [
        pytest.param(
            (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
            (DOMAIN, SERVICE_BOOST_HEATING_ON),
            {ATTR_TIME_PERIOD: "00:00:30", ATTR_TEMPERATURE: 20.0},
            "Boost minutes must be positive",
            id="heating-boost-too-short",
        ),
        pytest.param(
            (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
            (DOMAIN, SERVICE_BOOST_HEATING_ON),
            {ATTR_TIME_PERIOD: "00:30:00", ATTR_TEMPERATURE: 33.0},
            "Boost temperature must be between 5.0 and 32.0",
            id="heating-boost-too-hot",
        ),
        pytest.param(
            (CLIMATE_DOMAIN, CLIMATE_UNIQUE_ID),
            (DOMAIN, SERVICE_BOOST_HEATING_ON),
            {ATTR_TIME_PERIOD: "00:30:00", ATTR_TEMPERATURE: 4.5},
            "Boost temperature must be between 5.0 and 32.0",
            id="heating-boost-too-cold",
        ),
        pytest.param(
            (WATER_HEATER_DOMAIN, WATER_HEATER_UNIQUE_ID),
            (DOMAIN, SERVICE_BOOST_HOT_WATER),
            {ATTR_TIME_PERIOD: "00:00:30", ATTR_ONOFF: "on"},
            "Boost minutes must be positive",
            id="hot-water-boost-too-short",
        ),
    ],
)
async def test_invalid_command_argument_raises_validation_error(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    target: tuple[str, str],
    service: tuple[str, str],
    data: dict[str, object],
    match: str,
) -> None:
    """An argument out of Hive's range is a validation error, and nothing is sent."""
    await setup_entry(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError, match=match):
        await call_service(hass, entity_registry, target, service, data)

    assert [c for c in mock_hive.mock_calls if c[0].startswith("set_")] == []


async def test_services_are_registered_without_devices(
    hass: HomeAssistant,
    mock_hive: MagicMock,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The entry loads and reloads, with its services, on an account with only a hub."""
    mock_hive.get_nodes.return_value = make_nodes(products=[], devices=[HUB])

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
    thermostat = get_device(device_registry, mock_config_entry, THERMOSTAT_ID)

    assert await async_remove_config_entry_device(hass, mock_config_entry, thermostat)
