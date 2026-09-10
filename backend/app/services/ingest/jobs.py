"""后台任务执行器：ThreadPoolExecutor(N) + ingest_jobs 状态机。

- worker 线程通过 SyncSessionLocal 使用独立同步 engine（SQLite 连接不可跨线程共享）
- 幂等：同一文档已有排队/运行中任务时直接复用，不重复提交
- 生产环境替换方案：Celery + Redis（任务持久化、失败重试、多 worker 水平扩展）
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models import JOB_DELETE, JOB_INGEST, JOB_QUEUED, JOB_REBUILD, IngestJob

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(
    max_workers=settings.ingest_workers, thread_name_prefix="ingest"
)


def _run_job(job_id: int) -> None:
    """worker 入口：按任务类型分发到流水线。"""
    from app.services.ingest import pipeline

    with SyncSessionLocal() as db:
        job = db.get(IngestJob, job_id)
        if job is None:
            return
        job_type = job.job_type
        document_id = job.document_id

    try:
        if job_type == JOB_INGEST:
            pipeline.run_ingest(job_id)
        elif job_type == JOB_DELETE:
            pipeline.run_delete(document_id)
            _finish_job(job_id, "删除完成")
        elif job_type == JOB_REBUILD:
            pipeline.run_rebuild(re_embed=(document_id == -1))
            _finish_job(job_id, "索引重建完成")
    except Exception as e:  # noqa: BLE001
        logger.exception("任务 %s 执行异常", job_id)
        _finish_job(job_id, f"执行异常: {e}", failed=True)


def _finish_job(job_id: int, message: str, failed: bool = False) -> None:
    from app.models import JOB_FAILED, JOB_SUCCEEDED
    from app.models.common import utcnow

    with SyncSessionLocal() as db:
        job = db.get(IngestJob, job_id)
        if job is not None:
            job.status = JOB_FAILED if failed else JOB_SUCCEEDED
            job.message = message
            job.progress = 100.0 if not failed else job.progress
            job.finished_at = utcnow()
            db.commit()


def _has_active_job(db, document_id: int, job_type: str) -> IngestJob | None:
    return db.scalar(
        select(IngestJob)
        .where(
            IngestJob.document_id == document_id,
            IngestJob.job_type == job_type,
            IngestJob.status.in_([JOB_QUEUED, "running"]),
        )
        .order_by(IngestJob.id.desc())
    )


def submit_ingest(document_id: int, started_by: int) -> IngestJob:
    """提交单文档摄入任务；已存在进行中任务则复用。"""
    with SyncSessionLocal() as db:
        active = _has_active_job(db, document_id, JOB_INGEST)
        if active is not None:
            return active
        job = IngestJob(
            document_id=document_id, job_type=JOB_INGEST, status=JOB_QUEUED, started_by=started_by
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    _executor.submit(_run_job, job_id)
    return job


def submit_delete(document_id: int, started_by: int) -> IngestJob:
    with SyncSessionLocal() as db:
        job = IngestJob(
            document_id=document_id, job_type=JOB_DELETE, status=JOB_QUEUED, started_by=started_by
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    _executor.submit(_run_job, job_id)
    return job


def submit_rebuild(started_by: int, re_embed: bool = False) -> IngestJob:
    """提交索引重建任务（document_id=-1 表示 re_embed 全量重向量化）。"""
    with SyncSessionLocal() as db:
        job = IngestJob(
            document_id=-1 if re_embed else None,
            job_type=JOB_REBUILD,
            status=JOB_QUEUED,
            started_by=started_by,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    _executor.submit(_run_job, job_id)
    return job
