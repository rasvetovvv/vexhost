from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import os
import re
import shutil
import base64
import secrets
import zipfile
import subprocess
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import time
from urllib.parse import parse_qsl, urlparse

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, delete

from .config import settings
from .db import SessionLocal, db_ping, init_db
from .deployer import delete_static, validate_build_options, validate_public_repo, DeployValidationError, _copytree_clean
from .models import Deployment, Project, User, WaitlistRequest
from .schemas import AdminSummaryOut, DashboardOut, DeployIn, DeployOut, DeploymentOut, LoginIn, LoginOut, ProjectIn, ProjectOut, UserOut, WaitlistIn, WaitlistOut


DEPLOY_ROOT = Path(os.environ.get('DEPLOY_ROOT', '/data/deployments'))
TEMPLATES = [
    {'key': 'telegram-bot-starter', 'name': 'Telegram Bot Starter', 'type': 'telegram_bot', 'description': 'aiogram webhook bot with Docker, healthcheck and env example.'},
    {'key': 'mini-app-starter', 'name': 'Mini App Starter', 'type': 'mini_app', 'description': 'React + Vite Mini App with FastAPI backend and initData validation.'},
    {'key': 'fastapi-api', 'name': 'FastAPI API', 'type': 'api', 'description': 'Clean Python API starter with PostgreSQL and Redis-ready structure.'},
    {'key': 'react-landing', 'name': 'React Landing', 'type': 'static_site', 'description': 'Dark SaaS landing page built with React, Vite and Tailwind-ready CSS.'},
    {'key': 'ai-support-bot', 'name': 'AI Support Bot', 'type': 'telegram_bot', 'description': 'Telegram support bot concept with tickets and knowledge-base hooks.'},
    {'key': 'stars-store', 'name': 'Telegram Stars Store', 'type': 'mini_app', 'description': 'Digital goods Mini App concept with Stars checkout flow.'},
]

ADDONS = [
    {'key': 'postgres', 'name': 'PostgreSQL database', 'category': 'database', 'price': 'Free beta', 'status': 'available', 'description': 'Managed project database with connection string and backups.'},
    {'key': 'redis', 'name': 'Redis', 'category': 'database', 'price': 'Free beta', 'status': 'available', 'description': 'Cache, queues and sessions for bots/APIs.'},
    {'key': 'file-storage', 'name': 'File storage', 'category': 'storage', 'price': 'Coming soon', 'status': 'soon', 'description': 'Persistent object/file storage for uploads and media.'},
    {'key': 'cron-jobs', 'name': 'Cron jobs', 'category': 'automation', 'price': 'Free beta', 'status': 'available', 'description': 'Scheduled commands and background jobs.'},
    {'key': 'email-sending', 'name': 'Email sending', 'category': 'communication', 'price': 'Coming soon', 'status': 'soon', 'description': 'SMTP/API email for transactional messages.'},
    {'key': 'ai-credits', 'name': 'AI credits', 'category': 'ai', 'price': 'Coming soon', 'status': 'soon', 'description': 'LLM/image API credits for apps and bots.'},
    {'key': 'custom-domain', 'name': 'Custom domain', 'category': 'network', 'price': 'Pro', 'status': 'soon', 'description': 'Bring your own domain with TLS.'},
    {'key': 'extra-ram', 'name': 'Extra RAM', 'category': 'compute', 'price': 'Pro', 'status': 'soon', 'description': 'Increase container memory limits.'},
    {'key': 'extra-disk', 'name': 'Extra disk', 'category': 'storage', 'price': 'Pro', 'status': 'soon', 'description': 'Increase workspace and deployment disk quota.'},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    DEPLOY_ROOT.mkdir(parents=True, exist_ok=True)
    await init_db()
    watchdog = asyncio.create_task(_runtime_watchdog())
    try:
        yield
    finally:
        watchdog.cancel()
        try:
            await watchdog
        except asyncio.CancelledError:
            pass


app = FastAPI(title='VexHost API', version='0.3.0', lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(',') if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ['*'],
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'OPTIONS'],
    allow_headers=['*'],
)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get('x-forwarded-for', '')
    return (forwarded.split(',')[0].strip() or (request.client.host if request.client else ''))


def _hash_ip(ip: str) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(('vexhost:' + ip).encode()).hexdigest()


def _slugify(value: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    return slug[:64] or 'project'




def _auth_secret() -> bytes:
    raw = settings.telegram_bot_token or settings.database_url
    return hashlib.sha256(('vexhost-auth:' + raw).encode()).digest()


def _password_hash(password: str) -> str:
    salt = secrets.token_hex(12)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120_000).hex()
    return f'pbkdf2${salt}${digest}'


def _verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith('pbkdf2$'):
        return False
    _, salt, digest = stored.split('$', 2)
    calc = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(calc, digest)


def _make_login_username(tg: dict) -> str:
    base = (tg.get('username') or f"tg{tg['id']}").lower()
    base = re.sub(r'[^a-z0-9_]+', '', base)[:40] or f"tg{tg['id']}"
    return f'vex_{base}'


def _issue_token(user: User) -> str:
    payload = {'uid': user.id, 'ts': int(time())}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
    sig = hmac.new(_auth_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f'{raw}.{sig}'


def _read_token(token: str) -> int | None:
    try:
        raw, sig = token.split('.', 1)
        calc = hmac.new(_auth_secret(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, sig):
            return None
        padded = raw + '=' * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if time() - int(payload.get('ts', 0)) > 86400 * 30:
            return None
        return int(payload['uid'])
    except Exception:
        return None


def _validate_subdomain(value: str | None, fallback: str) -> str:
    sub = (value or fallback).lower().removesuffix('.vexory.xyz')
    sub = re.sub(r'[^a-z0-9-]+', '-', sub).strip('-')[:50]
    if not sub or len(sub) < 3:
        raise HTTPException(status_code=422, detail='Subdomain must be at least 3 characters.')
    reserved = {'www','host','api','app','bot','proxy','client','admin','mail','ftp','vexory'}
    if sub in reserved or sub.startswith('-') or sub.endswith('-'):
        raise HTTPException(status_code=422, detail='This subdomain is reserved.')
    return sub


def _validate_public_repo(url: str) -> str:
    try:
        return validate_public_repo(url)
    except DeployValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _validate_build_options(build_command: str | None, output_dir: str | None) -> tuple[str, str]:
    try:
        return validate_build_options(build_command, output_dir)
    except DeployValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def validate_init_data(init_data: str) -> dict:
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail='Telegram auth is not configured.')
    if not init_data:
        raise HTTPException(status_code=401, detail='Open this dashboard from Telegram.')
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop('hash', None)
    auth_date = int(pairs.get('auth_date') or 0)
    if not received_hash or not auth_date:
        raise HTTPException(status_code=401, detail='Invalid Telegram initData.')
    if time() - auth_date > 86400 * 7:
        raise HTTPException(status_code=401, detail='Telegram session expired. Reopen the Mini App.')
    data_check = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b'WebAppData', settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=401, detail='Telegram signature mismatch.')
    try:
        user = json.loads(pairs.get('user') or '{}')
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail='Invalid Telegram user payload.')
    if not user.get('id'):
        raise HTTPException(status_code=401, detail='Telegram user is missing.')
    return user


async def _ensure_credentials(session, user: User, tg: dict | None = None) -> tuple[User, str | None]:
    new_password = None
    if not user.login_username:
        base = _make_login_username(tg or {'id': user.telegram_id, 'username': user.username})
        username = base
        i = 2
        while await session.scalar(select(User.id).where(User.login_username == username, User.id != user.id)):
            username = f'{base}{i}'
            i += 1
        user.login_username = username
    if not user.password_hash:
        new_password = secrets.token_urlsafe(9)
        user.password_hash = _password_hash(new_password)
    admin_id = str(user.telegram_id)
    if settings.telegram_admin_chat_id and admin_id == str(settings.telegram_admin_chat_id):
        user.is_admin = True
    return user, new_password


async def current_user(x_telegram_init_data: str = Header(default=''), authorization: str = Header(default='')) -> User:
    if authorization.lower().startswith('bearer '):
        uid = _read_token(authorization.split(' ', 1)[1].strip())
        if uid:
            async with SessionLocal() as session:
                user = await session.scalar(select(User).where(User.id == uid))
                if user:
                    if user.is_suspended:
                        raise HTTPException(status_code=403, detail='Account is suspended. Contact support.')
                    return user
        raise HTTPException(status_code=401, detail='Invalid or expired web session. Login again.')

    tg = validate_init_data(x_telegram_init_data)
    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.telegram_id == int(tg['id'])))
        if existing:
            existing.username = tg.get('username')
            existing.first_name = tg.get('first_name')
            existing.last_name = tg.get('last_name')
            existing.language_code = tg.get('language_code')
            await _ensure_credentials(session, existing, tg)
            await session.commit()
            await session.refresh(existing)
            if existing.is_suspended:
                raise HTTPException(status_code=403, detail='Account is suspended. Contact support.')
            return existing
        user = User(telegram_id=int(tg['id']), username=tg.get('username'), first_name=tg.get('first_name'), last_name=tg.get('last_name'), language_code=tg.get('language_code'))
        session.add(user)
        await session.flush()
        await _ensure_credentials(session, user, tg)
        await session.commit()
        await session.refresh(user)
        if user.is_suspended:
            raise HTTPException(status_code=403, detail='Account is suspended. Contact support.')
        return user


