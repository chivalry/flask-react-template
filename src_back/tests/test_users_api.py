import pytest
from flask import Flask
from flask.testing import FlaskClient
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select
from werkzeug.test import TestResponse

from src_back.models import Role, User
from src_back.tests.helpers import persist

USERS_URL = '/api/v1/users'
LOGIN_URL = '/api/v1/auth/login'
ME_URL = '/api/v1/auth/me'

PROTECTED_ROUTES = [
    ('GET', USERS_URL),
    ('POST', USERS_URL),
    ('PUT', f'{USERS_URL}/1'),
]

EMAIL_IN_USE_ERROR = {'error': 'Email already in use.'}
SELF_MODIFICATION_ERROR = {'error': 'You cannot deactivate or demote your own account.'}


def _login(client: FlaskClient, email: str, password: str) -> TestResponse:
    return client.post(LOGIN_URL, json={'email': email, 'password': password})


def _login_from_fresh_browser(app: Flask, email: str, password: str) -> TestResponse:
    # The ``app`` fixture keeps one application context pushed for the whole test,
    # Flask reuses it for every test-client request, and Flask-Login caches the
    # loaded user on ``g`` per context. A second client therefore runs its requests
    # in a fresh context, as a separate browser would.
    with app.app_context():
        return _login(app.test_client(), email, password)


def _persist_user(email: str) -> User:
    account = User(email=email, role=Role.user)
    account.set_password('password123')
    return persist(account)


# -- access control -----------------------------------------------------------


@pytest.mark.parametrize(('method', 'path'), PROTECTED_ROUTES)
def test_routes_reject_anonymous_callers(
    client: FlaskClient, method: str, path: str
) -> None:
    r = client.open(path, method=method, json={})
    assert r.status_code == 401
    assert r.get_json() == {'error': 'Unauthorized'}


@pytest.mark.parametrize(('method', 'path'), PROTECTED_ROUTES)
def test_routes_forbid_non_admins(
    auth_client: FlaskClient, method: str, path: str
) -> None:
    r = auth_client.open(path, method=method, json={})
    assert r.status_code == 403
    assert r.get_json() == {'error': 'Admin access required.'}


# -- list ---------------------------------------------------------------------


@pytest.mark.usefixtures('user')
def test_list_returns_pagination_envelope_ordered_by_email(
    admin_client: FlaskClient,
) -> None:
    _persist_user('zed@test.com')
    _persist_user('bob@test.com')
    r = admin_client.get(USERS_URL)
    assert r.status_code == 200
    data = r.get_json()
    assert set(data) == {'items', 'total', 'page', 'pages', 'per_page'}
    assert data['total'] == 4
    assert data['page'] == 1
    assert data['pages'] == 1
    assert data['per_page'] == 20
    assert [item['email'] for item in data['items']] == [
        'admin@test.com',
        'bob@test.com',
        'user@test.com',
        'zed@test.com',
    ]


@pytest.mark.usefixtures('user')
def test_list_items_carry_is_active_and_never_the_password(
    admin_client: FlaskClient,
) -> None:
    r = admin_client.get(USERS_URL)
    items = r.get_json()['items']
    assert len(items) == 2
    for item in items:
        assert item['is_active'] is True
        assert 'password' not in item
        assert 'password_hash' not in item


@pytest.mark.usefixtures('inactive_user')
def test_list_includes_deactivated_accounts(admin_client: FlaskClient) -> None:
    # An admin reactivates an account from this list, so it must show inactive ones.
    items = admin_client.get(USERS_URL).get_json()['items']
    assert {item['email']: item['is_active'] for item in items} == {
        'admin@test.com': True,
        'inactive@test.com': False,
    }


# -- create -------------------------------------------------------------------


