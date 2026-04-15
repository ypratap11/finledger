from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://finledger:finledger@localhost:5432/finledger"
    stripe_webhook_secret: str = "whsec_test_placeholder"
    stripe_api_key: str = "sk_test_placeholder"
    zuora_webhook_secret: str = "zuora_test_placeholder"


settings = Settings()
