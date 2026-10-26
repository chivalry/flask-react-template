# Issue #6: Add SQL Pagination, Test Helper, and Docs

## Context

Projects built from this template keep rediscovering the same helpers and lessons. This
adds them to the template, from the issue body and its comment of 2026-10-24:

- `paginate_select` (SQL `LIMIT` and `OFFSET` with a count subquery) beside the
  in-memory `paginate_and_dump`, sharing one envelope helper with `paginate()`;
  `parse_id_list` for `?ids=3,1,2`; and `parse_query_date` for a strict `YYYY-MM-DD`
- `require_unique_name()`, which raises a new `DuplicateRecordError` and compares names
  with straight and curly quotes folded together, so `fold_quotes` and
  `fold_quotes_in_sql` come with it; and `validate_ids_exist()` for id lists in a body
- `src_back/models/` as a package in place of `models.py`, and `src_back/auth.py`,
  which re-exports Flask-Login's `current_user` typed as `User`
- `persist()` in a new `src_back/tests/helpers.py`, used by the account fixtures
- the lessons in `ai/*.md`, a README section on starting a new project, and
  `plans/archive/.gitkeep`

The reference is hukilau, read through git objects. Where it differs from the issue:

- No shared envelope helper and no `persist` exist in any hukilau commit; both are new.
- `require_unique_name` is a module-level function,
  `require_unique_name(model, name, noun, except_id=None)`, not the `CRUDService`
  method the comment describes. Decided with the user: port the function.
- Routes map `DuplicateRecordError` to a 409 themselves with `conflict(str(exc))`;
  hukilau registers no app-level handler, and neither does this plan.
- The quote folding began in hukilau's `src_back/text.py`; hukilau PR #56, merged
  2026-10-23, moved it into `utils.py`, which is where this plan puts it.
- Two lessons, the 422 envelope and the react-refresh rule, exist only in hukilau's
  archived plan, not in its `ai/` files.
- The typed `current_user` comes from ranch-tracker (`f102c70`); hukilau has none.

Every edit below was applied by script to a scratch copy of this branch, where every
gate passed: Ruff check and format, pydoclint, the function-length check, basedpyright
(0 errors), pytest (146 passed, 100% coverage), markdownlint, Prettier, and `db check`
after `db upgrade` ("No new upgrade operations detected."). The same script generated
the code blocks below, so they are the tested text.

## Branch

`issue-6-add-sql-pagination-test-helper-and-docs` — already checked out; PR #41 exists.

## Change

**22 files: 14 edits, 7 new files, and 1 deletion.** New: `src_back/models/__init__.py`,
`src_back/models/base.py`, `src_back/models/user.py`, `src_back/auth.py`,
`src_back/services/errors.py`, `src_back/tests/helpers.py`, and
`plans/archive/.gitkeep`. Deleted: `src_back/models.py`. Edited: `src_back/api/auth.py`,
`src_back/utils.py`, `src_back/services/base.py`, `src_back/schemas/base.py`,
`src_back/tests/conftest.py`, `src_back/tests/test_utils.py`,
`src_back/tests/test_base_service.py`, `src_back/tests/test_schemas.py`,
`src_back/tests/test_auth.py`, `ai/project.md`, `ai/domain.md`, `ai/conventions.md`,
`README.md`, and `tools.md`.

How to read the edits:

- Line numbers refer to each file as it is on the branch now, before any edit. Apply a
  file's edits in the order given; each replaced block matches exactly one place.
- Copy blocks exactly. The Python is already Ruff-formatted, and the curly quotes in
  `utils.py`, `services/base.py`, and the tests are the real characters U+2018,
  U+2019, U+201C, and U+201D, which the quote-folding code and its tests depend on.

### `src_back/models/__init__.py` — new; re-exports every model

`app.py:154` (`from src_back import models`) and every `from src_back.models
import ...` keep working: this module imports both submodules and re-exports
their classes, so every table still registers on the shared metadata.

Create it with exactly this content:

```python
"""SQLAlchemy models, re-exported so ``from src_back.models import X`` keeps working.

Importing this package registers every table on the shared metadata, which is what
``db.create_all()`` and ``flask db migrate`` rely on, so a new model module is imported
here and its classes are added to ``__all__``.
"""

from src_back.models.base import BaseMixin
from src_back.models.user import Role, User

__all__ = ['BaseMixin', 'Role', 'User']
```

### `src_back/models/base.py` — new; `BaseMixin`

The class is `src_back/models.py:19-37` unchanged, and the module docstring keeps
the second paragraph of the old module docstring.

Create it with exactly this content:

```python
"""Shared mixin for every persisted model.

Every persisted model mixes in :class:`BaseMixin` for a surrogate key, a public
``uuid`` that is safe to expose in URLs, and audit timestamps.
"""

import uuid as uuid_lib
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column


class BaseMixin:
    """Surrogate key, public identifier, and audit timestamps.

    ``updated_at`` is refreshed by SQLAlchemy on every flush that changes the
    row, so services never set it by hand.
    """

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(
        String(36), unique=True, default=lambda: str(uuid_lib.uuid4())
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
```

### `src_back/models/user.py` — new; `Role` and `User`

