# Issue #29: Add Social Login With an OAuth Provider Registry and Google First

## Context

Accounts can sign in only with an email and a password. This change adds sign-in and
registration through `Continue with <provider>` buttons, on a backend-driven OAuth 2.0 and
OpenID Connect authorization-code flow: a registry that enables a provider when its keys
are in the environment, Google as the first provider, a signed transaction cookie instead
of session state, a fail-closed linking policy, and an Account page for linking and
unlinking. #30 (Apple) and #31 (Facebook) add adapters to this core, and #32 (passkeys)
adds a section to the Account page.

No endpoint, API client, page, or table for this exists yet. #28 built the groundwork this
reuses: `complete_login()`, `count_sign_in_methods()`, `LastSignInMethodError`,
`normalize_email()`, a nullable `password_hash`, `has_password`, `PUBLIC_BASE_URL`, and
the `passwordless_user` fixture. #22 built the `X-Requested-With` hook this exempts one
route from, and `ai/auth.md` already exists, so this change extends it.

The locked decisions stand and are not reopened here: a signed cookie rather than session
state, `requests` and `joserfc` rather than Authlib, never auto-linking to a password
account, and `PUBLIC_BASE_URL` as the only source of the public origin.

### Where the issue and the code disagree

Each of these was checked against the code or a primary source while planning, and each
changes what gets built.

1. **The issue's `read_transaction()` cannot produce `expired`.** It returns `None` for a
   bad signature and an expired one alike, so the callback could only say `invalid_state`,
   and a browser drops the cookie at its `max_age` anyway, so a late callback carries
   none. Here `read_transaction()` raises `OAuthError`: no cookie or an expired signature
   is `expired`, and a bad signature is `invalid_state`. The callback learns the mode only
   from a readable transaction, so an unreadable one lands on `/login`.
2. **`OAuthError` moves to `services/errors.py`.** `oauth_state.py` and `oidc.py` raise
   it, and `oauth.py` imports the provider module that imports `oidc.py`, so the issue's
   home for it is an import cycle. `ai/conventions.md` puts service exceptions there
   anyway.
3. **There is an eleventh code, `account_inactive`.** `complete_login()` raises
   `InactiveAccountError`, the issue's list has no code for it, and an uncaught raise
   would answer a browser navigation with a JSON 500. `_attach_account()` also refuses a
   deactivated account before it writes, so a refused sign-in leaves no link behind.
4. **The registry uses `setdefault`.** The issue's plain assignment after the overrides
   would erase the registry its own test fixture injects.
5. **One link per provider per account.** `DELETE /accounts/<provider>` names a provider,
   not a row, so two Google identities on one account would make unlink ambiguous. A
   second unique constraint, `(user_id, provider)`, and an `already_linked` refusal rule
   that out. It also stops a second Google identity claiming the same email from attaching
   to an account that has one, which fits Google's rule that `sub`, not the email,
   identifies a person.
6. **The "or" divider lives in `ProviderButtons`, not `AuthFormLayout`.** The slot always
   receives an element, so the layout cannot tell that it is empty, and a divider there
   would change the page for a project with no providers, which the first acceptance
   criterion forbids.
7. **`useProviders` uses local state, not a query.** "Loads the list once; empty on
   failure" is what `EnvironmentBadge` does, for a reason its comment records:
   `useSessionQueryCache` clears every query when the account changes, which would cancel
   the fetch during sign-in. It also keeps the render helpers of the 17 Login and Register
   tests unchanged; a query would need a `QueryClientProvider` around every one.
8. **A 401 from the linked accounts must end the session.** `reportLostSession` in
   `api/client.ts` skips every URL under `/v1/auth/`, so an expired session on `/account`
   would show an alert instead of the sign-in page. The exemption stops at
   `/v1/auth/oauth/`.
9. **`email_verified` is read strictly.** Google's OpenID Connect page describes a true or
   false value while its sample shows the text `"true"`, and #30 says Apple sends either.
   `bool('false')` is true, so `is_true_claim()` accepts only `True` and `'true'`.
10. **The audit log postdates the issue.** `services/auth.py` says every place that
    creates an account audits it, so an account a provider creates logs through
    `USER_AUDIT_TRAIL`. Links and unlinks get an admin-only trail of their own, because
    each one changes how an account can sign in.
11. **Logout clears the transaction cookie.** `link_user_id` outlives the session
    otherwise. On a shared browser, someone starts linking, abandons Google's page, and
    signs out. The next person presses Forward and finishes with their own Google account
    within ten minutes, and the callback links that account to the first person's and
    signs them in. Over http the cookie's path leaves it off the logout request, but RFC
    6265 section 8.6 says a browser accepts any `Path` in `Set-Cookie`, so the response
    clears it all the same.
12. **`startUrl` and the messages live in `utils/oauth.ts`, not `api/oauth.ts`.** Page
    tests automock the API module, which would turn a pure helper into `undefined`, and
    `utils/` is where framework-free helpers go. The messages sit in a `Map`: a `Record`
    lookup of `?error=__proto__` returns an object, which React refuses to render, so a
    crafted link would take the page down.
13. **`next` is capped at 512 characters, counted percent-encoded.** The cookie and the
    `Location` header both carry it, and host nginx sets no `proxy_buffer_size`, so its
    default of one page (4 KB on x86-64) holds the response headers and an overflow is a
    502. Werkzeug percent-encodes `Location`, where an emoji takes twelve characters, so
    the cap counts the encoded form. A test pins each response's budget.
14. **Staging arrived after the issue.** `.env.staging.example` gains the two keys, blank
    and optional, and `ai/staging.md` says so. `scripts/copy-production.sh` copies
    `oauth_accounts` with the rest of the database, so a tester whose production account
    has no password can sign in to staging only when staging has Google keys of its own.
15. **Already in place, or moved.** `ai/auth.md`, its duplicate-email recovery, and
    `passwordless_user` exist. `AppShell` lives in `components/layout/`, and tests mirror
    `src/` under `src/test/`, so the issue's test names map to the paths below.
16. **Linking must be asked for.** The issue links whenever `start` sees a session. A
    same-site click carries even a Strict cookie, `/login` has no signed-in guard, a
    session lasts 30 days, and `store/auth.ts` deliberately lets a failed logout leave one
    behind. So the next person to press `Continue with Google` on the sign-in page would
    attach their identity to that account, an admin's included, and keep access after it
    logs out. `start` now links only when the Account page asks: `?link=1` on a navigation
    whose `Sec-Fetch-Site` is `same-origin`. Browsers send that header to https origins
    and `http://localhost`. A `?link=1` without it, or without a session, is refused, not
    run as a sign-in, which would leave the identity on a second account nothing can move
    it from. An Account tab left open after signing out elsewhere is refused on the
    sign-in page, because the Account page would send it there anyway. A sign-in without
    `?link=1` replaces the stale session, as `store/auth.ts` promises. This departs from
    the issue's flow.
17. **The cookie is `__Host-oauth_txn` over https.** The signature proves this server
    issued a transaction, not that it issued it to this browser, and RFC 6265 section 8.6
    says a sibling host can set cookies the server cannot tell from its own. A sibling
    host, or a network attacker on a plain-http sibling, since HSTS here leaves out
    `includeSubDomains`, could plant its own signed transaction naming its own account and
    send a victim through Google, and the victim's identity would stay linked to that
    account. Browsers refuse a `__Host-` cookie from anywhere else. The prefix requires
    `Path=/`, which departs from the issue's path, and plain http keeps the plain name and
    the narrow path. `read_transaction()` reads only the scheme's name, so a plain cookie
    planted over https is ignored. Chuck chose this on 2026-11-01.
18. **The audience must be exactly this client.** `joserfc` passes a list that holds any
    one match, but OIDC Core 3.1.3.7 says a token MUST be rejected if "it contains
    additional audiences not trusted by the Client". `verify_id_token()` compares the
    audience itself, so the registry does not check it at all.
19. **A lost race is a refusal, not a 500.** Two first sign-ins at once can both miss the
    row they then insert. `resolve_user()` turns the `IntegrityError` into
    `already_linked` and rolls back, for the same reason as point 3.
20. **A failure another site can cause keeps the cookie.** Any site can send a browser to
    `callback?state=x`, so an unknown provider, an unreadable cookie, or the wrong state
    leaves a sign-in in progress alone. That also lets the second of two tabs finish.
21. **The timeouts are `(3, 5)`, not the issue's 10 seconds.** A callback makes up to
    three calls, and 20 seconds each could outlast gunicorn's 30-second worker limit,
    which ends in a 502 with the cookie still set.
22. **The last-method guard lives in `services/auth.py`.** #32 calls it shared, so
    `require_another_sign_in_method()` sits beside `count_sign_in_methods()`.
23. **`Continue with Google` always shows the account chooser.** Without
    `prompt=select_account`, a browser still signed in to Google goes straight through, so
    the next person at a shared browser, or someone linking a second account, never sees
    which account was used. Chuck chose this on 2026-11-01, along with auditing links.

### What was checked against primary sources

- **Pins.** On 2026-11-01, PyPI lists `requests` 2.34.2 (2026-05-14), `joserfc` 1.7.7
  (2026-10-19), and `responses` 0.26.3 (2026-08-26) as latest, none yanked, none with a
  listed vulnerability. `requests` 2.34 ships `py.typed`, so no `types-requests`.
  `joserfc` requires `cryptography>=45.0.1`.
- **The dependency trap.** `pip-audit` already puts `requests` in `.venv`, so pytest would
  pass with `requests` missing from `requirements.txt`. `app.py` therefore imports the
  registry at module level: `src_back/jobs/example.py` imports `src_back.app`, so
  `run_in production ... import src_back.jobs.example` in `test-backend-image.sh` fails on
  a missing runtime pin. A deferred import, like the blueprints', would not.
- **`joserfc` at tag 1.7.7.** `jwt.decode()` checks only the signature, so the claims need
  a `JWTClaimsRegistry`, whose `essential` entries are what make a claim required. Passing
  `algorithms` builds a registry that refuses every other algorithm, where the default one
  would allow ES256. A malformed token raises `DecodeError`, an unknown `kid`
  `InvalidKeyIdError`, and a bad signature `BadSignatureError`, all `JoseError`s.
  `KeySet.import_key_set()` raises `KeyError` or `TypeError` on a document with no `keys`
  and `MissingKeyError` on an empty set, so `fetch_jwks()` catches those too.
- **Google.** Its discovery document gives the issue's endpoints and JWKS URI, RS256,
  `code_challenge_methods_supported` with `S256`, and `client_secret_post`. Its OpenID
  Connect page gives both issuer values and caps `sub` at 255 ASCII characters. Its JWKS
  answer carried `max-age=23558` on 2026-11-01, so the one-hour cache is well inside it.
- **Test harness.** `responses` 0.26.3 has `RequestsMock.add`, `.get`, `.post`, `.remove`,
  and `assert_call_count`, and with several matches it answers the oldest and removes it,
  so a test that needs two JWKS answers in order clears the fixture's registration first.
  `URLSafeTimedSerializer` compresses with zlib, so a repeated character says nothing
  about a cookie's size. Flask's `redirect()` is typed as returning
  `werkzeug.wrappers.Response`, so the redirect routes annotate that.
- **Browsers.** RFC 6265bis, the current draft, says a top-level navigation may create a
  cookie with any `SameSite` value, that `SameSite=None; Secure` is sent on cross-site
  requests, and that a page's own sub-resources receive its `Strict` cookies. That shipped
  browsers do all of this across this redirect chain is inference until Verification step
  5 runs.
- **The app-context trap.** The `app` fixture keeps one application context, so
  Flask-Login's cached `g._login_user` survives between requests. Every test below that
  proves a cookie works, or simulates a missing session, runs `g.pop('_login_user', None)`
  first, as `test_auth.py` does.

### Accepted limits, documented in `ai/auth.md`

- Google's verified flag records that Google verified an address once. Its documentation
  warns that "ownership of the third party email account may have since changed", and
  recommends another challenge when the address is neither `@gmail.com` nor a Workspace
  one. Two rules of the linking policy rely on the flag anyway. Rule 4 creates a
  passwordless account today, and a stale address can then block the real owner's
  registration with a 409, which is no worse than anyone registering that address today.
  Rule 5 auto-links to such an account. It cannot run in production yet, because a
  provider-created account always holds its link and point 5 refuses a second Google link,
  so it goes live with #30, whose review decides it. Dropping rule 5 needs nothing stored
  now, so the accounts created here leave that fix open. Chuck kept this as documentation
  on 2026-11-01, knowing both rules.
- Two `start` requests in one browser overwrite the cookie, so the first callback fails
  with `invalid_state`, and the second succeeds.
- A link made in the callback has no audit actor, because the session cookie does not
  reach it in production. The entry's `user_id` names the account.
- Linking asks for no password or other fresh proof, so someone with brief access to a
  session can link their own Google account, and the link survives a password change.
  `ai/auth.md` gives the cleanup.
- A sibling host can still plant the session cookie, as it can today, so `__Host-` stops a
  planted transaction, not all login CSRF. A planted session shows the attacker's account,
  and a victim who presses Link there attaches their identity to it.
- One valid cookie can replay `GET callback?state=S&code=x` for ten minutes, and each
  replay holds a sync worker for a round trip to the provider. nginx's throttle counts
  only POSTs, and a `limit_req` for this needs a location per provider, which deserves its
  own issue.

### Sources

