from collections.abc import Callable
from typing import Any

import pytest
from flask import Flask, g
from flask.testing import FlaskClient
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select
from werkzeug.test import TestResponse

from src_back.models import AuditLog, User, WebAuthnCredential
from src_back.schemas.user import user_schema
from src_back.services import passkey_state
from src_back.services.auth import LAST_METHOD
from src_back.services.passkeys import ALREADY_REGISTERED, EXPIRED, NOT_VERIFIED
from src_back.tests.helpers import persist
from src_back.tests.software_authenticator import SoftwareAuthenticator

PASSKEYS_URL = '/api/v1/auth/passkeys'
REGISTER_OPTIONS_URL = f'{PASSKEYS_URL}/register/options'
REGISTER_VERIFY_URL = f'{PASSKEYS_URL}/register/verify'
LOGIN_OPTIONS_URL = f'{PASSKEYS_URL}/login/options'
LOGIN_VERIFY_URL = f'{PASSKEYS_URL}/login/verify'
REGISTER_COOKIE = '__Host-passkey_register'
LOGIN_COOKIE = '__Host-passkey_login'
EACH_OPTIONS_URL = pytest.mark.parametrize(
    'url', [REGISTER_OPTIONS_URL, LOGIN_OPTIONS_URL], ids=['register', 'login']
)


def register(
    client: FlaskClient,
    authenticator: SoftwareAuthenticator,
    nickname: str | None = None,
) -> TestResponse:
    options = client.get(REGISTER_OPTIONS_URL).get_json()
    body = {'credential': authenticator.create(options), 'nickname': nickname}
    return client.post(REGISTER_VERIFY_URL, json=body)


def sign_in_with(
    client: FlaskClient, authenticator: SoftwareAuthenticator
) -> TestResponse:
    options = client.get(LOGIN_OPTIONS_URL).get_json()
    return client.post(LOGIN_VERIFY_URL, json={'credential': authenticator.get(options)})


def me_from_the_session_cookie(client: FlaskClient) -> TestResponse:
    # The test app context is shared across client requests, so drop flask_login's
    # cached g._login_user to make /me read the session cookie.
    g.pop('_login_user', None)
    return client.get('/api/v1/auth/me')


def passkey_entry(db: SQLAlchemy) -> AuditLog:
    stmt = select(AuditLog).where(AuditLog.table_name == 'webauthn_credentials')
    return db.session.scalars(stmt).one()


def listed_ids(client: FlaskClient) -> list[int]:
    return [item['id'] for item in client.get(PASSKEYS_URL).get_json()]


def set_cookie_headers(response: TestResponse, name: str) -> list[str]:
    return [
        header
        for header in response.headers.getlist('Set-Cookie')
        if header.startswith(f'{name}=')
    ]


def set_cookie_attributes(response: TestResponse, name: str) -> dict[str, str | None]:
    [header] = set_cookie_headers(response, name)
    attributes: dict[str, str | None] = {}
    for attribute in header.split('; ')[1:]:
        key, separator, value = attribute.partition('=')
        attributes[key.lower()] = value if separator else None
    return attributes


# Adding a passkey


def test_register_options_need_a_session(client: FlaskClient) -> None:
    assert client.get(REGISTER_OPTIONS_URL).status_code == 401


@pytest.mark.parametrize('url', [REGISTER_OPTIONS_URL, LOGIN_OPTIONS_URL])
def test_options_are_json_no_cache_keeps(auth_client: FlaskClient, url: str) -> None:
    response = auth_client.get(url)
    assert response.status_code == 200
    assert response.mimetype == 'application/json'
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.get_json()['challenge']