`Role` and `User` are `src_back/models.py:40-91` unchanged.

Create it with exactly this content:

```python
"""Accounts and their roles."""

import enum

from flask_login import UserMixin
from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

from src_back.extensions import Base
from src_back.models.base import BaseMixin


class Role(enum.StrEnum):
    """Application roles.

    Only :attr:`admin` is privileged; see :func:`src_back.utils.admin_required`.
    New accounts receive :attr:`user` and are promoted out of band.
    """

    admin = 'admin'
    user = 'user'


class User(UserMixin, BaseMixin, Base):
    """An account that can sign in.

    The role is stored as a plain string column (``native_enum=False``) so the
    same migration works on PostgreSQL and SQLite.
    """

    __tablename__ = 'users'

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name='role', native_enum=False), default=Role.user
    )

    def set_password(self, password: str) -> None:
        """Hash a plaintext password and store it on the account.

        Args:
            password: The plaintext password to hash. Never persisted as-is.
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check a plaintext password against the stored hash.

        Args:
            password: The plaintext password submitted at sign-in.

        Returns:
            ``True`` when the password matches the stored hash.
        """
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        """Describe the account by email for logs and debugging.

        Returns:
            The repr string, for example ``<User a@b.test>``.
        """
        return f'<User {self.email}>'
```

### `src_back/models.py` — delete

Its contents now live in the three files above.

Delete the file.

### `src_back/auth.py` — new; `current_user` typed as `User`

Ported from ranch-tracker's `src_back/auth.py` (`f102c70`). In the scratch copy,
`reveal_type` showed Flask-Login's proxy as `LocalProxy[Any | None]`, this one as
`User`, and its `.role` as `Role`.

Create it with exactly this content:

```python
"""Typed access to the signed-in user.

Flask-Login's ``current_user`` reaches basedpyright as ``LocalProxy[Any | None]``:
reading ``role`` or ``id`` through it goes unchecked, and it cannot be passed where a
parameter is declared ``user: User``. Behind ``@login_required`` the proxy always
resolves to a real ``User``, so this module re-exports it under that type. Runtime
behavior is unchanged: the object is still Flask-Login's proxy.

Code that decides for itself whether anyone is signed in keeps importing from
``flask_login``: :func:`src_back.utils.admin_required` checks ``is_authenticated``,
so for it the value may genuinely be anonymous.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src_back.models import User

    current_user: User
else:
    from flask_login import current_user

__all__ = ['current_user']
```

### `src_back/api/auth.py` — import the typed `current_user`

`me()` (line 83) sits behind `@login_required`, so it is the first caller of the
typed proxy. `utils.admin_required` keeps Flask-Login's, as the new module's
docstring explains.

Replace lines 4-6:

```python
from flask_login import current_user, login_required, login_user, logout_user

from src_back.schemas.user import login_schema, user_schema
```

with:

```python
from flask_login import login_required, login_user, logout_user

from src_back.auth import current_user
from src_back.schemas.user import login_schema, user_schema
```

### `src_back/utils.py` — quote folding, query-string parsing, `paginate_select`

Ported from hukilau: `parse_id_list` and `paginate_select` from `0a47dcd`,
`parse_query_date` as amended in `5e58649`, and `fold_quotes` and
`fold_quotes_in_sql` from `3db8211`, which hukilau PR #56 moved into `utils.py`.
`_page_envelope` is new: `paginate()` and `paginate_select` share it, so both
compute `pages` the same way, zero-`per_page` guard included.

Edit 1 of 9: replace lines 4-5:

```python
HTTP status code, so route handlers can ``return`` one directly.
"""
```

with:

```python
HTTP status code, so route handlers can ``return`` one directly. The quote-folding
helpers compare text with straight and curly quotes treated as the same character.
"""
```

Edit 2 of 9: replace line 11:

```python
from datetime import UTC, datetime
```

with:

```python
from datetime import UTC, date, datetime
```

Edit 3 of 9: replace lines 18-22:

```python
from marshmallow import Schema
from werkzeug.datastructures import FileStorage
from werkzeug.security import safe_join

from src_back.models import Role
```

with:

```python
from marshmallow import Schema
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.base import ExecutableOption
from werkzeug.datastructures import FileStorage
from werkzeug.security import safe_join

from src_back.extensions import db
from src_back.models import Role
```

Edit 4 of 9: replace lines 27-28:

```python
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100
```

with:

```python
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100

QUOTE_FOLDS = {'‘': "'", '’': "'", '“': '"', '”': '"'}
"""Each curly quote and the straight quote it matches."""

_QUOTE_TRANSLATION = str.maketrans(QUOTE_FOLDS)
```

Edit 5 of 9: replace lines 121-124:

```python
    return str(uuid_lib.uuid4())


def pagination_args() -> tuple[int, int]:
```

with:

```python
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
```

Edit 6 of 9: replace line 146:

```python
def paginate(items: list[Any], page: int, per_page: int) -> dict[str, Any]:
```

with:

```python
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
```

Edit 7 of 9: replace lines 158-167:

```python
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
```

with:

```python
    start = (page - 1) * per_page
    return _page_envelope(items[start : start + per_page], len(items), page, per_page)
```

Edit 8 of 9: replace lines 186-188:

```python
    raw = request.get_json(silent=True)
    payload = raw if isinstance(raw, dict) else {}
    return cast(dict[str, Any], schema.load(payload, partial=partial))
```

with:

```python
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
```

Edit 9 of 9: replace lines 223-225:

```python
    if extra_fields:
        result.update(extra_fields)
    return jsonify(result), 200
```

with:

```python
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
```

### `src_back/services/errors.py` — new; `DuplicateRecordError`

hukilau's `services/errors.py`, holding only the class this issue needs; #7 adds
the others.

Create it with exactly this content:

```python
"""Exceptions services raise when a request breaks a business rule.

Route handlers catch them and answer with the matching envelope from
:mod:`src_back.utils`, such as :func:`~src_back.utils.conflict` for a 409.
"""


class DuplicateRecordError(Exception):
    """A unique natural key, such as a name or an email, is already taken (409)."""
```

### `src_back/services/base.py` — `require_unique_name()`

hukilau's module-level function (`8eaa232`), importing the quote folding from
`utils.py` as hukilau has since PR #56.

Edit 1 of 2: replace line 1:

```python
"""Generic base classes for the service layer.
```

with:

```python
"""Generic base classes and shared checks for the service layer.
```

Edit 2 of 2: replace lines 13-16:

```python
from src_back.extensions import Base, db


class CRUDService[T: Base]:
```

with:

```python
from src_back.extensions import Base, db
from src_back.services.errors import DuplicateRecordError
from src_back.utils import fold_quotes, fold_quotes_in_sql


def require_unique_name(
    model: type[Any], name: str, noun: str, except_id: int | None = None
) -> None:
    """Check that no other row has the name, whatever its quote style.

    Case still counts: ``Buyer`` and ``buyer`` may coexist, ``O'Neil`` and ``O’Neil``
    may not. Services call it from ``create`` and ``update`` before writing.

    Args:
        model: The table; it must have ``id`` and ``name`` columns.
        name: The name the caller wants to store.
        noun: The singular word for the message, such as ``project`` or ``widget``.
        except_id: The id of the row being updated, which may keep its own name;
            ``None`` on create.

    Raises:
        DuplicateRecordError: If a different row already has the name; the message
            names that row as stored.
    """
    query = db.session.query(model).filter(
        fold_quotes_in_sql(model.name) == fold_quotes(name)
    )
    if except_id is not None:
        query = query.filter(model.id != except_id)
    existing = query.first()
    if existing is not None:
        raise DuplicateRecordError(f'A {noun} named {existing.name} already exists.')


class CRUDService[T: Base]:
```

### `src_back/schemas/base.py` — `validate_ids_exist()`

hukilau's function from `3db8211`, with a longer docstring.

Edit 1 of 3: replace line 1:

```python
"""Base Marshmallow schema shared by every model-backed schema."""
```

with:

```python
"""Base Marshmallow schema and the validators shared by model-backed schemas."""
```

Edit 2 of 3: replace lines 6-8:

```python
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema

from src_back.extensions import db
```

with:

```python
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from sqlalchemy import func, select

from src_back.extensions import db
from src_back.models import BaseMixin
```

Edit 3 of 3: replace lines 39-40:

```python
            if field.allow_none and field.load_default is marshmallow.missing:
                field.load_default = None
```

with:

```python
            if field.allow_none and field.load_default is marshmallow.missing:
                field.load_default = None


def validate_ids_exist(model: type[BaseMixin], ids: list[int] | None, label: str) -> None:
    """Reject an id list that names a row which does not exist.

    One ``COUNT ... WHERE id IN (...)`` query checks the whole list, and a repeated id
    counts once. Call it from a schema's ``@validates`` method, so an unknown id fails
    the request with a 422.

    Args:
        model: The table the ids must belong to.
        ids: The ids from the payload, or ``None`` when the list was omitted.
        label: The singular noun for the message, such as ``tag``.

    Raises:
        marshmallow.ValidationError: If any id matches no row.
    """
    if not ids:
        return
    wanted = set(ids)
    found = db.session.scalar(select(func.count(model.id)).where(model.id.in_(wanted)))
    if found != len(wanted):
        raise marshmallow.ValidationError(f'Unknown {label} id.')
```

### `src_back/tests/helpers.py` — new; `persist()`

`src_back/tests/*` is outside coverage (`pyproject.toml:65`). The type parameter
uses PEP 695 syntax, which Ruff's `UP047` requires.

Create it with exactly this content:

```python
"""Helpers shared by the backend tests."""

from src_back.extensions import Base, db


def persist[T: Base](record: T) -> T:
    """Add a record to the session, commit it, and return it.

    Args:
        record: The new model instance to save.

    Returns:
        The same record, now committed.
    """
    db.session.add(record)
    db.session.commit()
    return record
```

### `src_back/tests/conftest.py` — the account fixtures use `persist()`

Edit 1 of 3: replace line 15:

```python
from src_back.models import BaseMixin, Role, User
```

with:

```python
from src_back.models import BaseMixin, Role, User
from src_back.tests.helpers import persist
```

Edit 2 of 3: replace lines 79-82:

```python
    u.set_password('password123')
    _db.session.add(u)
    _db.session.commit()
    return u
```

