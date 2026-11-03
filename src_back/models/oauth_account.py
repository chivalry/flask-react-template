"""A sign-in provider's identity, linked to one account."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src_back.extensions import Base
from src_back.models.base import BaseMixin

if TYPE_CHECKING:
    from src_back.models.user import User


class OAuthAccount(BaseMixin, Base):
    """One provider identity that can sign in to one account.

    ``provider_user_id`` is the provider's stable id for the person, and the only thing
    a returning sign-in is matched on: an email can change hands, so ``email`` and
    ``display_name`` only label the link on the Account page. An account has at most one
    link per provider, because unlinking names a provider rather than a row.
    """

    __tablename__ = 'oauth_accounts'
    __table_args__ = (
        UniqueConstraint(
            'provider', 'provider_user_id', name='uq_oauth_accounts_provider_subject'
        ),
        UniqueConstraint('user_id', 'provider', name='uq_oauth_accounts_user_provider'),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates='oauth_accounts')

    def __repr__(self) -> str:
        """Describe the link by provider and account for logs and debugging.

        Returns:
            The repr string, for example ``<OAuthAccount google user=3>``.
        """
        return f'<OAuthAccount {self.provider} user={self.user_id}>'
