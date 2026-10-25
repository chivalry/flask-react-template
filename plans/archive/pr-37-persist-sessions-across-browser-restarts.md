# Issue #5: Persist Sessions Across Browser Restarts

## Context

Users are signed out whenever their browser restarts. `register()` and `login()` call
`login_user(user)` (`src_back/api/auth.py:29` and `:46`) without marking the session
permanent. For a non-permanent session Flask's `get_expiration_time` returns `None`, so
the `session` cookie goes out with no `Expires` or `Max-Age`, and the browser drops it
when it quits. The fix makes the session permanent at sign-in with a 30-day sliding
lifetime. Per the issue's comment, logout also clears the session: `logout_user()`
removes only `_user_id`, `_fresh`, and `_id`, so Flask's `_permanent` key would survive
and Flask would renew an empty cookie for 30 days instead of deleting it.

`chivalry/hukilau` shipped this fix in `73fdf8f` on the same stack (Flask 3.1.0,
Flask-Login 0.6.3, the same `app` fixture), planned in its
`plans/archive/pr-28-users-are-signed-out-whenever-their.md`. This plan ports that commit
verbatim, so a later template-to-hukilau sync is a no-op on these lines, except where the
template differs:

- The template also has `register()`. It gets the same line, a docstring paragraph, and
  its own expiry test, since the acceptance criteria name registration.
- Template tests are annotated: Ruff ignores only `D` under `src_back/tests/*`
  (`pyproject.toml:20-21`), so `ANN` applies to the new helper and tests.
- The logout test drops Flask-Login's cached user with `g.pop('_login_user', None)`, the
  template's existing idiom (`src_back/tests/test_app.py:139-142`), instead of hukilau's
  fresh `app.app_context()`, which the template documents nowhere.
- The template has no account deactivation, so the conventions bullet drops hukilau's
  "at deactivation" and its `Account is inactive.` sentence, and names registration.

The change is backend only: no endpoint, payload, model, migration, frontend, or
environment change. A sign-in already open when a project deploys this keeps its
browser-session cookie until the user signs in again. The server enforces the same
limit: `open_session` rejects any session cookie signed more than
`PERMANENT_SESSION_LIFETIME` ago, which tightens from Flask's default 31 days to 30. The
issue's prerequisite, PR 3 (`tool-upgrade`), merged on 2026-10-13.

