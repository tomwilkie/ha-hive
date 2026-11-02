# CLAUDE.md

Guidance for Claude Code when working in this repository, locally and in
GitHub Actions.

This is ha-hive, a custom Home Assistant integration for Hive heating and hot
water. It is a fork of core's `hive` integration
(`homeassistant/components/hive`) that uses the owner's hard fork of the Hive
API library, hiveheating (GitHub `tomwilkie/hiveheating`, on PyPI). It exists to fix
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
  `requirements` as `hiveheating==<version>`. The `dev` group of
  `pyproject.toml` carries the same pin so the tests run against the release
  Home Assistant installs; `tests/test_manifest.py` checks they match. (Up
  to library v0.1.4 the package was `pyhive-integration`, installed from a
  GitHub release wheel as `<wheel URL>#pyhive-integration==<version>`; from
  v0.1.4 to v0.2.1 it was `apyhiveapi`.)
- The library's import name must not be `apyhiveapi` or `pyhiveapi`. The
  Home Assistant image comes with core's `pyhive-integration` installed,
  which provides both; pip unpacks a second package of the same name into
  the same folder, and upstream's leftover files shadow ours (upstream's
  `apyhiveapi/api/` hid our `api.py`, so the config flow failed to load).
  That is why the library is now `hiveheating`.
