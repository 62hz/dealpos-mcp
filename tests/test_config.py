import pytest
from dealpos_mcp.config import Settings


def test_settings_build_base_url_and_defaults(monkeypatch):
    monkeypatch.setenv("DEALPOS_SUBDOMAIN", "doubledeer.dealpos.co.id")
    monkeypatch.setenv("DEALPOS_CLIENT_ID", "cid")
    monkeypatch.setenv("DEALPOS_CLIENT_SECRET", "secret")
    s = Settings()
    assert s.base_url == "https://doubledeer.dealpos.co.id"
    assert s.low_stock_fallback == 5  # default


def test_settings_defaults_are_safe_and_instant(monkeypatch):
    monkeypatch.delenv("DEALPOS_READ_ONLY", raising=False)
    monkeypatch.delenv("DEALPOS_SUBDOMAIN", raising=False)
    s = Settings(client_id="cid", client_secret="secret", _env_file=None)
    assert s.read_only is True                        # writes opt-in
    assert s.subdomain == "doubledeer.dealpos.co.id"  # only the two secrets are required


def test_settings_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("DEALPOS_CLIENT_ID", raising=False)
    monkeypatch.setenv("DEALPOS_SUBDOMAIN", "x")
    monkeypatch.setenv("DEALPOS_CLIENT_SECRET", "secret")
    with pytest.raises(Exception):
        Settings(_env_file=None)  # skip .env so monkeypatch deletion is effective


def test_rate_limit_defaults_sit_under_the_api_limit_and_are_overridable(monkeypatch):
    s = Settings(client_id="cid", client_secret="sec", _env_file=None)
    assert (s.rate_permits, s.rate_window) == (45, 180.0)  # API allows 50 per 180 s
    monkeypatch.setenv("DEALPOS_RATE_PERMITS", "10")
    monkeypatch.setenv("DEALPOS_RATE_WINDOW", "60")
    s = Settings(client_id="cid", client_secret="sec", _env_file=None)
    assert (s.rate_permits, s.rate_window) == (10, 60.0)


def test_env_read_only_true_beats_dotenv_false(monkeypatch, tmp_path):
    # MF agents run dealpos-mcp with DEALPOS_READ_ONLY=true while Django's .env says false.
    env = tmp_path / ".env"
    env.write_text("DEALPOS_READ_ONLY=false\nDEALPOS_CLIENT_ID=cid\nDEALPOS_CLIENT_SECRET=sec\n")
    monkeypatch.setenv("DEALPOS_READ_ONLY", "true")
    s = Settings(_env_file=str(env))
    assert s.read_only is True
