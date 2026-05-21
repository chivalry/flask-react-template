from marshmallow import Schema, fields, validate


class UserSchema(Schema):
    id = fields.Int(dump_only=True)
    uuid = fields.Str(dump_only=True)
    email = fields.Email(required=True)
    password = fields.Str(
        load_only=True,
        required=True,
        validate=validate.Length(min=8, error="Password must be at least 8 characters."),
    )
    role = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class LoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.Str(required=True, load_only=True)


user_schema = UserSchema()
login_schema = LoginSchema()
