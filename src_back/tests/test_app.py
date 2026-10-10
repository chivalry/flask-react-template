import os

import pytest
from flask import Blueprint, abort, g
from marshmallow import ValidationError

from src_back.app import MAX_UPLOAD_MB, create_app, load_user, unauthorized_handler
from src_back.tests.conftest import PNG_BYTES


def test_unrouted_api_path_returns_json_not_found_error(client):
    response = client.get('/api/does-not-exist')
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Not found'}


def test_unknown_client_route_serves_spa_index_fallback(app, tmp_path):
    static_dir = tmp_path / 'dist'
    static_dir.mkdir()
    (static_dir / 'index.html').write_text('<html>spa</html>')
    app.static_folder = str(static_dir)
    response = app.test_client().get('/some-client-route')
    assert response.status_code == 200
    assert response.get_data(as_text=True) == '<html>spa</html>'


def test_index_route_serves_static_folder_index_html(app, tmp_path):
    static_dir = tmp_path / 'dist'
    static_dir.mkdir()
    (static_dir / 'index.html').write_text('<html>spa</html>')
    app.static_folder = str(static_dir)
    response = app.test_client().get('/')
    assert response.status_code == 200
    assert response.get_data(as_text=True) == '<html>spa</html>'


@pytest.mark.parametrize('path', ['/', '/some-client-route'])
def test_missing_frontend_build_returns_json_not_found(app, tmp_path, path):
    app.static_folder = str(tmp_path / 'no-build-here')
    response = app.test_client().get(path)
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Not found'}


@pytest.mark.parametrize('path', ['/api-docs', '/uploads-gallery'])
def test_lookalike_client_routes_serve_the_spa(app, tmp_path, path):
    static_dir = tmp_path / 'dist'
    static_dir.mkdir()
    (static_dir / 'index.html').write_text('<html>spa</html>')
    app.static_folder = str(static_dir)
    response = app.test_client().get(path)
    assert response.status_code == 200
    assert response.get_data(as_text=True) == '<html>spa</html>'


@pytest.mark.parametrize('path', ['/api', '/uploads', '/uploads/nested/missing.png'])
def test_bare_and_nested_json_prefixes_return_json_not_found(auth_client, path):
    response = auth_client.get(path)
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Not found'}


@pytest.mark.parametrize(
    ('status', 'message'),
    [(400, 'Bad request'), (401, 'Unauthorized'), (403, 'Forbidden')],
)
def test_abort_returns_json_error_envelope(app, status, message):
    bp = Blueprint(f'abort_{status}', __name__)

    @bp.get(f'/trigger-{status}')
    def trigger():
        abort(status)

    app.register_blueprint(bp)
    response = app.test_client().get(f'/trigger-{status}')
    assert response.status_code == status
    assert response.get_json() == {'error': message}


def test_unhandled_exception_returns_json_internal_server_error(app):
    bp = Blueprint('server_error_trigger', __name__)

    @bp.get('/trigger-server-error')
    def trigger_server_error():
        raise RuntimeError('deliberate failure for the 500 handler')

    app.register_blueprint(bp)
    app.config['PROPAGATE_EXCEPTIONS'] = False
    response = app.test_client().get('/trigger-server-error')
    assert response.status_code == 500
    assert response.get_json() == {'error': 'Internal server error'}


def test_validation_error_in_a_view_returns_json_unprocessable_entity(app):
    bp = Blueprint('validation_trigger', __name__)

    @bp.get('/trigger-validation-error')
    def trigger_validation_error():
        raise ValidationError({'name': ['Missing data for required field.']})

    app.register_blueprint(bp)
    response = app.test_client().get('/trigger-validation-error')
    assert response.status_code == 422
    assert response.get_json() == {'error': 'Invalid request'}


def test_oversized_request_body_returns_json_file_too_large(app, client):
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


def test_user_loader_reloads_user_from_session(app, user):
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


def test_load_user_returns_matching_user(app, user):
    loaded = load_user(str(user.id))
    assert loaded is not None
    assert loaded.id == user.id


def test_load_user_returns_none_for_missing_id(app):
    assert load_user('99999') is None


def test_unauthorized_handler_returns_json_401(app):
    with app.test_request_context('/'):
        response, status = unauthorized_handler()
    assert status == 401
    assert response.get_json() == {'error': 'Unauthorized'}


def test_uploads_unauthenticated_returns_unauthorized_json(client):
    response = client.get('/uploads/x.png')
    assert response.status_code == 401
    assert response.get_json() == {'error': 'Unauthorized'}


def test_uploads_authenticated_serves_stored_file_bytes(app, auth_client):
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    with open(os.path.join(app.config['UPLOAD_FOLDER'], 'sample.png'), 'wb') as f:
        f.write(PNG_BYTES)
    response = auth_client.get('/uploads/sample.png')
    assert response.status_code == 200
    assert response.data == PNG_BYTES


def test_uploads_missing_file_returns_json_not_found(auth_client):
    response = auth_client.get('/uploads/missing.png')
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Not found'}


def test_upload_folder_is_resolved_to_an_absolute_path(monkeypatch):
    monkeypatch.setenv('UPLOAD_FOLDER', 'relative/uploads')
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    assert os.path.isabs(app.config['UPLOAD_FOLDER'])
    assert app.config['UPLOAD_FOLDER'].endswith(os.path.join('relative', 'uploads'))


def test_cors_allows_each_listed_origin(monkeypatch):
    monkeypatch.setenv('CORS_ALLOWED_ORIGINS', 'http://a.test,http://b.test')
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    response = app.test_client().get('/api/health', headers={'Origin': 'http://b.test'})
    assert response.headers['Access-Control-Allow-Origin'] == 'http://b.test'


def test_cors_rejects_an_unlisted_origin(monkeypatch):
    monkeypatch.setenv('CORS_ALLOWED_ORIGINS', 'http://a.test,http://b.test')
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    response = app.test_client().get(
        '/api/health', headers={'Origin': 'http://evil.test'}
    )
    assert 'Access-Control-Allow-Origin' not in response.headers


def test_create_app_rejects_placeholder_secret_outside_development(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'change-me')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app()


def test_create_app_allows_placeholder_secret_in_development(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('SECRET_KEY', 'change-me')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    assert create_app().config['SECRET_KEY'] == 'change-me'


def test_create_app_allows_real_secret_outside_development(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'a-long-random-secret')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    assert create_app().config['SECRET_KEY'] == 'a-long-random-secret'
