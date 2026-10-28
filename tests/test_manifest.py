"""Tests that keep the packaging and translation files consistent."""

import json
from pathlib import Path
import re
import tomllib

REPO = Path(__file__).resolve().parent.parent
INTEGRATION = REPO / "custom_components" / "hive"

# The library pinned to one PyPI release, the form hassfest requires.
MANIFEST_REQUIREMENT = re.compile(r"^apyhiveapi==(?P<version>[\w.]+)$")


def _key_tree(node: object) -> object:
    """Return the nested keys of a JSON value, with the leaf values dropped."""
    if isinstance(node, dict):
        return {key: _key_tree(value) for key, value in node.items()}
    return None


def _manifest_requirement() -> str:
    """Return the manifest's one requirement, a pinned release of the library."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["requirements"]) == 1
    requirement = manifest["requirements"][0]
    assert MANIFEST_REQUIREMENT.match(requirement), requirement
    return requirement


def test_dev_dependency_installs_the_manifest_release() -> None:
    """The library the tests run against is the release the manifest asks Home Assistant for."""
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    dev_requirements = [
        requirement
        for requirement in pyproject["dependency-groups"]["dev"]
        if isinstance(requirement, str) and requirement.startswith("apyhiveapi")
    ]

    assert dev_requirements == [_manifest_requirement()]


def test_translations_match_strings() -> None:
    """en.json has exactly the keys of strings.json, with every reference resolved."""
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    translations_text = (INTEGRATION / "translations" / "en.json").read_text(
        encoding="utf-8"
    )

    assert _key_tree(json.loads(translations_text)) == _key_tree(strings)
    assert "[%key:" not in translations_text
