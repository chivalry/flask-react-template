"""The registry of sign-in providers, and how each one identifies a person.

A provider is enabled only when its keys are in the environment and ``PUBLIC_BASE_URL``
is known. A new provider is one :class:`OAuthProvider` and one identity function here;
``ai/auth.md`` has each provider's setup steps.
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from joserfc import jwt
from joserfc.jwk import ECKey

from src_back.services.errors import OAuthError
from src_back.services.oidc import verify_id_token

_log = logging.getLogger(__name__)

GOOGLE_AUTHORIZE_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_JWKS_URI = 'https://www.googleapis.com/oauth2/v3/certs'
GOOGLE_ISSUERS = ('https://accounts.google.com', 'accounts.google.com')

APPLE_AUTHORIZE_URL = 'https://appleid.apple.com/auth/authorize'
APPLE_TOKEN_URL = 'https://appleid.apple.com/auth/token'
APPLE_JWKS_URI = 'https://appleid.apple.com/auth/keys'
APPLE_ISSUER = 'https://appleid.apple.com'
"""The issuer of Apple's ID tokens, and the audience of the client secrets it accepts."""

APPLE_KEYS = (
    'OAUTH_APPLE_CLIENT_ID',
    'OAUTH_APPLE_TEAM_ID',
    'OAUTH_APPLE_KEY_ID',
    'OAUTH_APPLE_PRIVATE_KEY',
)
"""Sign in with Apple's variables, all four of which it needs."""

APPLE_SECRET_SECONDS = 300
"""How long a client secret lasts. Apple accepts up to six months, and a secret minted
for each exchange needs only minutes, so no long-lived secret exists."""

APPLE_USER_FIELD_LIMIT = 4096
"""The longest ``user`` field read from Apple's answer, which holds a name and an email.

Apple's form is urlencoded, which Flask's form memory limit does not cover, so the
field can be as long as the 25 MB request limit allows. The cap keeps parsing cheap,
and keeps nesting below the depth at which ``json.loads`` raises ``RecursionError``.
"""

