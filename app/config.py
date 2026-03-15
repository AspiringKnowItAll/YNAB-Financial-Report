from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """
    Application-level configuration loaded from environment variables / .env file.
    No secrets here — only non-sensitive server settings.
    Secrets (API keys, passwords) are entered via the Settings UI and stored encrypted.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PORT: int = 8080
    SYNC_DAY_OF_MONTH: int = 1


config = Config()