async def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail='Admin access required.')
    return user


async def notify_telegram(item: WaitlistRequest) -> None:
    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        return
    text = (
        '🚀 <b>New VexHost waitlist request</b>\n\n'
        f'<b>ID:</b> {item.id}\n'
        f'<b>Telegram:</b> @{html.escape(item.telegram_username or "not provided")}\n'
        f'<b>Email:</b> {html.escape(item.email or "not provided")}\n'
        f'<b>Project:</b> {html.escape(item.project_type)}\n'
        f'<b>Message:</b> {html.escape((item.message or "")[:500])}'
    )
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(f'https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage', json={'chat_id': settings.telegram_admin_chat_id, 'text': text, 'parse_mode': 'HTML'})
    except Exception:
        return


def project_out(item: Project, last_deployment_id: int | None = None) -> ProjectOut:
    return ProjectOut(
        id=item.id, name=item.name, slug=item.slug, subdomain=item.subdomain, type=item.type, status=item.status,
        repo_url=item.repo_url, live_url=item.live_url, template_key=item.template_key,
        build_command=item.build_command, output_dir=item.output_dir,
        last_deploy_status=item.last_deploy_status, last_deploy_log=item.last_deploy_log,
        last_deployment_id=last_deployment_id,
        restart_count=item.restart_count or 0, last_crash_reason=item.last_crash_reason,
        restart_policy=item.restart_policy or 'always',
    )


def _run(cmd: list[str], cwd: Path, log: list[str], timeout: int = 180) -> None:
    log.append(f'$ {" ".join(cmd)}')
    proc = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if proc.stdout:
        log.append(proc.stdout[-6000:])
    if proc.returncode != 0:
        raise RuntimeError(f'Command failed with exit code {proc.returncode}: {" ".join(cmd)}')


def _copytree_clean(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in {'.git', 'node_modules'}:
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns('.git', 'node_modules'))
        else:
            shutil.copy2(item, target)


def _deploy_static(repo_url: str, slug: str, build_command: str | None, output_dir: str | None) -> tuple[str, str]:
    repo_url = _validate_public_repo(repo_url)
    cmd = (build_command or 'auto').strip()
    out = (output_dir or 'auto').strip().strip('/') or 'auto'
    if cmd not in ALLOWED_BUILD_COMMANDS:
        raise HTTPException(status_code=422, detail='Allowed build commands: auto, none, npm install && npm run build, npm ci && npm run build, npm run build.')
    if out != 'auto' and (out.startswith('.') or '..' in Path(out).parts):
        raise HTTPException(status_code=422, detail='Invalid output directory.')
    log: list[str] = ['VexHost Stage 3 static deploy started.', f'Repo: {repo_url}', f'Build: {cmd}', f'Output: {out}']
    with tempfile.TemporaryDirectory(prefix='vexhost-build-') as tmp:
        work = Path(tmp) / 'repo'
        _run(['git', 'clone', '--depth', '1', repo_url, str(work)], Path(tmp), log, timeout=120)
        package_json = work / 'package.json'
        if cmd == 'auto':
            if package_json.exists():
                lock = work / 'package-lock.json'
                _run(['npm', 'ci' if lock.exists() else 'install'], work, log, timeout=240)
                _run(['npm', 'run', 'build'], work, log, timeout=240)
            else:
                log.append('No package.json found. Publishing repository files as static site.')
        elif cmd in {'', 'none'}:
            log.append('Build skipped by user.')
        elif cmd == 'npm install && npm run build':
            _run(['npm', 'install'], work, log, timeout=240)
            _run(['npm', 'run', 'build'], work, log, timeout=240)
        elif cmd == 'npm ci && npm run build':
            _run(['npm', 'ci'], work, log, timeout=240)
            _run(['npm', 'run', 'build'], work, log, timeout=240)
        elif cmd == 'npm run build':
            _run(['npm', 'run', 'build'], work, log, timeout=240)

        if out == 'auto':
            candidates = ['dist', 'build', 'out', 'public'] if package_json.exists() else ['.']
            output_path = next((work / c for c in candidates if (work / c).exists()), None)
        else:
            output_path = work / out
        if not output_path or not output_path.exists() or not output_path.is_dir():
            raise RuntimeError(f'Output directory not found: {out}')
        index = output_path / 'index.html'
        if not index.exists():
            log.append('Warning: output directory has no index.html. Nginx directory listing is disabled, so root may return 403.')
        target = DEPLOY_ROOT / slug
        _copytree_clean(output_path, target)
        log.append(f'Published to /p/{slug}/')
    return f'https://host.vexory.xyz/p/{slug}/', '\n'.join(log)[-12000:]


@app.get('/healthz')
async def healthz() -> dict:
    await db_ping()
    return {'ok': True, 'service': 'vexhost-api'}


@app.get('/api/stats')
async def stats() -> dict:
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count(WaitlistRequest.id))) or 0
        users = await session.scalar(select(func.count(User.id))) or 0
        projects = await session.scalar(select(func.count(Project.id))) or 0
    return {'waitlist': count, 'users': users, 'projects': projects, 'stage': 'deploy-worker-alpha'}


@app.post('/api/waitlist', response_model=WaitlistOut)
async def join_waitlist(payload: WaitlistIn, request: Request) -> WaitlistOut:
    if not payload.telegram_username and not payload.email:
        raise HTTPException(status_code=422, detail='Add your Telegram username or email so we can invite you.')
    async with SessionLocal() as session:
        item = WaitlistRequest(telegram_username=payload.telegram_username, email=payload.email, project_type=payload.project_type, message=payload.message, ip_hash=_hash_ip(_client_ip(request)))
        session.add(item)
        await session.commit()
        await session.refresh(item)
    await notify_telegram(item)
    return WaitlistOut(ok=True, id=item.id, message='You are on the VexHost early access list.')


@app.get('/api/templates')
async def templates() -> dict:
    return {'items': TEMPLATES}


@app.get('/api/addons')
async def addons(user: User = Depends(current_user)) -> dict:
    return {'items': ADDONS, 'plan': user.plan}



@app.post('/api/auth/login', response_model=LoginOut)
async def web_login(payload: LoginIn) -> LoginOut:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.login_username == payload.username.strip()))
        if not user or not _verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail='Wrong username or password.')
        if user.is_suspended:
            raise HTTPException(status_code=403, detail='Account is suspended. Contact support.')
        token = _issue_token(user)
        return LoginOut(ok=True, token=token, username=user.login_username or '', is_admin=user.is_admin)


@app.get('/api/internal/tls-check')
async def tls_check(domain: str = '') -> dict:
    host = domain.lower().split(':', 1)[0]
    if not host.endswith('.vexory.xyz'):
        raise HTTPException(status_code=404, detail='Unknown domain')
    sub = host.removesuffix('.vexory.xyz')
    async with SessionLocal() as session:
        exists = await session.scalar(select(Project.id).where(Project.subdomain == sub).limit(1))
    if not exists:
        raise HTTPException(status_code=404, detail='Site not found')
    return {'ok': True}


@app.get('/api/dashboard', response_model=DashboardOut)
async def dashboard(user: User = Depends(current_user)) -> DashboardOut:
    async with SessionLocal() as session:
        rows = (await session.scalars(select(Project).where(Project.user_id == user.id).order_by(Project.id.desc()))).all()
        waitlist_count = await session.scalar(select(func.count(WaitlistRequest.id)).where(WaitlistRequest.telegram_username == user.username)) if user.username else 0
        latest: dict[int, int] = {}
        for project in rows:
            dep_id = await session.scalar(select(Deployment.id).where(Deployment.project_id == project.id).order_by(Deployment.id.desc()).limit(1))
            if dep_id:
                latest[project.id] = dep_id
    return DashboardOut(user=UserOut(telegram_id=user.telegram_id, username=user.username, login_username=user.login_username, first_name=user.first_name, plan=user.plan, is_admin=user.is_admin), projects=[project_out(p, latest.get(p.id)) for p in rows], waitlist={'matched_requests': int(waitlist_count or 0), 'status': 'active'}, limits={'projects_used': len(rows), 'projects_limit': 20 if user.plan == 'free' else 100, 'plan': user.plan})


