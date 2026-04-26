import uuid as uuid_lib
from datetime import datetime, timezone

from flask import jsonify


def bad_request(message: str = "Bad request"):
    return jsonify({"error": message}), 400


def not_found(message: str = "Not found"):
    return jsonify({"error": message}), 404


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid_lib.uuid4())
