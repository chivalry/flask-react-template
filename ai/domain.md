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
  that reference it, and an admin cannot demote or deactivate themself.

## Test Fixtures

`src_back/tests/conftest.py` provides:

- `app` - application in testing mode with an in-memory SQLite database and a
  temporary `UPLOAD_FOLDER`
- `client` - unauthenticated test client
- `db` - the SQLAlchemy extension bound to the test app
- `user` and `admin_user` - persisted accounts with the passwords `password123` and
  `adminpass123`
- `passwordless_user` - a persisted account without a password, as a sign-in provider
  creates one
- `inactive_user` - a persisted, deactivated account with the password `password123`
- `auth_client` and `admin_client` - clients signed in as those accounts
- `Widget` and `WidgetNote` - test-only models exercising the generic services and
  `BaseSchema`
- `PNG_BYTES` - a minimal PNG for upload tests

`src_back/tests/helpers.py` provides `persist(record)`, which adds a record, commits it,
and returns it; use it instead of repeating those three lines.

The `app` fixture keeps one application context pushed for the whole test, and every
test-client request reuses it. Flask-Login caches the loaded user on `g` for that
context, so the cache outlives a request: to make the next request read the session
cookie again, drop it with `g.pop('_login_user', None)`, as `test_auth.py` and
`test_app.py` do, and run a second client's requests inside a fresh `app.app_context()`
so the two clients do not share one cached user.
