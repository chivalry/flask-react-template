# Issue #31: Add Facebook Login

## Context

Accounts sign in with a password, a passkey, Google, or Sign in with Apple. This change
adds Facebook Login as the registry's third provider. Facebook Login for the web is OAuth
2.0 without OpenID Connect, so where Google and Apple check an ID token, Facebook's
identity function spends the access token from the exchange on one Graph API call,
`GET /me?fields=id,name,email`, and keeps no token. A person who declines the email
permission, or has no address on Facebook, ends at `email_required`, as the issue asks.

What the flow needs is in place. `callback` takes the GET that Facebook sends, and
`_CANCELLED_ERRORS` already holds OAuth's `access_denied`, which Facebook sends for a
decline. `exchange_code()` posts the code with the app secret and leaves out PKCE for a
provider without it. `_resolve_by_email()` refuses a missing email as `email_required`
before it reads `email_verified`, and `_attach_account()` cuts the name to 255
characters. `fetch_identity` receives the provider, whose `client_secret()` signs the
profile lookup. The frontend draws buttons and link rows from the server's
`{name, label}` list, so "Continue with Facebook" needs no production change, and
Facebook adds no `?error=` code. Two small frontend changes remain: a layout gap that
shows once three providers can be linked (point 9), and an `email_required` message
that says why an address is needed (point 15).

### Where the issue and the code disagree

Each was checked against the code or a primary source while planning, and each changes
what gets built. Chuck chose points 1, 3, 4, and 9 on 2026-11-06, and points 10 and 15
on 2026-11-07, after the plan's review.

1. **No PKCE.** The issue asks for PKCE S256, but Meta documents `code_challenge` and
   `code_verifier` only in "OIDC Code Flow with PKCE for Manually Built Facebook Login
   Flows", which needs `openid` and a nonce and which Meta marks "still in testing". Its
   examples name v11.0, it leaves the ID-token checks to Limited Login's validation page,
   and Meta's discovery document lists neither a token endpoint nor the `code` response
   type. The manual flow's page never mentions PKCE. So `uses_pkce=False`, and the
   signed `state` alone ties Facebook's answer to the browser. That falls short of RFC
   9700's rule that a client MUST prevent code injection, which Chuck accepted in those
   words; "Accepted limits" says why little can leak.
2. **Graph API v27.0.** Meta released it on 2026-11-04 ([Meta][fb-v27]), after the
   issue named v26.0. Each version is "guaranteed to operate for at least two years";
   two years after the next one ships it is "no longer usable", and Meta answers API
   calls that name it with "the next oldest, usable version" ([Meta][fb-versions]). The
   page does not say what the Login Dialog does then.
3. **The dialog asks again for a declined email.** Every authorize URL carries
   `auth_type=rerequest`, because "once someone has declined a permission, the Login
   Dialog will not re-ask them for it unless you explicitly tell the dialog you're
   re-asking for a declined permission" ([Meta][fb-manual]). Meta warns of "Developer
   Alerts if your app repeatedly directs users to permissions dialogs after they deny
   permissions" ([Meta][fb-permissions]). The app never sends anyone back by itself:
   the person reads the `email_required` message (point 15) and chooses to try again,
   as that page advises.
4. **Every profile lookup carries `appsecret_proof`**, the token's HMAC-SHA256 under the
   app secret, so the app can turn on Require App Secret. Meta's Graph API page computes
   it over the token alone; its Login Security page describes a time-stamped form with
   `appsecret_time`, and neither page says whether the other form is still accepted.
   The plan sends the first, which Verification step 5 checks with the setting on.
5. **The token travels in the `Authorization` header, and the warning logs only a
   status.** Meta's Graph API overview shows only `?access_token=`, but `requests`
   copies a request's URL into its errors. Meta documents the Bearer header on
   graph.facebook.com for the WhatsApp Cloud API, and on 2026-11-06 graph.facebook.com
   read one sent to `/v27.0/me`: code 190, "Cannot parse access token", against code
   2500 without one. The URL still holds `appsecret_proof`, so a failed lookup logs a
   refusal's status, or otherwise the error's type, such as `JSONDecodeError` for an
   answer that is not JSON, and never the error's text.
6. **The shared timeout, not 10 s.** `HTTP_TIMEOUT_SECONDS`, 3 s to connect and 5 s to
   read, keeps a callback's calls under gunicorn's 30 s, and Facebook's makes two.
7. **Every bad profile answer is `exchange_failed`.** The issue names a non-2xx answer.
   An unreachable Graph API, a body that is not a JSON object, a profile without a text
   `id`, and a token response without an access token join it, so no new code reaches
   the frontend's messages.
8. **An empty or non-text email is none, and the name is cleaned** by Apple's
   `_storable_text`, which drops control characters and lone surrogates: PostgreSQL
   refuses NUL, and no driver encodes a lone surrogate.
9. **The Account page's Link buttons get `useFlexGap`.** Three of them wrap at 375 px,
   and MUI's default spacing leaves the wrapped row without a gap and with an 8 px
   indent.
10. **Staging and the dev stack sign in through test apps of production's Meta app.**
    The `id` is "unique to the app and cannot be used by other apps", so the links
    copied from production match only under production's app or a test app of it,
    whose "User IDs are scoped to the parent app". A test app has its own App ID and
    secret and is "always in Development mode", and Meta suggests test apps "for
    development, testing, QA, and staging purposes" ([Meta][fb-test-apps]). So
    production's secret stays off laptops and staging, and the dev stack can keep an
    `http://localhost` callback after production goes Live. That rests on Meta's
    dashboard saying in 2021 that localhost redirects "are automatically allowed while
    in development mode only", as [a forum post][auth0-localhost] quotes it; that
    thread's redirect went to Auth0, not localhost, and no primary source says so, so
    "Setting up Facebook" falls back to an https tunnel. Staging arrived after the
    issue, as #30 found for Apple. Verification step 5 checks the localhost callback and
    that a test app's ids are the parent's.
11. **No https check.** Unlike Apple, Facebook is enabled over an http `PUBLIC_BASE_URL`,
    so the dev stack can try it. Meta's dashboard decides which callbacks it accepts. No
    Meta documentation page says whether Development mode takes `http://localhost`;
    the forum post in point 10 quotes the dashboard saying it does, Verification step 5
    finds out, and an https tunnel is the fallback.
12. **The email counts as verified, as the issue decided, though Meta never says
    verified.** The User node's `email` is "The User's primary email address listed on
    their profile", left out when "no valid email address is available"; Meta's own
    `verified` field is deprecated and describes the account, not the address. Rule 4
    then creates an account, as it does for Google's possibly stale address, and rule 5
    still refuses an address that an account holds.
13. **The dialog still receives the nonce**, as every provider's does. The manual flow's
    page names no such parameter and says nothing of unknown ones, and nothing from
    Facebook carries it back; Verification step 5 shows whether the dialog minds.
14. **`exchange_code` posts.** Meta documents a GET with the app secret in the query,
    which `requests` would copy into a logged error. Meta's endpoint answered a form
    POST from a fake app id with the same error as the GET on 2026-11-06, and
    Verification step 5 is the check that a real exchange by POST succeeds. It also
    sends `grant_type=authorization_code`, which Meta does not document.
15. **The `email_required` message says why an address is needed.** It read "The
    sign-in provider did not share an email address.", and Meta advises "a clear and
    upfront explanation about why you are requesting each permission" after a person
    declines, then letting them "click or tap to opt back in" ([Meta][fb-permissions]).
    It becomes "The sign-in provider did not share an email address, which every
    account here needs. Share it and try again, or sign in another way." Every provider
    shares the message. Facebook leaves the address out when a person declines it or
    has none there, and Apple for some school and work accounts; anyone without an
    address to share can still take the message's "sign in another way". Chuck kept the
    text after the second review pointed out the Apple case.

### What was checked against primary sources

- **Graph API versions**: the changelog says "The latest Graph API version is: v27.0",
  though its table stops at v26.0, introduced July 29, 2026, and Meta's post of
  2026-11-04, "Introducing Graph API v27.0 and Marketing API v27.0", gives "Graph API
  v27.0 release: November 4, 2026". The versioning guide: "Each version is guaranteed
  to operate for at least two years."; "A version will no longer be usable two years
  after the date that the subsequent version is released."; and "For APIs, once a
  version is no longer usable, any calls made to it will be defaulted to the next
  oldest, usable version." It says nothing of dialogs past that date.
- **Manual login flow**: the dialog is `https://www.facebook.com/v27.0/dialog/oauth` with
  `client_id`, `redirect_uri`, and `state` required; `response_type=code` is "the
  default behavior"; `scope` is "A comma or space separated list of Permissions". The
  token exchange is `GET https://graph.facebook.com/v27.0/oauth/access_token` with
  `client_id`, `redirect_uri`, `client_secret`, and `code`, answering `access_token`,
  `token_type`, and `expires_in`. A decline redirects with
  `error_reason=user_denied&error=access_denied&error_description=Permissions+error.`;
  the example shows no `state`, and the page says only that `state` "will be passed
  back to you, unchanged, in your redirect URI". The `rerequest` sentence in point 3.
- **The OIDC variant**: "Be aware that this functionality is still in testing."; "To
  use OIDC, you must include openid in the list of permissions."; `code_challenge` and
  `nonce` are required; examples on v11.0; to validate the token, developers "should
  follow the Validating the Limited Login OIDC Token documentation".
- **The discovery document**: issuer `https://www.facebook.com`, JWKS
  `https://www.facebook.com/.well-known/oauth/openid/jwks/`, `response_types_supported`
  `id_token` and `token id_token`, `subject_types_supported` `pairwise`, RS256, and no
  `token_endpoint`.
- **The User node**: the `email` sentences in point 12; `id` is "The app user's
  App-Scoped User ID. This ID is unique to the app and cannot be used by other apps.";
  `verified` is deprecated: "Indicates whether the account has been verified."
- **Securing Graph API requests**: "The app secret proof is a sha256 hash of your access
  token, using your app secret as the key."; with Require App Secret on, a call without
  the proof "will fail". **Login Security**: the time-stamped proof, "considered expired
  after 5 minutes"; "Enabling Strict Mode is required for all apps.", with an exact
  match; Enforce HTTPS is on for "All new apps created as of March 2018".
- **Access levels and app modes**: "Permissions with Standard Access can only be
  requested from app users who have a role on the requesting app."; "All newly created
  Consumer apps are automatically approved for Advanced Access for the email and
  public_profile permissions. However, both permissions are set to Standard Access by
  default and must be manually switched to Advanced Access."; and "Business
  Verification is required to get Advanced Access". Basic Settings: "While verification
  is not required to Go Live, you will not be able to access data you do not own until
  verification is complete." App modes: "Apps in Development mode can only request
  permissions from role users".
