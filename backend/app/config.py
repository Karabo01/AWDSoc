from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Identity of this deployment. Appears in the JWT `iss` claim.
    app_name: str = "awdsoc"
    environment: str = "development"
    # Public origin of the console. Appears in the ingest URL handed to each
    # client's manager, so getting it wrong breaks onboarding, not the console.
    console_base_url: str = "https://soc.awdtech.co.za"

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
    # A single request may carry one alert object or an array. The array form
    # exists so a batching sidecar can arrive without an API change.
    ingest_max_batch: int = 500
    ingest_max_body_bytes: int = 4 * 1024 * 1024
    # Traefik appends the real peer to X-Forwarded-For, so the trustworthy entry
    # is counted from the RIGHT. One hop = Traefik only.
    ingest_trusted_proxy_hops: int = 1

    ingest_stream_key: str = "awdsoc:alerts"
    ingest_consumer_group: str = "writers"
    # Bounds Redis memory if the worker dies. Roughly a day of a busy cohort.
    ingest_stream_maxlen: int = 1_000_000

    # Tenant auth is cached so ingest costs no database round trip. On a refresh
    # failure the stale entry is served until the hard TTL - a degraded Postgres
    # must not stop ingestion.
    tenant_cache_soft_ttl: int = 30
    tenant_cache_hard_ttl: int = 900
    # Unknown slugs are cached too, or a scanner hammers Postgres for free.
    tenant_cache_negative_ttl: int = 10
    alert_retention_days: int = 90
    normalisation_map_version: int = 1
    wazuh_sync_interval: int = 300

    # Partitions are created this many months ahead by the maintenance task.
    partition_premake_months: int = 3

    # Each Postgres connection costs the server several MB, so on a small host
    # the pool is a real memory decision: api and worker each hold their own.
    db_pool_size: int = 10
    db_max_overflow: int = 20

    sql_echo: bool = Field(default=False)

    @property
    def rate_limit(self) -> tuple[int, int]:
        """(requests, window_seconds) parsed from e.g. "500/second"."""
        raw = self.ingest_rate_limit_per_tenant.strip()
        count, _, unit = raw.partition("/")
        windows = {"second": 1, "minute": 60, "hour": 3600}
        try:
            return int(count), windows[unit.strip().lower()]
        except (ValueError, KeyError) as exc:
            raise ValueError(
                f"INGEST_RATE_LIMIT_PER_TENANT must look like '500/second', got {raw!r}"
            ) from exc

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

    @model_validator(mode="after")
    def _rate_limit_parses(self) -> "Settings":
        """Checked at import: a typo here would otherwise surface as a 500 on the
        first alert a client ever sends."""
        _ = self.rate_limit
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
