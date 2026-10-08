from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEALPOS_",
        env_file=(str(ENV_FILE), ".env"),
        extra="ignore"
    )

    subdomain: str = "doubledeer.dealpos.co.id"
    client_id: str
    client_secret: str
    default_outlet: str | None = None
    low_stock_fallback: int = 5
    # Safe by default: write tools refuse to run until DEALPOS_READ_ONLY=false.
    read_only: bool = True

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}"
