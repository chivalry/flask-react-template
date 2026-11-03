import base64
import json
import logging
import time
from typing import Any

import pytest
import requests
import responses
from joserfc import jwt
from joserfc.jwk import ECKey, KeySet, OctKey, RSAKey

from src_back.services import oidc
from src_back.services.errors import OAuthError
from src_back.services.oauth_providers import GOOGLE_ISSUERS, GOOGLE_JWKS_URI
from src_back.services.oidc import verify_id_token
from src_back.tests.conftest import OAUTH_CLIENT_ID, OidcSigner

NONCE = 'the-nonce'


def _verify(id_token: str) -> dict[str, Any]:
    return verify_id_token(
        id_token,
        jwks_uri=GOOGLE_JWKS_URI,
        issuers=GOOGLE_ISSUERS,
        audience=OAUTH_CLIENT_ID,
        nonce=NONCE,
    )


def _token(signer: OidcSigner, claims: dict[str, Any] | None = None) -> str:
    return signer.make_id_token({'nonce': NONCE, **(claims or {})})


def _refusal(id_token: str) -> str:
    with pytest.raises(OAuthError) as excinfo:
        _verify(id_token)
    return excinfo.value.code


def _standard_claims() -> dict[str, Any]:
    now = int(time.time())
    return {
        'iss': GOOGLE_ISSUERS[0],
        'aud': OAUTH_CLIENT_ID,
        'sub': 'google-subject',
        'iat': now,
        'exp': now + 3600,
        'nonce': NONCE,
    }


def _base64url(data: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(data).encode())
    return encoded.rstrip(b'=').decode()


def _public_jwks(*keys: RSAKey | ECKey) -> dict[str, Any]:
    return dict(KeySet(list(keys)).as_dict(private=False))


def _another_key_with_the_same_kid(signer: OidcSigner) -> RSAKey:
    kid = signer.key.kid
    assert kid is not None
    return RSAKey.generate_key(2048, parameters={'kid': kid})


@pytest.mark.parametrize('issuer', GOOGLE_ISSUERS)
def test_a_valid_token_returns_its_claims(oidc_signer: OidcSigner, issuer: str) -> None:
    claims = _verify(_token(oidc_signer, {'iss': issuer}))
    assert claims['iss'] == issuer
    assert claims['sub'] == 'google-subject'
    assert claims['nonce'] == NONCE


def test_a_token_for_another_audience_is_refused(oidc_signer: OidcSigner) -> None:
    assert _refusal(_token(oidc_signer, {'aud': 'another-client'})) == 'invalid_token'


def test_another_issuer_is_refused(oidc_signer: OidcSigner) -> None:
    token = _token(oidc_signer, {'iss': 'https://evil.example'})
    assert _refusal(token) == 'invalid_token'


def test_a_token_with_a_second_audience_is_refused(oidc_signer: OidcSigner) -> None:
    token = _token(oidc_signer, {'aud': [OAUTH_CLIENT_ID, 'another-client']})
    assert _refusal(token) == 'invalid_token'


def test_a_one_item_audience_list_passes(oidc_signer: OidcSigner) -> None:
    claims = _verify(_token(oidc_signer, {'aud': [OAUTH_CLIENT_ID]}))
    assert claims['aud'] == [OAUTH_CLIENT_ID]


def test_a_token_without_an_audience_is_refused(oidc_signer: OidcSigner) -> None:
    assert _refusal(_token(oidc_signer, {'aud': None})) == 'invalid_token'


def test_a_token_expired_past_the_leeway_is_refused(oidc_signer: OidcSigner) -> None:
    token = _token(oidc_signer, {'exp': int(time.time()) - 120})
    assert _refusal(token) == 'invalid_token'


def test_a_token_expired_within_the_leeway_passes(oidc_signer: OidcSigner) -> None:
    claims = _verify(_token(oidc_signer, {'exp': int(time.time()) - 30}))
    assert claims['sub'] == 'google-subject'


def test_a_signature_by_another_key_is_refused(oidc_signer: OidcSigner) -> None:
    impostor = _another_key_with_the_same_kid(oidc_signer)
    assert _refusal(_token(OidcSigner(impostor))) == 'invalid_token'


def test_a_token_without_its_subject_is_refused(oidc_signer: OidcSigner) -> None:
    assert _refusal(_token(oidc_signer, {'sub': None})) == 'invalid_token'


def test_a_token_without_exp_is_refused(oidc_signer: OidcSigner) -> None:
    assert _refusal(_token(oidc_signer, {'exp': None})) == 'invalid_token'


def test_a_mismatched_nonce_is_refused(oidc_signer: OidcSigner) -> None:
    assert _refusal(_token(oidc_signer, {'nonce': 'another-nonce'})) == 'invalid_token'


def test_a_missing_nonce_is_refused(oidc_signer: OidcSigner) -> None:
    assert _refusal(_token(oidc_signer, {'nonce': None})) == 'invalid_token'


