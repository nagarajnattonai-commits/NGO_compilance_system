"""Separately deployable scheduler. It enqueues work and never runs domain services."""
import argparse

from .automation_service import schedule_scans
from .database import SessionLocal
from .process_control import install_signal_handlers, stop_event, wait


def schedule_once():
    with SessionLocal() as db:
        return schedule_scans(db)


def main():
    parser = argparse.ArgumentParser(description="Enqueue compliance automation scans")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    install_signal_handlers()
    while not stop_event.is_set():
        schedule_once()
        if not args.loop:
            break
        wait(max(10, min(args.interval, 3600)))


if __name__ == "__main__":
    main()
