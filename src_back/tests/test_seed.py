import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from src_back.models import Role, User
from src_back.seed import seed
from src_back.tests.helpers import persist

ADMIN_EMAIL = 'admin@example.com'
# ADMIN_EMAIL as an operator might type it into .env: padded and in mixed case.
TYPED_ADMIN_EMAIL = '  Admin@Example.COM '
ADMIN_PASSWORD = 'correct horse battery staple'

ADMIN_SKIP_LINE = 'Skipping admin seed: ADMIN_EMAIL and ADMIN_PASSWORD are not set.'
ADMIN_EXISTS_LINE = 'Admin Admin@Example.COM already exists; skipping admin seed.'


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
    assert ADMIN_EXISTS_LINE in capsys.readouterr().out


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
    assert ADMIN_EXISTS_LINE in capsys.readouterr().out
