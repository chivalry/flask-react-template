from datetime import UTC, datetime, timedelta

import flask_login
from flask import g
from flask.testing import FlaskClient

from src_back import auth
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


def test_register_cannot_choose_a_role(client: FlaskClient) -> None:
    r = client.post(
        '/api/v1/auth/register',
        json={'email': 'x@example.com', 'password': 'secure123', 'role': 'admin'},
    )
    assert r.status_code == 422


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


def test_logout_unauthenticated(client: FlaskClient) -> None:
    r = client.post('/api/v1/auth/logout')
    assert r.status_code == 401


def test_me_authenticated(auth_client: FlaskClient, user: User) -> None:
    r = auth_client.get('/api/v1/auth/me')
    assert r.status_code == 200
    assert r.get_json()['email'] == user.email


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
