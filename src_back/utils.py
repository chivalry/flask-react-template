import functools
import math
import uuid as uuid_lib
from datetime import UTC, datetime
from typing import Any

from flask import jsonify, request
from flask_login import current_user


def bad_request(message: str = "Bad request"):
    return jsonify({"error": message}), 400


def not_found(message: str = "Not found"):
    return jsonify({"error": message}), 404


def forbidden(message: str = "Forbidden"):
    return jsonify({"error": message}), 403


def conflict(message: str = "Conflict"):
    return jsonify({"error": message}), 409


def now() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid_lib.uuid4())


def pagination_args() -> tuple[int, int]:
    """Return (page, per_page) parsed from query params with safe defaults."""
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    except (TypeError, ValueError):
        per_page = 20
    return page, per_page


def paginate(items: list[Any], page: int, per_page: int) -> dict:
    """Slice a list and return a pagination envelope."""
    total = len(items)
    pages = math.ceil(total / per_page) if per_page else 1
    start = (page - 1) * per_page
    return {
        "items": items[start : start + per_page],
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
    }


def admin_required(f):
    """Decorator: require the current user to have role 'admin'."""

    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            return forbidden("Admin access required.")
        return f(*args, **kwargs)

    return decorated