@app.post('/api/projects', response_model=ProjectOut)
async def create_project(payload: ProjectIn, user: User = Depends(current_user)) -> ProjectOut:
    repo_url = _validate_public_repo(payload.repo_url) if payload.repo_url else None
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count(Project.id)).where(Project.user_id == user.id)) or 0
        limit = 20 if user.plan == 'free' else 100
        if count >= limit:
            raise HTTPException(status_code=403, detail=f'Project limit reached: {limit}.')
        slug_base = _slugify(payload.name)
        slug = slug_base
        i = 2
        while await session.scalar(select(Project.id).where(Project.slug == slug)):
            slug = f'{slug_base}-{i}'
            i += 1
        subdomain = _validate_subdomain(payload.subdomain, slug)
        sub_base = subdomain
        j = 2
        while await session.scalar(select(Project.id).where(Project.subdomain == subdomain)):
            subdomain = f'{sub_base}-{j}'[:50].strip('-')
            j += 1
        live_url = f'https://{subdomain}.vexory.xyz/'
        project = Project(user_id=user.id, name=payload.name.strip(), slug=slug, subdomain=subdomain, type=payload.type, template_key=payload.template_key, repo_url=repo_url, build_command=payload.build_command or 'auto', output_dir=payload.output_dir or 'auto', status='draft', live_url=live_url)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        _seed_project_files(project)
        if project.type == 'static_site':
            published = await asyncio.to_thread(_publish_static_workspace_sync, project)
            project.status = 'live' if published else 'draft'
            project.live_url = live_url
            if published:
                project.last_deployed_at = datetime.now(timezone.utc)
                session.add(Deployment(project_id=project.id, status='success', log='Initial static starter published automatically.', live_url=live_url, repo_url='starter', build_command='static-files', output_dir='.'))
            await session.commit()
            await session.refresh(project)
        return project_out(project)



def _safe_extract_zip(zip_path: Path, target: Path) -> None:
    tmp_target = target.with_name(target.name + '.uploading')
    if tmp_target.exists():
        shutil.rmtree(tmp_target)
    tmp_target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.infolist()
        if len(members) > 1500:
            raise HTTPException(status_code=413, detail='ZIP has too many files. Limit: 1500 files.')
        total = sum(m.file_size for m in members)
        if total > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail='Unpacked site is too large. Limit: 50 MB.')
        for member in members:
            name = member.filename.replace('\\', '/')
            if not name or name.startswith('/') or '..' in Path(name).parts:
                raise HTTPException(status_code=422, detail='ZIP contains unsafe paths.')
            if name.endswith('/'):
                continue
            dest = tmp_target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, 'wb') as dst:
                shutil.copyfileobj(src, dst)
    if not (tmp_target / 'index.html').exists():
        # Common GitHub zip shape: one root folder containing the site.
        children = [x for x in tmp_target.iterdir()]
        if len(children) == 1 and children[0].is_dir() and (children[0] / 'index.html').exists():
            inner = children[0]
            flattened = target.with_name(target.name + '.flat')
            if flattened.exists():
                shutil.rmtree(flattened)
            shutil.copytree(inner, flattened)
            shutil.rmtree(tmp_target)
            tmp_target = flattened
        else:
            raise HTTPException(status_code=422, detail='Static upload must contain index.html in root or one top-level folder.')
    if target.exists():
        shutil.rmtree(target)
    tmp_target.rename(target)


@app.post('/api/projects/{project_id}/upload-static')
async def upload_static(project_id: int, file: UploadFile = File(...), user: User = Depends(current_user)) -> dict:
    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=422, detail='Upload a .zip archive with index.html.')
    async with SessionLocal() as session:
        project = await session.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
        if not project:
            raise HTTPException(status_code=404, detail='Project not found.')
        if await session.scalar(select(Deployment.id).where(Deployment.project_id == project.id, Deployment.status.in_(['queued', 'processing'])).limit(1)):
            raise HTTPException(status_code=409, detail='Cannot upload while deployment is running.')
        target = DEPLOY_ROOT / project.slug
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
            size = 0
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 20 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail='ZIP too large. Limit: 20 MB.')
                tmp.write(chunk)
            tmp_path = Path(tmp.name)
        try:
            await asyncio.to_thread(_safe_extract_zip, tmp_path, target)
            if project.subdomain and project.subdomain != project.slug:
                await asyncio.to_thread(_copytree_clean, target, DEPLOY_ROOT / project.subdomain)
        finally:
            tmp_path.unlink(missing_ok=True)
        project.status = 'live'
        project.last_deploy_status = 'success'
        project.last_deploy_log = f'Uploaded ZIP {html.escape(file.filename)} and published static site.'
        project.last_deployed_at = datetime.now(timezone.utc)
        project.live_url = f'https://{project.subdomain}.vexory.xyz/' if project.subdomain else f'https://host.vexory.xyz/p/{project.slug}/'
        deployment = Deployment(project_id=project.id, status='success', repo_url=None, build_command='upload_zip', output_dir='zip', log=project.last_deploy_log, live_url=project.live_url, started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc))
        session.add(deployment)
        await session.commit()
        return {'ok': True, 'live_url': project.live_url, 'deployment_id': deployment.id}


@app.post('/api/projects/{project_id}/deploy', response_model=DeployOut)
async def deploy_project(project_id: int, payload: DeployIn, user: User = Depends(current_user)) -> DeployOut:
    async with SessionLocal() as session:
        project = await session.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
        if not project:
            raise HTTPException(status_code=404, detail='Project not found.')
        running = await session.scalar(select(Deployment.id).where(Deployment.project_id == project.id, Deployment.status.in_(['queued', 'processing'])).limit(1))
        if running:
            raise HTTPException(status_code=409, detail='A deployment is already queued or running for this project.')
        repo_url = _validate_public_repo(payload.repo_url or project.repo_url or '')
        build_command, output_dir = _validate_build_options(payload.build_command or project.build_command or 'auto', payload.output_dir or project.output_dir or 'auto')
        project.repo_url = repo_url
        project.build_command = build_command
        project.output_dir = output_dir
        project.status = 'queued'
        project.last_deploy_status = 'queued'
        project.last_deploy_log = 'Queued. Waiting for VexHost worker…'
        deployment = Deployment(project_id=project.id, status='queued', repo_url=repo_url, build_command=build_command, output_dir=output_dir, log=project.last_deploy_log)
        session.add(deployment)
        await session.commit()
        await session.refresh(deployment)
    return DeployOut(ok=True, deployment_id=deployment.id, status='queued', live_url=project.live_url, log='Queued. Worker will start shortly.')


@app.get('/api/deployments/{deployment_id}', response_model=DeploymentOut)
async def deployment_status(deployment_id: int, user: User = Depends(current_user)) -> DeploymentOut:
    async with SessionLocal() as session:
        row = await session.scalar(select(Deployment).join(Project).where(Deployment.id == deployment_id, Project.user_id == user.id))
        if not row:
            raise HTTPException(status_code=404, detail='Deployment not found.')
        return DeploymentOut(id=row.id, project_id=row.project_id, status=row.status, repo_url=row.repo_url, build_command=row.build_command, output_dir=row.output_dir, log=row.log, live_url=row.live_url)


@app.post('/api/projects/{project_id}/delete')
async def delete_project(project_id: int, user: User = Depends(current_user)) -> dict:
    async with SessionLocal() as session:
        project = await session.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
        if not project:
            raise HTTPException(status_code=404, detail='Project not found.')
        if await session.scalar(select(Deployment.id).where(Deployment.project_id == project.id, Deployment.status.in_(['queued', 'processing'])).limit(1)):
            raise HTTPException(status_code=409, detail='Cannot delete project while deployment is running.')
        slug = project.slug
        subdomain = project.subdomain
        await session.execute(delete(Deployment).where(Deployment.project_id == project.id))
        await session.delete(project)
        await session.commit()
    removed_static = await asyncio.to_thread(delete_static, slug)
    if subdomain and subdomain != slug:
        removed_static = (await asyncio.to_thread(delete_static, subdomain)) or removed_static
    return {'ok': True, 'removed_static': removed_static}


# ── Stage 6: files + Docker runtime MVP ───────────────────────────────
WORKSPACE_ROOT = DEPLOY_ROOT / '.workspaces'
RUNTIME_HOST_DEPLOY_ROOT = os.environ.get('RUNTIME_HOST_DEPLOY_ROOT', '/var/lib/docker/volumes/vexhost_deploy_data/_data')
RUNTIME_NETWORK = os.environ.get('RUNTIME_NETWORK', 'vexhost_default')
RUNTIME_IMAGES = {
    'python_app': 'python:3.11-slim',
    'telegram_bot': 'python:3.11-slim',
    'api': 'python:3.11-slim',
    'node_app': 'node:20-alpine',
    'mini_app': 'node:20-alpine',
}
RUNTIME_COMMANDS = {
    'python_app': "sh -lc 'if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi; python main.py'",
    'telegram_bot': "sh -lc 'if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi; python main.py'",
    'api': "sh -lc 'if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi; python main.py'",
    'node_app': "sh -lc 'if [ -f package.json ]; then npm install; fi; (npm start || node server.js || node index.js)'",
    'mini_app': "sh -lc 'if [ -f package.json ]; then npm install; fi; (npm start || node server.js || node index.js)'",
}
RUNTIME_MEMORY_MB = 384
RUNTIME_CPUS = '0.75'
# Docker keeps crashed containers alive; the watchdog reconciles DB state and
# captures crash reasons. Manual stop removes the container, so it stays down.
# User-facing policy -> Docker restart policy.
RESTART_POLICY_MAP = {'always': 'unless-stopped', 'on-failure': 'on-failure:5', 'manual': 'no'}
WATCHDOG_INTERVAL_SECONDS = 15
# In-process request counter per project, incremented by the runtime proxy.
# Resets when the API restarts — good enough for a live "requests" gauge.
RUNTIME_REQUESTS: dict[int, int] = {}
RUNTIME_BYTES_OUT: dict[int, int] = {}
RUNTIME_ERRORS: dict[int, int] = {}
RUNTIME_RESPONSE_MS: dict[int, float] = {}
RUNTIME_MANAGER_URL = os.environ.get('RUNTIME_MANAGER_URL', 'http://runtime-manager:8010').rstrip('/')


