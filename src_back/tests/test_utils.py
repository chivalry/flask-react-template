
from src_back.utils import admin_required, paginate, pagination_args


def test_paginate_first_page():
    items = list(range(50))
    result = paginate(items, page=1, per_page=20)
    assert result["items"] == list(range(20))
    assert result["total"] == 50
    assert result["page"] == 1
    assert result["pages"] == 3
    assert result["per_page"] == 20


def test_paginate_second_page():
    items = list(range(50))
    result = paginate(items, page=2, per_page=20)
    assert result["items"] == list(range(20, 40))


def test_paginate_last_page_partial():
    items = list(range(25))
    result = paginate(items, page=2, per_page=20)
    assert result["items"] == list(range(20, 25))
    assert result["pages"] == 2


def test_paginate_empty_list():
    result = paginate([], page=1, per_page=20)
    assert result["items"] == []
    assert result["total"] == 0
    assert result["pages"] == 0


def test_pagination_args_defaults(app):
    with app.test_request_context("/"):
        page, per_page = pagination_args()
    assert page == 1
    assert per_page == 20


def test_pagination_args_from_query(app):
    with app.test_request_context("/?page=3&per_page=50"):
        page, per_page = pagination_args()
    assert page == 3
    assert per_page == 50


def test_pagination_args_clamps_per_page(app):
    with app.test_request_context("/?per_page=999"):
        _, per_page = pagination_args()
    assert per_page == 100


def test_pagination_args_invalid_values(app):
    with app.test_request_context("/?page=abc&per_page=xyz"):
        page, per_page = pagination_args()
    assert page == 1
    assert per_page == 20


def test_admin_required_allows_admin(app, admin_user):
    from flask import Blueprint, jsonify


    bp = Blueprint("test_admin", __name__)

    @bp.get("/test-admin")
    @admin_required
    def admin_view():
        return jsonify({"ok": True})

    app.register_blueprint(bp)
    client = app.test_client()
    client.post(
        "/api/v1/auth/login",
        json={"email": admin_user.email, "password": "adminpass123"},
    )
    r = client.get("/test-admin")
    assert r.status_code == 200


def test_admin_required_blocks_regular_user(app, user):
    from flask import Blueprint, jsonify


    bp = Blueprint("test_user", __name__)

    @bp.get("/test-user")
    @admin_required
    def user_view():
        return jsonify({"ok": True})

    app.register_blueprint(bp)
    client = app.test_client()
    client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    r = client.get("/test-user")
    assert r.status_code == 403
