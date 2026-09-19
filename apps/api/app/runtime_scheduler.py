"""Separately deployable scheduler. It enqueues work and never runs domain services."""
import argparse
import time

from .automation_service import schedule_scans
from .database import SessionLocal


def schedule_once():
    with SessionLocal() as db:
        return schedule_scans(db)


def main():
    parser = argparse.ArgumentParser(description="Enqueue compliance automation scans")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    while True:
        schedule_once()
        if not args.loop:
            break
        time.sleep(max(10, min(args.interval, 3600)))


if __name__ == "__main__":
    main()
