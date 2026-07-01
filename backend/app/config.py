from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    app_name: str = 'VexHost'
    database_url: str = 'postgresql+asyncpg://vexhost:vexhost@db:5432/vexhost'
    cors_origins: str = 'https://host.vexory.xyz'
    telegram_bot_token: str = ''
    telegram_admin_chat_id: str = ''
    dashboard_url: str = 'https://host.vexory.xyz/#dashboard'


settings = Settings()