def test_register_verify_answers_201_with_the_passkey(
    auth_client: FlaskClient,
    db: SQLAlchemy,
    user: User,
    authenticator: SoftwareAuthenticator,
) -> None:
    response = register(auth_client, authenticator, 'Laptop')
    assert response.status_code == 201
    body = response.get_json()
    assert set(body) == {
        'id',
        'uuid',
        'nickname',
        'transports',
        'aaguid',
        'backup_eligible',
        'backup_state',
        'last_used_at',
        'created_at',
        'updated_at',
    }
    assert body['nickname'] == 'Laptop'
    assert body['last_used_at'] is None
    assert [passkey.id for passkey in user.passkeys] == [body['id']]
    assert passkey_entry(db).changed_by_id == user.id


@pytest.mark.parametrize(
    ('nickname', 'saved'),
    [('  Laptop  ', 'Laptop'), ('   ', None)],
    ids=['padded', 'blank'],
)
def test_register_verify_trims_the_nickname(
    auth_client: FlaskClient,
    db: SQLAlchemy,
    user: User,
    authenticator: SoftwareAuthenticator,
    nickname: str,
    saved: str | None,
) -> None:
    assert register(auth_client, authenticator, nickname).status_code == 201
    # Only committed rows survive a rollback.
    db.session.rollback()
    assert [passkey.nickname for passkey in user.passkeys] == [saved]


