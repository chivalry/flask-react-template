def test_register_success(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "secure123"},
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data["email"] == "new@example.com"
    assert "password" not in data
    assert "id" in data


def test_register_duplicate_email(client, user):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": user.email, "password": "secure123"},
    )
    assert r.status_code == 409


def test_register_short_password(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "x@example.com", "password": "short"},
    )
    assert r.status_code == 400


def test_register_invalid_email(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "secure123"},
    )
    assert r.status_code == 400


def test_login_success(client, user):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["email"] == user.email
    assert "password" not in data


def test_login_wrong_password(client, user):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "wrongpassword"},
    )
    assert r.status_code == 401


def test_login_unknown_email(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "password123"},
    )
    assert r.status_code == 401


def test_logout_success(auth_client):
    r = auth_client.post("/api/v1/auth/logout")
    assert r.status_code == 200


def test_logout_unauthenticated(client):
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 401


def test_me_authenticated(auth_client, user):
    r = auth_client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.get_json()["email"] == user.email


def test_me_unauthenticated(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
