import hashlib
import hmac
import json
import logging
import time
from typing import Any

import pytest
import requests
import responses
from cryptography.hazmat.primitives.asymmetric import ec
from joserfc import jwt
from joserfc.jwk import ECKey, RSAKey

from src_back.services.errors import OAuthError
from src_back.services.oauth_providers import (
    APPLE_AUTHORIZE_URL,
    APPLE_ISSUER,
    APPLE_JWKS_URI,
    APPLE_KEYS,
    APPLE_TOKEN_URL,
    APPLE_USER_FIELD_LIMIT,
    FACEBOOK_AUTHORIZE_URL,
    FACEBOOK_GRAPH_VERSION,
    FACEBOOK_PROFILE_URL,
    FACEBOOK_TOKEN_URL,
    OAuthIdentity,
    OAuthProvider,
    apple_client_secret,
    apple_display_name,
    build_registry,
    id_token_claims,
    load_private_key,
    redirect_uri,
)
from src_back.services.oidc import HTTP_TIMEOUT_SECONDS
from src_back.tests.conftest import (
    APPLE_CLIENT_ID,
    APPLE_ENVIRONMENT,
    APPLE_ID_TOKEN_CLAIMS,
    APPLE_KEY_ID,
    APPLE_PRIVATE_KEY,
    APPLE_TEAM_ID,
    FACEBOOK_CLIENT_ID,
    FACEBOOK_CLIENT_SECRET,
    FACEBOOK_ENVIRONMENT,
    OAUTH_CLIENT_ID,
    OAUTH_ENVIRONMENT,
    PUBLIC_BASE_URL,
    OidcSigner,
)

NONCE = 'the-nonce'
LOGGER = 'src_back.services.oauth_providers'
APPLE_PEM = APPLE_ENVIRONMENT['OAUTH_APPLE_PRIVATE_KEY']
# Only the public half checks a secret, as at Apple.
APPLE_PUBLIC_KEY = ECKey.import_key(APPLE_PRIVATE_KEY.as_dict(private=False))
# Apple's first answer names the person; its email is not the token's.
FIRST_ANSWER = json.dumps(
    {
        'name': {'firstName': 'Maria', 'lastName': 'Ruiz'},
        'email': 'someone.else@example.com',
    }
)
FACEBOOK_ACCESS_TOKEN = 'the-access-token'
# The HMAC-SHA256 of FACEBOOK_ACCESS_TOKEN keyed with conftest's app secret, worked out
# with openssl: printf %s the-access-token | openssl dgst -sha256 -hmac <secret>
FACEBOOK_PROOF = '2c2adff38a252d561f6838a54c867d54512dfe2b3656e569dd92b9d8eb00de47'
# What the Graph API answers for someone who granted both permissions.
FACEBOOK_PROFILE = {'id': '10101', 'name': 'Sam Lee', 'email': 'sam@example.com'}


def _google() -> OAuthProvider:
    return build_registry(OAUTH_ENVIRONMENT, PUBLIC_BASE_URL)['google']


def _identity(signer: OidcSigner, claims: dict[str, Any]) -> OAuthIdentity:
    provider = _google()
    tokens = {'id_token': signer.make_id_token({'nonce': NONCE, **claims})}
    return provider.fetch_identity(provider, tokens, NONCE, {})


def _apple() -> OAuthProvider:
    return build_registry(APPLE_ENVIRONMENT, PUBLIC_BASE_URL)['apple']


def _apple_identity(
    signer: OidcSigner, claims: dict[str, Any], params: dict[str, str]
) -> OAuthIdentity:
    provider = _apple()
    token = signer.make_id_token({**APPLE_ID_TOKEN_CLAIMS, 'nonce': NONCE, **claims})
    return provider.fetch_identity(provider, {'id_token': token}, NONCE, params)


def _pem(
    key: ECKey | RSAKey, *, private: bool = True, password: str | None = None
) -> str:
    return key.as_pem(private=private, password=password).decode()


def _decoded_secret(secret: str) -> jwt.Token:
    return jwt.decode(secret, APPLE_PUBLIC_KEY, algorithms=['ES256'])


def _user_field(name: object) -> str:
    return json.dumps({'name': name})