with:

```python
    u.set_password('password123')
    return persist(u)
```

Edit 3 of 3: replace lines 88-91:

```python
    u.set_password('adminpass123')
    _db.session.add(u)
    _db.session.commit()
    return u
```

with:

```python
    u.set_password('adminpass123')
    return persist(u)
```

### `src_back/tests/test_utils.py` — tests for the new helpers

hukilau's tests, typed, plus direct cases for `parse_query_date`'s round-trip
check (`20261014`, `2026-W42-3`), which hukilau exercised only through its API.
SQLAlchemy 2.0 drops loader options when a select becomes a subquery (in the
scratch copy even `joinedload` left a count unchanged), so no test can observe
"page query only" from the count; the loader-options test reads the SQL it ran
to prove the option reaches the page query.

Edit 1 of 6: replace lines 3-14:

```python
from collections.abc import Callable
from pathlib import Path

import pytest
from flask import Blueprint, Flask, Response, jsonify
from flask.testing import FlaskClient
from marshmallow import Schema, ValidationError, fields
from werkzeug.datastructures import FileStorage

from src_back.models import User
from src_back.tests.conftest import PNG_BYTES
from src_back.utils import (
```

with:

```python
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from flask import Blueprint, Flask, Response, jsonify
from flask.testing import FlaskClient
from flask_sqlalchemy import SQLAlchemy
from marshmallow import Schema, ValidationError, fields
from sqlalchemy import event, literal, select
from sqlalchemy.orm import defer
from werkzeug.datastructures import FileStorage

from src_back.models import User
from src_back.schemas.base import BaseSchema
from src_back.tests.conftest import PNG_BYTES, Widget
from src_back.tests.helpers import persist
from src_back.utils import (
```

Edit 2 of 6: replace lines 22-23:

```python
    dump_or_404,
    forbidden,
```

with:

```python
    dump_or_404,
    fold_quotes,
    fold_quotes_in_sql,
    forbidden,
```

Edit 3 of 6: replace lines 28-30:

```python
    paginate_and_dump,
    pagination_args,
    parse_request_json,
```

with:

```python
    paginate_and_dump,
    paginate_select,
    pagination_args,
    parse_id_list,
    parse_query_date,
    parse_request_json,
```

Edit 4 of 6: replace lines 168-170:

```python
def test_parse_request_json_partial_allows_missing_required_fields(app: Flask) -> None:
    with app.test_request_context('/', method='PUT', json={}):
        assert parse_request_json(NameSchema(), partial=True) == {}
```

with:

```python
def test_parse_request_json_partial_allows_missing_required_fields(app: Flask) -> None:
    with app.test_request_context('/', method='PUT', json={}):
        assert parse_request_json(NameSchema(), partial=True) == {}


# -- parse_id_list ------------------------------------------------------------


def test_parse_id_list_keeps_request_order_and_skips_blanks(app: Flask) -> None:
    with app.test_request_context('/?ids=3,1,,2'):
        assert parse_id_list('ids') == [3, 1, 2]


def test_parse_id_list_is_empty_when_absent(app: Flask) -> None:
    with app.test_request_context('/'):
        assert parse_id_list('ids') == []


def test_parse_id_list_rejects_an_entry_that_is_not_an_integer(app: Flask) -> None:
    with (
        app.test_request_context('/?ids=1,x'),
        pytest.raises(ValueError, match='ids must be a comma-separated list of ids'),
    ):
        parse_id_list('ids')


# -- parse_query_date ---------------------------------------------------------


@pytest.mark.parametrize('path', ['/', '/?due=', '/?due=+'])
def test_parse_query_date_is_none_when_absent_or_blank(app: Flask, path: str) -> None:
    with app.test_request_context(path):
        assert parse_query_date('due') is None


def test_parse_query_date_reads_an_iso_date(app: Flask) -> None:
    with app.test_request_context('/?due=2026-10-14'):
        assert parse_query_date('due') == date(2026, 10, 14)


@pytest.mark.parametrize(
    'value', ['tomorrow', '2026-13-01', '10/14/2026', '20261014', '2026-W42-3']
)
def test_parse_query_date_rejects_any_other_form(app: Flask, value: str) -> None:
    with (
        app.test_request_context('/', query_string={'due': value}),
        pytest.raises(ValueError, match='due must be a date in YYYY-MM-DD form'),
    ):
        parse_query_date('due')
```

Edit 5 of 6: replace lines 206-207:

```python
    assert status == 200
    assert response.get_json()['total_amount'] == '12.34'
```

with:

```python
    assert status == 200
    assert response.get_json()['total_amount'] == '12.34'


# -- paginate_select ----------------------------------------------------------


class WidgetSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = Widget


def _three_widgets() -> None:
    for name in ('a', 'b', 'c'):
        persist(Widget(name=name))


def test_paginate_select_returns_one_sql_page_with_the_envelope(app: Flask) -> None:
    _three_widgets()
    with app.test_request_context('/?page=2&per_page=2'):
        response, status = paginate_select(
            select(Widget).order_by(Widget.id), WidgetSchema()
        )
    assert status == 200
    body = response.get_json()
    assert [item['name'] for item in body['items']] == ['c']
    assert (body['total'], body['page'], body['pages'], body['per_page']) == (3, 2, 2, 2)


def test_paginate_select_applies_loader_options_to_the_page_query(
    app: Flask, db: SQLAlchemy
) -> None:
    _three_widgets()
    statements: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_rest: object) -> None:
        statements.append(statement)

    event.listen(db.engine, 'before_cursor_execute', record)
    try:
        with app.test_request_context('/?per_page=10'):
            response, _ = paginate_select(
                select(Widget).order_by(Widget.id), WidgetSchema(), defer(Widget.name)
            )
    finally:
        event.remove(db.engine, 'before_cursor_execute', record)
    # The deferred column is missing from the page query; dumping loads it per row.
    page_query = next(sql for sql in statements if 'LIMIT' in sql)
    assert 'widgets.name' not in page_query
    body = response.get_json()
    assert [item['name'] for item in body['items']] == ['a', 'b', 'c']
    assert (body['total'], body['pages']) == (3, 1)


def test_paginate_select_with_no_rows_reports_zero_pages(app: Flask) -> None:
    with app.test_request_context('/'):
        response, _ = paginate_select(select(Widget), WidgetSchema())
    assert response.get_json() == {
        'items': [],
        'total': 0,
        'page': 1,
        'pages': 0,
        'per_page': DEFAULT_PER_PAGE,
    }
```

Edit 6 of 6: replace lines 354-357:

```python
def test_new_uuid_returns_string_parseable_as_uuid() -> None:
    value = new_uuid()
    assert len(value) == 36
    assert str(uuid.UUID(value)) == value
```

with:

```python
def test_new_uuid_returns_string_parseable_as_uuid() -> None:
    value = new_uuid()
    assert len(value) == 36
    assert str(uuid.UUID(value)) == value


# -- fold_quotes and fold_quotes_in_sql ---------------------------------------


@pytest.mark.parametrize(
    ('text', 'folded'),
    [
        ('O’Neil', "O'Neil"),
        ('‘quoted’', "'quoted'"),
        ('“Ranch”', '"Ranch"'),
        ('O\'Neil "Ranch"', 'O\'Neil "Ranch"'),
    ],
)
def test_fold_quotes_makes_curly_quotes_straight(text: str, folded: str) -> None:
    assert fold_quotes(text) == folded


def test_fold_quotes_in_sql_matches_the_python_fold(db: SQLAlchemy) -> None:
    value = '“O’Neil‘s”'
    folded = db.session.scalar(select(fold_quotes_in_sql(literal(value))))
    assert folded == fold_quotes(value) == '"O\'Neil\'s"'
```

### `src_back/tests/test_base_service.py` — tests for `require_unique_name()`

hukilau's test from `8eaa232`, typed.

Edit 1 of 2: replace lines 1-5:

```python
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect

from src_back.services.base import ChildRecordService, CRUDService
from src_back.tests.conftest import Widget, WidgetNote
```

with:

```python
import pytest
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect

from src_back.services.base import ChildRecordService, CRUDService, require_unique_name
from src_back.services.errors import DuplicateRecordError
from src_back.tests.conftest import Widget, WidgetNote
```

Edit 2 of 2: replace lines 201-204:

```python
def test_child_default_after_delete_is_a_no_op(db: SQLAlchemy) -> None:
    note = _make_note(db, _make_widget(db))
    service = ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id)
    assert service.after_delete(note) is None
```

with:

```python
def test_child_default_after_delete_is_a_no_op(db: SQLAlchemy) -> None:
    note = _make_note(db, _make_widget(db))
    service = ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id)
    assert service.after_delete(note) is None


# -- require_unique_name ------------------------------------------------------


def test_require_unique_name_ignores_quote_style_but_not_case(db: SQLAlchemy) -> None:
    widget = _make_widget(db, "O'Neil")
    with pytest.raises(DuplicateRecordError) as raised:
        require_unique_name(Widget, 'O’Neil', 'widget')
    assert str(raised.value) == "A widget named O'Neil already exists."
    assert require_unique_name(Widget, 'O’Neil', 'widget', except_id=widget.id) is None
    assert require_unique_name(Widget, "o'neil", 'widget') is None
```

### `src_back/tests/test_schemas.py` — tests for `validate_ids_exist()`

hukilau tested `validate_ids_exist` only through its API; these call it directly
with the `Widget` test model.

Edit 1 of 2: replace lines 8-10:

```python
from src_back.schemas.base import BaseSchema
from src_back.schemas.user import login_schema, user_schema
from src_back.tests.conftest import WidgetNote
```

with:

```python
from src_back.schemas.base import BaseSchema, validate_ids_exist
from src_back.schemas.user import login_schema, user_schema
from src_back.tests.conftest import Widget, WidgetNote
from src_back.tests.helpers import persist
```

Edit 2 of 2: replace lines 68-69:

```python
def test_user_repr_names_the_email(app: Flask) -> None:
    assert repr(User(email='a@b.test')) == '<User a@b.test>'
```

with:

