import pytest
from flask import Flask, Response
from itsdangerous import URLSafeTimedSerializer

from src_back.services.errors import OAuthError
from src_back.services.oauth_state import (
    COOKIE_NAME,
    MAX_NEXT_LENGTH,
    SECURE_COOKIE_NAME,
    OAuthTransaction,
    clear_transaction_cookie,
    code_challenge,
    new_transaction,
    read_transaction,
    safe_next,
    set_transaction_cookie,
    state_matches,
)

HTTP_ORIGIN = 'http://localhost:5174'
DEFAULT_PATH = '/default'
# é is six characters percent-encoded, so this fills the limit exactly once encoded.
LONGEST_ENCODED_NEXT = (
    '/' + 'é' * ((MAX_NEXT_LENGTH - 1) // 6) + 'a' * ((MAX_NEXT_LENGTH - 1) % 6)
)


def _transaction() -> OAuthTransaction:
    return new_transaction('google', uses_pkce=True, next_path='/widgets', link_user_id=7)


def _set_cookie_header(transaction: OAuthTransaction) -> str:
    response = Response()
    set_transaction_cookie(response, transaction)
    return response.headers['Set-Cookie']


def _cleared_cookie_header() -> str:
    response = Response()
    clear_transaction_cookie(response)
    return response.headers['Set-Cookie']


def _parse_set_cookie(header: str) -> tuple[str, str, dict[str, str | None]]:
    pair, *attributes = header.split('; ')
    name, _, value = pair.partition('=')
    parsed: dict[str, str | None] = {}
    for attribute in attributes:
        key, separator, attribute_value = attribute.partition('=')
        parsed[key.lower()] = attribute_value if separator else None
    return name, value, parsed


def _signed_value(transaction: OAuthTransaction) -> str:
    return _parse_set_cookie(_set_cookie_header(transaction))[1]


def _read(app: Flask, cookie: str | None, max_age: int | None = None) -> OAuthTransaction:
    headers = {} if cookie is None else {'Cookie': cookie}
    with app.test_request_context('/', headers=headers):
        if max_age is None:
            return read_transaction()
        return read_transaction(max_age=max_age)


def _read_error(app: Flask, cookie: str | None, max_age: int | None = None) -> str:
    with pytest.raises(OAuthError) as excinfo:
        _read(app, cookie, max_age)
    return excinfo.value.code


def test_new_transaction_makes_fresh_values() -> None:
    first = new_transaction('google', uses_pkce=True, next_path='/', link_user_id=None)
    second = new_transaction('google', uses_pkce=True, next_path='/', link_user_id=None)
    assert first.state != second.state
    assert first.nonce != second.nonce
    assert first.code_verifier != second.code_verifier
    assert first.code_verifier is not None
    assert 43 <= len(first.code_verifier) <= 128


def test_new_transaction_has_no_verifier_without_pkce() -> None:
    transaction = new_transaction(
        'google', uses_pkce=False, next_path='/', link_user_id=None
    )
    assert transaction.code_verifier is None


def test_code_challenge_matches_the_rfc_7636_example() -> None:
    verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
    assert code_challenge(verifier) == 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'


def test_state_matches() -> None:
    transaction = _transaction()
    assert state_matches(transaction, transaction.state) is True
    assert state_matches(transaction, 'another-state') is False
    assert state_matches(transaction, 'é') is False


def test_transaction_round_trips_through_the_cookie(app: Flask) -> None:
    transaction = _transaction()
    cookie = f'{SECURE_COOKIE_NAME}={_signed_value(transaction)}'
    assert _read(app, cookie) == transaction


def test_cookie_is_host_prefixed_over_https(app: Flask) -> None:
    name, _, attributes = _parse_set_cookie(_set_cookie_header(_transaction()))
    assert name == '__Host-oauth_txn'
    assert attributes['samesite'] == 'None'
    assert 'secure' in attributes
    assert 'httponly' in attributes
    assert attributes['path'] == '/'
    assert attributes['max-age'] == '600'
    assert 'domain' not in attributes


def test_cookie_keeps_its_plain_name_over_http(app: Flask) -> None:
    app.config['PUBLIC_BASE_URL'] = HTTP_ORIGIN
    name, _, attributes = _parse_set_cookie(_set_cookie_header(_transaction()))
    assert name == 'oauth_txn'
    assert attributes['path'] == '/api/v1/auth/oauth'
    assert attributes['samesite'] == 'Lax'
    assert 'secure' not in attributes


def test_the_plain_name_is_ignored_over_https(app: Flask) -> None:
    cookie = f'{COOKIE_NAME}={_signed_value(_transaction())}'
    assert _read_error(app, cookie) == 'expired'


def test_a_missing_cookie_is_expired(app: Flask) -> None:
    assert _read_error(app, None) == 'expired'


def test_a_signature_past_its_age_is_expired(app: Flask) -> None:
    cookie = f'{SECURE_COOKIE_NAME}={_signed_value(_transaction())}'
    assert _read_error(app, cookie, max_age=-1) == 'expired'


def test_a_tampered_cookie_is_invalid_state(app: Flask) -> None:
    value = _signed_value(_transaction())
    replacement = 'A' if value[5] != 'A' else 'B'
    cookie = f'{SECURE_COOKIE_NAME}={value[:5]}{replacement}{value[6:]}'
    assert _read_error(app, cookie) == 'invalid_state'


def test_a_cookie_signed_with_another_secret_is_invalid_state(app: Flask) -> None:
    cookie = f'{SECURE_COOKIE_NAME}={_signed_value(_transaction())}'
    app.config['SECRET_KEY'] = 'another-secret'
    assert _read_error(app, cookie) == 'invalid_state'


def test_a_cookie_from_an_older_release_is_invalid_state(app: Flask) -> None:
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='oauth-txn')
    cookie = f'{SECURE_COOKIE_NAME}={serializer.dumps({"unexpected": 1})}'
    assert _read_error(app, cookie) == 'invalid_state'


