import dataclasses
import secrets
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
import responses
from flask import Flask, g
from flask.testing import FlaskClient
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select
from werkzeug.test import TestResponse

from src_back.models import AuditAction, AuditLog, OAuthAccount, Role, User
from src_back.services import oauth as oauth_service
from src_back.services.auth import LAST_METHOD, find_user_by_email
from src_back.services.oauth_providers import GOOGLE_TOKEN_URL
from src_back.services.oauth_state import (
    MAX_NEXT_LENGTH,
    SECURE_COOKIE_NAME,
    OAuthTransaction,
    code_challenge,
    read_transaction,
)
from src_back.tests.conftest import OAUTH_CLIENT_ID, OidcSigner
from src_back.tests.helpers import persist
from src_back.tests.software_authenticator import SoftwareAuthenticator

OAUTH_URL = '/api/v1/auth/oauth'
START_URL = f'{OAUTH_URL}/google/start'
CALLBACK_URL = f'{OAUTH_URL}/google/callback'
ACCOUNTS_URL = f'{OAUTH_URL}/accounts'
ORIGIN = 'https://app.test'
SAME_ORIGIN = {'Sec-Fetch-Site': 'same-origin'}
NEW_EMAIL = 'new@example.com'
VERIFIED: dict[str, Any] = {
    'email': NEW_EMAIL,
    'email_verified': True,
    'name': 'New Person',
}


def begin(
    client: FlaskClient, *, headers: dict[str, str] | None = None, **query: str
) -> dict[str, str]:
    response = client.get(START_URL, query_string=query, headers=headers or {})
    assert response.status_code == 302
    return dict(parse_qsl(urlsplit(response.headers['Location']).query))


def begin_link(client: FlaskClient) -> dict[str, str]:
    # What the Account page's Link button sends.
    return begin(client, headers=SAME_ORIGIN, link='1')


def answer_token_request(
    mocked_http: responses.RequestsMock,
    signer: OidcSigner,
    nonce: str,
    claims: dict[str, Any],
) -> None:
    id_token = signer.make_id_token({'nonce': nonce, **claims})
    mocked_http.add(
        responses.POST,
        GOOGLE_TOKEN_URL,
        json={'access_token': 'the-access-token', 'id_token': id_token},
    )


def run_callback(client: FlaskClient, params: dict[str, str]) -> TestResponse:
    return client.get(
        CALLBACK_URL, query_string={'code': 'the-code', 'state': params['state']}
    )


def sign_in(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    signer: OidcSigner,
    claims: dict[str, Any],
) -> TestResponse:
    params = begin(client)
    answer_token_request(mocked_http, signer, params['nonce'], claims)
    return run_callback(client, params)


def finish_link(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    signer: OidcSigner,
    claims: dict[str, Any],
) -> TestResponse:
    params = begin_link(client)
    answer_token_request(mocked_http, signer, params['nonce'], claims)
    return run_callback(client, params)


def transaction_in(app: Flask, client: FlaskClient) -> OAuthTransaction:
    cookie = client.get_cookie(SECURE_COOKIE_NAME)
    assert cookie is not None
    headers = {'Cookie': f'{SECURE_COOKIE_NAME}={cookie.value}'}
    with app.test_request_context('/', headers=headers):
        return read_transaction()


def redirect_location(response: TestResponse) -> str:
    assert response.status_code == 302
    return response.headers['Location']


def has_transaction_cookie(client: FlaskClient) -> bool:
    return client.get_cookie(SECURE_COOKIE_NAME) is not None


def token_request_body(mocked_http: responses.RequestsMock) -> dict[str, str]:
    call = next(
        call for call in mocked_http.calls if call.request.url == GOOGLE_TOKEN_URL
    )
    body = call.request.body
    assert isinstance(body, str)
    return dict(parse_qsl(body))


def set_cookie_attributes(response: TestResponse, name: str) -> dict[str, str | None]:
    header = next(
        header
        for header in response.headers.getlist('Set-Cookie')
        if header.startswith(f'{name}=')
    )
    attributes: dict[str, str | None] = {}
    for attribute in header.split('; ')[1:]:
        key, separator, value = attribute.partition('=')
        attributes[key.lower()] = value if separator else None
    return attributes


