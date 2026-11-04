"""Passkeys: the two WebAuthn ceremonies and the signed-in account's passkeys.

The options routes are GETs: host nginx's sign-in throttle counts POSTs, and the sign-in
page asks for options on every visit, for its autofill. Each sets its ceremony's
challenge cookie (:mod:`src_back.services.passkey_state`) and leaves the session alone,
so its answer carries ``Cache-Control: no-store``, and each needs ``X-Requested-With``,
which ``src_back/app.py`` checks, so another site cannot reach one by navigation. Each
verify route clears its cookie on every answer it gives, which spends the challenge.
Without ``PUBLIC_BASE_URL`` the four ceremony routes answer 404, while listing, renaming,
and deleting still work. ``ai/auth.md`` walks through the flow.
"""

from functools import partial

from flask import Blueprint, Response, after_this_request, jsonify
from flask_login import login_required

from src_back.auth import current_user
from src_back.schemas.passkeys import (
    passkey_assertion_schema,
    passkey_register_schema,
    passkey_rename_schema,
    passkey_schema,
)
from src_back.schemas.user import user_schema
from src_back.services.auth import complete_login
from src_back.services.errors import (
    DuplicateRecordError,
    InactiveAccountError,
    LastSignInMethodError,
    PasskeyError,
)
from src_back.services.passkey_state import (
    ChallengeKind,
    clear_challenge_cookie,
    read_challenge_cookie,
    set_challenge_cookie,
)
from src_back.services.passkeys import (
    authentication_options,
    delete_passkey,
    list_passkeys,
    registration_options,
    rename_passkey,
    rp_settings,
    verify_authentication,
    verify_registration,
)
from src_back.utils import (
    ErrorResponse,
    bad_request,
    conflict,
    dump_or_404,
    forbidden,
    not_found,
    parse_request_json,
    unauthorized,
)

bp = Blueprint('passkeys', __name__)

DISABLED = 'Passkeys are not enabled.'
NOT_ACCEPTED = 'That passkey was not accepted.'


def _options_response(options_json: str, kind: ChallengeKind, token: str) -> Response:
    """Answer with a ceremony's options and its challenge cookie, which no cache may keep.

    Args:
        options_json: The options as py_webauthn serialized them.
        kind: The ceremony.
        token: The token that carries the options' challenge.

    Returns:
        The JSON response.
    """
    response = Response(options_json, mimetype='application/json')
    response.headers['Cache-Control'] = 'no-store'
    set_challenge_cookie(response, kind, token)
    return response


def _spend_challenge_on_any_answer(kind: ChallengeKind) -> None:
    """Clear a ceremony's challenge cookie on whatever answer this request ends with.

    Each verify route calls this before anything else, so a success, a refusal, and the
    422 that a body failing validation gets all spend the challenge, and the same answer
    posted again is refused.

    Args:
        kind: The ceremony being answered.
    """
    after_this_request(partial(clear_challenge_cookie, kind=kind))


@bp.get('/register/options')
@login_required
def register_options() -> Response | ErrorResponse:
    """Start adding a passkey to the signed-in account.

    Returns:
        The registration options, with their challenge cookie, or a 404 envelope when
        passkeys are off.
    """
    rp = rp_settings()
    if rp is None:
        return not_found(DISABLED)
    options_json, token = registration_options(current_user, rp)
    return _options_response(options_json, 'register', token)


@bp.post('/register/verify')
@login_required
def register_verify() -> tuple[Response, int]:
    """Finish adding a passkey with the browser's answer.

    A payload that fails validation never reaches the verification:
    ``parse_request_json`` raises and the application answers with a 422 envelope, which
    still clears the challenge cookie.

    Returns:
        The saved passkey with status 201; a 404 envelope when passkeys are off, a 400
        envelope when the request expired or the answer does not verify, or a 409
        envelope when the passkey is already registered.
    """
    _spend_challenge_on_any_answer('register')
    rp = rp_settings()
    if rp is None:
        return not_found(DISABLED)
    data = parse_request_json(passkey_register_schema)
    token = read_challenge_cookie('register')
    try:
        passkey = verify_registration(
            current_user, rp, data['credential'], data['nickname'], token
        )
    except PasskeyError as exc:
        return bad_request(str(exc))
    except DuplicateRecordError as exc:
        return conflict(str(exc))
    return jsonify(passkey_schema.dump(passkey)), 201


@bp.get('/login/options')
def login_options() -> Response | ErrorResponse:
    """Start a sign-in with any of the site's passkeys; open to anyone.

    Returns:
        The sign-in options, with their challenge cookie, or a 404 envelope when passkeys
        are off.
    """
    rp = rp_settings()
    if rp is None:
        return not_found(DISABLED)
    options_json, token = authentication_options(rp)
    return _options_response(options_json, 'login', token)


@bp.post('/login/verify')
def login_verify() -> Response | ErrorResponse:
    """Sign in with the passkey the browser chose, ending as password login does.

    Every answer, a 422 included, clears the sign-in's challenge cookie.

    Returns:
        The serialized user; a 404 envelope when passkeys are off; the same 401 envelope
        for every refusal; or a 403 envelope for a deactivated account, which only an
        answer that verified reaches.
    """
    _spend_challenge_on_any_answer('login')
    rp = rp_settings()
    if rp is None:
        return not_found(DISABLED)
    data = parse_request_json(passkey_assertion_schema)
    user = verify_authentication(rp, data['credential'], read_challenge_cookie('login'))
    if user is None:
        return unauthorized(NOT_ACCEPTED)
    try:
        complete_login(user)
    except InactiveAccountError as exc:
        return forbidden(str(exc))
    return jsonify(user_schema.dump(user))


@bp.get('')
@login_required
def list_account_passkeys() -> Response:
    """List the signed-in account's passkeys.

    Returns:
        Its passkeys, oldest first, without their key material.
    """
    return jsonify(passkey_schema.dump(list_passkeys(current_user), many=True))


@bp.put('/<int:passkey_id>')
@login_required
def rename_account_passkey(passkey_id: int) -> tuple[Response, int]:
    """Rename one of the signed-in account's passkeys.

    Args:
        passkey_id: The passkey's id.

    Returns:
        The renamed passkey, or a 404 envelope when the account has no such passkey.
    """
    data = parse_request_json(passkey_rename_schema)
    passkey = rename_passkey(current_user, passkey_id, data['nickname'])
    return dump_or_404(passkey, passkey_schema)


@bp.delete('/<int:passkey_id>')
@login_required
def delete_account_passkey(passkey_id: int) -> tuple[str, int] | ErrorResponse:
    """Delete one of the signed-in account's passkeys.

    Args:
        passkey_id: The passkey's id.

    Returns:
        An empty 204, a 404 envelope when the account has no such passkey, or a 409
        envelope when it is the account's last way to sign in.
    """
    try:
        removed = delete_passkey(current_user, passkey_id)
    except LastSignInMethodError as exc:
        return conflict(str(exc))
    if not removed:
        return not_found()
    return '', 204
