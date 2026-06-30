import pytest
from dealpos_mcp.config import Settings
from dealpos_mcp.client import DealPOSClient


@pytest.fixture
def settings():
    return Settings(subdomain="doubledeer.dealpos.co.id", client_id="cid", client_secret="sec")


@pytest.fixture
def client(settings):
    return DealPOSClient(settings)
