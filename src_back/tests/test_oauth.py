import logging
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
import requests
import responses
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

from src_back.models import OAuthAccount, User
from src_back.services.errors import OAuthError
from src_back.services.oauth import (
    build_authorize_url,
    exchange_code,
    list_accounts,
    resolve_user,
)
from src_back.services.oauth_providers import (
    APPLE_AUTHORIZE_URL,
    FACEBOOK_AUTHORIZE_URL,
    GOOGLE_AUTHORIZE_URL,
    GOOGLE_TOKEN_URL,
    OAuthIdentity,
    OAuthProvider,
    build_registry,
)
from src_back.services.oauth_state import code_challenge, new_transaction
from src_back.services.oidc import HTTP_TIMEOUT_SECONDS
from src_back.tests.conftest import (
    APPLE_CLIENT_ID,
    APPLE_ENVIRONMENT,
    FACEBOOK_CLIENT_ID,
    FACEBOOK_ENVIRONMENT,
    OAUTH_CLIENT_ID,
    OAUTH_ENVIRONMENT,
    PUBLIC_BASE_URL,
)
from src_back.tests.helpers import persist

REDIRECT_URI = f'{PUBLIC_BASE_URL}/api/v1/auth/oauth/google/callback'
APPLE_REDIRECT_URI = f'{PUBLIC_BASE_URL}/api/v1/auth/oauth/apple/callback'
FACEBOOK_REDIRECT_URI = f'{PUBLIC_BASE_URL}/api/v1/auth/oauth/facebook/callback'


def _google() -> OAuthProvider:
    return build_registry(OAUTH_ENVIRONMENT, PUBLIC_BASE_URL)['google']


def _token_request_body(mocked_http: responses.RequestsMock) -> dict[str, str]:
    body = mocked_http.calls[0].request.body
    assert isinstance(body, str)
    return dict(parse_qsl(body))


def test_authorize_url_carries_the_transaction() -> None:
    txn = new_transaction('google', uses_pkce=True, next_path='/', link_user_id=None)
    url = urlsplit(build_authorize_url(_google(), redirect_uri=REDIRECT_URI, txn=txn))
    assert f'{url.scheme}://{url.netloc}{url.path}' == GOOGLE_AUTHORIZE_URL
    assert txn.code_verifier is not None
    assert dict(parse_qsl(url.query)) == {
        'client_id': OAUTH_CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': txn.state,
        'nonce': txn.nonce,
        'prompt': 'select_account',
        'code_challenge': code_challenge(txn.code_verifier),
        'code_challenge_method': 'S256',
    }


def test_authorize_url_omits_pkce_without_a_verifier() -> None:
    txn = new_transaction('google', uses_pkce=False, next_path='/', link_user_id=None)
    url = urlsplit(build_authorize_url(_google(), redirect_uri=REDIRECT_URI, txn=txn))
    params = dict(parse_qsl(url.query))
    assert 'code_challenge' not in params
    assert 'code_challenge_method' not in params


def test_apples_authorize_url_asks_for_a_form_post_without_pkce() -> None:
    apple = build_registry(APPLE_ENVIRONMENT, PUBLIC_BASE_URL)['apple']
    txn = new_transaction('apple', uses_pkce=False, next_path='/', link_user_id=None)
    url = urlsplit(build_authorize_url(apple, redirect_uri=APPLE_REDIRECT_URI, txn=txn))
    assert f'{url.scheme}://{url.netloc}{url.path}' == APPLE_AUTHORIZE_URL
    assert dict(parse_qsl(url.query)) == {
        'client_id': APPLE_CLIENT_ID,
        'redirect_uri': APPLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'name email',
        'state': txn.state,
        'nonce': txn.nonce,
        'response_mode': 'form_post',
    }


def test_facebooks_authorize_url_asks_again_for_a_declined_email_without_pkce() -> None:
    facebook = build_registry(FACEBOOK_ENVIRONMENT, PUBLIC_BASE_URL)['facebook']
    txn = new_transaction('facebook', uses_pkce=False, next_path='/', link_user_id=None)
    url = urlsplit(
        build_authorize_url(facebook, redirect_uri=FACEBOOK_REDIRECT_URI, txn=txn)
    )
    assert f'{url.scheme}://{url.netloc}{url.path}' == FACEBOOK_AUTHORIZE_URL
    assert dict(parse_qsl(url.query)) == {
        'client_id': FACEBOOK_CLIENT_ID,
        'redirect_uri': FACEBOOK_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'public_profile email',
        'state': txn.state,
        'nonce': txn.nonce,
        'auth_type': 'rerequest',
    }


