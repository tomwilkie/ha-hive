"""Tests that keep the packaging and translation files consistent."""

import json
from pathlib import Path
import re
import tomllib

REPO = Path(__file__).resolve().parent.parent
INTEGRATION = REPO / "custom_components" / "hive"

# A release wheel URL with the requirement it satisfies as the fragment: the
# form Home Assistant accepts for custom integrations and hassfest lets through.
MANIFEST_REQUIREMENT = re.compile(
    r"^(?P<url>https://github\.com/tomwilkie/pyhive-integration/releases/download/"
    r"v(?P<tag>[\w.]+)/pyhive_integration-(?P<wheel_version>[\w.]+)-py3-none-any\.whl)"
    r"#pyhive-integration==(?P<version>[\w.]+)$"
)


def _key_tree(node: object) -> object:
    """Return the nested keys of a JSON value, with the leaf values dropped."""
    if isinstance(node, dict):
        return {key: _key_tree(value) for key, value in node.items()}
    return None


def _manifest_requirement() -> re.Match[str]:
    """Return the manifest's one requirement, parsed."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["requirements"]) == 1
    match = MANIFEST_REQUIREMENT.match(manifest["requirements"][0])
    assert match, manifest["requirements"][0]
    return match


def test_manifest_requirement_names_one_release() -> None:
    """The release tag, the wheel's version and the requirement's version agree."""
    requirement = _manifest_requirement()

    assert requirement["tag"] == requirement["wheel_version"] == requirement["version"]


def test_dev_dependency_installs_the_manifest_wheel() -> None:
    """The library the tests run against is the wheel the manifest asks Home Assistant for."""
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    dev_requirements = [
        requirement
        for requirement in pyproject["dependency-groups"]["dev"]
        if isinstance(requirement, str) and requirement.startswith("pyhive-integration")
    ]

    assert dev_requirements == [
        f"pyhive-integration @ {_manifest_requirement()['url']}"
    ]


def test_translations_match_strings() -> None:
    """en.json has exactly the keys of strings.json, with every reference resolved."""
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    translations_text = (INTEGRATION / "translations" / "en.json").read_text(
        encoding="utf-8"
    )

    assert _key_tree(json.loads(translations_text)) == _key_tree(strings)
    assert "[%key:" not in translations_text
