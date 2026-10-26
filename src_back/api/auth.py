"""Session authentication routes: register, login, logout, and identity."""

from flask import Blueprint, Response, jsonify, session
from flask_login import login_required, logout_user

from src_back.auth import current_user
from src_back.schemas.user import login_schema, user_schema
from src_back.services.auth import authenticate_user, complete_login, register_user
from src_back.services.errors import DuplicateRecordError
from src_back.utils import ErrorResponse, conflict, parse_request_json, unauthorized

bp = Blueprint('auth', __name__)


@bp.post('/register')
def register() -> tuple[Response, int]:
    """Create an account and sign the new user in immediately.

    A payload that fails validation never reaches this body: ``parse_request_json``
    raises and the application answers with a 422 envelope.

    The new user is signed in through :func:`~src_back.services.auth.complete_login`,
    as in :func:`login`, so the session survives a browser restart.

    Returns:
        The serialized user with status 201, or a 409 envelope when the email is
        already registered in any letter case.
    """
    data = parse_request_json(user_schema)
    try:
        user = register_user(data['email'], data['password'])
    except DuplicateRecordError as exc:
        return conflict(str(exc))
    complete_login(user)
    return jsonify(user_schema.dump(user)), 201


@bp.post('/login')
def login() -> Response | ErrorResponse:
    """Verify credentials and start a session that survives a browser restart.

    :func:`~src_back.services.auth.complete_login` makes the session permanent, so
    its cookie carries an expiry ``SESSION_LIFETIME_DAYS`` out, and every later
    response pushes it forward.

    Returns:
        The serialized user on success, or a 401 envelope when the credentials
        do not match. The message does not distinguish an unknown email, an
        account without a password, and a wrong password.
    """
    data = parse_request_json(login_schema)
    user = authenticate_user(data['email'], data['password'])
    if not user:
        return unauthorized('Invalid email or password.')
    complete_login(user)
    return jsonify(user_schema.dump(user))


@bp.post('/logout')
@login_required
def logout() -> Response:
    """End the current session and delete its cookie.

    ``logout_user()`` removes only Flask-Login's keys, so clearing the session
    also drops the permanent flag that login set. Flask deletes the cookie of an
    emptied session instead of renewing it.

    Returns:
        A JSON confirmation message.
    """
    logout_user()
    session.clear()
    return jsonify({'message': 'Logged out.'})


@bp.get('/me')
@login_required
def me() -> Response:
    """Return the signed-in user, for rehydrating the client on page load.

    Returns:
        The serialized current user.
    """
    return jsonify(user_schema.dump(current_user))