```python
def test_user_repr_names_the_email(app: Flask) -> None:
    assert repr(User(email='a@b.test')) == '<User a@b.test>'


@pytest.mark.parametrize('ids', [None, []])
def test_validate_ids_exist_accepts_an_omitted_or_empty_list(
    app: Flask, ids: list[int] | None
) -> None:
    assert validate_ids_exist(Widget, ids, 'widget') is None


def test_validate_ids_exist_counts_a_repeated_known_id_once(app: Flask) -> None:
    widget = persist(Widget(name='a'))
    assert validate_ids_exist(Widget, [widget.id, widget.id], 'widget') is None


def test_validate_ids_exist_rejects_an_unknown_id(app: Flask) -> None:
    widget = persist(Widget(name='a'))
    with pytest.raises(ValidationError, match='Unknown widget id.'):
        validate_ids_exist(Widget, [widget.id, widget.id + 1], 'widget')
```

### `src_back/tests/test_auth.py` — the typed proxy is Flask-Login's

Edit 1 of 2: replace lines 3-6:

```python
from flask import g
from flask.testing import FlaskClient

from src_back.app import SESSION_LIFETIME_DAYS
```

with:

```python
import flask_login
from flask import g
from flask.testing import FlaskClient

from src_back import auth
from src_back.app import SESSION_LIFETIME_DAYS
```

Edit 2 of 2: replace lines 170-172:

```python
def test_me_unauthenticated(client: FlaskClient) -> None:
    r = client.get('/api/v1/auth/me')
    assert r.status_code == 401
```

with:

```python
def test_me_unauthenticated(client: FlaskClient) -> None:
    r = client.get('/api/v1/auth/me')
    assert r.status_code == 401


def test_typed_current_user_is_flask_logins_proxy() -> None:
    assert auth.current_user is flask_login.current_user
```

### `ai/project.md` — intro, Project Structure, Database, Environment

Edit 1 also repairs the intro, which tells the reader to replace "the
application" below, a phrase the file no longer contains.

Edit 1 of 4: replace lines 3-5:

```markdown
Replace "the application" below with the project's name and purpose when starting a
project from this template. The sections describe the layout, the commands, and the
database rules that every contributor and agent follows.
```

with:

```markdown
Replace this paragraph with the project's name and purpose when starting a project from
this template. The sections describe the layout, the commands, and the database rules
that every contributor and agent follows.
```

Edit 2 of 4: replace lines 11-18:

```markdown
    - `models.py` - SQLAlchemy models; split into a `models/` package when it grows
    - `schemas/` - Marshmallow schemas; `schemas/base.py` holds `BaseSchema`
    - `services/` - business logic by domain; `services/base.py` holds the generic
      `CRUDService` and `ChildRecordService`
    - `tests/` - pytest; one `test_<module>.py` per module
    - `app.py` - application factory, error handlers, SPA and upload serving
    - `extensions.py` - shared Flask extensions and the declarative `Base`
    - `utils.py` - error envelopes, pagination, request parsing, upload validation
```

with:

```markdown
    - `models/` - SQLAlchemy models, one module per domain; `base.py` holds
      `BaseMixin`, `user.py` holds `Role` and `User`, and `__init__.py` re-exports every
      model, so `from src_back.models import User` works and every table registers
    - `schemas/` - Marshmallow schemas; `schemas/base.py` holds `BaseSchema` and
      `validate_ids_exist()`
    - `services/` - business logic by domain; `services/base.py` holds the generic
      `CRUDService`, `ChildRecordService`, and `require_unique_name()`, and
      `services/errors.py` the exceptions services raise
    - `tests/` - pytest; one `test_<module>.py` per module; `helpers.py` holds
      `persist()`
    - `app.py` - application factory, error handlers, SPA and upload serving
    - `auth.py` - `current_user` typed as `User`, for routes behind `@login_required`
    - `extensions.py` - shared Flask extensions and the declarative `Base`
    - `utils.py` - error envelopes, pagination in memory and in SQL, query-string
      parsing, quote folding, upload validation
```

Edit 3 of 4: replace line 68:

```markdown
  with `db upgrade`. Files are named `YYYY_MM_DD_<rev>_<slug>.py`.
```

with:

```markdown
  with `db upgrade`, and confirm with `db check`, which must report that no new upgrade
  operations were detected. Files are named `YYYY_MM_DD_<rev>_<slug>.py`.
- Every foreign key declares `ondelete`, and a parent's collection of child rows also
  sets `cascade='all, delete-orphan'`. The SQLite test database does not enforce
  foreign keys, so only the ORM cascade makes a delete there behave as it does on
  PostgreSQL.
```

Edit 4 of 4: replace line 86:

```markdown
`FLASK_ENV=development`, the app refuses to start with a placeholder `SECRET_KEY`.
```

with:

```markdown
`FLASK_ENV=development`, the app refuses to start with a placeholder `SECRET_KEY`.

`src_back/app.py` calls `load_dotenv()` at import, so `.env` values are visible to pytest
too. A test that depends on an environment variable sets or clears it with
`monkeypatch` first, as the `FLASK_ENV` and `CORS_ALLOWED_ORIGINS` tests in
`src_back/tests/test_app.py` do.
```

### `ai/domain.md` — `persist()` and the Flask-Login cache

The template's tests drop the cached user with `g.pop` (`test_auth.py:139-145`,
`test_app.py:133-145`); hukilau's lesson adds the fresh context for a second
client.

