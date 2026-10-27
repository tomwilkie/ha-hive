# ha-hive

A custom Home Assistant integration for [Hive](https://www.hivehome.com/) heating and hot water,
forked from the built-in `hive` integration in
[home-assistant/core](https://github.com/home-assistant/core/tree/dev/homeassistant/components/hive).

The goal is a simpler, more robust integration: bounded timeouts, retries that Home Assistant can
see, and errors that propagate instead of being swallowed. The Hive API client lives in
[tomwilkie/pyhive-integration](https://github.com/tomwilkie/pyhive-integration), a hard fork of
[Pyhass/Pyhive](https://github.com/Pyhass/Pyhive) installed from its GitHub releases.

## Provenance

The history of `custom_components/hive/` and `tests/` was extracted from home-assistant/core with
`git filter-repo`, starting at the 2026.10.2 release with the `pyhive-integration` 1.0.10 bump
(home-assistant/core#187610) cherry-picked on top. Later changes in core `dev` depend on APIs not
yet in a Home Assistant release, so they will be ported one at a time.

## Install

The integration uses the `hive` domain, so it replaces the built-in integration and keeps the
existing config entry, devices and entity IDs.

1. In HACS, add `https://github.com/tomwilkie/ha-hive` as a custom repository of type
   **Integration**, then install **Hive**.
2. Restart Home Assistant. The log shows `We found a custom integration hive which has not been
   tested by Home Assistant`, which confirms that the override loaded.

Only the climate and water heater platforms are provided. The light, switch, sensor and binary
sensor entities the built-in integration created become unavailable and can be deleted from their
device pages.

To go back to the built-in integration, remove it in HACS and restart.

Requires Home Assistant 2026.10 or later.

## Development

```sh
uv sync                             # Home Assistant, the library wheel and the dev tools
uv run pytest                       # the full suite, with coverage
uv run pre-commit run --all-files   # ruff (Home Assistant core's rules), codespell, zizmor, yamllint
scripts/check_requirements          # install the manifest requirement under core's package pins
```

CI runs the same checks, plus [hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest/)
and the [HACS action](https://github.com/hacs/action). `scripts/check_requirements` reproduces how
Home Assistant installs the library: with uv, under the `package_constraints.txt` of the release
named in `hacs.json`.

`custom_components/hive/translations/en.json` is generated from `strings.json` by resolving its
`[%key:...%]` references against core's common strings. Regenerate it when `strings.json` changes;
a test checks that the two files have the same keys.

## License

Apache 2.0, as for Home Assistant. See [LICENSE.md](LICENSE.md).
