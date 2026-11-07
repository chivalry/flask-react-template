# Issue #30: Add Sign In With Apple

## Context

Accounts sign in with a password, a passkey, or Google. This change adds Sign in with
Apple as the second provider on the registry #29 built: a client secret minted for each
token exchange, Apple's mandatory `form_post` callback, the person's name from Apple's
first answer, and Apple enabled only over https. The frontend needs no production change:
buttons and link rows come from the server's `{name, label}` list, and Apple adds no
error code to the messages in `src_front/src/utils/oauth.ts`.

What the flow needs is in place. `callback` takes GET and POST and is exempt from
`X-Requested-With`. The `__Host-oauth_txn` cookie is `SameSite=None; Secure` over https,
which a cross-site POST carries, and #29's browser check posted a stub's `form_post` back
in Chrome, WebKit, and Firefox. `is_true_claim()`, `id_token_claims()`, RS256 checks
against a cached JWKS, and `oauth_accounts.display_name` exist. The linking policy fails
closed for every existing account (`AUTO_LINK_BY_EMAIL = False`), and
`count_sign_in_methods()` and `unlink_account()`, which locks first, treat an Apple link
like any other.

### Where the issue and the code disagree

Each of these was checked against the code or a primary source while planning, and each
changes what gets built.

1. **The identity function receives the callback's parameters.** The issue reads the
   name "from the `user` form field", but `fetch_identity` gets only the provider, the
   token response, and the nonce. It gains a fourth argument, the callback's
   `request.values`. Google's ignores it, and so will #31's.
2. **The name lives on the link.** #29's `oauth_accounts.display_name` holds it, cut to
   255 characters by `_attach_account()`, so no migration is needed. Nothing shows it
   yet, as with Google's name.
3. **The `user` field is read for the name only, capped, and cleaned.** It is unsigned
   form data, so its `email` is ignored and the ID token's decides. Apple posts it
   urlencoded, which Werkzeug 3.1.9's form memory limit does not cover (it applies to
   multipart parts only), so the field can run to the 25 MB request limit, nested deeply
   enough that `json.loads` raises `RecursionError` (depth 100,000 does on Python
   3.13.18), which nothing would catch, so the callback would answer 500. A field over
   4,096 characters is not read, and `RecursionError` is caught too, because Python
   3.12.0 to 3.12.2 raise it at depths the cap still admits. Control characters and lone
   surrogates are dropped: PostgreSQL refuses NUL in text, and Python's `sqlite3` raises
   `UnicodeEncodeError` on a lone surrogate (both checked).
4. **The key is checked when the registry is built, and any failure keeps Apple off.**
   `exchange_code()` calls `client_secret()` before its `try`, so a key that cannot sign
   would answer Apple's callback with a 500, and `create_app()` runs `build_registry()`,
   so an exception there would stop the app from starting. `_apple_secret_minter()`
   imports the key and mints one trial secret. With joserfc 1.7.7, a malformed file
   raises `ValueError`, an encrypted one `TypeError`, and an RSA key
   `InvalidKeyTypeError` at import; a P-384 key raises `InvalidKeyCurveError`, a public
   key `UnsupportedKeyOperationError`, and a curve joserfc has no name for, such as
   P-224, `KeyError` at signing. As `passkeys.py` does for py_webauthn, the check catches
   every `Exception` and leaves Apple off with a warning naming the class.
5. **`apple_client_secret()` takes the imported key, not its PEM.** The key is parsed
   once at startup instead of on every exchange. The header is exactly Apple's `alg` and
   `kid`: joserfc adds `typ` unless `default_type=None`.
6. **The private key is the `.p8` file's text, not a path.** Neither Compose file mounts
   a file into the backend, so a path would work only for host-side runs. One line in
   `.env`, double-quoted with `\n` escapes, reaches the backend with real line breaks
   through Compose v5.6.1 and python-dotenv 1.2.4 (both run); a single-quoted one keeps
   the escapes, which `load_private_key()` restores.
7. **A warning only when Apple is partly configured.** The issue says "otherwise log a
   warning and skip", but every project without Apple would then log one at each start.
   With no key set Apple stays off quietly; a missing key, an http origin, or an unusable
   key each warns.
8. **Apple's cancel code joins OAuth's.** `user_cancelled_authorize`, which Apple calls
   "The only error code that might be returned", becomes `cancelled` beside
   `access_denied`. Apple sends `state` with its error, so the state check still runs
   first.
9. **The tests enable Apple only where a test asks.** `OAUTH_ENVIRONMENT` feeds both the
   clearing fixture and every `app`, so Apple's keys there would enable Apple in every
   test and break four exact-match assertions. `APPLE_ENVIRONMENT`, with a P-256 key made
   once per run, and an `apple` fixture keep it apart.
10. **The runbook tries Apple on staging.** `npm run docker:prod:up` exists, but it reads
    the dev `.env`, whose `DATABASE_URL` points at `localhost`, the container itself, and
    whose placeholder `SECRET_KEY` stops a production start, and it serves plain http on
    port 8080. Apple accepts a return URL only on a domain, never `localhost` or an IP
    address, and its token endpoint requires https. Staging has such a domain, and the
    same Services ID takes its return URL beside production's.
11. **Staging arrived after the issue.** `.env.staging.example` gains the four keys,
    blank and optional, and `ai/staging.md` says so.
12. **`*.p8` is ignored by git and Docker.** The runbook has the operator handle
    `AuthKey_<KEY_ID>.p8`, and no ignore rule covered one dropped into the tree.
13. **Compose's own `.env` parsing is now tested.** `test-compose-config.sh` exports its
    values through the shell, so nothing tested how Compose reads a value from the env
    file. A new case pins that a one-line double-quoted key arrives with its line breaks.
14. **The nonce stays mandatory.** Apple's `id_token` reference allows a token without
    `nonce` where `nonce_supported` is false. Apple documents no PKCE, though: its
    discovery document lists no `code_challenge_methods_supported`, and neither its
    authorize nor its token documentation mentions one. The nonce is then what stops an
    authorization code taken from one browser from finishing in another, and RFC 9700
    section 4.5.3.2 says such a client "MUST validate the `nonce` in the ID Token
    obtained from the token endpoint". A token without one stays `invalid_token`.
15. **An empty email counts as none.** Apple documents an empty `email` for some Work &
    School accounts. `_resolve_by_email()` already refuses one as `email_required`, and
    `None` keeps `''` out of `oauth_accounts.email` when such an account links.

### What was checked against primary sources

- **Apple's discovery document**, fetched 2026-11-04: issuer `https://appleid.apple.com`;
  authorize, token, and JWKS endpoints as below; `response_modes_supported` includes
  `form_post`; `id_token_signing_alg_values_supported` is `RS256` alone;
  `token_endpoint_auth_methods_supported` is `client_secret_post` alone; no
  `code_challenge_methods_supported`.
- **Authorization** ("Incorporating Sign in with Apple into other platforms"): the valid
  scopes are `name` and `email`; with any scope `response_mode` "must be `form_post`",
  which sends `application/x-www-form-urlencoded`; `user` is "A JSON string" in the
  format `{ "name": { "firstName": string, "lastName": string }, "email": string }`; an
  error carries `error` and `state`; `redirect_uri` "must include a domain name and can't
  be an IP address or `localhost`".
- **Token endpoint** ("Generate and validate tokens"): `POST
  https://appleid.apple.com/auth/token` with `client_id`, `client_secret`, `code`,
  `grant_type`, and `redirect_uri`, which "must use the HTTPS protocol"; a code "is
  single-use only and valid for five minutes"; a failure is a 400; no `code_verifier`.
- **Client secret** ("Creating a client secret"): ES256 on P-256 with SHA-256; header
  `alg` and `kid`; claims `iss` (the Team ID), `iat`, `exp` no more than 15777000
  seconds ahead, `aud` `https://appleid.apple.com`, and `sub`, the client id.
- **`id_token` reference**: `aud` is the client id; `nonce` "is present only if you pass
  it in the authorization request"; `email` "may be empty for Sign in with Apple at Work
  & School users"; `email_verified` and `is_private_email` "can either be a string
  (`"true"` or `"false"`) or a Boolean"; `real_user_status` "isn't present or supported
  for web-based apps".
- **"Authenticating users with Sign in with Apple"**: "Although Apple provides the user's
  email address in the identity token on all subsequent API responses, it doesn't
  include other information about the user, such as their name."
- **Web configuration help**: Services ID steps; "If you're enrolled as an individual,
  you can register up to 10 website URLs. If you're enrolled as an organization, you can
  register up to 100"; no file needs uploading to register a domain.
- **Private email relay help**: sending domains or addresses are registered under Sign in
  with Apple for Email Communication, with SPF or DKIM passing; "If you don't register
  all the source domains or emails that you use, email sent to the private relay service
  will result in a bounce message."
- **Human Interface Guidelines**: "Continue with Apple" is an allowed title; a custom web
  button keeps its logo and title "either black or white" on a black or white
  background, with Apple's logo artwork; "no smaller than other sign-in buttons". The
  plain outlined button meets the title and size rules, not the colors, which the issue
  defers.
- **RFC 9700 section 4.5.3.2**: the nonce protects a confidential client against code
  injection only if it checks the `nonce` of the ID token from the token endpoint.
