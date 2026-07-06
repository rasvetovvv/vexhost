from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    app_name: str = 'VexHost'
    database_url: str = 'postgresql+asyncpg://vexhost:vexhost@db:5432/vexhost'
    cors_origins: str = 'https://host.vexory.xyz'
    telegram_bot_token: str = ''
    telegram_admin_chat_id: str = ''
    # Secret for signing web session tokens. Set a long random value in
    # production. Public production refuses to use an implicit fallback.
    auth_secret: str = ''
    # Shared secret used by backend -> runtime-manager requests. Runtime
    # containers live on the same Docker network, so every runtime-manager
    # mutating/read endpoint must require this header.
    runtime_manager_token: str = ''
    dashboard_url: str = 'https://host.vexory.xyz/#dashboard'


settings = Settings()
