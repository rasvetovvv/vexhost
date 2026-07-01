from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from .config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def init_db() -> None:
    from . import models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight alpha migrations. Safe to run repeatedly on PostgreSQL.
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS build_command VARCHAR(128)"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS output_dir VARCHAR(128)"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_deploy_status VARCHAR(32)"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_deploy_log TEXT"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_deployed_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS subdomain VARCHAR(64)"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS restart_count INTEGER DEFAULT 0"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_crash_reason VARCHAR(512)"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS restart_policy VARCHAR(16) DEFAULT 'always'"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_subdomain_unique ON projects (subdomain) WHERE subdomain IS NOT NULL"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS login_username VARCHAR(64)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(128)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT false"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT false"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_login_username_unique ON users (login_username) WHERE login_username IS NOT NULL"))

async def db_ping() -> bool:
    async with engine.connect() as conn:
        await conn.execute(text('SELECT 1'))
    return True
