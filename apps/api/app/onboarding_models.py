from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import utcnow
class OrganizationOnboarding(Base):
    __tablename__ = "organization_onboarding"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    current_step: Mapped[str] = mapped_column(String(24), default="welcome")
    completed_steps: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="IN_PROGRESS")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str] = mapped_column(ForeignKey("auth_users.id"))
