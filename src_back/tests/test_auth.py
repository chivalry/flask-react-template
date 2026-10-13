from flask.testing import FlaskClient

from src_back.models import User


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


def test_logout_unauthenticated(client: FlaskClient) -> None:
    r = client.post('/api/v1/auth/logout')
    assert r.status_code == 401


def test_me_authenticated(auth_client: FlaskClient, user: User) -> None:
    r = auth_client.get('/api/v1/auth/me')
    assert r.status_code == 200
    assert r.get_json()['email'] == user.email


def test_me_unauthenticated(client: FlaskClient) -> None:
    r = client.get('/api/v1/auth/me')
    assert r.status_code == 401
