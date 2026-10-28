"""The audit log: one row per change a service records, never edited afterwards."""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src_back.extensions import Base
from src_back.models.base import BaseMixin

if TYPE_CHECKING:
    from src_back.models.user import User


class AuditAction(enum.StrEnum):
    """What happened to the record an audit entry describes."""

    created = 'created'
    updated = 'updated'
    deleted = 'deleted'


class AuditLog(BaseMixin, Base):
    """One recorded change to one row of an audited table.

    ``record_id`` has no foreign key, so the entry outlives the record it describes.
    ``changes`` holds the record's audited fields for ``created`` and ``deleted``, and
    ``{field: {'old': ..., 'new': ...}}`` for each field an ``updated`` changed.
    ``changed_by_id`` is ``None`` for a change made outside a signed-in request, such
    as the seed's, and becomes ``None`` when that account is deleted.
    """

    __tablename__ = 'audit_logs'
    # One record's history is the lookup every detail view makes.
    __table_args__ = (
        Index('ix_audit_logs_table_name_record_id', 'table_name', 'record_id'),
    )

    table_name: Mapped[str] = mapped_column(String(100))
    record_id: Mapped[int] = mapped_column()
    record_label: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name='audit_action', native_enum=False)
    )
    changes: Mapped[dict[str, Any]] = mapped_column(JSON)
    changed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), index=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    changed_by: Mapped[User | None] = relationship(back_populates='audit_entries')

    @property
    def changed_by_name(self) -> str | None:
        """Name the account that made the change.

        Returns:
            Its email, since accounts have no other name, or ``None`` when no
            signed-in account made the change or that account was deleted.
        """
        return self.changed_by.email if self.changed_by is not None else None

    def __repr__(self) -> str:
        """Describe the entry by table, record, and action for logs and debugging.

        Returns:
            The repr string, for example ``<AuditLog widgets:4 updated>``.
        """
        return f'<AuditLog {self.table_name}:{self.record_id} {self.action}>'
