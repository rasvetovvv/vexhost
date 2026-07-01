"""VexHost runtime-manager: narrow Docker API for user runtime containers.

This service is the only VexHost component that mounts /var/run/docker.sock.
The main backend talks to it over the private Docker network and never receives
full Docker root access in production.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="VexHost Runtime Manager", version="1.0.0")

DEPLOY_ROOT = os.environ.get("DEPLOY_ROOT", "/data/deployments")
RUNTIME_HOST_DEPLOY_ROOT = os.environ.get("RUNTIME_HOST_DEPLOY_ROOT", "/var/lib/docker/volumes/vexhost_deploy_data/_data")
RUNTIME_NETWORK = os.environ.get("RUNTIME_NETWORK", "vexhost_default")
RUNTIME_MEMORY_MB = int(os.environ.get("RUNTIME_MEMORY_MB", "384"))
RUNTIME_CPUS = os.environ.get("RUNTIME_CPUS", "0.75")

RUNTIME_IMAGES = {
    "python_app": "python:3.11-slim",
    "telegram_bot": "python:3.11-slim",
    "api": "python:3.11-slim",
    "node_app": "node:20-alpine",
    "mini_app": "node:20-alpine",
}
RUNTIME_COMMANDS = {
    "python_app": "sh -lc 'if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi; python main.py'",
    "telegram_bot": "sh -lc 'if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi; python main.py'",
    "api": "sh -lc 'if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi; python main.py'",
    "node_app": "sh -lc 'if [ -f package.json ]; then npm install; fi; (npm start || node server.js || node index.js)'",
    "mini_app": "sh -lc 'if [ -f package.json ]; then npm install; fi; (npm start || node server.js || node index.js)'",
}
RESTART_POLICY_MAP = {"always": "unless-stopped", "on-failure": "on-failure:5", "manual": "no"}
SAFE_NAME = re.compile(r"^vexhost_rt_\d+_[a-z0-9_]{1,48}$")
DANGEROUS_EXEC = re.compile(r"(docker\b|/var/run/docker\.sock|mount\b|--privileged|nsenter\b|rm\s+-rf\s+/(?:\s|$)|mkfs\b|dd\s+if=)", re.I)


class ProjectRuntime(BaseModel):
    id: int = Field(gt=0)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,48}$")
    type: str
    restart_policy: str = "always"


class NamePayload(BaseModel):
    name: str


class ExecPayload(NamePayload):
    command: str = Field(min_length=1, max_length=500)


class PolicyPayload(NamePayload):
    policy: str


def _container_name(project: ProjectRuntime) -> str:
    name = f"vexhost_rt_{project.id}_{project.slug}"[:62].replace("-", "_")
    if not SAFE_NAME.fullmatch(name):
        raise HTTPException(status_code=422, detail="Invalid runtime container name")
    return name


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not SAFE_NAME.fullmatch(name):
        raise HTTPException(status_code=422, detail="Invalid runtime container name")
    return name


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)


def _host_workspace(project: ProjectRuntime) -> str:
    return f"{RUNTIME_HOST_DEPLOY_ROOT}/.workspaces/{project.slug}"


@app.get("/healthz")
def healthz() -> dict:
    ok = _run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=10)
    return {"ok": ok.returncode == 0, "docker": ok.stdout.strip() if ok.returncode == 0 else "unavailable"}


@app.post("/runtime/start")
def runtime_start(project: ProjectRuntime) -> dict:
    if project.type not in RUNTIME_IMAGES:
        raise HTTPException(status_code=422, detail="Unsupported runtime type")
    name = _container_name(project)
    policy = RESTART_POLICY_MAP.get(project.restart_policy or "always", "unless-stopped")
    image = RUNTIME_IMAGES[project.type]
    cmd = RUNTIME_COMMANDS[project.type]
    _run(["docker", "rm", "-f", name], timeout=30)
    env_args: list[str] = []
    if os.path.exists(os.path.join(DEPLOY_ROOT, ".workspaces", project.slug, ".env")):
        env_args = ["--env-file", f"{_host_workspace(project)}/.env"]
    run = [
        "docker", "run", "-d", "--name", name, "--network", RUNTIME_NETWORK,
        "--restart", policy,
        "--memory", f"{RUNTIME_MEMORY_MB}m", "--cpus", RUNTIME_CPUS, "--pids-limit", "256",
        "--label", f"vexhost.project_id={project.id}", *env_args,
        "-e", "PORT=8080", "-w", "/workspace", "-v", f"{_host_workspace(project)}:/workspace",
        image, "sh", "-lc", cmd.replace("sh -lc '", "").rstrip("'"),
    ]
    proc = _run(run, timeout=180)
    return {"ok": proc.returncode == 0, "container": name, "output": proc.stdout[-12000:], "exit_code": proc.returncode}


@app.post("/runtime/stop")
def runtime_stop(payload: NamePayload) -> dict:
    name = _validate_name(payload.name)
    proc = _run(["docker", "rm", "-f", name], timeout=30)
    return {"ok": proc.returncode == 0, "output": proc.stdout[-4000:], "exit_code": proc.returncode}


@app.post("/runtime/start-existing")
def runtime_start_existing(payload: NamePayload) -> dict:
    name = _validate_name(payload.name)
    proc = _run(["docker", "start", name], timeout=60)
    return {"ok": proc.returncode == 0, "output": proc.stdout[-4000:], "exit_code": proc.returncode}


@app.post("/runtime/policy")
def runtime_policy(payload: PolicyPayload) -> dict:
    name = _validate_name(payload.name)
    if payload.policy not in RESTART_POLICY_MAP:
        raise HTTPException(status_code=422, detail="Invalid restart policy")
    proc = _run(["docker", "update", "--restart", RESTART_POLICY_MAP[payload.policy], name], timeout=20)
    return {"ok": proc.returncode == 0, "output": proc.stdout[-4000:], "exit_code": proc.returncode}


@app.get("/runtime/inspect/{name}")
def runtime_inspect(name: str) -> dict:
    name = _validate_name(name)
    fmt = "{{.State.Status}}|{{.State.Running}}|{{.State.StartedAt}}|{{.State.FinishedAt}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.RestartCount}}|{{.State.Error}}"
    proc = _run(["docker", "inspect", "-f", fmt, name], timeout=20)
    if proc.returncode != 0:
        return {"exists": False, "status": "not_created"}
    parts = (proc.stdout.strip().split("|") + [""] * 8)[:8]
    return {
        "exists": True,
        "status": parts[0] or "unknown",
        "running": parts[1] == "true",
        "started_at": parts[2],
        "finished_at": parts[3],
        "exit_code": int(parts[4]) if parts[4].lstrip("-").isdigit() else 0,
        "oom_killed": parts[5] == "true",
        "restart_count": int(parts[6]) if parts[6].isdigit() else 0,
        "error": parts[7].strip(),
    }


@app.get("/runtime/stats/{name}")
def runtime_stats(name: str) -> dict:
    name = _validate_name(name)
    proc = _run(["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}", name], timeout=20)
    if proc.returncode != 0 or "|" not in proc.stdout:
        return {"ok": False}
    cpu_s, mem_s, memperc_s = (proc.stdout.strip().split("|") + ["", "", ""])[:3]

    def to_mb(token: str) -> float:
        token = token.strip()
        m = re.match(r"([0-9.]+)\s*([KMGT]?i?B)?", token)
        if not m:
            return 0.0
        val = float(m.group(1))
        unit = (m.group(2) or "B").lower()
        factor = {"b": 1/(1024*1024), "kib": 1/1024, "kb": 1/1024, "mib": 1, "mb": 1, "gib": 1024, "gb": 1024, "tib": 1024*1024, "tb": 1024*1024}.get(unit, 1)
        return round(val * factor, 1)

    used_s, _, limit_s = mem_s.partition("/")
    return {
        "ok": True,
        "cpu_percent": round(float(cpu_s.strip().rstrip("%") or 0), 1),
        "mem_used_mb": to_mb(used_s),
        "mem_limit_mb": to_mb(limit_s) or float(RUNTIME_MEMORY_MB),
        "mem_percent": round(float(memperc_s.strip().rstrip("%") or 0), 1),
    }


@app.get("/runtime/logs/{name}")
def runtime_logs(name: str, lines: int = 160) -> dict:
    name = _validate_name(name)
    lines = max(1, min(int(lines or 160), 1000))
    proc = _run(["docker", "logs", "--tail", str(lines), name], timeout=30)
    return {"ok": proc.returncode == 0, "logs": proc.stdout[-20000:], "exit_code": proc.returncode}


@app.post("/runtime/exec")
def runtime_exec(payload: ExecPayload) -> dict:
    name = _validate_name(payload.name)
    command = payload.command.strip()
    if DANGEROUS_EXEC.search(command):
        raise HTTPException(status_code=422, detail="Command is not allowed by runtime-manager policy")
    proc = _run(["docker", "exec", name, "sh", "-lc", command], timeout=30)
    return {"exit_code": proc.returncode, "output": proc.stdout[-8000:]}
