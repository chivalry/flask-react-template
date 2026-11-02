import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import responses
from flask import Flask
from flask.testing import FlaskClient
from flask_sqlalchemy import SQLAlchemy
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src_back.app import create_app
from src_back.extensions import Base
from src_back.extensions import db as _db
from src_back.models import BaseMixin, OAuthAccount, Role, User
from src_back.services import oidc
from src_back.services.oauth_providers import (
    GOOGLE_ISSUERS,
    GOOGLE_JWKS_URI,
    build_registry,
)
from src_back.tests.helpers import persist

# A 1x1 PNG: enough for filetype to sniff image/png.
PNG_BYTES = (
    b'\x89PNG\r\n\x1a\n'
    b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
    b'\x1f\x15\xc4\x89'
    b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4'
    b'\x00\x00\x00\x00IEND\xaeB`\x82'
)

# The variables src_back/mailer.py reads; _clear_smtp_environment unsets every one.
SMTP_VARIABLES = (
    'SMTP_HOST',
    'SMTP_PORT',
    'SMTP_SECURITY',
    'SMTP_USERNAME',
    'SMTP_PASSWORD',
    'SMTP_FROM',
)

PUBLIC_BASE_URL = 'https://app.test'
OAUTH_CLIENT_ID = 'test-client-id'
OAUTH_ENVIRONMENT = {
    'OAUTH_GOOGLE_CLIENT_ID': OAUTH_CLIENT_ID,
    'OAUTH_GOOGLE_CLIENT_SECRET': 'test-client-secret',
}


class Widget(BaseMixin, Base):
    """Test-only parent model for exercising the generic services and schemas."""

    __tablename__ = 'widgets'

    name: Mapped[str] = mapped_column(String(100))


class WidgetNote(BaseMixin, Base):
    """Test-only child model owned by a Widget; ``body`` is nullable on purpose."""

    __tablename__ = 'widget_notes'

    widget_id: Mapped[int] = mapped_column(ForeignKey('widgets.id'))
    body: Mapped[str | None] = mapped_column(String(255))


class SpaTestClient(FlaskClient):
    """Test client that sends X-Requested-With on every request, as the SPA does."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.environ_base['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'


@pytest.fixture(autouse=True)
def _clear_app_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # src_back.app loads .env at import; a developer's APP_ENVIRONMENT would rename the
    # session cookie that test_auth.py reads.
    monkeypatch.delenv('APP_ENVIRONMENT', raising=False)


@pytest.fixture(autouse=True)
def _clear_smtp_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # src_back.app loads .env at import, where a developer's SMTP_* settings would let a
    # test send real mail. Every test starts with mail off, and a mailer test sets what
    # it needs.
    for name in SMTP_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _clear_oauth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # src_back.app loads .env at import, where a developer's real keys would enable
    # Google in every app a test builds without injecting a registry.
    for name in OAUTH_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _clear_jwks_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # Each process caches a provider's keys; a test must not inherit another's.
    monkeypatch.setattr(oidc, '_key_sets', {})


@pytest.fixture()
def app(tmp_path: Path) -> Iterator[Flask]:
    app = create_app(
        {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': os.environ.get(
                'TEST_DATABASE_URL', 'sqlite:///:memory:'
            ),
            'UPLOAD_FOLDER': str(tmp_path / 'uploads'),
            'PUBLIC_BASE_URL': PUBLIC_BASE_URL,
            'OAUTH_PROVIDERS': build_registry(OAUTH_ENVIRONMENT, PUBLIC_BASE_URL),
        }
    )
    # Every client the tests build, app.test_client() included, marks its requests as
    # the SPA's axios client does, which mutating API requests need.
    app.test_client_class = SpaTestClient
    with app.app_context():
        _db.create_all()
        yield app
        # Release the session's locks first; on Postgres they block DROP TABLE forever.
        _db.session.remove()
        _db.drop_all()
        # Close this app's pooled connections now. Waiting for garbage collection lets a
        # long run exhaust Postgres's connection limit.
        _db.engine.dispose()


@pytest.fixture()
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture()
def db(app: Flask) -> SQLAlchemy:
    return _db


@pytest.fixture()
def user(app: Flask) -> User:
    u = User(email='user@test.com', role=Role.user)
    u.set_password('password123')
    return persist(u)


@pytest.fixture()
def admin_user(app: Flask) -> User:
    u = User(email='admin@test.com', role=Role.admin)
    u.set_password('adminpass123')
    return persist(u)


@pytest.fixture()
def passwordless_user(app: Flask) -> User:
    return persist(User(email='nopass@test.com', role=Role.user))


@pytest.fixture()
def inactive_user(app: Flask) -> User:
    u = User(email='inactive@test.com', role=Role.user, is_active=False)
    u.set_password('password123')
    return persist(u)


@pytest.fixture()
def linked_user(passwordless_user: User) -> User:
    persist(
        OAuthAccount(
            user=passwordless_user,
            provider='google',
            provider_user_id='google-subject',
            email=passwordless_user.email,
        )
    )
    return passwordless_user


@pytest.fixture()
def mocked_http() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


class OidcSigner:
    """Signs ID tokens with a key whose public half the mocked JWKS URL serves."""

    def __init__(self, key: RSAKey) -> None:
        self.key = key

    def public_jwks(self) -> dict[str, Any]:
        return dict(KeySet([self.key]).as_dict(private=False))

    def make_id_token(self, claims: dict[str, Any]) -> str:
        now = int(time.time())
        payload = {
            'iss': GOOGLE_ISSUERS[0],
            'aud': OAUTH_CLIENT_ID,
            'sub': 'google-subject',
            'iat': now,
            'exp': now + 3600,
            **claims,
        }
        # A claim of None is left out, which is how a test drops sub, exp, or nonce.
        payload = {name: value for name, value in payload.items() if value is not None}
        header = {'alg': 'RS256', 'kid': self.key.kid}
        return jwt.encode(header, payload, self.key, algorithms=['RS256'])


@pytest.fixture(scope='session')
def oidc_key() -> RSAKey:
    return RSAKey.generate_key(2048, auto_kid=True)


@pytest.fixture()
def oidc_signer(oidc_key: RSAKey, mocked_http: responses.RequestsMock) -> OidcSigner:
    signer = OidcSigner(oidc_key)
    mocked_http.add(responses.GET, GOOGLE_JWKS_URI, json=signer.public_jwks())
    return signer


@pytest.fixture()
def auth_client(client: FlaskClient, user: User) -> FlaskClient:
    client.post(
        '/api/v1/auth/login',
        json={'email': user.email, 'password': 'password123'},
    )
    return client


@pytest.fixture()
def admin_client(client: FlaskClient, admin_user: User) -> FlaskClient:
    client.post(
        '/api/v1/auth/login',
        json={'email': admin_user.email, 'password': 'adminpass123'},
    )
    return client
