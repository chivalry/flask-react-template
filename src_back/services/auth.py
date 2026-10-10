"""Account creation and credential checking."""

from src_back.extensions import db
from src_back.models import Role, User


def register_user(email: str, password: str) -> User:
    """Create a new account and commit it.

    New accounts always receive the unprivileged ``user`` role; admins are
    promoted out of band rather than at registration.

    Args:
        email: The address to register. Must not already be in use.
        password: The plaintext password, hashed before it is stored.

    Returns:
        The newly committed user.

    Raises:
        ValueError: If an account with that email already exists.
    """
    if db.session.query(User).filter_by(email=email).first():
        raise ValueError('Email already registered.')
    user = User(email=email, role=Role.user)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def authenticate_user(email: str, password: str) -> User | None:
    """Look up an account and verify its password.

    Returns ``None`` for both an unknown address and a wrong password, so
    callers cannot distinguish the two and leak which emails are registered.

    Args:
        email: The address submitted at sign-in.
        password: The plaintext password submitted at sign-in.

    Returns:
        The matching user, or ``None`` if the credentials are not valid.
    """
    user = db.session.query(User).filter_by(email=email).first()
    if user and user.check_password(password):
        return user
    return None
