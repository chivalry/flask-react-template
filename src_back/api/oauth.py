"""Sign-in through a provider: its two navigations, and the accounts linked through it.

``start`` and ``callback`` are browser navigations, not API calls, so every outcome is a
redirect rather than the JSON envelope. ``callback`` trusts only the signed transaction
cookie, because production's ``SameSite=Strict`` session cookie does not arrive with the
provider's redirect, and it takes GET and POST alike, because Sign in with Apple posts
its answer. ``ai/auth.md`` walks through the flow.
"""

from flask import Blueprint, Response, current_app, jsonify, redirect, request
from flask_login import login_required
from werkzeug.wrappers import Response as BaseResponse

from src_back.auth import current_user
from src_back.models import User
from src_back.schemas.oauth import oauth_account_schema, oauth_provider_schema
from src_back.services.auth import complete_login
from src_back.services.errors import (
    InactiveAccountError,
    LastSignInMethodError,
    OAuthError,
)
from src_back.services.oauth import (
    build_authorize_url,
    exchange_code,
    list_accounts,
    resolve_user,
    signed_in_user_id,
    unlink_account,
)
from src_back.services.oauth_providers import OAuthProvider, redirect_uri
from src_back.services.oauth_state import (
    OAuthTransaction,
    clear_transaction_cookie,
    new_transaction,
    read_transaction,
    safe_next,
    set_transaction_cookie,
    state_matches,
)
from src_back.utils import ErrorResponse, conflict, not_found

bp = Blueprint('oauth', __name__)

_ACCOUNT_PAGE = '/account'

_KEEPS_TRANSACTION = frozenset({'unknown_provider', 'expired', 'invalid_state'})
"""Failures another site can cause, which must not end a sign-in in progress."""


def _find_provider(provider_name: str) -> OAuthProvider | None:
    """Look up an enabled provider.

    Args:
        provider_name: The name in the URL.

    Returns:
        The provider, or ``None`` if none by that name is enabled.
    """
    return current_app.config['OAUTH_PROVIDERS'].get(provider_name)


def _public_redirect(path: str) -> BaseResponse:
    """Redirect to a path on the public origin.

    Args:
        path: The path, which starts with a slash.

    Returns:
        The redirect. With no ``PUBLIC_BASE_URL`` no provider is enabled, and the path
        alone still reaches the page that says so.
    """
    public_base_url = current_app.config['PUBLIC_BASE_URL'] or ''
    return redirect(f'{public_base_url}{path}')


def _error_redirect(code: str, *, link_mode: bool = False) -> BaseResponse:
    """Send the browser to the page that shows a failed sign-in.

    Args:
        code: The ``?error=`` value, which the page turns into a message.
        link_mode: Whether the failure belongs to linking, shown on the Account page.

    Returns:
        The redirect, which ends the transaction unless another site could have caused
        this failure.
    """
    page = _ACCOUNT_PAGE if link_mode else '/login'
    response = _public_redirect(f'{page}?error={code}')
    if code not in _KEEPS_TRANSACTION:
        clear_transaction_cookie(response)
    return response


@bp.get('/providers')
def providers() -> Response:
    """List the enabled providers, for the sign-in pages.

    Returns:
        Each provider's name and label; an empty list when none is enabled.
    """
    enabled = current_app.config['OAUTH_PROVIDERS'].values()
    return jsonify(oauth_provider_schema.dump(enabled, many=True))


def _link_user_id() -> int | None:
    """Find the account a navigation that asked to link can link to.

    A session alone is not consent: the sign-in pages stay open to a visitor with a live
    session, and a failed logout leaves one behind, so only the Account page asks.
    ``Sec-Fetch-Site`` keeps another site, a sibling host included, from asking under any
    ``SameSite`` setting.

    Returns:
        The signed-in account's id, or ``None`` if this navigation cannot link.
    """
    same_origin = request.headers.get('Sec-Fetch-Site') == 'same-origin'
    return signed_in_user_id() if same_origin else None