- **In this `.venv`**: joserfc 1.7.7 allows ES256 by default and adds `typ` unless
  `default_type=None`; the import and signing failures in point 4; `ECKey.as_pem()`
  takes `password`; `responses` 0.26.3 drops a registration that has answered once a
  newer one matches, so `add` serves successive sign-ins in order; Werkzeug 3.1.9 limits
  form memory for multipart parts only. `unicodedata` puts NUL and tab in `Cc`, a lone
  surrogate in `Cs`, and the zero-width joiner some scripts need in `Cf`, which stays.
- **Python's changelog**: 3.12.0rc1 raised the C recursion limit from 800 to 1500
  (gh-107263), and 3.12.3 changed it to follow each platform's limits (gh-112215), so
  `json.loads` on 3.12.0 to 3.12.2 can raise `RecursionError` within the
  4,096-character cap.
- **Ubuntu's server documentation**: chrony keeps time by default from 25.10, and
  `systemd-timesyncd` before it.
- **RFC 6749 section 4.1.2.1**: for an invalid client id or redirect URI the server
  "MUST NOT automatically redirect the user-agent", so Apple shows that error itself.

### Accepted limits, documented in `ai/auth.md`

- Apple sends the name once. If that first sign-in fails, as `link_required` does, the
  name is lost until the person stops using Sign in with Apple for the site in their
  Apple Account settings and authorizes it again.
- Someone who hides their email has a relay address that matches no account here, so a
  first sign-in creates an account instead of answering `link_required`.
- Mail to a relay address bounces until the sending domain is registered with Apple.
  Nothing in the template mails an account yet.
- Unlinking does not revoke the site at Apple, and Apple's server-to-server
  notifications are not received.
- A secret lasts five minutes, so the server's clock must be right.
- Apple cannot be tried on `localhost`.

### Sources

