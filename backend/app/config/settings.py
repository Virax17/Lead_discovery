from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    google_places_api_key: str
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "lead_discovery"
    app_secret_key: str
    shared_username: str = "admin"
    shared_password_hash: str = ""
    bootstrap_admin_username: str = ""
    bootstrap_admin_password: str = ""
    bootstrap_admin_credit_limit: int = 1000
    bootstrap_user_username: str = ""
    bootstrap_user_password: str = ""
    bootstrap_user_credit_limit: int = 1000

    # Comma-separated list of allowed frontend origins, e.g. "https://app.example.com".
    # Leave unset to fall back to localhost-only (dev default).
    cors_allowed_origins: str = ""

    # S3-backed export storage. Leave unset to use local disk (backend/exports/) as today.
    s3_bucket: str = ""
    s3_region: str = ""
    s3_prefix: str = "exports/"

    model_config = SettingsConfigDict(env_file=(".env", "backend/.env"), extra="ignore")

settings = Settings()
