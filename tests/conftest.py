import pytest
from dealpos_mcp.config import Settings
from dealpos_mcp.client import DealPOSClient


@pytest.fixture(autouse=True)
def _writes_enabled(monkeypatch):
    """The suite tests write tools against mocked HTTP; production default is read-only."""
    monkeypatch.setenv("DEALPOS_READ_ONLY", "false")


@pytest.fixture
def settings():
    return Settings(subdomain="doubledeer.dealpos.co.id", client_id="cid", client_secret="sec")


@pytest.fixture
def client(settings):
    return DealPOSClient(settings)
