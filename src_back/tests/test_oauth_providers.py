from typing import Any

import pytest

from src_back.services.errors import OAuthError
from src_back.services.oauth_providers import (
    OAuthIdentity,
    OAuthProvider,
    build_registry,
    id_token_claims,
    redirect_uri,
)
from src_back.tests.conftest import (
    OAUTH_CLIENT_ID,
    OAUTH_ENVIRONMENT,
    PUBLIC_BASE_URL,
    OidcSigner,
)

NONCE = 'the-nonce'


def _google() -> OAuthProvider:
    return build_registry(OAUTH_ENVIRONMENT, PUBLIC_BASE_URL)['google']


def _identity(signer: OidcSigner, claims: dict[str, Any]) -> OAuthIdentity:
    provider = _google()
    tokens = {'id_token': signer.make_id_token({'nonce': NONCE, **claims})}
    return provider.fetch_identity(provider, tokens, NONCE)


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
