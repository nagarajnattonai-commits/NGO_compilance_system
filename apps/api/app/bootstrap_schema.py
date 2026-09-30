"""Explicit, fresh-database-only bootstrap; never run from API startup."""
import argparse

from sqlalchemy import inspect

from .database import Base, engine
from .production_security import validate_production_configuration
from . import main as _main  # register the complete application model metadata


def apply(target=engine):
    validate_production_configuration()
    if inspect(target).get_table_names():
        raise RuntimeError("Schema bootstrap requires an empty database; use the reviewed additive migrations")
    Base.metadata.create_all(bind=target)
    return len(Base.metadata.tables)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(f"Created {apply()} tables" if args.apply else "Fresh database bootstrap; review configuration and run --apply")
