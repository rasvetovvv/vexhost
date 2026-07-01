from pydantic import BaseModel, Field, field_validator


class WaitlistIn(BaseModel):
    telegram_username: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    project_type: str = Field(default='telegram_bot', max_length=64)
    message: str | None = Field(default=None, max_length=1200)

    @field_validator('telegram_username')
    @classmethod
    def clean_username(cls, value: str | None) -> str | None:
        if not value:
            return None
        return value.strip().lstrip('@')[:64]


class WaitlistOut(BaseModel):
    ok: bool
    id: int
    message: str


class LoginIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class LoginOut(BaseModel):
    ok: bool
    token: str
    username: str
    is_admin: bool = False


class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=96)
    type: str = Field(default='static_site', max_length=64)
    template_key: str | None = Field(default=None, max_length=64)
    repo_url: str | None = Field(default=None, max_length=512)
    subdomain: str | None = Field(default=None, max_length=64)
    build_command: str | None = Field(default='auto', max_length=128)
    output_dir: str | None = Field(default='auto', max_length=128)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value: str) -> str:
        return value.strip()

    @field_validator('repo_url')
    @classmethod
    def clean_repo(cls, value: str | None) -> str | None:
        if not value:
            return None
        return value.strip()

    @field_validator('subdomain')
    @classmethod
    def clean_subdomain(cls, value: str | None) -> str | None:
        if not value:
            return None
        return value.strip().lower().removesuffix('.vexory.xyz')

    @field_validator('output_dir')
    @classmethod
    def clean_output_dir(cls, value: str | None) -> str | None:
        if not value:
            return 'auto'
        return value.strip().strip('/') or 'auto'


class ProjectOut(BaseModel):
    id: int
    name: str
    slug: str
    subdomain: str | None = None
    type: str
    status: str
    repo_url: str | None = None
    live_url: str | None = None
    template_key: str | None = None
    build_command: str | None = None
    output_dir: str | None = None
    last_deploy_status: str | None = None
    last_deploy_log: str | None = None
    last_deployment_id: int | None = None
    restart_count: int = 0
    last_crash_reason: str | None = None
    restart_policy: str = 'always'


class UserOut(BaseModel):
    telegram_id: int
    username: str | None = None
    login_username: str | None = None
    first_name: str | None = None
    plan: str
    is_admin: bool = False


class DashboardOut(BaseModel):
    user: UserOut
    projects: list[ProjectOut]
    waitlist: dict
    limits: dict


class DeployIn(BaseModel):
    repo_url: str | None = Field(default=None, max_length=512)
    build_command: str | None = Field(default=None, max_length=128)
    output_dir: str | None = Field(default=None, max_length=128)


class DeployOut(BaseModel):
    ok: bool
    deployment_id: int
    status: str
    live_url: str | None = None
    log: str | None = None


class DeploymentOut(BaseModel):
    id: int
    project_id: int
    status: str
    repo_url: str | None = None
    build_command: str | None = None
    output_dir: str | None = None
    log: str | None = None
    live_url: str | None = None


class AdminSummaryOut(BaseModel):
    users: int
    projects: int
    deployments: int
    recent_projects: list[ProjectOut]
