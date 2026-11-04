import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial

import flask_login
import pytest
from flask import Flask, g, session
from flask.testing import FlaskClient
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select
from werkzeug.security import check_password_hash

from src_back import auth
from src_back.api import auth as auth_api
from src_back.app import SESSION_LIFETIME_DAYS
from src_back.models import AuditAction, AuditLog, Role, User, WebAuthnCredential
from src_back.models import user as user_model
from src_back.services import auth as auth_service
from src_back.services import oauth as oauth_service
from src_back.services import passkeys as passkey_service
from src_back.services.auth import (
    LAST_METHOD,
    complete_login,
    count_sign_in_methods,
    find_user_by_email,
    require_another_sign_in_method,
)
from src_back.services.errors import InactiveAccountError, LastSignInMethodError
from src_back.services.oauth import unlink_account
from src_back.services.oauth_state import SECURE_COOKIE_NAME
from src_back.services.passkeys import delete_passkey
from src_back.tests.helpers import persist
from src_back.tests.software_authenticator import SoftwareAuthenticator

SESSION_LIFETIME = timedelta(days=SESSION_LIFETIME_DAYS)

# Removes one of an account's sign-in methods, as delete_passkey and unlink_account do.
RemoveMethod = Callable[[User], bool]

RACE_TIMEOUT_SECONDS = 10


def _assert_session_cookie_expires_one_lifetime_after(
    client: FlaskClient, before: datetime, after: datetime
) -> None:
    cookie = client.get_cookie('session')
    assert cookie is not None
    assert cookie.expires is not None
    # Expires carries whole seconds, so the earliest bound drops the fraction.
    earliest = before.replace(microsecond=0) + SESSION_LIFETIME
    assert earliest <= cookie.expires <= after + SESSION_LIFETIME