def me_from_the_session_cookie(client: FlaskClient) -> TestResponse:
    # The test app context is shared across client requests, so drop flask_login's
    # cached g._login_user to make /me read the session cookie.
    g.pop('_login_user', None)
    return client.get('/api/v1/auth/me')


def link_count(db: SQLAlchemy) -> int:
    return db.session.query(OAuthAccount).count()


def oauth_account_entry(db: SQLAlchemy) -> AuditLog:
    stmt = select(AuditLog).where(AuditLog.table_name == 'oauth_accounts')
    return db.session.scalars(stmt).one()


# /providers


def test_providers_lists_name_and_label(client: FlaskClient) -> None:
    response = client.get(f'{OAUTH_URL}/providers')
    assert response.status_code == 200
    assert response.get_json() == [{'name': 'google', 'label': 'Google'}]


def test_providers_is_empty_with_none_enabled(app: Flask, client: FlaskClient) -> None:
    app.config['OAUTH_PROVIDERS'] = {}
    assert client.get(f'{OAUTH_URL}/providers').get_json() == []


# start


def test_start_redirects_with_state_nonce_and_pkce(
    app: Flask, client: FlaskClient
) -> None:
    url = urlsplit(redirect_location(client.get(START_URL)))
    assert url.netloc == 'accounts.google.com'
    params = dict(parse_qsl(url.query))
    assert params['client_id'] == OAUTH_CLIENT_ID
    assert params['redirect_uri'] == f'{ORIGIN}/api/v1/auth/oauth/google/callback'
    assert params['scope'] == 'openid email profile'
    assert params['response_type'] == 'code'
    assert params['prompt'] == 'select_account'
    assert params['code_challenge_method'] == 'S256'
    transaction = transaction_in(app, client)
    assert params['state'] == transaction.state
    assert params['nonce'] == transaction.nonce
    assert transaction.code_verifier is not None
    assert params['code_challenge'] == code_challenge(transaction.code_verifier)


def test_start_sets_the_transaction_cookie(client: FlaskClient) -> None:
    attributes = set_cookie_attributes(client.get(START_URL), SECURE_COOKIE_NAME)
    assert attributes['samesite'] == 'None'
    assert 'secure' in attributes
    assert 'httponly' in attributes
    assert attributes['path'] == '/'
    assert attributes['max-age'] == '600'


def test_start_over_http_uses_a_lax_cookie(app: Flask, client: FlaskClient) -> None:
    app.config['PUBLIC_BASE_URL'] = 'http://localhost:5174'
    attributes = set_cookie_attributes(client.get(START_URL), 'oauth_txn')
    assert attributes['samesite'] == 'Lax'
    assert attributes['path'] == '/api/v1/auth/oauth'
    assert 'secure' not in attributes


