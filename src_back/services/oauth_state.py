"""The signed cookie that carries one sign-in through a provider.

Production's session cookie is ``SameSite=Strict``, so browsers leave it off the
provider's redirect back to the callback, and gunicorn's workers share no memory. The
state, nonce, PKCE verifier, and return path therefore live in a cookie of their own,
signed with ``SECRET_KEY`` and good for ten minutes. ``ai/auth.md`` explains the choice.
"""

import base64
import hashlib
import hmac
import secrets
from dataclasses import asdict, dataclass

from flask import current_app, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.urls import iri_to_uri
from werkzeug.wrappers import Response

from src_back.services.errors import OAuthError

COOKIE_NAME = 'oauth_txn'
SECURE_COOKIE_NAME = '__Host-oauth_txn'
"""The name over https, which browsers refuse from a sibling host or plain http."""
COOKIE_MAX_AGE_SECONDS = 600

_COOKIE_PATH = '/api/v1/auth/oauth'
_SERIALIZER_SALT = 'oauth-txn'

MAX_NEXT_LENGTH = 512
"""The longest return path once percent-encoded, as a redirect header carries it."""


@dataclass(frozen=True)
class OAuthTransaction:
    """One sign-in in progress, as the cookie carries it.

    ``link_user_id`` names the signed-in account when a provider is being linked to it,
    and is ``None`` for an ordinary sign-in. ``code_verifier`` is ``None`` for a provider
    without PKCE.
    """

    provider: str
    state: str
    nonce: str
    code_verifier: str | None
    next_path: str
    link_user_id: int | None


def new_transaction(
    provider: str, *, uses_pkce: bool, next_path: str, link_user_id: int | None
) -> OAuthTransaction:
    """Start a transaction with fresh random values.

    Args:
        provider: The provider's registry name.
        uses_pkce: Whether to make a PKCE verifier.
        next_path: Where to go afterwards, already passed through :func:`safe_next`.
        link_user_id: The signed-in account to link to, or ``None`` to sign in.

    Returns:
        The new transaction.
    """
    return OAuthTransaction(
        provider=provider,
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        code_verifier=secrets.token_urlsafe(64) if uses_pkce else None,
        next_path=next_path,
        link_user_id=link_user_id,
    )


def code_challenge(verifier: str) -> str:
    """Derive the PKCE S256 challenge for a verifier.

    Args:
        verifier: The transaction's code verifier.

    Returns:
        The unpadded URL-safe base64 of the verifier's SHA-256 digest (RFC 7636).
    """
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode()


def state_matches(transaction: OAuthTransaction, state: str) -> bool:
    """Compare a callback's state with the transaction's, in constant time.

    Both sides are encoded first, because ``hmac.compare_digest`` refuses text that is
    not ASCII, which a forged callback can send.

    Args:
        transaction: The transaction read from the cookie.
        state: The ``state`` value the callback carried.

    Returns:
        ``True`` when they match.
    """
    return hmac.compare_digest(state.encode(), transaction.state.encode())


def _serializer() -> URLSafeTimedSerializer:
    """Build the signer for transaction cookies.

    Returns:
        A serializer keyed on ``SECRET_KEY``, with a salt no other signature shares.
    """
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=_SERIALIZER_SALT)


def _uses_https() -> bool:
    """Tell whether the site is served over https.

    Returns:
        ``True`` when ``PUBLIC_BASE_URL`` is https; ``False`` for plain http, which only
        development uses, and when it is unset.
    """
    return (current_app.config['PUBLIC_BASE_URL'] or '').startswith('https://')


def _cookie_name_and_path() -> tuple[str, str]:
    """Choose the cookie's name and path for the site's scheme.

    The signature proves this server issued a transaction, not that it issued it to this
    browser, so over https the ``__Host-`` prefix stops a sibling host or a network
    attacker from planting one of their own. The prefix requires ``Path=/`` and
    ``Secure``, so plain http keeps the plain name and a narrower path.

    Returns:
        The cookie's name and path.
    """
    if _uses_https():
        return SECURE_COOKIE_NAME, '/'
    return COOKIE_NAME, _COOKIE_PATH


def set_transaction_cookie(response: Response, transaction: OAuthTransaction) -> None:
    """Store a transaction in the browser for the provider's redirect back.

    Over https the cookie is ``SameSite=None`` so that a cross-site POST callback carries
    it, which needs ``Secure``. Over plain http it is ``Lax``, which a GET callback still
    carries.

    Args:
        response: The redirect to the provider.
        transaction: The transaction to store.
    """
    name, path = _cookie_name_and_path()
    secure = _uses_https()
    response.set_cookie(
        name,
        _serializer().dumps(asdict(transaction)),
        max_age=COOKIE_MAX_AGE_SECONDS,
        path=path,
        httponly=True,
        secure=secure,
        samesite='None' if secure else 'Lax',
    )


def read_transaction(max_age: int = COOKIE_MAX_AGE_SECONDS) -> OAuthTransaction:
    """Read the transaction back from the request's cookie.

    A browser drops the cookie at its ``max_age``, so a late callback usually carries
    none, which reads as expired like a signature past its age. Signed fields that do not
    fit came from an older release, and count as unreadable.

    Args:
        max_age: The oldest signature to accept, in seconds.

    Returns:
        The transaction.

    Raises:
        OAuthError: With ``expired`` if the cookie is missing or too old, and
            ``invalid_state`` if it cannot be read.
    """
    value = request.cookies.get(_cookie_name_and_path()[0])
    if value is None:
        raise OAuthError('expired')
    try:
        return OAuthTransaction(**_serializer().loads(value, max_age=max_age))
    except SignatureExpired as exc:
        raise OAuthError('expired') from exc
    except (BadSignature, TypeError) as exc:
        raise OAuthError('invalid_state') from exc


def clear_transaction_cookie(response: Response) -> None:
    """Delete the transaction cookie.

    A browser matches a cookie by name and path, and refuses a ``__Host-`` one without
    ``Secure``, a deletion included.

    Args:
        response: The response that ends the transaction.
    """
    name, path = _cookie_name_and_path()
    response.delete_cookie(name, path=path, secure=_uses_https())


def safe_next(value: str | None, default: str) -> str:
    """Accept a return path only if it stays on this site.

    The callback prefixes ``PUBLIC_BASE_URL``, which alone keeps a redirect on this
    origin; this refuses what a browser would still read as another host. Browsers treat
    a backslash as a slash and drop tabs and newlines from a URL, so a slash followed by
    a backslash, or a control character, could turn a path into ``//host``. The length is
    counted percent-encoded, as the callback's redirect header carries the path: an emoji
    takes twelve characters there, and nginx answers a header too large for its buffer
    with a 502.

    Args:
        value: The ``next`` query parameter, if any.
        default: The path to use instead.

    Returns:
        ``value`` when it is a single-slash path of a safe length, otherwise ``default``.
    """
    if (
        value is None
        or not value.startswith('/')
        or value.startswith(('//', '/\\'))
        or not value.isprintable()
        # Last: iri_to_uri raises on a malformed host such as //[, refused above.
        or len(iri_to_uri(value)) > MAX_NEXT_LENGTH
    ):
        return default
    return value
