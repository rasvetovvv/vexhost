from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

DEPLOY_ROOT = Path(os.environ.get('DEPLOY_ROOT', '/data/deployments'))
ALLOWED_BUILD_COMMANDS = {'auto', '', 'none', 'npm install && npm run build', 'npm ci && npm run build', 'npm run build'}


class DeployValidationError(ValueError):
    pass


def validate_public_repo(url: str) -> str:
    parsed = urlparse((url or '').strip())
    if parsed.scheme != 'https' or parsed.netloc.lower() not in {'github.com', 'www.github.com'}:
        raise DeployValidationError('Stage 4 supports public GitHub HTTPS repositories only.')
    parts = [p for p in parsed.path.split('/') if p]
    if '..' in parsed.path or len(parts) < 2:
        raise DeployValidationError('Invalid GitHub repository URL.')
    return url.strip()


def validate_build_options(build_command: str | None, output_dir: str | None) -> tuple[str, str]:
    cmd = (build_command or 'auto').strip()
    out = (output_dir or 'auto').strip().strip('/') or 'auto'
    if cmd not in ALLOWED_BUILD_COMMANDS:
        raise DeployValidationError('Allowed build commands: auto, none, npm install && npm run build, npm ci && npm run build, npm run build.')
    if out != 'auto':
        parts = Path(out).parts
        if out.startswith('.') or '..' in parts or any(part.startswith('.') for part in parts):
            raise DeployValidationError('Invalid output directory.')
    return cmd, out


def safe_slug(value: str) -> bool:
    return bool(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,95}', value or ''))


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


def deploy_static(repo_url: str, slug: str, build_command: str | None, output_dir: str | None) -> tuple[str, str]:
    if not safe_slug(slug):
        raise DeployValidationError('Invalid project slug.')
    repo_url = validate_public_repo(repo_url)
    cmd, out = validate_build_options(build_command, output_dir)
    DEPLOY_ROOT.mkdir(parents=True, exist_ok=True)
    log: list[str] = [
        'VexHost Stage 4 worker deploy started.',
        f'Repo: {repo_url}',
        f'Build: {cmd}',
        f'Output: {out}',
    ]
    with tempfile.TemporaryDirectory(prefix='vexhost-build-') as tmp:
        work = Path(tmp) / 'repo'
        _run(['git', 'clone', '--depth', '1', repo_url, str(work)], Path(tmp), log, timeout=120)
        package_json = work / 'package.json'
        if cmd == 'auto':
            if package_json.exists():
                lock = work / 'package-lock.json'
                _run(['npm', 'ci' if lock.exists() else 'install'], work, log, timeout=300)
                _run(['npm', 'run', 'build'], work, log, timeout=300)
            else:
                log.append('No package.json found. Publishing repository files as static site.')
        elif cmd in {'', 'none'}:
            log.append('Build skipped by user.')
        elif cmd == 'npm install && npm run build':
            _run(['npm', 'install'], work, log, timeout=300)
            _run(['npm', 'run', 'build'], work, log, timeout=300)
        elif cmd == 'npm ci && npm run build':
            _run(['npm', 'ci'], work, log, timeout=300)
            _run(['npm', 'run', 'build'], work, log, timeout=300)
        elif cmd == 'npm run build':
            _run(['npm', 'run', 'build'], work, log, timeout=300)

        if out == 'auto':
            candidates = ['dist', 'build', 'out', 'public'] if package_json.exists() else ['.']
            output_path = next((work / c for c in candidates if (work / c).exists()), None)
        else:
            output_path = work / out
        if not output_path or not output_path.exists() or not output_path.is_dir():
            raise RuntimeError(f'Output directory not found: {out}')
        if not (output_path / 'index.html').exists():
            log.append('Warning: output directory has no index.html. Nginx directory listing is disabled, so root may return 404/403.')
        target = DEPLOY_ROOT / slug
        _copytree_clean(output_path, target)
        log.append(f'Published to /p/{slug}/')
    return f'https://host.vexory.xyz/p/{slug}/', '\n'.join(log)[-12000:]


def delete_static(slug: str) -> bool:
    if not safe_slug(slug):
        return False
    target = DEPLOY_ROOT / slug
    if target.exists():
        shutil.rmtree(target)
        return True
    return False