- [Apple: discovery document](https://appleid.apple.com/.well-known/openid-configuration)
- [Apple: incorporating Sign in with Apple into other platforms][apple-platforms]
- [Apple: generate and validate tokens][apple-tokens]
- [Apple: creating a client secret][apple-secret]
- [Apple: `id_token`][apple-id-token]
- [Apple: authenticating users][apple-authenticating]
- [Apple: configure Sign in with Apple for the web][apple-web]
- [Apple: configure the private email relay service][apple-relay]
- [Apple: Human Interface Guidelines, Sign in with Apple][apple-hig]
- [RFC 9700, OAuth 2.0 Security Best Current Practice](https://www.rfc-editor.org/rfc/rfc9700)
- [Docker: Compose interpolation][compose-interpolation]

[apple-platforms]: https://developer.apple.com/documentation/signinwithapple/incorporating-sign-in-with-apple-into-other-platforms
[apple-tokens]: https://developer.apple.com/documentation/signinwithapplerestapi/generate-and-validate-tokens
[apple-secret]: https://developer.apple.com/documentation/accountorganizationaldatasharing/creating-a-client-secret
[apple-id-token]: https://developer.apple.com/documentation/signinwithapplejs/authorizationi/id_token
[apple-authenticating]: https://developer.apple.com/documentation/signinwithapple/authenticating-users-with-sign-in-with-apple
[apple-web]: https://developer.apple.com/help/account/configure-app-capabilities/configure-sign-in-with-apple-for-the-web
[apple-relay]: https://developer.apple.com/help/account/configure-app-capabilities/configure-private-email-relay-service/
[apple-hig]: https://developer.apple.com/design/human-interface-guidelines/sign-in-with-apple
[compose-interpolation]: https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/

## Branch

`issue-30-add-sign-in-with-apple` — already checked out; PR #60 exists.

## Change

**26 files**: 25 to edit and one to move. Line numbers are each file's before any edit,
and several replacements add lines, so apply each file's changes bottom-up.

- Backend: `src_back/services/oauth_providers.py`, `src_back/api/oauth.py`,
  `src_back/tests/conftest.py`, `src_back/tests/test_oauth_providers.py`,
  `src_back/tests/test_oauth.py`, `src_back/tests/test_oauth_api.py`
- Frontend tests: `src_front/src/test/utils/fixtures.ts`,
  `src_front/src/test/components/auth/ProviderButtons.test.tsx`,
  `src_front/src/test/components/account/LinkedAccounts.test.tsx`
- Configuration: `.env.example`, `.env.staging.example`, `docker-compose.yml`,
  `docker/docker-compose.prod.yml`, `scripts/provision.sh`, `.gitignore`, `.dockerignore`
- Shell tests: `scripts/tests/test-compose-config.sh`, `scripts/tests/test-provision.sh`,
  `scripts/tests/test-deploy.sh`
- Documentation: `ai/auth.md`, `ai/project.md`, `ai/domain.md`, `ai/staging.md`,
  `ai/conventions.md`, `tools.md`
- Move `plans/pr-59-add-passkeys-webauthn-for-sign-in-and.md` into `plans/archive/` with
  `git mv`, as each branch archives the plan before it.

### src_back/services/oauth_providers.py — Apple's provider, secret, key, and name

Replace the whole file with this. Google's code is unchanged except that its identity
function takes the fourth argument and `is_true_claim`'s docstring loses "(#30)".

```python
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
```

### src_back/api/oauth.py — Apple's cancel code, and the callback's parameters

After `_KEEPS_TRANSACTION` and its docstring (line 48), add:

```python
_CANCELLED_ERRORS = frozenset({'access_denied', 'user_cancelled_authorize'})
"""The ``error`` a provider sends when the person declines: OAuth's, and Apple's."""
```

Replace `_finish_sign_in` (lines 163-196) with:

```python
def _finish_sign_in(provider: OAuthProvider, transaction: OAuthTransaction) -> User:
    """Check the provider's answer and resolve it to an account.

    The state is compared before anything else in the answer is believed. The answer's
    parameters reach the provider's identity function, which is how Apple's one-time
    ``user`` field arrives.

    Args:
        provider: The provider named in the URL.
        transaction: The transaction read from the cookie.

    Returns:
        The account to sign in.

    Raises:
        OAuthError: With ``invalid_state`` if the answer does not belong to this
            transaction, ``cancelled`` if the person declined at the provider, and
            ``exchange_failed`` if the provider reported any other failure.
    """
    state = request.values.get('state', '')
    if transaction.provider != provider.name or not state_matches(transaction, state):
        raise OAuthError('invalid_state')
    error = request.values.get('error')
    if error:
        failure = 'cancelled' if error in _CANCELLED_ERRORS else 'exchange_failed'
        raise OAuthError(failure)
    code = request.values.get('code')
    if not code:
        raise OAuthError('exchange_failed')
    tokens = exchange_code(
        provider,
        code=code,
        redirect_uri=redirect_uri(current_app.config['PUBLIC_BASE_URL'], provider.name),
        code_verifier=transaction.code_verifier,
    )
    identity = provider.fetch_identity(
        provider, tokens, transaction.nonce, request.values
    )
    return resolve_user(identity, link_user_id=transaction.link_user_id)
```

### src_back/tests/conftest.py — Apple's test keys and two fixtures

Change the two imports at lines 13 and 22-26 to:

```python
from joserfc.jwk import ECKey, KeySet, RSAKey
```

```python
from src_back.services.oauth_providers import (
    APPLE_ISSUER,
    APPLE_JWKS_URI,
    GOOGLE_ISSUERS,
    GOOGLE_JWKS_URI,
    OAuthProvider,
    build_registry,
)
```

After `OAUTH_ENVIRONMENT` (line 54), add:

```python
APPLE_CLIENT_ID = 'com.example.app.web'
APPLE_TEAM_ID = 'TEAMID1234'
APPLE_KEY_ID = 'KEYID12345'
# The test team's Sign in with Apple key, made once per run.
APPLE_PRIVATE_KEY = ECKey.generate_key('P-256')
APPLE_ENVIRONMENT = {
    'OAUTH_APPLE_CLIENT_ID': APPLE_CLIENT_ID,
    'OAUTH_APPLE_TEAM_ID': APPLE_TEAM_ID,
    'OAUTH_APPLE_KEY_ID': APPLE_KEY_ID,
    'OAUTH_APPLE_PRIVATE_KEY': APPLE_PRIVATE_KEY.as_pem(private=True).decode(),
}
# What OidcSigner.make_id_token needs to sign as Apple rather than Google.
APPLE_ID_TOKEN_CLAIMS = {
    'iss': APPLE_ISSUER,
    'aud': APPLE_CLIENT_ID,
    'sub': 'apple-subject',
}
```

Replace `_clear_oauth_environment` (lines 98-103) with:

```python
@pytest.fixture(autouse=True)
def _clear_oauth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # src_back.app loads .env at import, where a developer's real keys would enable
    # Google or Apple in every app a test builds without injecting a registry.
    for name in (*OAUTH_ENVIRONMENT, *APPLE_ENVIRONMENT):
        monkeypatch.delenv(name, raising=False)
```

After `oidc_signer` (line 241), add:

```python
@pytest.fixture()
def apple_signer(
    oidc_signer: OidcSigner, mocked_http: responses.RequestsMock
) -> OidcSigner:
    # The same key answers at Apple's JWKS URL; APPLE_ID_TOKEN_CLAIMS makes a token
    # Apple's.
    mocked_http.add(responses.GET, APPLE_JWKS_URI, json=oidc_signer.public_jwks())
    return oidc_signer


@pytest.fixture()
def apple(app: Flask, apple_signer: OidcSigner) -> OAuthProvider:
    # Apple joins Google in this test's registry, built from the test team's keys.
    provider = build_registry(APPLE_ENVIRONMENT, PUBLIC_BASE_URL)['apple']
    app.config['OAUTH_PROVIDERS']['apple'] = provider
    return provider
```

### src_back/tests/test_oauth_providers.py — Apple's provider, secret, and identity

Replace the whole file with this. The Google tests are unchanged except that `_identity`
passes `{}` as the fourth argument.

```python
import json
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from joserfc import jwt
from joserfc.jwk import ECKey, RSAKey

from src_back.services.errors import OAuthError
from src_back.services.oauth_providers import (
    APPLE_AUTHORIZE_URL,
    APPLE_ISSUER,
    APPLE_JWKS_URI,
    APPLE_KEYS,
    APPLE_TOKEN_URL,
    APPLE_USER_FIELD_LIMIT,
    OAuthIdentity,
    OAuthProvider,
    apple_client_secret,
    apple_display_name,
    build_registry,
    id_token_claims,
    load_private_key,
    redirect_uri,
)
from src_back.tests.conftest import (
    APPLE_CLIENT_ID,
    APPLE_ENVIRONMENT,
    APPLE_ID_TOKEN_CLAIMS,
    APPLE_KEY_ID,
    APPLE_PRIVATE_KEY,
    APPLE_TEAM_ID,
    OAUTH_CLIENT_ID,
    OAUTH_ENVIRONMENT,
    PUBLIC_BASE_URL,
    OidcSigner,
)

NONCE = 'the-nonce'
APPLE_PEM = APPLE_ENVIRONMENT['OAUTH_APPLE_PRIVATE_KEY']
# Only the public half checks a secret, as at Apple.
APPLE_PUBLIC_KEY = ECKey.import_key(APPLE_PRIVATE_KEY.as_dict(private=False))
# Apple's first answer names the person; its email is not the token's.
FIRST_ANSWER = json.dumps(
    {
        'name': {'firstName': 'Maria', 'lastName': 'Ruiz'},
        'email': 'someone.else@example.com',
    }
)


def _google() -> OAuthProvider:
    return build_registry(OAUTH_ENVIRONMENT, PUBLIC_BASE_URL)['google']


def _identity(signer: OidcSigner, claims: dict[str, Any]) -> OAuthIdentity:
    provider = _google()
    tokens = {'id_token': signer.make_id_token({'nonce': NONCE, **claims})}
    return provider.fetch_identity(provider, tokens, NONCE, {})


def _apple() -> OAuthProvider:
    return build_registry(APPLE_ENVIRONMENT, PUBLIC_BASE_URL)['apple']


def _apple_identity(
    signer: OidcSigner, claims: dict[str, Any], params: dict[str, str]
) -> OAuthIdentity:
    provider = _apple()
    token = signer.make_id_token({**APPLE_ID_TOKEN_CLAIMS, 'nonce': NONCE, **claims})
    return provider.fetch_identity(provider, {'id_token': token}, NONCE, params)


def _pem(
    key: ECKey | RSAKey, *, private: bool = True, password: str | None = None
) -> str:
    return key.as_pem(private=private, password=password).decode()


def _decoded_secret(secret: str) -> jwt.Token:
    return jwt.decode(secret, APPLE_PUBLIC_KEY, algorithms=['ES256'])


def _user_field(name: object) -> str:
    return json.dumps({'name': name})


UNUSABLE_KEYS = {
    'not-a-key': 'not a key',
    'truncated': APPLE_PEM[:80],
    'rsa': _pem(RSAKey.generate_key(2048)),
    'p-384': _pem(ECKey.generate_key('P-384')),
    # A curve joserfc has no name for, on which signing raises KeyError.
    'p-224': _pem(ECKey.import_key(ec.generate_private_key(ec.SECP224R1()))),
    'public-only': _pem(APPLE_PRIVATE_KEY, private=False),
    'encrypted': _pem(APPLE_PRIVATE_KEY, password='a passphrase'),
}


def test_google_is_enabled_with_both_keys() -> None:
    registry = build_registry(OAUTH_ENVIRONMENT, PUBLIC_BASE_URL)
    assert list(registry) == ['google']
    google = registry['google']
    assert google.label == 'Google'
    assert google.client_id == OAUTH_CLIENT_ID
    assert google.client_secret() == 'test-client-secret'


@pytest.mark.parametrize(
    'env',
    [
        {'OAUTH_GOOGLE_CLIENT_SECRET': 'test-client-secret'},
        {'OAUTH_GOOGLE_CLIENT_ID': OAUTH_CLIENT_ID},
        {**OAUTH_ENVIRONMENT, 'OAUTH_GOOGLE_CLIENT_ID': ''},
        {**OAUTH_ENVIRONMENT, 'OAUTH_GOOGLE_CLIENT_SECRET': ''},
    ],
    ids=['no-client-id', 'no-client-secret', 'blank-client-id', 'blank-client-secret'],
)
def test_google_stays_off_without_a_key(env: dict[str, str]) -> None:
    assert build_registry(env, PUBLIC_BASE_URL) == {}


@pytest.mark.parametrize('public_base_url', [None, ''])
def test_nothing_is_enabled_without_a_public_origin(public_base_url: str | None) -> None:
    assert build_registry(OAUTH_ENVIRONMENT, public_base_url) == {}


def test_redirect_uri() -> None:
    assert (
        redirect_uri('https://app.test', 'google')
        == 'https://app.test/api/v1/auth/oauth/google/callback'
    )


def test_google_provider_asks_for_pkce_and_the_account_chooser() -> None:
    google = _google()
    assert google.uses_pkce is True
    assert google.scopes == ('openid', 'email', 'profile')
    assert google.extra_authorize_params == {'prompt': 'select_account'}


def test_google_identity_reads_the_claims(oidc_signer: OidcSigner) -> None:
    identity = _identity(
        oidc_signer,
        {'email': 'person@example.com', 'email_verified': True, 'name': 'A Person'},
    )
    assert identity == OAuthIdentity(
        provider='google',
        subject='google-subject',
        email='person@example.com',
        email_verified=True,
        display_name='A Person',
    )


@pytest.mark.parametrize(
    ('claims', 'verified'),
    [
        ({'email_verified': True}, True),
        ({'email_verified': 'true'}, True),
        ({'email_verified': False}, False),
        ({'email_verified': 'false'}, False),
        ({'email_verified': 1}, False),
        ({'email_verified': 'TRUE'}, False),
        ({}, False),
    ],
    ids=['true', 'text-true', 'false', 'text-false', 'one', 'upper-case', 'missing'],
)
def test_email_verified(
    oidc_signer: OidcSigner, claims: dict[str, Any], *, verified: bool
) -> None:
    claims = {'email': 'person@example.com', **claims}
    assert _identity(oidc_signer, claims).email_verified is verified


@pytest.mark.parametrize('tokens', [{}, {'id_token': 42}], ids=['missing', 'not-text'])
def test_a_token_response_without_an_id_token_is_invalid(tokens: dict[str, Any]) -> None:
    with pytest.raises(OAuthError) as excinfo:
        id_token_claims(_google(), tokens, NONCE)
    assert excinfo.value.code == 'invalid_token'


# Sign in with Apple: the registry


def test_apple_is_enabled_with_its_four_keys_over_https(
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = {**OAUTH_ENVIRONMENT, **APPLE_ENVIRONMENT}
    registry = build_registry(env, PUBLIC_BASE_URL)
    assert list(registry) == ['google', 'apple']
    apple = registry['apple']
    assert apple.label == 'Apple'
    assert apple.client_id == APPLE_CLIENT_ID
    assert apple.authorize_url == APPLE_AUTHORIZE_URL
    assert apple.token_url == APPLE_TOKEN_URL
    assert apple.issuers == (APPLE_ISSUER,)
    assert apple.jwks_uri == APPLE_JWKS_URI
    assert apple.scopes == ('name', 'email')
    assert apple.uses_pkce is False
    assert apple.extra_authorize_params == {'response_mode': 'form_post'}
    assert caplog.messages == []


def test_apple_stays_off_quietly_without_its_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert list(build_registry(OAUTH_ENVIRONMENT, PUBLIC_BASE_URL)) == ['google']
    assert build_registry(dict.fromkeys(APPLE_KEYS, ''), PUBLIC_BASE_URL) == {}
    assert caplog.messages == []


@pytest.mark.parametrize('missing', APPLE_KEYS)
def test_apple_stays_off_and_warns_without_one_key(
    missing: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert build_registry({**APPLE_ENVIRONMENT, missing: ''}, PUBLIC_BASE_URL) == {}
    assert caplog.messages == [f'Sign in with Apple is off: {missing} not set.']


def test_apple_stays_off_and_warns_over_http(caplog: pytest.LogCaptureFixture) -> None:
    assert build_registry(APPLE_ENVIRONMENT, 'http://localhost:5174') == {}
    (message,) = caplog.messages
    assert message == 'Sign in with Apple is off: PUBLIC_BASE_URL must be https.'


@pytest.mark.parametrize('pem', UNUSABLE_KEYS.values(), ids=list(UNUSABLE_KEYS))
def test_apple_stays_off_and_warns_with_an_unusable_key(
    pem: str, caplog: pytest.LogCaptureFixture
) -> None:
    env = {**APPLE_ENVIRONMENT, 'OAUTH_APPLE_PRIVATE_KEY': pem}
    assert build_registry(env, PUBLIC_BASE_URL) == {}
    (message,) = caplog.messages
    assert message.startswith('Sign in with Apple is off: OAUTH_APPLE_PRIVATE_KEY ')


# Sign in with Apple: the key and the client secret


@pytest.mark.parametrize(
    'value',
    [APPLE_PEM, APPLE_PEM.replace('\n', '\\n'), APPLE_PEM.replace('\n', '\r\n')],
    ids=['line-breaks', 'escaped-line-breaks', 'windows-line-breaks'],
)
def test_load_private_key_reads_the_p8_files_text(value: str) -> None:
    assert load_private_key(value).thumbprint() == APPLE_PRIVATE_KEY.thumbprint()


def test_the_client_secret_is_what_apple_documents() -> None:
    before = int(time.time())
    secret = apple_client_secret(
        team_id=APPLE_TEAM_ID,
        client_id=APPLE_CLIENT_ID,
        key_id=APPLE_KEY_ID,
        private_key=APPLE_PRIVATE_KEY,
    )
    token = _decoded_secret(secret)
    assert token.header == {'alg': 'ES256', 'kid': APPLE_KEY_ID}
    assert token.claims['iss'] == APPLE_TEAM_ID
    assert token.claims['sub'] == APPLE_CLIENT_ID
    assert token.claims['aud'] == 'https://appleid.apple.com'
    assert before <= token.claims['iat'] <= int(time.time())
    assert token.claims['exp'] - token.claims['iat'] == 300


def test_the_provider_signs_for_its_services_id_with_the_teams_key() -> None:
    token = _decoded_secret(_apple().client_secret())
    assert token.header['kid'] == APPLE_KEY_ID
    assert token.claims['iss'] == APPLE_TEAM_ID
    assert token.claims['sub'] == APPLE_CLIENT_ID


def test_each_exchange_mints_its_own_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    apple = _apple()
    monkeypatch.setattr(time, 'time', lambda: 1_800_000_000.5)
    first = _decoded_secret(apple.client_secret()).claims['iat']
    monkeypatch.setattr(time, 'time', lambda: 1_800_000_600.5)
    second = _decoded_secret(apple.client_secret()).claims['iat']
    assert (first, second) == (1_800_000_000, 1_800_000_600)


# Sign in with Apple: the identity and the name


def test_apple_identity_reads_the_token_and_the_first_answers_name(
    apple_signer: OidcSigner,
) -> None:
    claims = {'email': 'maria@privaterelay.appleid.com', 'email_verified': 'true'}
    identity = _apple_identity(apple_signer, claims, {'user': FIRST_ANSWER})
    # The user field is unsigned, so its email is ignored; the token's decides.
    assert identity == OAuthIdentity(
        provider='apple',
        subject='apple-subject',
        email='maria@privaterelay.appleid.com',
        email_verified=True,
        display_name='Maria Ruiz',
    )


def test_a_returning_apple_sign_in_carries_no_name(apple_signer: OidcSigner) -> None:
    claims = {'email': 'maria@example.com', 'email_verified': True}
    assert _apple_identity(apple_signer, claims, {}).display_name is None


@pytest.mark.parametrize(
    ('value', 'verified'),
    [(True, True), ('true', True), (False, False), ('false', False)],
    ids=['true', 'text-true', 'false', 'text-false'],
)
def test_apples_email_verified_is_text_or_a_boolean(
    apple_signer: OidcSigner, value: object, *, verified: bool
) -> None:
    claims = {'email': 'maria@example.com', 'email_verified': value}
    assert _apple_identity(apple_signer, claims, {}).email_verified is verified


def test_an_empty_apple_email_is_none(apple_signer: OidcSigner) -> None:
    claims = {'email': '', 'email_verified': 'false'}
    assert _apple_identity(apple_signer, claims, {}).email is None


@pytest.mark.parametrize(
    ('field', 'name'),
    [
        (_user_field({'firstName': 'Maria', 'lastName': 'Ruiz'}), 'Maria Ruiz'),
        (_user_field({'firstName': 'Maria'}), 'Maria'),
        (_user_field({'lastName': 'Ruiz'}), 'Ruiz'),
        (_user_field({'firstName': ' Maria ', 'lastName': '  '}), 'Maria'),
        (None, None),
        ('', None),
        ('not json', None),
        ('[]', None),
        (json.dumps({'email': 'maria@example.com'}), None),
        (_user_field('Maria Ruiz'), None),
        (_user_field({'firstName': 5, 'lastName': None}), None),
    ],
    ids=[
        'both',
        'given-only',
        'family-only',
        'padded',
        'missing',
        'empty',
        'not-json',
        'not-an-object',
        'no-name',
        'name-not-an-object',
        'parts-not-text',
    ],
)
def test_apple_display_name(field: str | None, name: str | None) -> None:
    assert apple_display_name(field) == name


def test_an_apple_name_keeps_only_what_a_database_can_store() -> None:
    # NUL, which PostgreSQL refuses, a tab, and a lone surrogate, which no driver can
    # encode, are dropped; a zero-width joiner, which some scripts need, stays.
    joiner = chr(0x200D)
    given = 'Ma' + chr(0) + 'ria' + joiner
    family = 'Ru' + chr(9) + 'iz' + chr(0xD800)
    field = _user_field({'firstName': given, 'lastName': family})
    assert apple_display_name(field) == 'Maria' + joiner + ' Ruiz'
    assert apple_display_name(_user_field({'firstName': chr(0)})) is None


def test_a_user_field_past_the_limit_is_not_read() -> None:
    padding = APPLE_USER_FIELD_LIMIT - len(_user_field({'firstName': ''}))
    longest = _user_field({'firstName': 'M' * padding})
    assert len(longest) == APPLE_USER_FIELD_LIMIT
    assert apple_display_name(longest) == 'M' * padding
    assert apple_display_name(_user_field({'firstName': 'M' * (padding + 1)})) is None
    # Nesting this deep fits the 25 MB request limit and makes json.loads raise.
    assert apple_display_name('[' * 100_000 + ']' * 100_000) is None
    # The deepest nesting the cap lets through; Python 3.12.0 to 3.12.2 refuse it.
    assert apple_display_name('[' * 2048 + ']' * 2048) is None
```

### src_back/tests/test_oauth.py — Apple's authorize URL

Add `APPLE_AUTHORIZE_URL` to the `oauth_providers` import, and change the `conftest`
import (line 29) to:

```python
from src_back.tests.conftest import (
    APPLE_CLIENT_ID,
    APPLE_ENVIRONMENT,
    OAUTH_CLIENT_ID,
    OAUTH_ENVIRONMENT,
    PUBLIC_BASE_URL,
)
```

After `REDIRECT_URI` (line 32), add:

```python
APPLE_REDIRECT_URI = f'{PUBLIC_BASE_URL}/api/v1/auth/oauth/apple/callback'
```

After `test_authorize_url_omits_pkce_without_a_verifier`, add:

```python
def test_apples_authorize_url_asks_for_a_form_post_without_pkce() -> None:
    apple = build_registry(APPLE_ENVIRONMENT, PUBLIC_BASE_URL)['apple']
    txn = new_transaction('apple', uses_pkce=False, next_path='/', link_user_id=None)
    url = urlsplit(build_authorize_url(apple, redirect_uri=APPLE_REDIRECT_URI, txn=txn))
    assert f'{url.scheme}://{url.netloc}{url.path}' == APPLE_AUTHORIZE_URL
    assert dict(parse_qsl(url.query)) == {
        'client_id': APPLE_CLIENT_ID,
        'redirect_uri': APPLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'name email',
        'state': txn.state,
        'nonce': txn.nonce,
        'response_mode': 'form_post',
    }
```

### src_back/tests/test_oauth_api.py — Apple end to end

Add `import json` after `import dataclasses`, and `from joserfc import jwt` and `from
joserfc.jwk import ECKey` after the `flask_sqlalchemy` import. Change the
`oauth_providers` import (line 17) and the `conftest` import (line 25) to:

```python
from src_back.services.oauth_providers import (
    APPLE_TOKEN_URL,
    GOOGLE_TOKEN_URL,
    OAuthProvider,
)
```

```python
from src_back.tests.conftest import (
    APPLE_CLIENT_ID,
    APPLE_ID_TOKEN_CLAIMS,
    APPLE_PRIVATE_KEY,
    OAUTH_CLIENT_ID,
    OidcSigner,
)
```

After `VERIFIED` (line 40), add:

```python
APPLE_CALLBACK_URL = f'{OAUTH_URL}/apple/callback'
APPLE_EMAIL = 'maria@privaterelay.appleid.com'
APPLE_VERIFIED: dict[str, Any] = {'email': APPLE_EMAIL, 'email_verified': 'true'}
# Apple's first answer names the person. Its email differs from the token's on purpose:
# the field is unsigned, so the account takes the token's.
FIRST_ANSWER = json.dumps(
    {'name': {'firstName': 'Maria', 'lastName': 'Ruiz'}, 'email': 'other@example.com'}
)
```

Replace `begin` (lines 43-48) with this; `START_URL` stays, since eight tests use it:

```python
def begin(
    client: FlaskClient,
    *,
    provider: str = 'google',
    headers: dict[str, str] | None = None,
    **query: str,
) -> dict[str, str]:
    response = client.get(
        f'{OAUTH_URL}/{provider}/start', query_string=query, headers=headers or {}
    )
    assert response.status_code == 302
    return dict(parse_qsl(urlsplit(response.headers['Location']).query))
```

After `finish_link` (line 95), add:

```python
def answer_apple_token_request(
    mocked_http: responses.RequestsMock, signer: OidcSigner, nonce: str
) -> None:
    claims = {**APPLE_ID_TOKEN_CLAIMS, **APPLE_VERIFIED, 'nonce': nonce}
    id_token = signer.make_id_token(claims)
    mocked_http.add(
        responses.POST,
        APPLE_TOKEN_URL,
        json={'access_token': 'the-access-token', 'id_token': id_token},
    )


def post_apple_answer(client: FlaskClient, form: dict[str, str]) -> TestResponse:
    # Apple's answer is a form another site posts, so it carries no X-Requested-With.
    client.environ_base.pop('HTTP_X_REQUESTED_WITH', None)
    return client.post(APPLE_CALLBACK_URL, data=form)


def sign_in_with_apple(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    signer: OidcSigner,
    **fields: str,
) -> TestResponse:
    params = begin(client, provider='apple')
    answer_apple_token_request(mocked_http, signer, params['nonce'])
    form = {'code': 'the-code', 'state': params['state'], **fields}
    return post_apple_answer(client, form)
```

Replace `token_request_body` (lines 115-121) with:

```python
def token_request_body(
    mocked_http: responses.RequestsMock, url: str = GOOGLE_TOKEN_URL
) -> dict[str, str]:
    call = next(call for call in mocked_http.calls if call.request.url == url)
    body = call.request.body
    assert isinstance(body, str)
    return dict(parse_qsl(body))
```

At the end of the file, add:

```python
# Sign in with Apple


def test_providers_lists_apple_after_google(
    client: FlaskClient, apple: OAuthProvider
) -> None:
    assert client.get(f'{OAUTH_URL}/providers').get_json() == [
        {'name': 'google', 'label': 'Google'},
        {'name': 'apple', 'label': 'Apple'},
    ]


def test_apples_start_asks_for_a_form_post_and_keeps_no_verifier(
    app: Flask, client: FlaskClient, apple: OAuthProvider
) -> None:
    params = begin(client, provider='apple')
    assert params['response_mode'] == 'form_post'
    assert params['client_id'] == APPLE_CLIENT_ID
    assert 'code_challenge' not in params
    assert transaction_in(app, client).code_verifier is None


def test_a_first_apple_sign_in_makes_an_account_named_from_the_answer(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    apple_signer: OidcSigner,
    apple: OAuthProvider,
) -> None:
    response = sign_in_with_apple(client, mocked_http, apple_signer, user=FIRST_ANSWER)
    assert redirect_location(response) == f'{ORIGIN}/'
    assert not has_transaction_cookie(client)
    assert me_from_the_session_cookie(client).get_json()['email'] == APPLE_EMAIL
    db.session.rollback()
    link = db.session.query(OAuthAccount).one()
    assert (link.provider, link.provider_user_id) == ('apple', 'apple-subject')
    assert (link.email, link.display_name) == (APPLE_EMAIL, 'Maria Ruiz')
    assert link.user.email == APPLE_EMAIL


def test_apples_token_request_carries_a_secret_minted_for_it(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    apple_signer: OidcSigner,
    apple: OAuthProvider,
) -> None:
    sign_in_with_apple(client, mocked_http, apple_signer)
    body = token_request_body(mocked_http, APPLE_TOKEN_URL)
    assert body['client_id'] == APPLE_CLIENT_ID
    assert body['redirect_uri'] == f'{ORIGIN}/api/v1/auth/oauth/apple/callback'
    assert 'code_verifier' not in body
    public_key = ECKey.import_key(APPLE_PRIVATE_KEY.as_dict(private=False))
    claims = jwt.decode(body['client_secret'], public_key, algorithms=['ES256']).claims
    assert claims['sub'] == APPLE_CLIENT_ID
    assert claims['exp'] - claims['iat'] == 300


def test_a_returning_apple_sign_in_keeps_the_first_name(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    apple_signer: OidcSigner,
    apple: OAuthProvider,
) -> None:
    sign_in_with_apple(client, mocked_http, apple_signer, user=FIRST_ANSWER)
    response = sign_in_with_apple(client, mocked_http, apple_signer)
    assert redirect_location(response) == f'{ORIGIN}/'
    assert me_from_the_session_cookie(client).get_json()['email'] == APPLE_EMAIL
    db.session.rollback()
    assert db.session.query(User).count() == 1
    assert db.session.query(OAuthAccount).one().display_name == 'Maria Ruiz'


def test_a_cancelled_apple_sign_in_is_cancelled(
    client: FlaskClient, mocked_http: responses.RequestsMock, apple: OAuthProvider
) -> None:
    params = begin(client, provider='apple')
    form = {'error': 'user_cancelled_authorize', 'state': params['state']}
    response = post_apple_answer(client, form)
    assert redirect_location(response) == f'{ORIGIN}/login?error=cancelled'
    assert not has_transaction_cookie(client)
    assert len(mocked_http.calls) == 0


def test_an_apple_name_a_database_cannot_store_is_cleaned(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    apple_signer: OidcSigner,
    apple: OAuthProvider,
) -> None:
    # SQLite cannot encode the surrogate and PostgreSQL refuses the NUL, so either one
    # reaching the database would fail the callback.
    name = {'firstName': 'Ma' + chr(0) + 'ria', 'lastName': 'Ruiz' + chr(0xD800)}
    field = json.dumps({'name': name})
    response = sign_in_with_apple(client, mocked_http, apple_signer, user=field)
    assert redirect_location(response) == f'{ORIGIN}/'
    db.session.rollback()
    assert db.session.query(OAuthAccount).one().display_name == 'Maria Ruiz'


def test_linking_apple_from_the_account_page_keeps_the_name(
    auth_client: FlaskClient,
    user: User,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    apple_signer: OidcSigner,
    apple: OAuthProvider,
) -> None:
    params = begin(auth_client, provider='apple', headers=SAME_ORIGIN, link='1')
    answer_apple_token_request(mocked_http, apple_signer, params['nonce'])
    form = {'code': 'the-code', 'state': params['state'], 'user': FIRST_ANSWER}
    response = post_apple_answer(auth_client, form)
    assert redirect_location(response) == f'{ORIGIN}/account'
    db.session.rollback()
    link = db.session.query(OAuthAccount).one()
    assert (link.user_id, link.provider) == (user.id, 'apple')
    assert link.display_name == 'Maria Ruiz'
```

### Frontend tests — Apple as a second provider

`src_front/src/test/utils/fixtures.ts`, after `googleProvider` (line 35):

```ts
/** Apple, as the providers route lists it once its four keys are set over https. */
export const appleProvider: OAuthProviderInfo = { name: 'apple', label: 'Apple' }
```

`src_front/src/test/components/auth/ProviderButtons.test.tsx`: change line 8 to `import
{ appleProvider, googleProvider } from '../../utils/fixtures'`, and add after the first
test (line 29). No test rendered two providers, so a component that drew only the first
passed.

```tsx
    it('links every enabled provider, in the order the server lists them', async () => {
        vi.mocked(listProviders).mockResolvedValue([googleProvider, appleProvider])

        render(<ProviderButtons next="/" />)

        const apple = await screen.findByRole('link', { name: 'Continue with Apple' })
        expect(apple).toHaveAttribute('href', '/api/v1/auth/oauth/apple/start?next=%2F')
        expect(screen.getAllByRole('link').map((link) => link.textContent)).toEqual([
            'Continue with Google',
            'Continue with Apple',
        ])
    })
```

`src_front/src/test/components/account/LinkedAccounts.test.tsx`: delete the
`OAuthProviderInfo` import (line 9) and the local `appleProvider` with its comment and
the blank line after it (lines 19-21), and change line 12 to `import { appleProvider,
googleProvider, linkedGoogleAccount } from '../../utils/fixtures'`.

### .env.example, .env.staging.example, the Compose files, and provisioning

In `.env.example`, replace the sign-in block (lines 53-58) with:

```text
# --- Sign-in providers (ai/auth.md) ---------------------------------------------
# A provider appears on the sign-in pages once all of its keys are set. Register
# PUBLIC_BASE_URL + /api/v1/auth/oauth/<provider>/callback with the provider, once per
# environment and dev port; here, http://localhost:5174/api/v1/auth/oauth/google/callback.
OAUTH_GOOGLE_CLIENT_ID=
OAUTH_GOOGLE_CLIENT_SECRET=
# Apple accepts only an https PUBLIC_BASE_URL on a real domain, so it stays off in
# development. The client id is the Services ID, and the private key is the .p8 file's
# text on one line, in double quotes, with \n between its lines (ai/auth.md).
OAUTH_APPLE_CLIENT_ID=
OAUTH_APPLE_TEAM_ID=
OAUTH_APPLE_KEY_ID=
OAUTH_APPLE_PRIVATE_KEY=
```

In `.env.staging.example`, change lines 2-3 to end "fill in every blank but SMTP_HOST,
OAUTH_GOOGLE_*, and OAUTH_APPLE_*.", rewrapped within 90 columns, and replace the
sign-in block (lines 52-56) with:

```text
# --- Sign-in providers (ai/auth.md) ---------------------------------------------
# Optional. Blank keeps each provider off here. To try one, register
# https://<DOMAIN>/api/v1/auth/oauth/<provider>/callback with it: with the Google
# client, or as a return URL on the Services ID beside production's.
OAUTH_GOOGLE_CLIENT_ID=
OAUTH_GOOGLE_CLIENT_SECRET=
OAUTH_APPLE_CLIENT_ID=
OAUTH_APPLE_TEAM_ID=
OAUTH_APPLE_KEY_ID=
OAUTH_APPLE_PRIVATE_KEY=
```

In both `docker-compose.yml` (after line 46) and `docker/docker-compose.prod.yml` (after
line 36), under the backend's `environment:`, add:

```text
      OAUTH_APPLE_CLIENT_ID: ${OAUTH_APPLE_CLIENT_ID:-}
      OAUTH_APPLE_TEAM_ID: ${OAUTH_APPLE_TEAM_ID:-}
      OAUTH_APPLE_KEY_ID: ${OAUTH_APPLE_KEY_ID:-}
      OAUTH_APPLE_PRIVATE_KEY: ${OAUTH_APPLE_PRIVATE_KEY:-}
```

In `scripts/provision.sh`, after `OAUTH_GOOGLE_CLIENT_SECRET=` (line 128), add the lines
below. The heredoc is unquoted, so `$DOMAIN` expands as in Google's comment; keep any
backtick or other `$` out.

```text
# Apple appears once all four of its keys are set. Add
# https://$DOMAIN/api/v1/auth/oauth/apple/callback to its Services ID's return URLs;
# the key is the .p8 file's text on one line (ai/auth.md, "Setting up Apple").
OAUTH_APPLE_CLIENT_ID=
OAUTH_APPLE_TEAM_ID=
OAUTH_APPLE_KEY_ID=
OAUTH_APPLE_PRIVATE_KEY=
```

After the `echo` about Google (line 165), add:

```bash
  echo "    Sign in with Apple stays off until all four OAUTH_APPLE_* are filled in."
```

### .gitignore and .dockerignore — the key file

Append to `.gitignore`:

```text

# Sign in with Apple's private key; its text goes in .env (ai/auth.md)
*.p8
```

Append to `.dockerignore`, where patterns match from the context root:

```text
**/*.p8
```

### scripts/tests — the three tests

`scripts/tests/test-compose-config.sh`: in the header comment (lines 5-6), name
`OAUTH_APPLE_*` beside `OAUTH_GOOGLE_*`, and add "and Apple's private key, from a
one-line value in the env file itself, with its line breaks" to what both stacks pass,
rewrapped within 90 columns. Add `OAUTH_APPLE_CLIENT_ID OAUTH_APPLE_TEAM_ID
OAUTH_APPLE_KEY_ID OAUTH_APPLE_PRIVATE_KEY` to the `unset` list (lines 26-28). Replace
the OAuth block (lines 57-62) with:

```bash
(
  export OAUTH_GOOGLE_CLIENT_ID=google-id OAUTH_GOOGLE_CLIENT_SECRET=google-secret \
    OAUTH_APPLE_CLIENT_ID=com.example.web OAUTH_APPLE_TEAM_ID=TEAMID1234 \
    OAUTH_APPLE_KEY_ID=KEYID12345 OAUTH_APPLE_PRIVATE_KEY=apple-key
  render > "$TEST_DIR/dev-oauth.json"
  render -f docker-compose.yml -f docker/docker-compose.prod.yml \
    > "$TEST_DIR/prod-oauth.json"
)
# Compose reads this value from the env file, not the shell: one double-quoted line
# whose \n escapes it turns into line breaks. printf's %s keeps the backslashes.
pem='-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n'
printf 'OAUTH_APPLE_PRIVATE_KEY="%s"\n' "$pem" > "$TEST_DIR/key.env"
render_key() {
  docker compose --env-file "$TEST_DIR/key.env" "$@" config --format json
}
render_key > "$TEST_DIR/dev-key.json"
render_key -f docker-compose.yml -f docker/docker-compose.prod.yml \
  > "$TEST_DIR/prod-key.json"
```

Inside the `for stack in dev prod` loop (after line 144), add:

```bash
  check "$stack" '.services.backend.environment | [.OAUTH_APPLE_CLIENT_ID,
    .OAUTH_APPLE_TEAM_ID, .OAUTH_APPLE_KEY_ID, .OAUTH_APPLE_PRIVATE_KEY]
    | all(. == "")' \
    'blank OAUTH_APPLE_* variables, which leave Sign in with Apple off'
  check "$stack-oauth" '.services.backend.environment
    | .OAUTH_APPLE_CLIENT_ID == "com.example.web"
    and .OAUTH_APPLE_TEAM_ID == "TEAMID1234" and .OAUTH_APPLE_KEY_ID == "KEYID12345"
    and .OAUTH_APPLE_PRIVATE_KEY == "apple-key"' \
    'the OAUTH_APPLE_* variables its .env gives passed through to the backend'
  check "$stack-key" '.services.backend.environment.OAUTH_APPLE_PRIVATE_KEY
    == "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"' \
    'a one-line private key from its env file, with its line breaks'
```

`scripts/tests/test-provision.sh`, after line 160:

```bash
assert_contains '^OAUTH_APPLE_CLIENT_ID=$' "$ENV_FILE"
assert_contains '^OAUTH_APPLE_TEAM_ID=$' "$ENV_FILE"
assert_contains '^OAUTH_APPLE_KEY_ID=$' "$ENV_FILE"
assert_contains '^OAUTH_APPLE_PRIVATE_KEY=$' "$ENV_FILE"
assert_contains '^# https://example\.com/api/v1/auth/oauth/apple/callback ' "$ENV_FILE"
```

`scripts/tests/test-deploy.sh`, after line 136:

```bash
assert_contains '^OAUTH_APPLE_CLIENT_ID=$' "$STAGING_EXAMPLE"
assert_contains '^OAUTH_APPLE_TEAM_ID=$' "$STAGING_EXAMPLE"
assert_contains '^OAUTH_APPLE_KEY_ID=$' "$STAGING_EXAMPLE"
assert_contains '^OAUTH_APPLE_PRIVATE_KEY=$' "$STAGING_EXAMPLE"
```

### ai/auth.md — Setting up Apple, and the wording that said "will"

Replace each passage below with the text that follows it; each fits 90 columns and
passes markdownlint and Prettier in place. On line 7, "Sign in with Apple (#30) and
Facebook (#31)" becomes "Google, Sign in with Apple, and Facebook (#31)", and on line 33
"as Sign in with Apple's `form_post` will (#30)" becomes "as Sign in with Apple's
`form_post` does"; both still fit.

Lines 45-50, the "Sign-in providers" opening:

```text
A `Continue with <provider>` button runs the OAuth 2.0 and OpenID Connect
authorization-code flow on the backend. No token reaches the browser and none is stored. A
provider is enabled when its keys are set and `PUBLIC_BASE_URL` is known, and Apple only
when that is https; with none enabled, `/providers` answers `[]` and the sign-in pages
show only the password form. Google and Apple are the providers so far. A new one is one
`OAuthProvider` and one identity function in `src_back/services/oauth_providers.py`. Its
identity function receives the callback's parameters as well as the token response, which
is how Apple's first answer delivers the person's name.
```

Lines 64-65, the end of step 2:

```text
   `next` defaults to `/`. It stores a transaction in the cookie below and redirects to
   the provider with `state`, `nonce`, and a PKCE challenge for a provider that supports
   one; Apple documents none.
```

Lines 66-68, step 3:

```text
3. The provider sends the browser back to `callback`, by GET, or by POST for Sign in with
   Apple. The callback trusts only the cookie: it compares `state`, exchanges the code,
   checks the ID token, resolves the account, and calls `complete_login`.
```

Lines 87-88, after the table:

```text
A failed token exchange or key fetch logs a warning; a wrong client secret shows up there
and nowhere else. OAuth's `access_denied` and Apple's `user_cancelled_authorize` both read
as `cancelled`.
```

Lines 146-147, the end of the linking policy's paragraph:

```text
rule 5, an account one provider created answers `link_required` to another provider's
sign-in until its owner links that provider from the Account page.
```

Lines 308-312, the first throttling bullet:

```text
- Every POST under `/api/v1/auth/` shares the budget, including a passkey's answers to
  `/passkeys/login/verify` and `/passkeys/register/verify`, and Sign in with Apple's
  callback, a POST, so an Apple sign-in costs one. The passkey options are GETs, so the
  sign-in page's autofill, which asks for them on every visit and every four minutes
  after, spends nothing. A passkey sign-in costs one POST, as a password sign-in does.
```

Then add this section after "Setting up Google" (after line 179), keeping the reference
definitions at its end:

````markdown
### Setting up Apple

Sign in with Apple needs a membership in the Apple Developer Program, and Apple accepts
a return URL only on a domain, never `localhost` or an IP address, over https. So
`build_registry()` leaves Apple off unless all four keys are set and `PUBLIC_BASE_URL`
is https, and once `PUBLIC_BASE_URL` is set it logs a warning when some keys are set and
Apple stays off anyway. Try it on staging (`ai/staging.md`). From a laptop it takes a
tunnel's https host name, registered with Apple, in front of a stack that accepts it:
the production stack run from an env file of its own, since the dev `.env` cannot start
it, or the dev stack once Vite's `server.allowedHosts` lists the host name.

1. In Certificates, Identifiers & Profiles, enable Sign in with Apple on an App ID,
   which becomes the primary App ID for the site. A site without an app still needs one.
2. Create a Services ID. Its identifier, such as `com.example.web`, is
   `OAUTH_APPLE_CLIENT_ID`. Enable Sign in with Apple on it, choose the primary App ID,
   and under Website URLs list each environment's domain and its return URL,
   `PUBLIC_BASE_URL + /api/v1/auth/oauth/apple/callback`, so that one Services ID serves
   production and staging. Apple asks for no verification file, and an individual
   membership can register 10 website URLs, an organization 100 ([Apple][apple-web]).
3. Create a key with Sign in with Apple enabled for the primary App ID. Its Key ID is
   `OAUTH_APPLE_KEY_ID`, and its `.p8` file downloads only once. The Team ID shown in
   the membership details is `OAUTH_APPLE_TEAM_ID`.
4. Put the `.p8` file's text in `OAUTH_APPLE_PRIVATE_KEY` on one line, in double
   quotes, with `\n` between its lines. These commands print that line, to paste over
   the blank one in the server's `.env`:

    ```bash
    key=$(awk 'NF { printf "%s\\n", $0 }' AuthKey_ABC123DEFG.p8)
    printf 'OAUTH_APPLE_PRIVATE_KEY="%s"\n' "$key"
    ```

5. Run `npm run deploy`, or `npm run deploy:staging` on staging, because Compose hands a
   container its values only when it creates one. Then check the backend's log for a
   warning that begins `Sign in with Apple is off`. Keep the `.p8` outside the
   repository; `.gitignore` and `.dockerignore` refuse `*.p8` files as a backstop.

Things to know about Apple:

- Apple sends the person's name only with their first authorization of the site, in
  the `user` field of its POST, and the link keeps it in `oauth_accounts.display_name`;
  nothing shows it yet. If that first sign-in fails, as `link_required` does, the name
  is lost until the person stops using Sign in with Apple for the site in their Apple
  Account settings and authorizes it again. The field is unsigned, so only the name is
  read from it, and the email always comes from the ID token.
- Someone who hides their email signs in with a relay address under
  `privaterelay.appleid.com`, which matches no account here, so their first sign-in
  creates a new account instead of answering `link_required`. Someone who already has
  an account should sign in to it and link Apple from the Account page.
- Mail to a relay address bounces until the sending domain or address is registered
  under Sign in with Apple for Email Communication, with SPF or DKIM passing
  ([Apple][apple-relay]). Nothing in the template mails an account yet.
- Each token exchange mints its own client secret, good for five minutes, so the
  server's clock must be right; Ubuntu keeps it synchronized by default, with chrony
  since 25.10 and `systemd-timesyncd` before. A wrong Team ID or Key ID shows up only as
  `exchange_failed`, with a 400 from Apple's token endpoint in the backend's log; a wrong
  client id, or a return URL missing from the Services ID, stops on Apple's own page.
- Apple documents no PKCE, so the nonce is what ties Apple's ID token to the browser
  that started the sign-in, and a token without one is refused ([RFC 9700][rfc9700],
  section 4.5.3.2).
- Unlinking Apple here does not revoke the site at Apple, which the person does in
  their Apple Account settings, and Apple's server-to-server notifications, such as a
  relay address's forwarding being turned off, are not received.

[apple-web]: https://developer.apple.com/help/account/configure-app-capabilities/configure-sign-in-with-apple-for-the-web
[apple-relay]: https://developer.apple.com/help/account/configure-app-capabilities/configure-private-email-relay-service/
[rfc9700]: https://www.rfc-editor.org/rfc/rfc9700#section-4.5.3.2
````

### ai/project.md, ai/domain.md, ai/staging.md, ai/conventions.md, and tools.md

`ai/project.md`, lines 167-171, becomes:

```text
Sign-in providers are off until their keys are set: `build_registry()` in
`src_back/services/oauth_providers.py` enables Google when `OAUTH_GOOGLE_CLIENT_ID` and
`OAUTH_GOOGLE_CLIENT_SECRET` are both set and `PUBLIC_BASE_URL` is known, and Sign in
with Apple when all four `OAUTH_APPLE_*` keys are set and `PUBLIC_BASE_URL` is https,
warning, once `PUBLIC_BASE_URL` is set, when any `OAUTH_APPLE_*` key is set but Apple
stays off. A server provisioned before these keys has no such lines, which leaves the
provider off. `ai/auth.md` has the setup steps.
```

and lines 177-178 become:

```text
variables, and the `OAUTH_GOOGLE_*` and `OAUTH_APPLE_*` keys for every test, so no test
sends mail or reaches a provider through a developer's account.
```

`ai/domain.md`: after the `oidc_signer` bullet (line 58), add two bullets, and change the
`_clear_oauth_environment` bullet (lines 63-64) to name "the `OAUTH_GOOGLE_*` and
`OAUTH_APPLE_*` keys":

```text
- `apple_signer` - `oidc_signer`, also serving its key at Apple's JWKS URL;
  `APPLE_ID_TOKEN_CLAIMS` makes a token it signs Apple's
- `apple` - adds Sign in with Apple to the `app` fixture's registry, built from
  `APPLE_ENVIRONMENT` with a P-256 key made once per run
```

`ai/staging.md`, lines 25-26:

```text
- sign-in providers, which stay off until `OAUTH_GOOGLE_*` or `OAUTH_APPLE_*` is filled
  in, and need staging's own redirect URI registered with the provider, which for Apple is
  one more return URL on the same Services ID;
```

`ai/staging.md`, lines 73-77, setup step 3:

```text
3. Fill in every blank in `.env` except `SMTP_HOST`, which stays blank so staging sends no
   mail, and the optional `OAUTH_GOOGLE_*` and `OAUTH_APPLE_*` keys. Generate each secret
   with `openssl rand -hex 32`, and repeat `POSTGRES_PASSWORD` inside `DATABASE_URL`. Set
   both `CORS_ALLOWED_ORIGINS` and `PUBLIC_BASE_URL` to `https://<DOMAIN>`.
   `PRODUCTION_DIR` must name production's clone, and `STAGING_HTPASSWD` the file the next
   step creates.
```

`ai/conventions.md`, line 96: drop "(#30)", leaving "reaches, is the only one."

`tools.md`, lines 90-94, the joserfc entry:

```text
- **joserfc**: validates a provider's ID token, signature and claims, in
  `src_back/services/oidc.py`. It brings `cryptography`, and also signs Sign in with
  Apple's ES256 client secrets, in `src_back/services/oauth_providers.py`. Authlib, which
  uses it, is not installed: its Flask client keeps state in the session, which the
  provider's redirect cannot read under a `SameSite=Strict` cookie.
```

## Parallelism

Four groups can run at once; each is sequential inside.

- **Group A, backend**: `oauth_providers.py`, then `api/oauth.py`, then `conftest.py`,
  whose imports need the new constants, then the three test files. Run
  `.venv/bin/python -m pytest src_back/tests/test_oauth_providers.py
  src_back/tests/test_oauth.py src_back/tests/test_oauth_api.py
  src_back/tests/test_app.py src_back/tests/test_schemas.py --no-cov` after the batch.
- **Group B, configuration and shell**: the env templates, both Compose files,
  `provision.sh`, the ignore files, then the three shell tests, run as `bash
  scripts/tests/test-compose-config.sh`, `bash scripts/tests/test-provision.sh`, and
  `bash scripts/tests/test-deploy.sh`.
- **Group C, frontend tests**: `fixtures.ts`, then the two test files, run with `npx
  vitest run src_front/src/test/components/auth/ProviderButtons.test.tsx
  src_front/src/test/components/account/LinkedAccounts.test.tsx`.
- **Group D, documentation**: the six documents and the plan's `git mv`. It names
  fixtures and messages from Group A, which this plan fixes, so it need not wait.

### Mutation checks

Each group runs these on a scratch copy of the repository, never the real files, behind
a dead `HTTP_PROXY` and `HTTPS_PROXY` for the backend, and with a timeout on every run.
Each must fail a test; report survivors rather than adding tests this plan does not list.

- `oauth_providers.py`: drop `user_cancelled_authorize`'s handling by removing it from
  `_CANCELLED_ERRORS` in `api/oauth.py`; `uses_pkce=True`; remove `response_mode`; drop
  `default_type=None`; `APPLE_SECRET_SECONDS = 15777000`; `'aud': team_id`; remove the
  trial `mint()`; catch `ValueError` alone; remove `.replace('\\n', '\n')`; remove the
  length cap; `>=` for `>` in the cap; skip `_storable_text`; read `user['email']` for
  the identity's email; drop `or None` on the email; `bool(...)` for `is_true_claim`;
  drop the `if not any(...)` early return; drop the https check; swap `team_id` and
  `key_id` in the `partial`; mint once and return the stored string; list Apple before
  Google.
- `api/oauth.py`: pass `{}` instead of `request.values` to `fetch_identity`.
- `_apple_secret_minter`: narrow `except Exception` to `(JoseError, TypeError,
  ValueError)`, which only the `p-224` case catches.
- Shell: drop an `OAUTH_APPLE_*` line from `docker-compose.yml`, from `provision.sh`,
  from `.env.example`, and from `.env.staging.example`.
- Frontend: render only `providers[0]` in `ProviderLinks`.

Three cannot fail by design: dropping a key from `docker/docker-compose.prod.yml`, which
Compose merges with the base file's identical entry, as #29 found; removing `*.p8` from
either ignore file; and dropping `RecursionError` from `apple_display_name`'s `except`,
which only Python 3.12.0 to 3.12.2 raise within the cap.

## No other changes needed

- Frontend production code: `ProviderButtons`, `SignInOptions`, `LinkedAccounts`, and
  `utils/oauth.ts` draw every provider from `{name, label}`, and Apple adds no `?error=`
  code. `vite.config.ts` and `index.html` need nothing.
- `src_back/services/oauth_state.py`: over https the transaction cookie is
  `__Host-oauth_txn` with `SameSite=None; Secure` (`set_transaction_cookie`), which a
  cross-site POST carries, and `test_start_sets_the_transaction_cookie` pins it.
- `src_back/app.py`: `_CROSS_SITE_POST_ENDPOINTS` already exempts `oauth.callback`, and
  `_configure_oauth_providers` passes the settled `PUBLIC_BASE_URL`.
- `src_back/services/oidc.py`: RS256 is the one algorithm Apple signs with, and the key
  cache is per URL.
- `src_back/services/oauth.py`: `build_authorize_url` adds `response_mode` from
  `extra_authorize_params` and leaves out PKCE without a verifier. `urlencode` writes a
  space as `+`, the form encoding RFC 6749 Appendix B prescribes for these parameters.
  `exchange_code` sends `client_secret_post`, the one method Apple lists.
  `_attach_account` cuts the name to 255.
- Models and migrations: `oauth_accounts.display_name` exists, and `provider`,
  `String(32)`, fits `apple`.
- nginx: Apple's POST callback is under `/api/v1/auth/`, inside the sign-in throttle,
  with `client_max_body_size 25m`.
- `requirements.txt`: `joserfc` and `cryptography`, which it requires, are installed.
- `scripts/deploy.sh`, `copy-production.sh`, and the other scripts read no `OAUTH_*` key,
  and their `get()` helpers read a one-line value whole.
- README: only its layout tree mentions OAuth.
- Branding the buttons, receiving Apple's server-to-server notifications, and revoking
  at unlink: the issue defers the first, now #61, and `ai/auth.md` records the other
  two.

## Added during implementation

Chuck approved these on 2026-11-06, after the groups' mutation checks showed decisions
that no listed test could fail. Each is a test or a sentence; no production code changed.

- `test_oauth_providers.py` gains four guards:
    - `test_apples_endpoints_are_the_ones_its_discovery_document_lists` pins the
      authorize, token, and JWKS URLs and the issuer to Apple's discovery document. The
      other tests import the same constants, so a typo in any of the three URLs passed
      them all.
    - `test_apple_stays_off_quietly_without_its_keys` also builds the registry for an
      http origin with no Apple key. Moving the https check before the check for any key,
      which would warn at every development start against point 7, passed every test.
    - `test_apples_warning_names_every_missing_key` and
      `test_apples_key_warning_names_the_error_class` pin the whole text and the
      `WARNING` level of two warnings: every missing key, in order, and the bad key's
      class, for the `ValueError` and `TypeError` that cryptography documents for
      undecodable data and for an encrypted key. Naming only the first missing key,
      dropping the class, or logging at `ERROR` passed.
    - `test_each_exchange_mints_its_own_secret` freezes the clock at `.9` of a second
      instead of `.5`, where `round()` and `int()` agree, so `iat = round(time.time())`
      fails every run rather than about 42% of them.
- `test-provision.sh` asserts the Apple line `provision.sh` prints, as it asserts
  Google's; deleting the `echo` passed.
- `test-compose-config.sh` checks that `key.env` is one line. With `%b` in place of `%s`,
  `printf` writes real line breaks, Compose reads the same key, and the test no longer
  covered the runbook's one-line form.
- `ai/auth.md`'s laptop route says the tunnel's https host name is also
  `PUBLIC_BASE_URL`, which the text implied but did not say.

Survivors left without a test:

- By design, as the plan says: dropping `RecursionError` from `apple_display_name`'s
  `except`, since Python 3.13.18 raises only at a nesting depth of 9,999 and the cap
  admits 2,048; dropping an Apple key from `docker/docker-compose.prod.yml`; and removing
  `*.p8` from either ignore file. With both the cap and the catch removed, a deeply nested
  `user` field answers 500.
- Equivalent: widening or dropping `algorithms=` when minting; reading `request.form` or
  `dict(request.values)` for the callback's parameters, since Apple only posts;
  `startswith('https')`; `.replace('\\n', '\r\n')` or `.replace('\\n', '')`, both of
  which cryptography's PEM parser reads; `env.get(name)` without `or ''`; an
  `object_hook` of `dict`; adding `Co` to the dropped categories; and parsing the key on
  every exchange instead of once.
- Not worth pinning: which of two true warnings shows first when keys are missing over
  http; the https warning's level, which the new tests pin only for the other two;
  `APPLE_USER_FIELD_LIMIT`'s value and unit, which the boundary test reads from the
  constant on purpose; that `prod-key.json` came from the production render; blank values
  in `.env.example`; and the four `unset` names, which matter only in a shell that exports
  them.
- Outside this change: `key={0}` in `ProviderLinks` only logs React's duplicate-key
  warning, and an `OAUTH_APPLE_*` value of spaces counts as set, as Google's keys do.

After the guards, every mutation ran again on scratch copies: 113 of the 138 backend ones
and 32 of the 44 shell ones are killed, 11 and 2 more than before, and none that was
killed before survives.

The browser check also showed:

- In Chrome 156, WebKit 27.2, and Firefox 157, every callback arrived as a cross-site POST
  carrying only `__Host-oauth_txn`, never `session`, even when the browser held one, and
  its response deleted `__Host-oauth_txn`. `session` was stored `SameSite=Strict`,
  `Secure`, and `HttpOnly`.
- The stub verified each client secret on its own, with cryptography and the key's public
  half: exactly `alg` and `kid` in the header, and `iss`, `sub`, `aud`, `iat`, and an
  `exp` 300 seconds later.
- A UTF-8 name, Zoë Núñez, reached `oauth_accounts.display_name` intact, and each link's
  audit entry has no actor, as "The linking policy" says for a link the callback makes.
- WebKit never shows `Set-Cookie` to Playwright, so its evidence of the deletion is the
  server's log of that response and the browser's cookie jar.
- The only console errors were the 401s from `/me` on a signed-out page load, which this
  change does not touch.

## Verification

1. Targeted, while editing: each group's command above.
2. At the end, in parallel: `npm run test`, `npm run lint -- --max-warnings=0`, and `npm
   run lint:py`; then `npm run typecheck`, `npm run lint:md`, `npx prettier --check .`,
   `npm run build`, `npm run test:scripts`, and `npx fallow audit`.
3. Against PostgreSQL, which refuses the NUL that SQLite stores: start a throwaway
   `postgres:16` container named `apple-check-pg-<pid>`, run `TEST_DATABASE_URL=<its
   URL> .venv/bin/python -m pytest`, and remove it by that name.
4. In real browsers, against a stub Apple on another site, with production's cookie
   settings and a production build, all in the scratchpad and nothing committed:
    - A runner calls `create_app()` with `load_dotenv` patched out, a scratch SQLite
      file, `PUBLIC_BASE_URL=https://localhost:<port>`,
      `SESSION_COOKIE_SAMESITE='Strict'`, and `SESSION_COOKIE_SECURE=True`. Its registry
      holds the real Apple provider, built by `build_registry()` from a scratch P-256
      key, with `dataclasses.replace` pointing its authorize, token, and JWKS URLs and
      its issuer at the stub on `http://127.0.0.1:<other port>`. It serves the built
      `dist/` over a self-signed certificate.
    - The stub's `/authorize` answers with an auto-submitting form that POSTs `code` and
      `state`, and `user` on a subject's first authorization only, or `error` and
      `state` when asked to cancel. Its `/token` verifies the client secret with the
      key's public half, checking `alg`, `kid`, `iss`, `sub`, `aud`, and a five-minute
      `exp`, and answers with an RS256 ID token carrying the nonce and `email_verified:
      "true"`. `/keys` serves the JWKS.
    - Playwright 1.64.1 with `ignoreHTTPSErrors` drives Chrome (`channel: 'chrome'`) and
      Playwright's WebKit and Firefox: "Continue with Apple" signs up and reaches `/`
      with `/api/v1/auth/me` answering 200, and the database holds the link's name;
      signing out and in again, with no `user`, keeps the account and its name; a
      cancel shows "Sign-in was cancelled." on `/login`; and a password account links
      Apple from `/account` and lands back there. Each browser stores `session` as
      `Strict` and drops `__Host-oauth_txn` after each callback.
    - Stop the runner and the stub, and confirm no process holds either port.
5. By Chuck, before the PR leaves draft, because only a Developer Program member can:
   follow "Setting up Apple" for staging, deploy it with `npm run deploy:staging`, and
   in Safari and one other browser sign up with Hide My Email, sign out and back in,
   cancel at Apple's page, link Apple to a password account from Account, and unlink
   it, confirming that staging's password prompt does not stop Apple's POST. Locally,
   with the four keys in `.env` and an http `PUBLIC_BASE_URL`, the backend logs the
   https warning and no Apple button appears.
