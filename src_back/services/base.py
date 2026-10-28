"""Generic base classes and shared checks for the service layer.

A service owns the database access for one resource so that API handlers stay
thin: they parse the request, call the service, and serialize the result.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnExpressionArgument

from src_back.extensions import Base, db
from src_back.services.audit_log import AuditTrail
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
    """Generic service for top-level resources with full CRUD operations.

    Subclasses may override :meth:`before_delete` for side effects that must run
    before the row is deleted, and :meth:`after_delete` for ones that must wait
    for the commit, such as removing the record's stored files.

    Passing ``audit_fields`` opts the service into the audit log: :meth:`create`,
    :meth:`update`, and :meth:`delete` each add an entry, through an
    :class:`~src_back.services.audit_log.AuditTrail`, that their commit saves with
    the change.
    """

    def __init__(
        self,
        model: type[T],
        *order_by: ColumnExpressionArgument[Any],
        audit_fields: Sequence[str] = (),
        label_field: str | None = 'name',
        audit_admin_only: bool = False,
    ) -> None:
        """Bind the service to a model and a default ordering.

        Args:
            model: The ORM class this service manages.
            *order_by: Column expressions applied to every :meth:`list` query.
            audit_fields: The columns each audit entry records; empty, the default,
                records nothing.
            label_field: The attribute that names a record in its audit entries;
                ``None`` for no label. Ignored without ``audit_fields``.
            audit_admin_only: Whether only admins may read a record's history.
                Ignored without ``audit_fields``.
        """
        self._model = model
        self._order_by = order_by
        self._audit = (
            AuditTrail(model, audit_fields, label_field, admin_only=audit_admin_only)
            if audit_fields
            else None
        )

    def list(self, **filter_by: Any) -> list[T]:
        """Return all records, optionally filtered by column equality.

        Args:
            **filter_by: Column name and value pairs passed to ``filter_by``.

        Returns:
            The matching records in the service's default order.
        """
        query = db.session.query(self._model)
        if filter_by:
            query = query.filter_by(**filter_by)
        return query.order_by(*self._order_by).all()

    def get(self, record_id: int) -> T | None:
        """Return a single record by primary key.

        Args:
            record_id: The record's primary key.

        Returns:
            The record, or ``None`` if it does not exist.
        """
        return db.session.get(self._model, record_id)

    def create(self, data: dict[str, Any], **extra: Any) -> T:
        """Create and persist a new record.

        Args:
            data: Validated column values, typically a loaded schema payload.
            **extra: Further column values the caller supplies, such as the
                owning user's id. These win over the same keys in ``data``.

        Returns:
            The committed record.
        """
        # Merge before unpacking: spreading two mappings that share a key raises
        # TypeError, and a keyword the caller passes explicitly should win.
        record = self._model(**{**data, **extra})
        db.session.add(record)
        if self._audit is not None:
            self._audit.log_created(record)
        db.session.commit()
        return record

    def update(self, record_id: int, data: dict[str, Any]) -> T | None:
        """Apply column values to an existing record and persist it.

        Args:
            record_id: The record's primary key.
            data: Validated column values to set.

        Returns:
            The updated record, or ``None`` if it does not exist.
        """
        record = db.session.get(self._model, record_id)
        if record is None:
            return None
        before = self._audit.snapshot(record) if self._audit is not None else {}
        for key, value in data.items():
            setattr(record, key, value)
        if self._audit is not None:
            self._audit.log_updated(record, before)
        db.session.commit()
        return record

    def delete(self, record_id: int) -> bool:
        """Delete a record by primary key.

        Calls :meth:`before_delete` before the row is removed and
        :meth:`after_delete` once the deletion is committed. An audited service logs
        the record after :meth:`before_delete`, so a ``before_delete`` that raises
        logs nothing.

        Args:
            record_id: The record's primary key.

        Returns:
            ``True`` on success, ``False`` if the record does not exist.
        """
        record = db.session.get(self._model, record_id)
        if record is None:
            return False
        self.before_delete(record)
        if self._audit is not None:
            self._audit.log_deleted(record)
        db.session.delete(record)
        db.session.commit()
        self.after_delete(record)
        return True

    def before_delete(self, record: T) -> None:
        """Run side effects before a record is deleted. Override in subclasses.

        Args:
            record: The record about to be deleted.
        """

    def after_delete(self, record: T) -> None:
        """Run side effects once a deletion is committed. Override in subclasses.

        This is where a service removes the record's stored files, through
        :func:`~src_back.utils.delete_upload`: a commit that fails never reaches
        this hook, so the row and its files stay together.

        Args:
            record: The deleted record, now detached from the session; the
                column values it had are still readable.
        """


class ChildRecordService[T: Base]:
    """Generic service for child records owned by a parent resource.

    Unlike :class:`CRUDService`, :meth:`update` and :meth:`delete` accept a
    pre-fetched record instead of an id. The API layer fetches it with
    :meth:`get_for_parent` first, which is what enforces that a child can only
    be reached through the parent that owns it. :meth:`before_delete` and
    :meth:`after_delete` work as they do on :class:`CRUDService`.

    Passing ``audit_fields`` opts the service into the audit log: :meth:`create`,
    :meth:`update`, and :meth:`delete` each add an entry, through an
    :class:`~src_back.services.audit_log.AuditTrail`, that their commit saves with
    the change.
    """

    def __init__(
        self,
        model: type[T],
        parent_fk: str,
        *order_by: ColumnExpressionArgument[Any],
        audit_fields: Sequence[str] = (),
        label_field: str | None = 'name',
        audit_admin_only: bool = False,
    ) -> None:
        """Bind the service to a child model and its parent foreign key.

        Args:
            model: The ORM class this service manages.
            parent_fk: The column holding the parent's primary key.
            *order_by: Column expressions applied to every :meth:`list` query.
            audit_fields: The columns each audit entry records; empty, the default,
                records nothing.
            label_field: The attribute that names a record in its audit entries;
                ``None`` for no label. Ignored without ``audit_fields``.
            audit_admin_only: Whether only admins may read a record's history.
                Ignored without ``audit_fields``.
        """
        self._model = model
        self._parent_fk = parent_fk
        self._order_by = order_by
        self._audit = (
            AuditTrail(model, audit_fields, label_field, admin_only=audit_admin_only)
            if audit_fields
            else None
        )

    def list(self, parent_id: int) -> list[T]:
        """Return every child record belonging to the given parent.

        Args:
            parent_id: The parent's primary key.

        Returns:
            The parent's children in the service's default order.
        """
        return (
            db.session.query(self._model)
            .filter_by(**{self._parent_fk: parent_id})
            .order_by(*self._order_by)
            .all()
        )

    def get(self, record_id: int) -> T | None:
        """Return a single child record by primary key, regardless of parent.

        Args:
            record_id: The child's primary key.

        Returns:
            The record, or ``None`` if it does not exist.
        """
        return db.session.get(self._model, record_id)

    def get_for_parent(self, record_id: int, parent_id: int) -> T | None:
        """Return a child record only if it belongs to the given parent.

        Args:
            record_id: The child's primary key.
            parent_id: The parent the child must belong to.

        Returns:
            The record, or ``None`` if it does not exist or has another parent.
        """
        return (
            db.session.query(self._model)
            .filter_by(id=record_id, **{self._parent_fk: parent_id})
            .one_or_none()
        )

    def create(self, parent_id: int, data: dict[str, Any], **extra: Any) -> T:
        """Create and persist a child record linked to the given parent.

        Args:
            parent_id: The parent's primary key, which wins over any parent id
                carried in ``data`` by a schema that sets ``include_fk``.
            data: Validated column values, typically a loaded schema payload.
            **extra: Further column values the caller supplies.

        Returns:
            The committed record.
        """
        # Merge before unpacking so a parent id in the body neither raises
        # TypeError for the duplicate keyword nor redirects the child to another
        # parent; the URL is the authority on ownership.
        record = self._model(**{**data, **extra, self._parent_fk: parent_id})
        db.session.add(record)
        if self._audit is not None:
            self._audit.log_created(record)
        db.session.commit()
        return record

    def update(self, record: T, data: dict[str, Any]) -> T:
        """Apply column values to a pre-fetched child record and persist it.

        The parent foreign key is skipped even when ``data`` carries it: the URL
        that :meth:`get_for_parent` validated stays authoritative, so a body
        cannot move the child under another parent.

        Args:
            record: The record returned by :meth:`get_for_parent`.
            data: Validated column values to set.

        Returns:
            The same record, updated and committed.
        """
        before = self._audit.snapshot(record) if self._audit is not None else {}
        for key, value in data.items():
            if key == self._parent_fk:
                continue
            setattr(record, key, value)
        if self._audit is not None:
            self._audit.log_updated(record, before)
        db.session.commit()
        return record

    def delete(self, record: T) -> None:
        """Delete a pre-fetched child record.

        Calls :meth:`before_delete` before the row is removed and
        :meth:`after_delete` once the deletion is committed. Existence was
        already established by :meth:`get_for_parent`, so nothing is returned. An
        audited service logs the record after :meth:`before_delete`, so a
        ``before_delete`` that raises logs nothing.

        Args:
            record: The record returned by :meth:`get_for_parent`.
        """
        self.before_delete(record)
        if self._audit is not None:
            self._audit.log_deleted(record)
        db.session.delete(record)
        db.session.commit()
        self.after_delete(record)

    def before_delete(self, record: T) -> None:
        """Run side effects before a record is deleted. Override in subclasses.

        Args:
            record: The record about to be deleted.
        """

    def after_delete(self, record: T) -> None:
        """Run side effects once a deletion is committed. Override in subclasses.

        This is where a service removes the record's stored files, through
        :func:`~src_back.utils.delete_upload`: a commit that fails never reaches
        this hook, so the row and its files stay together.

        Args:
            record: The deleted record, now detached from the session; the
                column values it had are still readable.
        """
