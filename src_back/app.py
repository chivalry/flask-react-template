"""Application factory, error handlers, and static-file serving.

The built frontend is served from the same origin as the API: unmatched
non-API paths fall through to the SPA shell so client-side routing works on a
hard refresh.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_login import login_required
from marshmallow import ValidationError
from werkzeug.exceptions import NotFound

from src_back.extensions import db, login_manager, migrate
from src_back.models import User

load_dotenv()

_log = logging.getLogger(__name__)

MAX_UPLOAD_MB = 25

_PLACEHOLDER_SECRET_KEYS = frozenset(
    {'dev-secret', 'change-me', 'change-me-in-production'}
)

_JSON_PATH_PREFIXES = ('/api', '/uploads')

_JSON_ERROR_MESSAGES = {
    400: 'Bad request',
    401: 'Unauthorized',
    403: 'Forbidden',
    413: f'File is too large. Maximum size is {MAX_UPLOAD_MB} MB.',
    500: 'Internal server error',
}


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    """Reload the signed-in user from the id stored in the session cookie.

    Args:
        user_id: The user's primary key, as a string from the session.

    Returns:
        The matching user, or ``None`` if the account no longer exists.
    """
    return db.session.get(User, int(user_id))


@login_manager.unauthorized_handler
def unauthorized_handler() -> tuple[Response, int]:
    """Answer unauthenticated requests with JSON instead of a redirect.

    Returns:
        A JSON error envelope with status 401.
    """
    return jsonify({'error': 'Unauthorized'}), 401


def create_app(config_overrides: dict[str, Any] | None = None) -> Flask:
    """Build and configure the Flask application.

    Args:
        config_overrides: Settings applied after the environment is read; the
            test suite uses this to enable testing mode and point at an
            in-memory database.

    Returns:
        The configured application, with extensions initialized, blueprints
        registered, and error handlers attached.
    """
    app = Flask(__name__, static_folder='../dist', static_url_path='/')

    _configure_application(app)
    if config_overrides:
        app.config.update(config_overrides)
    _guard_secret_key(app)
    _initialize_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_static_routes(app)

    return app


def _configure_application(app: Flask) -> None:
    """Read configuration from the environment onto the application.

    Development-friendly defaults keep the app starting with no ``.env``
    present. Uploads are resolved to an absolute path and capped at
    ``MAX_UPLOAD_MB``.

    Args:
        app: The application being configured.
    """
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', 'sqlite:///dev.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get(
        'SESSION_COOKIE_SAMESITE', 'Lax'
    )
    app.config['SESSION_COOKIE_SECURE'] = (
        os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    )
    app.config['UPLOAD_FOLDER'] = str(
        Path(os.environ.get('UPLOAD_FOLDER', 'src_back/uploads')).resolve()
    )
    app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024


def _guard_secret_key(app: Flask) -> None:
    """Refuse to start with a placeholder secret outside development.

    Args:
        app: The application being configured.

    Raises:
        RuntimeError: If ``FLASK_ENV`` is not ``development``, the app is not in
            testing mode, and ``SECRET_KEY`` is one of the shipped placeholders.
    """
    if os.environ.get('FLASK_ENV') == 'development' or app.config.get('TESTING'):
        return
    if app.config['SECRET_KEY'] in _PLACEHOLDER_SECRET_KEYS:
        raise RuntimeError(
            'SECRET_KEY must be set to a secure value outside development.'
        )


def _initialize_extensions(app: Flask) -> None:
    """Bind the shared extension singletons to this application.

    Args:
        app: The application being configured.
    """
    db.init_app(app)
    # Importing the models registers them on the shared metadata so that
    # ``db.create_all()`` and ``flask db migrate`` see every table.
    from src_back import models  # noqa: F401

    migrate.init_app(app, db)
    allowed_origins = os.environ.get('CORS_ALLOWED_ORIGINS', '*').split(',')
    CORS(app, origins=allowed_origins, supports_credentials=True)
    login_manager.init_app(app)


def _register_blueprints(app: Flask) -> None:
    """Register the API blueprints under their URL prefixes.

    The import is deferred into this function because the api package imports
    back through the models and extensions this module also wires up.

    Args:
        app: The application being configured.
    """
    from src_back.api import auth_bp, health_bp

    app.register_blueprint(health_bp, url_prefix='/api')
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')


def _build_json_error_handler(
    status_code: int, message: str
) -> Callable[[Exception], tuple[Response, int]]:
    """Create a handler that answers one status code with a JSON envelope.

    This is a factory rather than a closure defined inside the registration
    loop so that each handler captures its own status code and message instead
    of the loop's final values.

    Args:
        status_code: The HTTP status the handler should return.
        message: The message to place in the JSON error envelope.

    Returns:
        A Flask error handler bound to ``status_code``.
    """

    def handle_error(_e: Exception) -> tuple[Response, int]:
        """Return the JSON error envelope for this status code.

        Args:
            _e: The werkzeug exception instance. Unused.

        Returns:
            A JSON error envelope with the configured status.
        """
        return jsonify({'error': message}), status_code

    return handle_error


def _handle_validation_error(error: ValidationError) -> tuple[Response, int]:
    """Answer a failed request-body validation with a 422 envelope.

    Raised by :func:`src_back.utils.parse_request_json`. Field-level details are
    logged at debug level rather than returned, which keeps the error envelope
    uniform; clients enforce the same rules before submitting.

    Args:
        error: The marshmallow error carrying the per-field messages.

    Returns:
        A JSON error envelope with status 422.
    """
    _log.debug('Request validation error: %s', error.messages)
    return jsonify({'error': 'Invalid request'}), 422


def _is_json_path(path: str) -> bool:
    """Decide whether an unmatched path belongs to the API or the upload store.

    Matching whole path segments keeps client routes that merely start with the
    same letters, such as ``/api-docs`` or ``/uploads-gallery``, on the SPA shell.

    Args:
        path: The request path.

    Returns:
        ``True`` for ``/api``, ``/uploads``, and anything beneath them.
    """
    return any(
        path == prefix or path.startswith(prefix + '/') for prefix in _JSON_PATH_PREFIXES
    )


def _register_error_handlers(app: Flask) -> None:
    """Attach the JSON error handlers and the SPA fallthrough for 404.

    Args:
        app: The application being configured.
    """
    for status_code, message in _JSON_ERROR_MESSAGES.items():
        app.register_error_handler(
            status_code, _build_json_error_handler(status_code, message)
        )
    app.register_error_handler(ValidationError, _handle_validation_error)

    @app.errorhandler(404)
    def not_found_handler(_e: Exception) -> Response | tuple[Response, int]:
        """Serve JSON for unknown API paths and the SPA shell otherwise.

        This is what makes client-side routes survive a hard refresh: an
        unmatched browser path returns the app shell rather than a 404, so the
        router can resolve it. API and upload paths keep the real 404.

        Args:
            _e: The werkzeug exception instance. Unused.

        Returns:
            A JSON error envelope with status 404 for ``/api`` and ``/uploads``
            paths and their descendants, otherwise the built ``index.html``.
        """
        if _is_json_path(request.path):
            return jsonify({'error': 'Not found'}), 404
        return _serve_spa_shell(app)


def _register_static_routes(app: Flask) -> None:
    """Register the upload passthrough and the SPA entry route.

    Args:
        app: The application being configured.
    """

    @app.get('/uploads/<path:filename>')
    @login_required
    def serve_uploaded_file(filename: str) -> Response:
        """Serve an uploaded file to signed-in users only.

        Args:
            filename: Path of the file relative to ``UPLOAD_FOLDER``.

        Returns:
            The file response, or a 404 when no such file exists.
        """
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    @app.get('/')
    def index() -> Response | tuple[Response, int]:
        """Serve the built SPA shell at the site root.

        Returns:
            The built ``index.html`` from the static folder, or a JSON 404 when
            no frontend build is present.
        """
        return _serve_spa_shell(app)


def _serve_spa_shell(app: Flask) -> Response | tuple[Response, int]:
    """Serve the built single-page-app shell, or a JSON 404 when it is absent.

    The backend container ships without ``dist/``: in Docker the SPA comes from
    the Vite or nginx container instead. Without this guard the missing file
    would raise inside the 404 handler and surface as a 500.

    Args:
        app: The application whose static folder holds the frontend build.

    Returns:
        The built ``index.html``, or a JSON error envelope with status 404.
    """
    try:
        return app.send_static_file('index.html')
    except NotFound:
        return jsonify({'error': 'Not found'}), 404
