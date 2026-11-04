"""The signed cookies that carry a passkey ceremony's challenge to its answer.

The options routes hand the browser a challenge, and the verify routes need it back. Kept
in the Flask session, it made every options answer rewrite the session cookie: an answer
that landed after a sign-in could sign the visitor out, and a navigation from another
site, which arrives without the ``SameSite=Strict`` session cookie, replaced the session
with one holding only the challenge. Each kind of ceremony therefore keeps its challenge
in a cookie of its own, signed with ``SECRET_KEY`` and good for
:data:`CHALLENGE_TTL_SECONDS`, which only its own routes set and clear. ``ai/auth.md``
explains the choice.
"""

from typing import Literal

from flask import current_app, request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from werkzeug.wrappers import Response

ChallengeKind = Literal['register', 'login']
"""The two ceremonies: adding a passkey, and signing in with one."""

CHALLENGE_TTL_SECONDS = 300
"""How long a ceremony's challenge stays good; the browser's prompt waits as long."""

_COOKIE_PATH = '/api/v1/auth/passkeys'

_PAYLOAD_KEYS = frozenset({'challenge', 'user_id'})
"""The fields :func:`new_challenge_token` signs, and the only ones a token may carry."""


def _serializer(kind: ChallengeKind) -> URLSafeTimedSerializer:
    """Build the signer for one kind of challenge token.

    Args:
        kind: The ceremony.

    Returns:
        A serializer keyed on ``SECRET_KEY`` and salted with the kind, so a sign-in token
        never passes as a registration one.
    """
    secret_key = current_app.config['SECRET_KEY']
    return URLSafeTimedSerializer(secret_key, salt=f'passkey-{kind}')


def new_challenge_token(
    kind: ChallengeKind, challenge: bytes, *, user_id: int | None
) -> str:
    """Sign a ceremony's challenge together with the account it was issued to.

    Args:
        kind: The ceremony.
        challenge: The random bytes the options carry.
        user_id: The account adding a passkey, or ``None`` for a sign-in.

    Returns:
        The signed token, for :func:`set_challenge_cookie`.
    """
    payload = {'challenge': bytes_to_base64url(challenge), 'user_id': user_id}
    return _serializer(kind).dumps(payload)


def _challenge_in(payload: object, *, user_id: int | None) -> bytes | None:
    """Take the challenge out of a token's signed payload.

    Args:
        payload: What the token's signature covers.
        user_id: The account answering, or ``None`` for a sign-in.

    Returns:
        The challenge, or ``None`` when the payload is not the shape
        :func:`new_challenge_token` signs or names another account.
    """
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        return None
    challenge = payload['challenge']
    if not isinstance(challenge, str) or payload['user_id'] != user_id:
        return None
    try:
        return base64url_to_bytes(challenge)
    except ValueError:  # binascii.Error, for text that is not base64url
        return None


def challenge_from_token(
    kind: ChallengeKind, token: str | None, *, user_id: int | None
) -> bytes | None:
    """Check a ceremony's challenge token and take the challenge out of it.

    Args:
        kind: The ceremony being answered.
        token: The token from the ceremony's cookie, or ``None`` when there is none.
        user_id: The account answering, or ``None`` for a sign-in.

    Returns:
        The challenge, or ``None`` for a missing token, a bad signature, a token older
        than :data:`CHALLENGE_TTL_SECONDS`, one of another kind or for another account,
        and a payload of another shape.
    """
    if token is None:
        return None
    try:
        payload = _serializer(kind).loads(token, max_age=CHALLENGE_TTL_SECONDS)
    except BadSignature:  # SignatureExpired is one too
        return None
    return _challenge_in(payload, user_id=user_id)


def _uses_https() -> bool:
    """Tell whether the site is served over https.

    Returns:
        ``True`` when ``PUBLIC_BASE_URL`` is https; ``False`` for plain http, which only
        development uses, and when it is unset.
    """
    return (current_app.config['PUBLIC_BASE_URL'] or '').startswith('https://')


def _cookie_name_and_path(kind: ChallengeKind) -> tuple[str, str]:
    """Choose a ceremony's cookie name and path for the site's scheme.

    Over https the ``__Host-`` prefix makes browsers refuse the cookie from a sibling host
    or plain http. The prefix requires ``Path=/`` and ``Secure``, so plain http keeps the
    plain name and the passkey routes' path.

    Args:
        kind: The ceremony.

    Returns:
        The cookie's name and path.
    """
    if _uses_https():
        return f'__Host-passkey_{kind}', '/'
    return f'passkey_{kind}', _COOKIE_PATH


def set_challenge_cookie(response: Response, kind: ChallengeKind, token: str) -> None:
    """Hand the browser a ceremony's challenge token along with its options.

    ``SameSite=Strict`` keeps the cookie off every request another site starts, and it
    lives as long as the challenge stays good.

    Args:
        response: The options answer.
        kind: The ceremony.
        token: The token from :func:`new_challenge_token`.
    """
    name, path = _cookie_name_and_path(kind)
    response.set_cookie(
        name,
        token,
        max_age=CHALLENGE_TTL_SECONDS,
        path=path,
        httponly=True,
        secure=_uses_https(),
        samesite='Strict',
    )


def read_challenge_cookie(kind: ChallengeKind) -> str | None:
    """Read a ceremony's challenge token from the request.

    Args:
        kind: The ceremony being answered.

    Returns:
        The token, or ``None`` when the request carries no such cookie.
    """
    return request.cookies.get(_cookie_name_and_path(kind)[0])


def clear_challenge_cookie(response: Response, kind: ChallengeKind) -> Response:
    """Delete a ceremony's challenge cookie, so that one answer spends the challenge.

    A browser matches a cookie by name and path, and refuses a ``__Host-`` one without
    ``Secure``, a deletion included. The response comes back so that
    ``after_this_request`` can apply this to whatever answer a route gives.

    Args:
        response: The verify route's answer.
        kind: The ceremony answered.

    Returns:
        The same response.
    """
    name, path = _cookie_name_and_path(kind)
    response.delete_cookie(name, path=path, secure=_uses_https())
    return response
