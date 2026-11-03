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
from src_back.services.auth import LAST_METHOD
from src_back.services.passkeys import (
    ALREADY_REGISTERED,
    CHALLENGE_TTL_SECONDS,
    EXPIRED,
    NOT_VERIFIED,
    REGISTER_CHALLENGE_KEY,
)
from src_back.tests.helpers import persist
from src_back.tests.software_authenticator import SoftwareAuthenticator

PASSKEYS_URL = '/api/v1/auth/passkeys'
REGISTER_OPTIONS_URL = f'{PASSKEYS_URL}/register/options'
REGISTER_VERIFY_URL = f'{PASSKEYS_URL}/register/verify'
LOGIN_OPTIONS_URL = f'{PASSKEYS_URL}/login/options'
LOGIN_VERIFY_URL = f'{PASSKEYS_URL}/login/verify'


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
    auth_client: FlaskClient, authenticator: SoftwareAuthenticator
) -> None:
    options = auth_client.get(REGISTER_OPTIONS_URL).get_json()
    with auth_client.session_transaction() as flask_session:
        pending = flask_session[REGISTER_CHALLENGE_KEY]
        issued_at = pending['issued_at'] - CHALLENGE_TTL_SECONDS - 1
        flask_session[REGISTER_CHALLENGE_KEY] = {**pending, 'issued_at': issued_at}
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


def test_a_spent_answer_is_refused(client: FlaskClient, passwordless_user: User) -> None:
    # Its counter cannot refuse a replay, so only the spent challenge can.
    authenticator = SoftwareAuthenticator(counter_step=0)
    persist(authenticator.credential_for(passwordless_user))
    options = client.get(LOGIN_OPTIONS_URL).get_json()
    body = {'credential': authenticator.get(options)}
    assert client.post(LOGIN_VERIFY_URL, json=body).status_code == 200
    assert client.post(LOGIN_VERIFY_URL, json=body).status_code == 401


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