def test_a_nonce_with_non_ascii_text_is_refused(oidc_signer: OidcSigner) -> None:
    assert _refusal(_token(oidc_signer, {'nonce': 'é'})) == 'invalid_token'


@pytest.mark.usefixtures('oidc_signer')
def test_an_hmac_token_is_refused() -> None:
    token = jwt.encode(
        {'alg': 'HS256'},
        _standard_claims(),
        OctKey.import_key('x' * 32),
        algorithms=['HS256'],
    )
    assert _refusal(token) == 'invalid_token'


def test_an_es256_token_is_refused(mocked_http: responses.RequestsMock) -> None:
    ec_key = ECKey.generate_key('P-256', auto_kid=True)
    mocked_http.add(responses.GET, GOOGLE_JWKS_URI, json=_public_jwks(ec_key))
    token = jwt.encode(
        {'alg': 'ES256', 'kid': ec_key.kid},
        _standard_claims(),
        ec_key,
        algorithms=['ES256'],
    )
    assert _refusal(token) == 'invalid_token'


@pytest.mark.usefixtures('oidc_signer')
def test_an_unsigned_token_is_refused() -> None:
    header = _base64url({'alg': 'none', 'typ': 'JWT'})
    token = f'{header}.{_base64url(_standard_claims())}.'
    assert _refusal(token) == 'invalid_token'


@pytest.mark.usefixtures('oidc_signer')
def test_a_malformed_token_is_refused() -> None:
    assert _refusal('not-a-jwt') == 'invalid_token'


def test_an_unknown_key_id_fetches_the_keys_once_more(
    oidc_signer: OidcSigner, mocked_http: responses.RequestsMock
) -> None:
    mocked_http.remove(responses.GET, GOOGLE_JWKS_URI)
    old_key = RSAKey.generate_key(2048, auto_kid=True)
    mocked_http.get(GOOGLE_JWKS_URI, json=_public_jwks(old_key))
    mocked_http.get(GOOGLE_JWKS_URI, json=oidc_signer.public_jwks())
    assert _verify(_token(oidc_signer))['sub'] == 'google-subject'
    mocked_http.assert_call_count(GOOGLE_JWKS_URI, 2)


def test_a_key_id_unknown_after_the_refetch_is_refused(
    oidc_signer: OidcSigner, mocked_http: responses.RequestsMock
) -> None:
    mocked_http.remove(responses.GET, GOOGLE_JWKS_URI)
    old_key = RSAKey.generate_key(2048, auto_kid=True)
    mocked_http.get(GOOGLE_JWKS_URI, json=_public_jwks(old_key))
    assert _refusal(_token(oidc_signer)) == 'invalid_token'
    mocked_http.assert_call_count(GOOGLE_JWKS_URI, 2)


def test_a_second_token_uses_the_cached_keys(
    oidc_signer: OidcSigner, mocked_http: responses.RequestsMock
) -> None:
    _verify(_token(oidc_signer))
    _verify(_token(oidc_signer))
    mocked_http.assert_call_count(GOOGLE_JWKS_URI, 1)
    # responses records the call's keyword arguments at runtime, untyped.
    request: Any = mocked_http.calls[0].request
    assert request.req_kwargs['timeout'] == oidc.HTTP_TIMEOUT_SECONDS


def test_the_keys_are_fetched_again_after_an_hour(
    oidc_signer: OidcSigner, mocked_http: responses.RequestsMock
) -> None:
    stale_key = _another_key_with_the_same_kid(oidc_signer)
    stale_keys = KeySet.import_key_set({'keys': [stale_key.as_dict(private=False)]})
    oidc._key_sets[GOOGLE_JWKS_URI] = (time.monotonic() - 3601, stale_keys)
    assert _verify(_token(oidc_signer))['sub'] == 'google-subject'
    mocked_http.assert_call_count(GOOGLE_JWKS_URI, 1)


UNREADABLE_KEY_ANSWERS = {
    'server-error': {'status': 500},
    'not-json': {'body': 'not json'},
    'no-keys-member': {'json': {}},
    'a-list': {'json': []},
    'empty-key-set': {'json': {'keys': []}},
    'unreachable': {'body': requests.ConnectionError('unreachable')},
}


@pytest.mark.parametrize(
    'answer', UNREADABLE_KEY_ANSWERS.values(), ids=UNREADABLE_KEY_ANSWERS.keys()
)
def test_unreadable_keys_are_refused(
    oidc_key: RSAKey,
    mocked_http: responses.RequestsMock,
    caplog: pytest.LogCaptureFixture,
    answer: dict[str, Any],
) -> None:
    signer = OidcSigner(oidc_key)
    if answer.get('status') == 500:
        # A valid body, so only raise_for_status can refuse it.
        answer = {**answer, 'json': signer.public_jwks()}
    mocked_http.add(responses.GET, GOOGLE_JWKS_URI, **answer)
    with caplog.at_level(logging.WARNING, logger='src_back.services.oidc'):
        assert _refusal(_token(signer)) == 'invalid_token'
    assert f'Fetching the keys at {GOOGLE_JWKS_URI} failed' in caplog.text
