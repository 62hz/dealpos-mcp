import pytest
from dealpos_mcp.config import Settings


def test_settings_build_base_url_and_defaults(monkeypatch):
    monkeypatch.setenv("DEALPOS_SUBDOMAIN", "doubledeer.dealpos.co.id")
    monkeypatch.setenv("DEALPOS_CLIENT_ID", "cid")
    monkeypatch.setenv("DEALPOS_CLIENT_SECRET", "secret")
    s = Settings()
    assert s.base_url == "https://doubledeer.dealpos.co.id"
    assert s.low_stock_fallback == 5  # default


def test_settings_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("DEALPOS_CLIENT_ID", raising=False)
    monkeypatch.setenv("DEALPOS_SUBDOMAIN", "x")
    monkeypatch.setenv("DEALPOS_CLIENT_SECRET", "secret")
    with pytest.raises(Exception):
        Settings(_env_file=None)  # skip .env so monkeypatch deletion is effective
