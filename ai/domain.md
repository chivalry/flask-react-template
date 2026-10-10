# Domain

Describe the problem the application solves and the vocabulary its code uses. Replace
this placeholder when starting a project, and keep it to what an agent needs in order
to put new behavior in the right service.

## Domains

- Accounts: `User` with the `admin` and `user` roles. Registration, login, logout,
  and the current-user lookup live in `src_back/api/auth.py` and
  `src_back/services/auth.py`.

## Test Fixtures

`src_back/tests/conftest.py` provides:

- `app` - application in testing mode with an in-memory SQLite database and a
  temporary `UPLOAD_FOLDER`
- `client` - unauthenticated test client
- `db` - the SQLAlchemy extension bound to the test app
- `user` and `admin_user` - persisted accounts with the passwords `password123` and
  `adminpass123`
- `auth_client` and `admin_client` - clients signed in as those accounts
- `Widget` and `WidgetNote` - test-only models exercising the generic services and
  `BaseSchema`
- `PNG_BYTES` - a minimal PNG for upload tests
