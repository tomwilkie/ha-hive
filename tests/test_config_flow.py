"""Test the Hive config flow."""

from unittest.mock import AsyncMock, MagicMock

from apyhiveapi import (
    HiveApiError,
    HiveConnectionError,
    HiveError,
    HiveInvalid2FACode,
    HiveInvalidPassword,
    HiveInvalidUsername,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hive.const import CONF_CODE, CONF_DEVICE_NAME, DOMAIN
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import DEVICE_DATA, ENTRY_DATA, PASSWORD, TOKENS, USERNAME

LOGIN = {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
SMS_CHALLENGE = {"ChallengeName": "SMS_MFA", "Session": "mock-session"}
TOKENS_FOR_NEW_DEVICE = {
    "ChallengeName": "SUCCESS",
    "AuthenticationResult": {
        **TOKENS["AuthenticationResult"],
        "NewDeviceMetadata": {
            "DeviceGroupKey": "mock-device-group-key",
            "DeviceKey": "mock-device-key",
        },
    },
}
NO_TOKENS = {"ChallengeName": "FAILED"}
UPDATED_PASSWORD = "updated-password"
DEVICE_NAME = "Test Home Assistant"
MFA_CODE = "1234"
RESEND_CODE = "0000"

# The library's errors and the form error each one becomes.
CONNECTION_ERRORS = [
    pytest.param(HiveConnectionError(), "no_internet_available", id="no-internet"),
    pytest.param(HiveApiError(), "unknown", id="refused"),
]
LOGIN_ERRORS = [
    pytest.param(HiveInvalidUsername(), "invalid_username", id="invalid-username"),
    pytest.param(HiveInvalidPassword(), "invalid_password", id="invalid-password"),
    *CONNECTION_ERRORS,
]
TWO_FACTOR_ERRORS = [
    pytest.param(HiveInvalid2FACode(), "invalid_code", id="invalid-code"),
    *CONNECTION_ERRORS,
]


async def _start_user_flow(hass: HomeAssistant) -> ConfigFlowResult:
    """Open the user flow on its login form."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _submit(
    hass: HomeAssistant, result: ConfigFlowResult, user_input: dict[str, str]
) -> ConfigFlowResult:
    """Submit a form of the flow and wait for Home Assistant to settle."""
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    return result


async def test_user_flow_opens_on_the_login_form(hass: HomeAssistant) -> None:
    """The user flow starts with an empty login form."""
    result = await _start_user_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


@pytest.mark.parametrize(
    "username", [USERNAME, USERNAME.upper()], ids=["lowercase", "uppercase"]
)
async def test_login_creates_the_entry(
    hass: HomeAssistant,
    mock_auth_class: MagicMock,
    mock_auth: MagicMock,
    mock_setup_entry: AsyncMock,
    username: str,
) -> None:
    """A login needing no 2FA or registration creates the entry under the lower-cased username."""
    mock_auth.login.return_value = TOKENS
    result = await _start_user_flow(hass)

    result = await _submit(
        hass, result, {CONF_USERNAME: username, CONF_PASSWORD: PASSWORD}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == username
    assert result["data"] == {
        CONF_USERNAME: username,
        CONF_PASSWORD: PASSWORD,
        "tokens": TOKENS,
    }
    assert result["result"].unique_id == username.lower()
    assert mock_auth_class.call_args.kwargs["username"] == username.lower()
    mock_setup_entry.assert_awaited_once()


@pytest.mark.usefixtures("mock_setup_entry")
async def test_login_from_a_new_device_registers_it(
    hass: HomeAssistant, mock_auth: MagicMock
) -> None:
    """Tokens with NewDeviceMetadata lead to the device name form, then registration."""
    mock_auth.login.return_value = TOKENS_FOR_NEW_DEVICE
    mock_auth.get_device_data.return_value = DEVICE_DATA
    result = await _start_user_flow(hass)

    result = await _submit(hass, result, LOGIN)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "configuration"

    result = await _submit(hass, result, {CONF_DEVICE_NAME: DEVICE_NAME})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        **LOGIN,
        "tokens": TOKENS_FOR_NEW_DEVICE,
        "device_data": DEVICE_DATA,
    }
    mock_auth.device_registration.assert_awaited_once_with(DEVICE_NAME)


@pytest.mark.usefixtures("mock_setup_entry")
async def test_login_with_2fa_registers_the_device(
    hass: HomeAssistant, mock_auth: MagicMock
) -> None:
    """An SMS challenge leads to the code form, then to device registration."""
    mock_auth.login.return_value = SMS_CHALLENGE
    mock_auth.sms_2fa.return_value = TOKENS
    mock_auth.get_device_data.return_value = DEVICE_DATA
    result = await _start_user_flow(hass)

    result = await _submit(hass, result, LOGIN)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == CONF_CODE

    result = await _submit(hass, result, {CONF_CODE: MFA_CODE})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "configuration"

    result = await _submit(hass, result, {CONF_DEVICE_NAME: DEVICE_NAME})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {**LOGIN, "tokens": TOKENS, "device_data": DEVICE_DATA}
    mock_auth.sms_2fa.assert_awaited_once_with(MFA_CODE, SMS_CHALLENGE)
    mock_auth.device_registration.assert_awaited_once_with(DEVICE_NAME)


async def test_entering_0000_requests_a_new_code(
    hass: HomeAssistant, mock_auth: MagicMock
) -> None:
    """The code 0000 logs in again so Hive sends another SMS, and stays on the code form."""
    mock_auth.login.return_value = SMS_CHALLENGE
    result = await _start_user_flow(hass)
    result = await _submit(hass, result, LOGIN)

    result = await _submit(hass, result, {CONF_CODE: RESEND_CODE})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == CONF_CODE
    assert result["errors"] == {}
    assert mock_auth.login.await_count == 2
    mock_auth.sms_2fa.assert_not_awaited()


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_updates_the_password(
    hass: HomeAssistant, mock_auth: MagicMock
) -> None:
    """Reauth shows the rejected password as an error, then saves the new one."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={**ENTRY_DATA, CONF_PASSWORD: "incorrect-password"},
    )
    entry.add_to_hass(hass)
    mock_auth.login.side_effect = [HiveInvalidPassword(), TOKENS]

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_password"}

    result = await _submit(
        hass, result, {CONF_USERNAME: USERNAME, CONF_PASSWORD: UPDATED_PASSWORD}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == UPDATED_PASSWORD
    assert entry.data["tokens"] == TOKENS


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_with_2fa_keeps_a_registered_device(
    hass: HomeAssistant, mock_auth: MagicMock
) -> None:
    """After the SMS code, a device Hive still remembers is kept as it is."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={**ENTRY_DATA, "device_data": DEVICE_DATA},
    )
    entry.add_to_hass(hass)
    mock_auth.login.return_value = SMS_CHALLENGE
    mock_auth.sms_2fa.return_value = TOKENS
    mock_auth.is_device_registered.return_value = True

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == CONF_CODE

    result = await _submit(hass, result, {CONF_CODE: MFA_CODE})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["device_data"] == DEVICE_DATA
    mock_auth.device_registration.assert_not_awaited()


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_with_2fa_registers_a_forgotten_device(
    hass: HomeAssistant, mock_auth: MagicMock
) -> None:
    """After the SMS code, a device deleted from the Hive app is registered again."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=USERNAME, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    mock_auth.login.return_value = SMS_CHALLENGE
    mock_auth.sms_2fa.return_value = TOKENS
    mock_auth.is_device_registered.return_value = False
    mock_auth.get_device_data.return_value = DEVICE_DATA

    result = await entry.start_reauth_flow(hass)
    result = await _submit(hass, result, {CONF_CODE: MFA_CODE})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "configuration"

    result = await _submit(hass, result, {CONF_DEVICE_NAME: DEVICE_NAME})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["device_data"] == DEVICE_DATA
    mock_auth.device_registration.assert_awaited_once_with(DEVICE_NAME)


@pytest.mark.parametrize(("error", "message"), CONNECTION_ERRORS)
@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_retries_a_failed_registration_check(
    hass: HomeAssistant, mock_auth: MagicMock, error: HiveError, message: str
) -> None:
    """When the device check fails, the code form is shown again with the matching error."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=USERNAME, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    mock_auth.login.return_value = SMS_CHALLENGE
    mock_auth.sms_2fa.return_value = TOKENS
    mock_auth.is_device_registered.side_effect = [error, True]

    result = await entry.start_reauth_flow(hass)
    result = await _submit(hass, result, {CONF_CODE: MFA_CODE})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == CONF_CODE
    assert result["errors"] == {"base": message}

    result = await _submit(hass, result, {CONF_CODE: MFA_CODE})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


@pytest.mark.parametrize(("error", "message"), LOGIN_ERRORS)
async def test_login_error_is_shown_on_the_form(
    hass: HomeAssistant, mock_auth: MagicMock, error: HiveError, message: str
) -> None:
    """A failed login keeps the login form open with the matching error."""
    mock_auth.login.side_effect = error
    result = await _start_user_flow(hass)

    result = await _submit(hass, result, LOGIN)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": message}


@pytest.mark.parametrize(("error", "message"), TWO_FACTOR_ERRORS)
async def test_2fa_error_is_shown_on_the_form(
    hass: HomeAssistant, mock_auth: MagicMock, error: HiveError, message: str
) -> None:
    """A rejected code or an unreachable Hive keeps the code form open with the matching error."""
    mock_auth.login.return_value = SMS_CHALLENGE
    mock_auth.sms_2fa.side_effect = error
    result = await _start_user_flow(hass)
    result = await _submit(hass, result, LOGIN)

    result = await _submit(hass, result, {CONF_CODE: MFA_CODE})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == CONF_CODE
    assert result["errors"] == {"base": message}


@pytest.mark.parametrize(("error", "message"), CONNECTION_ERRORS)
async def test_resend_error_is_shown_on_the_form(
    hass: HomeAssistant, mock_auth: MagicMock, error: HiveError, message: str
) -> None:
    """A failed login for a new code keeps the code form open with the matching error."""
    mock_auth.login.side_effect = [SMS_CHALLENGE, error]
    result = await _start_user_flow(hass)
    result = await _submit(hass, result, LOGIN)

    result = await _submit(hass, result, {CONF_CODE: RESEND_CODE})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == CONF_CODE
    assert result["errors"] == {"base": message}


@pytest.mark.parametrize(("error", "message"), CONNECTION_ERRORS)
async def test_registration_error_is_shown_on_the_form(
    hass: HomeAssistant, mock_auth: MagicMock, error: HiveError, message: str
) -> None:
    """A failed device registration keeps the name form open and saves no device data."""
    mock_auth.login.return_value = TOKENS_FOR_NEW_DEVICE
    mock_auth.device_registration.side_effect = error
    result = await _start_user_flow(hass)
    result = await _submit(hass, result, LOGIN)

    result = await _submit(hass, result, {CONF_DEVICE_NAME: DEVICE_NAME})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "configuration"
    assert result["errors"] == {"base": message}
    mock_auth.get_device_data.assert_not_called()


async def test_login_without_tokens_is_an_unknown_error(
    hass: HomeAssistant, mock_auth: MagicMock
) -> None:
    """A login that completes no challenge and returns no tokens is an unknown error."""
    mock_auth.login.return_value = NO_TOKENS
    result = await _start_user_flow(hass)

    result = await _submit(hass, result, LOGIN)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "unknown"}


async def test_2fa_without_tokens_fails_at_configuration(
    hass: HomeAssistant, mock_auth: MagicMock
) -> None:
    """A code response without tokens still reaches the name form, which then fails."""
    mock_auth.login.return_value = SMS_CHALLENGE
    mock_auth.sms_2fa.return_value = NO_TOKENS
    mock_auth.get_device_data.return_value = DEVICE_DATA
    result = await _start_user_flow(hass)
    result = await _submit(hass, result, LOGIN)
    result = await _submit(hass, result, {CONF_CODE: MFA_CODE})
    assert result["step_id"] == "configuration"

    result = await _submit(hass, result, {CONF_DEVICE_NAME: DEVICE_NAME})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "configuration"
    assert result["errors"] == {"base": "unknown"}


async def test_second_entry_for_the_account_is_aborted(
    hass: HomeAssistant, mock_auth: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """An account that already has an entry is not logged in to again, whatever the letter case."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_user_flow(hass)

    result = await _submit(
        hass, result, {CONF_USERNAME: USERNAME.upper(), CONF_PASSWORD: PASSWORD}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_auth.login.assert_not_awaited()