def test_create_admin_account(admin_client: FlaskClient, app: Flask) -> None:
    r = admin_client.post(
        USERS_URL,
        json={'email': 'new@test.com', 'password': 'secure123', 'role': 'admin'},
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data['email'] == 'new@test.com'
    assert data['role'] == 'admin'
    assert data['is_active'] is True
    assert 'id' in data
    assert 'password' not in data
    assert 'password_hash' not in data
    assert _login_from_fresh_browser(app, 'new@test.com', 'secure123').status_code == 200


def test_create_defaults_to_an_active_user_account(
    admin_client: FlaskClient, app: Flask
) -> None:
    r = admin_client.post(
        USERS_URL, json={'email': 'new@test.com', 'password': 'secure123'}
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data['role'] == 'user'
    assert data['is_active'] is True
    assert _login_from_fresh_browser(app, 'new@test.com', 'secure123').status_code == 200


def test_create_inactive_account_cannot_log_in(
    admin_client: FlaskClient, app: Flask
) -> None:
    r = admin_client.post(
        USERS_URL,
        json={'email': 'new@test.com', 'password': 'secure123', 'is_active': False},
    )
    assert r.status_code == 201
    assert r.get_json()['is_active'] is False
    assert _login_from_fresh_browser(app, 'new@test.com', 'secure123').status_code == 403


def test_create_stores_the_email_normalized(
    admin_client: FlaskClient, db: SQLAlchemy
) -> None:
    r = admin_client.post(
        USERS_URL, json={'email': 'New@Test.COM', 'password': 'secure123'}
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data['email'] == 'new@test.com'
    # A column query reads the row itself rather than the session's in-memory object.
    stored = db.session.scalar(select(User.email).where(User.id == data['id']))
    assert stored == 'new@test.com'


def test_create_duplicate_email_conflicts(admin_client: FlaskClient, user: User) -> None:
    r = admin_client.post(USERS_URL, json={'email': user.email, 'password': 'secure123'})
    assert r.status_code == 409
    assert r.get_json() == EMAIL_IN_USE_ERROR


def test_create_email_taken_in_another_case_conflicts(
    admin_client: FlaskClient, user: User
) -> None:
    r = admin_client.post(
        USERS_URL, json={'email': user.email.upper(), 'password': 'secure123'}
    )
    assert r.status_code == 409
    assert r.get_json() == EMAIL_IN_USE_ERROR


@pytest.mark.parametrize(
    'payload',
    [
        {'email': 'new@test.com', 'password': 'short'},
        {'email': 'not-an-email', 'password': 'secure123'},
        {'email': 'new@test.com'},
    ],
    ids=['short-password', 'invalid-email', 'missing-password'],
)
def test_create_invalid_payload_is_unprocessable(
    admin_client: FlaskClient, payload: dict[str, str]
) -> None:
    r = admin_client.post(USERS_URL, json=payload)
    assert r.status_code == 422
    assert r.get_json() == {'error': 'Invalid request'}


# -- update -------------------------------------------------------------------


def test_update_email(admin_client: FlaskClient, user: User) -> None:
    r = admin_client.put(f'{USERS_URL}/{user.id}', json={'email': 'renamed@test.com'})
    assert r.status_code == 200
    assert r.get_json()['email'] == 'renamed@test.com'
    assert user.email == 'renamed@test.com'


def test_update_role(admin_client: FlaskClient, user: User) -> None:
    r = admin_client.put(f'{USERS_URL}/{user.id}', json={'role': 'admin'})
    assert r.status_code == 200
    assert r.get_json()['role'] == 'admin'
    assert user.role == Role.admin


def test_deactivation_ends_the_session_and_blocks_login(
    admin_client: FlaskClient, app: Flask, user: User
) -> None:
    # The user's own browser; see ``_login_from_fresh_browser`` for the context.
    other = app.test_client()
    with app.app_context():
        assert _login(other, user.email, 'password123').status_code == 200
        assert other.get(ME_URL).status_code == 200

    r = admin_client.put(f'{USERS_URL}/{user.id}', json={'is_active': False})
    assert r.status_code == 200
    assert r.get_json()['is_active'] is False

    # Another fresh context, so Flask-Login reloads the account from the session
    # cookie instead of returning a user cached on ``g``.
    with app.app_context():
        assert other.get(ME_URL).status_code == 401
        r = _login(other, user.email, 'password123')
    assert r.status_code == 403
    assert r.get_json() == {'error': 'Account is inactive.'}


def test_update_password(admin_client: FlaskClient, app: Flask, user: User) -> None:
    r = admin_client.put(f'{USERS_URL}/{user.id}', json={'password': 'newsecret1'})
    assert r.status_code == 200
    assert 'password' not in r.get_json()
    assert _login_from_fresh_browser(app, user.email, 'newsecret1').status_code == 200
    assert _login_from_fresh_browser(app, user.email, 'password123').status_code == 401


def test_admin_cannot_deactivate_themself(
    admin_client: FlaskClient, admin_user: User
) -> None:
    r = admin_client.put(f'{USERS_URL}/{admin_user.id}', json={'is_active': False})
    assert r.status_code == 400
    assert r.get_json() == SELF_MODIFICATION_ERROR
    assert admin_user.is_active is True


def test_admin_cannot_demote_themself(
    admin_client: FlaskClient, admin_user: User
) -> None:
    r = admin_client.put(f'{USERS_URL}/{admin_user.id}', json={'role': 'user'})
    assert r.status_code == 400
    assert r.get_json() == SELF_MODIFICATION_ERROR
    assert admin_user.role == Role.admin


def test_admin_can_change_their_own_email(
    admin_client: FlaskClient, admin_user: User
) -> None:
    r = admin_client.put(
        f'{USERS_URL}/{admin_user.id}',
        json={'email': 'root@test.com', 'role': 'admin', 'is_active': True},
    )
    assert r.status_code == 200
    assert r.get_json()['email'] == 'root@test.com'
    assert admin_client.get(ME_URL).get_json()['email'] == 'root@test.com'


def test_update_unknown_id_is_not_found(admin_client: FlaskClient) -> None:
    r = admin_client.put(f'{USERS_URL}/9999', json={'email': 'ghost@test.com'})
    assert r.status_code == 404
    assert r.get_json() == {'error': 'Not found'}


def test_update_to_another_users_email_conflicts(
    admin_client: FlaskClient, admin_user: User, user: User
) -> None:
    r = admin_client.put(f'{USERS_URL}/{user.id}', json={'email': admin_user.email})
    assert r.status_code == 409
    assert r.get_json() == EMAIL_IN_USE_ERROR
    assert user.email == 'user@test.com'


def test_update_to_another_users_email_in_another_case_conflicts(
    admin_client: FlaskClient, admin_user: User, user: User
) -> None:
    r = admin_client.put(
        f'{USERS_URL}/{user.id}', json={'email': admin_user.email.upper()}
    )
    assert r.status_code == 409
    assert r.get_json() == EMAIL_IN_USE_ERROR
    assert user.email == 'user@test.com'


def test_update_keeping_the_same_email_is_not_a_conflict(
    admin_client: FlaskClient, user: User
) -> None:
    r = admin_client.put(f'{USERS_URL}/{user.id}', json={'email': user.email})
    assert r.status_code == 200
    assert r.get_json()['email'] == 'user@test.com'


def test_update_unknown_field_is_unprocessable(
    admin_client: FlaskClient, user: User
) -> None:
    r = admin_client.put(f'{USERS_URL}/{user.id}', json={'nickname': 'x'})
    assert r.status_code == 422
    assert r.get_json() == {'error': 'Invalid request'}
