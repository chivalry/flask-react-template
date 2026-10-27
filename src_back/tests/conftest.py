import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src_back.app import create_app
from src_back.extensions import Base
from src_back.extensions import db as _db
from src_back.models import BaseMixin, Role, User
from src_back.tests.helpers import persist

# A 1x1 PNG: enough for filetype to sniff image/png.
PNG_BYTES = (
    b'\x89PNG\r\n\x1a\n'
    b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
    b'\x1f\x15\xc4\x89'
    b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4'
    b'\x00\x00\x00\x00IEND\xaeB`\x82'
)


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


@pytest.fixture()
def app(tmp_path: Path) -> Iterator[Flask]:
    app = create_app(
        {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': os.environ.get(
                'TEST_DATABASE_URL', 'sqlite:///:memory:'
            ),
            'UPLOAD_FOLDER': str(tmp_path / 'uploads'),
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
