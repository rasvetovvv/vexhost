from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from .db import SessionLocal, init_db
from .deployer import deploy_static, DEPLOY_ROOT, _copytree_clean
from .models import Deployment, Project

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('vexhost-worker')

POLL_SECONDS = 3


async def claim_job() -> int | None:
    async with SessionLocal() as session:
        job = await session.scalar(
            select(Deployment)
            # Runtime container starts are handled by the API's background task
            # (_runtime_start_job); claiming them here would race it and fail
            # deploy_static() with repo_url='runtime'.
            .where(Deployment.status == 'queued', Deployment.build_command != 'runtime-start')
            .order_by(Deployment.id.asc())
            .limit(1)
        )
        if not job:
            return None
        project = await session.scalar(select(Project).where(Project.id == job.project_id))
        if not project:
            job.status = 'failed'
            job.log = 'Project was deleted before deployment started.'
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
            return None
        job.status = 'processing'
        job.started_at = datetime.now(timezone.utc)
        job.log = 'Queued. Worker claimed deployment job.\nProcessing build/publish…'
        project.status = 'deploying'
        project.last_deploy_status = 'processing'
        project.last_deploy_log = job.log
        await session.commit()
        return job.id


async def run_job(job_id: int) -> None:
    async with SessionLocal() as session:
        job = await session.scalar(select(Deployment).where(Deployment.id == job_id))
        project = await session.scalar(select(Project).where(Project.id == job.project_id)) if job else None
        if not job or not project:
            return
        repo_url = job.repo_url or project.repo_url or ''
        build_command = job.build_command or project.build_command or 'auto'
        output_dir = job.output_dir or project.output_dir or 'auto'
        slug = project.slug
        job.status = 'processing'
        job.log = (job.log or '') + '\nRunning isolated static deploy worker…'
        project.last_deploy_status = 'processing'
        project.last_deploy_log = job.log
        await session.commit()

    try:
        generated_url, deploy_log = await asyncio.to_thread(deploy_static, repo_url, slug, build_command, output_dir)
        if project.subdomain and project.subdomain != slug:
            await asyncio.to_thread(_copytree_clean, DEPLOY_ROOT / slug, DEPLOY_ROOT / project.subdomain)
        live_url = project.live_url or generated_url
        status = 'success'
        final_log = deploy_log
    except Exception as exc:
        live_url = None
        status = 'failed'
        final_log = f'VexHost deploy failed: {exc}'

    async with SessionLocal() as session:
        job = await session.scalar(select(Deployment).where(Deployment.id == job_id))
        project = await session.scalar(select(Project).where(Project.id == job.project_id)) if job else None
        if job:
            job.status = status
            job.log = final_log
            job.live_url = live_url
            job.finished_at = datetime.now(timezone.utc)
        if project:
            project.status = 'live' if status == 'success' else 'deploy_failed'
            if live_url:
                project.live_url = live_url
            project.last_deploy_status = status
            project.last_deploy_log = final_log
            project.last_deployed_at = datetime.now(timezone.utc)
        await session.commit()
    log.info('deployment job %s finished with %s', job_id, status)


async def main() -> None:
    await init_db()
    log.info('VexHost Stage 4 worker started')
    while True:
        try:
            job_id = await claim_job()
            if job_id:
                await run_job(job_id)
            else:
                await asyncio.sleep(POLL_SECONDS)
        except Exception:
            log.exception('worker loop error')
            await asyncio.sleep(POLL_SECONDS)


if __name__ == '__main__':
    asyncio.run(main())