- **Basic Settings**: Display Name, Contact Email, Terms of Service URL, App Icon,
  Category, and App Purpose are each "required to switch your app to Live mode"; the
  Privacy Policy URL, which the issue's checklist names, carries no such line, and the
  data deletion URL "may be the relevant section in the application's Privacy Policy".
  **Data deletion**: "Developers need to specify either a data deletion callback
  instruction URL or a callback URL", and "all apps must inform users in their privacy
  policy how to request deletion of their data".
- **Authentication versus data access**: "The expiration period for data access is 90
  days, based on when the user was last active."; "To regain data access, your app must
  ask the user to re-authorize your app's permissions", on the web with
  `auth_type=reauthorize`. Whether an ordinary sign-in renews it is not stated.
- **User experience design**: "The preferred labels are either "Continue with Facebook"
  or "Login with Facebook" depending on the context.", with the approved "f" logo.
- **Requesting and revoking permissions**: "You may receive Developer Alerts if your
  app repeatedly directs users to permissions dialogs after they deny permissions."; "If
  a person declines the login dialog have a clear and upfront explanation about why you
  are requesting each permission. Then let them click or tap to opt back in to the
  permission request dialog."
- **Test apps**: "User IDs are scoped to the parent app."; "Test apps are always in
  Development mode and inherit their parent app settings at the time that they are
  created."; a later change to the parent reaches no test app; testing means updating
  "any SDK configurations that rely on your app ID and app secret with the test app's
  corresponding values"; "Test apps inherit the Administrators from their parents.";
  and Meta suggests "creating new test apps and migrating your development teams to use
  these new test apps for development, testing, QA, and staging purposes". To make one:
  "In the upper-left corner of the dashboard, click the app selection dropdown menu and
  click Create Test App."
- **Observed on 2026-11-06** with fake credentials: `/v27.0/me` read a Bearer header
  (point 5), and the token endpoint answered a GET and a form POST alike (point 14).
- **In this `.venv`**: requests 2.34.2 raises `JSONDecodeError`, a `RequestException`,
  for a body that is not JSON; responses 0.26.3 matches a URL registered without a
  query string and records the call's `params`; `openssl dgst -sha256 -hmac` gives the
  same proof as Python's `hmac`.

### Accepted limits, documented in `ai/auth.md`

- No PKCE or nonce (point 1). The callback spends a code at once and Meta matches the
  redirect URI exactly over https, so a code would have to leak unused, as from a
  callback refused for its `state` whose URL gunicorn's or nginx's access log kept, and
  be replayed within its lifetime. RFC 9700 says a client MUST prevent code injection
  with PKCE or, under OpenID Connect, a nonce, and this flow meets neither; the OIDC
  variant would supply both once Meta calls it stable.
- Only people with a role on an app can sign in through it until it is Live with
  Advanced Access to both permissions, and a test app never goes Live, so each staging
  tester and each developer needs a role on theirs.
- The `id` is app-scoped: production's app and its test apps share ids, which
  Verification step 5 confirms, and moving to another app orphans every link, as
  moving the domain orphans passkeys.
- Data access lapses 90 days after a person last used the app, and Meta does not say
  whether an ordinary sign-in renews it, so a returning person may see
  `exchange_failed`.
- Unlinking does not remove the app from the person's Facebook settings, Meta's
  deauthorize and data deletion callbacks are not received, and the template has no
  deletion flow.
- `FACEBOOK_GRAPH_VERSION` must move before v27.0 stops being usable.

### Sources

