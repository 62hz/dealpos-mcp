import pytest
from dealpos_mcp.config import Settings
from dealpos_mcp.client import DealPOSClient


@pytest.fixture(autouse=True)
def _writes_enabled(monkeypatch):
    """The suite tests write tools against mocked HTTP; production default is read-only."""
    monkeypatch.setenv("DEALPOS_READ_ONLY", "false")


@pytest.fixture
def settings():
    # _env_file=None: a developer's own .env must not leak into the suite.
    return Settings(subdomain="example.dealpos.co.id", client_id="cid", client_secret="sec",
                    default_outlet="Main Store", _env_file=None)


@pytest.fixture
def client(settings):
    return DealPOSClient(settings)
