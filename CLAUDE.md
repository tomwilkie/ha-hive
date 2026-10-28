# CLAUDE.md

Guidance for Claude Code when working in this repository, locally and in
GitHub Actions.

This is ha-hive, a custom Home Assistant integration for Hive heating and hot
water. It is a fork of core's `hive` integration
(`homeassistant/components/hive`) that uses the owner's hard fork of the Hive
API library, apyhiveapi (GitHub `tomwilkie/apyhiveapi`, on PyPI). It exists to fix
home-assistant/core#182752: a transient network failure at startup must be
retried, not become a permanent setup error.

## How it is installed, and what must not change

- The integration keeps the `hive` domain, so it **overrides** the built-in
  integration and inherits its config entry, devices and entities. Anything
  that changes an identifier breaks that: entity unique IDs are
  `f"{hive_id}-{hive_type}"` (`entity.py`), device identifiers are
  `(DOMAIN, device_id)`, and the hub's device is registered in `__init__.py`.
  Do not change them.
- HACS installs it from this repository (`hacs.json`); `manifest.json` carries
  the version. A release is a version bump there merged to `main`:
  `release.yml` tags the merge commit `v<version>` and publishes a GitHub
  Release, which HACS offers as a versioned install. `hacs.json`'s
  `homeassistant` is the oldest core release the
  code runs on. Raise it when using a newer core API: the code already needs
  2026.10 for `dr.async_get_device_id_by_identifier`, `probatio` and
  `AddConfigEntryEntitiesCallback`.
- Home Assistant installs the library from PyPI, pinned in `manifest.json`
  `requirements` as `apyhiveapi==<version>`. The `dev` group of
  `pyproject.toml` carries the same pin so the tests run against the release
  Home Assistant installs; `tests/test_manifest.py` checks they match. (Up
  to library v0.1.4 the package was `pyhive-integration`, installed from a
  GitHub release wheel as `<wheel URL>#pyhive-integration==<version>`.)
- Only the climate, water heater, binary sensor and sensor platforms exist.
  The binary sensors are the heating and hot water boost status, keeping
  core's unique IDs (`f"{hive_id}-Heating_Boost"`, `f"{hive_id}-Hotwater_Boost"`)
  so core's entities carry over. The one sensor is the battery level of each
  thermostat and TRV, read from `device_data["battery"]`, one per hardware
  device under core's unique ID (`f"{device_id}-Battery"`); a device whose
  props carry no battery gets none, and it is available while the hardware
  itself is online (`device_online`), not while the zone is. The light and
  switch platforms, and
  core's other sensors and binary sensors, were removed with the library's
  support for them; code the library has no counterpart for is removed, not
  kept.

## The library is updated in step

apyhiveapi is the one dependency that matters, and this repository is its
only consumer.

- Local checkout: `~/Documents/repos/apyhiveapi` (GitHub
  `tomwilkie/apyhiveapi`, formerly `tomwilkie/pyhive-integration`). In GitHub
  Actions, where the checkout is not available, fetch raw files from
  `https://raw.githubusercontent.com/tomwilkie/apyhiveapi/main/src/apyhiveapi/<file>.py`.
- Its `CLAUDE.md` holds the API contract and the error table. Read it before
  changing anything that touches `apyhiveapi`. Its rule mirrors this one:
  when its API changes, this repository is updated alongside.
- To take a new library release: update the `apyhiveapi==` pin in
  `manifest.json` *and* in the `dev` group of `pyproject.toml`
  (`tests/test_manifest.py` checks they match), run `uv lock`, run the tests,
  run `scripts/check_requirements`. Every merge to the library's `main` is
  released with a patch bump.

What this repository calls, and so what the library must keep:

- `Hive(websession)`: `start_session(config)`, `update_data()` (async, no
  arguments, returns bool, raises only `HiveReauthRequired`), `device_list`
  with the keys `parent`, `climate` and `water_heater`.
- `hive.heating`: `get_climate`, `set_mode`, `set_target_temperature`,
  `set_boost_on(device, minutes, temperature)`, `set_boost_off`.
  `hive.hotwater`: `get_water_heater`, `set_mode`,
  `set_boost_on(device, minutes)`, `set_boost_off`. Commands return nothing
  and raise a `HiveError`; a bad argument raises `ValueError`.
- `Auth(username=, password=)`: `login`, `sms_2fa(code, challenge)`,
  `device_registration(name)`, `get_device_data()` (sync; the three device
  credentials, stored whole as `device_data` in the config entry; v0.0.1
  added the token issue time, which v0.1.0 accepts and ignores),
  `is_device_registered()`,
  `forget_device(access_token, device_key)`.
- `Device`, read as attributes (v0.1.0 dropped the dict-style access that
  v0.0.1 had): `hive_id`, `hive_type`,
  `ha_name`, `device_id`, `device_name`, `device_data` (a dict of the
  hardware props plus two flags: `online`, the product's availability, and
  `device_online`, the hardware's own, added in v0.1.4; `battery` is the
  level in percent, present only for battery-powered hardware),
  `parent_device` (None when Hive reported no
  hub), `temperature_unit` (may be None), `status` (a dict), `min_temp`,
  `max_temp`. `status` keys: climate `mode`, `action`,
  `current_temperature`, `target_temperature`, `boost`; water heater
  `current_operation`, `boost`. Any value may be None.
