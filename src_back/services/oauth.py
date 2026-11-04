"""Sign-in through a provider: the authorize URL, the code exchange, and the accounts.

:func:`resolve_user` is the linking policy, and it fails closed; ``ai/auth.md`` explains
each step. Nothing here keeps a provider's tokens.
"""

import logging
from typing import Any
from urllib.parse import urlencode

import requests
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from src_back.extensions import db
from src_back.models import OAuthAccount, Role, User
from src_back.services.audit_log import AuditTrail
from src_back.services.auth import (
    USER_AUDIT_TRAIL,
    find_user_by_email,
    lock_sign_in_methods,
    require_another_sign_in_method,
)
from src_back.services.errors import InactiveAccountError, OAuthError
from src_back.services.oauth_providers import OAuthIdentity, OAuthProvider
from src_back.services.oauth_state import OAuthTransaction, code_challenge
from src_back.services.oidc import HTTP_TIMEOUT_SECONDS

_log = logging.getLogger(__name__)

_DISPLAY_NAME_LENGTH = 255
"""The length of ``oauth_accounts.display_name``; a longer name is cut to fit."""

AUTO_LINK_BY_EMAIL = False
"""Whether a provider's verified email may attach to an existing account.

Off, every existing account is refused, with a password or without. Registration never
verifies an address, so anyone can register a victim's email with a password and wait,
and attaching the victim's provider account would leave them a working password to the
merged account. An account a provider created can drop that provider while a passkey
remains, and attaching to an account without a password would let the removed identity
attach itself again. A project that verifies addresses at registration, and accepts that
an unlink then no longer revokes a provider, can turn this on.
"""

# Each link and unlink changes how an account can sign in. Only admins may read these
# histories, as for accounts. A link made in the callback has no actor, because
# production's session cookie does not reach it; the entry's user_id names the account.
OAUTH_ACCOUNT_AUDIT_TRAIL = AuditTrail(
    OAuthAccount,
    ('user_id', 'provider', 'email'),
    label_field='provider',
    admin_only=True,
)


def signed_in_user_id() -> int | None:
    """Find who is signed in, for a ``start`` that asked to link.

    It reads Flask-Login's own ``current_user`` rather than the typed one in
    :mod:`src_back.auth`, because the route is open to anonymous visitors.

    Returns:
        The signed-in account's id, or ``None`` for an anonymous visitor.
    """
    return current_user.id if current_user.is_authenticated else None


def build_authorize_url(
    provider: OAuthProvider, *, redirect_uri: str, txn: OAuthTransaction
) -> str:
    """Build the URL that sends the browser to the provider.

    Args:
        provider: The provider.
        redirect_uri: The callback URL registered with the provider.
        txn: The transaction, whose state, nonce, and verifier the URL carries.

    Returns:
        The absolute authorize URL.
    """
    params = {
        'client_id': provider.client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(provider.scopes),
        'state': txn.state,
        'nonce': txn.nonce,
        **provider.extra_authorize_params,
    }
    if txn.code_verifier is not None:
        params['code_challenge'] = code_challenge(txn.code_verifier)
        params['code_challenge_method'] = 'S256'
    return f'{provider.authorize_url}?{urlencode(params)}'