def _facebook() -> OAuthProvider:
    return build_registry(FACEBOOK_ENVIRONMENT, PUBLIC_BASE_URL)['facebook']


def _facebook_identity(
    mocked_http: responses.RequestsMock, **answer: Any
) -> OAuthIdentity:
    # The profile lookup gets the answer; the tokens are what the exchange returned.
    mocked_http.add(responses.GET, FACEBOOK_PROFILE_URL, **answer)
    provider = _facebook()
    tokens = {'access_token': FACEBOOK_ACCESS_TOKEN, 'token_type': 'bearer'}
    return provider.fetch_identity(provider, tokens, NONCE, {})


UNUSABLE_KEYS = {
    'not-a-key': 'not a key',
    'truncated': APPLE_PEM[:80],
    'rsa': _pem(RSAKey.generate_key(2048)),
    'p-384': _pem(ECKey.generate_key('P-384')),
    # A curve joserfc has no name for, on which signing raises KeyError.
    'p-224': _pem(ECKey.import_key(ec.generate_private_key(ec.SECP224R1()))),
    'public-only': _pem(APPLE_PRIVATE_KEY, private=False),
    'encrypted': _pem(APPLE_PRIVATE_KEY, password='a passphrase'),
}


def test_google_is_enabled_with_both_keys() -> None:
    registry = build_registry(OAUTH_ENVIRONMENT, PUBLIC_BASE_URL)
    assert list(registry) == ['google']
    google = registry['google']
    assert google.label == 'Google'
    assert google.client_id == OAUTH_CLIENT_ID
    assert google.client_secret() == 'test-client-secret'


@pytest.mark.parametrize(
    'env',
    [
        {'OAUTH_GOOGLE_CLIENT_SECRET': 'test-client-secret'},
        {'OAUTH_GOOGLE_CLIENT_ID': OAUTH_CLIENT_ID},
        {**OAUTH_ENVIRONMENT, 'OAUTH_GOOGLE_CLIENT_ID': ''},
        {**OAUTH_ENVIRONMENT, 'OAUTH_GOOGLE_CLIENT_SECRET': ''},
    ],
    ids=['no-client-id', 'no-client-secret', 'blank-client-id', 'blank-client-secret'],
)
def test_google_stays_off_without_a_key(env: dict[str, str]) -> None:
    assert build_registry(env, PUBLIC_BASE_URL) == {}


@pytest.mark.parametrize('public_base_url', [None, ''])
def test_nothing_is_enabled_without_a_public_origin(public_base_url: str | None) -> None:
    assert build_registry(OAUTH_ENVIRONMENT, public_base_url) == {}


def test_redirect_uri() -> None:
    assert (
        redirect_uri('https://app.test', 'google')
        == 'https://app.test/api/v1/auth/oauth/google/callback'
    )


def test_google_provider_asks_for_pkce_and_the_account_chooser() -> None:
    google = _google()
    assert google.uses_pkce is True
    assert google.scopes == ('openid', 'email', 'profile')
    assert google.extra_authorize_params == {'prompt': 'select_account'}


def test_google_identity_reads_the_claims(oidc_signer: OidcSigner) -> None:
    identity = _identity(
        oidc_signer,
        {'email': 'person@example.com', 'email_verified': True, 'name': 'A Person'},
    )
    assert identity == OAuthIdentity(
        provider='google',
        subject='google-subject',
        email='person@example.com',
        email_verified=True,
        display_name='A Person',
    )


@pytest.mark.parametrize(
    ('claims', 'verified'),
    [
        ({'email_verified': True}, True),
        ({'email_verified': 'true'}, True),
        ({'email_verified': False}, False),
        ({'email_verified': 'false'}, False),
        ({'email_verified': 1}, False),
        ({'email_verified': 'TRUE'}, False),
        ({}, False),
    ],
    ids=['true', 'text-true', 'false', 'text-false', 'one', 'upper-case', 'missing'],
)
def test_email_verified(
    oidc_signer: OidcSigner, claims: dict[str, Any], *, verified: bool
) -> None:
    claims = {'email': 'person@example.com', **claims}
    assert _identity(oidc_signer, claims).email_verified is verified