Issue #28 later moves every `login_user` call into a `complete_login(user)` helper in
`src_back/services/auth.py` and names #5 as one of the behaviors it centralizes. This
issue does not add that helper; #28 carries both `session.permanent = True` lines into
it (`plans/open-issues-order-and-parallel-work.md:88` already has #28 waiting on #5).

Three risks are accepted, as hukilau accepted the first two:

- The session is a signed client-side cookie, so logout deletes only this browser's
  copy. Flask already honored a copied cookie for 31 days after it was signed (the
  default `PERMANENT_SESSION_LIFETIME`, enforced in `open_session`). With a sliding
  refresh, whoever keeps using a copied cookie keeps it alive. Closing that needs
  server-side session state, such as a per-user session version checked in `load_user`,
  which this issue does not add.
- Every response now re-sends the cookie. A request that leaves before logout and is
  answered after it puts the signed-in cookie back. This takes unlucky timing.
- When `POST /logout` itself fails, `logout()` in `src_front/src/store/auth.ts:79-88`
  clears the user on screen anyway and the cookie stays. A reload already restored that
  user; now a browser restart does too, for up to 30 idle days.

## Branch

`issue-5-persist-sessions-across-browser-restarts` — already checked out; PR #37 exists.

## Change

**4 files to edit**: `src_back/app.py`, `src_back/api/auth.py`,
`src_back/tests/test_auth.py`, and `ai/conventions.md`.

### `src_back/app.py` — the session lifetime

Import `timedelta` between `from collections.abc import Callable` (line 10) and
`from pathlib import Path` (line 11), where Ruff's isort places it:

```python
import logging
import os
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
```

Add the constant after `MAX_UPLOAD_MB = 25` (line 28):

```python
MAX_UPLOAD_MB = 25
SESSION_LIFETIME_DAYS = 30
```

In `_configure_application` (lines 94-119), set the lifetime right after the
`SESSION_COOKIE_SECURE` assignment (lines 113-115), so the session settings stay
together:

```python
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=SESSION_LIFETIME_DAYS)
```

Extend the docstring's second paragraph (lines 97-99), hukilau's wording:

```python
    Development-friendly defaults keep the app starting with no ``.env``
    present. Uploads are resolved to an absolute path and capped at
    ``MAX_UPLOAD_MB``. A sign-in lasts ``SESSION_LIFETIME_DAYS`` past its latest
    request: login makes the session permanent, and Flask re-sends a permanent
    session's cookie with a fresh expiry on every response.
```

`SESSION_REFRESH_EACH_REQUEST` keeps Flask's default of `True`; nothing in the repo sets
it.

### `src_back/api/auth.py` — permanent at sign-in, cleared at logout

Add `session` to the Flask import on line 3:

```python
from flask import Blueprint, Response, jsonify, session
```

In `register()` (lines 13-30), mark the session permanent right after
`login_user(user)` (line 29), and add a docstring paragraph after the existing one
(lines 17-18). This paragraph is the template's own, since hukilau has no registration:

```python
    """Create an account and sign the new user in immediately.

    A payload that fails validation never reaches this body: ``parse_request_json``
    raises and the application answers with a 422 envelope.

    The session is permanent, as in :func:`login`, so the new user stays signed in
    across a browser restart.

    Returns:
        The serialized user with status 201, or a 409 envelope when the email is
        already registered.
    """
    data = parse_request_json(user_schema)
    try:
        user = register_user(data['email'], data['password'])
    except ValueError as e:
        return conflict(str(e))
    login_user(user)
    session.permanent = True
    return jsonify(user_schema.dump(user)), 201
```

In `login()` (lines 33-47), mark the session permanent right after `login_user(user)`
(line 46). Replace the docstring's summary line (line 35) and add hukilau's paragraph
before `Returns:`:

```python
    """Verify credentials and start a session that survives a browser restart.

    The session is permanent, so its cookie carries an expiry
    ``SESSION_LIFETIME_DAYS`` out, and every later response pushes it forward.

    Returns:
        The serialized user on success, or a 401 envelope when the credentials
        do not match. The message does not distinguish an unknown email from a
        wrong password.
    """
    data = parse_request_json(login_schema)
    user = authenticate_user(data['email'], data['password'])
    if not user:
        return unauthorized('Invalid email or password.')
    login_user(user)
    session.permanent = True
    return jsonify(user_schema.dump(user))
```

In `logout()` (lines 50-59), clear the session after `logout_user()` (line 58). Replace
the summary line (line 53) and add hukilau's paragraph:

```python
    """End the current session and delete its cookie.

    ``logout_user()`` removes only Flask-Login's keys, so clearing the session
    also drops the permanent flag that login set. Flask deletes the cookie of an
    emptied session instead of renewing it.

    Returns:
        A JSON confirmation message.
    """
    logout_user()
    session.clear()
    return jsonify({'message': 'Logged out.'})
```

### `src_back/tests/test_auth.py` — expiry at sign-in, refresh, and logout

Replace the import block (lines 1-3) and add a lifetime constant and one helper:

- `client.get_cookie()` returns Werkzeug's `Cookie`, whose `expires` is a UTC-aware
  `datetime` (Flask 3.1.0 requires Werkzeug 3.1 or later). Flask passes only `expires`
  to `set_cookie`, so `max_age` stays `None`; assert on `expires`.
- The `Expires` attribute keeps only whole seconds, so the lower bound drops the
  fraction from `before`; the clock reading `after` bounds the expiry from above.
- No time-mocking library is installed, and none is needed.

```python
from datetime import UTC, datetime, timedelta

from flask import g
from flask.testing import FlaskClient

from src_back.app import SESSION_LIFETIME_DAYS
from src_back.models import User

SESSION_LIFETIME = timedelta(days=SESSION_LIFETIME_DAYS)


def _assert_session_cookie_expires_one_lifetime_after(
    client: FlaskClient, before: datetime, after: datetime
) -> None:
    cookie = client.get_cookie('session')
    assert cookie is not None
    assert cookie.expires is not None
    # Expires carries whole seconds, so the earliest bound drops the fraction.
    earliest = before.replace(microsecond=0) + SESSION_LIFETIME
    assert earliest <= cookie.expires <= after + SESSION_LIFETIME
```

Add `test_register_cookie_expires_one_session_lifetime_out` after
`test_register_success` (lines 6-17). It is the template's own test:

```python
def test_register_cookie_expires_one_session_lifetime_out(client: FlaskClient) -> None:
    before = datetime.now(UTC)
    r = client.post(
        '/api/v1/auth/register',
        json={'email': 'new@example.com', 'password': 'secure123'},
    )
    after = datetime.now(UTC)
    assert r.status_code == 201
    _assert_session_cookie_expires_one_lifetime_after(client, before, after)
```

Add `test_login_cookie_expires_one_session_lifetime_out` after `test_login_success`
(lines 59-67):

```python
def test_login_cookie_expires_one_session_lifetime_out(
    client: FlaskClient, user: User
) -> None:
    before = datetime.now(UTC)
    r = client.post(
        '/api/v1/auth/login',
        json={'email': user.email, 'password': 'password123'},
    )
    after = datetime.now(UTC)
    assert r.status_code == 200
    _assert_session_cookie_expires_one_lifetime_after(client, before, after)
```

Add `test_logout_deletes_the_session_cookie` after `test_logout_success` (lines 92-95).
The `app` fixture (`src_back/tests/conftest.py:44-63`) keeps one app context for the
whole test, every request reuses it, and Flask-Login caches the user on its `g`. After
logout that cached user is anonymous, so `/me` would answer 401 whatever the cookie
held. Popping the cache, as `test_app.py:139-142` does, makes `/me` read the request:

```python
def test_logout_deletes_the_session_cookie(auth_client: FlaskClient) -> None:
    assert auth_client.post('/api/v1/auth/logout').status_code == 200
    assert auth_client.get_cookie('session') is None
    # The test app context is shared across client requests, so drop flask_login's
    # cached g._login_user to make /me read the session cookie, which is now gone.
    g.pop('_login_user', None)
    assert auth_client.get('/api/v1/auth/me').status_code == 401
```

Add `test_authenticated_request_extends_the_session_cookie` after
`test_me_authenticated` (lines 103-106). Its `Set-Cookie` check is what proves the
re-send: without it, the jar would still hold the login cookie, whose expiry can fall
inside the same bounds when both requests land in one second.

```python
def test_authenticated_request_extends_the_session_cookie(
    auth_client: FlaskClient,
) -> None:
    before = datetime.now(UTC)
    r = auth_client.get('/api/v1/auth/me')
    after = datetime.now(UTC)
    assert r.status_code == 200
    assert any(h.startswith('session=') for h in r.headers.getlist('Set-Cookie'))
    _assert_session_cookie_expires_one_lifetime_after(auth_client, before, after)
```

Run `npm run format:py` after writing the tests; Ruff format owns where the long `def`
lines break.

Each new test fails without its line of the fix:

- Without `session.permanent = True` in `register()` or `login()`, that route's expiry
  test fails on `cookie.expires is not None`; without it in `login()`, the refresh test
  also fails its `Set-Cookie` check.
- Without `session.clear()`, the logout test fails on `get_cookie('session')`.

### `ai/conventions.md` — the auth bullet (lines 35-36)

Replace the bullet with hukilau's, naming registration and dropping deactivation. Lines
stay within markdownlint's 90 (`.markdownlint.json`):

```markdown
- Auth is a Flask-Login session cookie. Login and registration mark the session
  permanent, so the cookie carries an expiry and survives a browser restart, and Flask
  re-sends it with a fresh expiry on every response: a sign-in ends at logout or after
  `SESSION_LIFETIME_DAYS` (30, in `app.py`) without a request. Protect routes with
  `@login_required` or `@admin_required` (401 for anonymous callers, 403 for non-admins).
```

## Parallelism

- **Can be done in parallel**: `src_back/app.py`, `src_back/api/auth.py`, and
  `ai/conventions.md` are separate files with no dependencies on each other.
- **Must be sequential**: `src_back/tests/test_auth.py` imports `SESSION_LIFETIME_DAYS`
  from `src_back/app.py`, so it follows that edit. The targeted pytest run follows all
  the code edits.

## No other changes needed

- No other sign-in or sign-out path exists: `login_user` and `logout_user` appear only
  in `src_back/api/auth.py` (lines 29, 46, 58). `src_back/services/auth.py` only creates
  and checks accounts, the seed creates no user, and there is no password-change route.
- No test reads `Set-Cookie` or cookie attributes today, so adding `Expires` breaks
  nothing. Every test that signs in goes through the real route and keeps working: the
  `auth_client` and `admin_client` fixtures (`conftest.py:94-109`), `_login()`
  (`test_utils.py:316-317`), and `test_user_loader_reloads_user_from_session`
  (`test_app.py:133-145`). Backend coverage stays at 100%, because the existing
  register, login, and logout tests already run every new line.
- Frontend: `fetchMe` (`src_front/src/store/auth.ts:68-78`) runs on mount
  (`src_front/src/App.tsx:27-31`), and the axios client sends the cookie
  (`withCredentials`, `src_front/src/api/client.ts:29`). Nothing on the client stores
  the session (`store/auth.ts:44`), so a cookie that survives the restart restores the
  user.
- Production's `SameSite=Strict` (`docker/docker-compose.prod.yml:22-23`,
  `scripts/provision.sh:94-95`) does not block this: `fetchMe` is a same-origin request.
  nginx (`docker/nginx.conf:21-26`, `scripts/nginx-ssl.conf.template:33-39`) and the
  Vite dev proxy (`vite.config.ts:62-66`) pass `Set-Cookie` through unchanged.
