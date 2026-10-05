import pytest


@pytest.fixture(autouse=True)
def application_plugins(installed_plugins):
    """Lifecycle tests exercise real adapters from an explicit plugin directory."""
