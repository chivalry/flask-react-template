"""Base Marshmallow schema, its UTC datetime field, and the shared validators."""

from datetime import UTC, datetime
from typing import Any

import marshmallow
from marshmallow_sqlalchemy import ModelConverter, SQLAlchemyAutoSchema
from sqlalchemy import DateTime, func, select

from src_back.extensions import db
from src_back.models import BaseMixin


class UTCDateTime(marshmallow.fields.DateTime):
    """A datetime serialized in UTC with an explicit offset, whichever database ran.

    PostgreSQL returns ``timestamptz`` values with their offset, but SQLite drops it,
    and a browser reads an ISO 8601 string without an offset as local time. Every
    datetime the models store is UTC (``BaseMixin`` and ``AuditLog`` default to
    ``datetime.now(UTC)``), so a value without an offset is read as UTC.
    """

    def _serialize(
        self, value: datetime | None, attr: str | None, obj: object, **kwargs: Any
    ) -> str | float | None:
        """Give the value an explicit UTC offset, then format it as ``DateTime`` does.

        Args:
            value: The datetime to serialize, with or without an offset, or ``None``.
            attr: The attribute or key the value came from.
            obj: The object the value came from.
            **kwargs: Passed through to :class:`marshmallow.fields.DateTime`.

        Returns:
            The formatted datetime, such as ``2026-10-14T16:05:00+00:00``, or ``None``.
        """
        if value is not None:
            aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            value = aware.astimezone(UTC)
        return super()._serialize(value, attr, obj, **kwargs)


class _UTCModelConverter(ModelConverter):
    """Build the field of every ``DateTime`` column as a :class:`UTCDateTime`."""

    SQLA_TYPE_MAPPING = {**ModelConverter.SQLA_TYPE_MAPPING, DateTime: UTCDateTime}


class BaseSchema(SQLAlchemyAutoSchema):
    """Auto schema that returns dicts on load and marks audit columns dump-only.

    Subclasses set ``Meta.model`` and list :data:`AUDIT` as ``dump_only`` so the
    client can never write the primary key, public identifier, or timestamps. Every
    ``DateTime`` column serializes through :class:`UTCDateTime`; a datetime field
    declared by hand uses it too.
    """

    AUDIT = ('id', 'uuid', 'created_at', 'updated_at')

    class Meta(SQLAlchemyAutoSchema.Meta):
        """Shared marshmallow-sqlalchemy options."""

        load_instance = False
        sqla_session = db.session
        model_converter = _UTCModelConverter

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Default every nullable field to ``None`` when it is absent on load.

        Without this, an omitted nullable column is simply missing from the
        loaded dict and a service has to special-case it; with it, a partial
        payload still produces every key the model expects.

        Args:
            *args: Positional arguments forwarded to the auto schema.
            **kwargs: Keyword arguments forwarded to the auto schema.
        """
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
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
