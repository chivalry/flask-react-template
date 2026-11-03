"""OpenID Connect ID-token validation against a provider's published keys.

Each process keeps a provider's keys for an hour, and fetches them again at once when a
token names a key it does not hold, because providers rotate keys without notice.
"""

import hmac
import logging
import time
from collections.abc import Sequence
from typing import Any

import requests
from joserfc import jwt
from joserfc.errors import InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from src_back.services.errors import OAuthError

_log = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = (3, 5)
"""Connect and read limits; a callback's three calls stay under gunicorn's 30 seconds."""

_JWKS_CACHE_SECONDS = 3600
_CLOCK_SKEW_SECONDS = 60

_ALLOWED_ALGORITHMS = ('RS256',)
"""Naming the algorithm refuses ``none`` and an HMAC token signed with a public key."""

_key_sets: dict[str, tuple[float, KeySet]] = {}
"""Each JWKS URI's keys and the monotonic time they were fetched, per process."""


def fetch_jwks(jwks_uri: str, *, refresh: bool = False) -> KeySet:
    """Return a provider's public keys, from this process's cache while fresh.

    Args:
        jwks_uri: The provider's JWKS URL.
        refresh: Whether to skip the cache, as for a token signed by an unknown key.

    Returns:
        The provider's keys.

    Raises:
        OAuthError: With ``invalid_token`` if the keys cannot be fetched or read, since
            no token can then be checked.
    """
    cached = _key_sets.get(jwks_uri)
    if cached and not refresh and time.monotonic() - cached[0] < _JWKS_CACHE_SECONDS:
        return cached[1]
    try:
        response = requests.get(jwks_uri, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        key_set = KeySet.import_key_set(response.json())
    except (requests.RequestException, JoseError, KeyError, TypeError, ValueError) as exc:
        _log.warning('Fetching the keys at %s failed: %s', jwks_uri, exc)
        raise OAuthError('invalid_token') from exc
    _key_sets[jwks_uri] = (time.monotonic(), key_set)
    return key_set


def _decode_signed_token(id_token: str, jwks_uri: str) -> dict[str, Any]:
    """Check a token's signature, fetching the keys again for an unknown key id.

    Args:
        id_token: The compact JWT from the token response.
        jwks_uri: The provider's JWKS URL.

    Returns:
        The token's claims, not yet checked.
    """
    try:
        token = jwt.decode(id_token, fetch_jwks(jwks_uri), algorithms=_ALLOWED_ALGORITHMS)
    except InvalidKeyIdError:
        key_set = fetch_jwks(jwks_uri, refresh=True)
        token = jwt.decode(id_token, key_set, algorithms=_ALLOWED_ALGORITHMS)
    return token.claims


def verify_id_token(
    id_token: str,
    *,
    jwks_uri: str,
    issuers: Sequence[str],
    audience: str,
    nonce: str,
) -> dict[str, Any]:
    """Validate an ID token's signature, issuer, audience, expiry, subject, and nonce.

    Args:
        id_token: The compact JWT from the token response.
        jwks_uri: The provider's JWKS URL.
        issuers: The issuer values the provider may use.
        audience: This application's client id.
        nonce: The nonce the transaction sent in the authorize request.

    Returns:
        The token's claims.

    Raises:
        OAuthError: With ``invalid_token`` if any check fails.
    """
    try:
        claims = _decode_signed_token(id_token, jwks_uri)
        JWTClaimsRegistry(
            leeway=_CLOCK_SKEW_SECONDS,
            iss={'essential': True, 'values': list(issuers)},
            exp={'essential': True},
            sub={'essential': True},
        ).validate(claims)
    except JoseError as exc:
        raise OAuthError('invalid_token') from exc
    # Compared here because joserfc accepts a list holding any one match, and OIDC Core
    # 3.1.3.7 rejects a token with an audience this client does not trust.
    if claims.get('aud') not in (audience, [audience]):
        raise OAuthError('invalid_token')
    # Encoded, because compare_digest refuses text that is not ASCII.
    token_nonce = str(claims.get('nonce', '')).encode()
    if not hmac.compare_digest(token_nonce, nonce.encode()):
        raise OAuthError('invalid_token')
    return claims