def test_clear_transaction_cookie_deletes_it_over_https(app: Flask) -> None:
    name, _, attributes = _parse_set_cookie(_cleared_cookie_header())
    assert name == SECURE_COOKIE_NAME
    assert attributes['max-age'] == '0'
    assert attributes['path'] == '/'
    assert 'secure' in attributes


def test_clear_transaction_cookie_deletes_it_over_http(app: Flask) -> None:
    app.config['PUBLIC_BASE_URL'] = HTTP_ORIGIN
    name, _, attributes = _parse_set_cookie(_cleared_cookie_header())
    assert name == COOKIE_NAME
    assert attributes['max-age'] == '0'
    assert attributes['path'] == '/api/v1/auth/oauth'


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (None, DEFAULT_PATH),
        ('', DEFAULT_PATH),
        ('/', '/'),
        ('/a/b?c=1#d', '/a/b?c=1#d'),
        ('//evil.example', DEFAULT_PATH),
        ('/\\evil.example', DEFAULT_PATH),
        ('https://evil.example', DEFAULT_PATH),
        ('javascript:alert(1)', DEFAULT_PATH),
        ('evil', DEFAULT_PATH),
        ('/\t/evil.example', DEFAULT_PATH),
        ('/a\nb', DEFAULT_PATH),
        ('/a\x7fb', DEFAULT_PATH),
        ('/' + 'a' * (MAX_NEXT_LENGTH - 1), '/' + 'a' * (MAX_NEXT_LENGTH - 1)),
        ('/' + 'a' * MAX_NEXT_LENGTH, DEFAULT_PATH),
        (LONGEST_ENCODED_NEXT, LONGEST_ENCODED_NEXT),
        (LONGEST_ENCODED_NEXT + 'a', DEFAULT_PATH),
        ('//[evil.example', DEFAULT_PATH),
    ],
    ids=[
        'none',
        'empty',
        'root',
        'path-query-fragment',
        'protocol-relative',
        'slash-backslash',
        'absolute-url',
        'javascript',
        'no-leading-slash',
        'tab',
        'newline',
        'delete-character',
        'longest-kept',
        'one-too-long',
        'longest-kept-encoded',
        'one-too-long-encoded',
        'malformed-host',
    ],
)
def test_safe_next(value: str | None, expected: str) -> None:
    assert safe_next(value, DEFAULT_PATH) == expected
