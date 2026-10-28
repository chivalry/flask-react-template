import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from src_back.models import AuditAction, AuditLog, Role, User
from src_back.seed import seed
from src_back.services.auth import authenticate_user
from src_back.services.users import update_user
from src_back.tests.helpers import persist

ADMIN_EMAIL = 'admin@example.com'
# ADMIN_EMAIL as an operator might type it into .env: padded and in mixed case.
TYPED_ADMIN_EMAIL = '  Admin@Example.COM '
ADMIN_PASSWORD = 'correct horse battery staple'
# Where the first admin moves on the Users screen, away from ADMIN_EMAIL.
RENAMED_ADMIN_EMAIL = 'owner@example.com'

ADMIN_SKIP_LINE = 'Skipping admin seed: ADMIN_EMAIL and ADMIN_PASSWORD are not set.'
ADMIN_EXISTS_LINE = 'An admin account already exists; skipping admin seed.'
ACCOUNT_EXISTS_LINE = 'Account Admin@Example.COM already exists; skipping admin seed.'


@pytest.fixture(autouse=True)
def _clear_admin_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # src_back.app loads .env at import, which may carry real admin credentials;
    # every test here starts with neither variable set.
    for name in ('ADMIN_EMAIL', 'ADMIN_PASSWORD'):
        monkeypatch.delenv(name, raising=False)


def _account_rows(db: SQLAlchemy) -> list[tuple[object, ...]]:
    # Columns rather than User objects: a second read then comes from the database,
    # not from the session's identity map, which a commit in seed's own application
    # context does not expire.
    columns = (
        User.id,
        User.email,
        User.role,
        User.is_active,
        User.password_hash,
        User.updated_at,
    )
    return [tuple(row) for row in db.session.query(*columns).order_by(User.id)]


@pytest.mark.parametrize(
    ('email', 'password'),
    [
        pytest.param(None, None, id='both-unset'),
        pytest.param(None, ADMIN_PASSWORD, id='email-unset'),
        pytest.param(ADMIN_EMAIL, None, id='password-unset'),
        pytest.param('', ADMIN_PASSWORD, id='email-empty'),
        pytest.param(ADMIN_EMAIL, '', id='password-empty'),
        pytest.param('   ', ADMIN_PASSWORD, id='email-whitespace'),
        pytest.param(ADMIN_EMAIL, '   ', id='password-whitespace'),
    ],
)
def test_seed_skips_the_admin_when_credentials_are_absent_or_blank(
    app: Flask,
    db: SQLAlchemy,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    email: str | None,
    password: str | None,
) -> None:
    if email is not None:
        monkeypatch.setenv('ADMIN_EMAIL', email)
    if password is not None:
        monkeypatch.setenv('ADMIN_PASSWORD', password)
    seed(app)
    assert db.session.query(User).count() == 0
    assert ADMIN_SKIP_LINE in capsys.readouterr().out


def test_seed_creates_a_normalized_active_admin(
    app: Flask,
    db: SQLAlchemy,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv('ADMIN_EMAIL', TYPED_ADMIN_EMAIL)
    monkeypatch.setenv('ADMIN_PASSWORD', ADMIN_PASSWORD)
    seed(app)
    admin = db.session.query(User).one()
    assert admin.email == ADMIN_EMAIL
    assert admin.role == Role.admin
    assert admin.is_active is True
    assert admin.check_password(ADMIN_PASSWORD)
    assert not admin.check_password('wrong password')
    assert f'Seeded admin {ADMIN_EMAIL}.' in capsys.readouterr().out
    entry = db.session.query(AuditLog).one()
    assert entry.table_name == 'users'
    assert entry.record_id == admin.id
    assert entry.action is AuditAction.created
    assert entry.changed_by_id is None


def test_seed_leaves_an_existing_account_in_another_case_untouched(
    app: Flask,
    db: SQLAlchemy,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    existing = User(email=ADMIN_EMAIL, role=Role.user)
    existing.set_password('original password')
    persist(existing)
    monkeypatch.setenv('ADMIN_EMAIL', TYPED_ADMIN_EMAIL)
    monkeypatch.setenv('ADMIN_PASSWORD', ADMIN_PASSWORD)
    seed(app)
    # persist() committed, which expired `existing`, so this query reloads it from
    # the database.
    account = db.session.query(User).one()
    assert account.role == Role.user
    assert account.check_password('original password')
    assert not account.check_password(ADMIN_PASSWORD)
    assert ACCOUNT_EXISTS_LINE in capsys.readouterr().out


def test_seed_twice_changes_nothing(
    app: Flask,
    db: SQLAlchemy,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv('ADMIN_EMAIL', TYPED_ADMIN_EMAIL)
    monkeypatch.setenv('ADMIN_PASSWORD', ADMIN_PASSWORD)
    seed(app)
    first_run = _account_rows(db)
    assert len(first_run) == 1
    capsys.readouterr()
    seed(app)
    assert _account_rows(db) == first_run
    assert db.session.query(AuditLog).count() == 1
    assert ADMIN_EXISTS_LINE in capsys.readouterr().out


def test_seed_creates_no_admin_after_the_first_changes_email(
    app: Flask,
    db: SQLAlchemy,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv('ADMIN_EMAIL', ADMIN_EMAIL)
    monkeypatch.setenv('ADMIN_PASSWORD', ADMIN_PASSWORD)
    seed(app)
    admin_id = db.session.query(User.id).scalar()
    # The first admin retires the bootstrap credentials on the Users screen.
    update_user(
        admin_id,
        {'email': RENAMED_ADMIN_EMAIL, 'password': 'a password of their own'},
        actor_id=admin_id,
    )
    capsys.readouterr()
    seed(app)
    assert [row[1] for row in _account_rows(db)] == [RENAMED_ADMIN_EMAIL]
    assert authenticate_user(ADMIN_EMAIL, ADMIN_PASSWORD) is None
    assert ADMIN_EXISTS_LINE in capsys.readouterr().out


@pytest.mark.parametrize('is_active', [True, False], ids=['active', 'inactive'])
def test_seed_skips_while_any_admin_exists(
    app: Flask,
    db: SQLAlchemy,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    is_active: bool,
) -> None:
    persist(User(email=RENAMED_ADMIN_EMAIL, role=Role.admin, is_active=is_active))
    monkeypatch.setenv('ADMIN_EMAIL', ADMIN_EMAIL)
    monkeypatch.setenv('ADMIN_PASSWORD', ADMIN_PASSWORD)
    seed(app)
    assert [row[1] for row in _account_rows(db)] == [RENAMED_ADMIN_EMAIL]
    assert ADMIN_EXISTS_LINE in capsys.readouterr().out


@pytest.mark.usefixtures('user')
def test_seed_creates_the_admin_beside_plain_accounts(
    app: Flask,
    db: SQLAlchemy,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv('ADMIN_EMAIL', ADMIN_EMAIL)
    monkeypatch.setenv('ADMIN_PASSWORD', ADMIN_PASSWORD)
    seed(app)
    roles = {row[1]: row[2] for row in _account_rows(db)}
    assert roles == {'user@test.com': Role.user, ADMIN_EMAIL: Role.admin}
    assert f'Seeded admin {ADMIN_EMAIL}.' in capsys.readouterr().out
