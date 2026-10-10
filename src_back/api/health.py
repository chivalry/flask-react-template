"""Unauthenticated liveness endpoint."""

from flask import Blueprint, jsonify

bp = Blueprint('health', __name__)


@bp.get('/health')
def health():
    """Report that the application is serving requests.

    Deliberately does not touch the database, so it stays a pure liveness
    signal rather than a readiness check.

    Returns:
        A JSON body of ``{'status': 'ok'}``.
    """
    return jsonify({'status': 'ok'})
