"""Shared helpers for JSON error envelopes, pagination, request parsing, and uploads.

Every error helper returns the ``{'error': message}`` envelope paired with its
HTTP status code, so route handlers can ``return`` one directly. The quote-folding
helpers compare text with straight and curly quotes treated as the same character.
"""

import functools
import math
import uuid as uuid_lib
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import filetype
from flask import Response, current_app, jsonify, request
from flask_login import current_user
from marshmallow import Schema
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.base import ExecutableOption
from werkzeug.datastructures import FileStorage
from werkzeug.security import safe_join

from src_back.extensions import db
from src_back.models import Role

ALLOWED_IMAGE_EXTENSIONS = frozenset({'.jpg', '.jpeg', '.png', '.gif', '.webp'})
ALLOWED_IMAGE_MIMES = frozenset({'image/jpeg', 'image/png', 'image/gif', 'image/webp'})

DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100

QUOTE_FOLDS = {'‘': "'", '’': "'", '“': '"', '”': '"'}
"""Each curly quote and the straight quote it matches."""

_QUOTE_TRANSLATION = str.maketrans(QUOTE_FOLDS)

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


def fold_quotes(text: str) -> str:
    """Replace curly quotes with their straight equivalents.

    Args:
        text: The text to fold.

    Returns:
        The text with every curly single or double quote made straight.
    """
    return text.translate(_QUOTE_TRANSLATION)


def fold_quotes_in_sql(
    expression: ColumnElement[Any] | QueryableAttribute[Any],
) -> ColumnElement[Any]:
    """Wrap a column in nested ``replace()`` calls that make curly quotes straight.

    ``replace()`` exists in SQLite and PostgreSQL, so the SQL is the same on both.

    Args:
        expression: The column, mapped attribute, or expression to fold.

    Returns:
        The folded expression.
    """
    folded = expression.expression
    for curly, straight in QUOTE_FOLDS.items():
        folded = func.replace(folded, curly, straight)
    return folded


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


def _page_envelope(items: object, total: int, page: int, per_page: int) -> dict[str, Any]:
    """Wrap one page of items in the metadata every paginated response carries.

    Args:
        items: The page's items, as records or already serialized.
        total: The number of items across every page.
        page: The 1-based page number.
        per_page: The page size; zero reports a single page.

    Returns:
        A mapping with ``items``, ``total``, ``page``, ``pages``, and ``per_page``.
    """
    return {
        'items': items,
        'total': total,
        'page': page,
        'pages': math.ceil(total / per_page) if per_page else 1,
        'per_page': per_page,
    }


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
    start = (page - 1) * per_page
    return _page_envelope(items[start : start + per_page], len(items), page, per_page)


def parse_request_json(schema: Schema, *, partial: bool = False) -> dict[str, Any]:
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


def parse_id_list(name: str) -> list[int]:
    """Read a comma-separated list of integer ids from the query string.

    Args:
        name: The query parameter to read.

    Returns:
        The ids in request order, with blank entries skipped; empty when the
        parameter is absent.

    Raises:
        ValueError: If any entry is not an integer.
    """
    raw = request.args.get(name, '')
    try:
        return [int(part) for part in raw.split(',') if part.strip()]
    except ValueError as exc:
        raise ValueError(f'{name} must be a comma-separated list of ids.') from exc


def parse_query_date(name: str) -> date | None:
    """Read an optional ``YYYY-MM-DD`` date from the query string.

    ``date.fromisoformat`` also accepts compact and ISO week dates, such as ``20261014``
    and ``2026-W42-3``, so the parsed date must format back to the value unchanged.

    Args:
        name: The query parameter to read.

    Returns:
        The date, or ``None`` when the parameter is absent or blank.

    Raises:
        ValueError: If the value is not a real date in ``YYYY-MM-DD`` form.
    """
    raw = request.args.get(name, '').strip()
    if not raw:
        return None
    message = f'{name} must be a date in YYYY-MM-DD form.'
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(message) from exc
    if parsed.isoformat() != raw:
        raise ValueError(message)
    return parsed


def dump_or_404(record: object, schema: Schema) -> tuple[Response, int]:
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


def paginate_select(
    stmt: Select[Any], schema: Schema, *options: ExecutableOption
) -> tuple[Response, int]:
    """Run one page of an ORM ``select`` and serialize it with the usual envelope.

    Unlike :func:`paginate_and_dump`, which slices a list already in memory, this
    applies ``LIMIT`` and ``OFFSET`` in SQL and counts with a subquery, so it suits
    tables too large to load whole. Loader options apply to the page query only,
    which keeps the count a plain select.

    ``total`` counts the rows ``stmt`` returns, so a join that multiplies them, such
    as one to a child table used for filtering, inflates it: filter with ``EXISTS``
    (``Model.children.any(...)``) instead. Load a page's collections with
    ``selectinload``, which adds one query rather than multiplying rows.

    Args:
        stmt: The ORM select, already filtered and ordered.
        schema: The schema used to serialize each row.
        *options: Loader options, such as ``selectinload``, for the page rows.

    Returns:
        The pagination envelope with serialized ``items`` and status 200.
    """
    page, per_page = pagination_args()
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.session.scalar(count_stmt) or 0
    window = stmt.limit(per_page).offset((page - 1) * per_page)
    if options:
        window = window.options(*options)
    items = db.session.scalars(window).all()
    envelope = _page_envelope(schema.dump(items, many=True), total, page, per_page)
    return jsonify(envelope), 200


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


def validate_image_file(file: FileStorage) -> ErrorResponse | None:
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
    ext = Path(file.filename or '').suffix.lower()
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


def delete_upload(filename: str | None) -> None:
    """Remove a stored upload from ``UPLOAD_FOLDER``, ignoring one already gone.

    Call it after the commit that stops referencing the file, as a service's
    ``after_delete`` does, so a failed commit never leaves a row pointing at a
    removed file. An empty name does nothing, and a name that would resolve
    outside ``UPLOAD_FOLDER`` is ignored, just as ``send_from_directory``
    refuses to serve one.

    Args:
        filename: Path of the file relative to ``UPLOAD_FOLDER``, as the record
            stores it, or ``None`` for a record without a file.
    """
    if not filename:
        return
    path = safe_join(current_app.config['UPLOAD_FOLDER'], filename)
    if path is not None:
        Path(path).unlink(missing_ok=True)


def admin_required[**P, R](f: Callable[P, R]) -> Callable[P, R | ErrorResponse]:
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
    def decorated(*args: P.args, **kwargs: P.kwargs) -> R | ErrorResponse:
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
