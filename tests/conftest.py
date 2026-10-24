"""Fixtures for the Hive tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hive.const import DOMAIN

from tests.common import (
    ENTRY_DATA,
    USERNAME,
    make_climate,
    make_devices,
    make_hub,
    make_mock_hive,
    make_water_heater,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for an account with saved tokens."""
    return MockConfigEntry(
        domain=DOMAIN, title=USERNAME, unique_id=USERNAME, data=ENTRY_DATA
    )


@pytest.fixture
def mock_hive() -> Generator[MagicMock]:
    """Patch the Hive session with a hub, one heating zone and hot water.

    Replace ``mock_hive.device_list`` before setting up the entry to test
    another account shape.
    """
    devices = make_devices(
        hub=make_hub(), climate=[make_climate()], water_heater=[make_water_heater()]
    )
    with patch(
        "custom_components.hive.Hive", return_value=make_mock_hive(devices)
    ) as mock_hive_class:
        yield mock_hive_class.return_value


@pytest.fixture
def mock_auth_class() -> Generator[MagicMock]:
    """Patch the Auth class the config flow logs in with."""
    with patch("custom_components.hive.config_flow.Auth", autospec=True) as mock_class:
        yield mock_class


@pytest.fixture
def mock_auth(mock_auth_class: MagicMock) -> MagicMock:
    """Return the Auth instance the config flow gets; its async methods are AsyncMocks."""
    return mock_auth_class.return_value


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Patch async_setup_entry so a config flow does not start the real session."""
    with patch(
        "custom_components.hive.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup
