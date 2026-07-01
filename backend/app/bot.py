from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from sqlalchemy import delete, func, select

from .config import settings
from .db import SessionLocal, init_db
from .models import Deployment, Project, User

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('vexhost.bot')

DEPLOY_ROOT = Path(os.environ.get('DEPLOY_ROOT', '/data/deployments'))
WORKSPACE_ROOT = DEPLOY_ROOT / '.workspaces'
RUNTIME_HOST_DEPLOY_ROOT = os.environ.get('RUNTIME_HOST_DEPLOY_ROOT', '/var/lib/docker/volumes/vexhost_deploy_data/_data')
RUNTIME_NETWORK = os.environ.get('RUNTIME_NETWORK', 'vexhost_default')
RUNTIME_MEMORY_MB = 384
RUNTIME_CPUS = '0.75'
RESTART_POLICY_MAP = {'always': 'unless-stopped', 'on-failure': 'on-failure:5', 'manual': 'no'}
RUNTIME_MANAGER_URL = os.environ.get('RUNTIME_MANAGER_URL', 'http://runtime-manager:8010').rstrip('/')

TEMPLATES = [
    {'key': 'react-landing', 'name': 'React Landing', 'type': 'static_site'},
    {'key': 'telegram-bot-starter', 'name': 'Telegram Bot Starter', 'type': 'telegram_bot'},
    {'key': 'fastapi-api', 'name': 'FastAPI API', 'type': 'api'},
    {'key': 'mini-app-starter', 'name': 'Mini App Starter', 'type': 'mini_app'},
    {'key': 'ai-support-bot', 'name': 'AI Support Bot', 'type': 'telegram_bot'},
]
TYPE_LABELS = {
    'static_site': '🌐 Static Site',
    'telegram_bot': '🤖 Telegram Bot',
    'api': '⚙️ Python API',
    'python_app': '🐍 Python App',
    'node_app': '🟩 Node.js App',
    'mini_app': '📱 Mini App',
}
RUNTIME_IMAGES = {
    'python_app': 'python:3.11-slim',
    'telegram_bot': 'python:3.11-slim',
    'api': 'python:3.11-slim',
    'node_app': 'node:20-alpine',
    'mini_app': 'node:20-alpine',
}
RUNTIME_COMMANDS = {
    'python_app': "if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi; python main.py",
    'telegram_bot': "if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi; python main.py",
    'api': "if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi; python main.py",
    'node_app': "if [ -f package.json ]; then npm install; fi; (npm start || node server.js || node index.js)",
    'mini_app': "if [ -f package.json ]; then npm install; fi; (npm start || node server.js || node index.js)",
}
DEFAULT_TEMPLATE_BY_TYPE = {
    'static_site': 'react-landing',
    'telegram_bot': 'telegram-bot-starter',
    'api': 'fastapi-api',
    'python_app': 'fastapi-api',
    'node_app': 'mini-app-starter',
    'mini_app': 'mini-app-starter',
}


class NewProject(StatesGroup):
    choosing_type = State()
    name = State()
    subdomain = State()
    template = State()


class BotSetup(StatesGroup):
    token = State()


def dashboard_url(project_id: int | None = None, view: str = 'dashboard') -> str:
    # Telegram Mini Apps may ignore URL hashes; query params are more reliable.
    raw = (settings.dashboard_url or 'https://host.vexory.xyz/').split('#', 1)[0]
    parts = urlsplit(raw)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params['view'] = view
    if project_id:
        params['project'] = str(project_id)
    else:
        params.pop('project', None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or '/', urlencode(params), ''))


def admin_url() -> str:
    return dashboard_url(view='admin')


def dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🚀 Open VexHost Dashboard', web_app=WebAppInfo(url=dashboard_url()))],
        [InlineKeyboardButton(text='🌐 Browser Dashboard', url=dashboard_url())],
    ])


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🚀 My Projects', callback_data='menu:projects'), InlineKeyboardButton(text='➕ New Project', callback_data='menu:new')],
        [InlineKeyboardButton(text='📁 Files', callback_data='menu:files'), InlineKeyboardButton(text='🟢 Running Apps', callback_data='menu:running')],
        [InlineKeyboardButton(text='📊 Stats', callback_data='menu:stats'), InlineKeyboardButton(text='💳 Billing', callback_data='menu:billing')],
        [InlineKeyboardButton(text='🆘 Support', callback_data='menu:support'), InlineKeyboardButton(text='⚙️ Settings', callback_data='menu:settings')],
        [InlineKeyboardButton(text='🌐 Open Dashboard', web_app=WebAppInfo(url=dashboard_url()))],
    ])


def onboarding_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🌐 Website', callback_data='new:type:static_site')],
        [InlineKeyboardButton(text='🤖 Telegram Bot', callback_data='new:type:telegram_bot')],
        [InlineKeyboardButton(text='⚙️ API', callback_data='new:type:api')],
        [InlineKeyboardButton(text='📱 Mini App', callback_data='new:type:mini_app')],
        [InlineKeyboardButton(text='🚀 My Projects', callback_data='menu:projects'), InlineKeyboardButton(text='🌐 Dashboard', web_app=WebAppInfo(url=dashboard_url()))],
    ])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🛡 Open Web Admin', web_app=WebAppInfo(url=admin_url())), InlineKeyboardButton(text='🌐 Browser Admin', url=admin_url())],
        [InlineKeyboardButton(text='Users', callback_data='admin:users'), InlineKeyboardButton(text='Projects', callback_data='admin:projects')],
        [InlineKeyboardButton(text='Running Apps', callback_data='admin:running'), InlineKeyboardButton(text='Crashes', callback_data='admin:crashes')],
        [InlineKeyboardButton(text='Payments', callback_data='admin:payments'), InlineKeyboardButton(text='Broadcast', callback_data='admin:broadcast')],
        [InlineKeyboardButton(text='🏠 Menu', callback_data='menu:home')],
    ])


def project_actions_keyboard(project: Project) -> InlineKeyboardMarkup:
    live = project.live_url or f'https://{project.subdomain or project.slug}.vexory.xyz/'
    rows = [
        [InlineKeyboardButton(text='▶️ Start', callback_data=f'proj:start:{project.id}'), InlineKeyboardButton(text='⏹️ Stop', callback_data=f'proj:stop:{project.id}'), InlineKeyboardButton(text='🔄 Restart', callback_data=f'proj:restart:{project.id}')],
        [InlineKeyboardButton(text='📜 Logs', callback_data=f'proj:logs:{project.id}'), InlineKeyboardButton(text='📊 Metrics', callback_data=f'proj:metrics:{project.id}')],
    ]
    if project.type == 'telegram_bot':
        rows.append([InlineKeyboardButton(text='🤖 Bot setup', callback_data=f'proj:botsetup:{project.id}'), InlineKeyboardButton(text='🔗 Check webhook', callback_data=f'proj:checkwebhook:{project.id}')])
    if project.type == 'mini_app':
        rows.append([InlineKeyboardButton(text='📱 Mini App setup', callback_data=f'proj:miniapp:{project.id}'), InlineKeyboardButton(text='✅ Check initData', callback_data=f'proj:checkinit:{project.id}')])
    rows.extend([
        [InlineKeyboardButton(text='🌍 Open Site', url=live), InlineKeyboardButton(text='🧑‍💻 Open Editor', web_app=WebAppInfo(url=dashboard_url(project.id)))],
        [InlineKeyboardButton(text='📁 Files', callback_data=f'proj:files:{project.id}'), InlineKeyboardButton(text='🗑 Delete', callback_data=f'proj:delete:{project.id}')],
        [InlineKeyboardButton(text='⬅️ Back to projects', callback_data='menu:projects')],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_list_keyboard(projects: list[Project]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f'{status_emoji(p.status)} {p.name}', callback_data=f'proj:view:{p.id}')] for p in projects[:25]]
    rows.append([InlineKeyboardButton(text='➕ New Project', callback_data='menu:new'), InlineKeyboardButton(text='🏠 Menu', callback_data='menu:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🌐 Static Site', callback_data='new:type:static_site')],
        [InlineKeyboardButton(text='🤖 Telegram Bot', callback_data='new:type:telegram_bot')],
        [InlineKeyboardButton(text='⚙️ Python API', callback_data='new:type:api')],
        [InlineKeyboardButton(text='🟩 Node.js App', callback_data='new:type:node_app')],
        [InlineKeyboardButton(text='📱 Mini App', callback_data='new:type:mini_app')],
        [InlineKeyboardButton(text='❌ Cancel', callback_data='new:cancel')],
    ])


def template_keyboard(project_type: str) -> InlineKeyboardMarkup:
    rows = []
    for t in TEMPLATES:
        if t['type'] == project_type or (project_type == 'python_app' and t['key'] == 'fastapi-api') or (project_type == 'node_app' and t['key'] == 'mini-app-starter'):
            rows.append([InlineKeyboardButton(text=t['name'], callback_data=f'new:tpl:{t["key"]}')])
    rows.append([InlineKeyboardButton(text='Use default', callback_data='new:tpl:default')])
    rows.append([InlineKeyboardButton(text='❌ Cancel', callback_data='new:cancel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _password_hash(password: str) -> str:
    salt = secrets.token_hex(12)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120_000).hex()
    return f'pbkdf2${salt}${digest}'


def _login_username_from_tg(tg) -> str:
    base = (tg.username if tg else None) or f'tg{tg.id}'
    base = re.sub(r'[^a-z0-9_]+', '', base.lower())[:40] or f'tg{tg.id}'
    return f'vex_{base}'


def _make_login_username(message: Message) -> str:
    return _login_username_from_tg(message.from_user)


def _slugify(value: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    return slug[:64] or 'project'


def _validate_subdomain(value: str | None, fallback: str) -> str:
    sub = _slugify(value or fallback)[:50].strip('-') or fallback[:50]
    if len(sub) < 3:
        sub = f'{sub}-app'
    if sub in {'www', 'api', 'app', 'host', 'admin', 'mail', 'ftp', 'client', 'proxy', 'bot'}:
        sub = f'{sub}-app'
    return sub


def _workspace(project: Project) -> Path:
    root = WORKSPACE_ROOT / project.slug
    root.mkdir(parents=True, exist_ok=True)
    return root


def _copytree_clean(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in {'.git', 'node_modules', '__pycache__'}:
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns('.git', 'node_modules', '__pycache__'))
        else:
            shutil.copy2(item, target)


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
        (root / 'main.py').write_text("import asyncio, os\nfrom aiogram import Bot, Dispatcher\nfrom aiogram.types import Message\nTOKEN=os.getenv('BOT_TOKEN','')\ndp=Dispatcher()\n@dp.message()\nasync def echo(m: Message): await m.answer('VexHost bot is running')\nasync def main():\n    if not TOKEN: print('Set BOT_TOKEN env var in dashboard. Sleeping.'); await asyncio.sleep(3600)\n    else: await dp.start_polling(Bot(TOKEN))\nasyncio.run(main())\n", encoding='utf-8')
    else:
        (root / 'index.html').write_text('<!doctype html><html><body><h1>VexHost static site</h1><p>Edit files in the dashboard.</p></body></html>\n', encoding='utf-8')


def _publish_static(project: Project) -> bool:
    root = _workspace(project)
    if not (root / 'index.html').exists():
        return False
    _copytree_clean(root, DEPLOY_ROOT / (project.subdomain or project.slug))
    if project.subdomain and project.subdomain != project.slug:
        _copytree_clean(root, DEPLOY_ROOT / project.slug)
    return True


def _container_name(project: Project) -> str:
    return f'vexhost_rt_{project.id}_{project.slug}'[:62].replace('-', '_')


def _project_host_workspace(project: Project) -> str:
    return f'{RUNTIME_HOST_DEPLOY_ROOT}/.workspaces/{project.slug}'


def _run_local(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)


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


def _docker_state(project: Project) -> str:
    data = _manager_get(f'/runtime/inspect/{_container_name(project)}', timeout=25)
    return data.get('status') if data.get('exists') else 'not_created'


def _start_container(project: Project) -> tuple[bool, str]:
    if project.type not in RUNTIME_IMAGES:
        return False, 'Runtime is available only for Node/Python/API/Bot projects.'
    _seed_project_files(project)
    data = _manager_post('/runtime/start', {
        'id': project.id,
        'slug': project.slug,
        'type': project.type,
        'restart_policy': project.restart_policy or 'always',
    }, timeout=220)
    return bool(data.get('ok')), str(data.get('output') or data.get('error') or '')[-1500:]


def _docker_stop(project: Project) -> None:
    _manager_post('/runtime/stop', {'name': _container_name(project)}, timeout=40)


def _docker_logs(project: Project, lines: int = 60) -> str:
    data = _manager_get(f'/runtime/logs/{_container_name(project)}?lines={max(1, min(lines, 1000))}', timeout=35)
    logs = str(data.get('logs') or data.get('error') or '')[-3500:]
    return logs if logs else 'No logs yet.'


def _docker_stats(project: Project) -> dict:
    data = _manager_get(f'/runtime/stats/{_container_name(project)}', timeout=25)
    if not data.get('ok'):
        return {'cpu': '0%', 'ram': '0 MB'}
    return {'cpu': f"{data.get('cpu_percent', 0)}%", 'ram': f"{data.get('mem_used_mb', 0)} MB"}


def status_emoji(status: str | None) -> str:
    return {'running': '🟢', 'live': '🟢', 'stopped': '⚫', 'draft': '🟡', 'crashed': '🔴', 'failed': '🔴'}.get(status or '', '🟡')


def type_label(project_type: str) -> str:
    return TYPE_LABELS.get(project_type, project_type)


def esc(v: object) -> str:
    return html.escape(str(v or ''))


async def ensure_user_from_tg(tg) -> tuple[User, str | None]:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == int(tg.id)))
        if not user:
            user = User(telegram_id=int(tg.id), username=tg.username, first_name=tg.first_name, last_name=tg.last_name, language_code=tg.language_code)
            session.add(user)
            await session.flush()
        else:
            user.username = tg.username
            user.first_name = tg.first_name
            user.last_name = tg.last_name
            user.language_code = tg.language_code
        new_password = None
        if not user.login_username:
            base = _login_username_from_tg(tg)
            username = base
            i = 2
            while await session.scalar(select(User.id).where(User.login_username == username, User.id != user.id)):
                username = f'{base}{i}'
                i += 1
            user.login_username = username
        if not user.password_hash:
            new_password = secrets.token_urlsafe(9)
            user.password_hash = _password_hash(new_password)
        if settings.telegram_admin_chat_id and str(tg.id) == str(settings.telegram_admin_chat_id):
            user.is_admin = True
        await session.commit()
        await session.refresh(user)
        return user, new_password


async def ensure_user_credentials(message: Message) -> tuple[User, str | None]:
    return await ensure_user_from_tg(message.from_user)


async def user_by_callback(callback: CallbackQuery) -> User:
    return (await ensure_user_from_tg(callback.from_user))[0]


async def get_user_projects(user: User, running_only: bool = False) -> list[Project]:
    async with SessionLocal() as session:
        q = select(Project).where(Project.user_id == user.id).order_by(Project.id.desc())
        if running_only:
            q = q.where(Project.status.in_(['running', 'live']))
        return list((await session.scalars(q)).all())


async def get_owned_project(user: User, project_id: int) -> Project | None:
    async with SessionLocal() as session:
        return await session.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))


def read_project_env(project: Project) -> dict[str, str]:
    env_path = _workspace(project) / '.env'
    data: dict[str, str] = {}
    if not env_path.exists():
        return data
    for line in env_path.read_text(encoding='utf-8', errors='ignore').splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        data[k.strip()] = v.strip()
    return data


def write_project_env(project: Project, values: dict[str, str]) -> None:
    env_path = _workspace(project) / '.env'
    current = read_project_env(project)
    current.update(values)
    env_path.write_text('\n'.join(f'{k}={v}' for k, v in sorted(current.items())) + '\n', encoding='utf-8')
    try:
        env_path.chmod(0o600)
    except OSError:
        pass


async def validate_bot_token(token: str) -> dict:
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(f'https://api.telegram.org/bot{token}/getMe')
    data = r.json()
    if not data.get('ok'):
        raise RuntimeError(data.get('description') or 'Token invalid')
    return data['result']


async def call_bot_api(token: str, method: str, payload: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f'https://api.telegram.org/bot{token}/{method}', json=payload or {})
    data = r.json()
    if not data.get('ok'):
        raise RuntimeError(data.get('description') or f'{method} failed')
    return data


def bot_setup_keyboard(project: Project) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔐 Send/replace token', callback_data=f'proj:botsetup:{project.id}')],
        [InlineKeyboardButton(text='🔗 Set webhook', callback_data=f'proj:setwebhook:{project.id}'), InlineKeyboardButton(text='✅ Check webhook', callback_data=f'proj:checkwebhook:{project.id}')],
        [InlineKeyboardButton(text='🧹 Remove webhook', callback_data=f'proj:removewebhook:{project.id}'), InlineKeyboardButton(text='🤖 Open bot', callback_data=f'proj:openbot:{project.id}')],
        [InlineKeyboardButton(text='▶️ Deploy / Restart', callback_data=f'proj:restart:{project.id}'), InlineKeyboardButton(text='⬅️ Project', callback_data=f'proj:view:{project.id}')],
    ])


def miniapp_setup_keyboard(project: Project) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔘 Set menu button', callback_data=f'proj:setmenubutton:{project.id}'), InlineKeyboardButton(text='📱 Open Mini App', web_app=WebAppInfo(url=project.live_url or dashboard_url(project.id)))],
        [InlineKeyboardButton(text='✅ Check initData', callback_data=f'proj:checkinit:{project.id}'), InlineKeyboardButton(text='🌍 Preview URL', url=project.live_url or f'https://{project.subdomain or project.slug}.vexory.xyz/')],
        [InlineKeyboardButton(text='▶️ Deploy / Restart', callback_data=f'proj:restart:{project.id}'), InlineKeyboardButton(text='⬅️ Project', callback_data=f'proj:view:{project.id}')],
    ])


def _read_cpu_jiffies() -> tuple[int, int]:
    parts = Path('/proc/stat').read_text().splitlines()[0].split()[1:]
    vals = [int(x) for x in parts]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    total = sum(vals)
    return idle, total


def host_admin_metrics() -> dict:
    try:
        idle1, total1 = _read_cpu_jiffies()
        time.sleep(0.12)
        idle2, total2 = _read_cpu_jiffies()
        total_delta = max(total2 - total1, 1)
        cpu_pct = max(0.0, min(100.0, 100.0 * (1.0 - ((idle2 - idle1) / total_delta))))
    except Exception:
        cpu_pct = 0.0
    meminfo = {}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, val = line.split(':', 1)
            meminfo[key] = int(val.strip().split()[0])
        total_kb = meminfo.get('MemTotal', 0)
        avail_kb = meminfo.get('MemAvailable', 0)
        used_kb = max(total_kb - avail_kb, 0)
    except Exception:
        total_kb = used_kb = 0
    try:
        st = os.statvfs('/')
        total_b = st.f_blocks * st.f_frsize
        free_b = st.f_bavail * st.f_frsize
        used_b = max(total_b - free_b, 0)
    except Exception:
        total_b = used_b = 0
    return {
        'cpu': f'{cpu_pct:.0f}%',
        'ram': f'{used_kb/1024/1024:.1f} GB / {total_kb/1024/1024:.1f} GB',
        'disk': f'{used_b/1024/1024/1024:.0f} GB / {total_b/1024/1024/1024:.0f} GB',
    }


async def set_user_dashboard_menu(message: Message) -> None:
    try:
        await message.bot.set_chat_menu_button(
            chat_id=message.chat.id,
            menu_button=MenuButtonWebApp(text='VexHost', web_app=WebAppInfo(url=dashboard_url())),
        )
    except Exception:
        log.exception('failed to set user menu button')


async def cmd_start(message: Message) -> None:
    await set_user_dashboard_menu(message)
    user, new_password = await ensure_user_credentials(message)
    password_line = f'\nBrowser login: <code>{esc(user.login_username)}</code> / <code>{new_password}</code>' if new_password else ''
    text = (
        'Welcome to VexHost 👋\n\n'
        '<b>What do you want to host?</b>\n\n'
        '🌐 Website\n'
        '🤖 Telegram Bot\n'
        '⚙️ API\n'
        '📱 Mini App\n'
        f'{password_line}\n\n'
        'I will guide you step by step to your first live URL.'
    )
    await message.answer(text, reply_markup=onboarding_keyboard())

async def cmd_menu(message: Message) -> None:
    await set_user_dashboard_menu(message)
    await ensure_user_credentials(message)
    await message.answer('🏠 <b>VexHost Menu</b>\n\nWhat do you want to do?', reply_markup=main_menu_keyboard())


async def show_projects(target: Message | CallbackQuery, running_only: bool = False) -> None:
    if isinstance(target, CallbackQuery):
        user = await user_by_callback(target)
    else:
        user = (await ensure_user_credentials(target))[0]
    projects = await get_user_projects(user, running_only=running_only)
    title = '🟢 <b>Running apps</b>' if running_only else '🚀 <b>My Projects</b>'
    if not projects:
        text = f'{title}\n\nNo projects yet.' if not running_only else f'{title}\n\nNo running apps right now.'
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='➕ New Project', callback_data='menu:new')], [InlineKeyboardButton(text='🏠 Menu', callback_data='menu:home')]])
    else:
        text = f'{title}\n\nSelect a project to manage:'
        kb = project_list_keyboard(projects)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb)


async def cmd_projects(message: Message) -> None:
    await show_projects(message)


async def cmd_new_project(message: Message, state: FSMContext) -> None:
    await ensure_user_credentials(message)
    await state.clear()
    await state.set_state(NewProject.choosing_type)
    await message.answer('➕ <b>New Project</b>\n\nChoose project type:', reply_markup=type_keyboard())


async def cmd_templates(message: Message) -> None:
    lines = ['🧩 <b>VexHost templates</b>\n']
    for t in TEMPLATES:
        lines.append(f'• <b>{esc(t["name"])}</b> — <code>{esc(t["type"])}</code>')
    await message.answer('\n'.join(lines), reply_markup=main_menu_keyboard())


async def cmd_reset_password(message: Message) -> None:
    user, _ = await ensure_user_credentials(message)
    new_password = secrets.token_urlsafe(9)
    async with SessionLocal() as session:
        db_user = await session.scalar(select(User).where(User.id == user.id))
        db_user.password_hash = _password_hash(new_password)
        await session.commit()
    await message.answer(f'🔐 <b>New VexHost password</b>\n\nUsername: <code>{esc(user.login_username)}</code>\nPassword: <code>{new_password}</code>', reply_markup=main_menu_keyboard())


async def cmd_admin(message: Message) -> None:
    user, _ = await ensure_user_credentials(message)
    if not user.is_admin:
        await message.answer('Admin access required.')
        return
    async with SessionLocal() as session:
        users = await session.scalar(select(func.count(User.id))) or 0
        projects = await session.scalar(select(func.count(Project.id))) or 0
        running = await session.scalar(select(func.count(Project.id)).where(Project.status == 'running')) or 0
        errors_today = await session.scalar(select(func.count(Project.id)).where(Project.status.in_(['crashed', 'failed']))) or 0
    m = host_admin_metrics()
    text = (
        '🛡 <b>VexHost Admin</b>\n\n'
        f'Users: <b>{users}</b>\n'
        f'Projects: <b>{projects}</b>\n'
        f'Running containers: <b>{running}</b>\n'
        f'CPU: <b>{esc(m["cpu"])}</b>\n'
        f'RAM: <b>{esc(m["ram"])}</b>\n'
        f'Disk: <b>{esc(m["disk"])}</b>\n'
        f'Errors today: <b>{errors_today}</b>\n'
        'Revenue today: <b>0 Stars</b>'
    )
    await message.answer(text, reply_markup=admin_keyboard())

async def on_admin(callback: CallbackQuery) -> None:
    user = await user_by_callback(callback)
    if not user.is_admin:
        await callback.answer('Admin access required', show_alert=True)
        return
    action = callback.data.split(':', 1)[1]
    async with SessionLocal() as session:
        if action == 'users':
            users = (await session.scalars(select(User).order_by(User.id.desc()).limit(10))).all()
            text = '👥 <b>Latest users</b>\n\n' + '\n'.join(f'#{u.id} @{esc(u.username)} plan={esc(u.plan)}' for u in users)
        elif action == 'projects':
            items = (await session.scalars(select(Project).order_by(Project.id.desc()).limit(12))).all()
            text = '🚀 <b>Latest projects</b>\n\n' + '\n'.join(f'#{p.id} {status_emoji(p.status)} {esc(p.name)} — {esc(p.type)} — {esc(p.subdomain)}' for p in items)
        elif action == 'running':
            items = (await session.scalars(select(Project).where(Project.status == 'running').order_by(Project.id.desc()).limit(20))).all()
            text = '🟢 <b>Running Apps</b>\n\n' + ('\n'.join(f'#{p.id} {esc(p.name)} — {esc(p.subdomain)}' for p in items) or 'No running apps.')
        elif action == 'crashes':
            items = (await session.scalars(select(Project).where(Project.status.in_(['crashed', 'failed'])).order_by(Project.id.desc()).limit(20))).all()
            text = '💥 <b>Crashes</b>\n\n' + ('\n'.join(f'#{p.id} {esc(p.name)} — {esc(p.last_crash_reason)}' for p in items) or 'No crashes.')
        elif action == 'payments':
            text = '💳 <b>Payments</b>\n\nRevenue today: <b>0 Stars</b>\nPayment table is not connected yet.'
        else:
            text = '📣 <b>Broadcast</b>\n\nBroadcast composer is not enabled yet. Next step: add confirmation + rate limit before sending.'
    await callback.message.edit_text(text, reply_markup=admin_keyboard())
    await callback.answer()


async def on_menu(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(':', 1)[1]
    if action == 'home':
        await state.clear()
        await callback.message.edit_text('🏠 <b>VexHost Menu</b>\n\nChoose an action:', reply_markup=main_menu_keyboard())
        await callback.answer()
    elif action == 'projects':
        await show_projects(callback)
    elif action == 'running':
        await show_projects(callback, running_only=True)
    elif action == 'new':
        await state.clear()
        await state.set_state(NewProject.choosing_type)
        await callback.message.edit_text('➕ <b>New Project</b>\n\nChoose project type:', reply_markup=type_keyboard())
        await callback.answer()
    elif action == 'files':
        user = await user_by_callback(callback)
        projects = await get_user_projects(user)
        await callback.message.edit_text('📁 <b>Files</b>\n\nChoose a project. I will show files and give you the editor button.', reply_markup=project_list_keyboard(projects) if projects else main_menu_keyboard())
        await callback.answer()
    elif action == 'stats':
        user = await user_by_callback(callback)
        projects = await get_user_projects(user)
        running = sum(1 for p in projects if p.status == 'running')
        live = sum(1 for p in projects if p.status == 'live')
        await callback.message.edit_text(f'📊 <b>Your stats</b>\n\nProjects: <b>{len(projects)}</b>\nRunning servers: <b>{running}</b>\nLive static sites: <b>{live}</b>\nPlan: <b>{esc(user.plan)}</b>', reply_markup=main_menu_keyboard())
        await callback.answer()
    elif action == 'billing':
        await callback.message.edit_text('💳 <b>Billing</b>\n\nCurrent plan: <b>Free</b>\n\nSoon: Telegram Stars upgrades, always-on add-ons, extra projects, custom domains.', reply_markup=main_menu_keyboard())
        await callback.answer()
    elif action == 'support':
        await callback.message.edit_text('🆘 <b>Support</b>\n\nWrite your issue in this chat, or open the dashboard. Soon I will create tickets directly from Telegram.', reply_markup=main_menu_keyboard())
        await callback.answer()
    elif action == 'settings':
        await callback.message.edit_text('⚙️ <b>Settings</b>\n\nUse /reset_password to reset browser login. Env variables and custom domains are coming next.', reply_markup=main_menu_keyboard())
        await callback.answer()


async def on_new_type(callback: CallbackQuery, state: FSMContext) -> None:
    project_type = callback.data.rsplit(':', 1)[1]
    await state.update_data(type=project_type)
    await state.set_state(NewProject.name)
    await callback.message.edit_text(f'{TYPE_LABELS.get(project_type, project_type)}\n\nSend project name:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ Cancel', callback_data='new:cancel')]]))
    await callback.answer()


async def on_new_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text('Cancelled.', reply_markup=main_menu_keyboard())
    await callback.answer()


async def on_new_name(message: Message, state: FSMContext) -> None:
    name = (message.text or '').strip()
    if len(name) < 2 or len(name) > 96:
        await message.answer('Project name must be 2-96 characters. Send another name:')
        return
    await state.update_data(name=name)
    await state.set_state(NewProject.subdomain)
    await message.answer('Subdomain? Example: <code>mybot</code> → <code>mybot.vexory.xyz</code>')


async def on_new_subdomain(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    sub = _validate_subdomain(message.text, _slugify(data.get('name', 'project')))
    await state.update_data(subdomain=sub)
    await state.set_state(NewProject.template)
    await message.answer(f'Subdomain: <code>{esc(sub)}.vexory.xyz</code>\n\nChoose template:', reply_markup=template_keyboard(data['type']))


async def on_new_template(callback: CallbackQuery, state: FSMContext) -> None:
    tpl = callback.data.rsplit(':', 1)[1]
    data = await state.get_data()
    project_type = data['type']
    template_key = DEFAULT_TEMPLATE_BY_TYPE.get(project_type, 'react-landing') if tpl == 'default' else tpl
    user = await user_by_callback(callback)
    try:
        project = await create_project_for_user(user, data['name'], project_type, data['subdomain'], template_key)
    except Exception as exc:
        await callback.message.edit_text(f'❌ Failed to create project:\n<code>{esc(str(exc)[:900])}</code>', reply_markup=main_menu_keyboard())
        await callback.answer()
        await state.clear()
        return
    await state.clear()
    if project.type == 'telegram_bot':
        await callback.message.edit_text(
            f'✅ Project created: <b>{esc(project.name)}</b>\n\n'
            '🤖 <b>BotFather-like setup wizard</b>\n\n'
            'Step 1/5: Create a bot in @BotFather\n'
            'Step 2/5: Send token here\n'
            'Step 3/5: Choose template — done\n'
            'Step 4/5: Deploy\n'
            'Step 5/5: Test /start\n\n'
            'Send your bot token from @BotFather.',
            reply_markup=bot_setup_keyboard(project),
        )
        await state.update_data(project_id=project.id)
        await state.set_state(BotSetup.token)
    elif project.type == 'mini_app':
        await callback.message.edit_text(
            f'✅ Project created: <b>{esc(project.name)}</b>\n\n'
            '📱 <b>Mini App setup wizard</b>\n\n'
            '1. Choose bot\n2. Set Mini App URL\n3. Validate Telegram initData\n4. Open preview\n5. Publish',
            reply_markup=miniapp_setup_keyboard(project),
        )
    else:
        await callback.message.edit_text(project_card_text(project), reply_markup=project_actions_keyboard(project))
    await callback.answer('Project created')


async def create_project_for_user(user: User, name: str, project_type: str, subdomain: str, template_key: str) -> Project:
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count(Project.id)).where(Project.user_id == user.id)) or 0
        limit = 20 if user.plan == 'free' else 100
        if count >= limit:
            raise RuntimeError(f'Project limit reached: {limit}')
        slug_base = _slugify(name)
        slug = slug_base
        i = 2
        while await session.scalar(select(Project.id).where(Project.slug == slug)):
            slug = f'{slug_base}-{i}'
            i += 1
        sub_base = _validate_subdomain(subdomain, slug)
        sub = sub_base
        j = 2
        while await session.scalar(select(Project.id).where(Project.subdomain == sub)):
            sub = f'{sub_base}-{j}'[:50].strip('-')
            j += 1
        live_url = f'https://{sub}.vexory.xyz/'
        project = Project(user_id=user.id, name=name.strip(), slug=slug, subdomain=sub, type=project_type, template_key=template_key, build_command='auto', output_dir='auto', status='draft', live_url=live_url)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        _seed_project_files(project)
        if project.type == 'static_site' and _publish_static(project):
            project.status = 'live'
            project.last_deployed_at = datetime.now(timezone.utc)
            session.add(Deployment(project_id=project.id, status='success', log='Created and published from Telegram bot.', live_url=live_url, repo_url='telegram-bot', build_command='static-files', output_dir='.'))
            await session.commit()
            await session.refresh(project)
        return project


def project_card_text(project: Project, metrics: dict | None = None) -> str:
    live = project.live_url or f'https://{project.subdomain or project.slug}.vexory.xyz/'
    cpu = metrics.get('cpu', '0%') if metrics else '0%'
    ram = metrics.get('ram', '0 MB') if metrics else '0 MB'
    return (
        f'{status_emoji(project.status)} <b>{esc(project.name)}</b>\n\n'
        f'<b>Status:</b> <code>{esc(project.status)}</code>\n'
        f'<b>URL:</b> {esc(live)}\n'
        f'<b>Type:</b> {esc(type_label(project.type))}\n'
        f'<b>RAM:</b> <code>{esc(ram)}</code>\n'
        f'<b>CPU:</b> <code>{esc(cpu)}</code>'
    )


async def on_project(callback: CallbackQuery, state: FSMContext) -> None:
    _, action, sid = callback.data.split(':', 2)
    user = await user_by_callback(callback)
    project = await get_owned_project(user, int(sid))
    if not project:
        await callback.answer('Project not found', show_alert=True)
        return
    if action == 'view':
        metrics = _docker_stats(project) if project.type in RUNTIME_IMAGES and project.status == 'running' else None
        await callback.message.edit_text(project_card_text(project, metrics), reply_markup=project_actions_keyboard(project))
        await callback.answer()
    elif action == 'start':
        if project.type == 'static_site':
            _seed_project_files(project)
            ok = _publish_static(project)
            async with SessionLocal() as session:
                p = await session.get(Project, project.id)
                p.status = 'live' if ok else 'draft'
                p.live_url = f'https://{p.subdomain or p.slug}.vexory.xyz/'
                if ok:
                    p.last_deployed_at = datetime.now(timezone.utc)
                await session.commit()
            project = await get_owned_project(user, project.id)
            await callback.message.edit_text(project_card_text(project), reply_markup=project_actions_keyboard(project))
            await callback.answer('Published')
        elif project.type in RUNTIME_IMAGES:
            await callback.answer('Starting…')
            ok, out = await asyncio.to_thread(_start_container, project)
            async with SessionLocal() as session:
                p = await session.get(Project, project.id)
                p.status = 'running' if ok else 'crashed'
                p.live_url = f'https://{p.subdomain or p.slug}.vexory.xyz/'
                p.last_crash_reason = None if ok else out[-500:]
                await session.commit()
            project = await get_owned_project(user, project.id)
            await callback.message.edit_text((project_card_text(project, _docker_stats(project) if ok else None) + ('' if ok else f'\n\n<code>{esc(out[-900:])}</code>')), reply_markup=project_actions_keyboard(project))
        else:
            await callback.answer('This project type cannot start yet.', show_alert=True)
    elif action == 'stop':
        _docker_stop(project)
        async with SessionLocal() as session:
            p = await session.get(Project, project.id)
            p.status = 'stopped'
            await session.commit()
        project = await get_owned_project(user, project.id)
        await callback.message.edit_text(project_card_text(project), reply_markup=project_actions_keyboard(project))
        await callback.answer('Stopped')
    elif action == 'restart':
        if project.type not in RUNTIME_IMAGES:
            await callback.answer('Only runtime projects can restart.', show_alert=True)
            return
        await callback.answer('Restarting…')
        _docker_stop(project)
        ok, out = await asyncio.to_thread(_start_container, project)
        async with SessionLocal() as session:
            p = await session.get(Project, project.id)
            p.status = 'running' if ok else 'crashed'
            p.restart_count = (p.restart_count or 0) + 1
            p.last_crash_reason = None if ok else out[-500:]
            await session.commit()
        project = await get_owned_project(user, project.id)
        await callback.message.edit_text(project_card_text(project, _docker_stats(project) if ok else None), reply_markup=project_actions_keyboard(project))
    elif action == 'logs':
        if project.type not in RUNTIME_IMAGES:
            text = '📜 <b>Logs</b>\n\nStatic sites do not have runtime logs. Open editor for files.'
        else:
            text = f'📜 <b>Logs: {esc(project.name)}</b>\n\n<pre>{esc(_docker_logs(project, 80))}</pre>'
        await callback.message.edit_text(text, reply_markup=project_actions_keyboard(project))
        await callback.answer()
    elif action == 'metrics':
        state = _docker_state(project) if project.type in RUNTIME_IMAGES else project.status
        metrics = _docker_stats(project) if project.type in RUNTIME_IMAGES else {'cpu': '0%', 'ram': '0 MB'}
        files_mb = dir_size_mb(_workspace(project))
        text = f'📊 <b>Metrics: {esc(project.name)}</b>\n\nStatus: <code>{esc(state)}</code>\nCPU: <code>{esc(metrics["cpu"])}</code>\nRAM: <code>{esc(metrics["ram"])}</code>\nDisk: <code>{files_mb} MB</code>\nURL: {esc(project.live_url)}'
        await callback.message.edit_text(text, reply_markup=project_actions_keyboard(project))
        await callback.answer()
    elif action == 'files':
        root = _workspace(project)
        _seed_project_files(project)
        items = []
        for item in sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:25]:
            if item.name.startswith('.'):
                continue
            icon = '📁' if item.is_dir() else '📄'
            size = '' if item.is_dir() else f' — {item.stat().st_size}b'
            items.append(f'{icon} <code>{esc(item.name)}</code>{size}')
        text = f'📁 <b>Files: {esc(project.name)}</b>\n\n' + ('\n'.join(items) if items else 'No files yet.')
        await callback.message.edit_text(text, reply_markup=project_actions_keyboard(project))
        await callback.answer()
    elif action == 'botsetup':
        await callback.message.edit_text(
            '🤖 <b>Telegram Bot Hosting Assistant</b>\n\n'
            'Step 1/5: Create a bot in @BotFather\n'
            'Step 2/5: Send token here\n'
            'Step 3/5: Choose template — done\n'
            'Step 4/5: Deploy\n'
            'Step 5/5: Test /start\n\n'
            'Send your bot token from @BotFather.',
            reply_markup=bot_setup_keyboard(project),
        )
        await state.update_data(project_id=project.id)
        await state.set_state(BotSetup.token)
        await callback.answer('Send token in chat')
    elif action in {'setwebhook', 'checkwebhook', 'removewebhook', 'openbot'}:
        env = read_project_env(project)
        token = env.get('BOT_TOKEN')
        if not token:
            await callback.message.edit_text('❌ BOT_TOKEN is not saved yet. Press Bot setup and send token from @BotFather.', reply_markup=bot_setup_keyboard(project))
            await callback.answer()
            return
        try:
            info = await validate_bot_token(token)
            if action == 'setwebhook':
                hook_url = (project.live_url or f'https://{project.subdomain or project.slug}.vexory.xyz/').rstrip('/') + '/webhook'
                await call_bot_api(token, 'setWebhook', {'url': hook_url, 'drop_pending_updates': True})
                text = f'✅ Webhook configured\nBot username: @{esc(info.get("username"))}\nWebhook: <code>{esc(hook_url)}</code>'
            elif action == 'checkwebhook':
                data = await call_bot_api(token, 'getWebhookInfo')
                result = data.get('result', {})
                text = f'✅ Webhook info for @{esc(info.get("username"))}\nURL: <code>{esc(result.get("url") or "not set")}</code>\nPending: <b>{esc(result.get("pending_update_count", 0))}</b>\nLast error: <code>{esc(result.get("last_error_message") or "none")}</code>'
            elif action == 'removewebhook':
                await call_bot_api(token, 'deleteWebhook', {'drop_pending_updates': False})
                text = f'✅ Webhook removed for @{esc(info.get("username"))}'
            else:
                text = f'🤖 Bot: @{esc(info.get("username"))}\nOpen: https://t.me/{esc(info.get("username"))}'
            await callback.message.edit_text(text, reply_markup=bot_setup_keyboard(project))
        except Exception as exc:
            await callback.message.edit_text(f'❌ Bot API error:\n<code>{esc(str(exc)[:900])}</code>', reply_markup=bot_setup_keyboard(project))
        await callback.answer()
    elif action == 'miniapp':
        await callback.message.edit_text(
            '📱 <b>Mini App setup wizard</b>\n\n'
            '1. Choose bot\n'
            '2. Set Mini App URL\n'
            '3. Validate Telegram initData\n'
            '4. Open preview\n'
            '5. Publish\n\n'
            f'Mini App URL: <code>{esc(project.live_url)}</code>',
            reply_markup=miniapp_setup_keyboard(project),
        )
        await callback.answer()
    elif action == 'checkinit':
        await callback.message.edit_text('✅ initData validation is built into VexHost dashboard auth. Open the Mini App from Telegram and dashboard will validate initData automatically.', reply_markup=miniapp_setup_keyboard(project))
        await callback.answer()
    elif action == 'setmenubutton':
        env = read_project_env(project)
        token = env.get('BOT_TOKEN')
        if not token:
            await callback.message.edit_text('❌ To set menu button, first save BOT_TOKEN in this project. Use Telegram Bot project setup or add BOT_TOKEN in editor .env.', reply_markup=miniapp_setup_keyboard(project))
            await callback.answer()
            return
        try:
            await call_bot_api(token, 'setChatMenuButton', {'menu_button': {'type': 'web_app', 'text': 'Open App', 'web_app': {'url': project.live_url or f'https://{project.subdomain or project.slug}.vexory.xyz/'}}})
            await callback.message.edit_text('✅ Mini App menu button configured.', reply_markup=miniapp_setup_keyboard(project))
        except Exception as exc:
            await callback.message.edit_text(f'❌ Failed to set menu button:\n<code>{esc(str(exc)[:900])}</code>', reply_markup=miniapp_setup_keyboard(project))
        await callback.answer()
    elif action == 'delete':
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ Yes, delete', callback_data=f'proj:confirm_delete:{project.id}')],
            [InlineKeyboardButton(text='Cancel', callback_data=f'proj:view:{project.id}')],
        ])
        await callback.message.edit_text(f'🗑 Delete <b>{esc(project.name)}</b>?\n\nThis removes DB record, files and runtime container.', reply_markup=kb)
        await callback.answer()
    elif action == 'confirm_delete':
        _docker_stop(project)
        for path in [DEPLOY_ROOT / project.slug, DEPLOY_ROOT / (project.subdomain or project.slug), WORKSPACE_ROOT / project.slug]:
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        async with SessionLocal() as session:
            await session.execute(delete(Deployment).where(Deployment.project_id == project.id))
            p = await session.get(Project, project.id)
            if p:
                await session.delete(p)
            await session.commit()
        await callback.message.edit_text('✅ Project deleted.', reply_markup=main_menu_keyboard())
        await callback.answer('Deleted')


def dir_size_mb(path: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files[:2000]:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return round(total / (1024 * 1024), 1)


async def on_bot_token(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    project_id = int(data.get('project_id') or 0)
    user = (await ensure_user_credentials(message))[0]
    project = await get_owned_project(user, project_id)
    if not project or project.type != 'telegram_bot':
        await state.clear()
        await message.answer('Project not found. Open project → Bot setup again.', reply_markup=main_menu_keyboard())
        return
    token = (message.text or '').strip()
    if not re.match(r'^\d{6,12}:[A-Za-z0-9_-]{30,}$', token):
        await message.answer('This does not look like a BotFather token. Send token like <code>123456:ABC...</code>')
        return
    try:
        info = await validate_bot_token(token)
    except Exception as exc:
        await message.answer(f'❌ Token invalid: <code>{esc(str(exc)[:500])}</code>')
        return
    write_project_env(project, {'BOT_TOKEN': token})
    hook_url = (project.live_url or f'https://{project.subdomain or project.slug}.vexory.xyz/').rstrip('/') + '/webhook'
    webhook_line = ''
    try:
        await call_bot_api(token, 'setWebhook', {'url': hook_url, 'drop_pending_updates': True})
        webhook_line = f'✅ Webhook configured: <code>{esc(hook_url)}</code>\n'
    except Exception as exc:
        webhook_line = f'⚠️ Webhook not configured yet: <code>{esc(str(exc)[:300])}</code>\n'
    await state.clear()
    text = (
        '✅ Token valid\n'
        f'Bot username: @{esc(info.get("username"))}\n\n'
        '✅ Token saved as <code>BOT_TOKEN</code>\n'
        f'{webhook_line}'
        'Next: press <b>Deploy / Restart</b>, then test /start in your bot.'
    )
    await message.answer(text, reply_markup=bot_setup_keyboard(project))


async def fallback(message: Message) -> None:
    await message.answer('🏠 Open menu or use /new_project to create hosting project.', reply_markup=main_menu_keyboard())


async def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN is not set')
    DEPLOY_ROOT.mkdir(parents=True, exist_ok=True)
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    await init_db()
    bot = Bot(settings.telegram_bot_token, default=DefaultBotProperties(parse_mode='HTML'))
    await bot.set_my_commands([
        BotCommand(command='start', description='Open VexHost menu'),
        BotCommand(command='menu', description='Show main menu'),
        BotCommand(command='projects', description='Manage projects'),
        BotCommand(command='new_project', description='Create a new project'),
        BotCommand(command='templates', description='View project templates'),
        BotCommand(command='reset_password', description='Reset browser dashboard password'),
        BotCommand(command='admin', description='Admin summary'),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text='VexHost', web_app=WebAppInfo(url=dashboard_url())))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.register(cmd_start, Command('start'))
    dp.message.register(cmd_menu, Command('menu'))
    dp.message.register(cmd_projects, Command('projects'))
    dp.message.register(cmd_new_project, Command('new_project'))
    dp.message.register(cmd_templates, Command('templates'))
    dp.message.register(cmd_reset_password, Command('reset_password'))
    dp.message.register(cmd_admin, Command('admin'))
    dp.callback_query.register(on_admin, F.data.startswith('admin:'))
    dp.callback_query.register(on_menu, F.data.startswith('menu:'))
    dp.callback_query.register(on_new_type, F.data.startswith('new:type:'))
    dp.callback_query.register(on_new_template, F.data.startswith('new:tpl:'))
    dp.callback_query.register(on_new_cancel, F.data == 'new:cancel')
    dp.callback_query.register(on_project, F.data.startswith('proj:'))
    dp.message.register(on_new_name, NewProject.name)
    dp.message.register(on_new_subdomain, NewProject.subdomain)
    dp.message.register(on_bot_token, BotSetup.token)
    dp.message.register(fallback, F.text)
    log.info('VexHost Telegram hosting bot polling started')
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == '__main__':
    asyncio.run(main())
