import logging
from pathlib import Path
from typing import NoReturn

import pytest
from flask import Blueprint, Flask, abort, g
from flask.testing import FlaskClient
from marshmallow import ValidationError

from src_back.app import MAX_UPLOAD_MB, create_app, load_user, unauthorized_handler
from src_back.models import User
from src_back.tests.conftest import PNG_BYTES


def test_unrouted_api_path_returns_json_not_found_error(client: FlaskClient) -> None:
    response = client.get('/api/does-not-exist')
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Not found'}


def test_unknown_client_route_serves_spa_index_fallback(
    app: Flask, tmp_path: Path
) -> None:
    static_dir = tmp_path / 'dist'
    static_dir.mkdir()
    (static_dir / 'index.html').write_text('<html>spa</html>')
    app.static_folder = str(static_dir)
    response = app.test_client().get('/some-client-route')
    assert response.status_code == 200
    assert response.get_data(as_text=True) == '<html>spa</html>'


def test_index_route_serves_static_folder_index_html(app: Flask, tmp_path: Path) -> None:
    static_dir = tmp_path / 'dist'
    static_dir.mkdir()
    (static_dir / 'index.html').write_text('<html>spa</html>')
    app.static_folder = str(static_dir)
    response = app.test_client().get('/')
    assert response.status_code == 200
    assert response.get_data(as_text=True) == '<html>spa</html>'


@pytest.mark.parametrize('path', ['/', '/some-client-route'])
def test_missing_frontend_build_returns_json_not_found(
    app: Flask, tmp_path: Path, path: str
) -> None:
    app.static_folder = str(tmp_path / 'no-build-here')
    response = app.test_client().get(path)
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Not found'}


@pytest.mark.parametrize('path', ['/api-docs', '/uploads-gallery'])
def test_lookalike_client_routes_serve_the_spa(
    app: Flask, tmp_path: Path, path: str
) -> None:
    static_dir = tmp_path / 'dist'
    static_dir.mkdir()
    (static_dir / 'index.html').write_text('<html>spa</html>')
    app.static_folder = str(static_dir)
    response = app.test_client().get(path)
    assert response.status_code == 200
    assert response.get_data(as_text=True) == '<html>spa</html>'


@pytest.mark.parametrize('path', ['/api', '/uploads', '/uploads/nested/missing.png'])
def test_bare_and_nested_json_prefixes_return_json_not_found(
    auth_client: FlaskClient, path: str
) -> None:
    response = auth_client.get(path)
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Not found'}


@pytest.mark.parametrize(
    ('status', 'message'),
    [(400, 'Bad request'), (401, 'Unauthorized'), (403, 'Forbidden')],
)
def test_abort_returns_json_error_envelope(app: Flask, status: int, message: str) -> None:
    bp = Blueprint(f'abort_{status}', __name__)

    @bp.get(f'/trigger-{status}')
    def trigger() -> NoReturn:
        abort(status)

    app.register_blueprint(bp)
    response = app.test_client().get(f'/trigger-{status}')
    assert response.status_code == status
    assert response.get_json() == {'error': message}


def test_unhandled_exception_returns_json_internal_server_error(app: Flask) -> None:
    bp = Blueprint('server_error_trigger', __name__)

    @bp.get('/trigger-server-error')
    def trigger_server_error() -> NoReturn:
        raise RuntimeError('deliberate failure for the 500 handler')

    app.register_blueprint(bp)
    app.config['PROPAGATE_EXCEPTIONS'] = False
    response = app.test_client().get('/trigger-server-error')
    assert response.status_code == 500
    assert response.get_json() == {'error': 'Internal server error'}


def test_validation_error_in_a_view_returns_json_unprocessable_entity(app: Flask) -> None:
    bp = Blueprint('validation_trigger', __name__)

    @bp.get('/trigger-validation-error')
    def trigger_validation_error() -> NoReturn:
        raise ValidationError({'name': ['Missing data for required field.']})

    app.register_blueprint(bp)
    response = app.test_client().get('/trigger-validation-error')
    assert response.status_code == 422
    assert response.get_json() == {'error': 'Invalid request'}


