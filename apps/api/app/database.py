from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'ngoguard.db'}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
if DATABASE_URL == "sqlite:///:memory:":
    engine_options["poolclass"] = StaticPool
elif DATABASE_URL.startswith("postgresql+"):
    connect_args.update({
        "connect_timeout": int(os.getenv("DATABASE_CONNECT_TIMEOUT", "10")),
        "application_name": os.getenv("DATABASE_APPLICATION_NAME", "setu-compliance")[:63],
    })
    engine_options.update({
        "pool_size": int(os.getenv("DATABASE_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DATABASE_MAX_OVERFLOW", "20")),
        "pool_timeout": int(os.getenv("DATABASE_POOL_TIMEOUT", "10")),
        "pool_recycle": int(os.getenv("DATABASE_POOL_RECYCLE", "1800")),
    })
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
