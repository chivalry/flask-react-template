"""Shared helpers for JSON error envelopes, pagination, request parsing, and uploads.

Every error helper returns the ``{'error': message}`` envelope paired with its
HTTP status code, so route handlers can ``return`` one directly.
"""

import functools
import math
import os
import uuid as uuid_lib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import filetype
from flask import Response, jsonify, request
from flask_login import current_user
from marshmallow import Schema

from src_back.models import Role

ALLOWED_IMAGE_EXTENSIONS = frozenset({'.jpg', '.jpeg', '.png', '.gif', '.webp'})
ALLOWED_IMAGE_MIMES = frozenset({'image/jpeg', 'image/png', 'image/gif', 'image/webp'})

DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100

ErrorResponse = tuple[Response, int]
"""A JSON error envelope paired with its HTTP status code."""


def bad_request(message: str = 'Bad request') -> ErrorResponse:
    """Build a 400 Bad Request JSON error response.

    Args:
        message: Human-readable explanation placed under the ``error`` key.

    Returns:
        The JSON error envelope paired with the status code 400.
    """
    return jsonify({'error': message}), 400


def unauthorized(message: str = 'Unauthorized') -> ErrorResponse:
    """Build a 401 Unauthorized JSON error response.

    Args:
        message: Human-readable explanation placed under the ``error`` key.

    Returns:
        The JSON error envelope paired with the status code 401.
    """
    return jsonify({'error': message}), 401


def forbidden(message: str = 'Forbidden') -> ErrorResponse:
    """Build a 403 Forbidden JSON error response.

    Args:
        message: Human-readable explanation placed under the ``error`` key.

    Returns:
        The JSON error envelope paired with the status code 403.
    """
    return jsonify({'error': message}), 403


def not_found(message: str = 'Not found') -> ErrorResponse:
    """Build a 404 Not Found JSON error response.

    Args:
        message: Human-readable explanation placed under the ``error`` key.

    Returns:
        The JSON error envelope paired with the status code 404.
    """
    return jsonify({'error': message}), 404


def conflict(message: str = 'Conflict') -> ErrorResponse:
    """Build a 409 Conflict JSON error response.

    Args:
        message: Human-readable explanation placed under the ``error`` key.

    Returns:
        The JSON error envelope paired with the status code 409.
    """
    return jsonify({'error': message}), 409


def unprocessable_entity(message: str = 'Unprocessable entity') -> ErrorResponse:
    """Build a 422 Unprocessable Entity JSON error response.

    Args:
        message: Human-readable explanation placed under the ``error`` key.

    Returns:
        The JSON error envelope paired with the status code 422.
    """
    return jsonify({'error': message}), 422


