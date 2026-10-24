---
name: testing
description: Python test-writing best practices covering test structure, fixtures, parametrization, and mocking with pytest. Use when writing, reviewing, or refactoring tests, adding test coverage, or working in tests directories and conftest.py.
paths:
  - "tests/**"
  - "**/test_*.py"
  - "**/*_test.py"
  - "**/conftest.py"
---

# Python Testing

Test-writing practices for pytest that no linter checks.

**`CLAUDE.md` and the existing tests take precedence.** Where a rule's example
differs from the repo, follow the repo:

- The tests run under pytest-homeassistant-custom-component: use its `hass`,
  `device_registry` and `entity_registry` fixtures and `MockConfigEntry`.
  `enable_custom_integrations` is applied automatically (`tests/conftest.py`).
- Mock at the `apyhiveapi` boundary only. The fixtures in `tests/conftest.py`
  do that: `mock_hive` patches `Hive`, `mock_auth` (and `mock_auth_class`)
  patch `Auth` in the config flow, `mock_setup_entry` patches
  `async_setup_entry`. Build devices with `make_hub()`, `make_climate()`,
  `make_water_heater()` and `make_devices()` from `tests/common.py`, and set
  an entry up with `setup_entry()`. Do not build new mocks of the library.
- Drive the integration the way Home Assistant does: config entries, flows,
  services and states. Do not call entity methods or read `_attr_*`.
- Mock with `unittest.mock` (`MagicMock`, `AsyncMock`, `patch`); pytest-mock
  is not installed, so there is no `mocker` fixture.
- Home Assistant core style: every test has a docstring and typed parameters
  (`hass: HomeAssistant`, `mock_hive: MagicMock`), `@pytest.fixture` takes no
  parentheses, parametrize names are a tuple, and phases are separated by
  blank lines, not `# Arrange / # Act / # Assert` comments.
- `asyncio_mode = "auto"`: async tests need no `@pytest.mark.asyncio`.
- Always run the full `uv run pytest`; coverage must stay above `fail_under`
  in `pyproject.toml`.

## Categories

### Mocking [CRITICAL]

| Rule | Description |
|------|-------------|
| [mock-boundaries](rules/mock-boundaries.md) | Mock external boundaries, not internal logic |

### Test Structure [HIGH]

| Rule | Description |
|------|-------------|
| [struct-test-naming](rules/struct-test-naming.md) | Name tests after the behavior they verify |
| [struct-one-behavior](rules/struct-one-behavior.md) | Test one behavior per test |
| [struct-no-logic](rules/struct-no-logic.md) | Keep conditionals and loops out of tests |

### Fixtures [HIGH]

| Rule | Description |
|------|-------------|
| [fixture-scope](rules/fixture-scope.md) | Use the narrowest fixture scope that works |
| [fixture-factory](rules/fixture-factory.md) | Use factory fixtures for varied test data |

### Parametrization [MEDIUM]

| Rule | Description |
|------|-------------|
| [param-parametrize](rules/param-parametrize.md) | Replace duplicated tests with parametrize |
| [param-ids](rules/param-ids.md) | Give parametrized cases readable ids |

## Quick Reference

From `tests/test_init.py`: the library is mocked, the real integration runs,
and the outcome is read back the way Home Assistant exposes it.

```python
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
    """A rejected login starts a reauth flow; a transient failure is retried."""
    mock_hive.start_session.side_effect = error
    mock_auth.login.side_effect = HiveInvalidPassword()

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is state
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == flow_sources
```
