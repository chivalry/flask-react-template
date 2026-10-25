"""Base Marshmallow schema and the validators shared by model-backed schemas."""

from typing import Any

import marshmallow
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from sqlalchemy import func, select

from src_back.extensions import db
from src_back.models import BaseMixin


class BaseSchema(SQLAlchemyAutoSchema):
    """Auto schema that returns dicts on load and marks audit columns dump-only.

    Subclasses set ``Meta.model`` and list :data:`AUDIT` as ``dump_only`` so the
    client can never write the primary key, public identifier, or timestamps.
    """

    AUDIT = ('id', 'uuid', 'created_at', 'updated_at')

    class Meta(SQLAlchemyAutoSchema.Meta):
        """Shared marshmallow-sqlalchemy options."""

        load_instance = False
        sqla_session = db.session

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