@pytest.mark.parametrize('tokens', [{}, {'id_token': 42}], ids=['missing', 'not-text'])
def test_a_token_response_without_an_id_token_is_invalid(tokens: dict[str, Any]) -> None:
    with pytest.raises(OAuthError) as excinfo:
        id_token_claims(_google(), tokens, NONCE)
    assert excinfo.value.code == 'invalid_token'


# Sign in with Apple: the registry


def test_apple_is_enabled_with_its_four_keys_over_https(
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = {**OAUTH_ENVIRONMENT, **APPLE_ENVIRONMENT}
    registry = build_registry(env, PUBLIC_BASE_URL)
    assert list(registry) == ['google', 'apple']
    apple = registry['apple']
    assert apple.label == 'Apple'
    assert apple.client_id == APPLE_CLIENT_ID
    assert apple.authorize_url == APPLE_AUTHORIZE_URL
    assert apple.token_url == APPLE_TOKEN_URL
    assert apple.issuers == (APPLE_ISSUER,)
    assert apple.jwks_uri == APPLE_JWKS_URI
    assert apple.scopes == ('name', 'email')
    assert apple.uses_pkce is False
    assert apple.extra_authorize_params == {'response_mode': 'form_post'}
    assert caplog.messages == []


def test_apples_endpoints_are_the_ones_its_discovery_document_lists() -> None:
    # https://appleid.apple.com/.well-known/openid-configuration, fetched 2026-11-04
    assert (APPLE_AUTHORIZE_URL, APPLE_TOKEN_URL, APPLE_JWKS_URI, APPLE_ISSUER) == (
        'https://appleid.apple.com/auth/authorize',
        'https://appleid.apple.com/auth/token',
        'https://appleid.apple.com/auth/keys',
        'https://appleid.apple.com',
    )


def test_apple_stays_off_quietly_without_its_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert list(build_registry(OAUTH_ENVIRONMENT, PUBLIC_BASE_URL)) == ['google']
    assert build_registry(dict.fromkeys(APPLE_KEYS, ''), PUBLIC_BASE_URL) == {}
    # Development's origin is http, which matters only once an Apple key is set.
    assert build_registry({}, 'http://localhost:5174') == {}
    assert caplog.messages == []


@pytest.mark.parametrize('missing', APPLE_KEYS)
def test_apple_stays_off_and_warns_without_one_key(
    missing: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert build_registry({**APPLE_ENVIRONMENT, missing: ''}, PUBLIC_BASE_URL) == {}
    assert caplog.messages == [f'Sign in with Apple is off: {missing} not set.']


def test_apples_warning_names_every_missing_key(caplog: pytest.LogCaptureFixture) -> None:
    env = {**APPLE_ENVIRONMENT, 'OAUTH_APPLE_TEAM_ID': '', 'OAUTH_APPLE_KEY_ID': ''}
    assert build_registry(env, PUBLIC_BASE_URL) == {}
    message = (
        'Sign in with Apple is off: OAUTH_APPLE_TEAM_ID, OAUTH_APPLE_KEY_ID not set.'
    )
    assert caplog.record_tuples == [(LOGGER, logging.WARNING, message)]


def test_apple_stays_off_and_warns_over_http(caplog: pytest.LogCaptureFixture) -> None:
    assert build_registry(APPLE_ENVIRONMENT, 'http://localhost:5174') == {}
    (message,) = caplog.messages
    assert message == 'Sign in with Apple is off: PUBLIC_BASE_URL must be https.'


@pytest.mark.parametrize('pem', UNUSABLE_KEYS.values(), ids=list(UNUSABLE_KEYS))
def test_apple_stays_off_and_warns_with_an_unusable_key(
    pem: str, caplog: pytest.LogCaptureFixture
) -> None:
    env = {**APPLE_ENVIRONMENT, 'OAUTH_APPLE_PRIVATE_KEY': pem}
    assert build_registry(env, PUBLIC_BASE_URL) == {}
    (message,) = caplog.messages
    assert message.startswith('Sign in with Apple is off: OAUTH_APPLE_PRIVATE_KEY ')


@pytest.mark.parametrize(
    ('pem', 'error'),
    [
        (UNUSABLE_KEYS['not-a-key'], 'ValueError'),
        (UNUSABLE_KEYS['encrypted'], 'TypeError'),
    ],
    ids=['malformed', 'encrypted'],
)
def test_apples_key_warning_names_the_error_class(
    pem: str, error: str, caplog: pytest.LogCaptureFixture
) -> None:
    env = {**APPLE_ENVIRONMENT, 'OAUTH_APPLE_PRIVATE_KEY': pem}
    assert build_registry(env, PUBLIC_BASE_URL) == {}
    message = (
        'Sign in with Apple is off: OAUTH_APPLE_PRIVATE_KEY is not a usable P-256 '
        f'private key ({error}).'
    )
    assert caplog.record_tuples == [(LOGGER, logging.WARNING, message)]


# Sign in with Apple: the key and the client secret


@pytest.mark.parametrize(
    'value',
    [APPLE_PEM, APPLE_PEM.replace('\n', '\\n'), APPLE_PEM.replace('\n', '\r\n')],
    ids=['line-breaks', 'escaped-line-breaks', 'windows-line-breaks'],
)
def test_load_private_key_reads_the_p8_files_text(value: str) -> None:
    assert load_private_key(value).thumbprint() == APPLE_PRIVATE_KEY.thumbprint()


def test_the_client_secret_is_what_apple_documents() -> None:
    before = int(time.time())
    secret = apple_client_secret(
        team_id=APPLE_TEAM_ID,
        client_id=APPLE_CLIENT_ID,
        key_id=APPLE_KEY_ID,
        private_key=APPLE_PRIVATE_KEY,
    )
    token = _decoded_secret(secret)
    assert token.header == {'alg': 'ES256', 'kid': APPLE_KEY_ID}
    assert token.claims['iss'] == APPLE_TEAM_ID
    assert token.claims['sub'] == APPLE_CLIENT_ID
    assert token.claims['aud'] == 'https://appleid.apple.com'
    assert before <= token.claims['iat'] <= int(time.time())
    assert token.claims['exp'] - token.claims['iat'] == 300


def test_the_provider_signs_for_its_services_id_with_the_teams_key() -> None:
    token = _decoded_secret(_apple().client_secret())
    assert token.header['kid'] == APPLE_KEY_ID
    assert token.claims['iss'] == APPLE_TEAM_ID
    assert token.claims['sub'] == APPLE_CLIENT_ID


def test_each_exchange_mints_its_own_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    apple = _apple()
    monkeypatch.setattr(time, 'time', lambda: 1_800_000_000.9)
    first = _decoded_secret(apple.client_secret()).claims['iat']
    monkeypatch.setattr(time, 'time', lambda: 1_800_000_600.9)
    second = _decoded_secret(apple.client_secret()).claims['iat']
    assert (first, second) == (1_800_000_000, 1_800_000_600)


# Sign in with Apple: the identity and the name


def test_apple_identity_reads_the_token_and_the_first_answers_name(
    apple_signer: OidcSigner,
) -> None:
    claims = {'email': 'maria@privaterelay.appleid.com', 'email_verified': 'true'}
    identity = _apple_identity(apple_signer, claims, {'user': FIRST_ANSWER})
    # The user field is unsigned, so its email is ignored; the token's decides.
    assert identity == OAuthIdentity(
        provider='apple',
        subject='apple-subject',
        email='maria@privaterelay.appleid.com',
        email_verified=True,
        display_name='Maria Ruiz',
    )


def test_a_returning_apple_sign_in_carries_no_name(apple_signer: OidcSigner) -> None:
    claims = {'email': 'maria@example.com', 'email_verified': True}
    assert _apple_identity(apple_signer, claims, {}).display_name is None


@pytest.mark.parametrize(
    ('value', 'verified'),
    [(True, True), ('true', True), (False, False), ('false', False)],
    ids=['true', 'text-true', 'false', 'text-false'],
)
def test_apples_email_verified_is_text_or_a_boolean(
    apple_signer: OidcSigner, value: object, *, verified: bool
) -> None:
    claims = {'email': 'maria@example.com', 'email_verified': value}
    assert _apple_identity(apple_signer, claims, {}).email_verified is verified


def test_an_empty_apple_email_is_none(apple_signer: OidcSigner) -> None:
    claims = {'email': '', 'email_verified': 'false'}
    assert _apple_identity(apple_signer, claims, {}).email is None


@pytest.mark.parametrize(
    ('field', 'name'),
    [
        (_user_field({'firstName': 'Maria', 'lastName': 'Ruiz'}), 'Maria Ruiz'),
        (_user_field({'firstName': 'Maria'}), 'Maria'),
        (_user_field({'lastName': 'Ruiz'}), 'Ruiz'),
        (_user_field({'firstName': ' Maria ', 'lastName': '  '}), 'Maria'),
        (None, None),
        ('', None),
        ('not json', None),
        ('[]', None),
        (json.dumps({'email': 'maria@example.com'}), None),
        (_user_field('Maria Ruiz'), None),
        (_user_field({'firstName': 5, 'lastName': None}), None),
    ],
    ids=[
        'both',
        'given-only',
        'family-only',
        'padded',
        'missing',
        'empty',
        'not-json',
        'not-an-object',
        'no-name',
        'name-not-an-object',
        'parts-not-text',
    ],
)
def test_apple_display_name(field: str | None, name: str | None) -> None:
    assert apple_display_name(field) == name


def test_an_apple_name_keeps_only_what_a_database_can_store() -> None:
    # NUL, which PostgreSQL refuses, a tab, and a lone surrogate, which no driver can
    # encode, are dropped; a zero-width joiner, which some scripts need, stays.
    joiner = chr(0x200D)
    given = 'Ma' + chr(0) + 'ria' + joiner
    family = 'Ru' + chr(9) + 'iz' + chr(0xD800)
    field = _user_field({'firstName': given, 'lastName': family})
    assert apple_display_name(field) == 'Maria' + joiner + ' Ruiz'
    assert apple_display_name(_user_field({'firstName': chr(0)})) is None


def test_a_user_field_past_the_limit_is_not_read() -> None:
    padding = APPLE_USER_FIELD_LIMIT - len(_user_field({'firstName': ''}))
    longest = _user_field({'firstName': 'M' * padding})
    assert len(longest) == APPLE_USER_FIELD_LIMIT
    assert apple_display_name(longest) == 'M' * padding
    assert apple_display_name(_user_field({'firstName': 'M' * (padding + 1)})) is None
    # Nesting this deep fits the 25 MB request limit and makes json.loads raise.
    assert apple_display_name('[' * 100_000 + ']' * 100_000) is None
    # The deepest nesting the cap lets through; Python 3.12.0 to 3.12.2 refuse it.
    assert apple_display_name('[' * 2048 + ']' * 2048) is None


# Facebook: the registry


def test_facebook_is_enabled_with_both_keys(caplog: pytest.LogCaptureFixture) -> None:
    env = {**OAUTH_ENVIRONMENT, **APPLE_ENVIRONMENT, **FACEBOOK_ENVIRONMENT}
    registry = build_registry(env, PUBLIC_BASE_URL)
    assert list(registry) == ['google', 'apple', 'facebook']
    facebook = registry['facebook']
    assert facebook.label == 'Facebook'
    assert facebook.client_id == FACEBOOK_CLIENT_ID
    assert facebook.client_secret() == FACEBOOK_CLIENT_SECRET
    assert facebook.authorize_url == FACEBOOK_AUTHORIZE_URL
    assert facebook.token_url == FACEBOOK_TOKEN_URL
    assert facebook.scopes == ('public_profile', 'email')
    assert facebook.uses_pkce is False
    assert facebook.extra_authorize_params == {'auth_type': 'rerequest'}
    assert facebook.issuers == ()
    assert facebook.jwks_uri is None
    assert caplog.messages == []


def test_facebooks_endpoints_name_one_graph_api_version() -> None:
    # Meta's manual login flow, and its Graph API v27.0 announcement of 2026-11-04.
    assert FACEBOOK_GRAPH_VERSION == 'v27.0'
    assert (FACEBOOK_AUTHORIZE_URL, FACEBOOK_TOKEN_URL, FACEBOOK_PROFILE_URL) == (
        'https://www.facebook.com/v27.0/dialog/oauth',
        'https://graph.facebook.com/v27.0/oauth/access_token',
        'https://graph.facebook.com/v27.0/me',
    )


def test_facebook_works_on_a_development_origin(caplog: pytest.LogCaptureFixture) -> None:
    # Unlike Apple, Facebook has no https check, so the dev stack can try it; Meta's
    # dashboard decides which callbacks it accepts.
    registry = build_registry(FACEBOOK_ENVIRONMENT, 'http://localhost:5174')
    assert list(registry) == ['facebook']
    assert caplog.messages == []


@pytest.mark.parametrize(
    'env',
    [
        {'OAUTH_FACEBOOK_CLIENT_SECRET': FACEBOOK_CLIENT_SECRET},
        {'OAUTH_FACEBOOK_CLIENT_ID': FACEBOOK_CLIENT_ID},
        {**FACEBOOK_ENVIRONMENT, 'OAUTH_FACEBOOK_CLIENT_ID': ''},
        {**FACEBOOK_ENVIRONMENT, 'OAUTH_FACEBOOK_CLIENT_SECRET': ''},
    ],
    ids=['no-client-id', 'no-client-secret', 'blank-client-id', 'blank-client-secret'],
)
def test_facebook_stays_off_quietly_without_a_key(
    env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    assert build_registry(env, PUBLIC_BASE_URL) == {}
    assert caplog.messages == []


# Facebook: the profile lookup


def test_facebook_identity_reads_the_profile(mocked_http: responses.RequestsMock) -> None:
    assert _facebook_identity(mocked_http, json=FACEBOOK_PROFILE) == OAuthIdentity(
        provider='facebook',
        subject='10101',
        email='sam@example.com',
        email_verified=True,
        display_name='Sam Lee',
    )


def test_the_lookup_signs_the_token_and_keeps_it_out_of_the_url(
    mocked_http: responses.RequestsMock,
) -> None:
    _facebook_identity(mocked_http, json=FACEBOOK_PROFILE)
    # responses records the call's parameters and keyword arguments at runtime, untyped.
    request: Any = mocked_http.calls[0].request
    assert request.method == 'GET'
    assert request.params == {
        'fields': 'id,name,email',
        'appsecret_proof': FACEBOOK_PROOF,
    }
    assert request.headers['Authorization'] == f'Bearer {FACEBOOK_ACCESS_TOKEN}'
    assert FACEBOOK_ACCESS_TOKEN not in request.url
    assert request.req_kwargs['timeout'] == HTTP_TIMEOUT_SECONDS
    # REQUESTS_CA_BUNDLE turns verify into a path, so check only that it is not off.
    assert request.req_kwargs['verify'] is not False


def test_the_proof_is_the_tokens_hmac_under_the_secret() -> None:
    # The known answer above, from the same inputs through Python's hmac.
    digest = hmac.new(
        FACEBOOK_CLIENT_SECRET.encode(), FACEBOOK_ACCESS_TOKEN.encode(), hashlib.sha256
    )
    assert digest.hexdigest() == FACEBOOK_PROOF


@pytest.mark.parametrize(
    'profile',
    [
        {'id': '10101', 'name': 'Sam Lee'},
        {'id': '10101', 'name': 'Sam Lee', 'email': ''},
        {'id': '10101', 'name': 'Sam Lee', 'email': None},
        {'id': '10101', 'name': 'Sam Lee', 'email': 42},
    ],
    ids=['declined', 'empty', 'null', 'not-text'],
)
def test_a_facebook_profile_without_an_email_has_none(
    mocked_http: responses.RequestsMock, profile: dict[str, Any]
) -> None:
    identity = _facebook_identity(mocked_http, json=profile)
    assert (identity.subject, identity.email, identity.email_verified) == (
        '10101',
        None,
        False,
    )


FACEBOOK_PROFILE_FAILURES: dict[str, dict[str, Any]] = {
    'refused': {
        'status': 400,
        'json': {'error': {'message': 'Invalid OAuth access token.', 'code': 190}},
    },
    'not-json': {'body': 'not json'},
    'a-list': {'json': ['not', 'an', 'object']},
    'unreachable': {'body': requests.ConnectionError('unreachable')},
    'no-id': {'json': {'name': 'Sam Lee', 'email': 'sam@example.com'}},
    'empty-id': {'json': {'id': '', 'email': 'sam@example.com'}},
    'id-not-text': {'json': {'id': 10101, 'email': 'sam@example.com'}},
}


@pytest.mark.parametrize(
    'answer', FACEBOOK_PROFILE_FAILURES.values(), ids=FACEBOOK_PROFILE_FAILURES.keys()
)
def test_a_profile_lookup_that_names_no_one_is_exchange_failed(
    mocked_http: responses.RequestsMock, answer: dict[str, Any]
) -> None:
    with pytest.raises(OAuthError) as excinfo:
        _facebook_identity(mocked_http, **answer)
    assert excinfo.value.code == 'exchange_failed'


@pytest.mark.parametrize(
    'tokens',
    [{}, {'access_token': ''}, {'access_token': 42}],
    ids=['missing', 'empty', 'not-text'],
)
def test_a_token_response_without_an_access_token_is_exchange_failed(
    mocked_http: responses.RequestsMock, tokens: dict[str, Any]
) -> None:
    provider = _facebook()
    with pytest.raises(OAuthError) as excinfo:
        provider.fetch_identity(provider, tokens, NONCE, {})
    assert excinfo.value.code == 'exchange_failed'
    assert len(mocked_http.calls) == 0


def test_the_callbacks_own_parameters_name_no_one(
    mocked_http: responses.RequestsMock,
) -> None:
    # The browser writes the callback's query, so only the Graph API's answer counts.
    mocked_http.add(responses.GET, FACEBOOK_PROFILE_URL, json={'id': '10101'})
    provider = _facebook()
    tokens = {'access_token': FACEBOOK_ACCESS_TOKEN, 'token_type': 'bearer'}
    forged = {'id': '20202', 'email': 'someone.else@example.com', 'name': 'Someone Else'}
    identity = provider.fetch_identity(provider, tokens, NONCE, forged)
    assert (identity.subject, identity.email) == ('10101', None)
    assert identity.display_name is None


@pytest.mark.parametrize(
    ('failure', 'logged'),
    [
        ('refused', '400'),
        ('not-json', 'JSONDecodeError'),
        ('unreachable', 'ConnectionError'),
    ],
)
def test_a_failed_lookup_logs_only_its_status_or_error_type(
    mocked_http: responses.RequestsMock,
    caplog: pytest.LogCaptureFixture,
    failure: str,
    logged: str,
) -> None:
    # The URL holds appsecret_proof, so no record at any level carries it or error text.
    with caplog.at_level(logging.DEBUG, logger=LOGGER), pytest.raises(OAuthError):
        _facebook_identity(mocked_http, **FACEBOOK_PROFILE_FAILURES[failure])
    assert caplog.record_tuples == [
        (LOGGER, logging.WARNING, f'Asking Facebook who signed in failed: {logged}'),
    ]
    for secret in (FACEBOOK_ACCESS_TOKEN, FACEBOOK_PROOF, FACEBOOK_CLIENT_SECRET):
        assert secret not in caplog.text


def test_a_facebook_name_keeps_only_what_a_database_can_store(
    mocked_http: responses.RequestsMock,
) -> None:
    # A NUL, which PostgreSQL refuses, and a lone surrogate, which no driver can encode.
    profile = {**FACEBOOK_PROFILE, 'name': 'Sam' + chr(0) + ' Lee' + chr(0xD800)}
    assert _facebook_identity(mocked_http, json=profile).display_name == 'Sam Lee'


@pytest.mark.parametrize(
    'profile',
    [{'id': '10101'}, {'id': '10101', 'name': 7}, {'id': '10101', 'name': ' '}],
    ids=['missing', 'not-text', 'blank'],
)
def test_a_facebook_profile_without_a_usable_name_has_none(
    mocked_http: responses.RequestsMock, profile: dict[str, Any]
) -> None:
    assert _facebook_identity(mocked_http, json=profile).display_name is None