Replace line 26:

```markdown
- `PNG_BYTES` - a minimal PNG for upload tests
```

with:

```markdown
- `PNG_BYTES` - a minimal PNG for upload tests

`src_back/tests/helpers.py` provides `persist(record)`, which adds a record, commits it,
and returns it; use it instead of repeating those three lines.

The `app` fixture keeps one application context pushed for the whole test, and every
test-client request reuses it. Flask-Login caches the loaded user on `g` for that
context, so the cache outlives a request: to make the next request read the session
cookie again, drop it with `g.pop('_login_user', None)`, as `test_auth.py` and
`test_app.py` do, and run a second client's requests inside a fresh `app.app_context()`
so the two clients do not share one cached user.
```

### `ai/conventions.md` — the new helpers and two frontend rules

The 422 and react-refresh rules come from hukilau's plan
(`plans/archive/hukilau-implementation.md:906-910`), the only place hukilau wrote
them down.

Edit 1 of 5: replace lines 19-20:

```markdown
  failure), a service does the work, and `jsonify(schema.dump(...))`, `dump_or_404`,
  or `paginate_and_dump` builds the response.
```

with:

```markdown
  failure), a service does the work, and `jsonify(schema.dump(...))`, `dump_or_404`,
  `paginate_and_dump` (slices a loaded list), or `paginate_select` (applies `LIMIT`
  and `OFFSET` in SQL with a count subquery, for tables too large to load whole)
  builds the response.
- `parse_id_list(name)` reads a query parameter such as `?ids=3,1,2` and
  `parse_query_date(name)` a strict `YYYY-MM-DD` date; both raise `ValueError`, which
  the handler answers with `bad_request(str(exc))`.
```

Edit 2 of 5: replace lines 25-26:

```markdown
  `create()` and `update()` keep the URL's parent id authoritative over any parent id
  in the body.
```

with:

```markdown
  `create()` and `update()` keep the URL's parent id authoritative over any parent id
  in the body.
- A service that keeps names unique calls `require_unique_name()` from
  `services/base.py` in `create` and `update`. It compares names with straight and
  curly quotes treated alike but case still counting, and raises `DuplicateRecordError`
  from `services/errors.py`, which the handler answers with `conflict(str(exc))`.
```

Edit 3 of 5: replace lines 33-34:

```markdown
  Auto schemas omit foreign-key columns; a child schema that accepts the parent id
  in the body sets `include_fk = True`.
```

with:

```markdown
  Auto schemas omit foreign-key columns; a child schema that accepts the parent id
  in the body sets `include_fk = True`. A schema that accepts a list of ids checks it
  in a `@validates` method with `validate_ids_exist(model, ids, label)`, one `COUNT`
  query, so an unknown id fails with a 422.
```

Edit 4 of 5: replace line 39:

```markdown
  `@login_required` or `@admin_required` (401 for anonymous callers, 403 for non-admins).
```

with:

```markdown
  `@login_required` or `@admin_required` (401 for anonymous callers, 403 for non-admins).
  Routes behind `@login_required` import `current_user` from `src_back/auth.py`, where
  it is typed as `User`; code that checks `is_authenticated` itself, such as
  `admin_required`, keeps Flask-Login's.
```

Edit 5 of 5: replace lines 77-78:

```markdown
- Forms use React Hook Form with Zod schemas; request errors surface through
  `useApiError`.
```

with:

```markdown
- Forms use React Hook Form with Zod schemas; request errors surface through
  `useApiError`. The 422 envelope carries no field details (`app.py` only logs them),
  so the Zod schemas enforce every backend validation rule; otherwise the user sees
  just "Invalid request".
- Component files export only components: `react-refresh/only-export-components` warns
  on any other export except a primitive constant, and CI fails on warnings, so shared
  constants and helpers live in `.ts` modules.
```

### `README.md` — "Starting a new project" and the layout tree

The list is the issue's, plus the `package-lock.json` name fields and the
`ai/project.md` intro. The `plans/archive/` paragraph gives the new `.gitkeep`
its purpose.

Edit 1 of 2: replace lines 18-20:

```markdown
[`tools.md`](tools.md) says why each tool and library in the repository is here.

## Quick start (local, no Docker)
```

with:

```markdown
[`tools.md`](tools.md) says why each tool and library in the repository is here.

## Starting a new project

After creating a repository from this template, replace the template's name and
placeholders:

- `name` in `package.json`, the two matching `name` fields at the top of
  `package-lock.json`, and `name` in `.devcontainer/devcontainer.json`
- `COMPOSE_PROJECT_NAME` and `APP_NAME` in `.env.example`, and in `.env` if it already
  exists
- the fallback project name on the first line of `docker-compose.yml`
- the `<title>` in `src_front/index.html`
- the app bar title in `src_front/src/components/layout/AppShell.tsx`, and the tests
  that expect it, `src_front/src/test/App.test.tsx` and
  `src_front/src/test/AppShell.test.tsx`
- this README's title and the `my-app` placeholders in its commands
- the placeholder paragraphs at the top of `ai/project.md` and `ai/domain.md`

`plans/archive/` holds the template's own finished plans. Delete them if the new project
should start without that history; `plans/archive/.gitkeep` keeps the folder.

## Quick start (local, no Docker)
```

