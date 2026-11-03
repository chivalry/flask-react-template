"""The registry of sign-in providers, and how each one identifies a person.

A provider is enabled only when its keys are in the environment and ``PUBLIC_BASE_URL``
is known. A new provider is one :class:`OAuthProvider` and one identity function here;
``ai/auth.md`` has each provider's setup steps.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src_back.services.errors import OAuthError
from src_back.services.oidc import verify_id_token

GOOGLE_AUTHORIZE_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_JWKS_URI = 'https://www.googleapis.com/oauth2/v3/certs'
GOOGLE_ISSUERS = ('https://accounts.google.com', 'accounts.google.com')


@dataclass(frozen=True)
class OAuthIdentity:
    """Who a provider says signed in.

    ``subject`` is the provider's stable id for the person. ``email_verified`` is what
    the provider claims, which :func:`~src_back.services.oauth.resolve_user` relies on.
    """

    provider: str
    subject: str
    email: str | None
    email_verified: bool
    display_name: str | None


@dataclass(frozen=True)
class OAuthProvider:
    """One enabled provider.

    ``client_secret`` is a function because Sign in with Apple mints a secret for every
    exchange (#30). ``fetch_identity`` receives the provider, the token response, and the
    transaction's nonce. ``issuers`` is empty and ``jwks_uri`` is ``None`` for a provider
    without ID tokens (#31).
    """

    name: str
    label: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    uses_pkce: bool
    client_id: str
    client_secret: Callable[[], str]
    extra_authorize_params: Mapping[str, str]
    fetch_identity: Callable[[OAuthProvider, Mapping[str, Any], str], OAuthIdentity]
    issuers: tuple[str, ...]
    jwks_uri: str | None


def redirect_uri(public_base_url: str, provider_name: str) -> str:
    """Build the callback URL registered with a provider.

    Args:
        public_base_url: The site's public origin.
        provider_name: The provider's registry name.

    Returns:
        The absolute callback URL.
    """
    return f'{public_base_url}/api/v1/auth/oauth/{provider_name}/callback'


def is_true_claim(value: object) -> bool:
    """Read a boolean claim that a provider may send as text.

    Google's documentation shows ``email_verified`` both ways, and Sign in with Apple
    sends either (#30). Only ``True`` and ``'true'`` count, so ``'false'`` is false.

    Args:
        value: The claim's value, if any.

    Returns:
        ``True`` when the claim says true.
    """
    return value is True or value == 'true'


def id_token_claims(
    provider: OAuthProvider, tokens: Mapping[str, Any], nonce: str
) -> dict[str, Any]:
    """Validate the ID token in a token response.

    Args:
        provider: The provider that answered.
        tokens: The token response.
        nonce: The transaction's nonce.

    Returns:
        The token's claims.

    Raises:
        OAuthError: With ``invalid_token`` if the response holds no ID token.
    """
    id_token = tokens.get('id_token')
    if not isinstance(id_token, str) or provider.jwks_uri is None:
        raise OAuthError('invalid_token')
    return verify_id_token(
        id_token,
        jwks_uri=provider.jwks_uri,
        issuers=provider.issuers,
        audience=provider.client_id,
        nonce=nonce,
    )


def _google_identity(
    provider: OAuthProvider, tokens: Mapping[str, Any], nonce: str
) -> OAuthIdentity:
    """Read who signed in from Google's ID token.

    Args:
        provider: The Google provider.
        tokens: The token response.
        nonce: The transaction's nonce.

    Returns:
        The identity the token's claims assert.
    """
    claims = id_token_claims(provider, tokens, nonce)
    return OAuthIdentity(
        provider=provider.name,
        subject=claims['sub'],
        email=claims.get('email'),
        email_verified=is_true_claim(claims.get('email_verified')),
        display_name=claims.get('name'),
    )


def _google_provider(env: Mapping[str, str]) -> OAuthProvider | None:
    """Build the Google provider when its keys are set.

    ``prompt=select_account`` shows Google's account chooser every time. Without it, a
    browser still signed in to Google goes straight through, so the next person at a
    shared browser, or someone linking a second account, would never see which account
    was used.

    Args:
        env: The environment.

    Returns:
        The provider, or ``None`` unless both keys are set.
    """
    client_id = env.get('OAUTH_GOOGLE_CLIENT_ID')
    client_secret = env.get('OAUTH_GOOGLE_CLIENT_SECRET')
    if not client_id or not client_secret:
        return None
    return OAuthProvider(
        name='google',
        label='Google',
        authorize_url=GOOGLE_AUTHORIZE_URL,
        token_url=GOOGLE_TOKEN_URL,
        scopes=('openid', 'email', 'profile'),
        uses_pkce=True,
        client_id=client_id,
        client_secret=lambda: client_secret,
        extra_authorize_params={'prompt': 'select_account'},
        fetch_identity=_google_identity,
        issuers=GOOGLE_ISSUERS,
        jwks_uri=GOOGLE_JWKS_URI,
    )


def build_registry(
    env: Mapping[str, str], public_base_url: str | None
) -> dict[str, OAuthProvider]:
    """Enable each provider whose keys are set.

    Args:
        env: The environment.
        public_base_url: The site's public origin; without one nothing is enabled,
            because no redirect URI can be built.

    Returns:
        The enabled providers by name, empty when there are none.
    """
    if not public_base_url:
        return {}
    candidates = (_google_provider(env),)
    return {provider.name: provider for provider in candidates if provider is not None}