def test_exchange_posts_the_code_and_secret(mocked_http: responses.RequestsMock) -> None:
    mocked_http.add(responses.POST, GOOGLE_TOKEN_URL, json={'id_token': 'the-token'})
    tokens = exchange_code(
        _google(),
        code='the-code',
        redirect_uri=REDIRECT_URI,
        code_verifier='the-verifier',
    )
    assert tokens == {'id_token': 'the-token'}
    assert _token_request_body(mocked_http) == {
        'grant_type': 'authorization_code',
        'code': 'the-code',
        'redirect_uri': REDIRECT_URI,
        'client_id': OAUTH_CLIENT_ID,
        'client_secret': 'test-client-secret',
        'code_verifier': 'the-verifier',
    }
    # responses records the call's keyword arguments at runtime, untyped.
    request: Any = mocked_http.calls[0].request
    assert request.req_kwargs['timeout'] == HTTP_TIMEOUT_SECONDS


def test_exchange_omits_the_verifier_without_pkce(
    mocked_http: responses.RequestsMock,
) -> None:
    mocked_http.add(responses.POST, GOOGLE_TOKEN_URL, json={'id_token': 'the-token'})
    exchange_code(
        _google(), code='the-code', redirect_uri=REDIRECT_URI, code_verifier=None
    )
    assert 'code_verifier' not in _token_request_body(mocked_http)


EXCHANGE_FAILURES = {
    'refused': {'status': 400, 'json': {'error': 'invalid_grant'}},
    'not-json': {'body': 'not json'},
    'a-list': {'json': ['not', 'an', 'object']},
    'unreachable': {'body': requests.ConnectionError('unreachable')},
}


@pytest.mark.parametrize(
    'answer', EXCHANGE_FAILURES.values(), ids=EXCHANGE_FAILURES.keys()
)
def test_exchange_failures(
    mocked_http: responses.RequestsMock, answer: dict[str, Any]
) -> None:
    mocked_http.add(responses.POST, GOOGLE_TOKEN_URL, **answer)
    with pytest.raises(OAuthError) as excinfo:
        exchange_code(
            _google(), code='the-code', redirect_uri=REDIRECT_URI, code_verifier=None
        )
    assert excinfo.value.code == 'exchange_failed'


def test_a_refused_exchange_logs_without_the_secret(
    mocked_http: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    mocked_http.add(responses.POST, GOOGLE_TOKEN_URL, status=400, json={'error': 'x'})
    with (
        caplog.at_level(logging.WARNING, logger='src_back.services.oauth'),
        pytest.raises(OAuthError),
    ):
        exchange_code(
            _google(), code='the-code', redirect_uri=REDIRECT_URI, code_verifier=None
        )
    assert 'The token exchange with google failed' in caplog.text
    assert 'test-client-secret' not in caplog.text


def test_oauth_account_repr(app: Flask) -> None:
    account = OAuthAccount(provider='google', user_id=3)
    assert repr(account) == '<OAuthAccount google user=3>'


def test_a_long_display_name_is_cut_to_fit(app: Flask) -> None:
    identity = OAuthIdentity(
        provider='google',
        subject='google-subject',
        email='long@example.com',
        email_verified=True,
        display_name='n' * 300,
    )
    account = resolve_user(identity, link_user_id=None)
    assert account.oauth_accounts[0].display_name == 'n' * 255


def test_list_accounts_is_in_provider_order(user: User) -> None:
    persist(OAuthAccount(user=user, provider='zeta', provider_user_id='zeta-subject'))
    persist(OAuthAccount(user=user, provider='alpha', provider_user_id='alpha-subject'))
    assert [account.provider for account in list_accounts(user)] == ['alpha', 'zeta']


def test_an_account_links_each_provider_once(db: SQLAlchemy, linked_user: User) -> None:
    db.session.add(
        OAuthAccount(user=linked_user, provider='google', provider_user_id='another')
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_an_identity_links_to_one_account(
    db: SQLAlchemy, linked_user: User, user: User
) -> None:
    db.session.add(
        OAuthAccount(user=user, provider='google', provider_user_id='google-subject')
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
