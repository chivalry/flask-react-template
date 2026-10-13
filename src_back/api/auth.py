"""Session authentication routes: register, login, logout, and identity."""

from flask import Blueprint, Response, jsonify
from flask_login import current_user, login_required, login_user, logout_user

from src_back.schemas.user import login_schema, user_schema
from src_back.services.auth import authenticate_user, register_user
from src_back.utils import ErrorResponse, conflict, parse_request_json, unauthorized

bp = Blueprint('auth', __name__)


@bp.post('/register')
def register() -> tuple[Response, int]:
    """Create an account and sign the new user in immediately.

    A payload that fails validation never reaches this body: ``parse_request_json``
    raises and the application answers with a 422 envelope.

    Returns:
        The serialized user with status 201, or a 409 envelope when the email is
        already registered.
    """
    data = parse_request_json(user_schema)
    try:
        user = register_user(data['email'], data['password'])
    except ValueError as e:
        return conflict(str(e))
    login_user(user)
    return jsonify(user_schema.dump(user)), 201


@bp.post('/login')
def login() -> Response | ErrorResponse:
    """Verify credentials and start a session.

    Returns:
        The serialized user on success, or a 401 envelope when the credentials
        do not match. The message does not distinguish an unknown email from a
        wrong password.
    """
    data = parse_request_json(login_schema)
    user = authenticate_user(data['email'], data['password'])
    if not user:
        return unauthorized('Invalid email or password.')
    login_user(user)
    return jsonify(user_schema.dump(user))


@bp.post('/logout')
@login_required
def logout() -> Response:
    """End the current session.

    Returns:
        A JSON confirmation message.
    """
    logout_user()
    return jsonify({'message': 'Logged out.'})


@bp.get('/me')
@login_required
def me() -> Response:
    """Return the signed-in user, for rehydrating the client on page load.

    Returns:
        The serialized current user.
    """
    return jsonify(user_schema.dump(current_user))
