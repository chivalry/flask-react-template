# Issue #17: Add an opt-in audit log to the generic services

## Context

Business applications built from the template need to answer who changed a record and
what changed; the template keeps only `created_at` and `updated_at`. This ports
ranch-tracker's audit log (`/Users/chuck/Projects/clients/connel/ranch-tracker/staging`,
clean at `922eaae`: `src_back/services/common/{audit_log,base}.py`,
`api/audit_logs.py`, `schemas/common/audit_log.py`, and the three tabs under
`src_front/src/components/`), without the two things the issue rejects (a `user`
argument on every mutating method, a hand-kept table allowlist) and without the
defects found reading it. Nothing audit-related exists yet. Reused as they are:
`paginate_select`, `parse_id_list`, `admin_required`, `fetchPage`, `useUsers`,
`QueryState`, and `utils/dates.ts`; `useInfiniteList`, `flattenPages`,
`lastLoadedPageTotal`, and `InfiniteScrollSentinel` (#7's fold-ins) get their first
production consumer here.

Facts that shape the design:

- `src_back/services/users.py` is plain functions, not a `CRUDService` (`create_user`
  66-84, `update_user` 87-116), and no production code uses `CRUDService` or
  `ChildRecordService` yet. Accounts therefore opt in through the helper the generic
  services use (`AuditTrail`), not through constructor arguments.
- Outside a request, Flask-Login's `current_user` stands for `None`
  (`flask_login/utils.py:367-374`); most service tests run with only an app context.
  In an anonymous request it is an `AnonymousUserMixin`, which has no `id`.
- Neither generic `create` flushes (`services/base.py` 104-105, 250-251), so an
  audited create flushes to get the id before logging.
- The generic services know records only as `T: Base`, which declares no columns, and
  Ruff's `ANN401` rejects a bare `Any` parameter (probed). The audit helpers take
  `record: object` and read attributes, `id` included, with `getattr`; Ruff's `B009`
  is not enabled.
- SQLite keeps no offset on stored datetimes, so a bound in another zone compares
  wrongly (probed), and it does not enforce foreign keys; the ORM's default one-to-many
  delete nulls the children's key instead (probed), which matches PostgreSQL's
  `ON DELETE SET NULL`.

Choices this plan makes beyond the issue text:

1. **Account history is admin-only.** The users table registers with
   `admin_only=True`, so a non-admin asking for a user's history gets 403. Otherwise any
   signed-in user could read every account's email, role, and active state by walking
   ids, though only admins may list accounts. Ranch-tracker has the same rule
   (`_ADMIN_ONLY_TABLE_NAMES`). Other audited tables stay readable by everyone signed
   in, as the issue says.
2. **The admin's date range travels as instants.** `/audit-logs/all` takes
   `changed_from` (inclusive) and `changed_before` (exclusive), ISO 8601 moments with an
   offset; the tab turns its inclusive range of local days into the local midnights
   that bound it. Ranch-tracker sends `YYYY-MM-DD` and reads UTC days, so an admin in
   California filtering through today misses every change made after 5 PM.
3. **Every account creation is logged.** Self-registration and the seeded first admin
   log `created` entries too, with no actor, so an account's history always starts with
   its creation. The users trail lives in `services/auth.py`, which already owns
   account creation and which `services/users.py` and `seed.py` import from (the
   reverse import would be circular).
4. **A deleted entry keeps the record.** It holds the record's audited fields
   (ranch-tracker stores `{}`), and it is added after `before_delete()` rather than
   before: a `before_delete` that refuses (`RecordInUseError`) then leaves no pending
   entry for a later commit in the same app context to save, as a test or a script
   would. The columns are the same either way.
5. **Both history routes page.** One record's history pages through `paginate_select`
   like the admin log (ranch-tracker returns a bare array), so both tabs share one
   infinite table. Entries order by `changed_at`, then `id`, newest first, and the table
   drops an entry that a later page repeats, as new entries push older ones down while
   an admin scrolls.
6. **Decimals and UUIDs become strings,** and times ISO text; ranch-tracker's `float`
   loses precision at scale.
7. **Misconfiguration fails at import.** `AuditTrail` raises `ValueError` when an
   audited field or the label field is not an attribute of the model, instead of an
   `AttributeError` at the first save.
8. **`changed_by_name` is the email,** since accounts have no other name; the issue's
   field name stays, so a project that adds a display name changes one property.
9. **`AuditLog` mixes in `BaseMixin`,** as every model does, and keeps `changed_at`
   beside `created_at`: they agree for every entry this code writes, and `changed_at`
   stays the change's time if a project imports older history.
10. The actor comes from Flask-Login's `current_user`, not the typed one, because the
    lookup handles anonymous and request-less calls (`ai/conventions.md` 61-63).
11. `RecordAuditLogTab` ships with tests and no screen; the template has no record
    detail view until #18. Fallow counts test imports as use.

## Branch

`issue-17-add-an-opt-in-audit-log-to-the-generic` — already checked out; PR #49 exists.

## Change

**Backend, new**: `src_back/models/audit_log.py`, `src_back/services/audit_log.py`,
`src_back/schemas/audit_log.py`, `src_back/api/audit_logs.py`, the `audit_logs`
migration, `src_back/tests/test_audit_log.py`, `src_back/tests/test_audit_logs_api.py`.
**Backend, edit**: `src_back/models/{__init__,user}.py`,
`src_back/services/{base,auth,users}.py`, `src_back/seed.py`, `src_back/utils.py`,
`src_back/api/__init__.py`, `src_back/app.py`,
`src_back/tests/{test_base_service,test_users_api,test_auth,test_seed,test_utils}.py`.
**Frontend, new** (under `src_front/src/`): `types/auditLog.ts`, `api/auditLogs.ts`,
`hooks/auditLogs.ts`, `components/common/{AuditLogTab,RecordAuditLogTab}.tsx`,
`components/admin/AdminAuditLogTab.tsx`, and a test for each.
**Frontend, edit**: `utils/dates.ts`, `pages/AdminPage.tsx`,
`test/utils/{fixtures,dialogQueries}.ts`, `test/utils/dates.test.ts`,
`test/pages/AdminPage.test.tsx`.
**Docs**: `ai/conventions.md`, `ai/domain.md`, `ai/project.md`, `README.md`.

### src_back/models/audit_log.py — new

```python
"""The audit log: one row per change a service records, never edited afterwards."""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src_back.extensions import Base
from src_back.models.base import BaseMixin

if TYPE_CHECKING:
    from src_back.models.user import User


class AuditAction(enum.StrEnum):
    """What happened to the record an audit entry describes."""

    created = 'created'
    updated = 'updated'
    deleted = 'deleted'


class AuditLog(BaseMixin, Base):
    """One recorded change to one row of an audited table.

    ``record_id`` has no foreign key, so the entry outlives the record it describes.
    ``changes`` holds the record's audited fields for ``created`` and ``deleted``, and
    ``{field: {'old': ..., 'new': ...}}`` for each field an ``updated`` changed.
    ``changed_by_id`` is ``None`` for a change made outside a signed-in request, such
    as the seed's, and becomes ``None`` when that account is deleted.
    """

    __tablename__ = 'audit_logs'
    # One record's history is the lookup every detail view makes.
    __table_args__ = (
        Index('ix_audit_logs_table_name_record_id', 'table_name', 'record_id'),
    )

    table_name: Mapped[str] = mapped_column(String(100))
    record_id: Mapped[int] = mapped_column()
    record_label: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name='audit_action', native_enum=False)
    )
    changes: Mapped[dict[str, Any]] = mapped_column(JSON)
    changed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), index=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    changed_by: Mapped[User | None] = relationship(back_populates='audit_entries')

    @property
    def changed_by_name(self) -> str | None:
        """Name the account that made the change.

        Returns:
            Its email, since accounts have no other name, or ``None`` when no
            signed-in account made the change or that account was deleted.
        """
        return self.changed_by.email if self.changed_by is not None else None

    def __repr__(self) -> str:
        """Describe the entry by table, record, and action for logs and debugging.

        Returns:
            The repr string, for example ``<AuditLog widgets:4 updated>``.
        """
        return f'<AuditLog {self.table_name}:{self.record_id} {self.action}>'
```

`Mapped[User | None]` with the `TYPE_CHECKING` import resolves through the declarative
registry (probed in memory).

### src_back/models/user.py — `audit_entries`

- Imports (3-11): add `from typing import TYPE_CHECKING`, `relationship` to the
  `sqlalchemy.orm` import, and after the imports:

```python
if TYPE_CHECKING:
    from src_back.models.audit_log import AuditLog
```

- After `is_active` (63-65):

```python
    # No cascade: the entries outlive the account. Deleting the account sets their
    # changed_by_id to NULL here, as ON DELETE SET NULL does in PostgreSQL, because
    # the SQLite test database does not enforce foreign keys.
    audit_entries: Mapped[list['AuditLog']] = relationship(back_populates='changed_by')
```

`UserSchema` is an auto schema without `include_relationships`, so the user payload
does not change.

### `src_back/models/__init__.py` — re-export

```python
from src_back.models.audit_log import AuditAction, AuditLog
from src_back.models.base import BaseMixin
from src_back.models.user import Role, User

__all__ = ['AuditAction', 'AuditLog', 'BaseMixin', 'Role', 'User']
```

### migrations/versions — new `<date>_<rev>_audit_logs.py`

1. `docker compose up -d db`, then `.venv/bin/flask --app src_back.app db upgrade`.
2. `.venv/bin/flask --app src_back.app db migrate -m "audit logs"`.
3. Review it: `down_revision = '6437e01e246c'`. `create_table('audit_logs', ...)` holds
   `table_name` `String(100)`, `record_id` `Integer`, `record_label` `String(255)`
   nullable, `action` `sa.Enum('created', 'updated', 'deleted', name='audit_action',
   native_enum=False)`, `changes` `sa.JSON()`, `changed_by_id` `Integer` nullable,
   `changed_at` `DateTime(timezone=True)`, the four `BaseMixin` columns,
   `ForeignKeyConstraint(['changed_by_id'], ['users.id'], ondelete='SET NULL')`,
   `PrimaryKeyConstraint('id')`, and `UniqueConstraint('uuid')`; then indexes
   `ix_audit_logs_changed_at`, `ix_audit_logs_changed_by_id`, and
   `ix_audit_logs_table_name_record_id`. Downgrade drops the three indexes, then the
   table. Give the docstring one line under the header: "Append-only; record_id has no
   foreign key, so an entry outlives its record."
4. `db upgrade`, `db check` (no new upgrade operations), `db downgrade`, `db upgrade`,
   `db check`. Write `db downgrade`, not `db downgrade -1`: Click 8.5 reads `-1` as an
   unknown option, and one revision back is the default. Verification step 3 repeats
   this on a fresh database.

### src_back/services/audit_log.py — new

```python
"""The audit log: recording changes, and the queries that read them back.

A service opts in through an :class:`AuditTrail` for its model; the generic services
build one when given ``audit_fields``. Nothing here commits: an entry joins the
caller's transaction, so a change and its entry are saved or rolled back together.
"""

import decimal
import enum
import uuid as uuid_lib
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from types import MappingProxyType
from typing import Any

from flask import has_request_context
from flask_login import current_user
from sqlalchemy import Select, select

from src_back.extensions import db
from src_back.models import AuditAction, AuditLog

MASKED_VALUE = '********'
"""Stands in for a secret, such as a password, in an entry's changes."""

_LABEL_LENGTH = 255
"""The length of ``audit_logs.record_label``; a longer label is cut to fit."""

_AUDITED_TABLES: dict[str, bool] = {}
"""Each audited table, mapped to whether only admins may read its history."""

NEWEST_FIRST = (AuditLog.changed_at.desc(), AuditLog.id.desc())
"""The order of every history; the id breaks ties between entries made at once."""
```

Functions, in this order, each with a Google docstring (Args, Returns, Raises):

- `register_audited_table(table_name: str, *, admin_only: bool = False) -> None`:

```python
    _AUDITED_TABLES[table_name] = _AUDITED_TABLES.get(table_name, False) or admin_only
```

  Docstring: `AuditTrail` calls it, so the tables come from the services that opted in
  rather than a list kept by hand; once any trail makes a table admin-only it stays
  so, and a later trail for the same table cannot open its history.

- `audited_tables() -> Mapping[str, bool]` returns `MappingProxyType(_AUDITED_TABLES)`.
- `_json_safe(value: object) -> object`:

```python
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, decimal.Decimal | uuid_lib.UUID):
        return str(value)
    if isinstance(value, date | time):
        return value.isoformat()
    return value
```

  (`datetime` is a `date`. Ruff's `UP038` requires the `X | Y` form.)

- `snapshot(record: object, fields: Sequence[str]) -> dict[str, object]` returns
  `{name: _json_safe(getattr(record, name)) for name in fields}`.
- `diff(before: Mapping[str, object], after: Mapping[str, object])
  -> dict[str, dict[str, object]]` returns
  `{name: {'old': before[name], 'new': after[name]} for name in before if
  before[name] != after[name]}`.
- `_current_actor_id() -> int | None`; its docstring says why it uses Flask-Login's
  proxy (outside a request it stands for `None`; an anonymous caller has no `id`):

```python
    if has_request_context() and current_user.is_authenticated:
        return current_user.id
    return None
```

- `create_audit_entry(table_name: str, record_id: int, record_label: str | None,
  action: AuditAction, changes: Mapping[str, object]) -> AuditLog | None`: returns
  `None` when `action is AuditAction.updated and not changes`; otherwise builds
  `AuditLog(..., changes=dict(changes), changed_by_id=_current_actor_id())`, calls
  `db.session.add(entry)`, and returns it. Never flushes or commits; the docstring
  says the caller's commit saves the entry with the change.

```python
class AuditTrail:
    """How one table's records log their creates, updates, and deletes.

    Building one registers the table with the history routes. A service calls
    :meth:`log_created` after adding a record, takes :meth:`snapshot` before changing
    one and passes it to :meth:`log_updated` after, and calls :meth:`log_deleted`
    before deleting one, each before its commit. A service whose entries need more,
    such as a masked password, builds the changes itself and calls :meth:`log`.
    """

    def __init__(
        self,
        model: type[Any],
        fields: Sequence[str],
        label_field: str | None = 'name',
        *,
        admin_only: bool = False,
    ) -> None:
        names = list(fields) if label_field is None else [*fields, label_field]
        missing = [name for name in names if not hasattr(model, name)]
        if missing:
            joined = ', '.join(missing)
            raise ValueError(f'{model.__name__} has no attribute {joined}.')
        self.table_name: str = model.__tablename__
        self._fields = tuple(fields)
        self._label_field = label_field
        register_audited_table(self.table_name, admin_only=admin_only)
```

Methods (docstrings as in the class docstring's terms):

- `snapshot(self, record: object) -> dict[str, object]` →
  `snapshot(record, self._fields)`.
- `log(self, record: object, action: AuditAction, changes: Mapping[str, object])
  -> AuditLog | None`:

```python
        # The generic services know records only as Base, which declares no columns;
        # every audited model mixes in BaseMixin, so the id is there.
        record_id: int = getattr(record, 'id')
        return create_audit_entry(
            self.table_name, record_id, self._label(record), action, changes
        )
```

- `log_created(self, record: object) -> None`: `db.session.flush()` (assigns the id),
  then `self.log(record, AuditAction.created, self.snapshot(record))`.
- `log_updated(self, record: object, before: Mapping[str, object]) -> None`:
  `self.log(record, AuditAction.updated, diff(before, self.snapshot(record)))`. The
  label is read after the change, so a renamed record's entry carries its new name.
- `log_deleted(self, record: object) -> None`:
  `self.log(record, AuditAction.deleted, self.snapshot(record))`.
- `_label(self, record: object) -> str | None`: `None` when `_label_field` is `None`;
  otherwise the attribute's value, `None` if it is `None`, else
  `str(value)[:_LABEL_LENGTH]`.

Queries, after the class:

```python
def select_record_history(table_name: str, record_id: int) -> Select[tuple[AuditLog]]:
    return (
        select(AuditLog)
        .where(AuditLog.table_name == table_name, AuditLog.record_id == record_id)
        .order_by(*NEWEST_FIRST)
    )


def select_audit_entries(
    *,
    table_name: str | None = None,
    changed_by_ids: Sequence[int] = (),
    changed_from: datetime | None = None,
    changed_before: datetime | None = None,
) -> Select[tuple[AuditLog]]:
    stmt = select(AuditLog)
    if table_name is not None:
        stmt = stmt.where(AuditLog.table_name == table_name)
    if changed_by_ids:
        stmt = stmt.where(AuditLog.changed_by_id.in_(changed_by_ids))
    if changed_from is not None:
        stmt = stmt.where(AuditLog.changed_at >= changed_from)
    if changed_before is not None:
        stmt = stmt.where(AuditLog.changed_at < changed_before)
    return stmt.order_by(*NEWEST_FIRST)
```

(Docstrings omitted above; both say "ready for `paginate_select`", and the second
documents `changed_from` as inclusive and `changed_before` as exclusive.) This module
imports nothing from `src_back.services` or `src_back.utils`, and `utils` must keep
importing no service.

### src_back/services/base.py — `audit_fields` and `label_field`

- Imports (9-15): add `from collections.abc import Sequence` and
  `from src_back.services.audit_log import AuditTrail`.
- Both class docstrings (48-53, 168-175) gain: "Passing ``audit_fields`` opts the
  service into the audit log: :meth:`create`, :meth:`update`, and :meth:`delete` each
  add an entry, through an :class:`~src_back.services.audit_log.AuditTrail`, that
  their commit saves with the change."
- Both `__init__`s (55-63, 177-189) take keyword-only parameters after `*order_by`,
  documented in Args:

```python
        audit_fields: Sequence[str] = (),
        label_field: str | None = 'name',
        audit_admin_only: bool = False,
```

  and end with:

```python
        self._audit = (
            AuditTrail(model, audit_fields, label_field, admin_only=audit_admin_only)
            if audit_fields
            else None
        )
```

  Args text: `audit_fields`: "The columns each audit entry records; empty, the
  default, records nothing." `label_field`: "The attribute that names a record in its
  audit entries; ``None`` for no label." `audit_admin_only`: "Whether only admins may
  read a record's history." The last two say "Ignored without ``audit_fields``."

- `create` (both, after `db.session.add(record)` at 104 and 250):

```python
        if self._audit is not None:
            self._audit.log_created(record)
```

- `CRUDService.update` (118-123) and `ChildRecordService.update` (268-272): snapshot
  before the `setattr` loop, log after it, before the commit:

```python
        before = self._audit.snapshot(record) if self._audit is not None else {}
        for key, value in data.items():
            ...
        if self._audit is not None:
            self._audit.log_updated(record, before)
        db.session.commit()
```

- `delete` (both, right after `self.before_delete(record)` at 141 and 285):

```python
        if self._audit is not None:
            self._audit.log_deleted(record)
```

  Add to both `delete` docstrings: "An audited service logs the record after
  :meth:`before_delete`, so a ``before_delete`` that raises logs nothing."

### src_back/services/auth.py — the account trail; log registrations

- Import `from src_back.services.audit_log import AuditTrail`.
- After `_DUMMY_PASSWORD_HASH` (18):

```python
# Every place that creates or changes an account audits it through this trail:
# registration here, the admin's Users screen (services/users.py), and the seed. Only
# admins may read account histories, which carry every account's email and role. No
# password or hash is recorded; services/users.py logs a change as MASKED_VALUE.
USER_AUDIT_TRAIL = AuditTrail(
    User, ('email', 'role', 'is_active'), label_field='email', admin_only=True
)
```

- `register_user` (33-56): `USER_AUDIT_TRAIL.log_created(user)` between `add` (54) and
  `commit` (55). Docstring: "Its audit entry has no actor: nobody is signed in yet."

### src_back/services/users.py — log the admin's changes, mask passwords

- Imports (12-14): `from src_back.models import AuditAction, Role, User`,
  `from src_back.services.audit_log import MASKED_VALUE, diff`, and
  `from src_back.services.auth import USER_AUDIT_TRAIL, find_user_by_email`.
- Module docstring (1-5), append: "Every change is audited through
  :data:`~src_back.services.auth.USER_AUDIT_TRAIL`, with the admin as the actor."
- `create_user`: `USER_AUDIT_TRAIL.log_created(user)` between `add` (82) and `commit`
  (83).
- `update_user`: replace 110-115 with:

```python
    before = USER_AUDIT_TRAIL.snapshot(user)
    for key in ('email', 'role', 'is_active'):
        if key in data:
            setattr(user, key, data[key])
    changes = diff(before, USER_AUDIT_TRAIL.snapshot(user))
    if 'password' in data:
        # Record that the password changed, never a password or its hash.
        old_password = MASKED_VALUE if user.has_password else None
        user.set_password(data['password'])
        changes['password'] = {'old': old_password, 'new': MASKED_VALUE}
    USER_AUDIT_TRAIL.log(user, AuditAction.updated, changes)
    db.session.commit()
```

  Docstring, before Args: "The audit entry lists only what changed; a new password
  shows as ``MASKED_VALUE``, with no old value for an account that had no password."
  The checks at 106-109 still run first, so a refused update logs nothing. The
  function stays under 50 lines.

### src_back/seed.py — log the first admin

Import `USER_AUDIT_TRAIL` with `find_user_by_email` (30). In `_seed_admin`, replace
`db.session.flush()` (75) with `USER_AUDIT_TRAIL.log_created(user)`, which flushes, so
the step still only flushes. Docstring: "Its creation is audited, with no actor."

### src_back/utils.py — `parse_query_datetime`

After `parse_query_date` (265-290); `UTC` and `datetime` are already imported (12):

```python
def parse_query_datetime(name: str) -> datetime | None:
    """Read an optional ISO 8601 moment, with its UTC offset, from the query string.

    The moment comes back in UTC: SQLite stores datetimes without an offset, so a
    bound in another zone would compare as if it were UTC.

    Args:
        name: The query parameter to read.

    Returns:
        The moment in UTC, or ``None`` when the parameter is absent or blank.

    Raises:
        ValueError: If the value is not a date and time with an offset, such as
            ``2026-10-14T07:00:00Z``.
    """
    raw = request.args.get(name, '').strip()
    if not raw:
        return None
    message = f'{name} must be an ISO 8601 date and time with a UTC offset.'
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(message) from exc
    if parsed.tzinfo is None:
        raise ValueError(message)
    return parsed.astimezone(UTC)
```

### src_back/schemas/audit_log.py — new

```python
"""Audit-log serialization; entries are only ever dumped, never loaded."""

from marshmallow import fields

from src_back.models import AuditAction, AuditLog
from src_back.schemas.base import BaseSchema


class AuditLogSchema(BaseSchema):
    """Serialize audit entries for the history routes.

    Every field is dump-only: no route accepts an entry. ``changed_by_name`` reads
    :attr:`~src_back.models.AuditLog.changed_by_name`, so a route loads the
    ``changed_by`` relationship with its page.
    """

    class Meta(BaseSchema.Meta):
        """Bind to the ``audit_logs`` table, keeping its foreign key."""

        model = AuditLog
        include_fk = True
        dump_only = (
            *BaseSchema.AUDIT,
            'table_name',
            'record_id',
            'record_label',
            'changes',
            'changed_by_id',
            'changed_at',
        )

    action = fields.Enum(AuditAction, by_value=True, dump_only=True)
    changed_by_name = fields.String(dump_only=True)


audit_log_schema = AuditLogSchema()
```

The JSON column auto-maps to `fields.Raw`.

### src_back/api/audit_logs.py — new; registered in `api/__init__.py` and `app.py`

```python
bp = Blueprint('audit_logs', __name__)

_WITH_ACTOR = joinedload(AuditLog.changed_by)
"""Loads each page's actors in the page query; changed_by_name reads them."""


@bp.get('')
@login_required
def list_record_history() -> tuple[Response, int]:
    table_name = request.args.get('table_name', '')
    admin_only = audited_tables().get(table_name)
    if admin_only is None:
        return not_found('No history is kept for that table.')
    record_id = request.args.get('record_id', type=int)
    if record_id is None:
        return bad_request('record_id must be an integer.')
    if admin_only and current_user.role != Role.admin:
        return forbidden('Admin access required.')
    stmt = select_record_history(table_name, record_id)
    return paginate_select(stmt, audit_log_schema, _WITH_ACTOR)


@bp.get('/all')
@admin_required
def list_audit_log() -> tuple[Response, int]:
    try:
        changed_by_ids = parse_id_list('changed_by_id')
        changed_from = parse_query_datetime('changed_from')
        changed_before = parse_query_datetime('changed_before')
    except ValueError as exc:
        return bad_request(str(exc))
    stmt = select_audit_entries(
        table_name=request.args.get('table_name') or None,
        changed_by_ids=changed_by_ids,
        changed_from=changed_from,
        changed_before=changed_before,
    )
    return paginate_select(stmt, audit_log_schema, _WITH_ACTOR)


@bp.get('/tables')
@admin_required
def list_audited_tables() -> tuple[Response, int]:
    return jsonify(sorted(audited_tables())), 200
```

- Imports: `Blueprint, Response, jsonify, request` from flask; `login_required` from
  flask_login; `joinedload` from `sqlalchemy.orm`; the typed `current_user` from
  `src_back.auth` (the route is behind `@login_required`); `AuditLog, Role` from
  models; `audit_log_schema`; `audited_tables, select_audit_entries,
  select_record_history` from `services/audit_log`; and `admin_required, bad_request,
  forbidden, not_found, paginate_select, parse_id_list, parse_query_datetime` from
  utils.
- Module docstring: "Audit-log routes: one record's history, the admin's filtered log,
  and the audited tables." Each handler's docstring lists its error envelopes; the
  record route's says the table check comes first, so an unknown table is 404 whatever
  the other parameters, and a non-admin gets 403 for an admin-only table.
- `/all` accepts any `table_name`, audited now or not, so entries from a table that
  stopped being audited stay reachable; `/tables` lists only registered ones.
- `api/__init__.py`: `from src_back.api.audit_logs import bp as audit_logs_bp`, and
  `__all__ = ['audit_logs_bp', 'auth_bp', 'health_bp', 'users_bp']`.
- `app.py` `_register_blueprints` (227-231): import `audit_logs_bp` with the others and
  register it last with `url_prefix='/api/v1/audit-logs'`.

### Backend tests

Assertion style follows the files they join. `select`, `func`, `persist`, and the
fixtures are imported as the neighbors do. Count rows with
`db.session.scalar(select(func.count(AuditLog.id)))` and read them with
`db.session.scalars(select(AuditLog).order_by(AuditLog.id)).all()`.

**Registry rule.** Building an `AuditTrail` registers its table for the rest of the
run, and `services/auth.py` registers `users` when it is first imported, which may be
the first `create_app()` (`app.py` 227). A test that needs a known registry replaces it
with `monkeypatch.setattr(audit_log, '_AUDITED_TABLES', {...})`, where `audit_log` is
`src_back.services.audit_log`, and requests `app`, directly or through `db`, so the app
is built and `users` registered before the patch; a test whose body does not use `app`
requests it with `@pytest.mark.usefixtures('app')`, as `test_users_api.py` does for
`user`. pytest sets up autouse fixtures before requested ones, so an autouse fixture
that patches takes `app` as a parameter.

**`src_back/tests/test_audit_log.py` — new**

- `# -- snapshot and diff`
    - `test_snapshot_makes_every_value_json_safe`: a `SimpleNamespace` holding
      `Decimal('12.50')`, `date(2026, 10, 14)`, an aware `datetime`, `time(9, 5)`,
      `Role.admin`, `UUID(int=1)`, `None`, `3`, `True`, and `'alpha'` snapshots to
      `'12.50'`, `'2026-10-14'`, the datetime's `isoformat()`, `'09:05:00'`,
      `'admin'`, `'00000000-0000-0000-0000-000000000001'`, `None`, `3`, `True`,
      `'alpha'`, and `json.dumps` accepts the result.
    - `test_diff_lists_only_changed_fields`.
- `# -- create_audit_entry`
    - `test_entry_is_added_without_a_commit(db)`: the entry is in `db.session.new`;
      after `db.session.rollback()` no row exists.
    - `test_update_that_changed_nothing_is_skipped(db)`: `updated` with `{}` returns
      `None` and adds nothing; `deleted` with `{}` still returns an entry.
    - `test_entry_outside_a_request_has_no_actor(db)`.
    - `test_entry_in_an_anonymous_request_has_no_actor(app)`: inside
      `app.test_request_context()`.
    - `test_entry_in_a_signed_in_request_names_the_actor(app, user)`: inside
      `app.test_request_context()`, `login_user(user)` first; finish with
      `g.pop('_login_user', None)` (`ai/domain.md` 46-51).
- `# -- AuditTrail and the registry`
    - `test_trail_registers_its_table(monkeypatch)`, using `app`: with an empty registry,
      `AuditTrail(Widget, ('name',))` then
      `AuditTrail(WidgetNote, ('body',), None, admin_only=True)` leave
      `{'widgets': False, 'widget_notes': True}`; a later
      `AuditTrail(WidgetNote, ('body',), None)` leaves `widget_notes` admin-only; and
      `audited_tables()['x'] = True` raises `TypeError` (that line carries
      `# pyright: ignore[reportIndexIssue]`, as `models/user.py:63` does).
    - `test_trail_rejects_attributes_the_model_lacks(monkeypatch)`, using `app`:
      `('nope',)` raises `ValueError('Widget has no attribute nope.')`;
      `AuditTrail(WidgetNote,
      ('body',))`, whose default label `name` is missing, raises
      `'WidgetNote has no attribute name.'`; the registry stays empty.
    - `test_trail_labels_entries(db)`: call `log(..., AuditAction.deleted, {})` on
      `SimpleNamespace` records, which adds entries without a flush, never on saved
      widgets: `Widget.name` is `String(100)` (`conftest.py:34`), so PostgreSQL in CI
      would refuse a long one. `SimpleNamespace(id=1, name='n' * 300)` gives a
      255-character label; `body=None` under `label_field='body'` gives `None`; a trail
      with `label_field=None` gives `None`.
- `# -- AuditLog`
    - `test_deleting_an_account_keeps_its_entries_without_an_actor(db, user)`:
      persist an entry with `changed_by_id=user.id`, delete the user and commit;
      after `db.session.refresh(entry)`, `changed_by_id` and `changed_by_name` are
      `None` (the acceptance criterion; on PostgreSQL the foreign key agrees).
    - `test_entry_names_its_actor_and_describes_itself(db, admin_user)`:
      `changed_by_name == 'admin@test.com'`; `repr` is
      `'<AuditLog widgets:1 created>'`.

**`src_back/tests/test_base_service.py` — new `# -- auditing` section before
`# -- require_unique_name` (209)**

Helpers: `_audited_widgets()` returns
`CRUDService(Widget, Widget.name, audit_fields=('name',))`; `_audited_notes()` returns
`ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id, audit_fields=('body',),
label_field=None)`; `_entries(db)` returns every entry in id order. The existing 22
tests stay as they are.

- `test_services_without_audit_fields_write_and_register_nothing(db, monkeypatch)`:
  with an empty registry, plain services of both kinds create, update, and delete; no
  entry exists and the registry is still empty.
- `test_audited_create_logs_the_new_record(db)`: one entry with `table_name='widgets'`,
  the new id, label `'gamma'`, `action=created`, `changes={'name': 'gamma'}`, and no
  actor.
- `test_audited_service_records_the_signed_in_actor(app, user)`: inside
  `app.test_request_context()`, `login_user(user)`, then
  `_audited_widgets().create({'name': 'x'})`; the entry's `changed_by_id` is
  `user.id`. Finish with `g.pop('_login_user', None)`.
- `test_audited_service_can_keep_its_history_from_non_admins(db, monkeypatch)`: with
  an empty registry, `CRUDService(Widget, Widget.name, audit_fields=('name',),
  audit_admin_only=True)` registers `{'widgets': True}`.
- `test_audited_create_entry_shares_the_records_transaction(db, monkeypatch)`: with
  `db.session.commit` replaced by a function that raises `RuntimeError`, `create`
  raises; after `monkeypatch.undo()` and `db.session.rollback()`, neither a widget nor
  an entry exists.
- `test_audited_update_logs_only_the_change(db)`: `alpha` renamed `beta` logs
  `{'name': {'old': 'alpha', 'new': 'beta'}}` with label `'beta'`.
- `test_audited_update_that_changes_nothing_logs_nothing(db)`.
- `test_audited_delete_logs_the_record(db)`: `changes={'name': 'alpha'}`, label
  `'alpha'`, and the widget is gone.
- `test_audited_delete_refused_by_before_delete_logs_nothing(db)`: a `CRUDService`
  subclass, audited, whose `before_delete` raises `RecordInUseError('in use', 1)`;
  after `pytest.raises`, no `AuditLog` is in `db.session.new`.
- `test_audited_child_create_update_and_delete(db)`: create logs `{'body': 'one'}` with
  no label; an update that also carries `widget_id` of another widget logs only the
  body change; a no-op update logs nothing; delete logs `{'body': 'two'}`.

**`src_back/tests/test_audit_logs_api.py` — new**

Constants `HISTORY_URL = '/api/v1/audit-logs'`, `ALL_URL`, `TABLES_URL`. An autouse
fixture `_pin_audited_tables(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None`
pins the registry to `{'users': True, 'widgets': False}`. A helper
`_entry(table_name='widgets', record_id=1, *, changed_at=..., changed_by=None,
changes=None) -> AuditLog` persists one entry (default changes
`{'name': {'old': 'a', 'new': 'b'}}`). Pass filters with `query_string={...}` so
offsets are encoded.

- `test_routes_reject_anonymous_callers` (parametrized over the three routes) → 401.
- `test_admin_routes_forbid_non_admins` (`/all`, `/tables`, as `auth_client`) → 403.
- `test_record_history_is_newest_first_and_only_that_record(auth_client, admin_user)`:
  entries for widgets#1 at 10:00 and 12:00 (by the admin), widgets#2, and users#1;
  the response is the envelope (`total == 2`, `page == 1`, `pages == 1`,
  `per_page == 20`) with the 12:00 entry first, `changed_by_name` the admin's email,
  and `None` for the entry without an actor.
- `test_history_breaks_ties_by_id`: two entries at one instant, the newer id first.
- `test_record_history_pages` (`per_page=2&page=2` of three).
- `test_unaudited_table_has_no_history` (parametrized `''`, `'widget_notes'`) → 404
  `No history is kept for that table.`
- `test_record_history_needs_an_integer_record_id` (missing, `''`, `'abc'`) → 400.
- `test_account_history_is_admin_only(auth_client, user)` → 403;
  `test_admin_reads_an_accounts_history(admin_client, user)` → 200.
- `test_log_lists_every_table_newest_first(admin_client)`.
- `test_log_filters_by_table_and_account(admin_client, admin_user, user)`, including
  `changed_by_id` with both ids.
- `test_log_rejects_a_malformed_account_filter` → 400
  `changed_by_id must be a comma-separated list of ids.`
- `test_log_range_includes_its_start_and_excludes_its_end`: entries at 06:00Z, 07:00Z,
  and 08:00Z; `changed_from=...T07:00:00Z&changed_before=...T08:00:00Z` returns only
  07:00.
- `test_log_range_reads_offsets`: `changed_from='2026-10-14T00:00:00-07:00'` (07:00Z)
  excludes 06:00Z and includes 07:00Z. This guards the UTC conversion on SQLite.
- `test_log_rejects_a_malformed_moment` (parametrized `2026-10-14`, `yesterday`,
  `2026-10-14T07:00:00`) → 400 with the helper's message.
- `test_tables_lists_the_audited_tables_in_order(admin_client)` →
  `['users', 'widgets']`.
- `test_an_admin_edit_shows_in_the_accounts_history(admin_client, user)`: PUT the role
  to admin, then the user's history holds one `updated` entry with
  `{'role': {'old': 'user', 'new': 'admin'}}` and the admin's email.

**`src_back/tests/test_users_api.py` — new `# -- audit log` section at the end**

A helper `_history(user_id)` returns the account's entries in id order.

- `test_account_history_is_admin_only_in_the_registry()`:
  `audited_tables()[USER_AUDIT_TRAIL.table_name] is True`. The test uses the import,
  so Ruff's `F401` does not strip it.
- `test_create_logs_the_account_with_the_admin_as_actor`: changes are exactly
  `email`, `role`, and `is_active`, with no `password` key; the actor is the admin;
  the label is the email.
- `test_update_logs_only_what_changed`: email unchanged and role changed log only
  `role`.
- `test_update_that_changes_nothing_logs_nothing`: `{'email': 'USER@test.com'}`
  normalizes to the stored address.
- `test_password_change_is_logged_masked`: changes are
  `{'password': {'old': '********', 'new': '********'}}`, and neither the plaintext nor
  `user.password_hash` appears in `json.dumps(entry.changes)`.
- `test_first_password_is_logged_without_an_old_value(admin_client,
  passwordless_user)`: `{'old': None, 'new': '********'}`.
- `test_refused_update_logs_nothing`: the self-demotion case (400) leaves no entry.

**`src_back/tests/test_auth.py`**: after `test_register_creates_an_active_user` (50),
`test_register_logs_the_account_with_no_actor`.
**`src_back/tests/test_seed.py`**: `test_seed_creates_a_normalized_active_admin` (75)
also asserts one `created` entry for the admin with no actor, and
`test_seed_twice_changes_nothing` (114) asserts there is still exactly one.
**`src_back/tests/test_utils.py`**: a `# -- parse_query_datetime` section after 228,
with the `parse_query_date` tests' shape: absent or blank → `None`; `Z` and
`-07:00` both read as the same UTC moment, with `tzinfo is UTC`; naive, date-only, and
junk values raise the message.

### Frontend: types, API, dates, hooks

**`types/auditLog.ts` — new.** `export type AuditAction = 'created' | 'updated' |
'deleted'`; `export interface AuditFieldChange { old: unknown; new: unknown }`; a
non-exported `AuditLogEntryBase` with `id`, `uuid`, `table_name`, `record_id`,
`record_label: string | null`, `changed_by_id: number | null`,
`changed_by_name: string | null`, `changed_at`, `created_at`, `updated_at`;

```ts
/** An update lists each changed field; a create or delete holds the audited fields. */
export type AuditLogEntry =
    | (AuditLogEntryBase & {
          action: 'updated'
          changes: Record<string, AuditFieldChange>
      })
    | (AuditLogEntryBase & {
          action: 'created' | 'deleted'
          changes: Record<string, unknown>
      })
```

and `export interface AuditLogFilters { tableName: string; changedById: string; from:
string; to: string }`, documented as "an empty string means any; `from` and `to` are
local `YYYY-MM-DD` days, both included". Every interface and alias gets JSDoc.

**`utils/dates.ts` — three helpers** after `formatLocalDate` (38-44), reusing the
private `parseLocalDate` (27-30):

```ts
export function addLocalDays(isoDate: string, days: number): string {
    const date = parseLocalDate(isoDate)
    date.setDate(date.getDate() + days)
    return localIsoDate(date)
}

export function localDayStartIso(isoDate: string): string {
    return parseLocalDate(isoDate).toISOString()
}

export function formatLocalDateTime(timestamp: string): string {
    return new Date(timestamp).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    })
}
```

JSDoc: `addLocalDays` "Move a `YYYY-MM-DD` date by whole days; negative moves back,
and daylight-saving changes do not shift the day"; `localDayStartIso` "The moment a
local day starts, in ISO 8601 UTC, as the API reads moments: for example
`2026-10-14T07:00:00.000Z` in California"; `formatLocalDateTime` "Format an ISO 8601
timestamp in local time, for example `Oct 14, 2026, 9:05 AM`".

**`api/auditLogs.ts` — new.**

```ts
/** @file Endpoints for the audit log: a record's history, the admin's log, the tables. */

const AUDIT_LOGS_URL = '/v1/audit-logs'

export const fetchRecordHistoryPage = (
    tableName: string,
    recordId: number,
    page: number,
) =>
    fetchPage<AuditLogEntry>(AUDIT_LOGS_URL, page, {
        table_name: tableName,
        record_id: recordId,
    })

function auditLogParams(filters: AuditLogFilters): Record<string, unknown> {
    return {
        table_name: filters.tableName || undefined,
        changed_by_id: filters.changedById || undefined,
        changed_from: filters.from ? localDayStartIso(filters.from) : undefined,
        changed_before: filters.to
            ? localDayStartIso(addLocalDays(filters.to, 1))
            : undefined,
    }
}

export const fetchAuditLogPage = (filters: AuditLogFilters, page: number) =>
    fetchPage<AuditLogEntry>(`${AUDIT_LOGS_URL}/all`, page, auditLogParams(filters))

export async function fetchAuditedTables(): Promise<string[]> {
    const { data } = await client.get<string[]>(`${AUDIT_LOGS_URL}/tables`)
    return data
}
```

`auditLogParams`' JSDoc says the range of local days goes out as the moments that
bound it, from the first day's local midnight up to, not including, the midnight after
the last; axios leaves `undefined` parameters out. Imports: `client, { fetchPage }`
from `./client`, the types, and the two date helpers.

**`hooks/auditLogs.ts` — new.**

```ts
/** Cache key prefix for every audit-log query. */
const AUDIT_LOGS_KEY = ['audit-logs'] as const

export const useRecordHistory = (tableName: string, recordId: number) =>
    useInfiniteList({
        queryKey: [...AUDIT_LOGS_KEY, 'record', tableName, recordId],
        fetchPage: (page) => fetchRecordHistoryPage(tableName, recordId, page),
    })

export const useAuditLog = (filters: AuditLogFilters) =>
    useInfiniteList({
        queryKey: [...AUDIT_LOGS_KEY, 'all', filters],
        fetchPage: (page) => fetchAuditLogPage(filters, page),
    })

/** The infinite query both history hooks return, which `AuditLogTab` renders. */
export type AuditLogQuery = ReturnType<typeof useAuditLog>

export const useAuditedTables = () =>
    useQuery({ queryKey: [...AUDIT_LOGS_KEY, 'tables'], queryFn: fetchAuditedTables })
```

The `record`, `all`, and `tables` segments keep the three keys apart whatever a table
is called. No mutation invalidates them: the Users and Audit tabs are separate routes,
and the Audit tab refetches when it mounts.

### Frontend: components and the admin tab

**`components/common/AuditLogTab.tsx` — new.** Props: `query: AuditLogQuery`,
`showRecord?: boolean` (adds a Record column for a log of many records), and
`emptyText?: string` (default `'No history yet.'`). Non-exported pieces, each with
JSDoc, keeping every function under 50 lines:

- `ACTION_COLORS: Record<AuditAction, 'success' | 'info' | 'error'>`: created
  success, updated info, deleted error.
- `formatValue(value: unknown): string`: `null` and `''` → `'—'`; a string as is; an
  object `JSON.stringify`; anything else `String(value)`. JSON has no `undefined`, so
  no branch handles it, and v8 would count one as uncovered.
- `describeChanges(entry: AuditLogEntry): string[]`: for `updated`, one
  `` `${field}: ${formatValue(change.old)} → ${formatValue(change.new)}` `` per field;
  otherwise `` `${field}: ${formatValue(value)}` ``.
- `describeRecord(entry)`: `` `${entry.table_name} · ${entry.record_label ??
  `#${entry.record_id}`}` ``.
- `uniqueEntries(entries)`: keeps the first entry with each id. Its JSDoc says why:
  entries recorded while the viewer scrolls push older ones onto the next page.
- `EntryRow` (props `entry`, `showRecord`): cells Date (`formatLocalDateTime`), User
  (`changed_by_name ?? '—'`), Action (`<Chip size="small" label={entry.action}
  color={ACTION_COLORS[entry.action]} />`), Record when `showRecord`, and Changes, one
  `<Typography variant="body2">` per line, keyed by the line.
- `EntryTable` (props `entries`, `showRecord`, `emptyText`): with no entries,
  `<Typography color="text.secondary" sx={{ p: 2 }}>` showing `emptyText`; otherwise
  `<TableContainer><Table size="small" aria-label="Audit log">` with a head row (Date,
  User, Action, Record when shown, Changes) and an `EntryRow` per entry.

The default export. The count sits outside `QueryState`, where the total is
`undefined` while the first page loads, so both arms of `total ?` run in the tests:

```tsx
export default function AuditLogTab(props: AuditLogTabProps) {
    const { query, showRecord = false, emptyText = 'No history yet.' } = props
    const total = lastLoadedPageTotal(query.data)
    return (
        <>
            {total ? (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    {total === 1 ? '1 entry' : `${total} entries`}
                </Typography>
            ) : null}
            <QueryState query={query}>
                {(data) => (
                    <>
                        <EntryTable
                            entries={uniqueEntries(flattenPages(data))}
                            showRecord={showRecord}
                            emptyText={emptyText}
                        />
                        <InfiniteScrollSentinel
                            hasNextPage={query.hasNextPage}
                            isFetchingNextPage={query.isFetchingNextPage}
                            fetchNextPage={() => void query.fetchNextPage()}
                        />
                    </>
                )}
            </QueryState>
        </>
    )
}
```

**`components/common/RecordAuditLogTab.tsx` — new.** Props `tableName: string` and
`recordId: number`, each documented; renders
`<AuditLogTab query={useRecordHistory(tableName, recordId)} />`. JSDoc: for a
record's detail view; the table must be audited, and an admin-only table's history
answers 403 to anyone else.

**`components/admin/AdminAuditLogTab.tsx` — new.**

- `DEFAULT_DAYS = 30` and `defaultFilters(): AuditLogFilters`, which returns
  `{ tableName: '', changedById: '', from: addLocalDays(today, 1 - DEFAULT_DAYS), to:
  today }` with `today = localIsoDate(new Date())`: 30 local days, today included.
- `FilterSelect` (props `label`, `allLabel`, `value: string`,
  `options: readonly { value: string; label: string }[]`,
  `onChange: (value: string) => void`): a `TextField select size="small"` with
  `sx={{ minWidth: 180 }}` and
  `slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}`, a
  first `<MenuItem value="">` showing `allLabel`, then one item per option. Without
  `displayEmpty`, MUI renders the `''` value as a blank field under an unshrunk label
  (`Select/SelectInput.js` 330-332, 465-470). It does not use `FormSelectField`, which
  needs a form context.
- `DateFilter` (props `label`, `value`, `min?`, `max?`, `onChange`): a
  `TextField type="date" size="small"` with
  `slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: min || undefined,
  max: max || undefined } }}`.
- `AuditLogFilterBar` (props `filters`, `onChange: (patch: Partial<AuditLogFilters>)
  => void`): reads `useAuditedTables().data ?? []` and `useUsers().data ?? []`, and
  renders `<Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>`
  holding Table (`All tables`, one option per table name), User (`All users`, value
  `String(user.id)`, label the email), From (`max` the To date), and To (`min` the From
  date).
- The default export holds `const [filters, setFilters] = useState(defaultFilters)`,
  passes `onChange={(patch) => setFilters((current) => ({ ...current, ...patch }))}`
  inline (an inline JSX arrow needs no JSDoc), and renders the bar above
  `<AuditLogTab query={useAuditLog(filters)} showRecord
  emptyText="No changes match these filters." />`. The filters sit outside
  `QueryState`, so changing one shows the spinner below them without unmounting them.

**`pages/AdminPage.tsx`**: import `AdminAuditLogTab` and add
`{ path: 'audit', label: 'Audit', element: <AdminAuditLogTab /> }` after the Users
entry in `SECTIONS` (20-22). Users stays the landing section.

### Frontend tests

Tests mock API modules with `vi.mock`, as the neighbors do; the zone is
America/Los_Angeles (`test/globalSetup.ts`).

- **`test/utils/fixtures.ts`**: `widgetRenamed` (id 2, widgets#4, label `beta`,
  `updated`, `{ name: { old: 'alpha', new: 'beta' }, active: { old: true, new: false
  } }`, by `adminUser`, at `2026-10-14T16:05:00Z`), `widgetCreated` (id 1, widgets#4,
  label `alpha`, `created`, `{ name: 'alpha', note: null, code: '' }`, no actor), and
  `auditPage(items, page = 1, total = items.length, perPage = 100)`, which wraps
  entries in the envelope. Both component tests use them, so fallow sees no copied
  blocks.
- **`test/utils/dialogQueries.ts`**: `tableRowContaining(text)`, like `rowContaining`
  but for the closest `tr`.
- **`test/utils/dates.test.ts`**: `addLocalDays` across a month end and the
  2026-11-01 change (`('2026-10-31', 1)` → `'2026-11-01'`, `('2026-11-01', 1)` →
  `'2026-11-02'`, `('2026-10-27', -29)` → `'2026-09-28'`); `localDayStartIso` on both
  sides of it (`'2026-10-14'` → `'2026-10-14T07:00:00.000Z'`, `'2026-11-02'` →
  `'2026-11-02T08:00:00.000Z'`); `formatLocalDateTime('2026-10-14T16:05:00Z')` equals
  `toLocaleString` with the same options and contains `9:05`.
- **`test/api/auditLogs.test.ts`**: mock `../../api/client` with a factory
  (`default: { get: vi.fn() }`, `fetchPage: vi.fn()`), as `test/api/users.test.ts`
  does. `fetchRecordHistoryPage('users', 7, 2)` calls
  `fetchPage('/v1/audit-logs', 2, { table_name: 'users', record_id: 7 })` and returns
  its result. `fetchAuditLogPage` with `{ tableName: 'users', changedById: '3', from:
  '2026-10-01', to: '2026-11-01' }` sends `changed_from:
  '2026-10-01T07:00:00.000Z'` and `changed_before: '2026-11-02T08:00:00.000Z'`;
  with blank filters every parameter is `undefined`. `fetchAuditedTables` gets
  `/v1/audit-logs/tables` and returns its data.
- **`test/hooks/auditLogs.test.tsx`**: mock `../../api/auditLogs`; `useRecordHistory`
  loads page 1 through `fetchRecordHistoryPage('users', 7, 1)`; `useAuditLog` through
  `fetchAuditLogPage(filters, 1)`; `useAuditedTables` returns the API's list.
- **`test/components/common/AuditLogTab.test.tsx`**: mock `../../../api/auditLogs` and
  render `AuditLogTab` from a small harness that calls `useRecordHistory` (or render
  `RecordAuditLogTab`), wrapped with `renderWithProviders`. Cases: an update's row
  shows the formatted date, the admin's email, an `updated` chip, and the lines
  `name: alpha → beta` and `active: true → false`; a create lists `name: alpha`,
  `note: —`, and `code: —` and shows `—` for the actor; an entry spread from
  `widgetRenamed` with `changes: { tags: { old: ['a'], new: ['a', 'b'] } }` shows
  `tags: ["a"] → ["a","b"]`; with `showRecord` the Record cell reads `widgets · beta`,
  or `widgets · #4` without a label; the caption reads `2 entries` and `1 entry`; no
  entries shows `emptyText`
  (default and custom); and with an `IntersectionObserver` stub that captures its
  callback, as `InfiniteScrollSentinel.test.tsx` does, pages of two per page,
  `auditPage([a, b], 1, 3, 2)` then `auditPage([b, c], 2, 3, 2)`, render three rows,
  not four, once the callback reports the sentinel visible. At 100 per page a total of
  3 has no second page (`useInfiniteList.ts` 27-30), and the test would cover neither
  `fetchNextPage` nor the repeated entry.
- **`test/components/common/RecordAuditLogTab.test.tsx`**: renders the record's
  entries and requests `('users', 7, 1)`.
- **`test/components/admin/AdminAuditLogTab.test.tsx`**: mock `../../../api/auditLogs`
  and `../../../api/users`; `vi.useFakeTimers({ toFake: ['Date'] })` with
  `vi.setSystemTime(new Date(2026, 9, 27, 18, 30))`, after which UTC is already
  October 28, and real timers again in `afterEach`. Cases: it opens on
  `{ tableName: '', changedById: '', from: '2026-09-28', to: '2026-10-27' }` (the
  first `fetchAuditLogPage` call and the From and To values); the Table select offers
  `All tables` plus the API's names, and choosing `users` refetches with it; the User
  select offers each account's email, and choosing `user@example.com` refetches with
  `changedById: '2'`; `fireEvent.change` on From to `2026-10-01` and on To to
  `2026-10-20` each refetch with the new date (v8 counts each inline arrow as a
  function); an entry's row shows its Record cell; with no entries it says
  `No changes match these filters.`
- **`test/pages/AdminPage.test.tsx`**: mock `AdminAuditLogTab` as `UsersAdmin` is
  mocked (10-12); `/admin/audit` shows the Audit section, and its tab is selected and
  links to `/admin/audit`. The redirect cases stay.

### Docs

- **`ai/conventions.md`**, Backend, after the `require_unique_name` bullet (32-35):

```markdown
- A service opts into the audit log (`AuditLog`, `services/audit_log.py`) by passing
  `audit_fields` to `CRUDService` or `ChildRecordService`, and `label_field` when its
  records are not named by `name` (`None` for no label). `create` then logs the new
  record's audited fields, `update` the ones it changed (`{field: {old, new}}`, and
  nothing when none did), and `delete` the record's fields after `before_delete`, each
  before the method's commit, so the entry and the change are saved together. The
  actor is the signed-in account, `None` outside a request. A hand-written service
  builds an `AuditTrail` and calls its `log_*` methods before committing, as
  `services/users.py` does with `USER_AUDIT_TRAIL`, and records a secret, such as a
  password, only as `MASKED_VALUE`. Building a trail registers its table, so one
  record's history (`GET /api/v1/audit-logs`) is served only for audited tables.
  `audit_admin_only=True` on a generic service, or `admin_only=True` on a trail, keeps
  a table's history from non-admins, as for accounts, and no later trail can undo it.
  A child record's entries belong to its own table, not its parent's.
```

- **`ai/conventions.md`**, Frontend, after the `RecordSection` bullet (154-159):

```markdown
- A record's detail view shows its history with `RecordAuditLogTab`, given the table
  and the record's id; a form beside it passes `alsoInvalidate: [['audit-logs']]` to
  its mutations so the history refreshes after a save. The admin screen's Audit tab is
  `AdminAuditLogTab`. Both render `AuditLogTab`, which pages with `useInfiniteList`
  and `InfiniteScrollSentinel`.
```

- **`ai/domain.md`**, Domains, after Accounts (9-18):

```markdown
- Audit log: `AuditLog` rows record each create, update, and delete an audited
  service makes (`src_back/services/audit_log.py`), with the signed-in account as the
  actor. Accounts are audited at registration, on the admin's Users screen, and by the
  seed; their history is admin-only, and a password change appears only masked.
  Anyone signed in reads one record's history through `/api/v1/audit-logs`; admins
  read and filter the whole log on the Audit tab of the admin screen.
```

- **`ai/domain.md`**, Test Fixtures: the Widget bullet (34-35) ends "...and
  `BaseSchema`; `test_base_service.py` builds audited services over them". After the
  `persist` paragraph (43-44), add: "Building an `AuditTrail` registers its table for
  the rest of the run. A test that needs a known set of audited tables replaces the
  registry with `monkeypatch.setattr(audit_log, '_AUDITED_TABLES', {...})` inside the
  test or a fixture, as `test_audit_logs_api.py` does."
- **`ai/project.md`**, Project Structure: `models/` (11-13) adds "`audit_log.py`
  holds `AuditAction` and `AuditLog`"; `services/` (16-19) adds
  "`services/audit_log.py` the audit trail and the history queries".
- **`README.md`** Project layout: line 206 becomes "Blueprints (health, auth, users,
  audit logs)".

Every added line stays within 90 characters.

## Parallelism

Implementer model for group agents: Sonnet 5.5 (#27).

- **Can be done in parallel**:
    - Group A, backend core: `models/audit_log.py`, `models/user.py`,
      `models/__init__.py`, the migration (needs the dev `db` container),
      `services/audit_log.py`, `services/base.py`, `test_audit_log.py`, and the
      `test_base_service.py` section. None of A's tests imports `USER_AUDIT_TRAIL`,
      which Group B adds; its registry test is in `test_users_api.py`.
    - Group C, frontend: every frontend file, against the API contract above.
    - Group D, docs: the four documents; every name they use is fixed here.
- **Must be sequential**:
    - Group B, after A: `services/auth.py`, `services/users.py`, `seed.py`,
      `utils.py`, `schemas/audit_log.py`, `api/audit_logs.py`, `api/__init__.py`,
      `app.py`, and `test_audit_logs_api.py`, `test_users_api.py`, `test_auth.py`,
      `test_seed.py`, `test_utils.py`. They import `AuditTrail`, `AuditLog`, and the
      queries from Group A.
    - Within A, the model before the migration; within C, types, dates, and the API
      module before the hooks, the hooks before the components.

## No other changes needed

- `BaseSchema.AUDIT` keeps its name; it means the bookkeeping columns.
- No new dependency: `Table`, `Chip`, and the date `TextField` come with
  `@mui/material`, and `vite.config.ts`'s `VENDOR_CHUNKS` already covers it.
- `docker/entrypoint.sh` applies the migration on every start; `scripts/deploy.sh`
  dumps the database first.
- `ai/backups.md`'s `UPLOAD_COLUMNS` stays empty: the log stores no upload paths.
- `useResourceMutations` and `hooks/users.ts` are unchanged (see the hooks section).
- `.env.example`, `tools.md`, and `ai/auth.md` need nothing.

## Verification

1. Backend, targeted:
   `.venv/bin/python -m pytest src_back/tests/test_audit_log.py
   src_back/tests/test_audit_logs_api.py src_back/tests/test_base_service.py
   src_back/tests/test_users_api.py src_back/tests/test_auth.py
   src_back/tests/test_seed.py src_back/tests/test_utils.py --no-cov`.
2. Frontend, targeted: `npx vitest run` over the seven new or changed test files.
3. The migration on a fresh database, then the backend suite on PostgreSQL, which
   checks the foreign key's `SET NULL` against the ORM's. Run the block as one shell
   command; `.env`'s `DATABASE_URL` does not override the exported one:

    ```bash
    docker compose up -d db
    docker compose exec -T db createdb -U app audit_check
    export DATABASE_URL=postgresql://app:app@localhost:5433/audit_check
    .venv/bin/flask --app src_back.app db upgrade
    .venv/bin/flask --app src_back.app db check
    .venv/bin/flask --app src_back.app db downgrade
    .venv/bin/flask --app src_back.app db upgrade
    .venv/bin/flask --app src_back.app db check
    unset DATABASE_URL
    docker compose exec -T db dropdb -U app audit_check
    docker compose exec -T db createdb -U app audit_test
    TEST_DATABASE_URL=postgresql://app:app@localhost:5433/audit_test \
      .venv/bin/python -m pytest
    docker compose exec -T db dropdb -U app audit_test
    ```

4. The full gate, in parallel: `npm run test`, `npm run lint -- --max-warnings=0`,
   `npm run lint:py`, `npm run lint:md`, `npm run typecheck`, `npm run fallow`, and
   `npm run build`. Both suites stay at 100% coverage.
5. In the dev stack (`npm run docker:up` in the background, then `npm run docker:url`),
   signed in as the seeded admin: create an account, change its role, then its
   password; Admin → Audit lists the three entries newest first, with the password as
   `******** → ********`; the Table, User, From, and To filters narrow the list; a
   change made just now appears under the default range whatever the hour. Signed in
   as a plain user, `GET /api/v1/audit-logs?table_name=users&record_id=1` answers 403,
   and a table no service audits answers 404.
