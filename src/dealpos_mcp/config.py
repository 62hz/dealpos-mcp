from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEALPOS_",
        env_file=str(ENV_FILE),   # package root only; never the caller's cwd
        extra="ignore"
    )

    subdomain: str = "doubledeer.dealpos.co.id"
    client_id: str
    client_secret: str
    default_outlet: str | None = None
    low_stock_fallback: int = 5
    # Safe by default: write tools refuse to run until DEALPOS_READ_ONLY=false.
    read_only: bool = True
    # DealPOS allows 50 requests per 180 s with no queue (GET /api/v3/ratelimit). Stay
    # under it with a small margin; set DEALPOS_RATE_PERMITS=0 to switch the limiter off.
    rate_permits: int = 45
    rate_window: float = 180.0

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}"