_UNSTORABLE_CATEGORIES = frozenset({'Cc', 'Cs'})
"""Control characters, NUL among them, which PostgreSQL refuses in text, and lone
surrogates, which have no UTF-8 form."""


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
    exchange. ``fetch_identity`` receives the provider, the token response, the
    transaction's nonce, and the parameters the provider's redirect carried, where Apple
    puts its one-time ``user`` field. ``issuers`` is empty and ``jwks_uri`` is ``None``
    for a provider without ID tokens (#31).
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
    fetch_identity: Callable[
        [OAuthProvider, Mapping[str, Any], str, Mapping[str, str]], OAuthIdentity
    ]
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

    Google's documentation shows ``email_verified`` both ways, and Apple documents it as
    either. Only ``True`` and ``'true'`` count, so ``'false'`` is false.

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
    provider: OAuthProvider,
    tokens: Mapping[str, Any],
    nonce: str,
    callback_params: Mapping[str, str],
) -> OAuthIdentity:
    """Read who signed in from Google's ID token.

    Args:
        provider: The Google provider.
        tokens: The token response.
        nonce: The transaction's nonce.
        callback_params: The callback's parameters, of which Google's needs none.

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


def apple_display_name(user_field: str | None) -> str | None:
    """Read the name from the ``user`` field of Apple's first answer.

    Apple sends the field once, when a person first authorizes the site, as JSON holding
    ``name.firstName``, ``name.lastName``, and ``email``. It is unsigned form data, so
    only the name is read; the email comes from the ID token. Anything malformed reads
    as no name.

    Args:
        user_field: The field's text, if the callback carried one.

    Returns:
        The given and family names joined by a space, or ``None``.
    """
    if not user_field or len(user_field) > APPLE_USER_FIELD_LIMIT:
        return None
    try:
        user = json.loads(user_field)
    # Python 3.12.0 to 3.12.2 raise RecursionError at depths the cap still admits.
    except (RecursionError, ValueError):
        return None
    name = user.get('name') if isinstance(user, dict) else None
    if not isinstance(name, dict):
        return None
    parts = (_storable_text(name.get(key)) for key in ('firstName', 'lastName'))
    return ' '.join(part for part in parts if part) or None


def _storable_text(value: object) -> str:
    """Keep the text of a name part that every database can store.

    Args:
        value: The part, which may be any JSON value.

    Returns:
        The text without control characters or lone surrogates, trimmed, or an empty
        string for anything but text.
    """
    if not isinstance(value, str):
        return ''
    kept = (
        char for char in value if unicodedata.category(char) not in _UNSTORABLE_CATEGORIES
    )
    return ''.join(kept).strip()


def _apple_identity(
    provider: OAuthProvider,
    tokens: Mapping[str, Any],
    nonce: str,
    callback_params: Mapping[str, str],
) -> OAuthIdentity:
    """Read who signed in from Apple's ID token, and their name from its first answer.

    Apple documents an empty ``email`` for some school and work accounts, which counts
    as none.

    Args:
        provider: The Apple provider.
        tokens: The token response.
        nonce: The transaction's nonce.
        callback_params: The callback's form, where Apple's first answer adds ``user``.

    Returns:
        The identity the token's claims assert, named from the ``user`` field.
    """
    claims = id_token_claims(provider, tokens, nonce)
    return OAuthIdentity(
        provider=provider.name,
        subject=claims['sub'],
        email=claims.get('email') or None,
        email_verified=is_true_claim(claims.get('email_verified')),
        display_name=apple_display_name(callback_params.get('user')),
    )


def load_private_key(value: str) -> ECKey:
    """Import Sign in with Apple's key from the text of its ``.p8`` file.

    A ``.env`` value is one line, so the key's line breaks may arrive escaped, as a
    backslash and an ``n``: Compose and python-dotenv restore them inside double quotes
    but not inside single ones.

    Args:
        value: The ``.p8`` file's text, with its line breaks real or escaped.

    Returns:
        The key, not yet known to be able to sign.
    """
    return ECKey.import_key(value.replace('\\n', '\n'))


def apple_client_secret(
    *, team_id: str, client_id: str, key_id: str, private_key: ECKey
) -> str:
    """Mint the client secret one token exchange with Apple sends.

    The secret is a JWT signed with the team's Sign in with Apple key, carrying exactly
    the header and claims Apple documents. ``typ`` stays out of the header, which
    joserfc would otherwise add.

    Args:
        team_id: The developer team's ID, the secret's issuer.
        client_id: The Services ID, the secret's subject.
        key_id: The key's ID, by which Apple finds the public half.
        private_key: The team's P-256 key.

    Returns:
        The signed secret, good for :data:`APPLE_SECRET_SECONDS`.
    """
    issued_at = int(time.time())
    claims = {
        'iss': team_id,
        'iat': issued_at,
        'exp': issued_at + APPLE_SECRET_SECONDS,
        'aud': APPLE_ISSUER,
        'sub': client_id,
    }
    return jwt.encode(
        {'alg': 'ES256', 'kid': key_id},
        claims,
        private_key,
        algorithms=['ES256'],
        default_type=None,
    )


def _apple_settings(
    env: Mapping[str, str], public_base_url: str
) -> dict[str, str] | None:
    """Read Sign in with Apple's four values, warning when they cannot enable it.

    A project without Apple sets none of them, and that logs nothing.

    Args:
        env: The environment.
        public_base_url: The site's public origin.

    Returns:
        The four values by name, or ``None`` while Apple stays off.
    """
    settings = {name: env.get(name) or '' for name in APPLE_KEYS}
    if not any(settings.values()):
        return None
    missing = [name for name, value in settings.items() if not value]
    if missing:
        _log.warning('Sign in with Apple is off: %s not set.', ', '.join(missing))
        return None
    # Apple accepts a return URL only on a domain, and its token endpoint only https.
    if not public_base_url.startswith('https://'):
        _log.warning('Sign in with Apple is off: PUBLIC_BASE_URL must be https.')
        return None
    return settings


def _apple_secret_minter(settings: Mapping[str, str]) -> Callable[[], str] | None:
    """Prepare the function that mints Apple's client secrets, if the key can sign.

    One secret is minted here as a trial, because
    :func:`~src_back.services.oauth.exchange_code` asks for one outside its error
    handling, so a key that cannot sign would fail a callback instead of keeping Apple
    off. Any failure keeps Apple off, because ``create_app()`` builds the registry and an
    optional provider must not stop the app from starting.

    Args:
        settings: Apple's four values by name.

    Returns:
        The function, or ``None`` if the key is unusable.
    """
    try:
        mint = partial(
            apple_client_secret,
            team_id=settings['OAUTH_APPLE_TEAM_ID'],
            client_id=settings['OAUTH_APPLE_CLIENT_ID'],
            key_id=settings['OAUTH_APPLE_KEY_ID'],
            private_key=load_private_key(settings['OAUTH_APPLE_PRIVATE_KEY']),
        )
        mint()
    except Exception as exc:  # joserfc and cryptography refuse a bad key with many types
        # The class says what is wrong, such as a malformed or encrypted file, another
        # kind of key, another curve, or a public key, and it quotes nothing of the key.
        _log.warning(
            'Sign in with Apple is off: OAUTH_APPLE_PRIVATE_KEY is not a usable P-256 '
            'private key (%s).',
            type(exc).__name__,
        )
        return None
    return mint


def _apple_provider(env: Mapping[str, str], public_base_url: str) -> OAuthProvider | None:
    """Build the Apple provider when its four keys are set and the site is https.

    Apple answers with a POSTed form, which it requires once any scope is asked for,
    and it documents no PKCE, so the nonce alone ties its ID token to the transaction.

    Args:
        env: The environment.
        public_base_url: The site's public origin.

    Returns:
        The provider, or ``None`` while Apple stays off.
    """
    settings = _apple_settings(env, public_base_url)
    mint = None if settings is None else _apple_secret_minter(settings)
    if settings is None or mint is None:
        return None
    return OAuthProvider(
        name='apple',
        label='Apple',
        authorize_url=APPLE_AUTHORIZE_URL,
        token_url=APPLE_TOKEN_URL,
        scopes=('name', 'email'),
        uses_pkce=False,
        client_id=settings['OAUTH_APPLE_CLIENT_ID'],
        client_secret=mint,
        extra_authorize_params={'response_mode': 'form_post'},
        fetch_identity=_apple_identity,
        issuers=(APPLE_ISSUER,),
        jwks_uri=APPLE_JWKS_URI,
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
    candidates = (_google_provider(env), _apple_provider(env, public_base_url))
    return {provider.name: provider for provider in candidates if provider is not None}
