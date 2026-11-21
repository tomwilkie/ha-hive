# Manual test plan

Checks the integration against a real Hive account in a throwaway Home
Assistant container. Run it before a release that changes the Home Assistant
version, the library or how commands are sent. The unit tests mock the library,
so this is the only check that talks to Hive.

The plan changes the account's real heating and hot water. Note the starting
state and put it back at the end.

## Setup

1. Start the Home Assistant release in `hacs.json`, with the integration
   mounted read-only:

   ```bash
   mkdir -p /tmp/ha-config
   cat > /tmp/ha-config/configuration.yaml <<'EOF'
   default_config:

   logger:
     default: info
     logs:
       custom_components.hive: debug
       hiveheating: debug
   EOF
   docker run -d --name ha-hive-test -p 8123:8123 \
     -v /tmp/ha-config:/config \
     -v "$PWD/custom_components/hive:/config/custom_components/hive:ro" \
     ghcr.io/home-assistant/home-assistant:<version>
   ```

2. Onboard at <http://localhost:8123> with the user `test` / `test`.
3. Add the Hive integration: log in, enter the SMS code, and confirm the
   configuration step (Home Assistant registers itself as a trusted device
   named "Home Assistant").
4. Drive the remaining steps through the REST API with a token for `test`
   (`/auth/login_flow`, then `/auth/token`). Leave about 30 s between Hive
   commands: Hive's gateway returns 403 for 1-2 minutes after a burst of about
   25 requests. Each command triggers a debounced refresh, so read states a
   few seconds after the command.

Code changes reach the container through the mount; `docker restart
ha-hive-test` loads them. `docker rm -f ha-hive-test` removes it.

## Read-only checks

| Check | Expected |
|---|---|
| Config entry state | `loaded` |
| Log (`docker logs ha-hive-test`) | No errors, and no deprecation warnings naming `custom_components.hive` |
| `climate.<zone>` | `hvac_modes` auto/heat/off, limits 5-32, unit from the account, a current and target temperature |
| `water_heater.<zone>_hot_water` | Operation eco/on/off |
| `binary_sensor.<zone>_boost`, `binary_sensor.<zone>_hot_water_boost` | `off` unless a boost is running |
| `sensor.<zone>_battery_level` | A percentage, for a thermostat with a battery |
| Device registry | The thermostat's device is linked to the hub through `via_device_id` |
| Reload the entry | Back to `loaded`, no errors logged |

## Commands

Write down the starting hvac mode, target temperature and hot water mode
first. `T` is the starting target.

| # | Command | Expected |
|---|---|---|
| 1 | `climate.set_temperature` to `T + 0.5` | Climate `temperature` is `T + 0.5` |
| 2 | `climate.set_temperature` to `T` | Climate `temperature` is back to `T` |
| 3 | `climate.set_preset_mode` `boost` | `preset_mode` `boost`, state `heat`, heating boost sensor `on`; the boost target is the current temperature rounded to 0.5 plus 0.5 |
| 4 | `climate.set_preset_mode` `none` | `preset_mode` `none`, the starting mode, boost sensor `off`; Hive can report the boost target until a later poll, then `T` |
| 5 | `hive.boost_heating_on`, `time_period: "00:05:00"`, `temperature: 16` | `preset_mode` `boost`, `temperature` 16, boost sensor `on` |
| 6 | `hive.boost_heating_off` | Starting mode, boost sensor `off`; the target returns to `T` as in step 4 |
| 7 | `hive.boost_hot_water`, `time_period: "00:05:00"`, `on_off: "on"` | Hot water boost sensor `on`; the operation still shows the mode the boost returns to |
| 8 | `hive.boost_hot_water`, `on_off: "off"` | Hot water back to its starting mode, boost sensor `off` |
| 9 | `water_heater.set_operation_mode` `eco` | Operation `eco` (Hive's schedule) |
| 10 | `water_heater.set_operation_mode` back to the starting mode | The starting mode |

## Finish

- Check the climate and hot water are back in their starting state, with no
  boost running, and fix them in the Hive app if not.
- Check the log again for errors or deprecation warnings.
- Remove the container, and the trusted device "Home Assistant" from the
  Hive app if removing the entry did not.