def test_register_success(client: FlaskClient) -> None:
    r = client.post(
        '/api/v1/auth/register',
        json={'email': 'new@example.com', 'password': 'secure123'},
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data['email'] == 'new@example.com'
    assert data['role'] == 'user'
    assert 'password' not in data
    assert 'password_hash' not in data
    assert 'id' in data


def test_register_creates_an_active_user(client: FlaskClient) -> None:
    r = client.post(
        '/api/v1/auth/register',
        json={'email': 'new@example.com', 'password': 'secure123'},
    )
    assert r.status_code == 201
    assert r.get_json()['is_active'] is True
    account = find_user_by_email('new@example.com')
    assert account is not None
    assert account.role is Role.user
    assert account.is_active is True


def test_register_logs_the_account_with_no_actor(
    client: FlaskClient, db: SQLAlchemy
) -> None:
    r = client.post(
        '/api/v1/auth/register',
        json={'email': 'new@example.com', 'password': 'secure123'},
    )
    assert r.status_code == 201
    entry = db.session.scalars(select(AuditLog)).one()
    assert entry.table_name == 'users'
    assert entry.record_id == r.get_json()['id']
    assert entry.record_label == 'new@example.com'
    assert entry.action is AuditAction.created
    assert entry.changes == {
        'email': 'new@example.com',
        'role': 'user',
        'is_active': True,
    }
    assert entry.changed_by_id is None


def test_register_cookie_expires_one_session_lifetime_out(client: FlaskClient) -> None:
    before = datetime.now(UTC)
    r = client.post(
        '/api/v1/auth/register',
        json={'email': 'new@example.com', 'password': 'secure123'},
    )
    after = datetime.now(UTC)
    assert r.status_code == 201
    _assert_session_cookie_expires_one_lifetime_after(client, before, after)


def test_register_duplicate_email(client: FlaskClient, user: User) -> None:
    r = client.post(
        '/api/v1/auth/register',
        json={'email': user.email, 'password': 'secure123'},
    )
    assert r.status_code == 409
    assert r.get_json() == {'error': 'Email already registered.'}


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


def test_register_short_password_is_unprocessable(client: FlaskClient) -> None:
    r = client.post(
        '/api/v1/auth/register',
        json={'email': 'x@example.com', 'password': 'short'},
    )
    assert r.status_code == 422
    assert r.get_json() == {'error': 'Invalid request'}


def test_register_invalid_email_is_unprocessable(client: FlaskClient) -> None:
    r = client.post(
        '/api/v1/auth/register',
        json={'email': 'not-an-email', 'password': 'secure123'},
    )
    assert r.status_code == 422


@pytest.mark.parametrize(('field', 'value'), [('role', 'admin'), ('is_active', False)])
def test_register_cannot_choose_a_role_or_active_state(
    client: FlaskClient, field: str, value: object
) -> None:
    r = client.post(
        '/api/v1/auth/register',
        json={'email': 'x@example.com', 'password': 'secure123', field: value},
    )
    assert r.status_code == 422
    assert find_user_by_email('x@example.com') is None


def test_register_without_body_is_unprocessable(client: FlaskClient) -> None:
    r = client.post('/api/v1/auth/register')
    assert r.status_code == 422


def test_login_success(client: FlaskClient, user: User) -> None:
    r = client.post(
        '/api/v1/auth/login',
        json={'email': user.email, 'password': 'password123'},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data['email'] == user.email
    assert 'password' not in data


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


def test_login_invalid_payload_is_unprocessable(client: FlaskClient) -> None:
    r = client.post('/api/v1/auth/login', json={'email': 'not-an-email'})
    assert r.status_code == 422


def test_login_wrong_password(client: FlaskClient, user: User) -> None:
    r = client.post(
        '/api/v1/auth/login',
        json={'email': user.email, 'password': 'wrongpassword'},
    )
    assert r.status_code == 401
    assert r.get_json() == {'error': 'Invalid email or password.'}


def test_login_unknown_email(client: FlaskClient) -> None:
    r = client.post(
        '/api/v1/auth/login',
        json={'email': 'nobody@example.com', 'password': 'password123'},
    )
    assert r.status_code == 401


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


def test_login_refuses_an_inactive_account_with_the_right_password(
    client: FlaskClient, inactive_user: User
) -> None:
    r = client.post(
        '/api/v1/auth/login',
        json={'email': inactive_user.email, 'password': 'password123'},
    )
    assert r.status_code == 403
    assert r.get_json() == {'error': 'Account is inactive.'}
    assert client.get_cookie('session') is None
    # The test app context is shared across client requests, so drop flask_login's
    # cached g._login_user to make /me read the session cookie, which was never set.
    g.pop('_login_user', None)
    assert client.get('/api/v1/auth/me').status_code == 401


@pytest.mark.usefixtures('user', 'passwordless_user', 'inactive_user')
@pytest.mark.parametrize(
    ('email', 'password'),
    [
        ('nobody@test.com', 'password123'),
        ('nopass@test.com', 'password123'),
        ('user@test.com', 'wrongpassword'),
        ('inactive@test.com', 'wrongpassword'),
    ],
    ids=['unknown-email', 'no-password', 'wrong-password', 'inactive-wrong-password'],
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


def test_complete_login_refuses_an_inactive_account(
    app: Flask, inactive_user: User
) -> None:
    with app.test_request_context():
        with pytest.raises(InactiveAccountError, match='Account is inactive.'):
            complete_login(inactive_user)
        assert flask_login.current_user.is_anonymous


def test_logout_success(auth_client: FlaskClient) -> None:
    r = auth_client.post('/api/v1/auth/logout')
    assert r.status_code == 200
    assert r.get_json() == {'message': 'Logged out.'}


def test_logout_deletes_the_session_cookie(auth_client: FlaskClient) -> None:
    assert auth_client.post('/api/v1/auth/logout').status_code == 200
    assert auth_client.get_cookie('session') is None
    # The test app context is shared across client requests, so drop flask_login's
    # cached g._login_user to make /me read the session cookie, which is now gone.
    g.pop('_login_user', None)
    assert auth_client.get('/api/v1/auth/me').status_code == 401


def test_logout_clears_the_transaction_cookie(auth_client: FlaskClient) -> None:
    r = auth_client.post('/api/v1/auth/logout')
    assert r.status_code == 200
    header = next(
        header
        for header in r.headers.getlist('Set-Cookie')
        if header.startswith(f'{SECURE_COOKIE_NAME}=')
    )
    attributes = header.split('; ')[1:]
    assert 'Max-Age=0' in attributes
    assert 'Path=/' in attributes
    assert 'Secure' in attributes


def test_logout_unauthenticated(client: FlaskClient) -> None:
    r = client.post('/api/v1/auth/logout')
    assert r.status_code == 401


def test_me_authenticated(auth_client: FlaskClient, user: User) -> None:
    r = auth_client.get('/api/v1/auth/me')
    assert r.status_code == 200
    assert r.get_json()['email'] == user.email
    assert r.get_json()['has_password'] is True


def test_authenticated_request_extends_the_session_cookie(
    auth_client: FlaskClient,
) -> None:
    before = datetime.now(UTC)
    r = auth_client.get('/api/v1/auth/me')
    after = datetime.now(UTC)
    assert r.status_code == 200
    assert any(h.startswith('session=') for h in r.headers.getlist('Set-Cookie'))
    _assert_session_cookie_expires_one_lifetime_after(auth_client, before, after)


def test_me_unauthenticated(client: FlaskClient) -> None:
    r = client.get('/api/v1/auth/me')
    assert r.status_code == 401


def test_typed_current_user_is_flask_logins_proxy() -> None:
    assert auth.current_user is flask_login.current_user


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


def test_count_sign_in_methods_counts_each_linked_provider(linked_user: User) -> None:
    assert count_sign_in_methods(linked_user) == 1
    linked_user.set_password('password123')
    assert count_sign_in_methods(linked_user) == 2


def test_count_sign_in_methods_counts_each_passkey(
    linked_user: User, authenticator: SoftwareAuthenticator
) -> None:
    assert count_sign_in_methods(linked_user) == 1
    persist(authenticator.credential_for(linked_user))
    assert count_sign_in_methods(linked_user) == 2
    persist(SoftwareAuthenticator().credential_for(linked_user))
    assert count_sign_in_methods(linked_user) == 3


def test_require_another_sign_in_method(linked_user: User) -> None:
    with pytest.raises(LastSignInMethodError, match=LAST_METHOD):
        require_another_sign_in_method(linked_user)
    linked_user.set_password('password123')
    require_another_sign_in_method(linked_user)


# Two removals at once, which only PostgreSQL's row lock keeps apart


@pytest.fixture()
def on_postgresql(db: SQLAlchemy) -> None:
    # SQLite ignores FOR UPDATE, so only PostgreSQL can show what the lock does.
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('needs PostgreSQL, through TEST_DATABASE_URL')


def remove_at_once(
    app: Flask,
    db: SQLAlchemy,
    monkeypatch: pytest.MonkeyPatch,
    account_id: int,
    removers: tuple[RemoveMethod, RemoveMethod],
) -> list[object]:
    # The first removal holds once its count passes, and the second starts meanwhile.
    first_checked = threading.Event()
    release_first = threading.Event()

    def check_then_hold(user: User) -> None:
        require_another_sign_in_method(user)
        if threading.current_thread().name == 'first':
            first_checked.set()
            release_first.wait(RACE_TIMEOUT_SECONDS)

    for module in (passkey_service, oauth_service):
        monkeypatch.setattr(module, 'require_another_sign_in_method', check_then_hold)
    outcomes: dict[str, object] = {}

    def remove(name: str, remover: RemoveMethod) -> None:
        # An application context of its own gives it a session and connection of its own.
        with app.app_context():
            user = db.session.get_one(User, account_id)
            count_sign_in_methods(user)  # read first, so the remover must reload them
            try:
                outcomes[name] = remover(user)
            except Exception as exc:
                outcomes[name] = exc

    names = ('first', 'second')
    threads = [
        threading.Thread(target=remove, args=pair, name=pair[0])
        for pair in zip(names, removers, strict=True)
    ]
    threads[0].start()
    try:
        assert first_checked.wait(RACE_TIMEOUT_SECONDS)
        threads[1].start()
        threads[1].join(1)
        # Still running a second later, because it waits for the first one's lock.
        assert threads[1].is_alive()
    finally:
        release_first.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(RACE_TIMEOUT_SECONDS)
    assert not any(thread.is_alive() for thread in threads)
    return [outcomes[name] for name in names]


@pytest.mark.usefixtures('on_postgresql')
def test_two_passkey_deletes_at_once_leave_one(
    app: Flask, db: SQLAlchemy, passwordless_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_id = persist(SoftwareAuthenticator().credential_for(passwordless_user)).id
    second_id = persist(SoftwareAuthenticator().credential_for(passwordless_user)).id
    removers = (
        partial(delete_passkey, passkey_id=first_id),
        partial(delete_passkey, passkey_id=second_id),
    )
    first, second = remove_at_once(app, db, monkeypatch, passwordless_user.id, removers)
    assert first is True
    assert isinstance(second, LastSignInMethodError)
    # Only committed rows survive a rollback.
    db.session.rollback()
    remaining = db.session.scalars(
        select(WebAuthnCredential.id).where(
            WebAuthnCredential.user_id == passwordless_user.id
        )
    ).all()
    assert remaining == [second_id]


@pytest.mark.parametrize(
    ('first', 'second'),
    [('unlink', 'delete'), ('delete', 'unlink')],
    ids=['unlink-first', 'delete-first'],
)
@pytest.mark.usefixtures('on_postgresql')
def test_an_unlink_and_a_delete_at_once_leave_one_way_in(
    app: Flask,
    db: SQLAlchemy,
    linked_user: User,
    authenticator: SoftwareAuthenticator,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
    second: str,
) -> None:
    passkey_id = persist(authenticator.credential_for(linked_user)).id
    removers: dict[str, RemoveMethod] = {
        'unlink': partial(unlink_account, provider='google'),
        'delete': partial(delete_passkey, passkey_id=passkey_id),
    }
    pair = (removers[first], removers[second])
    outcomes = remove_at_once(app, db, monkeypatch, linked_user.id, pair)
    assert outcomes[0] is True
    assert isinstance(outcomes[1], LastSignInMethodError)
    db.session.rollback()
    assert count_sign_in_methods(linked_user) == 1


@pytest.mark.parametrize('method', ['passkey', 'provider'])
@pytest.mark.usefixtures('on_postgresql')
def test_two_removals_of_one_method_at_once_remove_it_once(
    app: Flask,
    db: SQLAlchemy,
    linked_user: User,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    # Google and two passkeys, so the count lets both through: only a lookup made after
    # the lock tells the second that the first took the method.
    passkey_id = persist(SoftwareAuthenticator().credential_for(linked_user)).id
    persist(SoftwareAuthenticator().credential_for(linked_user))
    removers: dict[str, RemoveMethod] = {
        'passkey': partial(delete_passkey, passkey_id=passkey_id),
        'provider': partial(unlink_account, provider='google'),
    }
    remove = removers[method]
    outcomes = remove_at_once(app, db, monkeypatch, linked_user.id, (remove, remove))
    assert outcomes == [True, False]
