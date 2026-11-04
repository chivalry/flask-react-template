import secrets

import pytest
from flask import Flask, Response
from itsdangerous import URLSafeTimedSerializer
from webauthn.helpers import bytes_to_base64url

from src_back.services import passkey_state
from src_back.services.passkey_state import (
    ChallengeKind,
    challenge_from_token,
    clear_challenge_cookie,
    new_challenge_token,
    read_challenge_cookie,
    set_challenge_cookie,
)
from src_back.tests.conftest import PUBLIC_BASE_URL

HTTP_ORIGIN = 'http://localhost:5174'
CHALLENGE = secrets.token_bytes(32)
CHALLENGE_TEXT = bytes_to_base64url(CHALLENGE)
KINDS: list[ChallengeKind] = ['register', 'login']
# Whom each kind's token names: the account adding a passkey, or nobody for a sign-in.
ACCOUNTS: dict[ChallengeKind, int | None] = {'register': 7, 'login': None}

EACH_KIND = pytest.mark.parametrize('kind', KINDS)
EACH_SCHEME = pytest.mark.parametrize(
    ('origin', 'prefix', 'path'),
    [(PUBLIC_BASE_URL, '__Host-', '/'), (HTTP_ORIGIN, '', '/api/v1/auth/passkeys')],
    ids=['https', 'http'],
)


def _parse_set_cookie(header: str) -> tuple[str, str, dict[str, str | None]]:
    pair, *attributes = header.split('; ')
    name, _, value = pair.partition('=')
    parsed: dict[str, str | None] = {}
    for attribute in attributes:
        key, separator, attribute_value = attribute.partition('=')
        parsed[key.lower()] = attribute_value if separator else None
    return name, value, parsed


def _set_cookie_header(kind: ChallengeKind, token: str) -> str:
    response = Response()
    set_challenge_cookie(response, kind, token)
    return response.headers['Set-Cookie']


def _signed(app: Flask, kind: ChallengeKind, payload: object) -> str:
    # Signed as passkey_state signs, so only the payload can be wrong.
    secret_key = app.config['SECRET_KEY']
    return URLSafeTimedSerializer(secret_key, salt=f'passkey-{kind}').dumps(payload)


@EACH_SCHEME
@EACH_KIND
def test_a_challenge_round_trips_through_its_cookie(
    app: Flask, origin: str, prefix: str, path: str, kind: ChallengeKind
) -> None:
    app.config['PUBLIC_BASE_URL'] = origin
    token = new_challenge_token(kind, CHALLENGE, user_id=ACCOUNTS[kind])
    name, value, _ = _parse_set_cookie(_set_cookie_header(kind, token))
    with app.test_request_context(path, headers={'Cookie': f'{name}={value}'}):
        read = read_challenge_cookie(kind)
    assert read == token
    assert challenge_from_token(kind, read, user_id=ACCOUNTS[kind]) == CHALLENGE


@pytest.mark.parametrize('user_id', [7, None], ids=['an-account', 'no-account'])
@pytest.mark.parametrize(
    ('kind', 'other'), [('register', 'login'), ('login', 'register')], ids=KINDS
)
def test_a_token_passes_only_as_its_own_kind(
    app: Flask, kind: ChallengeKind, other: ChallengeKind, user_id: int | None
) -> None:
    # The same account argument both ways, so only the salt tells the kinds apart.
    token = new_challenge_token(kind, CHALLENGE, user_id=user_id)
    assert challenge_from_token(other, token, user_id=user_id) is None


@pytest.mark.parametrize('answering', [8, None], ids=['another-account', 'no-account'])
def test_a_token_passes_only_for_its_own_account(
    app: Flask, answering: int | None
) -> None:
    token = new_challenge_token('register', CHALLENGE, user_id=7)
    assert challenge_from_token('register', token, user_id=answering) is None


def test_an_expired_token_is_refused(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    token = new_challenge_token('login', CHALLENGE, user_id=None)
    monkeypatch.setattr(passkey_state, 'CHALLENGE_TTL_SECONDS', -1)
    assert challenge_from_token('login', token, user_id=None) is None


def test_a_bad_signature_is_refused(app: Flask) -> None:
    token = new_challenge_token('login', CHALLENGE, user_id=None)
    replacement = 'A' if token[5] != 'A' else 'B'
    tampered = f'{token[:5]}{replacement}{token[6:]}'
    assert challenge_from_token('login', tampered, user_id=None) is None
    app.config['SECRET_KEY'] = 'another-secret'
    assert challenge_from_token('login', token, user_id=None) is None


def test_a_missing_token_is_refused(app: Flask) -> None:
    assert challenge_from_token('login', None, user_id=None) is None


@pytest.mark.parametrize(
    'payload',
    [
        # The field names alone, which a check of the names without the type would pass.
        ['challenge', 'user_id'],
        CHALLENGE_TEXT,
        {'challenge': CHALLENGE_TEXT},
        {'user_id': None},
        {'challenge': CHALLENGE_TEXT, 'user_id': None, 'issued_at': 0},
        # A number whose text is base64url.
        {'challenge': 1234, 'user_id': None},
        {'challenge': 'A', 'user_id': None},
    ],
    ids=[
        'list',
        'text',
        'no-account',
        'no-challenge',
        'another-field',
        'challenge-not-text',
        'challenge-not-base64url',
    ],
)
def test_a_payload_of_another_shape_is_refused(app: Flask, payload: object) -> None:
    # The payload new_challenge_token signs passes, so the salt here is the real one.
    signed = _signed(app, 'login', {'challenge': CHALLENGE_TEXT, 'user_id': None})
    assert challenge_from_token('login', signed, user_id=None) == CHALLENGE
    token = _signed(app, 'login', payload)
    assert challenge_from_token('login', token, user_id=None) is None


@EACH_SCHEME
@EACH_KIND
def test_the_cookie_attributes(
    app: Flask, origin: str, prefix: str, path: str, kind: ChallengeKind
) -> None:
    app.config['PUBLIC_BASE_URL'] = origin
    name, value, attributes = _parse_set_cookie(_set_cookie_header(kind, 'the-token'))
    assert name == f'{prefix}passkey_{kind}'
    assert value == 'the-token'
    assert attributes['path'] == path
    assert ('secure' in attributes) is origin.startswith('https://')
    assert 'httponly' in attributes
    assert attributes['samesite'] == 'Strict'
    assert attributes['max-age'] == '300'
    assert 'domain' not in attributes


@EACH_SCHEME
@EACH_KIND
def test_a_clear_matches_the_cookie(
    app: Flask, origin: str, prefix: str, path: str, kind: ChallengeKind
) -> None:
    app.config['PUBLIC_BASE_URL'] = origin
    response = Response()
    assert clear_challenge_cookie(response, kind) is response
    name, _, attributes = _parse_set_cookie(response.headers['Set-Cookie'])
    assert name == f'{prefix}passkey_{kind}'
    assert attributes['max-age'] == '0'
    assert attributes['path'] == path
    # A browser refuses a __Host- cookie without Secure, a deletion included.
    assert ('secure' in attributes) is origin.startswith('https://')
