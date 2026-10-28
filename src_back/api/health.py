"""Unauthenticated liveness endpoint, which also names the deployment environment."""

from flask import Blueprint, Response, current_app, jsonify

bp = Blueprint('health', __name__)


@bp.get('/health')
def health() -> Response:
    """Report that the application is serving requests, and in which environment.

    Deliberately does not touch the database, so it stays a pure liveness
    signal rather than a readiness check. It answers without a session, so the
    sign-in page can show the environment badge too.

    Returns:
        A JSON body of ``{'status': 'ok', 'environment': <name>}``, where the name
        comes from ``APP_ENVIRONMENT`` and defaults to ``production``.
    """
    environment = current_app.config['APP_ENVIRONMENT']
    return jsonify({'status': 'ok', 'environment': environment})
