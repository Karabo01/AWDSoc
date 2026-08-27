from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Identity of this deployment. Appears in the JWT `iss` claim.
    app_name: str = "awdsoc"
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://awdsoc:awdsoc@localhost:5432/awdsoc"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl: int = 900
    jwt_refresh_ttl: int = 1209600

    # 32 bytes, base64. Encrypts Wazuh Manager API passwords at rest.
    encryption_key: str = ""
    encryption_key_version: int = 1

    ingest_max_skew_seconds: int = 300
    ingest_rate_limit_per_tenant: str = "500/second"
    alert_retention_days: int = 90
    normalisation_map_version: int = 1
    wazuh_sync_interval: int = 300

    # Partitions are created this many months ahead by the maintenance task.
    partition_premake_months: int = 3

    sql_echo: bool = Field(default=False)

    @model_validator(mode="after")
    def _refuse_weak_production_secrets(self) -> "Settings":
        """A short or default signing key forges every token in the product.

        Checked at import so a misconfigured deploy fails to start rather than
        running happily with a guessable secret.
        """
        if self.environment != "production":
            return self
        if len(self.jwt_secret.encode()) < 32 or self.jwt_secret == "dev-only-change-me":
            raise ValueError("JWT_SECRET must be at least 32 bytes in production")
        if not self.encryption_key:
            raise ValueError("ENCRYPTION_KEY must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
