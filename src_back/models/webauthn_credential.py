"""A passkey: a WebAuthn credential that can sign in to one account."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src_back.extensions import Base
from src_back.models.base import BaseMixin

if TYPE_CHECKING:
    from src_back.models.user import User


class WebAuthnCredential(BaseMixin, Base):
    """One passkey, held by an authenticator, that can sign in to one account.

    ``credential_id`` is what the browser names at sign-in, and ``public_key`` the COSE
    key that checks the signature; neither leaves the server. ``sign_count`` is the
    authenticator's counter, which a cloned key would repeat; synced passkeys always
    report 0. It is a ``BigInteger`` because the counter is an unsigned 32-bit number,
    which PostgreSQL's ``integer`` cannot hold. ``transports`` keeps the browser's hints,
    comma-joined, for the next registration's exclude list; ``backup_eligible`` says
    whether the passkey can sync, and ``backup_state`` whether it has.
    """

    __tablename__ = 'webauthn_credentials'

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0)
    transports: Mapped[str | None] = mapped_column(String(255))
    aaguid: Mapped[str | None] = mapped_column(String(36))
    backup_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_state: Mapped[bool] = mapped_column(Boolean, default=False)
    nickname: Mapped[str | None] = mapped_column(String(64))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates='passkeys')

    def __repr__(self) -> str:
        """Describe the passkey by id and account for logs and debugging.

        Returns:
            The repr string, for example ``<WebAuthnCredential 4 user=3>``.
        """
        return f'<WebAuthnCredential {self.id} user={self.user_id}>'
