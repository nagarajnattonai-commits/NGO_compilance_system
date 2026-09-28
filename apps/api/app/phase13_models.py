"""Personal saved views for the existing workspace lists and global search."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import uid, utcnow


class SavedView(Base):
    __tablename__ = "saved_views"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "scope", "name", name="uq_saved_view_user_scope_name"),
        Index("ix_saved_view_personal_default", "tenant_id", "user_id", "scope", "is_default"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(30), default="GLOBAL_SEARCH")
    filters: Mapped[str] = mapped_column(Text, default="{}")
    sorting: Mapped[str] = mapped_column(Text, default="{}")
    visible_columns: Mapped[str] = mapped_column(Text, default="[]")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
