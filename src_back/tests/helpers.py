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
