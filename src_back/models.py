"""SQLAlchemy models.

Every persisted model mixes in :class:`BaseMixin` for a surrogate key, a public
``uuid`` that is safe to expose in URLs, and audit timestamps.
"""

import enum
import uuid as uuid_lib
from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

from src_back.extensions import Base


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


class Role(enum.StrEnum):
    """Application roles.

    Only :attr:`admin` is privileged; see :func:`src_back.utils.admin_required`.
    New accounts receive :attr:`user` and are promoted out of band.
    """

    admin = 'admin'
    user = 'user'


class User(UserMixin, BaseMixin, Base):
    """An account that can sign in.

    The role is stored as a plain string column (``native_enum=False``) so the
    same migration works on PostgreSQL and SQLite.
    """

    __tablename__ = 'users'

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name='role', native_enum=False), default=Role.user
    )

    def set_password(self, password: str) -> None:
        """Hash a plaintext password and store it on the account.

        Args:
            password: The plaintext password to hash. Never persisted as-is.
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check a plaintext password against the stored hash.

        Args:
            password: The plaintext password submitted at sign-in.

        Returns:
            ``True`` when the password matches the stored hash.
        """
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        """Describe the account by email for logs and debugging.

        Returns:
            The repr string, for example ``<User a@b.test>``.
        """
        return f'<User {self.email}>'