- [Google: discovery document](https://accounts.google.com/.well-known/openid-configuration)
- [Google: OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect)
- [Google: verify an ID token](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token)
- [Google: app verification](https://support.google.com/cloud/answer/9110914)
- [joserfc 1.7.7 source](https://github.com/authlib/joserfc/tree/1.7.7/src/joserfc)
- [RFC 6265, HTTP cookies](https://www.rfc-editor.org/rfc/rfc6265)
- [RFC 7636, PKCE](https://www.rfc-editor.org/rfc/rfc7636)
- [RFC 6265bis, draft 22](https://www.ietf.org/archive/id/draft-ietf-httpbis-rfc6265bis-22.txt)
- [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html)
- [W3C: Fetch Metadata](https://w3c.github.io/webappsec-fetch-metadata/)
- [MDN: Sec-Fetch-Site](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Sec-Fetch-Site)
- [MDN: Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie)

## Branch

`issue-29-add-social-login-with-an-env-enabled` — already checked out; PR #56 exists.

## Change

**Backend, new**: `src_back/models/oauth_account.py`,
`migrations/versions/<date>_<rev>_oauth_accounts.py`, `src_back/services/oauth_state.py`,
`src_back/services/oidc.py`, `src_back/services/oauth_providers.py`,
`src_back/services/oauth.py`, `src_back/schemas/oauth.py`, `src_back/api/oauth.py`, and
`test_oauth_state.py`, `test_oidc.py`, `test_oauth_providers.py`, `test_oauth.py`, and
`test_oauth_api.py` in `src_back/tests/`.

**Backend, edited**: `requirements.txt`, `requirements-dev.txt`,
`src_back/models/__init__.py`, `src_back/models/user.py`, `src_back/services/errors.py`,
`src_back/services/auth.py`, `src_back/api/__init__.py`, `src_back/api/auth.py`,
`src_back/app.py`, and `conftest.py`, `test_app.py`, `test_auth.py`, `test_errors.py`, and
`test_schemas.py` in `src_back/tests/`.

**Frontend, new**, under `src_front/src/`: `api/oauth.ts`, `utils/oauth.ts`,
`hooks/useProviders.ts`, `hooks/oauth.ts`, `components/auth/ProviderButtons.tsx`,
`components/account/LinkedAccounts.tsx`, `pages/Account.tsx`, and under `test/`:
`api/oauth.test.ts`, `utils/oauth.test.ts`, `hooks/useProviders.test.tsx`,
`hooks/oauth.test.tsx`, `components/auth/ProviderButtons.test.tsx`,
`components/account/LinkedAccounts.test.tsx`, `pages/Account.test.tsx`.

**Frontend, edited**, under `src_front/src/`: `types/auth.ts`, `api/client.ts`,
`hooks/useAuthFormState.ts`, `components/AuthFormLayout.tsx`, `pages/Login.tsx`,
`pages/Register.tsx`, `components/layout/AppShell.tsx`, `App.tsx`, and under `test/`:
`api/client.test.ts`, `pages/Login.test.tsx`, `pages/Register.test.tsx`, `App.test.tsx`,
`components/layout/AppShell.test.tsx`, `utils/fixtures.ts`.

**Configuration**: `.env.example`, `.env.staging.example`, `docker-compose.yml`,
`docker/docker-compose.prod.yml`, `scripts/provision.sh`, and `test-provision.sh`,
`test-compose-config.sh`, and `test-deploy.sh` in `scripts/tests/`.

**Documentation**: `ai/auth.md`, `ai/conventions.md`, `ai/domain.md`, `ai/project.md`,
`ai/staging.md`, `tools.md`, `README.md`.

### requirements.txt and requirements-dev.txt — the pins

After `filetype==1.2.0` in `requirements.txt`:

```text
# Sign-in providers. Not Authlib: its Flask client keeps state in the session, which
# the provider's redirect cannot read under SameSite=Strict (ai/auth.md).
requests==2.34.2
joserfc==1.7.7
```

After `pytest-cov==6.1.0` in `requirements-dev.txt`: `responses==0.26.3`. Then run
`.venv/bin/python -m pip install -r requirements-dev.txt`, because nothing below imports
until then.

### src_back/services/errors.py — `OAuthError`

The module docstring's last sentence gains the exception to its rule:

```python
"""Exceptions services raise when a request breaks a business rule.

Route handlers catch them and answer with the matching envelope from
:mod:`src_back.utils`: :func:`~src_back.utils.conflict` for a 409,
:func:`~src_back.utils.bad_request` for a 400, and
:func:`~src_back.utils.forbidden` for a 403. :class:`OAuthError` differs: a provider
sign-in is a browser navigation, so its routes answer with a redirect.
"""
```

At the end of the file:

```python
class OAuthError(Exception):
    """A sign-in through a provider failed; the routes redirect with its code."""

    def __init__(self, code: str) -> None:
        """Record why the sign-in failed.

        Args:
            code: The ``?error=`` value, which the frontend turns into a message.
        """
        super().__init__(code)
        self.code = code
```

### src_back/models/oauth_account.py — new

```python
"""A sign-in provider's identity, linked to one account."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src_back.extensions import Base
from src_back.models.base import BaseMixin

if TYPE_CHECKING:
    from src_back.models.user import User


class OAuthAccount(BaseMixin, Base):
    """One provider identity that can sign in to one account.

    ``provider_user_id`` is the provider's stable id for the person, and the only thing
    a returning sign-in is matched on: an email can change hands, so ``email`` and
    ``display_name`` only label the link on the Account page. An account has at most one
    link per provider, because unlinking names a provider rather than a row.
    """

    __tablename__ = 'oauth_accounts'
    __table_args__ = (
        UniqueConstraint(
            'provider', 'provider_user_id', name='uq_oauth_accounts_provider_subject'
        ),
        UniqueConstraint('user_id', 'provider', name='uq_oauth_accounts_user_provider'),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates='oauth_accounts')

    def __repr__(self) -> str:
        """Describe the link by provider and account for logs and debugging.

        Returns:
            The repr string, for example ``<OAuthAccount google user=3>``.
        """
        return f'<OAuthAccount {self.provider} user={self.user_id}>'
```

### src_back/models/user.py and `__init__.py` — the relationship

In `src_back/models/user.py`, add to the `TYPE_CHECKING` block
`from src_back.models.oauth_account import OAuthAccount`, and below `audit_entries`:

```python
    oauth_accounts: Mapped[list['OAuthAccount']] = relationship(
        back_populates='user', cascade='all, delete-orphan'
    )
```

Change the class docstring's sentence about `password_hash` so it reads: "`password_hash`
is `None` for an account a sign-in provider created, which has no password;
`oauth_accounts` holds the providers it can sign in with." In
`src_back/models/__init__.py`, import `OAuthAccount` from `src_back.models.oauth_account`,
add it to `__all__`, in sorted order, and keep the module docstring's rule.

### migrations/versions — new `<date>_<rev>_oauth_accounts.py`

Start the dev database (`npm run docker:up -- -d`), then run
`.venv/bin/flask --app src_back.app db migrate -m "oauth accounts"`. Review the file: it
creates `oauth_accounts` with `ondelete='CASCADE'`, both named unique constraints, the
unique `uuid`, and `ix_oauth_accounts_user_id`, and `downgrade()` drops the index and the
table. Keep the file name `YYYY_MM_DD_<rev>_oauth_accounts.py`, and wrap as
`2026_10_27_b6ae6389cd3e_audit_logs.py` does. Apply it with `db upgrade`, and confirm with
`db check`.

### src_back/services/oauth_state.py — new

```python
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
```

### src_back/services/oidc.py — new

```python
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
```

### src_back/services/oauth_providers.py — new

```python
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
```

### src_back/services/oauth.py — new

```python
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
    require_another_sign_in_method,
)
from src_back.services.errors import InactiveAccountError, OAuthError
from src_back.services.oauth_providers import OAuthIdentity, OAuthProvider
from src_back.services.oauth_state import OAuthTransaction, code_challenge
from src_back.services.oidc import HTTP_TIMEOUT_SECONDS

_log = logging.getLogger(__name__)

_DISPLAY_NAME_LENGTH = 255
"""The length of ``oauth_accounts.display_name``; a longer name is cut to fit."""

AUTO_LINK_PASSWORD_ACCOUNTS = False
"""Whether a provider's verified email may attach to an account that has a password.

Registration never verifies an address, so anyone can register a victim's email with a
password and wait. Linking the victim's provider account to it would leave them holding
a working password to the merged account. A project that verifies addresses at
registration can turn this on.
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
    """Sign in or create an account from a verified email.

    An account with a password is never attached to, unless
    :data:`AUTO_LINK_PASSWORD_ACCOUNTS` says so. One without a password got its email
    from a provider that verified it (``ai/auth.md``).

    Args:
        identity: The identity the provider asserted, which matches no link.

    Returns:
        The account.

    Raises:
        OAuthError: With ``email_required`` if the provider gave no email,
            ``email_unverified`` if it did not verify it, and ``link_required`` if it
            belongs to an account with a password.
    """
    if not identity.email:
        raise OAuthError('email_required')
    if not identity.email_verified:
        raise OAuthError('email_unverified')
    user = find_user_by_email(identity.email)
    if user is None:
        return _create_user(identity.email, identity)
    if user.has_password and not AUTO_LINK_PASSWORD_ACCOUNTS:
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

    :func:`~src_back.services.auth.require_another_sign_in_method` refuses the last one.

    Args:
        user: The account.
        provider: The provider's registry name.

    Returns:
        ``True`` once the link is gone, ``False`` if there was none.
    """
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
```

### src_back/services/auth.py — count links; the shared guard; name the new caller

Change the comment above `USER_AUDIT_TRAIL` so its second line reads "registration here, a
provider sign-in (services/oauth.py), the admin's Users screen (services/users.py), and
the seed." and rewrap it. In `complete_login`'s docstring, "registration and password
login now, a provider callback or a passkey later" becomes "registration, password login,
and a provider callback now, a passkey later". Import `LastSignInMethodError` beside the
other two errors, and below `USER_AUDIT_TRAIL` add:

```python
LAST_METHOD = 'Add another way to sign in before removing this one.'
```

Replace `count_sign_in_methods`, and add the guard after it:

```python
def count_sign_in_methods(user: User) -> int:
    """Count the ways an account can sign in.

    A password and each linked provider count; passkeys join the count when their table
    arrives.

    Args:
        user: The account to inspect.

    Returns:
        The number of sign-in methods the account has.
    """
    return (1 if user.has_password else 0) + len(user.oauth_accounts)


def require_another_sign_in_method(user: User) -> None:
    """Refuse to remove a sign-in method that is the account's last.

    Code that removes one calls this first.

    Args:
        user: The account about to lose a method.

    Raises:
        LastSignInMethodError: If the account has no other way to sign in.
    """
    if count_sign_in_methods(user) <= 1:
        raise LastSignInMethodError(LAST_METHOD)
```

### src_back/schemas/oauth.py — new

```python
"""Serialization of sign-in providers and the accounts linked through them."""

from marshmallow import Schema, fields

from src_back.models import OAuthAccount
from src_back.schemas.base import BaseSchema


class OAuthProviderSchema(Schema):
    """Serialize an enabled provider for the sign-in pages; its keys stay out."""

    name = fields.String(dump_only=True)
    label = fields.String(dump_only=True)


class OAuthAccountSchema(BaseSchema):
    """Serialize a link for its owner.

    Every field is dump-only, because linking happens in the provider callback. The
    provider's subject stays out: the client has no use for it.
    """

    class Meta(BaseSchema.Meta):
        """Bind to the ``oauth_accounts`` table and hide the provider's subject."""

        model = OAuthAccount
        exclude = ('provider_user_id',)
        dump_only = (*BaseSchema.AUDIT, 'provider', 'email', 'display_name')


oauth_provider_schema = OAuthProviderSchema()
oauth_account_schema = OAuthAccountSchema()
```

### src_back/api/oauth.py — new

```python
"""Sign-in through a provider: its two navigations, and the accounts linked through it.

``start`` and ``callback`` are browser navigations, not API calls, so every outcome is a
redirect rather than the JSON envelope. ``callback`` trusts only the signed transaction
cookie, because production's ``SameSite=Strict`` session cookie does not arrive with the
provider's redirect, and it takes GET and POST alike, because Sign in with Apple posts
its answer. ``ai/auth.md`` walks through the flow.
"""

from flask import Blueprint, Response, current_app, jsonify, redirect, request
from flask_login import login_required
from werkzeug.wrappers import Response as BaseResponse

from src_back.auth import current_user
from src_back.models import User
from src_back.schemas.oauth import oauth_account_schema, oauth_provider_schema
from src_back.services.auth import complete_login
from src_back.services.errors import (
    InactiveAccountError,
    LastSignInMethodError,
    OAuthError,
)
from src_back.services.oauth import (
    build_authorize_url,
    exchange_code,
    list_accounts,
    resolve_user,
    signed_in_user_id,
    unlink_account,
)
from src_back.services.oauth_providers import OAuthProvider, redirect_uri
from src_back.services.oauth_state import (
    OAuthTransaction,
    clear_transaction_cookie,
    new_transaction,
    read_transaction,
    safe_next,
    set_transaction_cookie,
    state_matches,
)
from src_back.utils import ErrorResponse, conflict, not_found

bp = Blueprint('oauth', __name__)

_ACCOUNT_PAGE = '/account'

_KEEPS_TRANSACTION = frozenset({'unknown_provider', 'expired', 'invalid_state'})
"""Failures another site can cause, which must not end a sign-in in progress."""


def _find_provider(provider_name: str) -> OAuthProvider | None:
    """Look up an enabled provider.

    Args:
        provider_name: The name in the URL.

    Returns:
        The provider, or ``None`` if none by that name is enabled.
    """
    return current_app.config['OAUTH_PROVIDERS'].get(provider_name)


def _public_redirect(path: str) -> BaseResponse:
    """Redirect to a path on the public origin.

    Args:
        path: The path, which starts with a slash.

    Returns:
        The redirect. With no ``PUBLIC_BASE_URL`` no provider is enabled, and the path
        alone still reaches the page that says so.
    """
    public_base_url = current_app.config['PUBLIC_BASE_URL'] or ''
    return redirect(f'{public_base_url}{path}')


def _error_redirect(code: str, *, link_mode: bool = False) -> BaseResponse:
    """Send the browser to the page that shows a failed sign-in.

    Args:
        code: The ``?error=`` value, which the page turns into a message.
        link_mode: Whether the failure belongs to linking, shown on the Account page.

    Returns:
        The redirect, which ends the transaction unless another site could have caused
        this failure.
    """
    page = _ACCOUNT_PAGE if link_mode else '/login'
    response = _public_redirect(f'{page}?error={code}')
    if code not in _KEEPS_TRANSACTION:
        clear_transaction_cookie(response)
    return response


@bp.get('/providers')
def providers() -> Response:
    """List the enabled providers, for the sign-in pages.

    Returns:
        Each provider's name and label; an empty list when none is enabled.
    """
    enabled = current_app.config['OAUTH_PROVIDERS'].values()
    return jsonify(oauth_provider_schema.dump(enabled, many=True))


def _link_user_id() -> int | None:
    """Find the account a navigation that asked to link can link to.

    A session alone is not consent: the sign-in pages stay open to a visitor with a live
    session, and a failed logout leaves one behind, so only the Account page asks.
    ``Sec-Fetch-Site`` keeps another site, a sibling host included, from asking under any
    ``SameSite`` setting.

    Returns:
        The signed-in account's id, or ``None`` if this navigation cannot link.
    """
    same_origin = request.headers.get('Sec-Fetch-Site') == 'same-origin'
    return signed_in_user_id() if same_origin else None


@bp.get('/<provider_name>/start')
def start(provider_name: str) -> BaseResponse:
    """Send the browser to the provider, remembering the sign-in in a signed cookie.

    A navigation that asks to link returns to the Account page by default. One that
    cannot link is refused, not run as a sign-in, which would leave the identity on a
    second account nothing can move it from. Any other is a sign-in, which replaces a
    session left open in the browser.

    Args:
        provider_name: The provider's registry name.

    Returns:
        A redirect to the provider, or to the page that shows a refusal.
    """
    provider = _find_provider(provider_name)
    if provider is None:
        return _error_redirect('unknown_provider')
    asked_to_link = request.args.get('link') == '1'
    link_user_id = _link_user_id() if asked_to_link else None
    if asked_to_link and link_user_id is None:
        # Without a session the Account page could only send the visitor to sign in.
        return _error_redirect('invalid_state', link_mode=signed_in_user_id() is not None)
    default_path = '/' if link_user_id is None else _ACCOUNT_PAGE
    transaction = new_transaction(
        provider.name,
        uses_pkce=provider.uses_pkce,
        next_path=safe_next(request.args.get('next'), default_path),
        link_user_id=link_user_id,
    )
    public_base_url = current_app.config['PUBLIC_BASE_URL']
    response = redirect(
        build_authorize_url(
            provider,
            redirect_uri=redirect_uri(public_base_url, provider.name),
            txn=transaction,
        )
    )
    set_transaction_cookie(response, transaction)
    return response


def _finish_sign_in(provider: OAuthProvider, transaction: OAuthTransaction) -> User:
    """Check the provider's answer and resolve it to an account.

    The state is compared before anything else in the answer is believed.

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
        raise OAuthError('cancelled' if error == 'access_denied' else 'exchange_failed')
    code = request.values.get('code')
    if not code:
        raise OAuthError('exchange_failed')
    tokens = exchange_code(
        provider,
        code=code,
        redirect_uri=redirect_uri(current_app.config['PUBLIC_BASE_URL'], provider.name),
        code_verifier=transaction.code_verifier,
    )
    identity = provider.fetch_identity(provider, tokens, transaction.nonce)
    return resolve_user(identity, link_user_id=transaction.link_user_id)


@bp.route('/<provider_name>/callback', methods=['GET', 'POST'])
def callback(provider_name: str) -> BaseResponse:
    """Finish a sign-in when the provider sends the browser back.

    The ``X-Requested-With`` hook exempts this route, because a provider may answer with
    a cross-site POST; the signed state protects it instead.

    Args:
        provider_name: The provider's registry name.

    Returns:
        A redirect to the transaction's return path, or to the page that shows the
        failure: the Account page when linking, otherwise the sign-in page.
    """
    provider = _find_provider(provider_name)
    if provider is None:
        return _error_redirect('unknown_provider')
    link_mode = False
    try:
        transaction = read_transaction()
        link_mode = transaction.link_user_id is not None
        complete_login(_finish_sign_in(provider, transaction))
    except OAuthError as exc:
        return _error_redirect(exc.code, link_mode=link_mode)
    except InactiveAccountError:
        return _error_redirect('account_inactive', link_mode=link_mode)
    response = _public_redirect(transaction.next_path)
    clear_transaction_cookie(response)
    return response


@bp.get('/accounts')
@login_required
def accounts() -> Response:
    """List the signed-in account's linked providers.

    Returns:
        The links, without the provider's subject.
    """
    return jsonify(oauth_account_schema.dump(list_accounts(current_user), many=True))


@bp.delete('/accounts/<provider_name>')
@login_required
def unlink(provider_name: str) -> tuple[str, int] | ErrorResponse:
    """Remove the signed-in account's link to a provider.

    Args:
        provider_name: The provider's registry name.

    Returns:
        An empty 204, a 404 envelope when no such link exists, or a 409 envelope when it
        is the account's last way to sign in.
    """
    try:
        removed = unlink_account(current_user, provider_name)
    except LastSignInMethodError as exc:
        return conflict(str(exc))
    if not removed:
        return not_found('That provider is not linked.')
    return '', 204
```

In `src_back/api/__init__.py`, import `bp as oauth_bp` from `src_back.api.oauth`, in
sorted order, and add it to `__all__`.

### src_back/api/auth.py — logout ends a transaction too

Import `clear_transaction_cookie` from `src_back.services.oauth_state`, in sorted order,
and replace `logout`:

```python
@bp.post('/logout')
@login_required
def logout() -> Response:
    """End the current session and delete its cookie.

    ``logout_user()`` removes only Flask-Login's keys, so clearing the session
    also drops the permanent flag that login set. Flask deletes the cookie of an
    emptied session instead of renewing it. The provider transaction goes too: it can
    name this account, and linking must not finish after a sign-out.

    Returns:
        A JSON confirmation message.
    """
    logout_user()
    session.clear()
    response = jsonify({'message': 'Logged out.'})
    clear_transaction_cookie(response)
    return response
```

### src_back/app.py — the registry, the exemption, the blueprint

Import at module level, after `from src_back.models import User`, because the image test
reaches this import and so guards the two new pins:

```python
from src_back.services.oauth_providers import build_registry
```

Below `_MUTATING_METHODS`:

```python
_CROSS_SITE_POST_ENDPOINTS = frozenset({'oauth.callback'})
"""Routes that check their own signed state, because a provider posts to them."""
```

In `create_app`, between `_resolve_public_base_url(app)` and
`_initialize_extensions(app)`, call `_configure_oauth_providers(app)`, defined after
`_resolve_public_base_url`:

```python
def _configure_oauth_providers(app: Flask) -> None:
    """Enable each sign-in provider whose keys the environment holds.

    It runs after the overrides and :func:`_resolve_public_base_url`, because the registry
    needs the settled origin, and ``setdefault`` keeps a registry a test injects.

    Args:
        app: The application being configured.
    """
    app.config.setdefault(
        'OAUTH_PROVIDERS', build_registry(os.environ, app.config['PUBLIC_BASE_URL'])
    )
```

In `_register_blueprints`, import `oauth_bp` too, and after `auth_bp`:
`app.register_blueprint(oauth_bp, url_prefix='/api/v1/auth/oauth')`.

Replace the condition in `_require_requested_with_header`, and add to its docstring's
first paragraph "Routes in `_CROSS_SITE_POST_ENDPOINTS` are exempt.":

```python
    if (
        request.method in _MUTATING_METHODS
        and _is_json_path(request.path)
        and request.endpoint not in _CROSS_SITE_POST_ENDPOINTS
        and request.headers.get('X-Requested-With') != 'XMLHttpRequest'
    ):
```

### src_back/tests/conftest.py — the provider harness

`responses` replaces the `requests` transport, so the real exchange and key fetch run. The
key is generated once per session, because 2048-bit generation is slow, and 2048 bits
keeps `joserfc` from warning. The new imports are `time`, `responses`, `from joserfc
import jwt`, `from joserfc.jwk import KeySet, RSAKey`, `OAuthAccount` from
`src_back.models`, `from src_back.services import oidc`, and `GOOGLE_ISSUERS`,
`GOOGLE_JWKS_URI`, and `build_registry` from `src_back.services.oauth_providers`. Add,
beside `SMTP_VARIABLES`:

```python
PUBLIC_BASE_URL = 'https://app.test'
OAUTH_CLIENT_ID = 'test-client-id'
OAUTH_ENVIRONMENT = {
    'OAUTH_GOOGLE_CLIENT_ID': OAUTH_CLIENT_ID,
    'OAUTH_GOOGLE_CLIENT_SECRET': 'test-client-secret',
}
```

Beside `_clear_smtp_environment`:

```python
@pytest.fixture(autouse=True)
def _clear_oauth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # src_back.app loads .env at import, where a developer's real keys would enable
    # Google in every app a test builds without injecting a registry.
    for name in OAUTH_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _clear_jwks_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # Each process caches a provider's keys; a test must not inherit another's.
    monkeypatch.setattr(oidc, '_key_sets', {})
```

In the `app` fixture's overrides:

```python
            'PUBLIC_BASE_URL': PUBLIC_BASE_URL,
            'OAUTH_PROVIDERS': build_registry(OAUTH_ENVIRONMENT, PUBLIC_BASE_URL),
```

After the `inactive_user` fixture:

```python
@pytest.fixture()
def linked_user(passwordless_user: User) -> User:
    persist(
        OAuthAccount(
            user=passwordless_user,
            provider='google',
            provider_user_id='google-subject',
            email=passwordless_user.email,
        )
    )
    return passwordless_user


@pytest.fixture()
def mocked_http() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


class OidcSigner:
    """Signs ID tokens with a key whose public half the mocked JWKS URL serves."""

    def __init__(self, key: RSAKey) -> None:
        self.key = key

    def public_jwks(self) -> dict[str, Any]:
        return dict(KeySet([self.key]).as_dict(private=False))

    def make_id_token(self, claims: dict[str, Any]) -> str:
        now = int(time.time())
        payload = {
            'iss': GOOGLE_ISSUERS[0],
            'aud': OAUTH_CLIENT_ID,
            'sub': 'google-subject',
            'iat': now,
            'exp': now + 3600,
            **claims,
        }
        # A claim of None is left out, which is how a test drops sub, exp, or nonce.
        payload = {name: value for name, value in payload.items() if value is not None}
        header = {'alg': 'RS256', 'kid': self.key.kid}
        return jwt.encode(header, payload, self.key, algorithms=['RS256'])


@pytest.fixture(scope='session')
def oidc_key() -> RSAKey:
    return RSAKey.generate_key(2048, auto_kid=True)


@pytest.fixture()
def oidc_signer(oidc_key: RSAKey, mocked_http: responses.RequestsMock) -> OidcSigner:
    signer = OidcSigner(oidc_key)
    mocked_http.add(responses.GET, GOOGLE_JWKS_URI, json=signer.public_jwks())
    return signer
```

A claim of `None` is left out of the token, which is how a test drops `sub`, `exp`, or
`nonce`. `joserfc` refuses a JSON `null` even for a claim it does not require, so a test
that sent one would pass with the claim's check removed.

### src_back/tests/test_oauth_state.py — new

Reading needs a request, so wrap it, with the cookie under `SECURE_COOKIE_NAME`, since the
`app` fixture is https: `with app.test_request_context('/', headers={'Cookie': ...}):`.
Writing goes onto a plain `flask.Response()`, with `Set-Cookie` read from its headers.

- `test_new_transaction_makes_fresh_values`: two transactions differ in `state`, `nonce`,
  and `code_verifier`, and the verifier is 43 to 128 characters.
- `test_new_transaction_has_no_verifier_without_pkce`.
- `test_code_challenge_matches_the_rfc_7636_example`: verifier
  `dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk` gives
  `E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM`.
- `test_state_matches`: equal, different, and `'é'`, which must answer `False`, not raise.
- `test_transaction_round_trips_through_the_cookie`.
- `test_cookie_is_host_prefixed_over_https`: the name `__Host-oauth_txn`, `SameSite=None`,
  `Secure`, `HttpOnly`, `Path=/`, `Max-Age=600`, and no `Domain`, as the prefix requires.
- `test_cookie_keeps_its_plain_name_over_http`: with `app.config['PUBLIC_BASE_URL']` set
  to an http origin, the name `oauth_txn`, `Path=/api/v1/auth/oauth`, `SameSite=Lax`, and
  no `Secure`.
- `test_the_plain_name_is_ignored_over_https`: a valid transaction under `oauth_txn` reads
  as `expired`, which is what stops a plant.
- `test_a_missing_cookie_is_expired`; `test_a_signature_past_its_age_is_expired`, with
  `read_transaction(max_age=-1)`, which `itsdangerous` refuses as older than the limit.
- `test_a_tampered_cookie_is_invalid_state`.
- `test_a_cookie_signed_with_another_secret_is_invalid_state`: change
  `app.config['SECRET_KEY']` between writing and reading.
- `test_a_cookie_from_an_older_release_is_invalid_state`: `{'unexpected': 1}` signed with
  the same key and salt, which does not fit the dataclass.
- `test_clear_transaction_cookie_deletes_it_over_https`: `Max-Age=0`, `Path=/`, and
  `Secure`, because a browser refuses a `__Host-` deletion without it.
- `test_clear_transaction_cookie_deletes_it_over_http`: the plain name and its path.
- `test_safe_next`, parametrized on value and result: `None`, `''`, `'/'`, `'/a/b?c=1#d'`,
  `'//evil.example'`, `'/\\evil.example'`, `'https://evil.example'`,
  `'javascript:alert(1)'`, `'evil'`, `'/\t/evil.example'`, `'/a\nb'`, `'/a\x7fb'`, a path
  of `MAX_NEXT_LENGTH` characters (kept), one character longer (default), a path of `é`
  that fills `MAX_NEXT_LENGTH` exactly once percent-encoded (kept), one character longer
  (default), and `'//[evil.example'` (default), which `iri_to_uri` would raise on if the
  length check ran first.

### src_back/tests/test_oidc.py — new

A helper calls `verify_id_token` with `GOOGLE_JWKS_URI`, `GOOGLE_ISSUERS`,
`OAUTH_CLIENT_ID`, and `nonce='the-nonce'`. The default token carries that nonce.

- `test_a_valid_token_returns_its_claims`, parametrized on both issuers.
- `test_a_token_for_another_audience_is_refused`; `test_another_issuer_is_refused`.
- `test_a_token_with_a_second_audience_is_refused`, and
  `test_a_one_item_audience_list_passes`.
- `test_a_token_without_an_audience_is_refused`.
- `test_a_token_expired_past_the_leeway_is_refused` (`exp` 120 seconds ago) and
  `test_a_token_expired_within_the_leeway_passes` (30 seconds ago).
- `test_a_signature_by_another_key_is_refused`: another `RSAKey` under the same `kid`.
- `test_a_token_without_its_subject_is_refused`; `test_a_token_without_exp_is_refused`.
- `test_a_mismatched_nonce_is_refused`; `test_a_missing_nonce_is_refused`;
  `test_a_nonce_with_non_ascii_text_is_refused`, which must not raise `TypeError`.
- `test_an_hmac_token_is_refused`: `jwt.encode({'alg': 'HS256'}, ...,
  OctKey.import_key('x' * 32), algorithms=['HS256'])`.
- `test_an_es256_token_is_refused`: the JWKS serves an EC key and the token is signed
  with it, because only the `algorithms` argument refuses this one.
- `test_an_unsigned_token_is_refused`: a hand-built `alg: none` token.
- `test_a_malformed_token_is_refused`: `'not-a-jwt'`.
- `test_an_unknown_key_id_fetches_the_keys_once_more`: first run
  `mocked_http.remove(responses.GET, GOOGLE_JWKS_URI)`, because `responses` answers the
  oldest match and the fixture's registration is older. The JWKS URL then answers an old
  key first and the signing key second, and
  `mocked_http.assert_call_count(GOOGLE_JWKS_URI, 2)`.
- `test_a_key_id_unknown_after_the_refetch_is_refused`: two calls, no third.
- `test_a_second_token_uses_the_cached_keys`: one call.
- `test_the_keys_are_fetched_again_after_an_hour`: seed `oidc._key_sets` with a different
  key under the signing key's `kid`, stamped `time.monotonic() - 3601`. Under another
  `kid`, the refetch for an unknown key would hide a cache that never expires.
- `test_unreadable_keys_are_refused`, parametrized on a 500 with a valid JWKS body, so
  only `raise_for_status` refuses it, a body that is not JSON, `{}`, `[]`, `{'keys': []}`,
  and `requests.ConnectionError`; the 500 also asserts the warning in `caplog`.

### src_back/tests/test_oauth_providers.py — new

- `test_google_is_enabled_with_both_keys`, and `test_google_stays_off_without_a_key`,
  parametrized on each key missing and each blank, as Compose passes it.
- `test_nothing_is_enabled_without_a_public_origin`.
- `test_redirect_uri`.
- `test_google_provider_asks_for_pkce_and_the_account_chooser`: `uses_pkce`, the scopes,
  and `extra_authorize_params == {'prompt': 'select_account'}`.
- `test_google_identity_reads_the_claims`: subject, email, name, verified.
- `test_email_verified`, parametrized: `True` and `'true'` are verified; `False`,
  `'false'`, `1`, `'TRUE'`, and a missing claim are not.
- `test_a_token_response_without_an_id_token_is_invalid`, and with a non-string one.

### src_back/tests/test_oauth.py — new

- `test_authorize_url_carries_the_transaction`: every parameter, and `code_challenge`
  matches `code_challenge(txn.code_verifier)` with method `S256`.
- `test_authorize_url_omits_pkce_without_a_verifier`.
- `test_exchange_posts_the_code_and_secret`, reading the form body from
  `mocked_http.calls[0].request.body`, with `code_verifier` present, and
  `test_exchange_omits_the_verifier_without_pkce`.
- `test_exchange_failures`, parametrized on a 400, a body that is not JSON, a JSON list,
  and `requests.ConnectionError`, each `exchange_failed`.
- `test_a_refused_exchange_logs_without_the_secret`: `caplog` holds the provider and not
  `test-client-secret`.
- `test_oauth_account_repr`.
- `test_a_long_display_name_is_cut_to_fit`: a 300-character name stores 255. Only
  PostgreSQL would refuse the longer one, so CI's PostgreSQL run is what proves it.
- `test_list_accounts_is_in_provider_order`: two rows with `provider` values out of order.

### src_back/tests/test_oauth_api.py — new

Helpers: `begin(client, **query)` runs `start` with `query_string=query` and returns the
authorize URL's parameters as a dict; `begin_link(client)` does the same with `link='1'`
and `Sec-Fetch-Site: same-origin`, as the Account page's link does;
`answer_token_request(mocked_http, signer, nonce, claims)` registers the token response;
`sign_in(client, mocked_http, signer, claims)` runs `begin`, that, and the GET callback
with a `code` and the `state`; `finish_link` does the same after `begin_link`.
`transaction_in(app, client)` reads the cookie back through `read_transaction()` in a
`test_request_context`. `VERIFIED = {'email': 'new@example.com', 'email_verified': True,
'name': 'New Person'}`. The cookie is `client.get_cookie(SECURE_COOKIE_NAME)`, because the
`app` fixture is https.

`/providers`:

- `test_providers_lists_name_and_label`: `[{'name': 'google', 'label': 'Google'}]`,
  exactly.
- `test_providers_is_empty_with_none_enabled`: `app.config['OAUTH_PROVIDERS'] = {}`.

`start`:

- `test_start_redirects_with_state_nonce_and_pkce`: host, `client_id`, `redirect_uri`
  `https://app.test/api/v1/auth/oauth/google/callback`, `scope`, `response_type`,
  `prompt`, and `code_challenge_method`, with `code_challenge` matching the cookie's
  verifier.
- `test_start_sets_the_transaction_cookie`: its `Set-Cookie` over https.
- `test_start_over_http_uses_a_lax_cookie`: `app.config['PUBLIC_BASE_URL']` set to an
  http origin.
- `test_start_omits_pkce_for_a_provider_without_it`: inject
  `dataclasses.replace(provider, uses_pkce=False)`, and the callback sends no verifier.
- `test_start_links_when_the_account_page_asks`: `auth_client` and `begin_link`, and the
  transaction has `link_user_id` and `next_path == '/account'`.
- `test_start_does_not_link_without_being_asked`: `auth_client`, the same-origin header,
  and no `link`, so `link_user_id` is `None`. This is Context point 16.
- `test_start_refuses_a_link_it_cannot_prove`: `auth_client` and `link='1'`, parametrized
  on `cross-site`, `same-site`, `none`, and no header: a redirect to
  `/account?error=invalid_state`, and no transaction cookie.
- `test_start_refuses_a_link_without_a_session`: `link='1'` and the same-origin header,
  and a redirect to `/login?error=invalid_state`, since the Account page would send it
  there anyway. An Account tab left open after signing out elsewhere lands here.
- `test_start_signs_in_an_anonymous_visitor`: `link_user_id` is `None`, path `/`.
- `test_start_for_an_unknown_provider_redirects_to_login`.
- `test_unknown_provider_redirect_without_a_public_origin_stays_relative`.
- `test_start_response_headers_fit_nginx_default_buffer`: with `auth_client`, so the
  renewed session cookie counts, and `next` set to
  `'/' + secrets.token_urlsafe(MAX_NEXT_LENGTH)[:MAX_NEXT_LENGTH - 1]`, imported from the
  module, because zlib shrinks a repeated character to nothing. The sum over headers of
  name plus value plus four is under 3500.
- `test_callback_response_headers_fit_nginx_default_buffer`, parametrized on `next`:
  `/?q=` and 42 emoji arrive percent-encoded, while `/?q=` and 400 emoji, which a count
  of characters would keep, land on `/`. Each callback's headers stay under 3500.

The policy, each through the real exchange and token check:

- `test_callback_creates_a_passwordless_account`: redirect to `https://app.test/`; a user
  role, active account with no password; one `OAuthAccount`; after
  `g.pop('_login_user', None)`, `/me` answers that account.
- `test_new_account_is_audited`: `users` created and `oauth_accounts` created entries,
  each with no actor, and the `users` entry's `changes` as `test_auth.py` pins for
  registration.
- `test_callback_signs_in_the_linked_account`: `linked_user`, with a different email in
  the token, adds no row and no account.
- `test_callback_never_attaches_to_a_password_account`: `user`, redirect
  `/login?error=link_required`, no row, and `/me` answers 401 after the `g.pop`.
- `test_the_constant_relaxes_that_refusal`: monkeypatch `AUTO_LINK_PASSWORD_ACCOUNTS`.
- `test_callback_attaches_to_a_passwordless_account`: `passwordless_user`, one row.
- `test_a_second_identity_cannot_attach_by_email`: `linked_user`, another `sub`, the same
  email, `already_linked`, still one row.
- `test_an_unverified_email_is_refused`: `email_unverified`, parametrized on `False` and
  `'false'`, and no account is created.
- `test_an_unverified_email_never_matches_an_account`: `passwordless_user`, no row.
- `test_a_missing_email_is_refused`: `email_required`.
- `test_a_deactivated_linked_account_is_refused`: `/login?error=account_inactive`.
- `test_a_deactivated_passwordless_account_gains_no_link`: same code, no row.
- `test_a_signed_in_visitor_on_the_sign_in_page_signs_in`: `auth_client`, no `link`, and a
  different identity gets its own account, `user` gains no row, and `/me` after the
  `g.pop` answers the new account. This is Context point 16.
- `test_a_lost_race_is_already_linked`: persist the account, monkeypatch
  `oauth.find_user_by_email` to answer `None`, and the callback lands on
  `/login?error=already_linked`. A query afterwards still works, which needs the rollback.

Link mode:

Each of these starts with `begin_link`.

- `test_linking_attaches_to_the_signed_in_account`: `auth_client`, redirect
  `https://app.test/account`, one row on that user, audited with that user as the actor.
- `test_linking_works_without_the_session_cookie`: after `begin_link`, run
  `client.delete_cookie('session')` and `g.pop('_login_user', None)`, which is what a
  Strict cookie does; the row lands on the right account, the entry has no actor, and the
  callback signs that account in.
- `test_linking_ignores_the_email`: an unverified, and a missing, email still links.
- `test_linking_an_identity_another_account_holds_is_refused`:
  `/account?error=already_linked`.
- `test_linking_the_same_identity_again_changes_nothing`: success, one row.
- `test_linking_a_second_identity_of_a_provider_is_refused`: `already_linked`, one row.
- `test_linking_to_a_deactivated_account_is_refused`: deactivate after `begin_link`,
  `/account?error=account_inactive`, no row.
- `test_linking_to_a_deleted_account_is_refused`: delete after `begin_link`,
  `/account?error=account_inactive`, and the cookie is gone, because the code is spent.
- `test_logout_stops_a_link_in_progress`: `begin_link`, log out, and the callback answers
  `/login?error=expired`, with no row. This is Context point 11.

Failures another site can cause, each asserting the cookie is still there:

- `test_callback_for_an_unknown_provider`.
- `test_callback_without_a_cookie_is_expired`, which has no cookie to keep.
- `test_callback_with_the_wrong_state_is_invalid`, and with non-ASCII state.
- `test_callback_with_a_tampered_cookie_is_invalid`.
- `test_callback_for_another_providers_transaction_is_invalid`: register a second provider
  in `app.config['OAUTH_PROVIDERS']` with `dataclasses.replace`, and call its callback.
- `test_a_forged_callback_leaves_the_sign_in_in_progress`: after the wrong state, the real
  callback still succeeds.
- `test_the_second_of_two_tabs_finishes`: two `begin` calls; the first's callback is
  `invalid_state`, and the second's succeeds.
- `test_an_error_with_the_wrong_state_is_invalid_not_cancelled`: state first.

The other failures, each asserting the cookie is gone afterwards:

- `test_a_declined_consent_is_cancelled`: `error=access_denied`, and it posts no token
  request.
- `test_another_provider_error_is_exchange_failed`.
- `test_a_callback_without_a_code_is_exchange_failed`.
- `test_a_refused_code_is_exchange_failed`: the token endpoint answers 400.
- `test_a_token_for_another_nonce_is_invalid_token`.

Transport:

- `test_callback_accepts_a_post_without_the_spa_header`: pop `HTTP_X_REQUESTED_WITH` and
  post the form, which ends in a session.
- `test_callback_clears_the_transaction_cookie`.
- `test_callback_sends_the_transactions_verifier`: the token POST's form body carries the
  `code_verifier` that `transaction_in` read before the callback.
- `test_next_is_honoured`: `begin(client, next='/widgets/1?tab=2#x')`, which reaches the
  server whole only because the test client encodes it.
- `test_next_is_sanitized`: `next='//evil.example'` lands on `https://app.test/`.
- `test_callback_works_with_the_production_cookie_settings`: `app.config.update(
  SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=True)`; the callback's session
  `Set-Cookie` holds `SameSite=Strict` and `Secure`, and `/me` answers after the `g.pop`.

Linked accounts:

- `test_accounts_needs_a_session`: 401.
- `test_accounts_lists_only_the_callers_links`: another account's link stays out, and no
  item has `provider_user_id` or `user_id`.
- `test_unlink_removes_the_link`: 204, audited with the signed-in actor; needs a password
  account with a link.
- `test_unlink_of_a_provider_not_linked_is_404`.
- `test_unlink_of_the_last_method_is_409`: `linked_user`, signed in by a real callback,
  since it has no password; the message is `LAST_METHOD`, and the row stays.
- `test_unlink_needs_a_session`: 401.

### src_back/tests — the existing files

`test_app.py`:

- `test_the_environment_enables_a_provider`: set both keys with `monkeypatch`, and
  `create_app({...})` has `list(config['OAUTH_PROVIDERS']) == ['google']`.
- `test_no_provider_is_enabled_without_keys`.
- `test_no_provider_is_enabled_without_a_public_origin`: set the keys, then as
  `test_public_base_url_is_none_with_a_warning_outside_development` does.
- `test_an_injected_registry_wins_over_the_environment`.
- `test_the_provider_callback_needs_no_requested_with_header`: pop the header; a POST is
  not 403.
- `test_the_linked_account_routes_still_need_the_header`: pop the header; a DELETE to
  `/api/v1/auth/oauth/accounts/google` is 403 with the existing message.

`test_auth.py`:

- `test_count_sign_in_methods_counts_each_linked_provider`: `linked_user` is 1, and a
  password on it makes 2.
- `test_require_another_sign_in_method`: `linked_user` raises with `LAST_METHOD`, and a
  password on it passes.
- `test_logout_clears_the_transaction_cookie`: the logout response's `Set-Cookie` deletes
  `__Host-oauth_txn`, with `Path=/` and `Secure`.

`test_errors.py`: `test_oauth_error_keeps_its_code`.

`test_schemas.py`: `test_oauth_account_schema_hides_the_provider_subject`, which also
checks `created_at` carries a UTC offset, and
`test_oauth_provider_schema_dumps_name_and_label` with its keys exactly `{'name',
'label'}`, so no secret can leak.

### src_front/src/types/auth.ts — two types

Above `isAdmin`:

```ts
/** A sign-in provider the server has enabled. */
export interface OAuthProviderInfo {
    name: string
    label: string
}

/** A provider identity linked to the signed-in account. */
export interface LinkedAccount {
    id: number
    uuid: string
    provider: string
    /** The address the provider gave, which may differ from the account's. */
    email: string | null
    display_name: string | null
    created_at: string
    updated_at: string
}
```

### src_front/src/api/oauth.ts — new

```ts
/** @file Sign-in providers and the accounts linked through them. */

import type { LinkedAccount, OAuthProviderInfo } from '../types/auth'
import client from './client'

/** Where the provider endpoints live, relative to the API base. */
const OAUTH_URL = '/v1/auth/oauth'

/**
 * Fetch the sign-in providers the server has enabled.
 *
 * @returns Each provider's name and label; empty when none is enabled.
 */
export async function listProviders(): Promise<OAuthProviderInfo[]> {
    const { data } = await client.get<OAuthProviderInfo[]>(`${OAUTH_URL}/providers`)
    return data
}

/**
 * Fetch the signed-in account's linked providers.
 *
 * @returns The links, in provider order.
 */
export async function listLinkedAccounts(): Promise<LinkedAccount[]> {
    const { data } = await client.get<LinkedAccount[]>(`${OAUTH_URL}/accounts`)
    return data
}

/**
 * Remove the signed-in account's link to a provider.
 *
 * @param provider - The provider's name.
 * @returns A promise that settles when the link is gone; it rejects with the server's
 *   message when the provider is the account's last way to sign in.
 */
export async function unlinkAccount(provider: string): Promise<void> {
    await client.delete(`${OAUTH_URL}/accounts/${encodeURIComponent(provider)}`)
}
```

### src_front/src/utils/oauth.ts — new

```ts
/** @file The link that starts a provider sign-in, and the messages for its failures. */

/** A `Map`, so a crafted `?error=__proto__` finds no inherited property to render. */
const ERROR_MESSAGES = new Map([
    ['unknown_provider', 'That sign-in provider is not available.'],
    ['cancelled', 'Sign-in was cancelled.'],
    ['invalid_state', 'That sign-in could not be verified. Please try again.'],
    ['expired', 'That sign-in took too long. Please try again.'],
    ['exchange_failed', 'The sign-in provider could not finish. Please try again.'],
    ['invalid_token', 'The sign-in could not be verified. Please try again.'],
    ['email_required', 'The sign-in provider did not share an email address.'],
    ['email_unverified', 'Verify your email with the sign-in provider, then try again.'],
    [
        'link_required',
        'That email already has an account. Sign in, then link it from Account.',
    ],
    ['already_linked', 'That account is already linked to a sign-in provider.'],
    ['account_inactive', 'Account is inactive.'],
])

/** What to show for a code this build does not know. */
const FALLBACK_MESSAGE = 'Sign-in failed. Please try again.'

/**
 * Build the link that starts a sign-in.
 *
 * It is a plain URL rather than an API call: the browser leaves the page for the
 * provider, so it includes the `/api` prefix the axios client would add.
 *
 * @param name - The provider's name.
 * @param next - The path to return to.
 * @returns The URL to navigate to.
 */
export function startUrl(name: string, next?: string): string {
    const query = next ? `?next=${encodeURIComponent(next)}` : ''
    return `/api/v1/auth/oauth/${encodeURIComponent(name)}/start${query}`
}

/**
 * Build the link that attaches a provider to the signed-in account.
 *
 * A session alone is not enough for the server to link, so this link asks for it.
 *
 * @param name - The provider's name.
 * @returns The URL to navigate to.
 */
export function linkUrl(name: string): string {
    return `${startUrl(name, '/account')}&link=1`
}

/**
 * Turn the `error` query parameter a failed provider sign-in redirects with into text.
 *
 * The code itself is never shown, since anyone can write it into a link.
 *
 * @param code - The parameter's value, or null when it is absent.
 * @returns The message to show, or null when there is no code.
 */
export function oauthErrorMessage(code: string | null): string | null {
    if (!code) return null
    return ERROR_MESSAGES.get(code) ?? FALLBACK_MESSAGE
}
```

### src_front/src/hooks/useProviders.ts — new

```ts
/** @file The sign-in providers the server has enabled. */

import { useEffect, useState } from 'react'

import { listProviders } from '../api/oauth'
import type { OAuthProviderInfo } from '../types/auth'

/**
 * Load the enabled providers once.
 *
 * The list goes in local state rather than a query, as in `EnvironmentBadge`:
 * `useSessionQueryCache` clears every query when the account changes, which would
 * cancel the fetch during sign-in. A failure leaves the list empty, so the sign-in
 * pages fall back to the password form.
 *
 * @returns The providers; empty until they load, and after a failure.
 */
export function useProviders(): OAuthProviderInfo[] {
    const [providers, setProviders] = useState<OAuthProviderInfo[]>([])

    useEffect(() => {
        void listProviders()
            .then(setProviders)
            .catch(() => undefined)
    }, [])

    return providers
}
```

### src_front/src/hooks/oauth.ts — new

```ts
/** @file Server state for the accounts linked through sign-in providers. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { listLinkedAccounts, unlinkAccount } from '../api/oauth'

/** Cache key for the signed-in account's links. */
const LINKED_ACCOUNTS_KEY = ['linked-accounts'] as const

/**
 * Load the signed-in account's linked providers.
 *
 * @returns The query holding the links.
 */
export const useLinkedAccounts = () =>
    useQuery({ queryKey: LINKED_ACCOUNTS_KEY, queryFn: listLinkedAccounts })

/**
 * Build the mutation that removes a link, by provider name.
 *
 * @returns The mutation, which refreshes the links on success.
 */
export function useUnlinkAccount() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: unlinkAccount,
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: LINKED_ACCOUNTS_KEY })
        },
    })
}
```

### src_front/src/components/auth/ProviderButtons.tsx — new

```tsx
/** @file The "Continue with" buttons on the sign-in and registration pages. */

import { Button, Divider, Stack } from '@mui/material'

import { useProviders } from '../../hooks/useProviders'
import { startUrl } from '../../utils/oauth'

/** Props accepted by {@link ProviderButtons}. */
interface ProviderButtonsProps {
    next: string
}

/**
 * Render one link per enabled provider, behind an "or" divider.
 *
 * Each is a plain anchor, because the browser leaves the page for the provider. With
 * no provider enabled it renders nothing, divider included, so the page stays as it
 * was.
 *
 * @param props - The component props.
 * @param props.next - The path to return to after signing in.
 * @returns The buttons, or null.
 */
export default function ProviderButtons({ next }: ProviderButtonsProps) {
    const providers = useProviders()
    if (providers.length === 0) return null
    return (
        <Stack spacing={1} sx={{ mt: 2 }}>
            <Divider>or</Divider>
            {providers.map(({ name, label }) => (
                <Button
                    key={name}
                    variant="outlined"
                    fullWidth
                    href={startUrl(name, next)}
                >
                    Continue with {label}
                </Button>
            ))}
        </Stack>
    )
}
```

### src_front/src/components/AuthFormLayout.tsx — the slot and `autoComplete`

Add `autoComplete?: string` to `AuthTextFieldProps`, documented as
"`@param props.autoComplete` - The browser's autofill hint, if any.", and pass
`autoComplete={autoComplete}` to the `TextField`. The signature now passes 90 columns, so
Prettier wants it on several lines:

```tsx
export function AuthTextField({
    registration,
    label,
    type,
    error,
    autoComplete,
}: AuthTextFieldProps) {
```

Add `secondary?: ReactNode` to `AuthFormLayoutProps`, documented as
"`@param props.secondary` - Other ways to sign in, shown beneath the submit button.", and
render `{secondary}` between the submit `Button` and the footer `Typography`.

### src_front/src/hooks/useAuthFormState.ts — the redirect's error and the return path

Import `useSearchParams` beside `useLocation`, and `oauthErrorMessage` from
`../utils/oauth`. In `useAuthFormState`:

```ts
    const [params] = useSearchParams()
```

and replace the return, with the JSDoc's `@returns` updated to say `apiError` falls back
on the message for the `error` parameter a failed provider sign-in redirects with, and
that `returnPath` is where a provider sign-in should come back to:

```ts
    return {
        apiError: apiError ?? oauthErrorMessage(params.get('error')),
        handleAuthAction,
        returnPath: requestedPath(location.state),
    }
```

### src_front/src/pages/Login.tsx and Register.tsx — the slot

`Login()` has 46 of its 50 lines, which is why the error and the path come from
`useAuthFormState`. It ends at 49. In `Login.tsx`, import `ProviderButtons`, destructure
`returnPath`, and add to `AuthFormLayout`:

```tsx
            secondary={<ProviderButtons next={returnPath} />}
```

Add `autoComplete="email"` and `autoComplete="current-password"` to its two fields.
`Register.tsx` takes the same `secondary` line and destructuring, and `RegisterFields`
gains `autoComplete="email"`, and `autoComplete="new-password"` on both password fields.

### src_front/src/components/account/LinkedAccounts.tsx — new

```tsx
/** @file The Account page's section for linking and unlinking sign-in providers. */

import {
    Alert,
    Box,
    Button,
    List,
    ListItem,
    ListItemText,
    Stack,
    Typography,
} from '@mui/material'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useLinkedAccounts, useUnlinkAccount } from '../../hooks/oauth'
import { useProviders } from '../../hooks/useProviders'
import type { LinkedAccount, OAuthProviderInfo } from '../../types/auth'
import { linkUrl, oauthErrorMessage } from '../../utils/oauth'
import ConfirmDialog from '../common/ConfirmDialog'
import QueryState from '../common/QueryState'

/** Props accepted by {@link LinkedProviders}. */
interface LinkedProvidersProps {
    linked: LinkedAccount[]
    providers: OAuthProviderInfo[]
    labelFor: (provider: string) => string
    onUnlink: (account: LinkedAccount) => void
}

/**
 * Render the account's links, then a link button for each provider it lacks.
 *
 * @param props - The component props.
 * @returns The list and the buttons.
 */
function LinkedProviders(props: LinkedProvidersProps) {
    const { linked, providers, labelFor, onUnlink } = props
    const unlinked = providers.filter(
        ({ name }) => !linked.some(({ provider }) => provider === name),
    )
    return (
        <>
            {linked.length === 0 && (
                <Typography color="text.secondary">No providers are linked.</Typography>
            )}
            <List disablePadding>
                {linked.map((account) => (
                    <ListItem
                        key={account.provider}
                        divider
                        secondaryAction={
                            <Button
                                aria-label={`Unlink ${labelFor(account.provider)}`}
                                onClick={() => onUnlink(account)}
                            >
                                Unlink
                            </Button>
                        }
                    >
                        <ListItemText
                            primary={labelFor(account.provider)}
                            secondary={account.email}
                        />
                    </ListItem>
                ))}
            </List>
            <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap' }}>
                {unlinked.map(({ name, label }) => (
                    <Button key={name} variant="outlined" href={linkUrl(name)}>
                        Link {label}
                    </Button>
                ))}
            </Stack>
        </>
    )
}

/** Props accepted by {@link UnlinkDialog}. */
interface UnlinkDialogProps {
    account: LinkedAccount | null
    labelFor: (provider: string) => string
    onClose: () => void
}

/**
 * Confirm removing a link; a refusal stays open and shows the server's message.
 *
 * @param props - The component props.
 * @returns The confirmation, open while an account is chosen.
 */
function UnlinkDialog(props: UnlinkDialogProps) {
    const { account, labelFor, onClose } = props
    const unlink = useUnlinkAccount()
    // In production builds the React Compiler compares the paths confirm reads while
    // rendering, when account is still null, so the provider is read safely here.
    const provider = account?.provider

    /** Remove the chosen link, then close the confirmation. */
    const confirm = async () => {
        // Unlink is clickable only while open, and it is open only with an account.
        await unlink.mutateAsync(provider!)
        onClose()
    }

    return (
        <ConfirmDialog
            open={account !== null}
            title="Unlink provider"
            message={account ? `Stop using ${labelFor(account.provider)}?` : ''}
            confirmLabel="Unlink"
            onCancel={onClose}
            onConfirm={confirm}
        />
    )
}

/**
 * Show the providers the account can sign in with, and let it link and unlink them.
 *
 * A failed link returns here with `?error=`, shown above the list. A link to a provider
 * since disabled shows its name.
 *
 * @returns The section element.
 */
export default function LinkedAccounts() {
    const accounts = useLinkedAccounts()
    const providers = useProviders()
    const [params] = useSearchParams()
    const [unlinking, setUnlinking] = useState<LinkedAccount | null>(null)
    const linkError = oauthErrorMessage(params.get('error'))

    /**
     * Name a provider for the viewer.
     *
     * @param provider - The provider's name.
     * @returns Its label, or the name when it is no longer enabled.
     */
    const labelFor = (provider: string) =>
        providers.find(({ name }) => name === provider)?.label ?? provider

    return (
        <Box component="section">
            <Typography variant="h6" component="h2" gutterBottom>
                Sign-in providers
            </Typography>
            {linkError && (
                <Alert severity="error" sx={{ mb: 2 }}>
                    {linkError}
                </Alert>
            )}
            <QueryState query={accounts}>
                {(linked) => (
                    <LinkedProviders
                        linked={linked}
                        providers={providers}
                        labelFor={labelFor}
                        onUnlink={setUnlinking}
                    />
                )}
            </QueryState>
            <UnlinkDialog
                account={unlinking}
                labelFor={labelFor}
                onClose={() => setUnlinking(null)}
            />
        </Box>
    )
}
```

### src_front/src/pages/Account.tsx — new

```tsx
/** @file The signed-in account's own page. */

import { Container, Typography } from '@mui/material'

import LinkedAccounts from '../components/account/LinkedAccounts'

/**
 * Render the account page, which later sections, such as passkeys, join.
 *
 * @returns The account page element.
 */
export default function Account() {
    return (
        <Container maxWidth="sm" sx={{ py: 4 }}>
            <Typography variant="h4" component="h1" gutterBottom>
                Account
            </Typography>
            <LinkedAccounts />
        </Container>
    )
}
```

### src_front/src/App.tsx and AppShell.tsx — the route and the link

In `App.tsx`, add `const Account = lazy(() => import('./pages/Account'))` above
`AdminPage`, and `<Route path="/account" element={<Account />} />` after the index route.
In `AppShell.tsx`, import `AccountCircleIcon from '@mui/icons-material/AccountCircle'` and
add `{ to: '/account', label: 'Account', icon: <AccountCircleIcon /> }` between Home and
Admin.

### src_front/src/api/client.ts — a 401 from the linked accounts is a lost session

Replace `reportLostSession`:

```ts
/**
 * Run the registered handler when a request was refused for want of a session.
 *
 * A 401 from the auth endpoints themselves is skipped: a wrong password is a form
 * error, not a lost session. The linked accounts under `/v1/auth/oauth/` are ordinary
 * signed-in requests, so their 401 counts.
 *
 * @param error - The rejection axios produced for a failed request.
 * @returns A promise rejected with the same error.
 */
function reportLostSession(error: AxiosError): Promise<never> {
    const url = error.config?.url
    const isAuthEndpoint =
        url?.startsWith('/v1/auth/') && !url.startsWith('/v1/auth/oauth/')
    if (error.response?.status === 401 && !isAuthEndpoint) {
        unauthorizedHandler?.()
    }
    return Promise.reject(error)
}
```

### Frontend tests

`test/utils/fixtures.ts` gains `googleProvider: OAuthProviderInfo` and
`linkedGoogleAccount: LinkedAccount`.

`test/api/client.test.ts`: `report a 401 from the linked accounts`, beside the existing
`do not report a 401 from the auth endpoints`, which stays and pins the other side.

`test/api/oauth.test.ts`, with the client mocked as `test/api/auth.test.ts` does: each
function's URL and unwrapped data, and `unlinkAccount` encodes the name.

`test/utils/oauth.test.ts`: `startUrl` with and without `next`, encoding `?` and `#`;
`linkUrl` ends `?next=%2Faccount&link=1`; `oauthErrorMessage` gives a message for all
eleven codes, parametrized so none is missed, `null` for `null` and `''`, and the fallback
for `nope`, `__proto__`, and `constructor`.

`test/hooks/useProviders.test.tsx`, with `vi.mock('../../api/oauth')`: empty, then loaded;
empty after a rejection, with no unhandled rejection; and one fetch across a rerender.

`test/hooks/oauth.test.tsx`, following `test/hooks/users.test.tsx`: the query loads; the
mutation calls `unlinkAccount` with the name and invalidates the key, spying on
`client.invalidateQueries`.

`test/components/auth/ProviderButtons.test.tsx`: `findByRole('link', { name: 'Continue
with Google' })`, its `href` carrying the encoded `next`; and with an empty list, after
`waitFor` sees the call, no link and no `separator` role.

`test/components/account/LinkedAccounts.test.tsx`, through `renderWithProviders` with
`route` and `path`, mocking `../../../api/oauth`:

- lists a link with its label and email;
- shows the provider's name when it is no longer enabled;
- offers only providers not linked, with `href` ending `next=%2Faccount&link=1`;
- says no providers are linked, and still offers the link button;
- shows the message for `?error=already_linked`, and no alert without one;
- unlinks after confirming, closes the dialog, and refetches;
- does nothing on Cancel;
- keeps the dialog open with the server's message on a refusal;
- shows the query's error through `QueryState`.

`test/pages/Account.test.tsx`: the heading and the section's heading.

`test/pages/Login.test.tsx`: add `vi.mock('../../api/oauth')`, and in `beforeEach`
`vi.mocked(listProviders).mockReturnValue(new Promise(() => undefined))`, the pattern
`App.test.tsx` uses for `getHealth`, so the existing tests see no provider and no state
update after they end. `renderLogin` gains a `search` argument. New tests: the alert for
`?error=link_required`; a failed password attempt replacing that message, with one alert;
the button's `href` carrying the guard's recorded page; no button and no `separator` for
an empty list; and the two `autocomplete` attributes.

`test/pages/Register.test.tsx`: the same mock and default; the button, and the three
`autocomplete` attributes.

`test/App.test.tsx`: add `vi.mock('../api/oauth')`, the same default for `listProviders`,
and `listLinkedAccounts` resolving `[]`; `/account` renders the page when signed in, and
redirects to the sign-in page when signed out.

`test/components/layout/AppShell.test.tsx`: add `Account` to the soft list at line 113 and
assert its link, and add an `/account` route to `renderShell` with a test that the link
has `aria-current="page"` there.

### .env.example, the Compose files, and provisioning

In `.env.example`, between `WEBAUTHN_RP_NAME=` and the mail heading:

```text
# --- Sign-in providers (ai/auth.md) ---------------------------------------------
# A provider appears on the sign-in pages once both of its keys are set. Register
# PUBLIC_BASE_URL + /api/v1/auth/oauth/<provider>/callback with the provider, once per
# environment and dev port; here, http://localhost:5174/api/v1/auth/oauth/google/callback.
OAUTH_GOOGLE_CLIENT_ID=
OAUTH_GOOGLE_CLIENT_SECRET=
```

In `.env.staging.example`, change the header's `fill in every blank but SMTP_HOST` to
`fill in every blank but SMTP_HOST and OAUTH_GOOGLE_*`, rewrapped, and add after the mail
section:

```text
# --- Sign-in providers (ai/auth.md) ---------------------------------------------
# Optional. Blank keeps Google off here. To try it, register
# https://<DOMAIN>/api/v1/auth/oauth/google/callback with the Google client.
OAUTH_GOOGLE_CLIENT_ID=
OAUTH_GOOGLE_CLIENT_SECRET=
```

In `docker-compose.yml` and `docker/docker-compose.prod.yml`, after each `SMTP_FROM` line.
The `environment` block is an allowlist, so an unlisted variable never reaches the
backend:

```yaml
      OAUTH_GOOGLE_CLIENT_ID: ${OAUTH_GOOGLE_CLIENT_ID:-}
      OAUTH_GOOGLE_CLIENT_SECRET: ${OAUTH_GOOGLE_CLIENT_SECRET:-}
```

In `scripts/provision.sh`, inside the unquoted heredoc after `SMTP_FROM=`:

```text

# --- Sign-in providers (ai/auth.md) ---------------------------------------------
# Google appears on the sign-in pages once both keys are set. Register
# https://$DOMAIN/api/v1/auth/oauth/google/callback with the Google client.
OAUTH_GOOGLE_CLIENT_ID=
OAUTH_GOOGLE_CLIENT_SECRET=
```

and after the `Mail stays off` line:

```bash
  echo "    Google sign-in stays off until OAUTH_GOOGLE_* are filled in."
```

### scripts/tests — the three tests

`test-provision.sh`, after the `SMTP_FROM` assertion, and beside the mail output
assertion:

```bash
assert_contains '^OAUTH_GOOGLE_CLIENT_ID=$' "$ENV_FILE"
assert_contains '^OAUTH_GOOGLE_CLIENT_SECRET=$' "$ENV_FILE"
assert_contains '^# https://example\.com/api/v1/auth/oauth/google/callback ' "$ENV_FILE"
```

```bash
assert_contains 'Google sign-in stays off' "$OUTPUT"
```

`test-deploy.sh`, beside the `SMTP_HOST` assertion on the staging example:

```bash
assert_contains '^OAUTH_GOOGLE_CLIENT_ID=$' "$STAGING_EXAMPLE"
assert_contains '^OAUTH_GOOGLE_CLIENT_SECRET=$' "$STAGING_EXAMPLE"
```

`test-compose-config.sh`: in the header comment, `SMTP_* variables` becomes
`SMTP_* and OAUTH_GOOGLE_* variables`, rewrapped. Add both names to the `unset`. After the
`dev-smtp` block:

```bash
(
  export OAUTH_GOOGLE_CLIENT_ID=google-id OAUTH_GOOGLE_CLIENT_SECRET=google-secret
  render > "$TEST_DIR/dev-oauth.json"
  render -f docker-compose.yml -f docker/docker-compose.prod.yml \
    > "$TEST_DIR/prod-oauth.json"
)
```

and inside the `for stack in dev prod` loop:

```bash
  check "$stack" '.services.backend.environment | .OAUTH_GOOGLE_CLIENT_ID == ""
    and .OAUTH_GOOGLE_CLIENT_SECRET == ""' \
    'blank OAUTH_GOOGLE_* variables, which leave Google sign-in off'
  check "$stack-oauth" '.services.backend.environment
    | .OAUTH_GOOGLE_CLIENT_ID == "google-id"
    and .OAUTH_GOOGLE_CLIENT_SECRET == "google-secret"' \
    'the OAUTH_GOOGLE_* variables its .env gives passed through to the backend'
```

### ai/auth.md — the runbook

Replace the Overview's first paragraph:

```text
Accounts sign in with an email and a password through `src_back/api/auth.py` and
`src_back/services/auth.py`, or through a sign-in provider (below). #30, #31, and passkeys
(#32) build on the same groundwork:
```

In the `complete_login` bullet, "which every caller answers with 403" becomes "which the
JSON routes answer with 403 and the provider callback with `account_inactive`". In
"Deactivated accounts", "A fresh login answers 403 `Account is inactive.` after the
password check" gains ", and a provider sign-in lands on
`/login?error=account_inactive`". Replace the `count_sign_in_methods` bullet:

```text
- `count_sign_in_methods(user)` counts the ways an account can sign in. Code that removes
  one calls `require_another_sign_in_method(user)` first, which raises
  `LastSignInMethodError` (409) instead of removing the last.
```

Replace the paragraph that begins "An account without a password is trusted":

```text
An account without a password is trusted to own its email address as far as the sign-in
provider that created it verified the address, and "The linking policy" says how far that
goes. Any new way to create such an account, such as an invitation or a passkey-first
sign-up, must verify the address first; otherwise linking a provider by email would hand
the account to whoever created it.
```

Replace the bullet's last sentence about Sign in with Apple:

```text
- Every POST under `/api` must carry `X-Requested-With: XMLHttpRequest`
  (`ai/conventions.md`). A provider's callback may arrive as a cross-site POST without it,
  as Sign in with Apple's `form_post` will (#30), so `oauth.callback` is exempt and checks
  its signed `state` instead.
```

Add this section after the Overview, before "Sign-in throttling":

````markdown
## Sign-in providers

A `Continue with <provider>` button runs the OAuth 2.0 and OpenID Connect
authorization-code flow on the backend. No token reaches the browser and none is stored.
A provider is enabled when its keys are set and `PUBLIC_BASE_URL` is known; with none
enabled, `/providers` answers `[]` and the sign-in pages show only the password form.
Google is the first provider. A new one is one `OAuthProvider` and one identity function
in `src_back/services/oauth_providers.py`.

### The flow

1. Login and Register render one link per enabled provider to
   `GET /api/v1/auth/oauth/<provider>/start?next=/path`. It is a full-page navigation, so
   this route and `callback` answer with redirects, never the JSON envelope.
2. `start` reads the session only when asked. `?link=1` on a same-origin navigation by a
   signed-in visitor, which is what the Account page's link sends, is linking, and `next`
   defaults to `/account`. Any other `?link=1` is refused with `invalid_state`, not run as
   a sign-in, which would leave the identity on a second account nothing can move it
   from. The refusal lands on the Account page, or on the sign-in page when no session
   remains, as when an Account tab outlives a sign-out elsewhere. Without `?link=1`,
   anyone is signing in, even with a live session, which `complete_login` replaces, and
   `next` defaults to `/`. It stores a transaction in the cookie below and redirects to
   the provider with `state`, `nonce`, and a PKCE challenge.
3. The provider sends the browser back to `callback`, by GET, or by POST for Sign in with
   Apple (#30). The callback trusts only the cookie: it compares `state`, exchanges the
   code, checks the ID token, resolves the account, and calls `complete_login`.
4. It clears the cookie and redirects to `PUBLIC_BASE_URL + next`. A failure redirects to
   `/login?error=<code>`, or `/account?error=<code>` when linking, and the page shows the
   message `src_front/src/utils/oauth.ts` holds for that code.

| Code               | Meaning                                                       |
| ------------------ | ------------------------------------------------------------- |
| `unknown_provider` | No enabled provider has that name                             |
| `cancelled`        | The person declined at the provider                           |
| `invalid_state`    | The answer or link request does not belong to this browser    |
| `expired`          | The transaction's cookie is gone or more than ten minutes old |
| `exchange_failed`  | The provider refused the code or could not be reached         |
| `invalid_token`    | The ID token, or the keys to check it, failed validation      |
| `email_required`   | The provider gave no email                                    |
| `email_unverified` | The provider has not verified the email                       |
| `link_required`    | The email belongs to an account with a password               |
| `already_linked`   | The identity, or the account's slot for it, is already taken  |
| `account_inactive` | The account has been deactivated or no longer exists          |

A failed token exchange or key fetch logs a warning; a wrong client secret shows up there
and nowhere else.

### The transaction cookie

Production's session cookie is `SameSite=Strict`, and browsers never send such a cookie on
a navigation another site started, which is what the provider's redirect is. There is no
Redis, and gunicorn's workers share no memory. So `src_back/services/oauth_state.py` keeps
the transaction in a cookie of its own: signed with `SECRET_KEY`, `HttpOnly`, and good for
ten minutes. It holds nothing the browser's owner should not see. The callback's response
stores the session cookie. The browser may leave it off the redirect that follows, which
is harmless, because the SPA's `/me` call is same-site.

Over https the cookie is `__Host-oauth_txn`, with `SameSite=None; Secure` and `Path=/`.
`SameSite=None` lets a cross-site POST carry it. The signature proves this server issued a
transaction, not that it issued it to this browser, so the prefix does the rest: browsers
refuse such a cookie from a sibling host or plain http, which stops anyone planting their
own signed transaction and linking a victim's identity to their account. The session
cookie has no such prefix, so a sibling host can still sign a visitor in as someone else.
Over http the cookie is `oauth_txn`, `SameSite=Lax`, under `/api/v1/auth/oauth`, which a
GET callback still carries.

A callback that proved it belongs to the transaction clears the cookie, whatever the
outcome. One that did not leaves it, because any site can send a browser to the callback,
and that must not end a sign-in in progress. So two `start` requests in one browser
overwrite the cookie, the first callback fails with `invalid_state`, and the second
succeeds. Logging out clears the cookie too, so a link started before a sign-out cannot
finish after it.

The callback's GET is not throttled, because nginx counts only POSTs. One valid cookie can
replay it for ten minutes, and each replay holds a sync worker for a round trip to the
provider. A `limit_req` for it needs a location per provider, which is its own issue.

### The linking policy

`resolve_user()` in `src_back/services/oauth.py` fails closed:

1. A link matches the provider and its subject: sign in that account. While linking, one
   held by another account is `already_linked`. The subject decides, never the email: an
   address can change hands.
2. While linking: attach to the account that started the transaction, whatever the email
   says. An account has one link per provider, so a second is `already_linked`.
3. No email is `email_required`, and an unverified one is `email_unverified`.
4. A verified email with no account creates one, with no password and the `user` role.
5. A verified email on an account without a password attaches and signs in: that account's
   email was itself asserted by a provider that verified it.
6. A verified email on an account with a password is `link_required`. Registration never
   verifies an address, so auto-linking would let anyone who registered the victim's
   address keep a working password to the merged account. Sign in with the password, then
   link from the Account page. A project that verifies addresses at registration can set
   `AUTO_LINK_PASSWORD_ACCOUNTS`.

Rules 4 and 5 take the provider's word. Google warns that `email_verified` records a past
check: for an address outside `@gmail.com` and Google Workspace, "ownership of the third
party email account may have since changed", and it recommends another challenge
([Google](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token)).
So rule 4 can create an account for a stale address, and the real owner's registration
then answers 409, which is no worse than anyone registering that address today. Rule 5
cannot fire while Google is the only provider, because every account without a password
already holds its Google link. Decide it when adding a second provider: dropping rule 5,
so that every existing account answers `link_required`, needs nothing stored beforehand.

Link mode needs that same-origin request as well as the session, so another site cannot
start it, and a stale session cannot turn a sign-in into a link. Every link and unlink is
audited in `oauth_accounts`, admin-only, and a link made in the callback has no actor in
production, because the session does not reach it there. Unlinking the last way to sign in
is a 409.

Linking asks for no password or other fresh proof, and a link survives a password change.
To clear a compromised account, deactivate it and read its links' history on the Audit
tab. Filter by the `oauth_accounts` table rather than by user, because a link made in the
production callback has no actor, and match each entry's `user_id` to the account. Then
remove any link its owner does not recognize in a database shell before reactivating it:

```sql
DELETE FROM oauth_accounts WHERE user_id = <id> AND provider = '<provider>';
```

### Setting up Google

1. In the Google Cloud console, create an OAuth client of type Web application.
2. Add one authorized redirect URI per environment:
   `PUBLIC_BASE_URL + /api/v1/auth/oauth/google/callback`. The match is exact, including
   the port, and `scripts/worktree-setup.sh` moves the dev port per worktree, so register
   each one in use; any other shows `redirect_uri_mismatch` on Google's page.
3. `openid email profile` are non-sensitive scopes, so no app verification is needed.
   Publish the consent screen out of Testing, or only its test users can sign in. Showing
   the app's name and logo there takes Google's lighter
   [brand verification](https://support.google.com/cloud/answer/9110914).
4. Set `OAUTH_GOOGLE_CLIENT_ID` and `OAUTH_GOOGLE_CLIENT_SECRET` in the `.env`. Compose
   hands a container its values only when it creates one, so run `npm run deploy` on a
   server after changing them. A server provisioned before this has no such lines, which
   leaves Google off.
````

### ai/conventions.md, ai/domain.md, ai/project.md, ai/staging.md

`ai/conventions.md`:

- In the bullet on `services/errors.py`, add: "`OAuthError` differs: the provider routes
  answer it with a redirect carrying its code, and `InactiveAccountError` there with the
  code `account_inactive`."
- In the bullet on deactivated accounts, "so the 403 never tells a stranger" becomes "so
  the refusal never tells a stranger".
- Replace the `X-Requested-With` bullet's last sentence with: "A route that must accept a
  cross-site POST is named in `_CROSS_SITE_POST_ENDPOINTS` in `app.py` and checks its own
  signed `state` instead; `oauth.callback`, which Sign in with Apple's `form_post` answer
  reaches (#30), is the only one."
- In API Responses, after the errors bullet: "`start` and `callback` under
  `/api/v1/auth/oauth` are the one exception to that envelope: they are browser
  navigations, so every outcome is a redirect, and a failure lands on
  `/login?error=<code>` or `/account?error=<code>` (`ai/auth.md`)."
- In the Frontend bullet on TanStack Query, add: "A public value a signed-out page needs,
  such as the deployment's environment or the enabled sign-in providers, is fetched once
  into local state instead (`EnvironmentBadge`, `useProviders`), because
  `useSessionQueryCache()` would cancel the query during sign-in."

`ai/domain.md`:

- Accounts: add "An `OAuthAccount` links a provider identity to an account, one per
  provider, matched on the provider's subject and never on its email
  (`src_back/services/oauth.py`, `ai/auth.md`)."
- Audit log: "Accounts are audited at registration, when a sign-in provider creates one,
  on the admin's Users screen, and by the seed, and each provider link in
  `oauth_accounts`; their history is admin-only, ...".
- Fixtures: `app` also has `PUBLIC_BASE_URL` `https://app.test` and Google enabled with
  fake keys. Add `linked_user` (a passwordless account linked to Google), `mocked_http` (a
  `responses.RequestsMock`), `oidc_signer` (signs ID tokens, and serves its key at
  Google's JWKS URL), `_clear_oauth_environment` and `_clear_jwks_cache` (autouse).

`ai/project.md`:

- `models/`: add "`oauth_account.py` holds `OAuthAccount`".
- `services/`: add "`services/oauth.py`, `oauth_providers.py`, `oauth_state.py`, and
  `oidc.py` sign-in through a provider".
- `components/`: add "`components/auth/` the provider buttons, and `components/account/`
  the Account page's sections".
- Environment, after the mail paragraphs, before `load_dotenv()`:

```text
Sign-in providers are off until their keys are set: `build_registry()` in
`src_back/services/oauth_providers.py` enables Google when `OAUTH_GOOGLE_CLIENT_ID` and
`OAUTH_GOOGLE_CLIENT_SECRET` are both set and `PUBLIC_BASE_URL` is known. A server
provisioned before these keys has no such lines, which leaves Google off. `ai/auth.md` has
the setup steps.
```

- Change the closing sentence to "`conftest.py` clears `APP_ENVIRONMENT`, the `SMTP_*`
  variables, and the `OAUTH_GOOGLE_*` keys for every test, so no test sends mail or
  reaches a provider through a developer's account."

`ai/staging.md`:

- In the list of differences, after the mail item: "sign-in providers, which stay off
  until `OAUTH_GOOGLE_*` is filled in, and need staging's own redirect URI registered with
  the provider;".
- Step 3 begins: "Fill in every blank in `.env` except `SMTP_HOST`, which stays blank so
  staging sends no mail, and the optional `OAUTH_GOOGLE_*` keys."
- After "Testers then sign in to staging with their production passwords.", add: "An
  account with no password, which a sign-in provider created, can sign in there only when
  staging has that provider's keys."

### tools.md and README.md

In `tools.md`, under Backend runtime libraries, before `**watchdog**`:

```markdown
- **requests**: the HTTP client for a provider sign-in's two server-side calls, the token
  exchange in `src_back/services/oauth.py` and the key fetch in `oidc.py`, each with a
  timeout.
- **joserfc**: validates a provider's ID token, signature and claims, in
  `src_back/services/oidc.py`. It brings `cryptography`, and Sign in with Apple's ES256
  client secret will need it too (#30). Authlib, which uses it, is not installed: its
  Flask client keeps state in the session, which the provider's redirect cannot read under
  a `SameSite=Strict` cookie.
```

Under Backend quality and test tools, after **pytest-cov**:

```markdown
- **responses**: replaces the `requests` transport in tests, so the token exchange and the
  key fetch run for real against canned answers (`mocked_http` in `conftest.py`).
```

In `README.md`'s layout: "Blueprints (health, auth, users, audit logs)" becomes
"Blueprints (health, auth, OAuth, users, audit logs)"; "Home, Login, Register, Admin"
becomes "Home, Login, Register, Account, Admin"; and the components line becomes:

```text
│       ├── components/  Shell, route guards, error boundaries, layout/, common/,
│       │                admin/, account/, auth/
```

## Parallelism

Implementers are Opus, as #27 records for this issue.

- **Must be sequential**: within Group A, the pins and their install come first, then
  `errors.py`, the model, and the migration, then `oauth_state.py`, `oidc.py`,
  `oauth_providers.py`, and `oauth.py`, each importing the one before; then the schemas,
  the API, `app.py`, and the tests. Nothing else in the backend imports until the pins are
  installed.
- **Can be done in parallel**, once Group A's pins are in:
    - Group A, the backend: everything under `src_back/` and `migrations/`, and the two
      requirements files.
    - Group B, the frontend: everything under `src_front/`. Every API call is mocked, so
      it needs nothing from Group A.
    - Group C, the configuration: `.env.example`, `.env.staging.example`, the two Compose
      files, `scripts/provision.sh`, and the three shell tests.
    - Group D, the documentation: `ai/`, `tools.md`, `README.md`. It describes the others,
      so its last act is checking each name it cites against their results.
- **Reads across groups**: `test-backend-image.sh`, unchanged, reads Group A's
  `requirements.txt` and `app.py`, so run it only after Group A.

### Mutation checks

Each group runs these on a scratch copy of the repository, never the real files, with a
timeout on each run, because a hang counts as a gap. Report survivors, and any extra
mutations tried, instead of adding tests the plan does not list. Each must fail a test.

Group A:

1. `set_transaction_cookie`: always `samesite='Lax'`; drop `httponly`.
   `_cookie_name_and_path`: always the plain name; always the narrow path.
   `clear_transaction_cookie`: drop `secure`.
2. `read_transaction`: treat `BadSignature` as `expired`; treat a missing cookie as
   `invalid_state`; drop `TypeError`.
3. `safe_next`: drop each of the four refusals in turn.
4. `state_matches`: compare without encoding; always `True`.
5. `verify_id_token`: drop `algorithms`; drop `iss`, `exp`, or `sub` from the registry;
   `leeway=0`; skip the nonce; drop the audience comparison; allow any listed audience.
6. `fetch_jwks`: ignore `refresh`; never expire; drop `raise_for_status`.
7. `_decode_signed_token`: no refetch on an unknown key.
8. `is_true_claim`: `bool(value)`.
9. `_google_provider`: `or` to `and`. `build_registry`: drop the origin check.
10. `build_authorize_url`: drop the challenge; drop `extra_authorize_params`.
11. `exchange_code`: drop the verifier; drop the dict check.
12. `_attach_account`: drop the active check; drop the provider check; drop the audit
    line.
13. `_create_user`: drop the audit line.
14. `_resolve_by_email`: swap the two refusals' order with the lookup; ignore
    `AUTO_LINK_PASSWORD_ACCOUNTS`; ignore `email_verified`.
15. `_resolve_user`: drop the other-account check; drop the deleted-account check.
    `resolve_user`: drop the `IntegrityError` catch; drop the rollback.
16. `unlink_account`: drop the guard; drop the audit line.
    `require_another_sign_in_method`: `<= 1` to `< 1`.
17. `count_sign_in_methods`: drop the links.
18. `_finish_sign_in`: drop the provider comparison; move the `error` check above the
    state check; send `exchange_code` no verifier.
19. `callback`: never set `link_mode`; drop `except InactiveAccountError`; do not clear
    the cookie on success. `_error_redirect`: never clear it; always clear it.
20. `start`: skip `safe_next`; ignore `link`; run a refused link as a sign-in.
    `_link_user_id`: ignore `Sec-Fetch-Site`.
21. `logout`: do not clear the cookie.
22. `app.py`: empty `_CROSS_SITE_POST_ENDPOINTS`; exempt every path under the blueprint;
    assign the registry instead of `setdefault`.
23. `OAuthAccountSchema`: remove `exclude`.
24. `MAX_NEXT_LENGTH`: 4096, which `test_start_response_headers_fit...` must catch.

Group B:

1. `reportLostSession`: restore the old condition.
2. `useAuthFormState`: drop the fallback; flip the two errors' order.
3. `oauthErrorMessage`: use a plain object for the messages.
4. `ProviderButtons`: render the divider with no provider; drop `next`.
5. `LinkedProviders`: offer linked providers too; use `startUrl` instead of `linkUrl`.
6. `UnlinkDialog`: do not close on success.
7. `useProviders`: drop the `catch`.
8. `useUnlinkAccount`: drop the invalidation.
9. `AppShell`: drop the Account entry.

Group C:

1. Drop either key from either Compose file. Dropping a `:-` only adds a warning to
   Compose's output, and the variable still renders blank, so it is not on this list.
2. Drop a key from `scripts/provision.sh`; drop a key from `.env.example`, which the
   existing key-parity loop must catch.
3. Drop the staging example's keys.

Then, after Group A, on a scratch copy: remove `joserfc` from `requirements.txt`, and
`scripts/tests/test-backend-image.sh` must fail.

## No other changes needed

- `vite.config.ts`: its `^/api(/|$)` proxy has no method or Accept filter, so navigations
  and POSTs reach Flask, and `Location` and `Set-Cookie` pass through. No frontend
  dependency is added, so `VENDOR_CHUNKS` stays.
- `scripts/nginx-ssl.conf.template` and `docker/nginx.conf`: `location ^~ /api/v1/auth/`
  already proxies the blueprint with the security headers. Its throttle counts only POSTs,
  so Google's GET callback is never throttled. Apple's POST will share the budget, as
  `ai/auth.md` already records.
- `scripts/deploy.sh`, `scripts/up.sh`, `scripts/worktree-setup.sh`,
  `scripts/copy-production.sh`, `.devcontainer/`, and `.github/workflows/`: none names
  these keys, and CI installs the pins through `requirements-dev.txt`. `pip-audit -r
  requirements.txt` covers the new runtime packages.
- `src_front/src/components/ProtectedRoute.tsx` and `store/auth.ts`: `fetchMe()` on load
  is how a provider sign-in reaches the SPA.
- `RecordSection` and `EntityList`: both force an Add button, so `LinkedAccounts` uses
  `ConfirmDialog` and `QueryState` directly and neither changes.
- `src_back/seed.py`, `ai/tls.md`, `ai/backups.md`, `.fallowrc.json`, `pyproject.toml`.
- Provider branding, a set-password route for passwordless accounts, and refreshing a
  link's email at each sign-in: the issue defers the first, #32 defers the second, and
  nothing reads the third.

## Added during implementation

Chuck approved these on 2026-11-02, after the groups' mutation checks showed decisions no
test could fail. Each one fails its test once its decision is undone.

- `OidcSigner.make_id_token` leaves out a claim set to `None`, so the missing-claim tests
  send tokens that lack `exp` or `sub`, not a `null` that `joserfc` refuses anyway.
- The sign-up, link, and unlink tests in `test_oauth_api.py` roll the session back before
  asserting, because only committed rows survive a rollback. The sign-up test also checks
  the link's email.
- `test_a_callback_without_a_code_is_exchange_failed` takes `mocked_http` and asserts that
  no request left, so a missing code check cannot reach Google.
- `test_a_subject_matches_only_its_own_provider`: a subject linked under another provider
  does not sign that account in.
- `test_an_account_links_each_provider_once` and `test_an_identity_links_to_one_account`
  in `test_oauth.py` prove both unique constraints. CI never runs `db check`, so nothing
  else would notice one dropped from the model.
- The exchange test and `test_a_second_token_uses_the_cached_keys` assert the `(3, 5)`
  timeout on each outside call.
- `test_the_environment_enables_a_provider` clears `PUBLIC_BASE_URL`, so it does not lean
  on a developer's `.env`.
- Frontend: `startUrl` encodes the provider name (`test/utils/oauth.test.ts`), the provider
  buttons sit between Sign in and the footer (`test/pages/Login.test.tsx`), and "No
  providers are linked." hides once a link exists (`LinkedAccounts.test.tsx`).
- Documentation: README keeps "error boundaries" on a continuation line, and `ai/auth.md`
  finds a compromised account's links by the `oauth_accounts` table, since a callback link
  has no actor in production. Its policy section says "in production" as well.
- The browser check (Verification step 5) found two bugs no gate showed, both fixed and
  verified in Chrome, WebKit, and Firefox with the React Compiler on. `UnlinkDialog` reads
  `account?.provider` into a local during render: the compiler, on in production builds
  only, read the closure's `account!.provider` while rendering and crashed the Account
  page on first load. And `start` sends a `?link=1` refused without a session to
  `/login?error=invalid_state`, because `/account` could only bounce the visitor to a
  sign-in page that showed no message. `ai/conventions.md` records the compiler rule, and
  the same pattern in `RecordSection` is #57.
- An outside review of PR #56 found that `safe_next` counted decoded characters, while
  Werkzeug percent-encodes `Location`: `/?q=` and 400 emoji made a 5.3 KB callback
  header, which nginx 1.27 answers with a 502 under its default 4 KB buffer. `safe_next`
  now counts `iri_to_uri(value)`, after the host checks, because `iri_to_uri` raises on a
  malformed host such as `//[`. `test_safe_next` adds the encoded boundary and that host,
  and `test_callback_response_headers_fit_nginx_default_buffer` covers the callback,
  which the start test never did. Counting characters again, counting UTF-8 bytes, `>=`,
  and moving the check first each fail a test.

Two listed mutation checks cannot fail by design: dropping either key from
`docker/docker-compose.prod.yml`, because Compose merges in the base file's identical
entries, and dropping the provider check in `_attach_account` while the
`(user_id, provider)` constraint stands.

## Verification

1. Targeted, while editing: `.venv/bin/python -m pytest src_back/tests/test_oauth_state.py
   src_back/tests/test_oidc.py src_back/tests/test_oauth_providers.py
   src_back/tests/test_oauth.py src_back/tests/test_oauth_api.py
   src_back/tests/test_app.py src_back/tests/test_auth.py src_back/tests/test_errors.py
   src_back/tests/test_schemas.py --no-cov`; `npx vitest run` on the frontend test files
   above; and `bash` on each changed test in `scripts/tests/`.
2. The migration, on the dev database: `db upgrade`, `db check`, which must report no new
   operations, then `flask db downgrade`, without `-1`, then `db upgrade` and `db check`
   again.
3. At the end, in parallel: `npm run test`, `npm run lint -- --max-warnings=0`, and `npm
   run lint:py`; then `npm run typecheck`, `npx fallow audit`, `npm run lint:md`, `npx
   prettier --check .`, `npm run build`, and `npm run test:scripts`, which rebuilds the
   backend image with the new pins.
4. Against PostgreSQL, because SQLite ignores column lengths and foreign keys: start a
   throwaway `postgres:16` container named for this check, run
   `TEST_DATABASE_URL=<its URL> .venv/bin/python -m pytest`, and remove it by name.
5. In real browsers, with production's cookie settings, against a stub provider on a
   different site, because the design rests on what browsers do with these cookies. All of
   it stays in the scratchpad, and nothing is committed.
    - A scratch runner calls `create_app()` with
      `PUBLIC_BASE_URL=https://localhost:<port>`, `SESSION_COOKIE_SAMESITE='Strict'`,
      `SESSION_COOKIE_SECURE=True`, a scratch SQLite file, and `OAUTH_PROVIDERS` holding
      one `OAuthProvider` named `stub` whose URLs point at the stub on
      `http://127.0.0.1:<other port>`. That host is a different site from `localhost`,
      which is what makes the redirect back cross-site. It serves the built `dist/` with a
      self-signed certificate.
    - The stub provider is a small Flask app: `/authorize` redirects back with `code` and
      `state`, or answers with an auto-submitting POST form when asked for `form_post`;
      `/token` checks the PKCE verifier and returns an ID token carrying the nonce;
      `/keys` serves the JWKS.
    - Playwright 1.64.1, in a scratch directory, with `ignoreHTTPSErrors`, drives Chrome
      (`channel: 'chrome'`) and Playwright's WebKit and Firefox builds through: sign-up
      with a GET callback, reaching `/` signed in, with `/api/v1/auth/me` answering 200
      and `__Host-oauth_txn` gone; the same with a POST callback; signing out and back in;
      linking from `/account` as a password account, which proves `Sec-Fetch-Site` arrives
      in each engine, then unlinking; a declined consent, showing the alert on `/login`;
      the last method's 409 inside the dialog; with a session open, opening `/login` and
      pressing the button as a different identity, which must make a new account and leave
      the first with no link; and pressing Link in an `/account` tab whose session ended
      in another tab, which must stop at the sign-in page's alert without reaching the
      provider.
    - At 375 px wide, signed in as an admin, assert that the page has no horizontal scroll
      with the fourth button in the bar, and view a screenshot of the bar.
    - Confirm each browser stored `session` as `Strict` and `__Host-oauth_txn` as `None`
      with `Path=/`, and removed it after each callback and at logout.
    - Stop the runner and the stub, and confirm no process holds either port.
6. By Chuck, before the PR leaves draft, because only he can create a Google client:
   follow "Setting up Google" in `ai/auth.md` for the dev port, put the keys in `.env`,
   run `npm run docker:up`, and in Safari and one other browser: sign up with "Continue
   with Google"; sign out and sign in again, confirming the account chooser appears; try
   it with a Google address that already has a password account here, which must say to
   sign in first; sign in with the password and link Google from Account; then unlink it.
   With no keys, Login and Register look as they did. Google answers by GET, so real
   Safari's POST callback stays untested until #30; Playwright's WebKit stands in for it.
