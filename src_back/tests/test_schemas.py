from typing import Any, cast

import pytest
from marshmallow import ValidationError

from src_back.models import User
from src_back.schemas.base import BaseSchema
from src_back.schemas.user import login_schema, user_schema
from src_back.tests.conftest import WidgetNote


class WidgetNoteSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = WidgetNote
        # Auto schemas leave foreign keys out unless asked; a child schema that
        # accepts the parent id in the body must opt in.
        include_fk = True
        dump_only = BaseSchema.AUDIT


def test_user_schema_dump_exposes_public_fields_only(user):
    data = cast(dict[str, Any], user_schema.dump(user))
    assert set(data) == {'id', 'uuid', 'email', 'role', 'created_at', 'updated_at'}
    assert data['role'] == 'user'
    assert data['email'] == user.email


def test_user_schema_load_returns_email_and_password_only():
    data = user_schema.load({'email': 'a@b.test', 'password': 'password123'})
    assert data == {'email': 'a@b.test', 'password': 'password123'}


def test_user_schema_rejects_client_supplied_audit_or_role_fields():
    with pytest.raises(ValidationError):
        user_schema.load(
            {'email': 'a@b.test', 'password': 'password123', 'role': 'admin'}
        )
    with pytest.raises(ValidationError):
        user_schema.load({'email': 'a@b.test', 'password': 'password123', 'id': 7})


def test_user_schema_rejects_short_password_and_bad_email():
    with pytest.raises(ValidationError):
        user_schema.load({'email': 'a@b.test', 'password': 'short'})
    with pytest.raises(ValidationError):
        user_schema.load({'email': 'not-an-email', 'password': 'password123'})


def test_login_schema_requires_both_fields_and_accepts_short_passwords():
    with pytest.raises(ValidationError):
        login_schema.load({'email': 'a@b.test'})
    assert login_schema.load({'email': 'a@b.test', 'password': 'x'}) == {
        'email': 'a@b.test',
        'password': 'x',
    }


def test_base_schema_defaults_nullable_fields_to_none(app):
    assert WidgetNoteSchema().load({'widget_id': 1}) == {'widget_id': 1, 'body': None}


def test_base_schema_marks_audit_columns_dump_only(app):
    with pytest.raises(ValidationError):
        WidgetNoteSchema().load({'widget_id': 1, 'uuid': 'client-chosen'})


def test_user_repr_names_the_email(app):
    assert repr(User(email='a@b.test')) == '<User a@b.test>'