def _workspace(project: Project) -> Path:
    root = WORKSPACE_ROOT / project.slug
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_rel(path: str | None) -> Path:
    raw = (path or '').strip().lstrip('/').replace('\\', '/')
    if not raw or raw == '.':
        return Path('.')
    p = Path(raw)
    if any(part in {'..', ''} or part.startswith('.') for part in p.parts):
        raise HTTPException(status_code=422, detail='Invalid path.')
    return p


def _project_host_workspace(project: Project) -> str:
    return f"{RUNTIME_HOST_DEPLOY_ROOT}/.workspaces/{project.slug}"


def _container_name(project: Project) -> str:
    return f"vexhost_rt_{project.id}_{project.slug}"[:62].replace('-', '_')


def _run_local(cmd: list[str], timeout: int = 60, check: bool = False) -> subprocess.CompletedProcess:
    # Non-runtime helper for git/build/local filesystem operations only.
    # Docker operations are intentionally delegated to vexhost-runtime-manager.
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if check and proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stdout[-1000:] or 'Command failed')
    return proc


def _manager_get(path: str, timeout: int = 30) -> dict:
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f'{RUNTIME_MANAGER_URL}{path}')
        if r.status_code >= 400:
            return {'ok': False, 'error': r.text[:500], 'status_code': r.status_code}
        return r.json()
    except Exception as exc:
        return {'ok': False, 'error': str(exc)[:500]}


def _manager_post(path: str, payload: dict, timeout: int = 60) -> dict:
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f'{RUNTIME_MANAGER_URL}{path}', json=payload)
        if r.status_code >= 400:
            return {'ok': False, 'error': r.text[:500], 'status_code': r.status_code}
        return r.json()
    except Exception as exc:
        return {'ok': False, 'error': str(exc)[:500]}


# ── resource monitoring + auto-restart helpers ────────────────────────
def _dir_size_mb(path: Path, cap_files: int = 60000) -> float:
    total = 0
    seen = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            seen += 1
            if seen > cap_files:
                break
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                continue
    return round(total / (1024 * 1024), 1)


def _parse_docker_time(value: str) -> datetime | None:
    raw = (value or '').strip()
    if not raw or raw.startswith('0001'):
        return None
    raw = raw.replace('Z', '+00:00')
    # Docker emits nanoseconds; Python understands at most microseconds.
    if '.' in raw:
        head, _, tail = raw.partition('.')
        frac = ''
        tz = ''
        for i, ch in enumerate(tail):
            if ch in '+-':
                frac, tz = tail[:i], tail[i:]
                break
        else:
            frac = tail
        raw = f'{head}.{frac[:6]}{tz}'
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _inspect_state(name: str) -> dict | None:
    data = _manager_get(f'/runtime/inspect/{name}', timeout=25)
    if not data.get('exists'):
        return None
    return {
        'status': data.get('status') or 'unknown',
        'running': bool(data.get('running')),
        'started_at': data.get('started_at') or '',
        'finished_at': data.get('finished_at') or '',
        'exit_code': int(data.get('exit_code') or 0),
        'oom_killed': bool(data.get('oom_killed')),
        'restart_count': int(data.get('restart_count') or 0),
        'error': str(data.get('error') or '').strip(),
    }


def _docker_stats(name: str) -> dict | None:
    data = _manager_get(f'/runtime/stats/{name}', timeout=25)
    if not data.get('ok'):
        return None
    return {
        'cpu_percent': data.get('cpu_percent', 0),
        'mem_used_mb': data.get('mem_used_mb', 0),
        'mem_limit_mb': data.get('mem_limit_mb', RUNTIME_MEMORY_MB),
        'mem_percent': data.get('mem_percent', 0),
    }


_ERROR_PATTERNS = re.compile(r'(Error|Exception|Traceback|Cannot find module|ModuleNotFoundError|SyntaxError|panic:|fatal:|ENOENT|ECONNREFUSED|Killed|command not found)', re.IGNORECASE)


def _extract_last_error(logs: str) -> str | None:
    lines = [ln.strip() for ln in (logs or '').splitlines() if ln.strip()]
    for ln in reversed(lines):
        if _ERROR_PATTERNS.search(ln):
            return ln[:240]
    return lines[-1][:240] if lines else None


def _crash_reason_from_state(state: dict) -> str | None:
    if state.get('oom_killed'):
        return f'Out of memory — the app exceeded its {RUNTIME_MEMORY_MB} MB limit and was killed.'
    if state.get('error'):
        return state['error'][:500]
    code = state.get('exit_code', 0)
    if code and code != 0:
        note = ' (segfault / killed)' if code in (137, 139, 143) else ''
        return f'Exited with code {code}{note}. Check logs for the stack trace.'
    return None


def _start_container(project: Project) -> tuple[bool, str]:
    """Ask runtime-manager to create/start a runtime container."""
    payload = {
        'id': project.id,
        'slug': project.slug,
        'type': project.type,
        'restart_policy': project.restart_policy or 'always',
    }
    data = _manager_post('/runtime/start', payload, timeout=220)
    ok = bool(data.get('ok'))
    out = str(data.get('output') or data.get('error') or '')
    return ok, out


async def _set_runtime_state(project_id: int, **fields) -> None:
    async with SessionLocal() as session:
        p = await session.get(Project, project_id)
        if not p:
            return
        for key, value in fields.items():
            setattr(p, key, value)
        await session.commit()


async def _runtime_watchdog() -> None:
    """Reconcile container state, auto-restart crashed containers and record crash reasons.

    Docker's own `--restart unless-stopped` policy revives crashed processes; this
    loop keeps the dashboard status honest and recreates containers that vanished
    entirely (host reboot, manual `docker rm`). Projects that were stopped by the
    user are excluded, so a manual stop stays down.
    """
    while True:
        try:
            await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
            async with SessionLocal() as session:
                projects = (await session.scalars(select(Project).where(Project.status.in_(['running', 'crashed'])))).all()
            for p in projects:
                if p.type not in RUNTIME_IMAGES:
                    continue
                name = _container_name(p)
                manual = (p.restart_policy or 'always') == 'manual'
                state = await asyncio.to_thread(_inspect_state, name)
                if state is None:
                    if manual:
                        await _set_runtime_state(p.id, status='stopped')
                        continue
                    ok, out = await asyncio.to_thread(_start_container, p)
                    await _set_runtime_state(
                        p.id,
                        status='running' if ok else 'crashed',
                        restart_count=(p.restart_count or 0) + 1,
                        last_crash_reason=None if ok else f'Auto-restart failed: {out[-300:]}',
                    )
                    continue
                if state['running']:
                    reason = _crash_reason_from_state(state) if state['restart_count'] > 0 else None
                    await _set_runtime_state(p.id, status='running', restart_count=max(state['restart_count'], p.restart_count or 0), last_crash_reason=reason)
                elif state['status'] in ('exited', 'dead'):
                    reason = _crash_reason_from_state(state) or 'Container stopped unexpectedly.'
                    if manual:
                        await _set_runtime_state(p.id, status='crashed', restart_count=max(state['restart_count'], p.restart_count or 0), last_crash_reason=reason)
                        continue
                    ok = await asyncio.to_thread(lambda: bool(_manager_post('/runtime/start-existing', {'name': name}, timeout=70).get('ok')))
                    await _set_runtime_state(
                        p.id,
                        status='running' if ok else 'crashed',
                        restart_count=max(state['restart_count'], p.restart_count or 0) + (1 if ok else 0),
                        last_crash_reason=reason,
                    )
                else:  # restarting / paused / created — Docker is mid-recovery
                    await _set_runtime_state(p.id, status='crashed', last_crash_reason=_crash_reason_from_state(state) or f"Container is {state['status']}.")
        except asyncio.CancelledError:
            raise
        except Exception:
            log_watchdog_error()


def log_watchdog_error() -> None:
    import logging
    logging.getLogger('vexhost.watchdog').exception('watchdog loop error')


async def _owned_project(project_id: int, user: User) -> Project:
    async with SessionLocal() as session:
        project = await session.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
        if not project:
            raise HTTPException(status_code=404, detail='Project not found.')
        return project


def _seed_project_files(project: Project) -> None:
    root = _workspace(project)
    if any(root.iterdir()):
        return
    if project.type in {'node_app', 'mini_app'}:
        (root / 'package.json').write_text(json.dumps({'scripts': {'start': 'node server.js'}, 'dependencies': {'express': '^4.18.3'}}, indent=2), encoding='utf-8')
        (root / 'server.js').write_text("const express=require('express');const app=express();const port=process.env.PORT||8080;app.get('/',(_,res)=>res.send('<h1>VexHost Node app is live</h1>'));app.listen(port,'0.0.0.0',()=>console.log('listening '+port));\n", encoding='utf-8')
    elif project.type in {'python_app', 'api'}:
        (root / 'requirements.txt').write_text('fastapi==0.115.6\nuvicorn[standard]==0.32.1\n', encoding='utf-8')
        (root / 'main.py').write_text("from fastapi import FastAPI\nimport uvicorn, os\napp=FastAPI()\n@app.get('/')\ndef home(): return {'ok': True, 'service': 'VexHost Python app'}\nif __name__=='__main__': uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT','8080')))\n", encoding='utf-8')
    elif project.type == 'telegram_bot':
        (root / 'requirements.txt').write_text('aiogram==3.15.0\n', encoding='utf-8')
        (root / 'main.py').write_text("import asyncio, os\nfrom aiogram import Bot, Dispatcher\nfrom aiogram.types import Message\nTOKEN=os.getenv('BOT_TOKEN','')\ndp=Dispatcher()\n@dp.message()\nasync def echo(m: Message): await m.answer('VexHost bot is running')\nasync def main():\n    if not TOKEN: print('Set BOT_TOKEN env var in future env manager. Sleeping.'); await asyncio.sleep(3600)\n    else: await dp.start_polling(Bot(TOKEN))\nasyncio.run(main())\n", encoding='utf-8')
    else:
        (root / 'index.html').write_text('<!doctype html><html><body><h1>VexHost static site</h1><p>Edit files in the dashboard.</p></body></html>\n', encoding='utf-8')



def _publish_static_workspace_sync(project: Project) -> bool:
    """Publish a static project's workspace to the public subdomain directory.

    Returns True when an index.html exists and was published. Returns False when
    the static project is still a draft (no index.html), and removes stale public
    files so users never see an old version accidentally.
    """
    if project.type != 'static_site':
        return False
    root = _workspace(project)
    target_name = project.subdomain or project.slug
    if not (root / 'index.html').exists():
        delete_static(target_name)
        if project.subdomain and project.subdomain != project.slug:
            delete_static(project.slug)
        return False
    _copytree_clean(root, DEPLOY_ROOT / target_name)
    if project.subdomain and project.subdomain != project.slug:
        # Keep slug route working too, useful for old links/debugging.
        _copytree_clean(root, DEPLOY_ROOT / project.slug)
    return True


async def _sync_static_project(project: Project, reason: str = 'Auto-published from file manager.') -> dict:
    if project.type != 'static_site':
        return {'ok': True, 'published': False, 'skip': True}
    published = await asyncio.to_thread(_publish_static_workspace_sync, project)
    live_url = f'https://{project.subdomain or project.slug}.vexory.xyz/'
    async with SessionLocal() as session:
        p = await session.get(Project, project.id)
        if p:
            p.live_url = live_url
            if published:
                p.status = 'live'
                p.last_deployed_at = datetime.now(timezone.utc)
                session.add(Deployment(project_id=p.id, status='success', log=reason, live_url=live_url, repo_url='file-manager', build_command='static-files', output_dir='.'))
            else:
                p.status = 'draft'
            await session.commit()
    return {'ok': True, 'published': published, 'live_url': live_url}


async def _find_project_by_subdomain(subdomain: str) -> Project | None:
    async with SessionLocal() as session:
        return await session.scalar(select(Project).where(Project.subdomain == subdomain))


@app.get('/api/projects/{project_id}/files')
async def list_project_files(project_id: int, path: str = '', user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    _seed_project_files(project)
    root = _workspace(project)
    base = (root / _safe_rel(path)).resolve()
    if not str(base).startswith(str(root.resolve())):
        raise HTTPException(status_code=422, detail='Invalid path.')
    if not base.exists():
        raise HTTPException(status_code=404, detail='Path not found.')
    items = []
    for item in sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if item.name.startswith('.'):
            continue
        items.append({'name': item.name, 'path': str(item.relative_to(root)), 'type': 'dir' if item.is_dir() else 'file', 'size': item.stat().st_size if item.is_file() else 0})
    return {'items': items, 'cwd': str(base.relative_to(root)) if base != root else ''}


@app.get('/api/projects/{project_id}/file')
async def read_project_file(project_id: int, path: str, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    root = _workspace(project)
    file_path = (root / _safe_rel(path)).resolve()
    if not str(file_path).startswith(str(root.resolve())) or not file_path.is_file():
        raise HTTPException(status_code=404, detail='File not found.')
    if file_path.stat().st_size > 500_000:
        raise HTTPException(status_code=413, detail='File is too large for editor.')
    return {'path': str(file_path.relative_to(root)), 'content': file_path.read_text(encoding='utf-8', errors='replace')}


@app.post('/api/projects/{project_id}/file')
async def write_project_file(project_id: int, payload: dict, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    root = _workspace(project)
    rel = _safe_rel(payload.get('path'))
    file_path = (root / rel).resolve()
    if not str(file_path).startswith(str(root.resolve())):
        raise HTTPException(status_code=422, detail='Invalid path.')
    content = str(payload.get('content') or '')
    if len(content.encode()) > 1_000_000:
        raise HTTPException(status_code=413, detail='File content too large.')
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding='utf-8')
    sync = await _sync_static_project(project, f'Auto-published after saving {rel}.')
    return {'ok': True, 'path': str(rel), **sync}


@app.post('/api/projects/{project_id}/upload-file')
async def upload_project_file(project_id: int, file: UploadFile = File(...), path: str = '', user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    root = _workspace(project)
    filename = re.sub(r'[^a-zA-Z0-9._-]+', '-', file.filename or 'upload.bin')[:120]
    target = (root / _safe_rel(path) / filename).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise HTTPException(status_code=422, detail='Invalid path.')
    data = await file.read()
    if len(data) > 10_000_000:
        raise HTTPException(status_code=413, detail='Single file limit is 10MB.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    sync = await _sync_static_project(project, f'Auto-published after uploading {target.relative_to(root)}.')
    return {'ok': True, 'path': str(target.relative_to(root)), 'size': len(data), **sync}


@app.post('/api/projects/{project_id}/mkdir')
async def mkdir_project(project_id: int, payload: dict, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    root = _workspace(project)
    d = (root / _safe_rel(payload.get('path'))).resolve()
    if not str(d).startswith(str(root.resolve())):
        raise HTTPException(status_code=422, detail='Invalid path.')
    d.mkdir(parents=True, exist_ok=True)
    return {'ok': True}


@app.post('/api/projects/{project_id}/delete-file')
async def delete_project_file(project_id: int, payload: dict, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    root = _workspace(project)
    pth = (root / _safe_rel(payload.get('path'))).resolve()
    if not str(pth).startswith(str(root.resolve())) or pth == root:
        raise HTTPException(status_code=422, detail='Invalid path.')
    if pth.is_dir(): shutil.rmtree(pth)
    elif pth.exists(): pth.unlink()
    sync = await _sync_static_project(project, f'Auto-published after deleting {pth.relative_to(root)}.')
    return {'ok': True, **sync}


@app.post('/api/projects/{project_id}/rename')
async def rename_project_file(project_id: int, payload: dict, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    root = _workspace(project)
    src = (root / _safe_rel(payload.get('from'))).resolve()
    dst = (root / _safe_rel(payload.get('to'))).resolve()
    root_r = str(root.resolve())
    if not str(src).startswith(root_r) or not str(dst).startswith(root_r) or src == root:
        raise HTTPException(status_code=422, detail='Invalid path.')
    if not src.exists():
        raise HTTPException(status_code=404, detail='Source not found.')
    if dst.exists():
        raise HTTPException(status_code=409, detail='A file with that name already exists.')
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    sync = await _sync_static_project(project, f'Auto-published after renaming {src.relative_to(root)} to {dst.relative_to(root)}.')
    return {'ok': True, 'path': str(dst.relative_to(root)), **sync}


def _build_tree(base: Path, root: Path, depth: int = 0, budget: list[int] | None = None) -> list[dict]:
    if budget is None:
        budget = [4000]
    if depth > 12:
        return []
    out = []
    for item in sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if item.name.startswith('.') or item.name in {'node_modules', '__pycache__', '.git'}:
            continue
        budget[0] -= 1
        if budget[0] <= 0:
            break
        node = {'name': item.name, 'path': str(item.relative_to(root)), 'type': 'dir' if item.is_dir() else 'file'}
        if item.is_dir():
            node['children'] = _build_tree(item, root, depth + 1, budget)
        else:
            node['size'] = item.stat().st_size
        out.append(node)
    return out


@app.get('/api/projects/{project_id}/files-tree')
async def files_tree(project_id: int, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    _seed_project_files(project)
    root = _workspace(project)
    return {'tree': await asyncio.to_thread(_build_tree, root, root)}


@app.get('/api/projects/{project_id}/search')
async def search_project(project_id: int, q: str = '', mode: str = 'name', user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    root = _workspace(project)
    needle = (q or '').strip()
    if len(needle) < 2:
        return {'items': []}
    items: list[dict] = []
    lowered = needle.lower()
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in {'node_modules', '__pycache__', '.git'}]
        for fn in filenames:
            if fn.startswith('.'):
                continue
            fp = Path(dirpath) / fn
            rel = str(fp.relative_to(root))
            if mode == 'name':
                if lowered in fn.lower():
                    items.append({'path': rel})
            else:  # content
                scanned += 1
                if scanned > 800 or len(items) >= 100:
                    break
                try:
                    if fp.stat().st_size > 400_000:
                        continue
                    with open(fp, 'r', encoding='utf-8', errors='ignore') as fh:
                        for i, line in enumerate(fh, 1):
                            if lowered in line.lower():
                                items.append({'path': rel, 'line': i, 'text': line.strip()[:200]})
                                if len(items) >= 100:
                                    break
                except OSError:
                    continue
        if len(items) >= 100:
            break
    return {'items': items[:100], 'mode': mode}


@app.post('/api/projects/{project_id}/publish-static-files')
async def publish_static_files(project_id: int, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    root = _workspace(project)
    if not (root / 'index.html').exists():
        raise HTTPException(status_code=422, detail='Static site needs index.html in project root.')
    sync = await _sync_static_project(project, 'Published from file manager.')
    return {'ok': True, 'live_url': sync.get('live_url'), 'published': sync.get('published')}


async def _runtime_start_job(project_id: int, deployment_id: int) -> None:
    async with SessionLocal() as session:
        project = await session.get(Project, project_id)
        dep = await session.get(Deployment, deployment_id)
        if not project or not dep:
            return
        dep.status = 'processing'
        dep.started_at = datetime.now(timezone.utc)
        dep.log = 'Queued. Runtime start job is processing…'
        project.status = 'starting'
        project.last_deploy_status = 'processing'
        project.last_deploy_log = dep.log
        await session.commit()
    try:
        _seed_project_files(project)
        ok, output = await asyncio.to_thread(_start_container, project)
        status = 'success' if ok else 'failed'
        log_text = output[-12000:] or ('Runtime container started.' if ok else 'Docker start failed.')
    except Exception as exc:
        status = 'failed'
        log_text = f'Runtime start failed: {exc}'
    async with SessionLocal() as session:
        project = await session.get(Project, project_id)
        dep = await session.get(Deployment, deployment_id)
        if dep:
            dep.status = status
            dep.finished_at = datetime.now(timezone.utc)
            dep.log = log_text
            if project:
                dep.live_url = f'https://{project.subdomain or project.slug}.vexory.xyz/'
        if project:
            project.status = 'running' if status == 'success' else 'crashed'
            project.last_crash_reason = None if status == 'success' else log_text[-500:]
            project.restart_count = 0 if status == 'success' else project.restart_count
            project.live_url = f'https://{project.subdomain or project.slug}.vexory.xyz/'
            project.last_deploy_status = status
            project.last_deploy_log = log_text
        await session.commit()
    RUNTIME_REQUESTS[project_id] = 0




def _bot_commands_file(project: Project) -> Path:
    return _workspace(project) / '.vexhost_bot_commands.json'


def _read_bot_commands(project: Project) -> list[dict]:
    path = _bot_commands_file(project)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, list):
                return [{'command': str(x.get('command','')).strip().lstrip('/')[:32], 'description': str(x.get('description','')).strip()[:256]} for x in data if isinstance(x, dict) and x.get('command')]
        except (OSError, json.JSONDecodeError):
            pass
    return [
        {'command': 'start', 'description': 'Start bot'},
        {'command': 'help', 'description': 'Help'},
        {'command': 'profile', 'description': 'My profile'},
    ]


def _read_project_bot_token(project: Project) -> str | None:
    env = _workspace(project) / '.env'
    if not env.exists() or env.stat().st_size > 200_000:
        return None
    for line in env.read_text(encoding='utf-8', errors='ignore').splitlines():
        if '=' not in line or line.strip().startswith('#'):
            continue
        key, val = line.split('=', 1)
        if key.strip() in {'BOT_TOKEN', 'TELEGRAM_BOT_TOKEN', 'VEXHOST_BOT_TOKEN'}:
            token = val.strip().strip('"\'')
            return token if re.match(r'^\d{6,}:[A-Za-z0-9_-]{20,}$', token) else None
    return None


async def _telegram_api(token: str, method: str, payload: dict | None = None) -> dict:
    url = f'https://api.telegram.org/bot{token}/{method}'
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.post(url, json=payload or {}) if payload is not None else await client.get(url)
    data = r.json() if r.headers.get('content-type','').startswith('application/json') else {'ok': False, 'description': r.text[:200]}
    if not data.get('ok'):
        raise HTTPException(status_code=422, detail=data.get('description') or 'Telegram Bot API error')
    return data.get('result') or {}


def _bot_log_analytics(logs: str) -> dict:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    lower = logs.lower()
    commands: dict[str, int] = {}
    user_ids = set(re.findall(r'(?:user|from|chat)[^0-9]{0,12}(\d{5,})', logs, re.I))
    for cmd in re.findall(r'/(start|help|profile|[a-zA-Z0-9_]{2,32})\b', logs):
        commands['/' + cmd.lower()] = commands.get('/' + cmd.lower(), 0) + 1
    messages_today = sum(1 for line in logs.splitlines() if today in line and ('message' in line.lower() or 'update' in line.lower()))
    errors = len(re.findall(r'\b(error|exception|traceback|failed)\b', lower))
    return {
        'total_users': len(user_ids),
        'new_users_today': 0,
        'messages_today': messages_today,
        'active_chats': len(user_ids),
        'top_commands': sorted(commands.items(), key=lambda x: x[1], reverse=True)[:8],
        'errors': errors,
    }


@app.get('/api/projects/{project_id}/bot/status')
async def bot_status(project_id: int, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    if project.type != 'telegram_bot':
        raise HTTPException(status_code=422, detail='Telegram bot panel is available only for Telegram Bot projects.')
    token = _read_project_bot_token(project)
    name = _container_name(project)
    state = await asyncio.to_thread(_inspect_state, name)
    logs = await asyncio.to_thread(lambda: (_manager_get(f'/runtime/logs/{name}?lines=500', timeout=15).get('logs') or '') if state else '')
    analytics = _bot_log_analytics(logs or '')
    bot_info = {'username': None, 'id': None}
    webhook = {'configured': False, 'url': None, 'pending_update_count': 0, 'last_error_date': None, 'last_error_message': None}
    if token:
        try:
            me = await _telegram_api(token, 'getMe')
            bot_info = {'username': me.get('username'), 'id': me.get('id')}
            wh = await _telegram_api(token, 'getWebhookInfo')
            webhook = {'configured': bool(wh.get('url')), 'url': wh.get('url') or None, 'pending_update_count': wh.get('pending_update_count', 0), 'last_error_date': wh.get('last_error_date'), 'last_error_message': wh.get('last_error_message')}
        except HTTPException as exc:
            webhook['last_error_message'] = str(exc.detail)
    return {
        'token_status': 'connected' if token and bot_info.get('username') else ('configured' if token else 'missing'),
        'webhook_status': 'enabled' if webhook.get('configured') else 'polling_or_not_set',
        'bot_username': bot_info.get('username'),
        'last_update': state.get('started_at') if state and state.get('running') else None,
        'users_count': analytics['total_users'],
        'messages_today': analytics['messages_today'],
        'errors': analytics['errors'],
        'webhook': webhook,
        'analytics': analytics,
        'commands': _read_bot_commands(project),
    }


@app.get('/api/projects/{project_id}/bot/commands')
async def bot_commands(project_id: int, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    if project.type != 'telegram_bot':
        raise HTTPException(status_code=422, detail='Telegram bot commands are available only for Telegram Bot projects.')
    return {'commands': _read_bot_commands(project)}


@app.post('/api/projects/{project_id}/bot/commands')
async def save_bot_commands(project_id: int, payload: dict, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    if project.type != 'telegram_bot':
        raise HTTPException(status_code=422, detail='Telegram bot commands are available only for Telegram Bot projects.')
    raw = payload.get('commands') or []
    if not isinstance(raw, list) or len(raw) > 50:
        raise HTTPException(status_code=422, detail='Commands must be a list with max 50 items.')
    commands = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        command = str(item.get('command','')).strip().lstrip('/').lower()
        desc = str(item.get('description','')).strip()
        if not re.fullmatch(r'[a-z0-9_]{1,32}', command) or not (1 <= len(desc) <= 256):
            raise HTTPException(status_code=422, detail='Each command must be /lowercase_name and description 1-256 chars.')
        commands.append({'command': command, 'description': desc})
    _bot_commands_file(project).write_text(json.dumps(commands, ensure_ascii=False, indent=2), encoding='utf-8')
    token = _read_project_bot_token(project)
    applied = False
    if token:
        await _telegram_api(token, 'setMyCommands', {'commands': commands})
        applied = True
    return {'ok': True, 'commands': commands, 'applied_to_telegram': applied}

@app.post('/api/projects/{project_id}/runtime/start')
async def runtime_start(project_id: int, background_tasks: BackgroundTasks, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    if project.type not in RUNTIME_IMAGES:
        raise HTTPException(status_code=422, detail='Runtime containers are available for Node/Python/API/Bot projects.')
    async with SessionLocal() as session:
        p = await session.get(Project, project.id)
        dep = Deployment(project_id=project.id, status='queued', repo_url='runtime', build_command='runtime-start', output_dir='container', log='Runtime start queued.')
        session.add(dep)
        if p:
            p.status = 'queued'
            p.last_deploy_status = 'queued'
            p.last_deploy_log = dep.log
        await session.commit()
        await session.refresh(dep)
        deployment_id = dep.id
    background_tasks.add_task(_runtime_start_job, project.id, deployment_id)
    return {'ok': True, 'queued': True, 'deployment_id': deployment_id, 'status': 'queued', 'container': _container_name(project), 'live_url': f'https://{project.subdomain or project.slug}.vexory.xyz/'}


@app.post('/api/projects/{project_id}/runtime/stop')
async def runtime_stop(project_id: int, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    name = _container_name(project)
    _manager_post('/runtime/stop', {'name': name}, timeout=40)
    async with SessionLocal() as session:
        p = await session.get(Project, project.id)
        if p: p.status = 'stopped'; await session.commit()
    return {'ok': True}


@app.post('/api/projects/{project_id}/runtime/restart')
async def runtime_restart(project_id: int, background_tasks: BackgroundTasks, user: User = Depends(current_user)) -> dict:
    # Restart is queued; runtime-manager removes/recreates the old container inside the job.
    return await runtime_start(project_id, background_tasks, user)


@app.get('/api/projects/{project_id}/runtime/health')
async def runtime_health(project_id: int, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    if project.type not in RUNTIME_IMAGES:
        return {'ok': True, 'skip': True}
    url = f'http://{_container_name(project)}:8080/'
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(url)
        return {'ok': r.status_code < 500, 'status_code': r.status_code}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)[:200]}


@app.post('/api/projects/{project_id}/runtime/policy')
async def runtime_policy(project_id: int, payload: dict, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    policy = str(payload.get('policy') or '').strip()
    if policy not in RESTART_POLICY_MAP:
        raise HTTPException(status_code=422, detail='Policy must be one of: always, on-failure, manual.')
    async with SessionLocal() as session:
        p = await session.get(Project, project.id)
        if p:
            p.restart_policy = policy
            await session.commit()
    # Apply live so the running container picks up the new policy immediately.
    running = await asyncio.to_thread(_inspect_state, _container_name(project))
    if running and running.get('running'):
        await asyncio.to_thread(lambda: _manager_post('/runtime/policy', {'name': _container_name(project), 'policy': policy}, timeout=30))
    return {'ok': True, 'policy': policy}


@app.get('/api/projects/{project_id}/runtime/status')
async def runtime_status(project_id: int, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    name = _container_name(project)
    state = await asyncio.to_thread(_inspect_state, name)
    return {'container': name, 'status': state.get('status') if state else 'not_created'}


@app.get('/api/projects/{project_id}/runtime/metrics')
async def runtime_metrics(project_id: int, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    if project.type not in RUNTIME_IMAGES:
        raise HTTPException(status_code=422, detail='Metrics are available for Node/Python/API/Bot projects.')
    name = _container_name(project)
    state = await asyncio.to_thread(_inspect_state, name)
    disk_mb = await asyncio.to_thread(_dir_size_mb, _workspace(project))
    requests = RUNTIME_REQUESTS.get(project.id, 0)

    if state is None:
        return {'status': 'not_created', 'running': False, 'disk_mb': disk_mb, 'requests': requests,
                'restart_count': project.restart_count or 0, 'crash': None, 'errors': RUNTIME_ERRORS.get(project.id, 0),
                'bandwidth_mb': round(RUNTIME_BYTES_OUT.get(project.id, 0) / (1024 * 1024), 2), 'response_time_ms': round(RUNTIME_RESPONSE_MS.get(project.id, 0), 0),
                'cpu_percent': 0, 'mem_used_mb': 0, 'mem_limit_mb': RUNTIME_MEMORY_MB, 'mem_percent': 0,
                'uptime_seconds': 0, 'started_at': None}

    running = state['running']
    stats = await asyncio.to_thread(_docker_stats, name) if running else None
    started = _parse_docker_time(state['started_at']) if running else None
    uptime = int((datetime.now(timezone.utc) - started).total_seconds()) if started else 0
    crash = None
    if not running or state['restart_count'] > 0:
        reason = _crash_reason_from_state(state)
        if reason:
            full = await asyncio.to_thread(lambda: _manager_get(f'/runtime/logs/{name}?lines=40', timeout=20).get('logs') or '')
            crash = {
                'reason': reason,
                'exit_code': state['exit_code'],
                'oom_killed': state['oom_killed'],
                'last_error': _extract_last_error(full),
                'log_tail': full[-900:].strip(),
            }

    return {
        'status': state['status'],
        'running': running,
        'cpu_percent': (stats or {}).get('cpu_percent', 0),
        'mem_used_mb': (stats or {}).get('mem_used_mb', 0),
        'mem_limit_mb': (stats or {}).get('mem_limit_mb', RUNTIME_MEMORY_MB),
        'mem_percent': (stats or {}).get('mem_percent', 0),
        'disk_mb': disk_mb,
        'uptime_seconds': uptime,
        'started_at': state['started_at'] if running else None,
        'restart_count': max(state['restart_count'], project.restart_count or 0),
        'requests': requests,
        'errors': RUNTIME_ERRORS.get(project.id, 0),
        'bandwidth_mb': round(RUNTIME_BYTES_OUT.get(project.id, 0) / (1024 * 1024), 2),
        'response_time_ms': round(RUNTIME_RESPONSE_MS.get(project.id, 0), 0),
        'crash': crash,
    }


@app.get('/api/projects/{project_id}/runtime/logs')
async def runtime_logs(project_id: int, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    data = await asyncio.to_thread(lambda: _manager_get(f'/runtime/logs/{_container_name(project)}?lines=160', timeout=35))
    return {'logs': str(data.get('logs') or data.get('error') or '')[-12000:]}


@app.post('/api/projects/{project_id}/runtime/exec')
async def runtime_exec(project_id: int, payload: dict, user: User = Depends(current_user)) -> dict:
    project = await _owned_project(project_id, user)
    command = str(payload.get('command') or '').strip()
    if not command or len(command) > 500:
        raise HTTPException(status_code=422, detail='Command is required.')
    data = await asyncio.to_thread(lambda: _manager_post('/runtime/exec', {'name': _container_name(project), 'command': command}, timeout=35))
    return {'exit_code': int(data.get('exit_code') or (0 if data.get('ok') else 1)), 'output': str(data.get('output') or data.get('error') or '')[-8000:]}


@app.api_route('/api/runtime-proxy{path:path}', methods=['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'])
async def runtime_proxy(path: str, request: Request) -> Response:
    host = (request.headers.get('host') or '').split(':')[0].lower()
    sub = host.removesuffix('.vexory.xyz') if host.endswith('.vexory.xyz') else ''
    if not sub or sub in {'host','www','vexory'}:
        return Response('Not found', status_code=404)
    project = await _find_project_by_subdomain(sub)
    if not project or project.type not in RUNTIME_IMAGES:
        return Response('Site not found', status_code=404)
    RUNTIME_REQUESTS[project.id] = RUNTIME_REQUESTS.get(project.id, 0) + 1
    started_proxy = time()
    url = f"http://{_container_name(project)}:8080{path or '/'}"
    if request.url.query:
        url += '?' + request.url.query
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            body = await request.body()
            upstream = await client.request(request.method, url, content=body, headers={k:v for k,v in request.headers.items() if k.lower() not in {'host','content-length'}})
        elapsed_ms = (time() - started_proxy) * 1000
        prev = RUNTIME_RESPONSE_MS.get(project.id, 0)
        RUNTIME_RESPONSE_MS[project.id] = elapsed_ms if not prev else (prev * 0.75 + elapsed_ms * 0.25)
        RUNTIME_BYTES_OUT[project.id] = RUNTIME_BYTES_OUT.get(project.id, 0) + len(upstream.content or b'')
        if upstream.status_code >= 500:
            RUNTIME_ERRORS[project.id] = RUNTIME_ERRORS.get(project.id, 0) + 1
        return Response(content=upstream.content, status_code=upstream.status_code, headers={'content-type': upstream.headers.get('content-type','text/plain')})
    except Exception as exc:
        RUNTIME_ERRORS[project.id] = RUNTIME_ERRORS.get(project.id, 0) + 1
        return Response(f'Runtime is not ready: {exc}', status_code=502)



# ── admin console helpers ──────────────────────────────────────────────
SUSPICIOUS_TEXT = re.compile(r'(xmrig|monero|stratum\+tcp|cpuminer|masscan|nmap|hydra|proxychain|mirai|ddos|spam|smtp|mailgun|sendgrid)', re.IGNORECASE)
SUSPICIOUS_PACKAGES = re.compile(r'(puppeteer|playwright|selenium|masscan|scapy|pymetasploit|cryptonight|monero|xmrig|nodemailer)', re.IGNORECASE)


def _confirm(payload: dict) -> None:
    if payload.get('confirm') is not True:
        raise HTTPException(status_code=400, detail='Dangerous admin action requires confirm=true.')


def _safe_rm(path: Path) -> bool:
    try:
        root = DEPLOY_ROOT.resolve()
        target = path.resolve()
        if target == root or not str(target).startswith(str(root)):
            return False
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            return True
    except OSError:
        return False
    return False


def _admin_runtime_snapshot(project: Project) -> dict:
    disk_mb = _dir_size_mb(_workspace(project))
    state = None
    stats = None
    log_tail = ''
    if project.type in RUNTIME_IMAGES:
        name = _container_name(project)
        state = _inspect_state(name)
        if state and state.get('running'):
            stats = _docker_stats(name)
        log_tail = str(_manager_get(f'/runtime/logs/{name}?lines=80', timeout=18).get('logs') or '')[-5000:]
    return {
        'container': _container_name(project) if project.type in RUNTIME_IMAGES else None,
        'docker_status': state['status'] if state else ('static' if project.type == 'static_site' else 'not_created'),
        'running': bool(state and state.get('running')) or project.status == 'live',
        'cpu_percent': (stats or {}).get('cpu_percent', 0),
        'mem_used_mb': (stats or {}).get('mem_used_mb', 0),
        'disk_mb': disk_mb,
        'restart_count': max((state or {}).get('restart_count', 0), project.restart_count or 0),
        'errors': RUNTIME_ERRORS.get(project.id, 0),
        'log_bytes': len(log_tail.encode()),
        'log_tail': log_tail,
    }


def _admin_abuse_flags(project: Project, snap: dict) -> list[dict]:
    flags: list[dict] = []
    if snap['restart_count'] >= 5 or (project.restart_count or 0) >= 5:
        flags.append({'level': 'high', 'kind': 'too_many_restarts', 'label': 'Too many restarts'})
    if snap['cpu_percent'] >= 80:
        flags.append({'level': 'high', 'kind': 'high_cpu', 'label': f'High CPU: {snap["cpu_percent"]}%'})
    if snap['disk_mb'] >= 900:
        flags.append({'level': 'medium', 'kind': 'disk_usage', 'label': f'High disk usage: {snap["disk_mb"]} MB'})
    if snap['log_bytes'] >= 4500:
        flags.append({'level': 'medium', 'kind': 'huge_logs', 'label': 'Huge/repetitive logs'})
    if snap['errors'] >= 10 or project.status in {'crashed', 'deploy_failed', 'failed'}:
        flags.append({'level': 'medium', 'kind': 'errors', 'label': 'Runtime/build errors'})
    if SUSPICIOUS_TEXT.search(snap.get('log_tail') or ''):
        flags.append({'level': 'critical', 'kind': 'suspicious_logs', 'label': 'Crypto/spam/scanning keywords in logs'})
    try:
        root = _workspace(project)
        for rel in ['package.json', 'requirements.txt', 'pyproject.toml', 'main.py', 'server.js', 'index.js']:
            fp = root / rel
            if fp.exists() and fp.stat().st_size < 250_000:
                txt = fp.read_text(encoding='utf-8', errors='ignore')
                if (rel in {'package.json', 'requirements.txt', 'pyproject.toml'} and SUSPICIOUS_PACKAGES.search(txt)) or SUSPICIOUS_TEXT.search(txt):
                    flags.append({'level': 'critical', 'kind': 'suspicious_packages', 'label': f'Suspicious keywords/packages in {rel}'})
                    break
    except OSError:
        pass
    return flags


@app.get('/api/admin/summary')
async def admin_summary(admin: User = Depends(require_admin)) -> dict:
    async with SessionLocal() as session:
        users_count = await session.scalar(select(func.count(User.id))) or 0
        projects_count = await session.scalar(select(func.count(Project.id))) or 0
        deployments_count = await session.scalar(select(func.count(Deployment.id))) or 0
        users = (await session.scalars(select(User).order_by(User.id.desc()).limit(100))).all()
        projects = (await session.scalars(select(Project).order_by(Project.id.desc()).limit(200))).all()
        queue_rows = (await session.scalars(select(Deployment).where(Deployment.status.in_(['queued','processing','failed'])).order_by(Deployment.id.desc()).limit(50))).all()

    rows = []
    total_cpu = 0.0
    total_ram = 0.0
    total_disk = 0.0
    all_flags = []
    running = 0
    for p in projects:
        snap = _admin_runtime_snapshot(p)
        flags = _admin_abuse_flags(p, snap)
        running += 1 if snap['running'] else 0
        total_cpu += float(snap['cpu_percent'] or 0)
        total_ram += float(snap['mem_used_mb'] or 0)
        total_disk += float(snap['disk_mb'] or 0)
        for f in flags:
            all_flags.append({**f, 'project_id': p.id, 'project_name': p.name, 'user_id': p.user_id})
        rows.append({
            **project_out(p).model_dump(),
            'user_id': p.user_id,
            'runtime': {k:v for k,v in snap.items() if k != 'log_tail'},
            'abuse_flags': flags,
        })

    return {
        'users': users_count,
        'projects': projects_count,
        'deployments': deployments_count,
        'running_containers': running,
        'cpu_percent': round(total_cpu, 1),
        'ram_mb': round(total_ram, 1),
        'disk_mb': round(total_disk, 1),
        'errors': sum(RUNTIME_ERRORS.values()),
        'payments': {'count': 0, 'revenue': 0, 'status': 'not_configured'},
        'abuse_flags': all_flags[:100],
        'queue': {
            'queued': sum(1 for d in queue_rows if d.status == 'queued'),
            'processing': sum(1 for d in queue_rows if d.status == 'processing'),
            'failed': sum(1 for d in queue_rows if d.status == 'failed'),
            'items': [{'id': d.id, 'project_id': d.project_id, 'status': d.status, 'created_at': d.created_at.isoformat() if d.created_at else None, 'started_at': d.started_at.isoformat() if d.started_at else None} for d in queue_rows[:30]],
        },
        'recent_projects': rows[:80],
        'recent_users': [{
            'id': u.id, 'telegram_id': u.telegram_id, 'username': u.username, 'login_username': u.login_username,
            'plan': u.plan, 'is_admin': u.is_admin, 'is_suspended': bool(getattr(u, 'is_suspended', False)),
            'created_at': u.created_at.isoformat() if u.created_at else None,
        } for u in users],
    }


@app.post('/api/admin/action')
async def admin_action(payload: dict, admin: User = Depends(require_admin)) -> dict:
    _confirm(payload)
    action = str(payload.get('action') or '').strip()
    project_id = payload.get('project_id')
    user_id = payload.get('user_id')

    async with SessionLocal() as session:
        project = await session.get(Project, int(project_id)) if project_id else None
        target_user = await session.get(User, int(user_id)) if user_id else None

        if action in {'stop_project', 'delete_runtime', 'delete_files', 'delete_project'} and not project:
            raise HTTPException(status_code=404, detail='Project not found.')
        if action in {'suspend_user', 'reset_password', 'give_pro'} and not target_user:
            raise HTTPException(status_code=404, detail='User not found.')

        if action == 'stop_project':
            _manager_post('/runtime/stop', {'name': _container_name(project)}, timeout=40)
            project.status = 'stopped'
            await session.commit()
            return {'ok': True, 'action': action}

        if action == 'delete_runtime':
            _manager_post('/runtime/stop', {'name': _container_name(project)}, timeout=40)
            project.status = 'stopped'
            project.last_crash_reason = None
            await session.commit()
            return {'ok': True, 'action': action}

        if action == 'delete_files':
            _manager_post('/runtime/stop', {'name': _container_name(project)}, timeout=40)
            removed = False
            removed = _safe_rm(_workspace(project)) or removed
            removed = _safe_rm(DEPLOY_ROOT / project.slug) or removed
            if project.subdomain and project.subdomain != project.slug:
                removed = _safe_rm(DEPLOY_ROOT / project.subdomain) or removed
            project.status = 'draft'
            project.last_deploy_status = None
            project.last_deploy_log = None
            await session.commit()
            return {'ok': True, 'action': action, 'removed_files': removed}

        if action == 'delete_project':
            slug, sub = project.slug, project.subdomain
            _manager_post('/runtime/stop', {'name': _container_name(project)}, timeout=40)
            await session.execute(delete(Deployment).where(Deployment.project_id == project.id))
            await session.delete(project)
            await session.commit()
            _safe_rm(WORKSPACE_ROOT / slug)
            _safe_rm(DEPLOY_ROOT / slug)
            if sub and sub != slug:
                _safe_rm(DEPLOY_ROOT / sub)
            return {'ok': True, 'action': action}

        if action == 'suspend_user':
            target_user.is_suspended = True
            # Stop all owned containers immediately.
            owned = (await session.scalars(select(Project).where(Project.user_id == target_user.id))).all()
            for p in owned:
                _manager_post('/runtime/stop', {'name': _container_name(p)}, timeout=30)
                if p.type in RUNTIME_IMAGES:
                    p.status = 'stopped'
            await session.commit()
            return {'ok': True, 'action': action, 'stopped_projects': len(owned)}

        if action == 'reset_password':
            new_password = secrets.token_urlsafe(10)
            target_user.password_hash = _password_hash(new_password)
            await session.commit()
            return {'ok': True, 'action': action, 'login_username': target_user.login_username, 'new_password': new_password}

        if action == 'give_pro':
            target_user.plan = 'pro'
            target_user.is_suspended = False
            await session.commit()
            return {'ok': True, 'action': action, 'plan': 'pro'}

    raise HTTPException(status_code=422, detail='Unknown admin action.')


@app.post('/api/admin/projects/{project_id}/delete')
async def admin_delete_project(project_id: int, payload: dict | None = None, admin: User = Depends(require_admin)) -> dict:
    payload = payload or {}
    payload.update({'action': 'delete_project', 'project_id': project_id, 'confirm': payload.get('confirm') is True})
    return await admin_action(payload, admin)
