import os

import pytest

os.environ.setdefault("RATELIMIT_ENABLED", "0")

from src_back.app import create_app  # noqa: E402
from src_back.extensions import db as _db  # noqa: E402
from src_back.models import User  # noqa: E402


@pytest.fixture()
def app():
    app = create_app()
    app.config.update(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        }
    )
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def user(app):
    u = User(email="user@test.com", role="user")
    u.set_password("password123")
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture()
def admin_user(app):
    u = User(email="admin@test.com", role="admin")
    u.set_password("adminpass123")
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture()
def auth_client(client, user):
    client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    return client


@pytest.fixture()
def admin_client(client, admin_user):
    client.post(
        "/api/v1/auth/login",
        json={"email": admin_user.email, "password": "adminpass123"},
    )
    return client
