"""Shared test fixtures for the pvnode integration test suite."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

_REPO_ROOT = Path(__file__).parent.parent
_SOURCE = _REPO_ROOT / "custom_components" / "pvnode"


def pytest_configure(config: object) -> None:
    """Make this repo's custom_components/pvnode discoverable by the HA test harness.

    pytest-homeassistant-custom-component always looks for custom integrations
    under its own package's `testing_config/custom_components` directory, so we
    link (or copy, if symlinks aren't available) this repo's integration there
    once before the test session starts.
    """
    import pytest_homeassistant_custom_component.common as ha_common

    target_root = (
        Path(ha_common.__file__).parent / "testing_config" / "custom_components"
    )
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / "pvnode"

    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)

    try:
        target.symlink_to(_SOURCE, target_is_directory=True)
    except OSError:
        shutil.copytree(_SOURCE, target)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integration loading for every test in this suite."""
