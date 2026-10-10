"""Generic base classes for the service layer.

A service owns the database access for one resource so that API handlers stay
thin: they parse the request, call the service, and serialize the result.
"""

from typing import Any, Generic, TypeVar

from src_back.extensions import Base, db

T = TypeVar('T', bound=Base)


class CRUDService(Generic[T]):
    """Generic service for top-level resources with full CRUD operations.

    Subclasses may override :meth:`before_delete` to add side effects, such as
    removing files, that must run before the row is deleted.
    """

    def __init__(self, model: type[T], *order_by: Any) -> None:
        """Bind the service to a model and a default ordering.

        Args:
            model: The ORM class this service manages.
            *order_by: Column expressions applied to every :meth:`list` query.
        """
        self._model = model
        self._order_by = order_by

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
        for key, value in data.items():
            setattr(record, key, value)
        db.session.commit()
        return record

    def delete(self, record_id: int) -> bool:
        """Delete a record by primary key.

        Calls :meth:`before_delete` before the row is removed.

        Args:
            record_id: The record's primary key.

        Returns:
            ``True`` on success, ``False`` if the record does not exist.
        """
        record = db.session.get(self._model, record_id)
        if record is None:
            return False
        self.before_delete(record)
        db.session.delete(record)
        db.session.commit()
        return True

    def before_delete(self, record: T) -> None:
        """Run side effects before a record is deleted. Override in subclasses.

        Args:
            record: The record about to be deleted.
        """


class ChildRecordService(Generic[T]):
    """Generic service for child records owned by a parent resource.

    Unlike :class:`CRUDService`, :meth:`update` and :meth:`delete` accept a
    pre-fetched record instead of an id. The API layer fetches it with
    :meth:`get_for_parent` first, which is what enforces that a child can only
    be reached through the parent that owns it.
    """

    def __init__(self, model: type[T], parent_fk: str, *order_by: Any) -> None:
        """Bind the service to a child model and its parent foreign key.

        Args:
            model: The ORM class this service manages.
            parent_fk: The column holding the parent's primary key.
            *order_by: Column expressions applied to every :meth:`list` query.
        """
        self._model = model
        self._parent_fk = parent_fk
        self._order_by = order_by

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
        db.session.commit()
        return record

    def update(self, record: T, data: dict[str, Any]) -> T:
        """Apply column values to a pre-fetched child record and persist it.

        Args:
            record: The record returned by :meth:`get_for_parent`.
            data: Validated column values to set.

        Returns:
            The same record, updated and committed.
        """
        for key, value in data.items():
            setattr(record, key, value)
        db.session.commit()
        return record

    def delete(self, record: T) -> None:
        """Delete a pre-fetched child record.

        Calls :meth:`before_delete` before the row is removed. Existence was
        already established by :meth:`get_for_parent`, so nothing is returned.

        Args:
            record: The record returned by :meth:`get_for_parent`.
        """
        self.before_delete(record)
        db.session.delete(record)
        db.session.commit()

    def before_delete(self, record: T) -> None:
        """Run side effects before a record is deleted. Override in subclasses.

        Args:
            record: The record about to be deleted.
        """
