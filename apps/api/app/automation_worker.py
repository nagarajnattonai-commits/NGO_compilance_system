"""Separately deployable worker for durable compliance automation jobs."""
import argparse
import os
import socket
import time
import uuid

from .automation_service import claim_job, execute_job, fail_job, finish_job
from .database import SessionLocal


def process_one(worker_id: str | None = None) -> bool:
    identity = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        job = claim_job(db, identity)
        if not job:
            return False
        started = time.monotonic()
        try:
            result = execute_job(db, job)
            finish_job(db, job, result, started_monotonic=started)
            db.commit()
        except Exception as error:
            db.rollback()
            job = db.get(type(job), job.id)
            fail_job(db, job, error, started_monotonic=started)
            db.commit()
        return True


def process_batch(limit: int = 25, worker_id: str | None = None) -> int:
    processed = 0
    for _ in range(limit):
        if not process_one(worker_id):
            break
        processed += 1
    return processed


def main():
    parser = argparse.ArgumentParser(description="Process compliance automation jobs")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    while True:
        processed = process_batch(max(1, min(args.limit, 200)))
        if not args.loop:
            break
        time.sleep(1 if processed else 5)


if __name__ == "__main__":
    main()
