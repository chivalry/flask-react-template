"""Exceptions services raise when a request breaks a business rule.

Route handlers catch them and answer with the matching envelope from
:mod:`src_back.utils`: :func:`~src_back.utils.conflict` for a 409,
:func:`~src_back.utils.bad_request` for a 400, and
:func:`~src_back.utils.forbidden` for a 403.
"""


class DuplicateRecordError(Exception):
    """A unique natural key, such as a name or an email, is already taken (409)."""


class LastSignInMethodError(Exception):
    """Removing a sign-in method would leave the account no way to sign in (409)."""


class RecordInUseError(Exception):
    """A record cannot be deleted while other rows still reference it (409)."""

    def __init__(self, message: str, count: int) -> None:
        """Record how many rows block the delete.

        Args:
            message: The explanation returned to the client.
            count: The number of referencing rows.
        """
        super().__init__(message)
        self.count = count


class ProtectedRecordError(Exception):
    """A built-in record the application relies on cannot be deleted (409)."""


class SelfModificationError(Exception):
    """An admin tried to deactivate or demote their own account (400)."""


class InactiveAccountError(Exception):
    """A deactivated account tried to sign in (403)."""