- From `apyhiveapi`: `HiveError`, `HiveConnectionError`, `HiveApiError`,
  `HiveDeviceOffline`, `HiveReauthRequired` and its subclasses
  `HiveInvalidUsername`, `HiveInvalidPassword`, `HiveInvalid2FACode`;
  `SMS_REQUIRED`.

## Error mapping

| Where | Library raises | This repository does |
|---|---|---|
| `async_setup_entry` | `HiveReauthRequired` | `ConfigEntryAuthFailed`: Home Assistant starts the reauth flow |
| | `HiveConnectionError` | `ConfigEntryNotReady`: retried with backoff (the #182752 fix) |
| | any other `HiveError` | `ConfigEntryError` |
| commands, via `refresh_system` | `HiveError` | `HomeAssistantError` |
| | `ValueError` | `ServiceValidationError` |
| config flow (login, 2FA, resend, registration) | `HiveInvalidUsername` / `HiveInvalidPassword` / `HiveInvalid2FACode` | form error `invalid_username` / `invalid_password` / `invalid_code` |
| | `HiveConnectionError` | form error `no_internet_available` |
| | any other `HiveError` | form error `unknown`, logged at ERROR |

Home Assistant logs setup failures itself: raise, do not log and raise.
Polling (`async_update`) does not catch `HiveReauthRequired` yet; see "Known
gaps".

## Project rules

- Write Home Assistant core code. Style, structure and naming follow
  `homeassistant/components/hive` so that fixes can be sent upstream: ruff
  runs with core's configuration (copied into `pyproject.toml`), imports are
  sorted core-style, everything has a docstring including tests, and schemas
  use `probatio`, not voluptuous.
- Never log tokens, passwords or `device_data`. The library's messages are
  already sanitised and this repository logs no payloads.
- Every bug fix comes with a test. Tests mock at the `apyhiveapi` boundary
  only (`Hive` in `custom_components.hive`, `Auth` in
  `custom_components.hive.config_flow`) and drive the integration through
  config entries, flows, services and states, never entity internals. Follow
  `.claude/skills/testing/`.
- `strings.json` is the source; `translations/en.json` is regenerated by hand
  by resolving the `[%key:...%]` references against core's
  `homeassistant/strings.json`. `tests/test_manifest.py` checks the key trees
  match.

## Commands

```bash
uv sync                             # Home Assistant, the library and the dev tools
uv run pytest                       # the full suite, with coverage (fail_under in pyproject.toml)
uv run pre-commit run --all-files   # ruff, codespell, zizmor, yamllint, uv lock check
scripts/check_requirements          # install the manifest requirement under core's pins
```

CI (`.github/workflows/ci.yml`) runs the same, plus hassfest and the HACS
action. Actions are pinned to commit SHAs, except hassfest and HACS, which
only publish moving branches and are meant to track current validation rules.

## Layout

```text
custom_components/hive/
├── __init__.py        ← async_setup_entry: start_session → ConfigEntry* mapping,
│                        the hub device; refresh_system wraps every command
├── config_flow.py     ← login, SMS 2FA, device registration, reauth
├── entity.py          ← HiveEntity: unique_id, device info, via_device, refresh signal
├── climate.py         ← heating zones and TRV controls
├── water_heater.py    ← hot water
├── binary_sensor.py   ← heating and hot water boost status
├── sensor.py          ← battery level of each thermostat and TRV
├── services.py        ← boost_heating_on/off and boost_hot_water, registered in async_setup
├── const.py, manifest.json, services.yaml, icons.json
└── strings.json, translations/en.json
tests/                 ← pytest-homeassistant-custom-component; helpers in common.py,
                         fixtures in conftest.py
scripts/check_requirements
```

## Known gaps

- `update_data()` raising `HiveReauthRequired` during polling, or a command
  raising it, is not turned into a reauth flow: it propagates and is logged on
  every poll (since v0.1.0 the library does not contact Cognito again for
  it, so the cost is the log line). Needs `entry.async_start_reauth(hass)`
  in the entities.
- Refreshed tokens are never written back to the config entry (Pyhive#123):
  the library treats saved tokens as due for a refresh, so every start
  refreshes them. Needs a token-updated hook in the library.
- `async_remove_entry` forgets the device with the access token saved at
  registration, which has usually expired by then.

## Links

- Upstream integration: <https://github.com/home-assistant/core/tree/dev/homeassistant/components/hive>
- The issue this fork fixes: <https://github.com/home-assistant/core/issues/182752>
- Setup failures: <https://developers.home-assistant.io/docs/integration_setup_failures/>
- Config flow: <https://developers.home-assistant.io/docs/config_entries_config_flow_handler/>
- climate: <https://developers.home-assistant.io/docs/core/entity/climate/>
- water_heater: <https://developers.home-assistant.io/docs/core/entity/water-heater/>
- Blocking calls in the event loop: <https://developers.home-assistant.io/docs/asyncio_blocking_operations/>
