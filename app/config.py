from pydantic_settings import SettingsConfigDict, BaseSettings

class Settings(BaseSettings):
    # Database Settings (defaults to local sqlite for test/dev if unset)
    database_url: str = "sqlite:///./dev.db"
    secret_key: str = "dev-insecure-secret-key-change-in-production-123456789"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Email Settings
    email_host_user: str = "dev@example.com"
    email_host_password: str = "dev-password"
    default_from_email: str = "noreply@example.com"
    email_smtp_server: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    
    # Redis Settings
    redis_url: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()