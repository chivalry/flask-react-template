"""Base Marshmallow schema shared by every model-backed schema."""

from typing import Any

import marshmallow
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema

from src_back.extensions import db


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
