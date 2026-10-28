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


def register_audited_table(table_name: str, *, admin_only: bool = False) -> None:
    """Record that a table keeps an audit history, which the history routes serve.

    :class:`AuditTrail` calls it, so the tables come from the services that opted in
    rather than a list kept by hand. Once any trail makes a table admin-only it stays
    so, and a later trail for the same table cannot open its history.

    Args:
        table_name: The audited table's name.
        admin_only: Whether only admins may read the table's history.
    """
    _AUDITED_TABLES[table_name] = _AUDITED_TABLES.get(table_name, False) or admin_only


def audited_tables() -> Mapping[str, bool]:
    """Expose the audited tables, read-only.

    Returns:
        A live view that maps each audited table's name to whether only admins may
        read its history.
    """
    return MappingProxyType(_AUDITED_TABLES)


def _json_safe(value: object) -> object:
    """Convert a column value to one that the JSON column stores.

    Args:
        value: A value read from a record.

    Returns:
        An enum's value; a decimal or UUID as text, so a large amount keeps every
        digit; a date, datetime, or time as ISO 8601 text; anything else unchanged.
    """
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, decimal.Decimal | uuid_lib.UUID):
        return str(value)
    if isinstance(value, date | time):
        return value.isoformat()
    return value


def snapshot(record: object, fields: Sequence[str]) -> dict[str, object]:
    """Read a record's audited fields as JSON-safe values.

    Args:
        record: The record to read; any object with the named attributes.
        fields: The attribute names to read.

    Returns:
        Each field's name mapped to its current value.
    """
    return {name: _json_safe(getattr(record, name)) for name in fields}


def diff(
    before: Mapping[str, object], after: Mapping[str, object]
) -> dict[str, dict[str, object]]:
    """List the fields whose values differ between two snapshots.

    Args:
        before: The snapshot taken before the change.
        after: The snapshot taken after it, of the same fields.

    Returns:
        ``{field: {'old': ..., 'new': ...}}`` for each field that changed; empty
        when none did.
    """
    return {
        name: {'old': before[name], 'new': after[name]}
        for name in before
        if before[name] != after[name]
    }


def _current_actor_id() -> int | None:
    """Find the account that is making the change.

    It reads Flask-Login's own ``current_user`` rather than the typed one in
    :mod:`src_back.auth`, because the callers are not all behind ``@login_required``:
    outside a request the proxy stands for ``None``, and in an anonymous request it
    is an ``AnonymousUserMixin``, which has no ``id``.

    Returns:
        The signed-in account's id, or ``None`` outside a request or when nobody is
        signed in.
    """
    if has_request_context() and current_user.is_authenticated:
        return current_user.id
    return None


def create_audit_entry(
    table_name: str,
    record_id: int,
    record_label: str | None,
    action: AuditAction,
    changes: Mapping[str, object],
) -> AuditLog | None:
    """Add an audit entry to the session, with the signed-in account as the actor.

    It never flushes or commits: the caller's commit saves the entry with the change
    it describes. An update that changed nothing adds no entry.

    Args:
        table_name: The audited table's name.
        record_id: The record's primary key.
        record_label: What names the record in the log, or ``None`` for no label.
        action: What happened to the record.
        changes: The record's audited fields for a create or delete, or
            ``{field: {'old': ..., 'new': ...}}`` for an update.

    Returns:
        The pending entry, or ``None`` for an update with no changes.
    """
    if action is AuditAction.updated and not changes:
        return None
    entry = AuditLog(
        table_name=table_name,
        record_id=record_id,
        record_label=record_label,
        action=action,
        changes=dict(changes),
        changed_by_id=_current_actor_id(),
    )
    db.session.add(entry)
    return entry


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
        """Check the model against the audited fields and register its table.

        Args:
            model: The ORM class whose records are audited.
            fields: The attributes each entry records.
            label_field: The attribute that names a record in its entries; ``None``
                for no label.
            admin_only: Whether only admins may read the table's history.

        Raises:
            ValueError: If an audited field or the label field is not an attribute
                of the model, so a misconfiguration fails at import instead of at
                the first save.
        """
        names = list(fields) if label_field is None else [*fields, label_field]
        missing = [name for name in names if not hasattr(model, name)]
        if missing:
            joined = ', '.join(missing)
            raise ValueError(f'{model.__name__} has no attribute {joined}.')
        self.table_name: str = model.__tablename__
        self._fields = tuple(fields)
        self._label_field = label_field
        register_audited_table(self.table_name, admin_only=admin_only)

    def snapshot(self, record: object) -> dict[str, object]:
        """Read a record's audited fields, to compare after the record changes.

        Args:
            record: The record about to change.

        Returns:
            The audited fields' current values, for :meth:`log_updated`.
        """
        return snapshot(record, self._fields)

    def log(
        self, record: object, action: AuditAction, changes: Mapping[str, object]
    ) -> AuditLog | None:
        """Add an entry whose changes the caller built.

        Args:
            record: The record the entry describes; it must have an ``id``.
            action: What happened to the record.
            changes: What to record, as :func:`create_audit_entry` describes.

        Returns:
            The pending entry, or ``None`` for an update with no changes.
        """
        # The generic services know records only as Base, which declares no columns;
        # every audited model mixes in BaseMixin, so the id is there.
        record_id: int = getattr(record, 'id')
        return create_audit_entry(
            self.table_name, record_id, self._label(record), action, changes
        )

    def log_created(self, record: object) -> None:
        """Add an entry for a record that was just added to the session.

        It flushes first, because the entry needs the id that the insert assigns.

        Args:
            record: The new record.
        """
        db.session.flush()
        self.log(record, AuditAction.created, self.snapshot(record))

    def log_updated(self, record: object, before: Mapping[str, object]) -> None:
        """Add an entry for what changed in a record, if anything.

        The label is read after the change, so a renamed record's entry carries its
        new name.

        Args:
            record: The record, after the change.
            before: The :meth:`snapshot` taken before the change.
        """
        self.log(record, AuditAction.updated, diff(before, self.snapshot(record)))

    def log_deleted(self, record: object) -> None:
        """Add an entry holding the fields of a record about to be deleted.

        Args:
            record: The record about to be deleted.
        """
        self.log(record, AuditAction.deleted, self.snapshot(record))

    def _label(self, record: object) -> str | None:
        """Name the record for its entries.

        Args:
            record: The record to name.

        Returns:
            The label field's value as text, cut to fit the ``record_label`` column;
            ``None`` when the trail has no label field or the value is ``None``.
        """
        if self._label_field is None:
            return None
        value = getattr(record, self._label_field)
        if value is None:
            return None
        return str(value)[:_LABEL_LENGTH]


def select_record_history(table_name: str, record_id: int) -> Select[tuple[AuditLog]]:
    """Build the query for one record's entries, newest first.

    The result is ready for :func:`~src_back.utils.paginate_select`.

    Args:
        table_name: The audited table's name.
        record_id: The record's primary key.

    Returns:
        The select of the record's entries, in :data:`NEWEST_FIRST` order.
    """
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
    """Build the admin's filtered query over every entry, newest first.

    The result is ready for :func:`~src_back.utils.paginate_select`. A filter left at
    its default does not narrow the log.

    Args:
        table_name: Only this table's entries.
        changed_by_ids: Only entries made by any of these accounts.
        changed_from: Only entries made at or after this moment (inclusive); give it
            in UTC, since SQLite stores datetimes without an offset.
        changed_before: Only entries made before this moment (exclusive); also UTC.

    Returns:
        The select of the matching entries, in :data:`NEWEST_FIRST` order.
    """
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