def test_register_verify_answers_400_for_an_expired_request(
    auth_client: FlaskClient,
    authenticator: SoftwareAuthenticator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = auth_client.get(REGISTER_OPTIONS_URL).get_json()
    monkeypatch.setattr(passkey_state, 'CHALLENGE_TTL_SECONDS', -1)
    body = {'credential': authenticator.create(options)}
    response = auth_client.post(REGISTER_VERIFY_URL, json=body)
    assert response.status_code == 400
    assert response.get_json() == {'error': EXPIRED}


def test_register_verify_answers_400_for_an_answer_that_does_not_verify(
    auth_client: FlaskClient, authenticator: SoftwareAuthenticator
) -> None:
    options = auth_client.get(REGISTER_OPTIONS_URL).get_json()
    body = {'credential': authenticator.create(options, origin='https://evil.test')}
    response = auth_client.post(REGISTER_VERIFY_URL, json=body)
    assert response.status_code == 400
    assert response.get_json() == {'error': NOT_VERIFIED}


def test_register_verify_answers_409_for_a_registered_passkey(
    auth_client: FlaskClient, authenticator: SoftwareAuthenticator
) -> None:
    assert register(auth_client, authenticator).status_code == 201
    response = register(auth_client, authenticator)
    assert response.status_code == 409
    assert response.get_json() == {'error': ALREADY_REGISTERED}


@pytest.mark.parametrize(
    'body',
    [
        {},
        {'credential': None},
        {'credential': 'text'},
        {'credential': {}, 'nickname': 'x' * 65},
        {'credential': {}, 'role': 'admin'},
    ],
    ids=['empty', 'null', 'text', 'long-nickname', 'unknown-field'],
)
def test_register_verify_validates_the_body(
    auth_client: FlaskClient, body: dict[str, Any]
) -> None:
    assert auth_client.post(REGISTER_VERIFY_URL, json=body).status_code == 422


def test_register_verify_needs_a_session(client: FlaskClient) -> None:
    response = client.post(REGISTER_VERIFY_URL, json={'credential': {}})
    assert response.status_code == 401


def test_ceremonies_answer_404_without_a_public_base_url(
    app: Flask, auth_client: FlaskClient
) -> None:
    app.config['PUBLIC_BASE_URL'] = None
    answers = [
        auth_client.get(REGISTER_OPTIONS_URL),
        auth_client.post(REGISTER_VERIFY_URL, json={'credential': {}}),
        auth_client.get(LOGIN_OPTIONS_URL),
        auth_client.post(LOGIN_VERIFY_URL, json={'credential': {}}),
    ]
    for response in answers:
        assert response.status_code == 404
        assert response.get_json() == {'error': 'Passkeys are not enabled.'}
    assert auth_client.get(PASSKEYS_URL).status_code == 200


# Signing in with a passkey


def test_login_options_are_open_to_anyone(client: FlaskClient) -> None:
    assert client.get(LOGIN_OPTIONS_URL).status_code == 200


def test_login_verify_signs_in(
    client: FlaskClient, passkey_user: User, authenticator: SoftwareAuthenticator
) -> None:
    response = sign_in_with(client, authenticator)
    assert response.status_code == 200
    assert response.get_json() == user_schema.dump(passkey_user)
    me = me_from_the_session_cookie(client)
    assert me.status_code == 200
    assert me.get_json()['id'] == passkey_user.id
    # complete_login makes the session permanent.
    cookie = client.get_cookie('session')
    assert cookie is not None
    assert cookie.expires is not None


def test_a_registered_passkey_signs_in(
    auth_client: FlaskClient, user: User, authenticator: SoftwareAuthenticator
) -> None:
    assert register(auth_client, authenticator).status_code == 201
    assert auth_client.post('/api/v1/auth/logout').status_code == 200
    response = sign_in_with(auth_client, authenticator)
    assert response.status_code == 200
    assert response.get_json()['id'] == user.id
    [item] = auth_client.get(PASSKEYS_URL).get_json()
    assert item['last_used_at'] is not None


def an_unknown_passkey(
    _authenticator: SoftwareAuthenticator, _other: User
) -> SoftwareAuthenticator:
    return SoftwareAuthenticator()


def another_accounts_user_handle(
    authenticator: SoftwareAuthenticator, other: User
) -> SoftwareAuthenticator:
    authenticator.user_handle = other.uuid.encode()
    return authenticator


REFUSED_PASSKEYS: dict[
    str, Callable[[SoftwareAuthenticator, User], SoftwareAuthenticator]
] = {
    'unknown-passkey': an_unknown_passkey,
    'another-user-handle': another_accounts_user_handle,
}


@pytest.mark.parametrize(
    'refused', REFUSED_PASSKEYS.values(), ids=REFUSED_PASSKEYS.keys()
)
@pytest.mark.usefixtures('passkey_user')
def test_login_verify_answers_401_alike(
    client: FlaskClient,
    user: User,
    authenticator: SoftwareAuthenticator,
    refused: Callable[[SoftwareAuthenticator, User], SoftwareAuthenticator],
) -> None:
    response = sign_in_with(client, refused(authenticator, user))
    assert response.status_code == 401
    assert response.get_json() == {'error': 'That passkey was not accepted.'}
    assert me_from_the_session_cookie(client).status_code == 401


def test_login_verify_answers_403_for_a_deactivated_account(
    client: FlaskClient, inactive_user: User, authenticator: SoftwareAuthenticator
) -> None:
    persist(authenticator.credential_for(inactive_user))
    response = sign_in_with(client, authenticator)
    assert response.status_code == 403
    assert response.get_json() == {'error': 'Account is inactive.'}
    assert me_from_the_session_cookie(client).status_code == 401


@pytest.mark.parametrize(
    'body', [{}, {'credential': []}], ids=['empty', 'credential-not-an-object']
)
def test_login_verify_validates_the_body(
    client: FlaskClient, body: dict[str, Any]
) -> None:
    assert client.post(LOGIN_VERIFY_URL, json=body).status_code == 422


# The challenge cookies


@pytest.mark.parametrize(
    ('origin', 'prefix', 'path'),
    [('https://app.test', '__Host-', '/'), ('http://localhost:5174', '', PASSKEYS_URL)],
    ids=['https', 'http'],
)
@pytest.mark.parametrize('kind', ['register', 'login'])
def test_options_set_their_challenge_cookie(
    app: Flask,
    auth_client: FlaskClient,
    origin: str,
    prefix: str,
    path: str,
    kind: str,
) -> None:
    app.config['PUBLIC_BASE_URL'] = origin
    response = auth_client.get(f'{PASSKEYS_URL}/{kind}/options')
    assert response.status_code == 200
    attributes = set_cookie_attributes(response, f'{prefix}passkey_{kind}')
    assert attributes['path'] == path
    assert ('secure' in attributes) is origin.startswith('https://')
    assert 'httponly' in attributes
    assert attributes['samesite'] == 'Strict'
    assert attributes['max-age'] == '300'


def test_login_options_leave_an_anonymous_session_alone(client: FlaskClient) -> None:
    response = client.get(LOGIN_OPTIONS_URL)
    assert response.status_code == 200
    assert set_cookie_headers(response, LOGIN_COOKIE) != []
    assert set_cookie_headers(response, 'session') == []


@pytest.mark.parametrize(
    ('first', 'status'),
    [('the-answer', 200), ('an-unknown-passkey', 401), ('no-credential', 422)],
)
def test_every_sign_in_answer_spends_the_challenge(
    client: FlaskClient, passwordless_user: User, first: str, status: int
) -> None:
    # Its counter cannot refuse a replay, so only the cleared cookie can.
    authenticator = SoftwareAuthenticator(counter_step=0)
    persist(authenticator.credential_for(passwordless_user))
    options = client.get(LOGIN_OPTIONS_URL).get_json()
    bodies: dict[str, dict[str, Any]] = {
        'the-answer': {'credential': authenticator.get(options)},
        'an-unknown-passkey': {'credential': SoftwareAuthenticator().get(options)},
        'no-credential': {},
    }
    response = client.post(LOGIN_VERIFY_URL, json=bodies[first])
    assert response.status_code == status
    assert set_cookie_attributes(response, LOGIN_COOKIE)['max-age'] == '0'
    # The answer that signs in, refused once any answer has spent its challenge.
    assert client.post(LOGIN_VERIFY_URL, json=bodies['the-answer']).status_code == 401


@pytest.mark.parametrize(
    ('first', 'status'),
    [('the-answer', 201), ('another-origin', 400), ('no-credential', 422)],
)
def test_every_registration_answer_spends_the_challenge(
    auth_client: FlaskClient,
    authenticator: SoftwareAuthenticator,
    first: str,
    status: int,
) -> None:
    options = auth_client.get(REGISTER_OPTIONS_URL).get_json()
    evil = authenticator.create(options, origin='https://evil.test')
    bodies: dict[str, dict[str, Any]] = {
        'the-answer': {'credential': authenticator.create(options)},
        'another-origin': {'credential': evil},
        'no-credential': {},
    }
    response = auth_client.post(REGISTER_VERIFY_URL, json=bodies[first])
    assert response.status_code == status
    assert set_cookie_attributes(response, REGISTER_COOKIE)['max-age'] == '0'
    # The answer that registers, refused once any answer has spent its challenge.
    again = auth_client.post(REGISTER_VERIFY_URL, json=bodies['the-answer'])
    assert again.status_code == 400
    assert again.get_json() == {'error': EXPIRED}


@pytest.mark.parametrize('method', ['GET', 'HEAD'])
@EACH_OPTIONS_URL
def test_options_need_the_requested_with_header(
    client: FlaskClient, url: str, method: str
) -> None:
    # As a navigation from another site arrives: no header, and no Strict session cookie.
    client.environ_base.pop('HTTP_X_REQUESTED_WITH')
    response = client.open(url, method=method)
    assert response.status_code == 403
    assert 'Set-Cookie' not in response.headers


@EACH_OPTIONS_URL
def test_an_options_request_needs_no_requested_with_header(
    client: FlaskClient, url: str
) -> None:
    client.environ_base.pop('HTTP_X_REQUESTED_WITH')
    assert client.options(url).status_code == 200


def test_an_options_answer_that_left_before_a_sign_in_keeps_it(
    client: FlaskClient, user: User
) -> None:
    body = {'email': user.email, 'password': 'password123'}
    assert client.post('/api/v1/auth/login', json=body).status_code == 200
    signed_in = client.get_cookie('session')
    assert signed_in is not None
    # The renewal left before the sign-in answered, so it carried no session cookie.
    client.delete_cookie('session')
    assert client.get(LOGIN_OPTIONS_URL).status_code == 200
    # Its answer lands last: the browser keeps the sign-in's cookie unless it replaces it.
    late = client.get_cookie('session')
    client.set_cookie('session', (late or signed_in).value)
    assert me_from_the_session_cookie(client).status_code == 200


# The signed-in account's passkeys


def test_list_needs_a_session(client: FlaskClient) -> None:
    assert client.get(PASSKEYS_URL).status_code == 401


@pytest.mark.usefixtures('passkey_user')
def test_list_shows_only_the_callers_passkeys(
    auth_client: FlaskClient, user: User
) -> None:
    mine = persist(SoftwareAuthenticator().credential_for(user))
    response = auth_client.get(PASSKEYS_URL)
    assert response.status_code == 200
    assert [item['id'] for item in response.get_json()] == [mine.id]


def test_rename_answers_200_with_the_new_nickname(
    auth_client: FlaskClient, user: User
) -> None:
    url = f'{PASSKEYS_URL}/{persist(SoftwareAuthenticator().credential_for(user)).id}'
    response = auth_client.put(url, json={'nickname': 'Phone'})
    assert response.status_code == 200
    assert response.get_json()['nickname'] == 'Phone'
    response = auth_client.put(url, json={'nickname': None})
    assert response.status_code == 200
    assert response.get_json()['nickname'] is None


def test_rename_of_another_accounts_passkey_is_404(
    auth_client: FlaskClient, passkey_user: User
) -> None:
    url = f'{PASSKEYS_URL}/{passkey_user.passkeys[0].id}'
    response = auth_client.put(url, json={'nickname': 'Mine now'})
    assert response.status_code == 404
    assert response.get_json() == {'error': 'Not found'}


@pytest.mark.parametrize(
    'body', [{}, {'nickname': 'x' * 65}], ids=['empty', 'long-nickname']
)
def test_rename_validates_the_body(
    auth_client: FlaskClient, user: User, body: dict[str, Any]
) -> None:
    url = f'{PASSKEYS_URL}/{persist(SoftwareAuthenticator().credential_for(user)).id}'
    assert auth_client.put(url, json=body).status_code == 422


def test_delete_answers_204(auth_client: FlaskClient, db: SQLAlchemy, user: User) -> None:
    passkey_id = persist(SoftwareAuthenticator().credential_for(user)).id
    response = auth_client.delete(f'{PASSKEYS_URL}/{passkey_id}')
    assert response.status_code == 204
    assert response.data == b''
    # Only committed rows survive a rollback.
    db.session.rollback()
    assert db.session.get(WebAuthnCredential, passkey_id) is None


def test_delete_of_another_accounts_passkey_is_404(
    auth_client: FlaskClient, db: SQLAlchemy, passkey_user: User
) -> None:
    passkey_id = passkey_user.passkeys[0].id
    response = auth_client.delete(f'{PASSKEYS_URL}/{passkey_id}')
    assert response.status_code == 404
    db.session.rollback()
    assert db.session.get(WebAuthnCredential, passkey_id) is not None


def test_delete_of_the_last_way_to_sign_in_is_409(
    client: FlaskClient, passkey_user: User, authenticator: SoftwareAuthenticator
) -> None:
    assert sign_in_with(client, authenticator).status_code == 200
    passkey_id = passkey_user.passkeys[0].id
    response = client.delete(f'{PASSKEYS_URL}/{passkey_id}')
    assert response.status_code == 409
    assert response.get_json() == {'error': LAST_METHOD}
    assert listed_ids(client) == [passkey_id]


def test_delete_needs_a_session(client: FlaskClient) -> None:
    assert client.delete(f'{PASSKEYS_URL}/1').status_code == 401
