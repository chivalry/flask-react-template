"""Account creation, credential checking, and the one place a sign-in starts."""

import secrets

from flask import session
from flask_login import login_user
from werkzeug.security import check_password_hash, generate_password_hash

from src_back.extensions import db
from src_back.models import Role, User
from src_back.models.user import normalize_email
from src_back.services.errors import DuplicateRecordError

# Checked in place of a stored hash when there is none, so an unknown email and an
# account without a password cost the same hash computation as a wrong password. It
# is hashed the way User.set_password hashes, from a random plaintext nobody keeps, so
# checking it can never let anyone in.
_DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))


def find_user_by_email(email: str) -> User | None:
    """Look up an account by email, ignoring case and surrounding whitespace.

    Args:
        email: The address to look up, in any case.

    Returns:
        The account registered under that address, or ``None`` if there is none.
    """
    return db.session.query(User).filter_by(email=normalize_email(email)).first()


def register_user(email: str, password: str) -> User:
    """Create a new account and commit it.

    The duplicate check ignores letter case, and the model stores the email
    normalized. New accounts always receive the unprivileged ``user`` role; admins
    are promoted out of band rather than at registration.

    Args:
        email: The address to register, in any case. Must not already be in use.
        password: The plaintext password, hashed before it is stored.

    Returns:
        The newly committed user.

    Raises:
        DuplicateRecordError: If an account with that email already exists.
    """
    if find_user_by_email(email) is not None:
        raise DuplicateRecordError('Email already registered.')
    user = User(email=email, role=Role.user)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def authenticate_user(email: str, password: str) -> User | None:
    """Look up an account and verify its password.

    Returns ``None`` for an unknown address, an account without a password, and a
    wrong password alike, so callers cannot tell which emails are registered. The
    first two check the password against a dummy hash, so all three cost one hash
    computation and take the same time.

    Args:
        email: The address submitted at sign-in, in any case.
        password: The plaintext password submitted at sign-in.

    Returns:
        The matching user, or ``None`` if the credentials are not valid.
    """
    user = find_user_by_email(email)
    if user is None or not user.has_password:
        check_password_hash(_DUMMY_PASSWORD_HASH, password)
        return None
    return user if user.check_password(password) else None


def complete_login(user: User) -> None:
    """Start the session of a user whose identity has been verified.

    Every sign-in ends here, whatever proved the identity: registration and password
    login now, a provider callback or a passkey later. The session is permanent, so
    its cookie carries an expiry ``SESSION_LIFETIME_DAYS`` out and every later
    response pushes it forward.

    Args:
        user: The account to sign in.
    """
    login_user(user)
    session.permanent = True


def count_sign_in_methods(user: User) -> int:
    """Count the ways an account can sign in.

    Code that removes a sign-in method checks this first and raises
    :class:`~src_back.services.errors.LastSignInMethodError` instead of removing the
    last one. Only a password counts so far; linked providers and passkeys join the
    count when their tables arrive.

    Args:
        user: The account to inspect.

    Returns:
        The number of sign-in methods the account has.
    """
    return 1 if user.has_password else 0
