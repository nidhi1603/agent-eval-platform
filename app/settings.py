from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All config comes from AEP_* environment variables (set by the Helm chart)."""

    model_config = SettingsConfigDict(env_prefix="AEP_")

    database_url: str = "sqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "aep:trials"

    # Where trial pods run and how they call back.
    namespace: str = "default"
    trial_image: str = "agent-eval:dev"
    api_url: str = "http://localhost:8000"

    # Cap on concurrently active trial attempts (protects LLM rate limits; OpenAI usage tier 1).
    max_concurrency: int = 2
    # Infrastructure failures (pod crash, lost Job, missing callback) are retried this many times;
    # agent failures and deadline expiry are results and are never retried.
    max_infra_retries: int = 1
    reconcile_interval_seconds: int = 5
    missing_job_grace_seconds: int = 60
    trial_cpu_limit: str = "500m"
    trial_memory_limit: str = "512Mi"
    trial_deadline_seconds: int = 900


settings = Settings()
