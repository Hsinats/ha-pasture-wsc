"""Real HA fixture suite; run on Linux with the custom-component pytest plugin."""
import pytest

@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield
