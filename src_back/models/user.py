"""Accounts and their roles."""

import enum

from flask_login import UserMixin
from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

from src_back.extensions import Base
from src_back.models.base import BaseMixin


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
