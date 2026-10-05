import pytest

from tests.plugin_helpers import install_plugins


@pytest.fixture
def installed_plugins(tmp_path):
    return install_plugins(tmp_path / "plugins")
