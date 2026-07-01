from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class WaitlistRequest(Base):
    __tablename__ = 'waitlist_requests'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    project_type: Mapped[str] = mapped_column(String(64), default='telegram_bot')
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default='landing')
    ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default='new')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    plan: Mapped[str] = mapped_column(String(32), default='free')
    login_username: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_admin: Mapped[bool] = mapped_column(default=False)
    is_suspended: Mapped[bool] = mapped_column(default=False, server_default='false')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    projects: Mapped[list['Project']] = relationship(back_populates='user')


class Project(Base):
    __tablename__ = 'projects'
    __table_args__ = (UniqueConstraint('user_id', 'slug', name='uq_projects_user_slug'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(96))
    slug: Mapped[str] = mapped_column(String(96), index=True)
    subdomain: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    type: Mapped[str] = mapped_column(String(64), default='telegram_bot')
    status: Mapped[str] = mapped_column(String(32), default='draft')
    repo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    live_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    build_command: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_deploy_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_deploy_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    last_crash_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    restart_policy: Mapped[str] = mapped_column(String(16), default='always', server_default='always')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates='projects')
    deployments: Mapped[list['Deployment']] = relationship(back_populates='project')


class Deployment(Base):
    __tablename__ = 'deployments'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    status: Mapped[str] = mapped_column(String(32), default='queued')
    repo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    build_command: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(128), nullable=True)
    log: Mapped[str | None] = mapped_column(Text, nullable=True)
    live_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates='deployments')
