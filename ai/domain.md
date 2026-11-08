# Domain

Describe the problem the application solves and the vocabulary its code uses. Replace
this placeholder when starting a project, and keep it to what an agent needs in order
to put new behavior in the right service.

## Domains

- Accounts: `User` with the `admin` and `user` roles. Registration, login, logout,
  and the current-user lookup live in `src_back/api/auth.py` and
  `src_back/services/auth.py`; `ai/auth.md` covers sign-in in depth. An account a
  sign-in provider creates has no password (`password_hash` is `NULL`), which
  `User.has_password` and the `has_password` field of the user payload report.
  Admins manage accounts through `/api/v1/users` (`src_back/api/users.py` and
  `src_back/services/users.py`) and the Users tab of the admin screen: they create
  accounts with any role and change an account's email, password, role, and active
  state. Nothing deletes an account; deactivating one (`User.is_active`) keeps the rows
  that reference it, and an admin cannot demote or deactivate themself. An `OAuthAccount`
  links a provider identity to an account, one per provider, matched on the provider's
  subject and never on its email (`src_back/services/oauth.py`, `ai/auth.md`). A
  `WebAuthnCredential` is a passkey; an account has any number, each found at sign-in by
  its credential id and tied to its account by the user handle, the account's `uuid`
  (`src_back/services/passkeys.py`, `ai/auth.md`).
- Audit log: `AuditLog` rows record each create, update, and delete an audited
  service makes (`src_back/services/audit_log.py`), with the signed-in account as the
  actor. Accounts are audited at registration, when a sign-in provider creates one, on
  the admin's Users screen, and by the seed, each provider link in `oauth_accounts`, and
  each passkey in `webauthn_credentials`; their history is admin-only, and a password
  change appears only masked.
  Anyone signed in reads one record's history through `/api/v1/audit-logs`; admins
  read and filter the whole log on the Audit tab of the admin screen.

## Test Fixtures

`src_back/tests/conftest.py` provides:

- `app` - application in testing mode with an in-memory SQLite database and a
  temporary `UPLOAD_FOLDER`; its `PUBLIC_BASE_URL` is `https://app.test`, and Google is
  enabled with fake keys
- `client` - unauthenticated test client
- `db` - the SQLAlchemy extension bound to the test app
- `user` and `admin_user` - persisted accounts with the passwords `password123` and
  `adminpass123`
- `passwordless_user` - a persisted account without a password, as a sign-in provider
  creates one
- `inactive_user` - a persisted, deactivated account with the password `password123`
- `linked_user` - a passwordless account linked to Google
- `authenticator` - a `SoftwareAuthenticator`
  (`src_back/tests/software_authenticator.py`), a P-256 passkey that answers both
  ceremonies as a browser would
- `passkey_user` - `passwordless_user` with that authenticator's passkey as its only way
  in
- `auth_client` and `admin_client` - clients signed in as those accounts
- `Widget` and `WidgetNote` - test-only models exercising the generic services and
  `BaseSchema`; `test_base_service.py` builds audited services over them
- `PNG_BYTES` - a minimal PNG for upload tests
- `mocked_http` - a `responses.RequestsMock`
- `oidc_signer` - signs ID tokens, and serves its key at Google's JWKS URL
- `apple_signer` - `oidc_signer`, also serving its key at Apple's JWKS URL;
  `APPLE_ID_TOKEN_CLAIMS` makes a token it signs Apple's
- `apple` - adds Sign in with Apple to the `app` fixture's registry, built from
  `APPLE_ENVIRONMENT` with a P-256 key made once per run
- `facebook` - adds Facebook to the `app` fixture's registry, built from
  `FACEBOOK_ENVIRONMENT`; it brings `mocked_http`, which refuses any call a test has not
  answered
- `_clear_app_environment` - an autouse fixture that clears `APP_ENVIRONMENT`, so a
  developer's `.env` cannot rename the session cookie
- `_clear_smtp_environment` - an autouse fixture that clears the `SMTP_*` variables, so
  every test starts with mail off and a developer's `.env` cannot make one send mail
- `_clear_oauth_environment` and `_clear_jwks_cache` - autouse fixtures that clear the
  `OAUTH_GOOGLE_*`, `OAUTH_APPLE_*`, and `OAUTH_FACEBOOK_*` keys and the JWKS cache for
  every test

The `app` fixture sets `app.test_client_class` to `SpaTestClient`, so every client the
tests build, `app.test_client()` included, sends `X-Requested-With: XMLHttpRequest` as
the SPA does. To send a request without it, pop `HTTP_X_REQUESTED_WITH` from the
client's `environ_base`.

`src_back/tests/helpers.py` provides `persist(record)`, which adds a record, commits it,
and returns it; use it instead of repeating those three lines.

Building an `AuditTrail` registers its table for the rest of the run. A test that needs a
known set of audited tables replaces the registry with
`monkeypatch.setattr(audit_log, '_AUDITED_TABLES', {...})` inside the test or a fixture,
as `test_audit_logs_api.py` does.

The `app` fixture keeps one application context pushed for the whole test, and every
test-client request reuses it. Flask-Login caches the loaded user on `g` for that
context, so the cache outlives a request: to make the next request read the session
cookie again, drop it with `g.pop('_login_user', None)`, as `test_auth.py` and
`test_app.py` do, and run a second client's requests inside a fresh `app.app_context()`
so the two clients do not share one cached user.