- [Meta: manually build a login flow][fb-manual]
- [Meta: OIDC code flow with PKCE](https://developers.facebook.com/docs/facebook-login/guides/advanced/oidc-token/)
- [Meta: validating the Limited Login OIDC token][fb-limited-login]
- [Meta: OpenID Connect discovery document](https://www.facebook.com/.well-known/openid-configuration/)
- [Meta: Graph API changelog](https://developers.facebook.com/docs/graph-api/changelog)
- [Meta: Introducing Graph API v27.0 and Marketing API v27.0][fb-v27]
- [Meta: Graph API versioning][fb-versions]
- [Meta: the User node][fb-user]
- [Meta: securing Graph API requests](https://developers.facebook.com/docs/graph-api/securing-requests)
- [Meta: Login Security][fb-security]
- [Meta: access levels][fb-access]
- [Meta: app modes][fb-modes]
- [Meta: test apps][fb-test-apps]
- [Meta: Basic Settings][fb-basic]
- [Meta: data deletion callback][fb-deletion]
- [Meta: authentication versus data access][fb-data-access]
- [Meta: requesting and revoking permissions][fb-permissions]
- [Meta: user experience design](https://developers.facebook.com/docs/facebook-login/userexperience)
- [RFC 9700, OAuth 2.0 Security Best Current Practice](https://www.rfc-editor.org/rfc/rfc9700)
- [RFC 9110, section 10.2.2, Location](https://www.rfc-editor.org/rfc/rfc9110#section-10.2.2)
- [Auth0 Community, 2021, quoting Meta's dashboard; secondary][auth0-localhost]

[fb-manual]: https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow
[fb-versions]: https://developers.facebook.com/docs/graph-api/guides/versioning
[fb-user]: https://developers.facebook.com/docs/graph-api/reference/user
[fb-security]: https://developers.facebook.com/docs/facebook-login/security
[fb-access]: https://developers.facebook.com/docs/graph-api/overview/access-levels
[fb-modes]: https://developers.facebook.com/docs/development/build-and-test/app-modes
[fb-basic]: https://developers.facebook.com/docs/development/create-an-app/app-dashboard/basic-settings
[fb-deletion]: https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback
[fb-data-access]: https://developers.facebook.com/docs/facebook-login/auth-vs-data
[fb-v27]: https://developers.facebook.com/blog/post/2026/11/04/introducing-graph-api-v27-and-marketing-api-v27/
[fb-test-apps]: https://developers.facebook.com/docs/development/build-and-test/test-apps
[fb-permissions]: https://developers.facebook.com/docs/facebook-login/guides/permissions/request-revoke
[fb-limited-login]: https://developers.facebook.com/docs/facebook-login/limited-login/token/validating
[auth0-localhost]: https://community.auth0.com/t/problems-with-facebook-login-when-testing-connection/64718

## Branch

`issue-31-add-facebook-login` — already checked out; PR #62 exists.

## Change

**25 files**: 24 to edit and one to move. Line numbers are each file's before any edit,
and several replacements add lines, so apply each file's changes bottom-up.

- Backend: `src_back/services/oauth_providers.py`, `src_back/tests/conftest.py`,
  `src_back/tests/test_oauth_providers.py`, `src_back/tests/test_oauth.py`,
  `src_back/tests/test_oauth_api.py`
- Frontend: `src_front/src/components/account/LinkedAccounts.tsx`,
  `src_front/src/utils/oauth.ts`, and the tests `src_front/src/test/utils/fixtures.ts`,
  `src_front/src/test/utils/oauth.test.ts`,
  `src_front/src/test/components/auth/ProviderButtons.test.tsx`, and
  `src_front/src/test/components/account/LinkedAccounts.test.tsx`
- Configuration: `.env.example`, `.env.staging.example`, `docker-compose.yml`,
  `docker/docker-compose.prod.yml`, `scripts/provision.sh`
- Shell tests: `scripts/tests/test-compose-config.sh`, `scripts/tests/test-provision.sh`,
  `scripts/tests/test-deploy.sh`
- Documentation: `ai/auth.md`, `ai/project.md`, `ai/domain.md`, `ai/staging.md`,
  `tools.md`
- Move `plans/pr-60-add-sign-in-with-apple.md` into `plans/archive/` with `git mv`, as
  each branch archives the plan before it.

### src_back/services/oauth_providers.py — Facebook's provider and profile lookup

Seven edits; Google's and Apple's code is unchanged.

Lines 10 to 23, the imports, become:

```python
import hashlib
import hmac
import json
import logging
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

import requests
from joserfc import jwt
from joserfc.jwk import ECKey

from src_back.services.errors import OAuthError
from src_back.services.oidc import HTTP_TIMEOUT_SECONDS, verify_id_token
```

After line 60, the end of `_UNSTORABLE_CATEGORIES`'s docstring, add a blank line and:

```python
FACEBOOK_GRAPH_VERSION = 'v27.0'
"""The Graph API version that Facebook's three URLs name. Two years after the next one
ships, Meta answers calls that name it with the oldest version it still serves
(``ai/auth.md``, "Setting up Facebook")."""

FACEBOOK_AUTHORIZE_URL = f'https://www.facebook.com/{FACEBOOK_GRAPH_VERSION}/dialog/oauth'
FACEBOOK_TOKEN_URL = (
    f'https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/oauth/access_token'
)
FACEBOOK_PROFILE_URL = f'https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/me'
FACEBOOK_PROFILE_FIELDS = 'id,name,email'
"""What the profile lookup asks for; ``email`` is missing when the person declined it or
has no address on Facebook."""
```

Lines 67 and 68, in `OAuthIdentity`'s docstring, become the lines below, because
Facebook's `email_verified` records only that an address came:

```python
    ``subject`` is the provider's stable id for the person. ``email_verified`` is what
    the provider claims, or for Facebook, which claims nothing, whether it sent an
    address; :func:`~src_back.services.oauth.resolve_user` relies on it.
```

In `OAuthProvider`'s docstring, line 86, `for a provider without ID tokens (#31).` becomes
`for a provider without ID tokens, such as Facebook.`

In `_storable_text`, line 251's summary becomes `Keep the text of a name, or a part of
one, that every database can store.` and line 254's argument line becomes `value: The
name or part, which may be any JSON value.`

After line 443, the end of `_apple_provider`, add two blank lines and:

```python
def _facebook_profile(access_token: str, app_secret: str) -> dict[str, Any]:
    """Ask the Graph API whom an access token belongs to.

    The token travels in the ``Authorization`` header, so no URL holds it.
    ``appsecret_proof`` signs the token with the app secret, which Require App Secret
    asks of every call. The URL does hold the proof, and ``requests`` copies the URL
    into its errors, so the warning logs only a refusal's status, or otherwise the
    error's type.

    Args:
        access_token: The access token from the code exchange.
        app_secret: The app's secret.

    Returns:
        The profile's fields.

    Raises:
        OAuthError: With ``exchange_failed`` if Facebook cannot be reached, refuses the
            token, or answers with anything but a JSON object.
    """
    proof = hmac.new(app_secret.encode(), access_token.encode(), hashlib.sha256)
    try:
        response = requests.get(
            FACEBOOK_PROFILE_URL,
            params={
                'fields': FACEBOOK_PROFILE_FIELDS,
                'appsecret_proof': proof.hexdigest(),
            },
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        profile = response.json()
    except requests.RequestException as exc:
        failure = type(exc).__name__ if exc.response is None else exc.response.status_code
        _log.warning('Asking Facebook who signed in failed: %s', failure)
        raise OAuthError('exchange_failed') from exc
    if not isinstance(profile, dict):
        raise OAuthError('exchange_failed')
    return profile


def _facebook_identity(
    provider: OAuthProvider,
    tokens: Mapping[str, Any],
    nonce: str,
    callback_params: Mapping[str, str],
) -> OAuthIdentity:
    """Read who signed in from the Facebook profile the access token unlocks.

    Facebook Login issues no ID token, so the access token is spent on one profile lookup
    and kept nowhere. An email Facebook returns counts as verified. Without one, because
    the person declined it or has no address there, only a returning sign-in or a link
    succeeds; a first sign-in is ``email_required``.

    Args:
        provider: The Facebook provider.
        tokens: The token response.
        nonce: The transaction's nonce, which nothing from Facebook carries.
        callback_params: The callback's parameters, of which Facebook's needs none.

    Returns:
        The identity the profile names.

    Raises:
        OAuthError: With ``exchange_failed`` if the token response holds no access token
            or the profile names no one.
    """
    access_token = tokens.get('access_token')
    if not isinstance(access_token, str) or not access_token:
        raise OAuthError('exchange_failed')
    profile = _facebook_profile(access_token, provider.client_secret())
    subject = profile.get('id')
    if not isinstance(subject, str) or not subject:
        raise OAuthError('exchange_failed')
    email = profile.get('email')
    if not isinstance(email, str) or not email:
        email = None
    return OAuthIdentity(
        provider=provider.name,
        subject=subject,
        email=email,
        email_verified=email is not None,
        display_name=_storable_text(profile.get('name')) or None,
    )


def _facebook_provider(env: Mapping[str, str]) -> OAuthProvider | None:
    """Build the Facebook provider when its keys are set.

    Facebook Login is OAuth 2.0 without OpenID Connect, so there are no issuers or keys.
    Meta documents PKCE only for an OpenID Connect variant it calls in testing, so none
    is sent, and the signed ``state`` alone ties the answer to the browser.
    ``auth_type=rerequest`` asks again for a permission the person declined before;
    without it, someone who once declined their email would get ``email_required`` at
    every sign-in.

    Args:
        env: The environment.

    Returns:
        The provider, or ``None`` unless both keys are set.
    """
    client_id = env.get('OAUTH_FACEBOOK_CLIENT_ID')
    client_secret = env.get('OAUTH_FACEBOOK_CLIENT_SECRET')
    if not client_id or not client_secret:
        return None
    return OAuthProvider(
        name='facebook',
        label='Facebook',
        authorize_url=FACEBOOK_AUTHORIZE_URL,
        token_url=FACEBOOK_TOKEN_URL,
        scopes=('public_profile', 'email'),
        uses_pkce=False,
        client_id=client_id,
        client_secret=lambda: client_secret,
        extra_authorize_params={'auth_type': 'rerequest'},
        fetch_identity=_facebook_identity,
        issuers=(),
        jwks_uri=None,
    )
```

In `build_registry`, line 461 becomes:

```python
    candidates = (
        _google_provider(env),
        _apple_provider(env, public_base_url),
        _facebook_provider(env),
    )
```

Checked in memory against the edited module, the review's changes included, on
2026-11-07: Ruff check and `ruff format` report nothing, pydoclint's `Visitor` with this
repository's settings finds no violation, basedpyright reports no error, and the longest
new function, `_facebook_identity`, has 43 of the 50 lines allowed.

### src_back/tests/conftest.py — Facebook's keys and fixture

After line 74, the end of `APPLE_ID_TOKEN_CLAIMS`, add:

```python
FACEBOOK_CLIENT_ID = '1234567890123456'
FACEBOOK_CLIENT_SECRET = 'facebook-app-secret'
FACEBOOK_ENVIRONMENT = {
    'OAUTH_FACEBOOK_CLIENT_ID': FACEBOOK_CLIENT_ID,
    'OAUTH_FACEBOOK_CLIENT_SECRET': FACEBOOK_CLIENT_SECRET,
}
```

Lines 118 to 123, `_clear_oauth_environment`, become the version below. Facebook works
on `http://localhost`, so a developer's `.env` is likely to hold its keys, which
`load_dotenv()` would otherwise hand to every app a test builds without a registry:
`test_no_provider_is_enabled_without_keys` in `test_app.py` fails then.

```python
@pytest.fixture(autouse=True)
def _clear_oauth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # src_back.app loads .env at import, where a developer's real keys would enable a
    # provider in every app a test builds without injecting a registry.
    for name in (*OAUTH_ENVIRONMENT, *APPLE_ENVIRONMENT, *FACEBOOK_ENVIRONMENT):
        monkeypatch.delenv(name, raising=False)
```

After line 279, the end of the `apple` fixture, add two blank lines and:

```python
@pytest.fixture()
def facebook(app: Flask, mocked_http: responses.RequestsMock) -> OAuthProvider:
    # Facebook joins Google in this test's registry. Every call it makes goes to
    # mocked_http, which refuses one it was not given, so no test reaches Meta.
    provider = build_registry(FACEBOOK_ENVIRONMENT, PUBLIC_BASE_URL)['facebook']
    app.config['OAUTH_PROVIDERS']['facebook'] = provider
    return provider
```

### src_back/tests/test_oauth_providers.py — the registry and the profile lookup

Lines 1 to 9, the standard and third-party imports, become:

```python
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import pytest
import requests
import responses
from cryptography.hazmat.primitives.asymmetric import ec
from joserfc import jwt
from joserfc.jwk import ECKey, RSAKey
```

In the `oauth_providers` import, lines 12 to 27, add `FACEBOOK_AUTHORIZE_URL`,
`FACEBOOK_GRAPH_VERSION`, `FACEBOOK_PROFILE_URL`, and `FACEBOOK_TOKEN_URL` after
`APPLE_USER_FIELD_LIMIT`. After that import add
`from src_back.services.oidc import HTTP_TIMEOUT_SECONDS`. In the `conftest` import,
lines 28 to 39, add `FACEBOOK_CLIENT_ID`, `FACEBOOK_CLIENT_SECRET`, and
`FACEBOOK_ENVIRONMENT` after `APPLE_TEAM_ID`.

After line 52, the end of `FIRST_ANSWER`, add:

```python
FACEBOOK_ACCESS_TOKEN = 'the-access-token'
# The HMAC-SHA256 of FACEBOOK_ACCESS_TOKEN keyed with conftest's app secret, worked out
# with openssl: printf %s the-access-token | openssl dgst -sha256 -hmac <secret>
FACEBOOK_PROOF = '2c2adff38a252d561f6838a54c867d54512dfe2b3656e569dd92b9d8eb00de47'
# What the Graph API answers for someone who granted both permissions.
FACEBOOK_PROFILE = {'id': '10101', 'name': 'Sam Lee', 'email': 'sam@example.com'}
```

After line 88, the end of `_user_field`, add two blank lines and:

```python
def _facebook() -> OAuthProvider:
    return build_registry(FACEBOOK_ENVIRONMENT, PUBLIC_BASE_URL)['facebook']


def _facebook_identity(
    mocked_http: responses.RequestsMock, **answer: Any
) -> OAuthIdentity:
    # The profile lookup gets the answer; the tokens are what the exchange returned.
    mocked_http.add(responses.GET, FACEBOOK_PROFILE_URL, **answer)
    provider = _facebook()
    tokens = {'access_token': FACEBOOK_ACCESS_TOKEN, 'token_type': 'bearer'}
    return provider.fetch_identity(provider, tokens, NONCE, {})
```

At the end of the file, after line 419, add two blank lines and:

```python
# Facebook: the registry


def test_facebook_is_enabled_with_both_keys(caplog: pytest.LogCaptureFixture) -> None:
    env = {**OAUTH_ENVIRONMENT, **APPLE_ENVIRONMENT, **FACEBOOK_ENVIRONMENT}
    registry = build_registry(env, PUBLIC_BASE_URL)
    assert list(registry) == ['google', 'apple', 'facebook']
    facebook = registry['facebook']
    assert facebook.label == 'Facebook'
    assert facebook.client_id == FACEBOOK_CLIENT_ID
    assert facebook.client_secret() == FACEBOOK_CLIENT_SECRET
    assert facebook.authorize_url == FACEBOOK_AUTHORIZE_URL
    assert facebook.token_url == FACEBOOK_TOKEN_URL
    assert facebook.scopes == ('public_profile', 'email')
    assert facebook.uses_pkce is False
    assert facebook.extra_authorize_params == {'auth_type': 'rerequest'}
    assert facebook.issuers == ()
    assert facebook.jwks_uri is None
    assert caplog.messages == []


def test_facebooks_endpoints_name_one_graph_api_version() -> None:
    # Meta's manual login flow, and its Graph API v27.0 announcement of 2026-11-04.
    assert FACEBOOK_GRAPH_VERSION == 'v27.0'
    assert (FACEBOOK_AUTHORIZE_URL, FACEBOOK_TOKEN_URL, FACEBOOK_PROFILE_URL) == (
        'https://www.facebook.com/v27.0/dialog/oauth',
        'https://graph.facebook.com/v27.0/oauth/access_token',
        'https://graph.facebook.com/v27.0/me',
    )


def test_facebook_works_on_a_development_origin(caplog: pytest.LogCaptureFixture) -> None:
    # Unlike Apple, Facebook has no https check, so the dev stack can try it; Meta's
    # dashboard decides which callbacks it accepts.
    registry = build_registry(FACEBOOK_ENVIRONMENT, 'http://localhost:5174')
    assert list(registry) == ['facebook']
    assert caplog.messages == []


@pytest.mark.parametrize(
    'env',
    [
        {'OAUTH_FACEBOOK_CLIENT_SECRET': FACEBOOK_CLIENT_SECRET},
        {'OAUTH_FACEBOOK_CLIENT_ID': FACEBOOK_CLIENT_ID},
        {**FACEBOOK_ENVIRONMENT, 'OAUTH_FACEBOOK_CLIENT_ID': ''},
        {**FACEBOOK_ENVIRONMENT, 'OAUTH_FACEBOOK_CLIENT_SECRET': ''},
    ],
    ids=['no-client-id', 'no-client-secret', 'blank-client-id', 'blank-client-secret'],
)
def test_facebook_stays_off_quietly_without_a_key(
    env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    assert build_registry(env, PUBLIC_BASE_URL) == {}
    assert caplog.messages == []


# Facebook: the profile lookup


def test_facebook_identity_reads_the_profile(mocked_http: responses.RequestsMock) -> None:
    assert _facebook_identity(mocked_http, json=FACEBOOK_PROFILE) == OAuthIdentity(
        provider='facebook',
        subject='10101',
        email='sam@example.com',
        email_verified=True,
        display_name='Sam Lee',
    )


def test_the_lookup_signs_the_token_and_keeps_it_out_of_the_url(
    mocked_http: responses.RequestsMock,
) -> None:
    _facebook_identity(mocked_http, json=FACEBOOK_PROFILE)
    # responses records the call's parameters and keyword arguments at runtime, untyped.
    request: Any = mocked_http.calls[0].request
    assert request.method == 'GET'
    assert request.params == {
        'fields': 'id,name,email',
        'appsecret_proof': FACEBOOK_PROOF,
    }
    assert request.headers['Authorization'] == f'Bearer {FACEBOOK_ACCESS_TOKEN}'
    assert FACEBOOK_ACCESS_TOKEN not in request.url
    assert request.req_kwargs['timeout'] == HTTP_TIMEOUT_SECONDS
    # REQUESTS_CA_BUNDLE turns verify into a path, so check only that it is not off.
    assert request.req_kwargs['verify'] is not False


def test_the_proof_is_the_tokens_hmac_under_the_secret() -> None:
    # The known answer above, from the same inputs through Python's hmac.
    digest = hmac.new(
        FACEBOOK_CLIENT_SECRET.encode(), FACEBOOK_ACCESS_TOKEN.encode(), hashlib.sha256
    )
    assert digest.hexdigest() == FACEBOOK_PROOF


@pytest.mark.parametrize(
    'profile',
    [
        {'id': '10101', 'name': 'Sam Lee'},
        {'id': '10101', 'name': 'Sam Lee', 'email': ''},
        {'id': '10101', 'name': 'Sam Lee', 'email': None},
        {'id': '10101', 'name': 'Sam Lee', 'email': 42},
    ],
    ids=['declined', 'empty', 'null', 'not-text'],
)
def test_a_facebook_profile_without_an_email_has_none(
    mocked_http: responses.RequestsMock, profile: dict[str, Any]
) -> None:
    identity = _facebook_identity(mocked_http, json=profile)
    assert (identity.subject, identity.email, identity.email_verified) == (
        '10101',
        None,
        False,
    )


FACEBOOK_PROFILE_FAILURES: dict[str, dict[str, Any]] = {
    'refused': {
        'status': 400,
        'json': {'error': {'message': 'Invalid OAuth access token.', 'code': 190}},
    },
    'not-json': {'body': 'not json'},
    'a-list': {'json': ['not', 'an', 'object']},
    'unreachable': {'body': requests.ConnectionError('unreachable')},
    'no-id': {'json': {'name': 'Sam Lee', 'email': 'sam@example.com'}},
    'empty-id': {'json': {'id': '', 'email': 'sam@example.com'}},
    'id-not-text': {'json': {'id': 10101, 'email': 'sam@example.com'}},
}


@pytest.mark.parametrize(
    'answer', FACEBOOK_PROFILE_FAILURES.values(), ids=FACEBOOK_PROFILE_FAILURES.keys()
)
def test_a_profile_lookup_that_names_no_one_is_exchange_failed(
    mocked_http: responses.RequestsMock, answer: dict[str, Any]
) -> None:
    with pytest.raises(OAuthError) as excinfo:
        _facebook_identity(mocked_http, **answer)
    assert excinfo.value.code == 'exchange_failed'


@pytest.mark.parametrize(
    'tokens',
    [{}, {'access_token': ''}, {'access_token': 42}],
    ids=['missing', 'empty', 'not-text'],
)
def test_a_token_response_without_an_access_token_is_exchange_failed(
    mocked_http: responses.RequestsMock, tokens: dict[str, Any]
) -> None:
    provider = _facebook()
    with pytest.raises(OAuthError) as excinfo:
        provider.fetch_identity(provider, tokens, NONCE, {})
    assert excinfo.value.code == 'exchange_failed'
    assert len(mocked_http.calls) == 0


def test_the_callbacks_own_parameters_name_no_one(
    mocked_http: responses.RequestsMock,
) -> None:
    # The browser writes the callback's query, so only the Graph API's answer counts.
    mocked_http.add(responses.GET, FACEBOOK_PROFILE_URL, json={'id': '10101'})
    provider = _facebook()
    tokens = {'access_token': FACEBOOK_ACCESS_TOKEN, 'token_type': 'bearer'}
    forged = {'id': '20202', 'email': 'someone.else@example.com', 'name': 'Someone Else'}
    identity = provider.fetch_identity(provider, tokens, NONCE, forged)
    assert (identity.subject, identity.email) == ('10101', None)
    assert identity.display_name is None


@pytest.mark.parametrize(
    ('failure', 'logged'),
    [
        ('refused', '400'),
        ('not-json', 'JSONDecodeError'),
        ('unreachable', 'ConnectionError'),
    ],
)
def test_a_failed_lookup_logs_only_its_status_or_error_type(
    mocked_http: responses.RequestsMock,
    caplog: pytest.LogCaptureFixture,
    failure: str,
    logged: str,
) -> None:
    # The URL holds appsecret_proof, so no record at any level carries it or error text.
    with caplog.at_level(logging.DEBUG, logger=LOGGER), pytest.raises(OAuthError):
        _facebook_identity(mocked_http, **FACEBOOK_PROFILE_FAILURES[failure])
    assert caplog.record_tuples == [
        (LOGGER, logging.WARNING, f'Asking Facebook who signed in failed: {logged}'),
    ]
    for secret in (FACEBOOK_ACCESS_TOKEN, FACEBOOK_PROOF, FACEBOOK_CLIENT_SECRET):
        assert secret not in caplog.text


def test_a_facebook_name_keeps_only_what_a_database_can_store(
    mocked_http: responses.RequestsMock,
) -> None:
    # A NUL, which PostgreSQL refuses, and a lone surrogate, which no driver can encode.
    profile = {**FACEBOOK_PROFILE, 'name': 'Sam' + chr(0) + ' Lee' + chr(0xD800)}
    assert _facebook_identity(mocked_http, json=profile).display_name == 'Sam Lee'


@pytest.mark.parametrize(
    'profile',
    [{'id': '10101'}, {'id': '10101', 'name': 7}, {'id': '10101', 'name': ' '}],
    ids=['missing', 'not-text', 'blank'],
)
def test_a_facebook_profile_without_a_usable_name_has_none(
    mocked_http: responses.RequestsMock, profile: dict[str, Any]
) -> None:
    assert _facebook_identity(mocked_http, json=profile).display_name is None
```

### src_back/tests/test_oauth.py — Facebook's authorize URL

In the `oauth_providers` import, line 21, add `FACEBOOK_AUTHORIZE_URL` after
`APPLE_AUTHORIZE_URL`; in the `conftest` import, line 32, add `FACEBOOK_CLIENT_ID` and
`FACEBOOK_ENVIRONMENT` after `APPLE_ENVIRONMENT`. After line 40 add:

```python
FACEBOOK_REDIRECT_URI = f'{PUBLIC_BASE_URL}/api/v1/auth/oauth/facebook/callback'
```

After line 92, the end of `test_apples_authorize_url_asks_for_a_form_post_without_pkce`,
add two blank lines and:

```python
def test_facebooks_authorize_url_asks_again_for_a_declined_email_without_pkce() -> None:
    facebook = build_registry(FACEBOOK_ENVIRONMENT, PUBLIC_BASE_URL)['facebook']
    txn = new_transaction('facebook', uses_pkce=False, next_path='/', link_user_id=None)
    url = urlsplit(
        build_authorize_url(facebook, redirect_uri=FACEBOOK_REDIRECT_URI, txn=txn)
    )
    assert f'{url.scheme}://{url.netloc}{url.path}' == FACEBOOK_AUTHORIZE_URL
    assert dict(parse_qsl(url.query)) == {
        'client_id': FACEBOOK_CLIENT_ID,
        'redirect_uri': FACEBOOK_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'public_profile email',
        'state': txn.state,
        'nonce': txn.nonce,
        'auth_type': 'rerequest',
    }
```

### src_back/tests/test_oauth_api.py — Facebook end to end

In the `oauth_providers` import, lines 20 to 24, add `FACEBOOK_PROFILE_URL` and
`FACEBOOK_TOKEN_URL` after `APPLE_TOKEN_URL`; in the `conftest` import, lines 32 to 38,
add `FACEBOOK_CLIENT_ID` and `FACEBOOK_CLIENT_SECRET` after `APPLE_PRIVATE_KEY`.

After line 61, the end of `FIRST_ANSWER`, add:

```python
FACEBOOK_CALLBACK_URL = f'{OAUTH_URL}/facebook/callback'
FACEBOOK_EMAIL = 'sam@example.com'
FACEBOOK_PROFILE: dict[str, Any] = {
    'id': '10101',
    'name': 'Sam Lee',
    'email': FACEBOOK_EMAIL,
}
```

After line 152, the end of `sign_in_with_apple`, add two blank lines and:

```python
def answer_facebook(mocked_http: responses.RequestsMock, profile: dict[str, Any]) -> None:
    # The token response Meta documents, then the profile lookup's answer.
    tokens = {'access_token': 'the-access-token', 'token_type': 'bearer'}
    mocked_http.add(responses.POST, FACEBOOK_TOKEN_URL, json=tokens)
    mocked_http.add(responses.GET, FACEBOOK_PROFILE_URL, json=profile)


def sign_in_with_facebook(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    profile: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    **query: str,
) -> TestResponse:
    params = begin(client, provider='facebook', headers=headers, **query)
    answer_facebook(mocked_http, profile)
    answer = {'code': 'the-code', 'state': params['state']}
    return client.get(FACEBOOK_CALLBACK_URL, query_string=answer)
```

At the end of the file, after line 1206, add two blank lines and:

```python
# Facebook Login


def test_providers_lists_facebook_after_google(
    client: FlaskClient, facebook: OAuthProvider
) -> None:
    assert client.get(f'{OAUTH_URL}/providers').get_json() == [
        {'name': 'google', 'label': 'Google'},
        {'name': 'facebook', 'label': 'Facebook'},
    ]


def test_facebooks_start_asks_again_for_a_declined_email_and_keeps_no_verifier(
    app: Flask, client: FlaskClient, facebook: OAuthProvider
) -> None:
    params = begin(client, provider='facebook')
    assert params['client_id'] == FACEBOOK_CLIENT_ID
    assert params['redirect_uri'] == f'{ORIGIN}/api/v1/auth/oauth/facebook/callback'
    assert params['scope'] == 'public_profile email'
    assert params['auth_type'] == 'rerequest'
    assert 'code_challenge' not in params
    assert transaction_in(app, client).code_verifier is None


def test_a_first_facebook_sign_in_makes_an_account(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    facebook: OAuthProvider,
) -> None:
    response = sign_in_with_facebook(client, mocked_http, FACEBOOK_PROFILE)
    assert redirect_location(response) == f'{ORIGIN}/'
    assert not has_transaction_cookie(client)
    assert me_from_the_session_cookie(client).get_json()['email'] == FACEBOOK_EMAIL
    # Only committed rows survive a rollback.
    db.session.rollback()
    link = db.session.query(OAuthAccount).one()
    assert (link.provider, link.provider_user_id) == ('facebook', '10101')
    assert (link.email, link.display_name) == (FACEBOOK_EMAIL, 'Sam Lee')
    assert link.user.has_password is False


def test_facebooks_token_request_carries_the_secret_and_no_verifier(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    facebook: OAuthProvider,
) -> None:
    sign_in_with_facebook(client, mocked_http, FACEBOOK_PROFILE)
    body = token_request_body(mocked_http, FACEBOOK_TOKEN_URL)
    assert body['client_id'] == FACEBOOK_CLIENT_ID
    assert body['client_secret'] == FACEBOOK_CLIENT_SECRET
    assert body['code'] == 'the-code'
    assert body['redirect_uri'] == f'{ORIGIN}/api/v1/auth/oauth/facebook/callback'
    assert 'code_verifier' not in body


def test_a_declined_facebook_email_is_email_required(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    facebook: OAuthProvider,
) -> None:
    profile = {'id': '10101', 'name': 'Sam Lee'}
    response = sign_in_with_facebook(client, mocked_http, profile)
    assert redirect_location(response) == f'{ORIGIN}/login?error=email_required'
    assert not has_transaction_cookie(client)
    db.session.rollback()
    assert db.session.query(User).count() == 0
    assert link_count(db) == 0


def test_a_returning_facebook_sign_in_needs_no_email(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    facebook: OAuthProvider,
) -> None:
    # The subject decides before the email does, so a person who later removes the
    # email permission still reaches the account it made.
    sign_in_with_facebook(client, mocked_http, FACEBOOK_PROFILE)
    response = sign_in_with_facebook(client, mocked_http, {'id': '10101'})
    assert redirect_location(response) == f'{ORIGIN}/'
    assert me_from_the_session_cookie(client).get_json()['email'] == FACEBOOK_EMAIL
    db.session.rollback()
    assert db.session.query(User).count() == 1


def test_a_facebook_email_an_account_holds_is_link_required(
    client: FlaskClient,
    db: SQLAlchemy,
    user: User,
    mocked_http: responses.RequestsMock,
    facebook: OAuthProvider,
) -> None:
    # Facebook's address counts as verified and still attaches to no existing account.
    profile = {**FACEBOOK_PROFILE, 'email': user.email}
    response = sign_in_with_facebook(client, mocked_http, profile)
    assert redirect_location(response) == f'{ORIGIN}/login?error=link_required'
    assert link_count(db) == 0


def test_a_cancelled_facebook_sign_in_is_cancelled(
    client: FlaskClient, mocked_http: responses.RequestsMock, facebook: OAuthProvider
) -> None:
    params = begin(client, provider='facebook')
    # Meta's documented decline, plus the error_code and the transaction's state that
    # its example leaves out.
    answer = {
        'error': 'access_denied',
        'error_code': '200',
        'error_description': 'Permissions error.',
        'error_reason': 'user_denied',
        'state': params['state'],
    }
    response = client.get(FACEBOOK_CALLBACK_URL, query_string=answer)
    assert redirect_location(response) == f'{ORIGIN}/login?error=cancelled'
    assert not has_transaction_cookie(client)
    assert len(mocked_http.calls) == 0


def test_a_refused_facebook_profile_lookup_is_exchange_failed(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    facebook: OAuthProvider,
) -> None:
    params = begin(client, provider='facebook')
    tokens = {'access_token': 'the-access-token', 'token_type': 'bearer'}
    mocked_http.add(responses.POST, FACEBOOK_TOKEN_URL, json=tokens)
    refusal = {'error': {'message': 'Invalid OAuth access token.', 'code': 190}}
    mocked_http.add(responses.GET, FACEBOOK_PROFILE_URL, status=400, json=refusal)
    answer = {'code': 'the-code', 'state': params['state']}
    response = client.get(FACEBOOK_CALLBACK_URL, query_string=answer)
    assert redirect_location(response) == f'{ORIGIN}/login?error=exchange_failed'
    assert not has_transaction_cookie(client)
    db.session.rollback()
    assert db.session.query(User).count() == 0


def test_linking_facebook_from_the_account_page(
    auth_client: FlaskClient,
    user: User,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    facebook: OAuthProvider,
) -> None:
    response = sign_in_with_facebook(
        auth_client, mocked_http, FACEBOOK_PROFILE, headers=SAME_ORIGIN, link='1'
    )
    assert redirect_location(response) == f'{ORIGIN}/account'
    db.session.rollback()
    link = db.session.query(OAuthAccount).one()
    assert (link.user_id, link.provider) == (user.id, 'facebook')
    assert link.email == FACEBOOK_EMAIL
```

### src_front/src/components/account/LinkedAccounts.tsx — a gap between wrapped rows

Line 68 opens the row of Link buttons. MUI 6.5.0's `Stack` spaces its children with a
left margin unless `useFlexGap` is set (`node_modules/@mui/system/Stack/createStack.js`,
lines 106 to 122 and 155), so a wrapped row keeps its first button's 8 px indent and has
no gap above it. An account with none of three providers linked shows "Link Google",
"Link Apple", and "Link Facebook", about 390 px of buttons in a 343 px column at 375 px.
Replace line 68 with Prettier's layout of the same element plus `useFlexGap`:

```tsx
            <Stack
                direction="row"
                spacing={1}
                useFlexGap
                sx={{ mt: 2, flexWrap: 'wrap' }}
            >
```

jsdom lays nothing out but applies MUI's styles, so a Vitest test can read the row's
computed `gap` and `flex-wrap` ("Frontend tests"); Verification step 4 measures the
layout itself in three browsers.

### src_front/src/utils/oauth.ts — why the email is needed

Line 11, the `email_required` entry of `ERROR_MESSAGES`, becomes the text Chuck chose
(point 15), in the layout Prettier prints for it, split so no line passes 90 columns:

```ts
    [
        'email_required',
        'The sign-in provider did not share an email address, which every account here ' +
            'needs. Share it and try again, or sign in another way.',
    ],
```

### Frontend tests — Facebook as a third provider

`src_front/src/test/utils/fixtures.ts`: after line 38, `appleProvider`, add a blank line
and:

```ts
/** Facebook, as the providers route lists it once both of its keys are set. */
export const facebookProvider: OAuthProviderInfo = { name: 'facebook', label: 'Facebook' }
```

`src_front/src/test/components/auth/ProviderButtons.test.tsx`: line 8 imports
`{ appleProvider, facebookProvider, googleProvider }`. Replace the body of
`links every enabled provider, in the order the server lists them`, lines 32 to 41,
keeping its Apple assertions:

```tsx
        vi.mocked(listProviders).mockResolvedValue([
            googleProvider,
            appleProvider,
            facebookProvider,
        ])

        render(<ProviderButtons next="/" />)

        const apple = await screen.findByRole('link', { name: 'Continue with Apple' })
        expect(apple).toHaveAttribute('href', '/api/v1/auth/oauth/apple/start?next=%2F')
        expect(
            screen.getByRole('link', { name: 'Continue with Facebook' }),
        ).toHaveAttribute('href', '/api/v1/auth/oauth/facebook/start?next=%2F')
        expect(screen.getAllByRole('link').map((link) => link.textContent)).toEqual([
            'Continue with Google',
            'Continue with Apple',
            'Continue with Facebook',
        ])
```

`src_front/src/test/components/account/LinkedAccounts.test.tsx`: line 11's import
becomes the multi-line form Prettier prints:

```tsx
import {
    appleProvider,
    facebookProvider,
    googleProvider,
    linkedGoogleAccount,
} from '../../utils/fixtures'
```

In `offers to link only the providers not yet linked`, line 56 lists all three
providers, as in the ProviderButtons test above, and after the Apple assertion (lines 59
to 62) add:

```tsx
        expect(screen.getByRole('link', { name: 'Link Facebook' })).toHaveAttribute(
            'href',
            '/api/v1/auth/oauth/facebook/start?next=%2Faccount&link=1',
        )
```

Before the test `says no providers are linked and still offers the link button`, add
this one, which Chuck approved during implementation. It fails without `useFlexGap`,
with `spacing={0}`, or without the wrap:

```tsx
    it('spaces the Link buttons with a gap that a wrapped row keeps', async () => {
        vi.mocked(listProviders).mockResolvedValue([
            googleProvider,
            appleProvider,
            facebookProvider,
        ])
        renderLinkedAccounts()

        // jsdom lays nothing out but applies MUI's styles: with useFlexGap the row spaces
        // its buttons with a gap, which a wrapped row keeps, instead of left margins.
        const link = await screen.findByRole('link', { name: 'Link Facebook' })
        const row = getComputedStyle(link.parentElement!)
        expect([row.getPropertyValue('flex-wrap'), row.getPropertyValue('gap')]).toEqual([
            'wrap',
            '8px',
        ])
    })
```

`src_front/src/test/utils/oauth.test.ts`: line 18, the `email_required` entry of
`MESSAGES`, becomes the same five lines as in `utils/oauth.ts`, at the same indentation.

### .env.example, .env.staging.example, the Compose files, and provisioning

`.env.example`: after line 65, `OAUTH_APPLE_PRIVATE_KEY=`, add:

```text
# Facebook appears once both keys are set: the App ID and the App secret from App
# settings, Basic, of the Meta app, or in development of a test app of it, whose
# callback step 5 of ai/auth.md's "Setting up Facebook" covers. Only people with a role
# on an app can sign in through it until it is Live with Advanced Access, which a test
# app never is.
OAUTH_FACEBOOK_CLIENT_ID=
OAUTH_FACEBOOK_CLIENT_SECRET=
```

`.env.staging.example`: lines 2 to 4 become:

```text
# (ai/staging.md). Copy this file to .env in the staging clone, chmod 600 it, and fill
# in every blank but SMTP_HOST and the optional OAUTH_* keys. Generate each secret with
# `openssl rand -hex 32`; none may match production's.
```

Lines 53 to 55 become:

```text
# Optional. Blank keeps each provider off here. To try one, register
# https://<DOMAIN>/api/v1/auth/oauth/<provider>/callback with it: with the Google
# client, as a return URL on the Services ID beside production's, or as the redirect
# URI of a test app of production's Meta app, which shares its user ids.
```

After line 61, `OAUTH_APPLE_PRIVATE_KEY=`, add:

```text
OAUTH_FACEBOOK_CLIENT_ID=
OAUTH_FACEBOOK_CLIENT_SECRET=
```

`docker-compose.yml`, after line 50, and `docker/docker-compose.prod.yml`, after line 40,
each `OAUTH_APPLE_PRIVATE_KEY: ${OAUTH_APPLE_PRIVATE_KEY:-}`, add:

```yaml
      OAUTH_FACEBOOK_CLIENT_ID: ${OAUTH_FACEBOOK_CLIENT_ID:-}
      OAUTH_FACEBOOK_CLIENT_SECRET: ${OAUTH_FACEBOOK_CLIENT_SECRET:-}
```

`scripts/provision.sh`: after line 135, `OAUTH_APPLE_PRIVATE_KEY=`, inside the unquoted
heredoc, add:

```text
# Facebook appears once both keys are set. Add
# https://$DOMAIN/api/v1/auth/oauth/facebook/callback to the Meta app's Valid OAuth
# Redirect URIs (ai/auth.md, "Setting up Facebook").
OAUTH_FACEBOOK_CLIENT_ID=
OAUTH_FACEBOOK_CLIENT_SECRET=
```

After line 173, the Apple `echo`, add:

```bash
  echo "    Facebook sign-in stays off until both OAUTH_FACEBOOK_* are filled in."
```

### scripts/tests — the three tests

`scripts/tests/test-compose-config.sh`: lines 2 to 14, the header, become:

```bash
# Render the development and production Compose configurations and check that only the
# development stack carries file watch, watchdog, and backend source owned by the app
# user, that every watched path exists and migrations sync without restarting the
# backend, that neither stack overrides the image's user, that both pass the .env's
# SMTP_*, OAUTH_GOOGLE_*, OAUTH_APPLE_*, and OAUTH_FACEBOOK_* variables to the backend,
# blank when unset, and Apple's private key, from a one-line value in the env file
# itself, with its line breaks, and what the production stack must keep: loopback-only
# ports and no database port; a backend that runs docker/entrypoint.sh under
# FLASK_ENV=production, where it starts gunicorn, with GUNICORN_WORKERS, secure session
# cookies, and the .env's APP_ENVIRONMENT passed through, blank when unset; and the
# nginx frontend. It needs the docker CLI with Compose, and jq, but no daemon; without
# them it exits 77, which scripts/tests/run-all.sh counts as a skip outside CI. It runs
# under macOS's bash 3.2 and on Linux.
```

Lines 27 to 30, the `unset`, gain a fifth line:

```bash
unset COMPOSE_FILE GUNICORN_WORKERS SESSION_COOKIE_SECURE SESSION_COOKIE_SAMESITE \
  APP_ENVIRONMENT SMTP_HOST SMTP_PORT SMTP_SECURITY SMTP_USERNAME SMTP_PASSWORD \
  SMTP_FROM OAUTH_GOOGLE_CLIENT_ID OAUTH_GOOGLE_CLIENT_SECRET OAUTH_APPLE_CLIENT_ID \
  OAUTH_APPLE_TEAM_ID OAUTH_APPLE_KEY_ID OAUTH_APPLE_PRIVATE_KEY \
  OAUTH_FACEBOOK_CLIENT_ID OAUTH_FACEBOOK_CLIENT_SECRET
```

Lines 60 to 62, the `export` in the OAuth subshell, gain a fourth line:

```bash
  export OAUTH_GOOGLE_CLIENT_ID=google-id OAUTH_GOOGLE_CLIENT_SECRET=google-secret \
    OAUTH_APPLE_CLIENT_ID=com.example.web OAUTH_APPLE_TEAM_ID=TEAMID1234 \
    OAUTH_APPLE_KEY_ID=KEYID12345 OAUTH_APPLE_PRIVATE_KEY=apple-key \
    OAUTH_FACEBOOK_CLIENT_ID=facebook-id OAUTH_FACEBOOK_CLIENT_SECRET=facebook-secret
```

After line 170, inside the `for stack in dev prod` loop and before the key check, add:

```bash
  check "$stack" '.services.backend.environment | .OAUTH_FACEBOOK_CLIENT_ID == ""
    and .OAUTH_FACEBOOK_CLIENT_SECRET == ""' \
    'blank OAUTH_FACEBOOK_* variables, which leave Facebook sign-in off'
  check "$stack-oauth" '.services.backend.environment
    | .OAUTH_FACEBOOK_CLIENT_ID == "facebook-id"
    and .OAUTH_FACEBOOK_CLIENT_SECRET == "facebook-secret"' \
    'the OAUTH_FACEBOOK_* variables its .env gives passed through to the backend'
```

A key missing from the base file reads as `null`, which fails the blank check.

`scripts/tests/test-provision.sh`: after line 165 add:

```bash
assert_contains '^OAUTH_FACEBOOK_CLIENT_ID=$' "$ENV_FILE"
assert_contains '^OAUTH_FACEBOOK_CLIENT_SECRET=$' "$ENV_FILE"
assert_contains '^# https://example\.com/api/v1/auth/oauth/facebook/callback ' "$ENV_FILE"
```

After line 200 add:

```bash
assert_contains 'Facebook sign-in stays off' "$OUTPUT"
```

`scripts/tests/test-deploy.sh`: after line 140 add the two lines below. The loop after
them, which checks that `.env.example` documents every key `.env.staging.example` sets,
then covers the new keys too.

```bash
assert_contains '^OAUTH_FACEBOOK_CLIENT_ID=$' "$STAGING_EXAMPLE"
assert_contains '^OAUTH_FACEBOOK_CLIENT_SECRET=$' "$STAGING_EXAMPLE"
```

### ai/auth.md — the flow, the linking policy, and Setting up Facebook

Line 7, `Google, Sign in with Apple, and Facebook (#31) build on the same groundwork:`,
loses its `(#31)`.

Lines 36 to 41, on accounts without a password, become:

```markdown
An account without a password got its email address from the sign-in provider that
created it: Google and Apple say they verified it, and Facebook's address is taken as
verified though Meta never says so ("The linking policy"). No sign-in attaches a provider
to an existing account by its email unless `AUTO_LINK_BY_EMAIL` is on. A project that
turns it on must also verify every address nobody has verified yet, such as one from
Facebook, an invitation, or a passkey-first sign-up, or linking a provider by email would
hand the account to whoever created it.
```

Lines 45 to 52, the opening of "Sign-in providers", become:

```markdown
A `Continue with <provider>` button runs the OAuth 2.0 authorization-code flow on the
backend, with OpenID Connect where the provider offers it. No token reaches the browser
and none is stored. A provider is enabled when its keys are set and `PUBLIC_BASE_URL` is
known, and Apple only when that is https; with none enabled, `/providers` answers `[]`
and the sign-in pages show only the password form. Google, Apple, and Facebook are the
providers so far, listed in that order. A new one is one `OAuthProvider` and one identity
function in `src_back/services/oauth_providers.py`. Its identity function receives the
callback's parameters as well as the token response, which is how Apple's first answer
delivers the person's name; Facebook's, which gets no ID token, spends the access token
on one profile lookup.
```

Lines 66 to 68, the end of step 2, become:

```markdown
   `next` defaults to `/`. It stores a transaction in the cookie below and redirects to
   the provider with `state`, `nonce`, and a PKCE challenge for a provider that supports
   one; Apple documents none, and Facebook one only for a flow it calls in testing.
```

Lines 69 to 71, step 3, become:

```markdown
3. The provider sends the browser back to `callback`, by GET, or by POST for Sign in with
   Apple. The callback trusts only the cookie: it compares `state`, exchanges the code,
   checks the ID token, or for Facebook asks the Graph API whose access token it got,
   resolves the account, and calls `complete_login`.
```

Line 82, the table's `exchange_failed` row, becomes (the cell keeps the column's width):

```markdown
| `exchange_failed`  | The provider refused the code or token, or was unreachable    |
```

Lines 90 to 92 become:

```markdown
A failed token exchange, key fetch, or Facebook profile lookup logs a warning; a wrong
client secret shows up there and nowhere else. OAuth's `access_denied`, which Facebook
sends too, and Apple's `user_cancelled_authorize` both read as `cancelled`.
```

After line 151, the end of the paragraph on rule 4, add a blank line and:

```markdown
Facebook sends no `email_verified`. Its profile holds "The User's primary email address
listed on their profile", left out when "no valid email address is available"
([Meta][fb-user]), and the template counts an address it returns as verified, though
Meta never calls it that. So rule 4 takes Facebook's word as it takes Google's, and rule
5 still refuses an address that an account holds. A project that turns on
`AUTO_LINK_BY_EMAIL` would take that word for linking as well.
```

After line 251, the last of the Apple section's link definitions, add a blank line and:

```markdown
### Setting up Facebook

Facebook Login for the web is OAuth 2.0 without OpenID Connect. The backend trades the
code for an access token and spends it on one Graph API call,
`GET /me?fields=id,name,email`, with the token in the `Authorization` header and
`appsecret_proof`, the token's HMAC-SHA256 under the app secret. `build_registry()`
enables Facebook once both of its keys are set, over plain http too, so the dev stack
can try it through a test app, which never leaves Development mode.

1. In Meta for Developers, create a Consumer app with the Facebook Login use case. It is
   production's app, and steps 2 to 4 set it up.
2. In the use case's Facebook Login settings, add production's Valid OAuth Redirect URI,
   `PUBLIC_BASE_URL + /api/v1/auth/oauth/facebook/callback`. Strict Mode, which every
   app must keep on, matches each URI exactly, and Enforce HTTPS, on for every app made
   since March 2018, refuses plain http ([Meta][fb-security]).
3. In App settings, Basic, the App ID is `OAUTH_FACEBOOK_CLIENT_ID` and the App secret
   `OAUTH_FACEBOOK_CLIENT_SECRET`. Going Live needs the Display Name, Contact Email,
   Terms of Service URL, App Icon, Category, and App Purpose there ([Meta][fb-basic]).
   Fill in the Privacy Policy URL as well: Meta requires a data deletion callback or an
   instructions URL, and a privacy policy that says how to ask for deletion
   ([Meta][fb-deletion]). The template has no callback, so point the instructions URL
   at that part of the policy, which Basic Settings allows.
4. In App settings, Advanced, turn on Require App Secret. Every Graph API call already
   comes from the backend with `appsecret_proof`, so the setting costs nothing, and an
   access token that leaks cannot then call the Graph API as this app.
5. Create a test app for staging and another for development: in the upper-left corner
   of the dashboard, open the app menu and choose Create Test App ([Meta][fb-test-apps]).
   A test app copies the parent's settings as they stand when it is made, so make each
   after steps 2 to 4, then replace its Valid OAuth Redirect URIs: staging's test app
   takes staging's callback. The development one takes none, because Meta's dashboard
   said in 2021 that `http://localhost` redirects are allowed "automatically" in
   Development mode, where a test app always is ([quoted here][fb-localhost]); if
   Facebook's page instead says the URL is blocked, put the dev stack behind an https
   tunnel, as "Setting up Apple" describes, and register that callback. Each test app has
   its own App ID and secret, and its "User IDs are scoped to the parent app", while a
   person's `id` is otherwise "unique to the app and cannot be used by other apps"
   ([Meta][fb-user]). So the links staging copies from production still match there,
   and production's secret stays off laptops and staging.
6. Put each app's keys in its environment's `.env`: production's app on production, and
   each test app on its own environment. Compose hands a container its values only when
   it creates one, so run `npm run deploy` on a server, or `npm run deploy:staging` on
   staging, after changing them. A server provisioned before this has no such lines,
   which leaves Facebook off.
7. Until production's app is Live and both `email` and `public_profile` have Advanced
   Access, only people with a role on it, such as its administrators, developers, and
   testers, can sign in ([Meta][fb-modes]), which suits an internal project. Meta
   approves a new Consumer app for Advanced Access to both but leaves them at Standard
   Access until someone switches them, and says "Business Verification is required to
   get Advanced Access" ([Meta][fb-access]), though going Live does not need it, so
   expect to complete it. Then switch the app to Live. A test app never goes Live: it
   inherits the parent's administrators, and anyone else who signs in through it, such
   as a staging tester, needs a role on it.

Things to know about Facebook:

- Meta documents PKCE only for an OpenID Connect variant of this flow, which it marks
  "still in testing", so the backend sends none, and the signed `state` alone ties
  Facebook's answer to the browser. The callback spends each code at once, and Meta
  matches the redirect URI exactly over https, so a code would have to leak unused, as
  from a callback refused for its `state` whose URL an access log kept, and be replayed
  in time. RFC 9700 says a client MUST prevent code injection, with PKCE or, for an
  OpenID Connect client, a nonce ([RFC 9700][rfc9700-code], section 2.1.1). This flow
  sends no PKCE challenge, and the nonce it sends comes back in no ID token to check, so
  it falls short of that until Meta calls the variant stable; then move to it, with
  `openid` in the scopes and the ID token checked as Google's is.
- A person may untick the email permission, and an account opened with a phone number
  may have no address; either ends at `email_required`, whose message asks the person
  to share the address and try again, or to sign in another way. The dialog carries
  `auth_type=rerequest`, so the next try asks for the email again ([Meta][fb-manual]).
  Meta warns of "Developer Alerts if your app repeatedly directs users to permissions
  dialogs after they deny permissions" ([Meta][fb-permissions]); the backend never
  sends anyone back on its own.
- Data access lapses 90 days after a person last used the app. Meta says "To regain
  data access, your app must ask the user to re-authorize", on the web with
  `auth_type=reauthorize` ([Meta][fb-data-access]), and does not say whether an ordinary
  sign-in renews it or what `/me` answers meanwhile. A returning sign-in needs only the
  `id`, matched by subject, but a person away that long may see `exchange_failed`, with
  the Graph API's status in the backend's log.
- `FACEBOOK_GRAPH_VERSION` names Graph API v27.0. Meta guarantees a version for at least
  two years; two years after the next one ships, it answers calls naming v27.0 with the
  oldest version it still serves, and it does not say what the Login Dialog then does
  ([Meta][fb-versions]), so move the constant, and the test that pins it, before then.
- A test app keeps the settings it was made with: a later change to production's app
  reaches no test app until someone makes it there too ([Meta][fb-test-apps]).
- A wrong app secret shows up only as `exchange_failed`, with a 400 from the token
  endpoint in the backend's log, and a refused profile lookup logs its status the same
  way. A wrong App ID, or a callback missing from Valid OAuth Redirect URIs, should
  stop on Facebook's own page, since RFC 6749 forbids redirecting for either
  ([RFC 6749][rfc6749], section 4.1.2.1).
- Unlinking Facebook here does not remove the app from the person's Facebook settings,
  and Meta's deauthorize and data deletion callbacks are not received. Accounts here are
  deactivated, never deleted, so a deletion request is the project's to answer: remove
  the link with the SQL in "The linking policy", and decide whether the account goes too.

[fb-user]: https://developers.facebook.com/docs/graph-api/reference/user
[fb-security]: https://developers.facebook.com/docs/facebook-login/security
[fb-basic]: https://developers.facebook.com/docs/development/create-an-app/app-dashboard/basic-settings
[fb-deletion]: https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback
[fb-modes]: https://developers.facebook.com/docs/development/build-and-test/app-modes
[fb-access]: https://developers.facebook.com/docs/graph-api/overview/access-levels
[fb-manual]: https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow
[fb-data-access]: https://developers.facebook.com/docs/facebook-login/auth-vs-data
[fb-versions]: https://developers.facebook.com/docs/graph-api/guides/versioning
[fb-test-apps]: https://developers.facebook.com/docs/development/build-and-test/test-apps
[fb-permissions]: https://developers.facebook.com/docs/facebook-login/guides/permissions/request-revoke
[fb-localhost]: https://community.auth0.com/t/problems-with-facebook-login-when-testing-connection/64718
[rfc9700-code]: https://www.rfc-editor.org/rfc/rfc9700#section-2.1.1
[rfc6749]: https://www.rfc-editor.org/rfc/rfc6749#section-4.1.2.1
```

### ai/project.md, ai/domain.md, ai/staging.md, and tools.md

`ai/project.md`, lines 167 to 173, the paragraph on sign-in providers, becomes:

```markdown
Sign-in providers are off until their keys are set: `build_registry()` in
`src_back/services/oauth_providers.py` enables Google when `OAUTH_GOOGLE_CLIENT_ID` and
`OAUTH_GOOGLE_CLIENT_SECRET` are both set and `PUBLIC_BASE_URL` is known, Sign in with
Apple when all four `OAUTH_APPLE_*` keys are set and `PUBLIC_BASE_URL` is https, warning,
once `PUBLIC_BASE_URL` is set, when any `OAUTH_APPLE_*` key is set but Apple stays off,
and Facebook when `OAUTH_FACEBOOK_CLIENT_ID` and `OAUTH_FACEBOOK_CLIENT_SECRET` are both
set and `PUBLIC_BASE_URL` is known. A server provisioned before these keys has no such
lines, which leaves the provider off. `ai/auth.md` has the setup steps.
```

Lines 175 to 180 become:

```markdown
`src_back/app.py` calls `load_dotenv()` at import, so `.env` values are visible to pytest
too. A test that depends on an environment variable sets or clears it with
`monkeypatch` first, as the `FLASK_ENV` and `CORS_ALLOWED_ORIGINS` tests in
`src_back/tests/test_app.py` do; `conftest.py` clears `APP_ENVIRONMENT`, the `SMTP_*`
variables, and the `OAUTH_GOOGLE_*`, `OAUTH_APPLE_*`, and `OAUTH_FACEBOOK_*` keys for
every test, so no test sends mail or reaches a provider through a developer's account.
```

`ai/domain.md`: after line 62, the `apple` bullet, add:

```markdown
- `facebook` - adds Facebook to the `app` fixture's registry, built from
  `FACEBOOK_ENVIRONMENT`; it brings `mocked_http`, which refuses any call a test has not
  answered
```

Lines 67 and 68 become:

```markdown
- `_clear_oauth_environment` and `_clear_jwks_cache` - autouse fixtures that clear the
  `OAUTH_GOOGLE_*`, `OAUTH_APPLE_*`, and `OAUTH_FACEBOOK_*` keys and the JWKS cache for
  every test
```

`ai/staging.md`, lines 25 to 27, the sign-in providers bullet, becomes:

```markdown
- sign-in providers, which stay off until `OAUTH_GOOGLE_*`, `OAUTH_APPLE_*`, or
  `OAUTH_FACEBOOK_*` is filled in, and need staging's own redirect URI registered with
  the provider, which for Apple is one more return URL on the same Services ID, and for
  Facebook the Valid OAuth Redirect URI of a test app of production's Meta app, whose
  ids match production's, so the copied links still sign in (`ai/auth.md`);
```

Lines 74 to 79, step 3, become:

```markdown
3. Fill in every blank in `.env` except `SMTP_HOST`, which stays blank so staging sends no
   mail, and the optional `OAUTH_GOOGLE_*`, `OAUTH_APPLE_*`, and `OAUTH_FACEBOOK_*` keys.
   Generate each secret with `openssl rand -hex 32`, and repeat `POSTGRES_PASSWORD`
   inside `DATABASE_URL`. Set both `CORS_ALLOWED_ORIGINS` and `PUBLIC_BASE_URL` to
   `https://<DOMAIN>`. `PRODUCTION_DIR` must name production's clone, and
   `STAGING_HTPASSWD` the file the next step creates.
```

Lines 176 to 181 become:

```markdown
Testers then sign in to staging with their production passwords. An account with no
password, which a sign-in provider created, can sign in there only when staging has that
provider's keys; for Facebook, those of a test app of production's app, on which the
tester also needs a role. Passkeys copy too, but none works there: each is bound to
production's host name, and staging has its own, so a tester adds a passkey on staging
to try one. An account whose only way in is a passkey cannot sign in to staging until an
admin there sets it a password.
```

`tools.md`, lines 87 to 89, the `requests` entry, becomes:

```markdown
- **requests**: the HTTP client for a provider sign-in's server-side calls: the token
  exchange in `src_back/services/oauth.py`, the key fetch in `oidc.py`, and Facebook's
  profile lookup in `oauth_providers.py`, each with a timeout.
```

Lines 132 and 133, the `responses` entry, become:

```markdown
- **responses**: replaces the `requests` transport in tests, so the token exchange, the
  key fetch, and Facebook's profile lookup run for real against canned answers
  (`mocked_http` in `conftest.py`).
```

### plans/ — archive #30's plan

```bash
git mv plans/pr-60-add-sign-in-with-apple.md plans/archive/
```

## Parallelism

Four groups can run at once; each is sequential inside. #27 names Sonnet 5.5 for #31's
group agents.

- **Group A, backend**: `oauth_providers.py`, then `conftest.py`, whose `facebook`
  fixture needs the new provider, then the three test files. Run
  `.venv/bin/python -m pytest src_back/tests/test_oauth_providers.py
  src_back/tests/test_oauth.py src_back/tests/test_oauth_api.py src_back/tests/test_app.py
  src_back/tests/test_schemas.py --no-cov` after the batch.
- **Group B, configuration and shell**: the two env templates, both Compose files, and
  `provision.sh`, then the three shell tests, run as `bash
  scripts/tests/test-compose-config.sh`, `bash scripts/tests/test-provision.sh`, and
  `bash scripts/tests/test-deploy.sh`.
- **Group C, frontend**: `LinkedAccounts.tsx`, `utils/oauth.ts`, and `fixtures.ts`,
  then the three test files, run with `npx vitest run
  src_front/src/test/utils/oauth.test.ts
  src_front/src/test/components/auth/ProviderButtons.test.tsx
  src_front/src/test/components/account/LinkedAccounts.test.tsx`.
- **Group D, documentation**: the five documents and the `git mv`. They name fixtures,
  constants, and messages that this plan fixes, so the group need not wait for A.

No group's tests read another group's files.

### Mutation checks

Each group runs these on a scratch copy of the repository, never the real files, behind
a dead `HTTP_PROXY` and `HTTPS_PROXY` for the backend, and with a timeout on every run.
Each must fail a test; report survivors rather than adding tests this plan does not
list.

- `oauth_providers.py`: `uses_pkce=True`; drop `auth_type`; drop `email` from the
  scopes; `FACEBOOK_PROFILE_FIELDS = 'id,name'`; `FACEBOOK_GRAPH_VERSION = 'v26.0'`; swap
  the HMAC's key and message; `hashlib.sha1`; drop `appsecret_proof`; send the token as
  an `access_token` query parameter instead of the header; `timeout=10`; drop
  `raise_for_status()`; drop the `isinstance(profile, dict)` check; drop the `id` check;
  `str(subject)` in place of the `isinstance` check; drop the access-token check; read
  the name raw instead of through `_storable_text`; `email_verified=True`; drop the
  email's `isinstance` check; list Facebook before Google; copy Apple's https check into
  `_facebook_provider`; log `exc` in place of the status; log the lookup's URL at INFO
  as well; read the email, `id`, or name from `callback_params`; pass `verify=False` to
  the profile lookup.
- `conftest.py`: drop `FACEBOOK_ENVIRONMENT` from `_clear_oauth_environment`, and run
  with `OAUTH_FACEBOOK_CLIENT_ID` and `OAUTH_FACEBOOK_CLIENT_SECRET` exported, as a
  developer's `.env` would; `test_no_provider_is_enabled_without_keys` must fail.
- `api/oauth.py`: remove `access_denied` from `_CANCELLED_ERRORS`.
- Shell: drop an `OAUTH_FACEBOOK_*` line from `docker-compose.yml`, from
  `provision.sh`'s heredoc, from `.env.example`, and from `.env.staging.example`; drop
  the Facebook `echo`.
- Frontend: render only `providers.slice(0, 2)` in `ProviderLinks`; restore the old
  `email_required` text in `utils/oauth.ts`; remove `useFlexGap`; `spacing={0}`; drop
  `flexWrap` from the row's `sx`.

One cannot fail by design: dropping a key from `docker/docker-compose.prod.yml`, which
Compose merges with the base file's identical entry, as #29 found. Verification step 4
measures the Link row's layout, which jsdom never computes.

## No other changes needed

- `src_back/api/oauth.py`: `callback` takes the GET Facebook sends, `_CANCELLED_ERRORS`
  already holds OAuth's `access_denied`, and `_finish_sign_in` checks `state` before it
  reads `error`, so a forged decline cannot end a sign-in in progress.
- `src_back/services/oauth.py`: `build_authorize_url` adds `auth_type` from
  `extra_authorize_params` and no challenge without a verifier, and `urlencode` writes
  the scopes' space as `+`; `exchange_code` posts `grant_type`, `code`, `redirect_uri`,
  `client_id`, and `client_secret`, leaves out `code_verifier` without one, and refuses
  a body that is not a JSON object; `_resolve_by_email` answers a missing email with
  `email_required` before it reads `email_verified`; `_attach_account` cuts the name to
  255 characters; `unlink_account` locks first and keeps the last sign-in method.
- `src_back/services/oauth_state.py`: a provider without PKCE gets a transaction without
  a verifier, and the http cookie, `oauth_txn` under `/api/v1/auth/oauth` with
  `SameSite=Lax`, reaches a GET callback in development.
- Models and migrations: `oauth_accounts.provider` is `String(32)`, which fits
  `facebook`, and `provider_user_id`, `email`, and `display_name` exist.
- Frontend production code other than `LinkedAccounts.tsx` and the `email_required`
  message: `ProviderButtons`, `SignInOptions`, and `utils/oauth.ts` draw every provider
  from `{name, label}`, and Facebook adds no `?error=` code.
- nginx: the callback is a GET, which the sign-in throttle does not count, as for
  Google.
- `requirements.txt`: `requests` is installed, and `hmac` and `hashlib` are the standard
  library's.
- `scripts/deploy.sh`, `copy-production.sh`, and the other scripts read no `OAUTH_*` key.
- `.gitignore` and `.dockerignore`: Facebook has no key file.
- Facebook's deauthorize and data deletion callbacks, and button branding: out of scope,
  and `ai/auth.md` says what each would need.

## Added during implementation

Chuck approved these on 2026-11-07, after the groups' mutation checks, PostgreSQL, and
the browser check had run:

- The `LinkedAccounts.test.tsx` test in "Frontend tests" that reads the Link row's
  computed `gap` and `flex-wrap`. The frontend group found that jsdom applies MUI's
  styles, so the gap is testable after all.
- Three `ai/auth.md` wording fixes the docs group and the browser check found. The
  Facebook bullet on PKCE, in the block above, now says the flow sends no PKCE challenge
  and that no ID token brings its nonce back, so it no longer seems to contradict step 2,
  where every redirect carries a nonce. "The transaction cookie" and "The linking policy",
  text from #29, now say what the browser check saw: Chrome 156 sends the
  `SameSite=Strict` session to a callback the provider redirects to at once, while
  WebKit and Firefox withhold it. The replay sentence counts Facebook's two calls.

The first paragraph of "The transaction cookie" becomes:

```markdown
Production's session cookie is `SameSite=Strict`, so the callback cannot count on it.
Browsers withhold such a cookie from a navigation another site started, such as a click
on the provider's page, and Firefox and WebKit withhold it when the provider redirects at
once, though Chrome 156 then sends it. There is no Redis, and gunicorn's workers share no
memory. So `src_back/services/oauth_state.py` keeps the transaction in a cookie of its
own: signed with `SECRET_KEY`, `HttpOnly`, and good for ten minutes. It holds nothing the
browser's owner should not see. The callback's response stores the session cookie. The
browser may leave it off the redirect that follows, which is harmless, because the SPA's
`/me` call is same-site.
```

The paragraph on the callback's GET there becomes:

```markdown
The callback's GET is not throttled, because nginx counts only POSTs. One valid cookie can
replay it for ten minutes, and each replay holds a sync worker for a round trip to the
provider, or two to Facebook. A `limit_req` for it needs a location per provider, which
is its own issue.
```

In "The linking policy", the paragraph on link mode becomes:

```markdown
Link mode needs that same-origin request as well as the session, so another site cannot
start it, and a stale session cannot turn a sign-in into a link. Every link and unlink is
audited in `oauth_accounts`, admin-only. A link made in the callback has an actor only
when the browser sent the session there, which production's cookie mostly prevents ("The
transaction cookie"). Unlinking the last way to sign in is a 409.
```

The last two lines before its `DELETE FROM oauth_accounts` example become:

```markdown
production callback may have no actor, and match each entry's `user_id` to the account.
Before reactivating it, remove any link its owner does not recognize in a database shell:
```

The archive step found `plans/pr-60-add-sign-in-with-apple.md` already moved into
`plans/archive/`, byte for byte, but unstaged; staging both paths recorded the rename that
`git mv` would have.

## Verification

1. Targeted, while editing: each group's command above.
2. At the end, in parallel: `npm run test`, `npm run lint -- --max-warnings=0`, and `npm
   run lint:py`; then `npm run typecheck`, `npm run lint:md`, `npx prettier --check .`,
   `npm run build`, `npm run test:scripts`, and `npx fallow audit`.
3. Against PostgreSQL, which refuses the NUL that SQLite stores: start a throwaway
   `postgres:16` container named `facebook-check-pg-<pid>`, run `TEST_DATABASE_URL=<its
   URL> .venv/bin/python -m pytest`, and remove it by that name.
4. In real browsers, against a stub Facebook on another site, with production's cookie
   settings and a production build, all in the scratchpad and nothing committed. #30's
   harness, `runner.py` and `stub_apple.py` in this directory, is the starting point:
   `/private/tmp/claude-501/-Users-chuck-Projects-chivalry-flask-react-template/e40557e0-b6da-4025-a39e-a7be6ee2d393/scratchpad/browser-check/`.
   Both were there on 2026-11-07, but macOS empties `/private/tmp` at boot; if they are
   gone, build the runner and the stub afresh from the description below:
    - The runner builds the real providers with `build_registry()`: Google from fake
      keys, Apple from a scratch P-256 key, and Facebook, with `dataclasses.replace`
      pointing Facebook's authorize and token URLs at the stub on
      `http://127.0.0.1:<other port>` and the module's `FACEBOOK_PROFILE_URL` patched to
      the stub's `/me`.
    - The stub's `/dialog/oauth` checks `auth_type=rerequest` and the absence of a
      `code_challenge`, then redirects back with `code` and `state`, or with
      Facebook's decline parameters and `state` when asked to cancel, ending each
      redirect in `#_=_`, as Facebook's have long ended. Its `/oauth/access_token`
      checks the client secret, the redirect URI, and that no `code_verifier` came, and
      its `/me` checks the `Authorization` header and that `appsecret_proof` is the
      token's HMAC under the secret, then answers with or without `email`, as each
      check asks.
    - Playwright 1.64.1 drives Chrome (`channel: 'chrome'`), WebKit, and Firefox:
      "Continue with Facebook" signs up and reaches `/` with `/api/v1/auth/me`
      answering 200; a profile without `email` shows the new `email_required` message
      (point 15) on `/login`; a cancel shows "Sign-in was cancelled."; and a password
      account links Facebook from `/account` and lands back there. Each page works
      with the `#_=_` that the browser carries over from the stub's redirect.
    - At 375 px, a password account with no links shows three Link buttons on
      `/account`: the wrapped row's first button starts at the first row's left edge,
      8 px below it.
    - Stop the runner and the stub, and confirm no process holds either port.
5. By Chuck, before the PR leaves draft, because only a Meta developer account can.
   Follow "Setting up Facebook" steps 1 to 4 for production's app, leave it in
   Development mode with Require App Secret on, and put its keys in the dev `.env` for
   the first two checks. Sign in with his own Facebook account, which holds the app's
   administrator role. Each check settles a point Meta's pages leave open:
    - "Continue with Facebook" signs up and lands on `/`: Meta accepts the
      `http://localhost` callback (point 11), the dialog takes the nonce (point 13),
      the exchange works by POST (point 14), and `/me` takes the Bearer header and the
      untimed proof with Require App Secret on (points 4 and 5). Note whether the
      address ends in `#_=_`, which Facebook has long added to its redirects and a
      browser keeps across the callback's own redirect (RFC 9110, section 10.2.2); it
      is cosmetic, and stripping it would be a follow-up.
    - If Facebook's page says the URL is blocked instead, Development mode does not take
      an unlisted `http://localhost` callback. Record what it says, run the dev stack
      behind an https tunnel, as "Setting up Apple" describes, and register the tunnel's
      callback on production's app, removing it once these checks end, and on the
      development test app; then repeat the check above.
    - Signing out and in again reaches the same account.
    - Create the development test app (step 5 of "Setting up Facebook"), put its keys
      in the dev `.env` in place of the parent's, and restart the stack with
      `npm run docker:up`, which recreates the backend with them. Signing in through
      the test app reaches the same account, which proves that a test app's ids are
      the parent's (point 10). If it answers `link_required` instead, the ids differ,
      and the runbook goes back to one app for every environment. The checks below
      use the test app.
    - If the dashboard offers Create Test App only once the parent is Live, record it,
      and run the checks below with production's app: the runbook's step 5 then moves
      after step 7, and the id comparison waits until production's app is Live.
    - After removing the app in Facebook's settings, a sign-in with the email
      permission unticked shows the `email_required` message, and the next sign-in
      asks for the email again (point 3).
    - A cancel at Facebook's dialog shows "Sign-in was cancelled.", which proves that
      the decline carries `state`; without it the page would show the `invalid_state`
      message, and the plan needs another look.
    - A password account links Facebook from Account, lands back there, and unlinks it.
      Note whether the link's audit entry names an actor: Chrome 156 sends the session
      to a callback the provider redirects to at once, and WebKit and Firefox do not.
    - The backend logged no warning. If any check fails, record what Facebook answered
      before changing the code.
