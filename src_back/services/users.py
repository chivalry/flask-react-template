"""Accounts: the list query, create, and update operations behind the admin routes.

There is no delete. An account is deactivated instead, which keeps the rows that
reference it intact.
"""

from typing import Any

from sqlalchemy import Select, select

from src_back.extensions import db
from src_back.models import Role, User
from src_back.services.auth import find_user_by_email
from src_back.services.errors import DuplicateRecordError, SelfModificationError

EMAIL_IN_USE = 'Email already in use.'
SELF_MODIFICATION = 'You cannot deactivate or demote your own account.'


def select_users_in_email_order() -> Select[tuple[User]]:
    """Build the query for every account, active or not, in email order.

    The list route pages it in SQL through :func:`~src_back.utils.paginate_select`
    instead of loading every account.

    Returns:
        The select of accounts, ordered by email.
    """
    return select(User).order_by(User.email)


def _is_email_taken(email: str, except_user_id: int | None = None) -> bool:
    """Tell whether an account other than the given one already has the email.

    Letter case and surrounding whitespace are ignored, as in every email
    comparison, because the lookup goes through
    :func:`~src_back.services.auth.find_user_by_email`.

    Args:
        email: The address to look up, in any case.
        except_user_id: The account whose own address does not count as a
            conflict, as when it is the one being updated; ``None`` on create.

    Returns:
        ``True`` when a different account has the email.
    """
    existing = find_user_by_email(email)
    return existing is not None and existing.id != except_user_id


def _removes_admin_access(data: dict[str, Any]) -> bool:
    """Tell whether an update would deactivate an account or take its admin role.

    Args:
        data: The validated update payload.

    Returns:
        ``True`` when the payload sets ``is_active`` to ``False`` or sets
        ``role`` to anything but ``admin``.
    """
    deactivates = data.get('is_active') is False
    demotes = 'role' in data and data['role'] != Role.admin
    return deactivates or demotes


def create_user(data: dict[str, Any]) -> User:
    """Create an account with the role and status the admin chose.

    Args:
        data: The validated payload: ``email``, ``password``, ``role``, and ``is_active``.

    Returns:
        The committed account.

    Raises:
        DuplicateRecordError: If the email is already in use.
    """
    if _is_email_taken(data['email']):
        raise DuplicateRecordError(EMAIL_IN_USE)
    user = User(email=data['email'], role=data['role'], is_active=data['is_active'])
    user.set_password(data['password'])
    db.session.add(user)
    db.session.commit()
    return user


def update_user(user_id: int, data: dict[str, Any], actor_id: int) -> User | None:
    """Apply the admin's changes to an account.

    Args:
        user_id: The account's primary key.
        data: The validated payload; every key is optional.
        actor_id: The signed-in admin's primary key, so an admin cannot lock
            themself out by deactivating or demoting their own account.

    Returns:
        The updated account, or ``None`` if there is no such account.

    Raises:
        SelfModificationError: If the admin deactivates or demotes themself.
        DuplicateRecordError: If the new email belongs to another account.
    """
    user = db.session.get(User, user_id)
    if user is None:
        return None
    if user_id == actor_id and _removes_admin_access(data):
        raise SelfModificationError(SELF_MODIFICATION)
    if 'email' in data and _is_email_taken(data['email'], except_user_id=user_id):
        raise DuplicateRecordError(EMAIL_IN_USE)
    for key in ('email', 'role', 'is_active'):
        if key in data:
            setattr(user, key, data[key])
    if 'password' in data:
        user.set_password(data['password'])
    db.session.commit()
    return user
