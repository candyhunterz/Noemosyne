"""Small database-backed worker entrypoint for explicit M1 jobs."""

from __future__ import annotations

from datetime import UTC, datetime

from noemosyne_db.models import Job
from noemosyne_db.session import SessionLocal
from sqlalchemy import select


def run_one() -> bool:
    """Claim one pending job; M1 has no autonomous ingestion or model calls."""
    with SessionLocal.begin() as session:
        job = session.scalar(
            select(Job)
            .where(Job.status == "pending")
            .order_by(Job.recorded_at)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return False
        job.status = "completed"
        job.started_at = datetime.now(UTC)
        job.completed_at = job.started_at
        job.result_json = {"note": "No M1 background handler registered"}
    return True


if __name__ == "__main__":
    run_one()
