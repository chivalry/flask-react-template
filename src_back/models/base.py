"""Shared mixin for every persisted model.

Every persisted model mixes in :class:`BaseMixin` for a surrogate key, a public
``uuid`` that is safe to expose in URLs, and audit timestamps.
"""

import uuid as uuid_lib
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column


class BaseMixin:
    """Surrogate key, public identifier, and audit timestamps.

    ``updated_at`` is refreshed by SQLAlchemy on every flush that changes the
    row, so services never set it by hand.
    """

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(
        String(36), unique=True, default=lambda: str(uuid_lib.uuid4())
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