- Only the climate, water heater, binary sensor and sensor platforms exist.
  The binary sensors are the heating and hot water boost status, keeping
  core's unique IDs (`f"{hive_id}-Heating_Boost"`, `f"{hive_id}-Hotwater_Boost"`)
  so core's entities carry over. The one sensor is the battery level of each
  thermostat, read from the hardware `Device`'s `battery`, one per
  hardware device under core's unique ID (`f"{device_id}-Battery"`); a device
  with no battery gets none, and it is available while the hardware itself
  is online (the `Device`'s `online`), not while the zone is. The light and
  switch platforms, and
  core's other sensors and binary sensors, were removed with the library's
  support for them; code the library has no counterpart for is removed, not
  kept.

## The library is updated in step

hiveheating is the one dependency that matters, and this repository is its
only consumer.

- Local checkout: `~/Documents/repos/hiveheating` (GitHub
  `tomwilkie/hiveheating`, formerly `tomwilkie/apyhiveapi` and
  `tomwilkie/pyhive-integration`). In GitHub
  Actions, where the checkout is not available, fetch raw files from
  `https://raw.githubusercontent.com/tomwilkie/hiveheating/main/src/hiveheating/<file>.py`.
- Its `CLAUDE.md` holds the API contract and the error table. Read it before
  changing anything that touches `hiveheating`. Its rule mirrors this one:
  when its API changes, this repository is updated alongside.
- To take a new library release: update the `hiveheating==` pin in
  `manifest.json` *and* in the `dev` group of `pyproject.toml`
  (`tests/test_manifest.py` checks they match), run `uv lock`, run the tests,
  run `scripts/check_requirements`. Every merge to the library's `main` is
  released with a patch bump.

What this repository calls, and so what the library must keep:

- `Hive(websession)`: `new_session(config)` (sync, sends nothing, raises
  only `HiveReauthRequired`, for missing tokens or incomplete
  `device_data`), `get_nodes()` (one `GET /nodes/all`, used for discovery
  and every poll; returns `Nodes` or raises a `HiveError`, including
  `HiveConnectionError` for a reply with no products or no devices).
- Commands, each one `POST` that returns nothing or raises a `HiveError`:
  `set_mode(product, mode)` (`Mode`: `SCHEDULE` / `MANUAL` / `OFF`),
  `set_target_temperature(heating_product, target)`,
  `set_heating_boost(heating_product, minutes, target)`,
  `set_hot_water_boost(hot_water_product, minutes)`. There is no boost-off
  call, and the library checks no argument values.
- `Auth(username=, password=)`: `login`, `sms_2fa(code, challenge)`,
  `device_registration(name)`, `get_device_data()` (sync; the three device
  credentials, stored whole as `device_data` in the config entry; v0.0.1
  added the token issue time, which v0.1.0 accepts and ignores),
  `is_device_registered()`,
  `forget_device(access_token, device_key)`.
- The frozen dataclasses `get_nodes` returns, read as attributes. Fields
  keep Hive's names and raw values; a missing or wrong-typed value is None.
  - `Nodes`: `user` (`User`: `temperature_unit`), `products` (by ID) and
    `devices` (by ID).
  - `HeatingProduct` (`heating`): `id`, `type`, `name`, `online`, `model`,
    `version`, `zone`, `temperature`, `working`,
    `mode` (can be `BOOST`), `target`, `boost` (minutes), `previous_mode`
    (`False` means OFF).
  - `HotWaterProduct` (`hotwater`): `id`, `type`, `name`, `online`, `model`,
    `version`, `zone`, `mode`, `boost`, `previous_mode`.
  - `Device` (`hub`, `thermostatui`, `boilermodule`): `id`, `type`,
    `name`, `online`, `model`, `manufacturer`, `version`, `zone`, `battery`,
    `mac_address`.
- From `hiveheating`: `HiveError`, `HiveConnectionError`, `HiveApiError`,
  `HiveReauthRequired` and its subclasses `HiveInvalidUsername`,
  `HiveInvalidPassword`, `HiveInvalid2FACode`; `SMS_REQUIRED`; `Mode`.

## From Hive's model to Home Assistant's

The library knows nothing about Home Assistant; this repository does the
mapping.

- **Polling**: one `HiveDataUpdateCoordinator` per entry (`coordinator.py`)
  calls `get_nodes()` every 120 s, with `always_update=False`. Entities are
  `CoordinatorEntity`s and read the latest snapshot. After a command,
  `refresh_system` calls `async_request_refresh()`, which is debounced:
  Hive's gateway returns 403 for 1-2 minutes after a burst of about 25
  requests.
- **Degraded replies** (hiveheating #20): a product Hive sends with no `mode`
  (its state holds only `name`) is replaced by its last good snapshot, for
  up to `MAX_DEGRADED_POLLS` (5) polls in a row; after that it is shown as
  sent, so a real outage shows.
- **Discovery** happens once, from the first refresh; products that appear
  later wait for a reload. Heating and hot water attach to the
  `thermostatui` in their zone, or are their own device when there is none.
  Device info comes from the attached `Device`, or from
  the product (with no manufacturer) when it is its own device; `via_device`
  is the hub. Hive's `Receiver` is shown as `Heating`.
- **State**: while `mode` is `BOOST`, the mode shown is `previous_mode`
  (`False` is OFF), and the boost is active while `boost` is truthy; a
  boosting climate entity shows HEAT. Hot water `MANUAL` is shown as on.
  Climate temperatures are `temperature` (to 1 decimal) and `target`,
  limits 5-32, in `user.temperature_unit`.
- **Availability**: climate, water heater and boost sensors while the
  product's `online` is true; the
  battery sensor while its hardware's `online` is true. A failed refresh
  keeps the last snapshot, so entities keep their last state.
- **Commands**: arguments are checked here (boost minutes > 0, boost target
  5-32). Ending a boost is `set_mode(product, previous_mode)`, sent only
  while a boost is active. The old library also restored the previous target
  when returning to MANUAL or OFF; that waits for `set_mode` to take a
  target.

## Error mapping

| Where | Library raises | This repository does |
|---|---|---|
| `new_session`, any refresh | `HiveReauthRequired` | `ConfigEntryAuthFailed`: Home Assistant starts the reauth flow |
| first refresh | `HiveConnectionError` | `UpdateFailed`, so `ConfigEntryNotReady`: retried with backoff (the #182752 fix) |
| | any other `HiveError` | `ConfigEntryError` |
| later refreshes | any other `HiveError` | `UpdateFailed`: the last state is kept |
| commands, via `refresh_system` | `HiveError` | `HomeAssistantError` |
| | an invalid argument (checked here) | `ServiceValidationError` |
| config flow (login, 2FA, resend, registration) | `HiveInvalidUsername` / `HiveInvalidPassword` / `HiveInvalid2FACode` | form error `invalid_username` / `invalid_password` / `invalid_code` |
| | `HiveConnectionError` | form error `no_internet_available` |
| | any other `HiveError` | form error `unknown`, logged at ERROR |

Home Assistant logs setup and refresh failures itself: raise, do not log
and raise.

## Project rules

- Write Home Assistant core code. Style, structure and naming follow
  `homeassistant/components/hive` so that fixes can be sent upstream: ruff
  runs with core's configuration (copied into `pyproject.toml`), imports are
  sorted core-style, everything has a docstring including tests, and schemas
  use `probatio`, not voluptuous.
- Never log tokens, passwords or `device_data`. The library's messages are
  already sanitised and this repository logs no payloads.
- Every bug fix comes with a test. Tests mock at the `hiveheating` boundary
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
├── __init__.py        ← async_setup_entry: new_session, first refresh, the hub
│                        device; refresh_system wraps every command
├── coordinator.py     ← HiveDataUpdateCoordinator: get_nodes, error mapping,
│                        degraded replies
├── config_flow.py     ← login, SMS 2FA, device registration, reauth
├── entity.py          ← HiveEntity: discovery, unique_id, device info, via_device,
│                        availability, ending a boost
├── climate.py         ← heating zones
├── water_heater.py    ← hot water
├── binary_sensor.py   ← heating and hot water boost status
├── sensor.py          ← battery level of each thermostat
├── services.py        ← boost_heating_on/off and boost_hot_water, registered in async_setup
├── const.py, manifest.json, services.yaml, icons.json
└── strings.json, translations/en.json
tests/                 ← pytest-homeassistant-custom-component; helpers in common.py,
                         fixtures in conftest.py
scripts/check_requirements
```

## Known gaps

- A command raising `HiveReauthRequired` is reported as a
  `HomeAssistantError`, not turned into a reauth flow; the next poll starts
  one.
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
