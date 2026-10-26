"""Accounts and their roles."""

import enum

from flask_login import UserMixin
from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, validates
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


def normalize_email(email: str) -> str:
    """Return the form every email is stored and compared in.

    Surrounding whitespace is dropped and every letter lowercased, so letter case
    never lets one address register twice or miss its account at sign-in.
    :class:`User` applies it to every email assigned to an account, and
    :func:`src_back.services.auth.find_user_by_email` to every address it looks up.

    Args:
        email: An address as a client submitted it or a provider asserted it.

    Returns:
        The trimmed, lowercased address.
    """
    return email.strip().lower()


class User(UserMixin, BaseMixin, Base):
    """An account that can sign in.

    The role is stored as a plain string column (``native_enum=False``) so the
    same migration works on PostgreSQL and SQLite. Every email assigned to an
    account is stored through :func:`normalize_email`, however the account is
    created or edited. ``password_hash`` is ``None`` for an account a sign-in
    provider created, which has no password.
    """

    __tablename__ = 'users'

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name='role', native_enum=False), default=Role.user
    )

    @validates('email')
    def _store_email_normalized(self, _key: str, email: str) -> str:
        """Normalize an email as it is assigned, so no code path stores another form.

        Args:
            _key: The attribute being set, always ``email``. Unused.
            email: The address being assigned.

        Returns:
            The address as :func:`normalize_email` returns it.
        """
        return normalize_email(email)

    @property
    def has_password(self) -> bool:
        """Whether the account can sign in with a password.

        Returns:
            ``False`` for an account a sign-in provider created without one.
        """
        return self.password_hash is not None

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
            ``True`` when the password matches the stored hash; always ``False``
            for an account without a password.
        """
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        """Describe the account by email for logs and debugging.

        Returns:
            The repr string, for example ``<User a@b.test>``.
        """
        return f'<User {self.email}>'
