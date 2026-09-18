import pytest
from flask import Blueprint, abort


@pytest.fixture()
def spa_index(app, tmp_path):
    (tmp_path / "index.html").write_text('<div id="root"></div>')
    app.static_folder = str(tmp_path)


def test_malformed_json_returns_json_400(client):
    r = client.post(
        "/api/v1/auth/register",
        data="{not json",
        content_type="application/json",
    )
    assert r.status_code == 400
    assert r.get_json() == {"error": "Bad request"}


def test_forbidden_returns_json_403(app, client):
    bp = Blueprint("test_forbidden", __name__)

    @bp.get("/test-forbidden")
    def forbidden_view():
        abort(403)

    app.register_blueprint(bp)
    r = client.get("/test-forbidden")
    assert r.status_code == 403
    assert r.get_json() == {"error": "Forbidden"}


def test_unhandled_exception_returns_json_500(app, client):
    bp = Blueprint("test_crash", __name__)

    @bp.get("/test-crash")
    def crash_view():
        raise RuntimeError("boom")

    app.register_blueprint(bp)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    r = client.get("/test-crash")
    assert r.status_code == 500
    assert r.get_json() == {"error": "Internal server error"}


def test_unknown_api_path_returns_json_404(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.get_json() == {"error": "Not found"}


def test_unknown_client_path_serves_spa_index(client, spa_index):
    r = client.get("/some/client/route")
    assert r.status_code == 200
    assert b'id="root"' in r.data


def test_root_serves_spa_index(client, spa_index):
    r = client.get("/")
    assert r.status_code == 200
    assert b'id="root"' in r.data
