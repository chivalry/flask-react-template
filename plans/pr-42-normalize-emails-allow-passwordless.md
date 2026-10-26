# Issue #28: Normalize Emails, Allow Passwordless Accounts, and Add PUBLIC_BASE_URL for Sign-In Providers <!-- markdownlint-disable-line MD013 -->

## Context

This is the groundwork for social login (#29, #30, #31) and passkeys (#32). Emails get
one canonical form. An account can exist without a password. One `PUBLIC_BASE_URL`
becomes the public origin that OAuth redirect URIs and the WebAuthn origin derive from.
Every sign-in goes through one `complete_login()`. None of these helpers exist yet. The
API gains one field, `has_password`.

The issue was written on 2026-10-24, before #5 and #6 merged. Since then:

- `User` lives in `src_back/models/user.py`, not `models.py`.
- `login` and `register` already set `session.permanent = True` after `login_user`
  (#5). `complete_login` takes over both lines.
- `src_back/services/errors.py` exists, with `DuplicateRecordError`.
- The issue's workstation prerequisites are already met: `.venv` runs Python 3.13.17,
  and local `main` equals `origin/main`.

Decided with the user on 2026-10-25, beyond the issue's text:

1. `has_password: boolean` is added to the frontend `AuthUser` type and its seven test
   fixtures.
2. `register_user` raises `DuplicateRecordError` instead of `ValueError`. The PR #41
   plan deferred this to #28.
3. The migration folds emails in Python, with a frozen copy of `normalize_email`, not
   with SQL `lower(trim())`. SQLite's `lower()` folds only ASCII, and PostgreSQL's
   follows the database locale.
4. `User` normalizes every email assigned to it, through `@validates('email')`. That
   moves `normalize_email()` into `src_back/models/user.py`, because `utils.py` and the
   services import the models; `services/auth.py` imports it from there.
5. Found during implementation: `migrations/alembic.ini` declares the `flask_migrate`
   logger, as Flask-Migrate's own template does. Without it, `fileConfig()` in `env.py`
   disabled the logger Flask-Migrate reports errors through, so the migration's abort,
   like every `flask db` error, exited 1 with no message.
6. From the PR review on 2026-10-25: Docker dev passes the `.env` value of
   `PUBLIC_BASE_URL` through, falling back to `http://localhost:${FRONTEND_PORT:-5174}`,
   so the backend never ignores a configured origin; and `up.sh` also moves a localhost
   value that ends in a slash.

Adopted from an independent design review:

- The dummy hash uses a random plaintext.
- Tests check that every failed login costs exactly one hash check, and that the dummy
  check's result is never trusted.
- `up.sh` rewrites only a blank or localhost `PUBLIC_BASE_URL`.
- The migration lists at most 20 accounts and prints its instruction last, so the
  deploy's 50-line log tail still shows it.
- A `passwordless_user` fixture is added; #29 had planned it too.
- `ai/auth.md` is created here, because the migration's message sends operators to it.
  #29's body calls the file new; #29 extends it instead.
- `ai/auth.md` records the invariant that #29's linking policy relies on: an account
  without a password is trusted to own its email.

What planning validated, without writing any files (plan mode allowed none):

- Every Python block passed Ruff format and Ruff check (the repo config, through stdin)
  and pydoclint (the repo's settings, in memory), and every function is under 50 lines.
- The migration's upgrade and downgrade ran against an in-memory SQLite database that
  the initial migration built:
    - a collision aborts and leaves the data untouched
    - `ÄNNE` folds to `änne`
    - both unnamed unique constraints survive batch mode
    - a long listing is capped
    - the downgrade refuses while a passwordless account exists, then runs cleanly
- The markdown passed markdownlint (repo config) and Prettier.
- The YAML and TypeScript passed Prettier, and the four scripts passed `sh -n` or
  `bash -n`.
- The `up.sh` sed expression ran under BSD sed.

Not yet run: pytest, basedpyright, `tsc -b`, Vitest, and the migration on PostgreSQL.
Verification covers all of them.

## Branch

`issue-28-normalize-emails-allow-passwordless` — already checked out; PR #42 exists.

## Change

**35 files to edit (2 of them new)**:

- Backend:
    - `src_back/models/user.py`
    - `src_back/services/errors.py`
    - `src_back/services/auth.py`
    - `src_back/api/auth.py`
    - `src_back/schemas/user.py`
    - `src_back/app.py`
- Migrations (the version file is new):
    - `migrations/versions/<date>_<rev>_normalize_emails_and_nullable_password.py`
    - `migrations/alembic.ini`
- Backend tests:
    - `src_back/tests/conftest.py`
    - `src_back/tests/test_auth.py`
    - `src_back/tests/test_schemas.py`
    - `src_back/tests/test_app.py`
- Frontend:
    - `src_front/src/types/auth.ts`
    - `src_front/src/test/store.test.ts`
    - `src_front/src/test/authApi.test.ts`
    - `src_front/src/test/AppShell.test.tsx`
    - `src_front/src/test/App.test.tsx`
    - `src_front/src/test/ProtectedRoute.test.tsx`
    - `src_front/src/test/Register.test.tsx`
    - `src_front/src/test/Login.test.tsx`
- Configuration:
    - `.env.example`
    - `docker-compose.yml`
    - `docker/docker-compose.prod.yml`
    - `scripts/provision.sh`
    - `scripts/deploy.sh`
    - `scripts/up.sh`
    - `scripts/worktree-setup.sh`
- Documentation:
    - `ai/auth.md` (new)
    - `ai/conventions.md`
    - `ai/domain.md`
    - `ai/project.md`
    - `tools.md`
    - `README.md`
    - `AGENTS.md`
    - `.claude/CLAUDE.md`

Line numbers refer to each file as it is on `main` at 3df8bc0, before any edit. Copy the
blocks exactly: the Python is already Ruff-formatted.

### `src_back/models/user.py` — `normalize_email`, the email validator, nullable hash, `has_password`

`normalize_email()` moves here, so that the model can apply it to every assigned email
without an import cycle. `Mapped[str | None]` makes the column nullable, which the
migration matches. `check_password` needs its `None` guard for basedpyright as well as
for correctness. Replace the whole file with:

```python
"""Accounts and their roles."""

import enum

from flask_login import UserMixin
from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, validates
from werkzeug.security import check_password_hash, generate_password_hash

from src_back.extensions import Base
from src_back.models.base import BaseMixin


class Role(enum.StrEnum):
    """Application roles.

    Only :attr:`admin` is privileged; see :func:`src_back.utils.admin_required`.
    New accounts receive :attr:`user` and are promoted out of band.
    """

    admin = 'admin'
    user = 'user'


def normalize_email(email: str) -> str:
    """Return the form every email is stored and compared in.

    Surrounding whitespace is dropped and every letter lowercased, so letter case
    never lets one address register twice or miss its account at sign-in.
    :class:`User` applies it to every email assigned to an account, and
    :func:`src_back.services.auth.find_user_by_email` to every address it looks up.

    Args:
        email: An address as a client submitted it or a provider asserted it.

    Returns:
        The trimmed, lowercased address.
    """
    return email.strip().lower()


class User(UserMixin, BaseMixin, Base):
    """An account that can sign in.

    The role is stored as a plain string column (``native_enum=False``) so the
    same migration works on PostgreSQL and SQLite. Every email assigned to an
    account is stored through :func:`normalize_email`, however the account is
    created or edited. ``password_hash`` is ``None`` for an account a sign-in
    provider created, which has no password.
    """

    __tablename__ = 'users'

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name='role', native_enum=False), default=Role.user
    )

    @validates('email')
    def _store_email_normalized(self, _key: str, email: str) -> str:
        """Normalize an email as it is assigned, so no code path stores another form.

        Args:
            _key: The attribute being set, always ``email``. Unused.
            email: The address being assigned.

        Returns:
            The address as :func:`normalize_email` returns it.
        """
        return normalize_email(email)

    @property
    def has_password(self) -> bool:
        """Whether the account can sign in with a password.

        Returns:
            ``False`` for an account a sign-in provider created without one.
        """
        return self.password_hash is not None

    def set_password(self, password: str) -> None:
        """Hash a plaintext password and store it on the account.

        Args:
            password: The plaintext password to hash. Never persisted as-is.
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check a plaintext password against the stored hash.

        Args:
            password: The plaintext password submitted at sign-in.

        Returns:
            ``True`` when the password matches the stored hash; always ``False``
            for an account without a password.
        """
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        """Describe the account by email for logs and debugging.

        Returns:
            The repr string, for example ``<User a@b.test>``.
        """
        return f'<User {self.email}>'
```

`src_back/models/__init__.py` stays as it is: callers import `normalize_email` from
`src_back.models.user`.

### `src_back/services/errors.py` — `LastSignInMethodError`

Nothing raises it yet. #29's unlink and #32's passkey delete will, after checking
`count_sign_in_methods`. Replace the whole file with:

```python
"""Exceptions services raise when a request breaks a business rule.

Route handlers catch them and answer with the matching envelope from
:mod:`src_back.utils`, such as :func:`~src_back.utils.conflict` for a 409.
"""


class DuplicateRecordError(Exception):
    """A unique natural key, such as a name or an email, is already taken (409)."""


class LastSignInMethodError(Exception):
    """Removing a sign-in method would leave the account no way to sign in (409)."""
```

### `src_back/services/auth.py` — lookup, uniform-cost authentication, `complete_login`

The dummy hash is built at import, about 80 ms per process, with the same call
`set_password` uses, so checking it costs what checking a real hash costs. Its
plaintext is random and never kept, and its result is discarded. `check_password_hash`
is imported by name so the tests can replace it. Replace the whole file with:

```python
"""Account creation, credential checking, and the one place a sign-in starts."""

import secrets

from flask import session
from flask_login import login_user
from werkzeug.security import check_password_hash, generate_password_hash

from src_back.extensions import db
from src_back.models import Role, User
from src_back.models.user import normalize_email
from src_back.services.errors import DuplicateRecordError

# Checked in place of a stored hash when there is none, so an unknown email and an
# account without a password cost the same hash computation as a wrong password. It
# is hashed the way User.set_password hashes, from a random plaintext nobody keeps, so
# checking it can never let anyone in.
_DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))


def find_user_by_email(email: str) -> User | None:
    """Look up an account by email, ignoring case and surrounding whitespace.

    Args:
        email: The address to look up, in any case.

    Returns:
        The account registered under that address, or ``None`` if there is none.
    """
    return db.session.query(User).filter_by(email=normalize_email(email)).first()


def register_user(email: str, password: str) -> User:
    """Create a new account and commit it.

    The duplicate check ignores letter case, and the model stores the email
    normalized. New accounts always receive the unprivileged ``user`` role; admins
    are promoted out of band rather than at registration.

    Args:
        email: The address to register, in any case. Must not already be in use.
        password: The plaintext password, hashed before it is stored.

    Returns:
        The newly committed user.

    Raises:
        DuplicateRecordError: If an account with that email already exists.
    """
    if find_user_by_email(email) is not None:
        raise DuplicateRecordError('Email already registered.')
    user = User(email=email, role=Role.user)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def authenticate_user(email: str, password: str) -> User | None:
    """Look up an account and verify its password.

    Returns ``None`` for an unknown address, an account without a password, and a
    wrong password alike, so callers cannot tell which emails are registered. The
    first two check the password against a dummy hash, so all three cost one hash
    computation and take the same time.

    Args:
        email: The address submitted at sign-in, in any case.
        password: The plaintext password submitted at sign-in.

    Returns:
        The matching user, or ``None`` if the credentials are not valid.
    """
    user = find_user_by_email(email)
    if user is None or not user.has_password:
        check_password_hash(_DUMMY_PASSWORD_HASH, password)
        return None
    return user if user.check_password(password) else None


def complete_login(user: User) -> None:
    """Start the session of a user whose identity has been verified.

    Every sign-in ends here, whatever proved the identity: registration and password
    login now, a provider callback or a passkey later. The session is permanent, so
    its cookie carries an expiry ``SESSION_LIFETIME_DAYS`` out and every later
    response pushes it forward.

    Args:
        user: The account to sign in.
    """
    login_user(user)
    session.permanent = True


def count_sign_in_methods(user: User) -> int:
    """Count the ways an account can sign in.

    Code that removes a sign-in method checks this first and raises
    :class:`~src_back.services.errors.LastSignInMethodError` instead of removing the
    last one. Only a password counts so far; linked providers and passkeys join the
    count when their tables arrive.

    Args:
        user: The account to inspect.

    Returns:
        The number of sign-in methods the account has.
    """
    return 1 if user.has_password else 0
```

### `src_back/api/auth.py` — both handlers sign in through `complete_login`

This drops `login_user`, but `session` stays imported because `logout` still clears it.
The `ValueError` catch becomes `DuplicateRecordError`, and the 409 body is unchanged.
Replace the whole file with:

```python
"""Session authentication routes: register, login, logout, and identity."""

from flask import Blueprint, Response, jsonify, session
from flask_login import login_required, logout_user

from src_back.auth import current_user
from src_back.schemas.user import login_schema, user_schema
from src_back.services.auth import authenticate_user, complete_login, register_user
from src_back.services.errors import DuplicateRecordError
from src_back.utils import ErrorResponse, conflict, parse_request_json, unauthorized

bp = Blueprint('auth', __name__)


@bp.post('/register')
def register() -> tuple[Response, int]:
    """Create an account and sign the new user in immediately.

    A payload that fails validation never reaches this body: ``parse_request_json``
    raises and the application answers with a 422 envelope.

    The new user is signed in through :func:`~src_back.services.auth.complete_login`,
    as in :func:`login`, so the session survives a browser restart.

    Returns:
        The serialized user with status 201, or a 409 envelope when the email is
        already registered in any letter case.
    """
    data = parse_request_json(user_schema)
    try:
        user = register_user(data['email'], data['password'])
    except DuplicateRecordError as exc:
        return conflict(str(exc))
    complete_login(user)
    return jsonify(user_schema.dump(user)), 201


@bp.post('/login')
def login() -> Response | ErrorResponse:
    """Verify credentials and start a session that survives a browser restart.

    :func:`~src_back.services.auth.complete_login` makes the session permanent, so
    its cookie carries an expiry ``SESSION_LIFETIME_DAYS`` out, and every later
    response pushes it forward.

    Returns:
        The serialized user on success, or a 401 envelope when the credentials
        do not match. The message does not distinguish an unknown email, an
        account without a password, and a wrong password.
    """
    data = parse_request_json(login_schema)
    user = authenticate_user(data['email'], data['password'])
    if not user:
        return unauthorized('Invalid email or password.')
    complete_login(user)
    return jsonify(user_schema.dump(user))


@bp.post('/logout')
@login_required
def logout() -> Response:
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


@bp.get('/me')
@login_required
def me() -> Response:
    """Return the signed-in user, for rehydrating the client on page load.

    Returns:
        The serialized current user.
    """
    return jsonify(user_schema.dump(current_user))
```

### `src_back/schemas/user.py` — dump-only `has_password`

`has_password` reads the model property. Because it is dump-only, a body that sends it
is rejected as an unknown field (checked with marshmallow 3.23). Replace the whole file
with:

```python
"""Marshmallow schemas for accounts: registration, sign-in, and serialization."""

from marshmallow import Schema, fields, validate

from src_back.models import Role, User
from src_back.schemas.base import BaseSchema


class UserSchema(BaseSchema):
    """Serialize accounts and validate registration payloads.

    ``password`` is load-only so it is never echoed back, and ``role`` is
    dump-only so a client cannot grant itself privileges at registration.
    ``has_password`` is dump-only too: it tells the client whether the account has a
    password without exposing the hash.
    """

    class Meta(BaseSchema.Meta):
        """Bind to the ``users`` table and hide the stored hash."""

        model = User
        exclude = ('password_hash',)
        dump_only = BaseSchema.AUDIT

    email = fields.Email(required=True)
    password = fields.Str(
        load_only=True,
        required=True,
        validate=validate.Length(min=8, error='Password must be at least 8 characters.'),
    )
    role = fields.Enum(Role, by_value=True, dump_only=True)
    has_password = fields.Boolean(dump_only=True)


class LoginSchema(Schema):
    """Validate a sign-in payload.

    Deliberately omits the length rule from :class:`UserSchema` so that
    credentials predating a policy change can still be submitted.
    """

    email = fields.Email(required=True)
    password = fields.Str(required=True, load_only=True)


user_schema = UserSchema()
login_schema = LoginSchema()
```

### `src_back/app.py` — `PUBLIC_BASE_URL` and `WEBAUTHN_RP_NAME`

The environment is read in `_configure_application`, and the value is settled after
`config_overrides`. That way the testing flag from the overrides counts, and an
injected `PUBLIC_BASE_URL` wins: #29's conftest sets `'https://app.test'`. `or` chains
treat the blank values that `.env` and Compose pass (`${VAR:-}`) as unset. A new
`_is_development_or_testing` replaces the inline check in `_guard_secret_key`, so the
two cannot drift apart. Five edits:

1. Line 87, in `create_app`: replace

    ```python
        _guard_secret_key(app)
        _initialize_extensions(app)
    ```

    with

    ```python
        _guard_secret_key(app)
        _resolve_public_base_url(app)
        _initialize_extensions(app)
    ```

2. Lines 102-103, the end of the `_configure_application` docstring's paragraph: replace

    ```python
        request: login makes the session permanent, and Flask re-sends a permanent
        session's cookie with a fresh expiry on every response.
    ```

    with

    ```python
        request: login makes the session permanent, and Flask re-sends a permanent
        session's cookie with a fresh expiry on every response. ``PUBLIC_BASE_URL`` is
        only read here; :func:`_resolve_public_base_url` settles it once the overrides
        are applied. The site name that passkey prompts show falls back from
        ``WEBAUTHN_RP_NAME`` to ``APP_NAME`` to the template's own name.
    ```

3. After line 124 (`app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024`),
   at the end of `_configure_application`, add:

    ```python
        app.config['PUBLIC_BASE_URL'] = os.environ.get('PUBLIC_BASE_URL')
        app.config['WEBAUTHN_RP_NAME'] = (
            os.environ.get('WEBAUTHN_RP_NAME')
            or os.environ.get('APP_NAME')
            or 'Flask React Template'
        )
    ```

4. Lines 137-138, in `_guard_secret_key`: replace

    ```python
        if os.environ.get('FLASK_ENV') == 'development' or app.config.get('TESTING'):
            return
    ```

    with

    ```python
        if _is_development_or_testing(app):
            return
    ```

5. Between `_guard_secret_key` (ends line 142) and `def _initialize_extensions`
   (line 145), insert, with two blank lines on each side:

    ```python
    def _resolve_public_base_url(app: Flask) -> None:
        """Settle ``PUBLIC_BASE_URL``, the one origin external URLs are built from.

        OAuth redirect URIs and the WebAuthn origin derive from it, never from the
        request: there is no ``ProxyFix``, so behind nginx the request does not carry the
        public origin. A trailing slash is stripped. Development and testing fall back to
        the Vite dev server on ``FRONTEND_PORT``; anywhere else an unset value becomes
        ``None``, with a warning that OAuth sign-in and passkeys are disabled. This runs
        after the overrides so that the testing flag and an injected URL both count.

        Args:
            app: The application being configured.
        """
        public_base_url = (app.config.get('PUBLIC_BASE_URL') or '').rstrip('/')
        if not public_base_url and _is_development_or_testing(app):
            frontend_port = os.environ.get('FRONTEND_PORT') or '5174'
            public_base_url = f'http://localhost:{frontend_port}'
        if not public_base_url:
            _log.warning(
                'PUBLIC_BASE_URL is not set: OAuth sign-in and passkeys are disabled.'
            )
        app.config['PUBLIC_BASE_URL'] = public_base_url or None


    def _is_development_or_testing(app: Flask) -> bool:
        """Report whether development defaults and placeholder secrets are allowed.

        Args:
            app: The application being configured, with its overrides applied.

        Returns:
            ``True`` when ``FLASK_ENV`` is ``development`` or the app is in testing mode.
        """
        return os.environ.get('FLASK_ENV') == 'development' or bool(app.config.get('TESTING'))
    ```

The last line is exactly 90 characters; Ruff format leaves it as it is.

### `migrations/versions/<date>_<rev>_normalize_emails_and_nullable_password.py` — new

Make this edit after the `models/user.py` edit; autogenerate needs to see the nullable
column. Author it against a scratch SQLite database at head, so Docker is not needed:

```bash
db="$(mktemp -d)/author.db"
DATABASE_URL="sqlite:///$db" FLASK_ENV=development \
  .venv/bin/flask --app src_back.app db upgrade
DATABASE_URL="sqlite:///$db" FLASK_ENV=development \
  .venv/bin/flask --app src_back.app db migrate -m "normalize_emails_and_nullable_password"
```

The only detected change should be `password_hash` becoming nullable. Anything else
means the models and the schema have drifted, so stop and investigate. Then hand-edit
the generated file:

- Keep its header: the docstring's first lines, `revision`, `down_revision = '683d57722be2'`,
  `branch_labels`, `depends_on`. Before the docstring's closing `"""`, add:

    ```text
    Stores every email in the form src_back.models.user.normalize_email produces, and
    lets users.password_hash be NULL for accounts that sign-in providers create.

    Emails are folded in Python by a frozen copy of normalize_email, not by SQL lower()
    and trim(): SQLite's lower() folds only ASCII, PostgreSQL's follows the database
    locale, and trim() strips only spaces, so either could store a form that sign-in
    never computes. The upgrade stops before changing anything when two accounts would
    share an email once folded: merge them by hand (ai/auth.md), then run it again. The
    downgrade restores NOT NULL and stops while any account has no password; emails
    stay folded.
    ```

- Add `from collections import defaultdict` and a blank line above `from alembic import op`.
- Replace everything after `depends_on = None` (the generated `upgrade` and `downgrade`)
  with:

    ```python
    # Enough accounts to act on, and few enough that the deploy's 50-line log tail still
    # shows the instruction printed after them.
    LISTED_ACCOUNTS_LIMIT = 20


    def upgrade():
        connection = op.get_bind()
        accounts = connection.execute(
            sa.text('SELECT id, email FROM users ORDER BY id')
        ).all()
        _abort_listing_accounts(
            _accounts_whose_emails_collide_once_normalized(accounts),
            'Cannot normalize emails: these accounts collide once trimmed and lowercased.',
            'Merge them by hand (see ai/auth.md), then run the upgrade again.',
        )
        for account in accounts:
            normalized = _normalize_email(account.email)
            if normalized != account.email:
                connection.execute(
                    sa.text('UPDATE users SET email = :email WHERE id = :id'),
                    {'email': normalized, 'id': account.id},
                )
        with op.batch_alter_table('users') as batch_op:
            batch_op.alter_column(
                'password_hash', existing_type=sa.String(length=255), nullable=True
            )


    def downgrade():
        passwordless = op.get_bind().execute(
            sa.text('SELECT id, email FROM users WHERE password_hash IS NULL ORDER BY id')
        ).all()
        _abort_listing_accounts(
            passwordless,
            'Cannot make users.password_hash NOT NULL: these accounts have no password.',
            'Give each one a password or delete it, then run the downgrade again.',
        )
        with op.batch_alter_table('users') as batch_op:
            batch_op.alter_column(
                'password_hash', existing_type=sa.String(length=255), nullable=False
            )


    def _normalize_email(email):
        # A frozen copy of src_back.models.user.normalize_email: a migration must keep
        # doing what it did when it was written, whatever the application code becomes.
        return email.strip().lower()


    def _accounts_whose_emails_collide_once_normalized(accounts):
        by_normalized_email = defaultdict(list)
        for account in accounts:
            by_normalized_email[_normalize_email(account.email)].append(account)
        return [
            account
            for group in by_normalized_email.values()
            if len(group) > 1
            for account in group
        ]


    def _abort_listing_accounts(accounts, headline, instruction):
        if not accounts:
            return
        listed = [
            f'  id {account.id}: {account.email!r}'
            for account in accounts[:LISTED_ACCOUNTS_LIMIT]
        ]
        if len(accounts) > LISTED_ACCOUNTS_LIMIT:
            listed.append(f'  ... and {len(accounts) - LISTED_ACCOUNTS_LIMIT} more')
        raise RuntimeError('\n'.join([headline, *listed, instruction]))
    ```

Both checks run before any write, so an abort leaves the database unchanged on SQLite
too. On PostgreSQL the whole run is one transaction (`migrations/env.py:29`). No UPDATE
can collide partway through, because collisions are rejected first and every
already-folded email maps to itself. `repr()` makes stray spaces and tabs visible in
the listing.

### `migrations/alembic.ini` — declare the `flask_migrate` logger

Flask-Migrate turns a migration's `RuntimeError` into `Error: <message>` on its
`flask_migrate` logger and exits 1. `fileConfig()` in `env.py` disables every logger the
file does not declare, so without this section the message never printed, for this
migration or for any other `flask db` error. Add `flask_migrate` to `[loggers] keys`
(`keys = root,sqlalchemy,alembic,flask_migrate`), and after the `[logger_alembic]`
section insert:

```ini
# Flask-Migrate reports every `flask db` error, a migration's RuntimeError included,
# through this logger. Undeclared, fileConfig() in env.py disables it, and the commands
# exit 1 without a message.
[logger_flask_migrate]
level = INFO
handlers =
qualname = flask_migrate
```

### `src_back/tests/conftest.py` — `passwordless_user` fixture

After the `admin_user` fixture (ends line 88), and before `@pytest.fixture()` of
`auth_client` (line 91), insert, with two blank lines on each side:

```python
@pytest.fixture()
def passwordless_user(app: Flask) -> User:
    return persist(User(email='nopass@test.com', role=Role.user))
```

### `src_back/tests/test_auth.py` — normalization, uniform failures, `complete_login`, lookups

1. Lines 3-9: replace

    ```python
    import flask_login
    from flask import g
    from flask.testing import FlaskClient

    from src_back import auth
    from src_back.app import SESSION_LIFETIME_DAYS
    from src_back.models import User
    ```

    with

    ```python
    import flask_login
    import pytest
    from flask import Flask, g, session
    from flask.testing import FlaskClient
    from werkzeug.security import check_password_hash

    from src_back import auth
    from src_back.api import auth as auth_api
    from src_back.app import SESSION_LIFETIME_DAYS
    from src_back.models import User
    from src_back.models import user as user_model
    from src_back.services import auth as auth_service
    from src_back.services.auth import (
        complete_login,
        count_sign_in_methods,
        find_user_by_email,
    )
    ```

2. After `test_register_duplicate_email` (ends line 56), insert:

    ```python
    def test_register_stores_the_email_normalized(client: FlaskClient) -> None:
        r = client.post(
            '/api/v1/auth/register',
            json={'email': 'Mixed@Example.COM', 'password': 'secure123'},
        )
        assert r.status_code == 201
        assert r.get_json()['email'] == 'mixed@example.com'


    def test_register_rejects_an_email_taken_in_another_case(
        client: FlaskClient, user: User
    ) -> None:
        r = client.post(
            '/api/v1/auth/register',
            json={'email': user.email.upper(), 'password': 'secure123'},
        )
        assert r.status_code == 409
        assert r.get_json() == {'error': 'Email already registered.'}
    ```

3. After `test_login_unknown_email` (ends line 132), insert the block below. The
   three-way parametrized test wraps both `check_password_hash` names, the service's
   for the dummy and the model's for a real hash. It shows that every kind of failed
   login costs exactly one hash computation, without timing anything. The next test
   makes the dummy check answer `True` and still expects a 401.

    ```python
    def test_login_matches_an_email_registered_in_mixed_case(client: FlaskClient) -> None:
        client.post(
            '/api/v1/auth/register',
            json={'email': 'Mixed@Example.COM', 'password': 'secure123'},
        )
        r = client.post(
            '/api/v1/auth/login',
            json={'email': 'mixed@example.com', 'password': 'secure123'},
        )
        assert r.status_code == 200
        assert r.get_json()['email'] == 'mixed@example.com'


    def test_login_ignores_the_case_of_the_email(client: FlaskClient, user: User) -> None:
        r = client.post(
            '/api/v1/auth/login',
            json={'email': user.email.upper(), 'password': 'password123'},
        )
        assert r.status_code == 200


    @pytest.mark.usefixtures('user', 'passwordless_user')
    @pytest.mark.parametrize(
        ('email', 'password'),
        [
            ('nobody@test.com', 'password123'),
            ('nopass@test.com', 'password123'),
            ('user@test.com', 'wrongpassword'),
        ],
        ids=['unknown-email', 'no-password', 'wrong-password'],
    )
    def test_every_failed_login_checks_one_hash_and_answers_alike(
        client: FlaskClient, monkeypatch: pytest.MonkeyPatch, email: str, password: str
    ) -> None:
        checked: list[str] = []

        def record_check(stored_hash: str, candidate: str) -> bool:
            checked.append(stored_hash)
            return check_password_hash(stored_hash, candidate)

        monkeypatch.setattr(auth_service, 'check_password_hash', record_check)
        monkeypatch.setattr(user_model, 'check_password_hash', record_check)
        r = client.post(
            '/api/v1/auth/login',
            json={'email': email, 'password': password},
        )
        assert r.status_code == 401
        assert r.get_json() == {'error': 'Invalid email or password.'}
        # One hash computation in every case, so the response time reveals nothing.
        assert len(checked) == 1


    def test_login_never_trusts_the_dummy_hash_check(
        client: FlaskClient, passwordless_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            auth_service, 'check_password_hash', lambda stored_hash, candidate: True
        )
        r = client.post(
            '/api/v1/auth/login',
            json={'email': passwordless_user.email, 'password': 'password123'},
        )
        assert r.status_code == 401


    def test_register_and_login_sign_in_through_complete_login(
        client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        signed_in: list[str] = []

        def record_sign_in(user: User) -> None:
            signed_in.append(user.email)

        monkeypatch.setattr(auth_api, 'complete_login', record_sign_in)
        body = {'email': 'new@example.com', 'password': 'secure123'}
        assert client.post('/api/v1/auth/register', json=body).status_code == 201
        assert client.post('/api/v1/auth/login', json=body).status_code == 200
        assert signed_in == ['new@example.com', 'new@example.com']


    def test_complete_login_starts_a_permanent_session(app: Flask, user: User) -> None:
        with app.test_request_context():
            complete_login(user)
            assert session.permanent is True
            assert flask_login.current_user == user
    ```

4. In `test_me_authenticated`, after line 158
   (`assert r.get_json()['email'] == user.email`), add:

    ```python
        assert r.get_json()['has_password'] is True
    ```

5. At the end of the file (after line 178), append:

    ```python
    def test_find_user_by_email_ignores_case_and_surrounding_whitespace(user: User) -> None:
        assert find_user_by_email(' USER@Test.com ') is user


    def test_find_user_by_email_returns_none_for_an_unknown_address(app: Flask) -> None:
        assert find_user_by_email('nobody@test.com') is None


    def test_count_sign_in_methods_counts_a_password(user: User) -> None:
        assert count_sign_in_methods(user) == 1


    def test_count_sign_in_methods_is_zero_without_a_password(
        passwordless_user: User,
    ) -> None:
        assert count_sign_in_methods(passwordless_user) == 0
    ```

### `src_back/tests/test_schemas.py` — `has_password` dumps and the model rules

The exact-key assertion at line 25 breaks without this edit.

1. After line 7 (`from src_back.models import User`), add:

    ```python
    from src_back.models.user import normalize_email
    ```

2. Lines 25-27: replace

    ```python
        assert set(data) == {'id', 'uuid', 'email', 'role', 'created_at', 'updated_at'}
        assert data['role'] == 'user'
        assert data['email'] == user.email
    ```

    with the following, which also adds the passwordless dump test right after it:

    ```python
        assert set(data) == {
            'id',
            'uuid',
            'email',
            'role',
            'has_password',
            'created_at',
            'updated_at',
        }
        assert data['role'] == 'user'
        assert data['email'] == user.email
        assert data['has_password'] is True


    def test_user_schema_dump_reports_a_passwordless_account(passwordless_user: User) -> None:
        data = cast(dict[str, Any], user_schema.dump(passwordless_user))
        assert data['has_password'] is False
    ```

3. After `test_user_repr_names_the_email` (ends line 70), insert:

    ```python
    def test_normalize_email_trims_and_lowercases() -> None:
        assert normalize_email('  Mixed@Example.COM\n') == 'mixed@example.com'


    def test_user_stores_every_assigned_email_normalized(app: Flask) -> None:
        account = User(email='  Mixed@Example.COM ')
        assert account.email == 'mixed@example.com'
        account.email = 'Other@Example.COM'
        assert account.email == 'other@example.com'


    def test_user_without_a_password_never_matches_one(passwordless_user: User) -> None:
        assert passwordless_user.has_password is False
        assert passwordless_user.check_password('password123') is False
    ```

### `src_back/tests/test_app.py` — `PUBLIC_BASE_URL` and `WEBAUTHN_RP_NAME`

`load_dotenv()` copies a developer's `.env` (`FLASK_ENV`, `APP_NAME`, `FRONTEND_PORT`,
and `PUBLIC_BASE_URL` once `up.sh` writes it) into pytest's environment. So each test
sets or clears every variable it depends on, and calls `create_app` directly rather
than through the `app` fixture.

1. Line 1: insert `import logging` above `from pathlib import Path`.
2. At the end of the file (after line 239), append:

    ```python
    def test_public_base_url_defaults_to_the_dev_server_in_testing(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv('PUBLIC_BASE_URL', raising=False)
        monkeypatch.delenv('FRONTEND_PORT', raising=False)
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        assert app.config['PUBLIC_BASE_URL'] == 'http://localhost:5174'


    def test_public_base_url_follows_frontend_port_in_development(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv('FLASK_ENV', 'development')
        monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
        monkeypatch.setenv('FRONTEND_PORT', '5180')
        monkeypatch.delenv('PUBLIC_BASE_URL', raising=False)
        assert create_app().config['PUBLIC_BASE_URL'] == 'http://localhost:5180'


    def test_public_base_url_is_none_with_a_warning_outside_development(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv('FLASK_ENV', 'production')
        monkeypatch.setenv('SECRET_KEY', 'a-long-random-secret')
        monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
        monkeypatch.delenv('PUBLIC_BASE_URL', raising=False)
        with caplog.at_level(logging.WARNING, logger='src_back.app'):
            app = create_app()
        assert app.config['PUBLIC_BASE_URL'] is None
        assert 'PUBLIC_BASE_URL is not set' in caplog.text


    def test_public_base_url_from_the_environment_drops_a_trailing_slash(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv('FLASK_ENV', 'production')
        monkeypatch.setenv('SECRET_KEY', 'a-long-random-secret')
        monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
        monkeypatch.setenv('PUBLIC_BASE_URL', 'https://app.example.com/')
        assert create_app().config['PUBLIC_BASE_URL'] == 'https://app.example.com'


    def test_public_base_url_override_wins_over_the_environment(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv('PUBLIC_BASE_URL', 'http://localhost:5174')
        app = create_app(
            {
                'TESTING': True,
                'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                'PUBLIC_BASE_URL': 'https://app.test/',
            }
        )
        assert app.config['PUBLIC_BASE_URL'] == 'https://app.test'


    @pytest.mark.parametrize(
        ('rp_name', 'app_name', 'expected'),
        [
            ('Acme Passkeys', 'acme', 'Acme Passkeys'),
            ('', 'acme', 'acme'),
            ('', '', 'Flask React Template'),
        ],
    )
    def test_webauthn_rp_name_falls_back_to_app_name_then_the_template_name(
        monkeypatch: pytest.MonkeyPatch, rp_name: str, app_name: str, expected: str
    ) -> None:
        monkeypatch.setenv('WEBAUTHN_RP_NAME', rp_name)
        monkeypatch.setenv('APP_NAME', app_name)
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        assert app.config['WEBAUTHN_RP_NAME'] == expected
    ```

### `src_front/src/types/auth.ts` and the seven `AuthUser` fixtures

1. `src_front/src/types/auth.ts`, after line 11 (`role: Role`), add:

    ```ts
        /** False for an account a sign-in provider created without a password. */
        has_password: boolean
    ```

2. In each fixture below, add `has_password: true,` on the line after its `role:`
   line, at the same indentation. There is no shared factory, and `tsc -b`
   type-checks the tests through `tsconfig.test.json`. `store.test.ts:151` spreads
   `testUser` and needs nothing.
    - `src_front/src/test/store.test.ts:16`
    - `src_front/src/test/authApi.test.ts:25`
    - `src_front/src/test/AppShell.test.tsx:18`
    - `src_front/src/test/App.test.tsx:18`
    - `src_front/src/test/ProtectedRoute.test.tsx:14`
    - `src_front/src/test/Register.test.tsx:18`
    - `src_front/src/test/Login.test.tsx:18`

### `.env.example` — the public origin and the passkey name

Between line 33 (blank, after `VITE_API_URL=`) and line 34 (`# --- Production only`),
insert this section, followed by one blank line. The header is padded to 82 characters
like the others:

```text
# --- Public origin and passkey name ---------------------------------------------
# The origin browsers use: scheme, host, and port, with no path. OAuth redirect URIs
# and the WebAuthn origin are built from it, never from the request. scripts/up.sh
# moves a blank or localhost value to FRONTEND_PORT, scripts/worktree-setup.sh sets
# it per worktree, and scripts/provision.sh writes https://$DOMAIN on the server.
# Blank outside development, it disables OAuth sign-in and passkeys.
PUBLIC_BASE_URL=http://localhost:5174
# Site name in passkey prompts. Blank falls back to APP_NAME.
WEBAUTHN_RP_NAME=
```

### `docker-compose.yml` and `docker/docker-compose.prod.yml` — pass both keys to the backend

`.env` is in `.dockerignore`, and no service uses `env_file:`, so both files must name
the keys. The prod file overrides keys one at a time. Without its own `PUBLIC_BASE_URL`,
production would inherit the development localhost value.

- `docker-compose.yml`, after line 33 (`CORS_ALLOWED_ORIGINS: ...`):

    ```yaml
          PUBLIC_BASE_URL: '${PUBLIC_BASE_URL:-http://localhost:${FRONTEND_PORT:-5174}}'
          WEBAUTHN_RP_NAME: ${WEBAUTHN_RP_NAME:-}
    ```

- `docker/docker-compose.prod.yml`, after line 20 (`CORS_ALLOWED_ORIGINS: ${CORS_ALLOWED_ORIGINS}`):

    ```yaml
          PUBLIC_BASE_URL: ${PUBLIC_BASE_URL}
          WEBAUTHN_RP_NAME: ${WEBAUTHN_RP_NAME:-}
    ```

### `scripts/provision.sh`, `scripts/deploy.sh`, `scripts/worktree-setup.sh`

- `scripts/provision.sh`, inside the unquoted `.env` heredoc, after line 93
  (`CORS_ALLOWED_ORIGINS=https://$DOMAIN`):

    ```text
    # OAuth redirect URIs and the WebAuthn origin are built from PUBLIC_BASE_URL.
    PUBLIC_BASE_URL=https://$DOMAIN
    WEBAUTHN_RP_NAME=$APP_NAME
    ```

- `scripts/deploy.sh`, after the `DOMAIN` check (ends line 36). The second line tells
  an older server what to add:

    ```bash
    if [ -z "$(get PUBLIC_BASE_URL)" ]; then
      echo "ERROR: PUBLIC_BASE_URL is empty in $REPO_DIR/.env. Refusing to deploy."
      echo "       Add PUBLIC_BASE_URL=https://$DOMAIN; ai/auth.md explains it."
      exit 1
    fi
    ```

- `scripts/worktree-setup.sh`, after line 95 (`set_env VITE_API_URL ...`):

    ```sh
    set_env PUBLIC_BASE_URL "http://localhost:$frontend_port"
    ```

### `scripts/up.sh` — move a blank or localhost `PUBLIC_BASE_URL` with the ports

The rewrite follows `DATABASE_URL`'s pattern: only a blank or localhost value moves, so
a custom origin such as a tunnel survives. The first new sed fills a blank value, and
the second moves a localhost one to the new port. Three edits:

First, on line 45, append `PUBLIC_BASE_URL` to the `for key in` list, so an older
`.env` gets a line for the sed to edit. Second, after line 53 (the `VITE_API_URL` sed),
insert these two lines. The second keeps an optional trailing slash, which the app
accepts:

```sh
    | sed "s|^PUBLIC_BASE_URL=\$|PUBLIC_BASE_URL=http://localhost:${frontend_port}|" \
    | sed -E "s|^(PUBLIC_BASE_URL=http://localhost:)[0-9]+(/?)\$|\1${frontend_port}\2|" \
```

Third, on lines 58-61, replace the four echo lines with these five, realigned:

```sh
  echo "  DB_PORT         = ${db_port}"
  echo "  BACKEND_PORT    = ${backend_port}"
  echo "  FRONTEND_PORT   = ${frontend_port}"
  echo "  VITE_API_URL    = http://localhost:${backend_port}"
  echo "  PUBLIC_BASE_URL = $(read_env PUBLIC_BASE_URL .env)"
```

### `ai/auth.md` — new runbook

Create it with exactly this content:

````markdown
# Authentication

## Overview

Accounts sign in with an email and a password through `src_back/api/auth.py` and
`src_back/services/auth.py`. Sign-in providers (#29, #30, #31) and passkeys (#32) build
on this groundwork:

- `User` stores every email through `normalize_email()` in `src_back/models/user.py`
  (trimmed and lowercased), however the account is created or edited, and
  `find_user_by_email()` normalizes the address it looks up.
- `users.password_hash` is nullable: an account a sign-in provider creates has no
  password. `User.has_password`, and `has_password` in the user payload, say which.
  `authenticate_user` answers such an account, and an unknown email, exactly as it
  answers a wrong password, down to the one password-hash check each costs.
- `complete_login(user)` is the one place a sign-in starts, and it makes the session
  permanent.
- `count_sign_in_methods(user)` counts the ways an account can sign in. Code that
  removes one raises `LastSignInMethodError` (409) instead of removing the last.

An account without a password is trusted to own its email address, because only a
sign-in provider that verified the address creates one. Any new way to create such an
account, such as an invitation or a passkey-first sign-up, must verify the address
first; otherwise linking a provider by email would hand the account to whoever
created it.

## Configuration

- `PUBLIC_BASE_URL` is the origin browsers use: scheme, host, and port, with no path.
  A trailing slash is stripped. OAuth redirect URIs and the WebAuthn origin are built
  from it, never from the request.
    - Development and testing default it to `http://localhost:$FRONTEND_PORT`.
      `docker-compose.yml` passes the `.env` value to the backend with the same
      fallback. `scripts/up.sh` moves a blank or localhost value along with the ports,
      and `scripts/worktree-setup.sh` sets one per worktree.
    - In production `scripts/provision.sh` writes `https://$DOMAIN`, and
      `scripts/deploy.sh` refuses to deploy while it is empty. Unset anywhere else, it
      is `None`, and the app logs that OAuth sign-in and passkeys are disabled.
- `WEBAUTHN_RP_NAME` is the site name passkey prompts show. It falls back to
  `APP_NAME`, which is a slug, and then to `Flask React Template`, so set it to the
  product's display name.

A server provisioned before these settings existed lacks both lines, and its next
deploy stops with `PUBLIC_BASE_URL is empty`. Add them to `~/$APP_NAME/.env`, then
deploy again:

```text
PUBLIC_BASE_URL=https://<DOMAIN>
WEBAUTHN_RP_NAME=<display name>
```

## Email normalization migration

The `normalize_emails_and_nullable_password` migration folds every stored email with a
frozen copy of `normalize_email()`. Before it changes anything, it looks for accounts
whose emails would collide once folded. If any do, it stops, lists their ids and
emails, and leaves the database unchanged. `docker/entrypoint.sh` then exits, the
backend container restarts in a loop, and the deploy fails waiting for `/api/health`.
In development the same check runs when the backend container starts.

### Before deploying

Look for collisions while the old version is still serving. Open a database shell on
the server (`POSTGRES_USER` and `POSTGRES_DB` are in `.env`; in development the
command is `docker compose exec db psql -U app -d app`):

```bash
docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
  --env-file .env exec db psql -U <POSTGRES_USER> -d <POSTGRES_DB>
```

```sql
SELECT id, email, created_at FROM users
WHERE lower(trim(email)) IN (
    SELECT lower(trim(email)) FROM users
    GROUP BY lower(trim(email)) HAVING count(*) > 1
)
ORDER BY lower(trim(email)), id;
```

SQL `lower()` folds ASCII letters the way the migration does, which covers nearly every
address; the migration's own check is the authoritative one.

### Merging colliding accounts

For each group, keep one account and remove the others, in the same database shell:

1. Point the rows that reference an account you will remove at the one you keep.
   Foreign keys to `users.id` declare `ondelete`, so deleting an account cascades to,
   or nulls, whatever still references it.
2. Delete the extra accounts (`DELETE FROM users WHERE id IN (...);`), or give each one
   a different address.
3. If the migration already failed, restart the backend so its entrypoint runs the
   migration again, and rerun the deploy if it timed out:

    ```bash
    docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
      --env-file .env restart backend
    ```

If a merge goes wrong, the deploy's pre-migration dump (`ai/backups.md`) holds the
database as it was before the deploy.

### Downgrading

`flask db downgrade` restores `NOT NULL` on `password_hash`, and while any account has
no password it stops and lists them; give each one a password or delete it first.
Emails stay folded, because their original letter case is gone.
````

### `ai/conventions.md` — the sign-in entry point, email storage, the public origin

1. Lines 46-49: replace

    ```markdown
    - Auth is a Flask-Login session cookie. Login and registration mark the session
      permanent, so the cookie carries an expiry and survives a browser restart, and Flask
      re-sends it with a fresh expiry on every response: a sign-in ends at logout or after
      `SESSION_LIFETIME_DAYS` (30, in `app.py`) without a request. Protect routes with
    ```

    with

    ```markdown
    - Auth is a Flask-Login session cookie. Every sign-in ends in `complete_login(user)`
      from `services/auth.py`, the only `login_user` call, so a new way to sign in (an
      OAuth callback, a passkey check) calls it too. It marks the session permanent, so
      the cookie carries an expiry and survives a browser restart, and Flask re-sends it
      with a fresh expiry on every response: a sign-in ends at logout or after
      `SESSION_LIFETIME_DAYS` (30, in `app.py`) without a request. Protect routes with
    ```

2. After line 53, which ends the auth bullet with "keeps Flask-Login's.", insert:

    ```markdown
    - `User` stores every email through `normalize_email()` in `models/user.py` (trimmed
      and lowercased), however the account is created or edited, and lookups go through
      `find_user_by_email()` in `services/auth.py`, so letter case never tells two
      accounts apart. Compare emails no other way.
    - `app.config['PUBLIC_BASE_URL']` is the only source of the public origin. Build OAuth
      redirect URIs and the WebAuthn origin from it, never from the request: there is no
      `ProxyFix`, so the request does not know the public origin. Development and testing
      default it to `http://localhost:$FRONTEND_PORT`; elsewhere it is `None` when unset,
      and the features that need it stay off. `ai/auth.md` has the details.
    ```

### `ai/domain.md` — passwordless accounts and the new fixture

1. Lines 10-11: replace

    ```markdown
      and the current-user lookup live in `src_back/api/auth.py` and
      `src_back/services/auth.py`.
    ```

    with

    ```markdown
      and the current-user lookup live in `src_back/api/auth.py` and
      `src_back/services/auth.py`; `ai/auth.md` covers sign-in in depth. An account a
      sign-in provider creates has no password (`password_hash` is `NULL`), which
      `User.has_password` and the `has_password` field of the user payload report.
    ```

2. After line 22 (the end of the `user` and `admin_user` bullet), insert:

    ```markdown
    - `passwordless_user` - a persisted account without a password, as a sign-in provider
      creates one
    ```

### `ai/project.md`, `tools.md`, `README.md`, `AGENTS.md`, `.claude/CLAUDE.md`

- `ai/project.md` lines 96-98: replace the paragraph with

    ```markdown
    `.env.example` documents every variable. `scripts/up.sh` rewrites the port variables,
    and `PUBLIC_BASE_URL` with them, when a port is busy; `scripts/worktree-setup.sh` shifts
    them per worktree. Outside `FLASK_ENV=development`, the app refuses to start with a
    placeholder `SECRET_KEY`, and without `PUBLIC_BASE_URL` it starts with OAuth sign-in
    and passkeys disabled.
    ```

- `tools.md` lines 61-63, the end of the Flask-Login bullet: replace with

    ```markdown
      unauthorized handler makes it answer a JSON 401 instead of redirecting. Every sign-in
      goes through `complete_login()`, which makes the session permanent, so a sign-in
      lasts 30 days past its latest request.
    ```

- `README.md`, the new-project checklist, after line 29 (the `docker-compose.yml`
  bullet):

    ```markdown
    - `Flask React Template`, the last fallback for `WEBAUTHN_RP_NAME` in `src_back/app.py`,
      and the test that expects it in `src_back/tests/test_app.py`
    ```

- `README.md` lines 202-206, the Agent instructions paragraph: replace with

    ```markdown
    `ai/project.md`, `ai/conventions.md`, and `ai/domain.md` are the canonical project
    instructions; `ai/auth.md`, `ai/backups.md`, and `ai/tls.md` are the operations
    runbooks. `AGENTS.md` and `.claude/CLAUDE.md` are thin adapters that point at them.
    `.claude/settings.json` runs `tsc -b` after every TypeScript edit and assigns new GitHub
    issues to the repository owner.
    ```

- `AGENTS.md`, after line 9 (`` - `ai/tls.md` ``): `` - `ai/auth.md` ``
- `.claude/CLAUDE.md`, after line 7 (`@../ai/tls.md`): `@../ai/auth.md`

## Parallelism

- **Can be done in parallel**:
    - **A. Backend accounts**: `models/user.py`, `services/errors.py`,
      `services/auth.py`, `api/auth.py`, `schemas/user.py`, `tests/conftest.py`,
      `tests/test_auth.py`, `tests/test_schemas.py`.
    - **B. App configuration**: `app.py`, `tests/test_app.py`.
    - **C. Configuration and scripts**: `.env.example`, both Compose files, and the four
      scripts.
    - **D. Documentation**: `ai/auth.md` and the other seven doc edits.
    - **E. Frontend**: `types/auth.ts` and the seven fixtures.

    After A and B, run Verification step 1, one pytest invocation for both. After E, run
    step 2.
- **Must be sequential**:
    - The migration and the `alembic.ini` logger come after A's `models/user.py` edit.
      Autogenerate must see `Mapped[str | None]`, and `db check` compares against it.
      Then run Verification steps 3 and 4.
    - Verification steps 5 and 6 come after C and the migration: the dev backend runs the
      migration when it starts, and step 5 reads the `up.sh` and Compose changes.
    - Verification step 8 is last.

## No other changes needed

- No other code creates users, compares emails, or calls `login_user`. `src_back/seed.py`
  only prints "No seed data defined.", and `src_back/auth.py` is untouched.
- Both schemas keep `fields.Email`. Padded input still gets a 422 before the service
  runs, and the Zod schemas reject it in the browser, so the strip in `normalize_email`
  matters for provider-asserted addresses. No `pre_load` trim is added.
- `migrations/env.py` is unchanged. `render_as_batch` stays off, and the migration calls
  `op.batch_alter_table` itself, as the issue says. The logging fix lives in
  `alembic.ini`.
- CI does not change. No CI job runs migrations, so Verification steps 3 and 4 run them
  by hand.
- No dependency is added, so `requirements*.txt`, `package.json`, `VENDOR_CHUNKS`, and
  `tools.md`'s inventory are untouched.
- `is_active` belongs to #7, as the PR #41 plan noted.
- Considered and not added:
    - startup validation that `PUBLIC_BASE_URL` is a bare origin, which #32 may want
    - a flush-only `create_account()` for #29's provider sign-up, which is #29's call
    - passing `APP_NAME` into the dev backend container, which means Docker dev passkey
      prompts fall back to `Flask React Template`
- For the follow-on issues:
    - #29 extends `ai/auth.md` rather than creating it, and reuses `passwordless_user`
      (`nopass@test.com`).
    - #29's `PUBLIC_BASE_URL='https://app.test'` override works because the default
      applies only to a value still unset after the overrides.
    - #29 and #32 add their counts to `count_sign_in_methods`.
    - The `@validates` guard normalizes #29's provider sign-ups and #7's admin edits
      without either remembering to.
- Noticed, out of scope: `plans/pr-41-add-sql-pagination-test-helper-and-docs.md` is
  still at the top of `plans/`, though PR #41 has merged.

## Verification

1. **Targeted backend tests**, in one invocation:

    ```bash
    .venv/bin/python -m pytest src_back/tests/test_auth.py src_back/tests/test_schemas.py \
      src_back/tests/test_app.py --no-cov
    ```

2. **Frontend**: the seven fixture files, then the type check, which also type-checks
   the tests:

    ```bash
    npx vitest run src_front/src/test/store.test.ts src_front/src/test/authApi.test.ts \
      src_front/src/test/AppShell.test.tsx src_front/src/test/App.test.tsx \
      src_front/src/test/ProtectedRoute.test.tsx src_front/src/test/Register.test.tsx \
      src_front/src/test/Login.test.tsx
    npm run typecheck
    ```

3. **Migration on SQLite**, in a scratch file, covering the collision abort, a clean
   upgrade, the downgrade refusal, and the round trip:

    ```bash
    db="$(mktemp -d)/check.db"
    export DATABASE_URL="sqlite:///$db" FLASK_ENV=development
    flask_cli() { .venv/bin/flask --app src_back.app db "$@"; }
    flask_cli upgrade 683d57722be2
    sqlite3 "$db" "INSERT INTO users (email, password_hash, role, uuid, created_at, updated_at)
      VALUES ('Bob@x.test', 'h', 'user', 'u1', '2026-01-01', '2026-01-01'),
             (' bob@x.test', 'h', 'user', 'u2', '2026-01-01', '2026-01-01');"
    flask_cli upgrade          # RuntimeError listing ids 1 and 2
    flask_cli current          # still 683d57722be2
    sqlite3 "$db" "DELETE FROM users WHERE id = 2;"
    flask_cli upgrade
    sqlite3 "$db" "SELECT email FROM users;"   # bob@x.test
    flask_cli check            # No new upgrade operations detected.
    sqlite3 "$db" "INSERT INTO users (email, password_hash, role, uuid, created_at, updated_at)
      VALUES ('nopass@x.test', NULL, 'user', 'u3', '2026-01-01', '2026-01-01');"
    flask_cli downgrade        # the listing of nopass@x.test; the revision defaults to -1
    sqlite3 "$db" "DELETE FROM users WHERE password_hash IS NULL;"
    flask_cli downgrade
    flask_cli upgrade
    flask_cli check
    unset DATABASE_URL FLASK_ENV
    ```

4. **Migration on PostgreSQL**, in a scratch database inside the dev stack:

    ```bash
    npm run docker:up -- -d
    port="$(grep '^DB_PORT=' .env | cut -d= -f2)"
    docker compose exec -T db createdb -U app scratch28
    export DATABASE_URL="postgresql://app:app@localhost:$port/scratch28" FLASK_ENV=development
    flask_cli() { .venv/bin/flask --app src_back.app db "$@"; }
    flask_cli upgrade 683d57722be2
    docker compose exec -T db psql -U app -d scratch28 -c "INSERT INTO users
      (email, password_hash, role, uuid, created_at, updated_at) VALUES
      ('Bob@x.test', 'h', 'user', 'u1', now(), now()),
      ('bob@x.test', 'h', 'user', 'u2', now(), now());"
    flask_cli upgrade          # RuntimeError listing both; current stays 683d57722be2
    docker compose exec -T db psql -U app -d scratch28 -c "DELETE FROM users WHERE id = 2;"
    flask_cli upgrade && flask_cli check
    flask_cli downgrade && flask_cli upgrade && flask_cli check
    unset DATABASE_URL FLASK_ENV
    docker compose exec -T db dropdb -U app scratch28
    ```

5. **Dev stack behavior**: `.env` was rewritten, the backend has the origin and no
   warning, and registration stores a folded email and reports `has_password`:

    ```bash
    grep '^PUBLIC_BASE_URL=' .env          # http://localhost:<FRONTEND_PORT>
    docker compose exec -T backend printenv PUBLIC_BASE_URL
    docker compose logs backend | grep -c 'PUBLIC_BASE_URL is not set'   # 0
    backend="http://localhost:$(grep '^BACKEND_PORT=' .env | cut -d= -f2)"
    jar="$(mktemp -d)/cookies"
    curl -s -c "$jar" -H 'Content-Type: application/json' \
      -d "{\"email\": \"Mixed.$(date +%s)@Example.COM\", \"password\": \"secure123\"}" \
      "$backend/api/v1/auth/register"      # lowercased email, "has_password": true
    curl -s -b "$jar" "$backend/api/v1/auth/me"   # the same fields
    ```

    Optionally, set a custom `PUBLIC_BASE_URL` such as `https://tunnel.example.test` in
    `.env`, rerun `npm run docker:down` and `npm run docker:up -- -d`, confirm the value
    survives, and restore it.

6. **Production Compose**: the backend gets the server's origin, not the dev localhost
   value:

    ```bash
    PUBLIC_BASE_URL=https://app.example.com WEBAUTHN_RP_NAME='Example App' \
      docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
      config backend | grep -E 'PUBLIC_BASE_URL|WEBAUTHN_RP_NAME'
    ```

7. **Scripts parse**:

    ```bash
    sh -n scripts/up.sh && sh -n scripts/worktree-setup.sh \
      && bash -n scripts/deploy.sh && bash -n scripts/provision.sh
    ```

8. **Full gates**: run `npm run test`, `npm run lint`, and `npm run lint:py` in
   parallel, then `npm run lint:md`, `npm run typecheck`, and `npx prettier --check .`.
   Both suites must stay at 100% coverage.