def exchange_code(
    provider: OAuthProvider, *, code: str, redirect_uri: str, code_verifier: str | None
) -> dict[str, Any]:
    """Trade an authorization code for the provider's tokens.

    The log line carries the status and URL only: a failure's message holds no secret,
    and it is what shows a wrong client secret, which the visitor sees only as
    ``exchange_failed``.

    Args:
        provider: The provider.
        code: The authorization code from the callback.
        redirect_uri: The callback URL, which must match the authorize request's.
        code_verifier: The transaction's PKCE verifier, if the provider uses one.

    Returns:
        The token response.

    Raises:
        OAuthError: With ``exchange_failed`` if the provider cannot be reached, refuses
            the code, or answers with anything but a JSON object.
    """
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'client_id': provider.client_id,
        'client_secret': provider.client_secret(),
    }
    if code_verifier is not None:
        payload['code_verifier'] = code_verifier
    try:
        response = requests.post(
            provider.token_url,
            data=payload,
            headers={'Accept': 'application/json'},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        tokens = response.json()
    except requests.RequestException as exc:
        _log.warning('The token exchange with %s failed: %s', provider.name, exc)
        raise OAuthError('exchange_failed') from exc
    if not isinstance(tokens, dict):
        raise OAuthError('exchange_failed')
    return tokens


def _attach_account(user: User, identity: OAuthIdentity) -> User:
    """Link a provider identity to an account and save it.

    Args:
        user: The account to link to.
        identity: The identity the provider asserted.

    Returns:
        The account.

    Raises:
        InactiveAccountError: If the account has been deactivated.
        OAuthError: With ``already_linked`` if the account already has this provider.
    """
    if not user.is_active:
        raise InactiveAccountError('Account is inactive.')
    if any(account.provider == identity.provider for account in user.oauth_accounts):
        raise OAuthError('already_linked')
    display_name = (identity.display_name or '')[:_DISPLAY_NAME_LENGTH] or None
    account = OAuthAccount(
        provider=identity.provider,
        provider_user_id=identity.subject,
        email=identity.email,
        display_name=display_name,
    )
    user.oauth_accounts.append(account)
    OAUTH_ACCOUNT_AUDIT_TRAIL.log_created(account)
    db.session.commit()
    return user


def _create_user(email: str, identity: OAuthIdentity) -> User:
    """Create a passwordless account for a verified identity.

    Args:
        email: The verified address.
        identity: The identity the provider asserted.

    Returns:
        The committed account, linked to the identity.
    """
    user = User(email=email, role=Role.user)
    db.session.add(user)
    USER_AUDIT_TRAIL.log_created(user)
    return _attach_account(user, identity)


def _resolve_by_email(identity: OAuthIdentity) -> User:
    """Create an account from a verified email, or refuse one that an account holds.

    An existing account, with a password or without, is attached to only when
    :data:`AUTO_LINK_BY_EMAIL` says so. Otherwise its owner signs in another way and links
    the provider from the Account page (``ai/auth.md``).

    Args:
        identity: The identity the provider asserted, which matches no link.

    Returns:
        The account.

    Raises:
        OAuthError: With ``email_required`` if the provider gave no email,
            ``email_unverified`` if it did not verify it, and ``link_required`` if it
            belongs to an existing account.
    """
    if not identity.email:
        raise OAuthError('email_required')
    if not identity.email_verified:
        raise OAuthError('email_unverified')
    user = find_user_by_email(identity.email)
    if user is None:
        return _create_user(identity.email, identity)
    if not AUTO_LINK_BY_EMAIL:
        raise OAuthError('link_required')
    return _attach_account(user, identity)


def _resolve_user(identity: OAuthIdentity, *, link_user_id: int | None) -> User:
    """Find or create the account a provider identity signs in to.

    The provider's subject decides first, because an email can change hands. Failing
    that, link mode attaches to the signed-in account whatever the email says, and an
    ordinary sign-in falls back on a verified email.

    Args:
        identity: The identity the provider asserted.
        link_user_id: The account being linked, or ``None`` for an ordinary sign-in.

    Returns:
        The account to sign in, with any new link committed.

    Raises:
        InactiveAccountError: If the account being linked no longer exists.
        OAuthError: With ``already_linked`` if the identity belongs to another account.
    """
    account = (
        db.session.query(OAuthAccount)
        .filter_by(provider=identity.provider, provider_user_id=identity.subject)
        .first()
    )
    if account is not None:
        if link_user_id is not None and account.user_id != link_user_id:
            raise OAuthError('already_linked')
        return account.user
    if link_user_id is None:
        return _resolve_by_email(identity)
    user = db.session.get(User, link_user_id)
    if user is None:
        # The code is spent by now, so this must be a failure that ends the transaction.
        raise InactiveAccountError('Account is inactive.')
    return _attach_account(user, identity)


def resolve_user(identity: OAuthIdentity, *, link_user_id: int | None) -> User:
    """Resolve an identity to an account, treating a lost race for a row as a refusal.

    Two first sign-ins at once can both miss the row they then insert. The unique
    constraints decide between them, and the loser gets a redirect instead of a 500.

    Args:
        identity: The identity the provider asserted.
        link_user_id: The account being linked, or ``None`` for an ordinary sign-in.

    Returns:
        The account to sign in, with any new link committed.

    Raises:
        OAuthError: With ``already_linked`` if another request took the row first.
    """
    try:
        return _resolve_user(identity, link_user_id=link_user_id)
    except IntegrityError as exc:
        db.session.rollback()
        raise OAuthError('already_linked') from exc


def list_accounts(user: User) -> list[OAuthAccount]:
    """List an account's linked providers.

    Args:
        user: The account.

    Returns:
        Its links, in provider order.
    """
    return sorted(user.oauth_accounts, key=lambda account: account.provider)


def unlink_account(user: User, provider: str) -> bool:
    """Remove an account's link to a provider, unless it is the last way to sign in.

    :func:`~src_back.services.auth.lock_sign_in_methods` comes first, so a removal that
    overlaps this one finishes before the link is looked up and the methods counted, and
    :func:`~src_back.services.auth.require_another_sign_in_method` refuses the last one.

    Args:
        user: The account.
        provider: The provider's registry name.

    Returns:
        ``True`` once the link is gone, ``False`` if there was none.
    """
    lock_sign_in_methods(user)
    account = next(
        (link for link in user.oauth_accounts if link.provider == provider), None
    )
    if account is None:
        return False
    require_another_sign_in_method(user)
    OAUTH_ACCOUNT_AUDIT_TRAIL.log_deleted(account)
    user.oauth_accounts.remove(account)
    db.session.commit()
    return True
