"""Marshmallow schemas for accounts: registration, sign-in, and serialization."""

from marshmallow import Schema, fields, validate

from src_back.models import Role, User
from src_back.schemas.base import BaseSchema


class UserSchema(BaseSchema):
    """Serialize accounts and validate registration payloads.

    ``password`` is load-only so it is never echoed back, and ``role`` is
    dump-only so a client cannot grant itself privileges at registration.
    """

    class Meta(BaseSchema.Meta):
        """Bind to the ``users`` table and hide the stored hash."""

        model = User
        exclude = ('password_hash',)
        dump_only = BaseSchema.AUDIT

    email = fields.Email(required=True)
    password = fields.Str(
        load_only=True,
        required=True,
        validate=validate.Length(min=8, error='Password must be at least 8 characters.'),
    )
    role = fields.Enum(Role, by_value=True, dump_only=True)


class LoginSchema(Schema):
    """Validate a sign-in payload.

    Deliberately omits the length rule from :class:`UserSchema` so that
    credentials predating a policy change can still be submitted.
    """

    email = fields.Email(required=True)
    password = fields.Str(required=True, load_only=True)


user_schema = UserSchema()
login_schema = LoginSchema()