@bp.get('/<provider_name>/start')
def start(provider_name: str) -> BaseResponse:
    """Send the browser to the provider, remembering the sign-in in a signed cookie.

    A navigation that asks to link returns to the Account page by default. One that
    cannot link is refused, not run as a sign-in, which would leave the identity on a
    second account nothing can move it from. Any other is a sign-in, which replaces a
    session left open in the browser.

    Args:
        provider_name: The provider's registry name.

    Returns:
        A redirect to the provider, or to the page that shows a refusal.
    """
    provider = _find_provider(provider_name)
    if provider is None:
        return _error_redirect('unknown_provider')
    asked_to_link = request.args.get('link') == '1'
    link_user_id = _link_user_id() if asked_to_link else None
    if asked_to_link and link_user_id is None:
        # Without a session the Account page could only send the visitor to sign in.
        return _error_redirect('invalid_state', link_mode=signed_in_user_id() is not None)
    default_path = '/' if link_user_id is None else _ACCOUNT_PAGE
    transaction = new_transaction(
        provider.name,
        uses_pkce=provider.uses_pkce,
        next_path=safe_next(request.args.get('next'), default_path),
        link_user_id=link_user_id,
    )
    public_base_url = current_app.config['PUBLIC_BASE_URL']
    response = redirect(
        build_authorize_url(
            provider,
            redirect_uri=redirect_uri(public_base_url, provider.name),
            txn=transaction,
        )
    )
    set_transaction_cookie(response, transaction)
    return response


def _finish_sign_in(provider: OAuthProvider, transaction: OAuthTransaction) -> User:
    """Check the provider's answer and resolve it to an account.

    The state is compared before anything else in the answer is believed.

    Args:
        provider: The provider named in the URL.
        transaction: The transaction read from the cookie.

    Returns:
        The account to sign in.

    Raises:
        OAuthError: With ``invalid_state`` if the answer does not belong to this
            transaction, ``cancelled`` if the person declined at the provider, and
            ``exchange_failed`` if the provider reported any other failure.
    """
    state = request.values.get('state', '')
    if transaction.provider != provider.name or not state_matches(transaction, state):
        raise OAuthError('invalid_state')
    error = request.values.get('error')
    if error:
        raise OAuthError('cancelled' if error == 'access_denied' else 'exchange_failed')
    code = request.values.get('code')
    if not code:
        raise OAuthError('exchange_failed')
    tokens = exchange_code(
        provider,
        code=code,
        redirect_uri=redirect_uri(current_app.config['PUBLIC_BASE_URL'], provider.name),
        code_verifier=transaction.code_verifier,
    )
    identity = provider.fetch_identity(provider, tokens, transaction.nonce)
    return resolve_user(identity, link_user_id=transaction.link_user_id)


@bp.route('/<provider_name>/callback', methods=['GET', 'POST'])
def callback(provider_name: str) -> BaseResponse:
    """Finish a sign-in when the provider sends the browser back.

    The ``X-Requested-With`` hook exempts this route, because a provider may answer with
    a cross-site POST; the signed state protects it instead.

    Args:
        provider_name: The provider's registry name.

    Returns:
        A redirect to the transaction's return path, or to the page that shows the
        failure: the Account page when linking, otherwise the sign-in page.
    """
    provider = _find_provider(provider_name)
    if provider is None:
        return _error_redirect('unknown_provider')
    link_mode = False
    try:
        transaction = read_transaction()
        link_mode = transaction.link_user_id is not None
        complete_login(_finish_sign_in(provider, transaction))
    except OAuthError as exc:
        return _error_redirect(exc.code, link_mode=link_mode)
    except InactiveAccountError:
        return _error_redirect('account_inactive', link_mode=link_mode)
    response = _public_redirect(transaction.next_path)
    clear_transaction_cookie(response)
    return response


@bp.get('/accounts')
@login_required
def accounts() -> Response:
    """List the signed-in account's linked providers.

    Returns:
        The links, without the provider's subject.
    """
    return jsonify(oauth_account_schema.dump(list_accounts(current_user), many=True))


@bp.delete('/accounts/<provider_name>')
@login_required
def unlink(provider_name: str) -> tuple[str, int] | ErrorResponse:
    """Remove the signed-in account's link to a provider.

    Args:
        provider_name: The provider's registry name.

    Returns:
        An empty 204, a 404 envelope when no such link exists, or a 409 envelope when it
        is the account's last way to sign in.
    """
    try:
        removed = unlink_account(current_user, provider_name)
    except LastSignInMethodError as exc:
        return conflict(str(exc))
    if not removed:
        return not_found('That provider is not linked.')
    return '', 204
