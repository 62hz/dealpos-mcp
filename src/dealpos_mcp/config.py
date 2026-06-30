from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEALPOS_", env_file=".env", extra="ignore")

    subdomain: str
    client_id: str
    client_secret: str
    default_outlet: str | None = None
    low_stock_fallback: int = 5

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}"