Edit 2 of 2: replace lines 134-136:

```markdown
│   ├── app.py         # Application factory, error handlers, SPA and uploads
│   ├── extensions.py  # db (SQLAlchemy 2 Base), migrate, login_manager
│   ├── models.py      # BaseMixin, Role, User
```

with:

```markdown
│   ├── app.py         # Application factory, error handlers, SPA and uploads
│   ├── auth.py        # current_user typed as User
│   ├── extensions.py  # db (SQLAlchemy 2 Base), migrate, login_manager
│   ├── models/        # Package: base.py has BaseMixin, user.py has Role and User
```

### `tools.md` — the Werkzeug entry names `models/user.py`

The path moves with the package; the lines rewrap to stay within 90.

Replace lines 41-44:

```markdown
  pinned on its own. The code uses it directly for password hashing in
  `src_back/models.py`, for the `NotFound` exception the SPA fallback catches when no
  build is present, and for the `FileStorage` type and `safe_join` in the upload
  helpers.
```

with:

```markdown
  pinned on its own. The code uses it directly for password hashing in
  `src_back/models/user.py`, for the `NotFound` exception the SPA fallback catches
  when no build is present, and for the `FileStorage` type and `safe_join` in the
  upload helpers.
```

### `plans/archive/.gitkeep` — new

`plans/archive/` holds files today, so the `.gitkeep` matters once a project
deletes the template's plans, as the README now offers.

Create it as an empty file.

## Parallelism

Each group edits its own files, so all four run as one parallel batch. The groups import
from one another (the services import the quote folding from `utils.py`, and the tests
import `persist`), which matters only once tests run, after the whole batch.

- **A, models and auth**: the three `src_back/models/` files, the deletion of
  `src_back/models.py` (in the same step, since the package would otherwise shadow
  it), `src_back/auth.py`, `src_back/api/auth.py`, `src_back/tests/helpers.py`,
  `src_back/tests/conftest.py`, and `src_back/tests/test_auth.py`
- **B, utils**: `src_back/utils.py` and `src_back/tests/test_utils.py`
- **C, services and schemas**: `src_back/services/errors.py`,
  `src_back/services/base.py`, `src_back/schemas/base.py`,
  `src_back/tests/test_base_service.py`, and `src_back/tests/test_schemas.py`
- **D, docs**: `ai/project.md`, `ai/domain.md`, `ai/conventions.md`, `README.md`,
  `tools.md`, and `plans/archive/.gitkeep`

After the batch, run Verification steps 1 to 4 in order.

## No other changes needed

- `src_back/app.py`: `from src_back.models import User` (line 23) and
  `from src_back import models` (line 154) work unchanged against the package.
- `migrations/`: the split changes no table, which Verification step 2 confirms.
- `src_back/services/auth.py`: `register_user` keeps raising `ValueError`, which
  `api/auth.py` maps to a 409; #28 rewrites registration and can move it to
  `DuplicateRecordError`.
- `admin_required` in `src_back/utils.py` keeps Flask-Login's `current_user`: it checks
  `is_authenticated`, so the user may be anonymous there.
- No app-level `DuplicateRecordError` handler: no template route raises it yet, and
  hukilau's routes map it themselves.
- `_make_widget` and `_make_note` in `src_back/tests/test_base_service.py` keep their
  inline add and commit; the issue moves only the conftest fixtures to `persist()`.
- No frontend code: the README lists the frontend files a new project renames, and the
  conventions now carry the 422 and react-refresh rules.
- hukilau's `is_active` column on `User` is not ported; it belongs to #7 and #28.
- Noticed, out of scope:
    - The issue forms, `.github/workflows/assign-issues.yml`, and
      `scripts/hook-issue-assign.sh` assign issues to `chivalry`. That is the owner's
      login, not the template's name, so the README list leaves it out; a project
      someone else owns changes it as well.
    - The `admin_client` fixture (`src_back/tests/conftest.py:103-109`) is used by no
      test.

## Verification

1. **Targeted tests**, once the batch is done:

    ```bash
    .venv/bin/python -m pytest src_back/tests/test_utils.py \
      src_back/tests/test_base_service.py src_back/tests/test_schemas.py \
      src_back/tests/test_auth.py --no-cov
    ```

2. **No schema drift from the package split.** Migrate a throwaway SQLite database,
   then check it; the second command must print `No new upgrade operations detected.`

    ```bash
    db="$(mktemp -d)/check.db"
    DATABASE_URL="sqlite:///$db" FLASK_ENV=development \
      .venv/bin/flask --app src_back.app db upgrade
    DATABASE_URL="sqlite:///$db" FLASK_ENV=development \
      .venv/bin/flask --app src_back.app db check
    ```

3. **No stale path**: `git grep -n 'models\.py' -- ':!plans'` prints nothing.
4. **Full gates**, in one parallel batch: `npm run test`, `npm run lint`,
   `npm run lint:py`, `npm run lint:md`, and `npx prettier --check .`. The scratch copy
   passed every backend and Markdown gate; ESLint and the frontend suite see no change
   but run as part of the standard set.