def test_start_omits_pkce_for_a_provider_without_it(
    app: Flask,
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    providers = app.config['OAUTH_PROVIDERS']
    providers['google'] = dataclasses.replace(providers['google'], uses_pkce=False)
    params = begin(client)
    assert 'code_challenge' not in params
    assert 'code_challenge_method' not in params
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    assert redirect_location(run_callback(client, params)) == f'{ORIGIN}/'
    assert 'code_verifier' not in token_request_body(mocked_http)


def test_start_links_when_the_account_page_asks(
    app: Flask, auth_client: FlaskClient, user: User
) -> None:
    begin_link(auth_client)
    transaction = transaction_in(app, auth_client)
    assert transaction.link_user_id == user.id
    assert transaction.next_path == '/account'


def test_start_does_not_link_without_being_asked(
    app: Flask, auth_client: FlaskClient
) -> None:
    begin(auth_client, headers=SAME_ORIGIN)
    assert transaction_in(app, auth_client).link_user_id is None


@pytest.mark.parametrize(
    'fetch_site',
    ['cross-site', 'same-site', 'none', None],
    ids=['cross-site', 'same-site', 'none', 'no-header'],
)
def test_start_refuses_a_link_it_cannot_prove(
    auth_client: FlaskClient, fetch_site: str | None
) -> None:
    headers = {} if fetch_site is None else {'Sec-Fetch-Site': fetch_site}
    response = auth_client.get(START_URL, query_string={'link': '1'}, headers=headers)
    assert redirect_location(response) == f'{ORIGIN}/account?error=invalid_state'
    assert not has_transaction_cookie(auth_client)


def test_start_refuses_a_link_without_a_session(client: FlaskClient) -> None:
    # An Account tab left open after signing out elsewhere: the sign-in page says so.
    response = client.get(START_URL, query_string={'link': '1'}, headers=SAME_ORIGIN)
    assert redirect_location(response) == f'{ORIGIN}/login?error=invalid_state'
    assert not has_transaction_cookie(client)


def test_start_signs_in_an_anonymous_visitor(app: Flask, client: FlaskClient) -> None:
    begin(client)
    transaction = transaction_in(app, client)
    assert transaction.link_user_id is None
    assert transaction.next_path == '/'


def test_start_for_an_unknown_provider_redirects_to_login(client: FlaskClient) -> None:
    response = client.get(f'{OAUTH_URL}/nope/start')
    assert redirect_location(response) == f'{ORIGIN}/login?error=unknown_provider'


def test_unknown_provider_redirect_without_a_public_origin_stays_relative(
    app: Flask, client: FlaskClient
) -> None:
    app.config['PUBLIC_BASE_URL'] = None
    response = client.get(f'{OAUTH_URL}/nope/start')
    assert redirect_location(response) == '/login?error=unknown_provider'


def test_start_response_headers_fit_nginx_default_buffer(
    app: Flask, auth_client: FlaskClient
) -> None:
    # Random text, because zlib shrinks a repeated character to nothing.
    next_path = '/' + secrets.token_urlsafe(MAX_NEXT_LENGTH)[: MAX_NEXT_LENGTH - 1]
    response = auth_client.get(START_URL, query_string={'next': next_path})
    assert response.status_code == 302
    assert transaction_in(app, auth_client).next_path == next_path
    assert any(h.startswith('session=') for h in response.headers.getlist('Set-Cookie'))
    size = sum(len(name) + len(value) + 4 for name, value in response.headers.items())
    assert size < 3500


@pytest.mark.parametrize(
    ('next_path', 'landing'),
    [
        ('/?q=' + '\U0001f600' * 42, '/?q=' + '%F0%9F%98%80' * 42),
        ('/?q=' + '\U0001f600' * 400, '/'),
    ],
    ids=['longest-kept', 'too-long-once-encoded'],
)
def test_callback_response_headers_fit_nginx_default_buffer(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
    next_path: str,
    landing: str,
) -> None:
    # An emoji is one character in next and twelve in the redirect header.
    params = begin(client, next=next_path)
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    response = run_callback(client, params)
    assert redirect_location(response) == f'{ORIGIN}{landing}'
    size = sum(len(name) + len(value) + 4 for name, value in response.headers.items())
    assert size < 3500


# The linking policy, each through the real exchange and token check


def test_callback_creates_a_passwordless_account(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    response = sign_in(client, mocked_http, oidc_signer, VERIFIED)
    assert redirect_location(response) == f'{ORIGIN}/'
    # Only committed rows survive a rollback.
    db.session.rollback()
    created = find_user_by_email(NEW_EMAIL)
    assert created is not None
    assert created.role is Role.user
    assert created.is_active is True
    assert created.has_password is False
    assert link_count(db) == 1
    assert [account.provider for account in created.oauth_accounts] == ['google']
    assert created.oauth_accounts[0].email == NEW_EMAIL
    me = me_from_the_session_cookie(client)
    assert me.status_code == 200
    assert me.get_json()['email'] == NEW_EMAIL


def test_a_subject_matches_only_its_own_provider(
    client: FlaskClient,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    persist(OAuthAccount(user=user, provider='other', provider_user_id='google-subject'))
    response = sign_in(client, mocked_http, oidc_signer, VERIFIED)
    assert redirect_location(response) == f'{ORIGIN}/'
    created = find_user_by_email(NEW_EMAIL)
    assert created is not None
    assert created.id != user.id


def test_new_account_is_audited(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    sign_in(client, mocked_http, oidc_signer, VERIFIED)
    entries = db.session.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    assert [(entry.table_name, entry.action) for entry in entries] == [
        ('users', AuditAction.created),
        ('oauth_accounts', AuditAction.created),
    ]
    assert [entry.changed_by_id for entry in entries] == [None, None]
    assert entries[0].changes == {
        'email': NEW_EMAIL,
        'role': 'user',
        'is_active': True,
    }


def test_callback_signs_in_the_linked_account(
    client: FlaskClient,
    db: SQLAlchemy,
    linked_user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    claims = {'email': 'changed@example.com', 'email_verified': True}
    response = sign_in(client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/'
    assert link_count(db) == 1
    assert db.session.query(User).count() == 1
    assert me_from_the_session_cookie(client).get_json()['email'] == linked_user.email


def test_callback_never_attaches_to_a_password_account(
    client: FlaskClient,
    db: SQLAlchemy,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    claims = {'email': user.email, 'email_verified': True}
    response = sign_in(client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/login?error=link_required'
    assert link_count(db) == 0
    assert me_from_the_session_cookie(client).status_code == 401


@pytest.mark.parametrize('has_password', [True, False], ids=['password', 'no-password'])
def test_the_constant_relaxes_that_refusal(
    client: FlaskClient,
    user: User,
    passwordless_user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
    monkeypatch: pytest.MonkeyPatch,
    *,
    has_password: bool,
) -> None:
    monkeypatch.setattr(oauth_service, 'AUTO_LINK_BY_EMAIL', True)
    account = user if has_password else passwordless_user
    claims = {'email': account.email, 'email_verified': True}
    response = sign_in(client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/'
    assert [link.provider for link in account.oauth_accounts] == ['google']


def test_callback_never_attaches_to_a_passwordless_account(
    client: FlaskClient,
    db: SQLAlchemy,
    passwordless_user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    claims = {'email': passwordless_user.email, 'email_verified': True}
    response = sign_in(client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/login?error=link_required'
    # Only committed rows survive a rollback.
    db.session.rollback()
    assert link_count(db) == 0
    assert me_from_the_session_cookie(client).status_code == 401


def test_an_unlinked_provider_cannot_relink_itself(
    client: FlaskClient,
    db: SQLAlchemy,
    linked_user: User,
    authenticator: SoftwareAuthenticator,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    # A passkey keeps the account reachable once Google goes.
    persist(authenticator.credential_for(linked_user))
    assert (
        redirect_location(sign_in(client, mocked_http, oidc_signer, {})) == f'{ORIGIN}/'
    )
    assert client.delete(f'{ACCOUNTS_URL}/google').status_code == 204
    assert client.post('/api/v1/auth/logout').status_code == 200
    claims = {'email': linked_user.email, 'email_verified': True}
    response = sign_in(client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/login?error=link_required'
    db.session.rollback()
    assert link_count(db) == 0
    assert me_from_the_session_cookie(client).status_code == 401


def test_a_second_identity_cannot_attach_by_email(
    client: FlaskClient,
    db: SQLAlchemy,
    linked_user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    claims = {
        'sub': 'another-subject',
        'email': linked_user.email,
        'email_verified': True,
    }
    response = sign_in(client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/login?error=link_required'
    assert link_count(db) == 1


@pytest.mark.parametrize('email_verified', [False, 'false'], ids=['false', 'text-false'])
def test_an_unverified_email_is_refused(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
    *,
    email_verified: bool | str,
) -> None:
    claims = {**VERIFIED, 'email_verified': email_verified}
    response = sign_in(client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/login?error=email_unverified'
    assert db.session.query(User).count() == 0


def test_an_unverified_email_never_matches_an_account(
    client: FlaskClient,
    db: SQLAlchemy,
    passwordless_user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    claims = {'email': passwordless_user.email, 'email_verified': False}
    response = sign_in(client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/login?error=email_unverified'
    assert link_count(db) == 0


def test_a_missing_email_is_refused(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    response = sign_in(client, mocked_http, oidc_signer, {'email_verified': True})
    assert redirect_location(response) == f'{ORIGIN}/login?error=email_required'


def test_a_deactivated_linked_account_is_refused(
    client: FlaskClient,
    db: SQLAlchemy,
    linked_user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    linked_user.is_active = False
    db.session.commit()
    response = sign_in(client, mocked_http, oidc_signer, {})
    assert redirect_location(response) == f'{ORIGIN}/login?error=account_inactive'


def test_a_deactivated_passwordless_account_gains_no_link(
    client: FlaskClient,
    db: SQLAlchemy,
    passwordless_user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    passwordless_user.is_active = False
    db.session.commit()
    claims = {'email': passwordless_user.email, 'email_verified': True}
    response = sign_in(client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/login?error=link_required'
    assert link_count(db) == 0


def test_a_signed_in_visitor_on_the_sign_in_page_signs_in(
    auth_client: FlaskClient,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    response = sign_in(auth_client, mocked_http, oidc_signer, VERIFIED)
    assert redirect_location(response) == f'{ORIGIN}/'
    assert user.oauth_accounts == []
    created = find_user_by_email(NEW_EMAIL)
    assert created is not None
    assert [account.provider for account in created.oauth_accounts] == ['google']
    assert me_from_the_session_cookie(auth_client).get_json()['email'] == NEW_EMAIL


def test_a_lost_race_is_already_linked(
    client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist(User(email=NEW_EMAIL, role=Role.user))
    # The other request inserted the account after this one looked for it.
    monkeypatch.setattr(oauth_service, 'find_user_by_email', lambda _email: None)
    response = sign_in(client, mocked_http, oidc_signer, VERIFIED)
    assert redirect_location(response) == f'{ORIGIN}/login?error=already_linked'
    # Only the rollback leaves the session usable for another query.
    assert db.session.query(User).count() == 1
    assert link_count(db) == 0


# Link mode


def test_linking_attaches_to_the_signed_in_account(
    auth_client: FlaskClient,
    db: SQLAlchemy,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    response = finish_link(auth_client, mocked_http, oidc_signer, VERIFIED)
    assert redirect_location(response) == f'{ORIGIN}/account'
    # Only committed rows survive a rollback.
    db.session.rollback()
    assert [account.provider for account in user.oauth_accounts] == ['google']
    entry = oauth_account_entry(db)
    assert entry.action is AuditAction.created
    assert entry.changed_by_id == user.id


def test_linking_works_without_the_session_cookie(
    auth_client: FlaskClient,
    db: SQLAlchemy,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    params = begin_link(auth_client)
    # What a SameSite=Strict session cookie does on the provider's redirect back.
    auth_client.delete_cookie('session')
    g.pop('_login_user', None)
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    response = run_callback(auth_client, params)
    assert redirect_location(response) == f'{ORIGIN}/account'
    assert [account.provider for account in user.oauth_accounts] == ['google']
    assert oauth_account_entry(db).changed_by_id is None
    assert me_from_the_session_cookie(auth_client).get_json()['email'] == user.email


@pytest.mark.parametrize(
    'claims',
    [{'email': 'other@example.com', 'email_verified': False}, {}],
    ids=['unverified', 'missing'],
)
def test_linking_ignores_the_email(
    auth_client: FlaskClient,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
    claims: dict[str, Any],
) -> None:
    response = finish_link(auth_client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/account'
    assert [account.provider for account in user.oauth_accounts] == ['google']


@pytest.mark.usefixtures('linked_user')
def test_linking_an_identity_another_account_holds_is_refused(
    auth_client: FlaskClient,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    response = finish_link(auth_client, mocked_http, oidc_signer, {})
    assert redirect_location(response) == f'{ORIGIN}/account?error=already_linked'
    assert user.oauth_accounts == []


def test_linking_the_same_identity_again_changes_nothing(
    auth_client: FlaskClient,
    db: SQLAlchemy,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    persist(OAuthAccount(user=user, provider='google', provider_user_id='google-subject'))
    response = finish_link(auth_client, mocked_http, oidc_signer, {})
    assert redirect_location(response) == f'{ORIGIN}/account'
    assert link_count(db) == 1


def test_linking_a_second_identity_of_a_provider_is_refused(
    auth_client: FlaskClient,
    db: SQLAlchemy,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    persist(OAuthAccount(user=user, provider='google', provider_user_id='google-subject'))
    claims = {'sub': 'another-subject'}
    response = finish_link(auth_client, mocked_http, oidc_signer, claims)
    assert redirect_location(response) == f'{ORIGIN}/account?error=already_linked'
    assert link_count(db) == 1


def test_linking_to_a_deactivated_account_is_refused(
    auth_client: FlaskClient,
    db: SQLAlchemy,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    params = begin_link(auth_client)
    user.is_active = False
    db.session.commit()
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    response = run_callback(auth_client, params)
    assert redirect_location(response) == f'{ORIGIN}/account?error=account_inactive'
    assert link_count(db) == 0


def test_linking_to_a_deleted_account_is_refused(
    auth_client: FlaskClient,
    db: SQLAlchemy,
    user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    params = begin_link(auth_client)
    db.session.delete(user)
    db.session.commit()
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    response = run_callback(auth_client, params)
    assert redirect_location(response) == f'{ORIGIN}/account?error=account_inactive'
    # The code is spent, so the transaction ends.
    assert not has_transaction_cookie(auth_client)


def test_logout_stops_a_link_in_progress(
    auth_client: FlaskClient,
    db: SQLAlchemy,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    params = begin_link(auth_client)
    assert auth_client.post('/api/v1/auth/logout').status_code == 200
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    response = run_callback(auth_client, params)
    assert redirect_location(response) == f'{ORIGIN}/login?error=expired'
    assert link_count(db) == 0


# Failures another site can cause leave the sign-in in progress


def test_callback_for_an_unknown_provider(client: FlaskClient) -> None:
    params = begin(client)
    response = client.get(
        f'{OAUTH_URL}/nope/callback',
        query_string={'code': 'the-code', 'state': params['state']},
    )
    assert redirect_location(response) == f'{ORIGIN}/login?error=unknown_provider'
    assert has_transaction_cookie(client)


def test_callback_without_a_cookie_is_expired(client: FlaskClient) -> None:
    response = client.get(CALLBACK_URL, query_string={'code': 'the-code', 'state': 's'})
    assert redirect_location(response) == f'{ORIGIN}/login?error=expired'


@pytest.mark.parametrize('state', ['wrong-state', 'é'], ids=['wrong', 'non-ascii'])
def test_callback_with_the_wrong_state_is_invalid(
    client: FlaskClient, state: str
) -> None:
    begin(client)
    response = client.get(CALLBACK_URL, query_string={'code': 'the-code', 'state': state})
    assert redirect_location(response) == f'{ORIGIN}/login?error=invalid_state'
    assert has_transaction_cookie(client)


def test_callback_with_a_tampered_cookie_is_invalid(client: FlaskClient) -> None:
    params = begin(client)
    cookie = client.get_cookie(SECURE_COOKIE_NAME)
    assert cookie is not None
    replacement = 'A' if cookie.value[5] != 'A' else 'B'
    client.set_cookie(
        SECURE_COOKIE_NAME, f'{cookie.value[:5]}{replacement}{cookie.value[6:]}'
    )
    response = run_callback(client, params)
    assert redirect_location(response) == f'{ORIGIN}/login?error=invalid_state'
    assert has_transaction_cookie(client)


def test_callback_for_another_providers_transaction_is_invalid(
    app: Flask, client: FlaskClient
) -> None:
    providers = app.config['OAUTH_PROVIDERS']
    providers['other'] = dataclasses.replace(
        providers['google'], name='other', label='Other'
    )
    params = begin(client)
    response = client.get(
        f'{OAUTH_URL}/other/callback',
        query_string={'code': 'the-code', 'state': params['state']},
    )
    assert redirect_location(response) == f'{ORIGIN}/login?error=invalid_state'
    assert has_transaction_cookie(client)


def test_a_forged_callback_leaves_the_sign_in_in_progress(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    params = begin(client)
    forged = client.get(
        CALLBACK_URL, query_string={'code': 'forged-code', 'state': 'forged-state'}
    )
    assert redirect_location(forged) == f'{ORIGIN}/login?error=invalid_state'
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    assert redirect_location(run_callback(client, params)) == f'{ORIGIN}/'


def test_the_second_of_two_tabs_finishes(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    first = begin(client)
    second = begin(client)
    first_response = run_callback(client, first)
    assert redirect_location(first_response) == f'{ORIGIN}/login?error=invalid_state'
    answer_token_request(mocked_http, oidc_signer, second['nonce'], VERIFIED)
    assert redirect_location(run_callback(client, second)) == f'{ORIGIN}/'


def test_an_error_with_the_wrong_state_is_invalid_not_cancelled(
    client: FlaskClient,
) -> None:
    begin(client)
    response = client.get(
        CALLBACK_URL, query_string={'error': 'access_denied', 'state': 'wrong-state'}
    )
    assert redirect_location(response) == f'{ORIGIN}/login?error=invalid_state'
    assert has_transaction_cookie(client)


# The other failures end the transaction


def test_a_declined_consent_is_cancelled(
    client: FlaskClient, mocked_http: responses.RequestsMock
) -> None:
    params = begin(client)
    response = client.get(
        CALLBACK_URL, query_string={'error': 'access_denied', 'state': params['state']}
    )
    assert redirect_location(response) == f'{ORIGIN}/login?error=cancelled'
    assert not has_transaction_cookie(client)
    assert len(mocked_http.calls) == 0


def test_another_provider_error_is_exchange_failed(client: FlaskClient) -> None:
    params = begin(client)
    response = client.get(
        CALLBACK_URL, query_string={'error': 'server_error', 'state': params['state']}
    )
    assert redirect_location(response) == f'{ORIGIN}/login?error=exchange_failed'
    assert not has_transaction_cookie(client)


def test_a_callback_without_a_code_is_exchange_failed(
    client: FlaskClient, mocked_http: responses.RequestsMock
) -> None:
    params = begin(client)
    response = client.get(CALLBACK_URL, query_string={'state': params['state']})
    assert redirect_location(response) == f'{ORIGIN}/login?error=exchange_failed'
    assert not has_transaction_cookie(client)
    assert len(mocked_http.calls) == 0


def test_a_refused_code_is_exchange_failed(
    client: FlaskClient, mocked_http: responses.RequestsMock
) -> None:
    params = begin(client)
    mocked_http.add(
        responses.POST, GOOGLE_TOKEN_URL, status=400, json={'error': 'invalid_grant'}
    )
    response = run_callback(client, params)
    assert redirect_location(response) == f'{ORIGIN}/login?error=exchange_failed'
    assert not has_transaction_cookie(client)


def test_a_token_for_another_nonce_is_invalid_token(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    params = begin(client)
    answer_token_request(mocked_http, oidc_signer, 'another-nonce', VERIFIED)
    response = run_callback(client, params)
    assert redirect_location(response) == f'{ORIGIN}/login?error=invalid_token'
    assert not has_transaction_cookie(client)


# Transport


def test_callback_accepts_a_post_without_the_spa_header(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    params = begin(client)
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    client.environ_base.pop('HTTP_X_REQUESTED_WITH')
    response = client.post(
        CALLBACK_URL, data={'code': 'the-code', 'state': params['state']}
    )
    assert redirect_location(response) == f'{ORIGIN}/'
    assert me_from_the_session_cookie(client).get_json()['email'] == NEW_EMAIL


def test_callback_clears_the_transaction_cookie(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    response = sign_in(client, mocked_http, oidc_signer, VERIFIED)
    assert redirect_location(response) == f'{ORIGIN}/'
    assert not has_transaction_cookie(client)


def test_callback_sends_the_transactions_verifier(
    app: Flask,
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    params = begin(client)
    verifier = transaction_in(app, client).code_verifier
    assert verifier is not None
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    run_callback(client, params)
    assert token_request_body(mocked_http)['code_verifier'] == verifier


def test_next_is_honoured(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    params = begin(client, next='/widgets/1?tab=2#x')
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    response = run_callback(client, params)
    assert redirect_location(response) == f'{ORIGIN}/widgets/1?tab=2#x'


def test_next_is_sanitized(
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    params = begin(client, next='//evil.example')
    answer_token_request(mocked_http, oidc_signer, params['nonce'], VERIFIED)
    assert redirect_location(run_callback(client, params)) == f'{ORIGIN}/'


def test_callback_works_with_the_production_cookie_settings(
    app: Flask,
    client: FlaskClient,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    app.config.update(SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=True)
    response = sign_in(client, mocked_http, oidc_signer, VERIFIED)
    attributes = set_cookie_attributes(response, 'session')
    assert attributes['samesite'] == 'Strict'
    assert 'secure' in attributes
    assert me_from_the_session_cookie(client).status_code == 200


# Linked accounts


def test_accounts_needs_a_session(client: FlaskClient) -> None:
    assert client.get(ACCOUNTS_URL).status_code == 401


@pytest.mark.usefixtures('linked_user')
def test_accounts_lists_only_the_callers_links(
    auth_client: FlaskClient, user: User
) -> None:
    persist(
        OAuthAccount(
            user=user,
            provider='google',
            provider_user_id='user-subject',
            email=user.email,
        )
    )
    response = auth_client.get(ACCOUNTS_URL)
    assert response.status_code == 200
    items = response.get_json()
    assert [(item['provider'], item['email']) for item in items] == [
        ('google', user.email)
    ]
    assert all('provider_user_id' not in item for item in items)
    assert all('user_id' not in item for item in items)


def test_unlink_removes_the_link(
    auth_client: FlaskClient, db: SQLAlchemy, user: User
) -> None:
    persist(OAuthAccount(user=user, provider='google', provider_user_id='user-subject'))
    response = auth_client.delete(f'{ACCOUNTS_URL}/google')
    assert response.status_code == 204
    # Only committed rows survive a rollback.
    db.session.rollback()
    assert user.oauth_accounts == []
    entry = oauth_account_entry(db)
    assert entry.action is AuditAction.deleted
    assert entry.changed_by_id == user.id


def test_unlink_of_a_provider_not_linked_is_404(auth_client: FlaskClient) -> None:
    response = auth_client.delete(f'{ACCOUNTS_URL}/google')
    assert response.status_code == 404
    assert response.get_json() == {'error': 'That provider is not linked.'}


def test_unlink_of_the_last_method_is_409(
    client: FlaskClient,
    linked_user: User,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    # It has no password, so a provider callback is its only way in.
    assert (
        redirect_location(sign_in(client, mocked_http, oidc_signer, {})) == f'{ORIGIN}/'
    )
    response = client.delete(f'{ACCOUNTS_URL}/google')
    assert response.status_code == 409
    assert response.get_json() == {'error': LAST_METHOD}
    assert len(linked_user.oauth_accounts) == 1


def test_unlink_is_allowed_while_a_passkey_remains(
    client: FlaskClient,
    linked_user: User,
    authenticator: SoftwareAuthenticator,
    mocked_http: responses.RequestsMock,
    oidc_signer: OidcSigner,
) -> None:
    persist(authenticator.credential_for(linked_user))
    assert (
        redirect_location(sign_in(client, mocked_http, oidc_signer, {})) == f'{ORIGIN}/'
    )
    assert client.delete(f'{ACCOUNTS_URL}/google').status_code == 204


def test_unlink_needs_a_session(client: FlaskClient) -> None:
    assert client.delete(f'{ACCOUNTS_URL}/google').status_code == 401
