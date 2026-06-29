from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    google_places_api_key: str
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "lead_discovery"
    app_secret_key: str
    shared_username: str = "admin"
    shared_password_hash: str
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
