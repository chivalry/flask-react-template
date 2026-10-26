"""Account schemas: admin management, registration, sign-in, and serialization."""

from marshmallow import Schema, fields, validate

from src_back.models import Role, User
from src_back.schemas.base import BaseSchema

PASSWORD_RULE = validate.Length(min=8, error='Password must be at least 8 characters.')


class UserSchema(BaseSchema):
    """Serialize accounts and validate the admin's create payload.

    ``password`` is load-only so it is never echoed back. ``role`` and ``is_active``
    are writable because only admins reach the routes that load this schema;
    self-registration loads :class:`RegistrationSchema` instead. ``has_password`` is
    dump-only: it tells the client whether the account has a password without
    exposing the hash.
    """

    class Meta(BaseSchema.Meta):
        """Bind to the ``users`` table and hide the stored hash."""

        model = User
        exclude = ('password_hash',)
        dump_only = BaseSchema.AUDIT

    email = fields.Email(required=True)
    password = fields.Str(load_only=True, required=True, validate=PASSWORD_RULE)
    role = fields.Enum(Role, by_value=True, load_default=Role.user)
    is_active = fields.Boolean(load_default=True)
    has_password = fields.Boolean(dump_only=True)


class UserUpdateSchema(Schema):
    """Validate the admin's update payload; every field is optional."""

    email = fields.Email()
    password = fields.Str(load_only=True, validate=PASSWORD_RULE)
    role = fields.Enum(Role, by_value=True)
    is_active = fields.Boolean()


class RegistrationSchema(Schema):
    """Validate a self-registration payload, which carries only an email and a password.

    A ``role`` or ``is_active`` in the body is an unknown field, so validation fails
    with a 422 and nobody can register as an admin.
    """

    email = fields.Email(required=True)
    password = fields.Str(required=True, load_only=True, validate=PASSWORD_RULE)


class LoginSchema(Schema):
    """Validate a sign-in payload.

    Deliberately omits the length rule from :class:`UserSchema` so that
    credentials predating a policy change can still be submitted.
    """

    email = fields.Email(required=True)
    password = fields.Str(required=True, load_only=True)


user_schema = UserSchema()
user_update_schema = UserUpdateSchema()
registration_schema = RegistrationSchema()
login_schema = LoginSchema()