def test_oversized_request_body_returns_json_file_too_large(
    app: Flask, client: FlaskClient
) -> None:
    app.config['MAX_CONTENT_LENGTH'] = 100
    response = client.post(
        '/api/v1/auth/login',
        data=b'x' * 10_000,
        content_type='application/json',
    )
    assert response.status_code == 413
    assert response.get_json() == {
        'error': f'File is too large. Maximum size is {MAX_UPLOAD_MB} MB.'
    }


def test_user_loader_reloads_user_from_session(app: Flask, user: User) -> None:
    client = app.test_client()
    client.post(
        '/api/v1/auth/login',
        json={'email': user.email, 'password': 'password123'},
    )
    # The test app context is shared across client requests, so flask_login's
    # cached g._login_user would short-circuit the user_loader; drop the cache
    # to force the next request to reconstitute the user from the session.
    g.pop('_login_user', None)
    response = client.get('/api/v1/auth/me')
    assert response.status_code == 200
    assert response.get_json()['email'] == user.email


def test_load_user_returns_matching_user(app: Flask, user: User) -> None:
    loaded = load_user(str(user.id))
    assert loaded is not None
    assert loaded.id == user.id


def test_load_user_returns_none_for_missing_id(app: Flask) -> None:
    assert load_user('99999') is None


def test_unauthorized_handler_returns_json_401(app: Flask) -> None:
    with app.test_request_context('/'):
        response, status = unauthorized_handler()
    assert status == 401
    assert response.get_json() == {'error': 'Unauthorized'}


def test_uploads_unauthenticated_returns_unauthorized_json(client: FlaskClient) -> None:
    response = client.get('/uploads/x.png')
    assert response.status_code == 401
    assert response.get_json() == {'error': 'Unauthorized'}


def test_uploads_authenticated_serves_stored_file_bytes(
    app: Flask, auth_client: FlaskClient
) -> None:
    upload_folder = Path(app.config['UPLOAD_FOLDER'])
    upload_folder.mkdir(parents=True, exist_ok=True)
    (upload_folder / 'sample.png').write_bytes(PNG_BYTES)
    response = auth_client.get('/uploads/sample.png')
    assert response.status_code == 200
    assert response.data == PNG_BYTES


def test_uploads_missing_file_returns_json_not_found(auth_client: FlaskClient) -> None:
    response = auth_client.get('/uploads/missing.png')
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Not found'}


def test_upload_folder_is_resolved_to_an_absolute_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('UPLOAD_FOLDER', 'relative/uploads')
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    upload_folder = Path(app.config['UPLOAD_FOLDER'])
    assert upload_folder.is_absolute()
    assert upload_folder.parts[-2:] == ('relative', 'uploads')


def test_cors_allows_each_listed_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CORS_ALLOWED_ORIGINS', 'http://a.test,http://b.test')
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    response = app.test_client().get('/api/health', headers={'Origin': 'http://b.test'})
    assert response.headers['Access-Control-Allow-Origin'] == 'http://b.test'


def test_cors_rejects_an_unlisted_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CORS_ALLOWED_ORIGINS', 'http://a.test,http://b.test')
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    response = app.test_client().get(
        '/api/health', headers={'Origin': 'http://evil.test'}
    )
    assert 'Access-Control-Allow-Origin' not in response.headers


def test_create_app_rejects_placeholder_secret_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'change-me')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app()


def test_create_app_allows_placeholder_secret_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('SECRET_KEY', 'change-me')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    assert create_app().config['SECRET_KEY'] == 'change-me'


def test_create_app_allows_real_secret_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'a-long-random-secret')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    assert create_app().config['SECRET_KEY'] == 'a-long-random-secret'


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