- The lifetime is a constant, not an environment variable, so `.env.example`,
  `docker-compose.yml`, and `provision.sh` stay as they are. `ai/domain.md` (Accounts)
  and the frontend bullets in `ai/conventions.md` (lines 61-69) remain accurate.
- Noticed, out of scope: `.env.example:21` sets `SESSION_COOKIE_HTTPONLY=true`, which
  nothing reads, since `app.py:109` hard-codes `True`.

## Verification

1. **Bootstrap.** The checkout is a fresh clone with no `.venv` or `node_modules`, as
   the README's quick start describes:

    ```bash
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    npm install
    ```

2. **Targeted tests** while editing:

    ```bash
    .venv/bin/python -m pytest src_back/tests/test_auth.py \
      src_back/tests/test_app.py src_back/tests/test_utils.py --no-cov
    ```

3. **Gates.** Run `npm run test`, `npm run lint`, `npm run lint:py`, and
   `npm run lint:md` in one parallel batch; the backend suite enforces 100% coverage.
4. **Dev stack.** Run `npm run docker:up`, then `npm run docker:url`, and register or
   sign in.
    - The response's `Set-Cookie` carries `Expires` 30 days out, with `HttpOnly`,
      `Path=/`, and `SameSite=Lax`. In DevTools, Application, Cookies, the `session`
      row shows that date instead of `Session`. Check this rather than rely on the
      restart alone: a browser set to restore its previous session also restores
      session-only cookies, so the restart test can pass without the fix.
    - Reload: the `/me` response carries a new `Set-Cookie` with a later `Expires`.
    - Quit and reopen the browser: still signed in.
    - Sign out: the logout response expires the cookie (`Max-Age=0`), and a reload
      lands on the login page.
5. **Edge cases.** A wrong password (401), a taken email (409), and an invalid payload
   (422) all return before `login_user`, so none marks a session permanent; the existing
   tests cover those responses. Logout deleting the cookie is the new logout test.