def now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Returns:
        The current moment in UTC.
    """
    return datetime.now(UTC)


def new_uuid() -> str:
    """Generate a random UUID4 in its canonical hyphenated form.

    Returns:
        The generated identifier as a string.
    """
    return str(uuid_lib.uuid4())


def pagination_args() -> tuple[int, int]:
    """Read the pagination query parameters with safe defaults.

    Unparseable values fall back to the defaults rather than raising, so a
    malformed query string still yields a usable page.

    Returns:
        The 1-based page number and the page size. ``page`` is at least 1 and
        defaults to 1; ``per_page`` is clamped to ``1..MAX_PER_PAGE`` and
        defaults to ``DEFAULT_PER_PAGE``.
    """
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(MAX_PER_PAGE, max(1, int(request.args.get('per_page', 20))))
    except (TypeError, ValueError):
        per_page = DEFAULT_PER_PAGE
    return page, per_page


def paginate(items: list[Any], page: int, per_page: int) -> dict[str, Any]:
    """Slice an in-memory list into one page and wrap it with metadata.

    Args:
        items: The full result set to slice.
        page: The 1-based page number to return.
        per_page: Maximum number of items on the page.

    Returns:
        A mapping with the sliced ``items`` plus the ``total`` item count, the
        echoed ``page`` and ``per_page``, and the total number of ``pages``.
    """
    total = len(items)
    pages = math.ceil(total / per_page) if per_page else 1
    start = (page - 1) * per_page
    return {
        'items': items[start : start + per_page],
        'total': total,
        'page': page,
        'pages': pages,
        'per_page': per_page,
    }


def parse_request_json(schema: Schema, partial: bool = False) -> dict[str, Any]:
    """Parse and validate the JSON request body against a Marshmallow schema.

    A missing, non-JSON, or non-object body is validated as an empty mapping, so
    required fields surface as ordinary validation errors. A failed validation
    propagates as a ``marshmallow.ValidationError``, which the application-level
    handler in :mod:`src_back.app` turns into a 422 envelope, so route handlers
    only ever see valid data.

    Args:
        schema: The schema to load the body with.
        partial: Whether to accept a partial payload, as for an update.

    Returns:
        The validated payload as a plain dict.
    """
    raw = request.get_json(silent=True)
    payload = raw if isinstance(raw, dict) else {}
    return cast(dict[str, Any], schema.load(payload, partial=partial))


def dump_or_404(record: Any, schema: Schema) -> tuple[Response, int]:
    """Serialize a record with status 200, or answer 404 when it is missing.

    Args:
        record: The ORM instance to serialize, or ``None`` when not found.
        schema: The schema used to serialize the record.

    Returns:
        The serialized record with status 200, or a 404 error envelope.
    """
    if record is None:
        return not_found()
    return jsonify(schema.dump(record)), 200


def paginate_and_dump(
    items: list[Any], schema: Schema, extra_fields: dict[str, Any] | None = None
) -> tuple[Response, int]:
    """Paginate items from the current request's query string and serialize them.

    Args:
        items: The full list of ORM instances already fetched.
        schema: The schema used to serialize each item.
        extra_fields: Extra keys merged into the envelope beside the pagination
            keys, such as aggregates computed over the full list.

    Returns:
        The pagination envelope with serialized ``items`` and status 200.
    """
    page, per_page = pagination_args()
    result = paginate(items, page, per_page)
    result['items'] = schema.dump(result['items'], many=True)
    if extra_fields:
        result.update(extra_fields)
    return jsonify(result), 200


def require_parent(getter: Callable[[int], Any], parent_id: int) -> ErrorResponse | None:
    """Answer 404 when a nested route's parent record does not exist.

    Call this first in every nested child route so a child can only be reached
    through a parent that exists. The getter must return ``None`` for a missing
    record rather than raise.

    Args:
        getter: Looks up the parent by primary key.
        parent_id: The parent's primary key from the URL.

    Returns:
        ``None`` when the parent exists, otherwise a 404 error envelope to return.
    """
    if getter(parent_id) is None:
        return not_found()
    return None


def validate_image_file(file: Any) -> ErrorResponse | None:
    """Validate an uploaded file's extension and sniffed MIME type.

    Reads the leading 512 bytes to detect the real content type, then seeks
    back to the start so the caller can still save the stream. A file whose
    extension is allowed but whose sniffed type is not gets rejected, so
    renaming a non-image does not slip through.

    Args:
        file: The uploaded file object, as provided by ``request.files``.

    Returns:
        ``None`` when the file is a permitted image type, otherwise a 400 error
        envelope.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return bad_request('Invalid file type')
    header = file.read(512)
    try:
        file.seek(0)
    except OSError:
        return bad_request('Invalid file type')
    kind = filetype.guess(header)
    if kind is None or kind.mime not in ALLOWED_IMAGE_MIMES:
        return bad_request('Invalid file type')
    return None


def admin_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Restrict a route to authenticated users with the ``admin`` role.

    Apply beneath the route decorator. Anonymous callers get 401 and signed-in
    non-admins get 403, matching the application's error handlers.

    Args:
        f: The view function to protect.

    Returns:
        The wrapped view, which short-circuits with an error envelope unless the
        current user is an authenticated admin.
    """

    @functools.wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        """Reject non-admin callers before running the wrapped view.

        Args:
            *args: Positional arguments forwarded to the wrapped view.
            **kwargs: Keyword arguments forwarded to the wrapped view.

        Returns:
            The wrapped view's response, or a 401 or 403 error envelope.
        """
        if not current_user.is_authenticated:
            return unauthorized()
        if current_user.role != Role.admin:
            return forbidden('Admin access required.')
        return f(*args, **kwargs)

    return decorated
