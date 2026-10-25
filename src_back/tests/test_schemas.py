from typing import Any, cast

import pytest
from flask import Flask
from marshmallow import ValidationError

from src_back.models import User
from src_back.schemas.base import BaseSchema, validate_ids_exist
from src_back.schemas.user import login_schema, user_schema
from src_back.tests.conftest import Widget, WidgetNote
from src_back.tests.helpers import persist


class WidgetNoteSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = WidgetNote
        # Auto schemas leave foreign keys out unless asked; a child schema that
        # accepts the parent id in the body must opt in.
        include_fk = True
        dump_only = BaseSchema.AUDIT


def test_user_schema_dump_exposes_public_fields_only(user: User) -> None:
    data = cast(dict[str, Any], user_schema.dump(user))
    assert set(data) == {'id', 'uuid', 'email', 'role', 'created_at', 'updated_at'}
    assert data['role'] == 'user'
    assert data['email'] == user.email


def test_user_schema_load_returns_email_and_password_only() -> None:
    data = user_schema.load({'email': 'a@b.test', 'password': 'password123'})
    assert data == {'email': 'a@b.test', 'password': 'password123'}


def test_user_schema_rejects_client_supplied_audit_or_role_fields() -> None:
    with pytest.raises(ValidationError):
        user_schema.load(
            {'email': 'a@b.test', 'password': 'password123', 'role': 'admin'}
        )
    with pytest.raises(ValidationError):
        user_schema.load({'email': 'a@b.test', 'password': 'password123', 'id': 7})


def test_user_schema_rejects_short_password_and_bad_email() -> None:
    with pytest.raises(ValidationError):
        user_schema.load({'email': 'a@b.test', 'password': 'short'})
    with pytest.raises(ValidationError):
        user_schema.load({'email': 'not-an-email', 'password': 'password123'})


def test_login_schema_requires_both_fields_and_accepts_short_passwords() -> None:
    with pytest.raises(ValidationError):
        login_schema.load({'email': 'a@b.test'})
    assert login_schema.load({'email': 'a@b.test', 'password': 'x'}) == {
        'email': 'a@b.test',
        'password': 'x',
    }


def test_base_schema_defaults_nullable_fields_to_none(app: Flask) -> None:
    assert WidgetNoteSchema().load({'widget_id': 1}) == {'widget_id': 1, 'body': None}


def test_base_schema_marks_audit_columns_dump_only(app: Flask) -> None:
    with pytest.raises(ValidationError):
        WidgetNoteSchema().load({'widget_id': 1, 'uuid': 'client-chosen'})


def test_user_repr_names_the_email(app: Flask) -> None:
    assert repr(User(email='a@b.test')) == '<User a@b.test>'


@pytest.mark.parametrize('ids', [None, []])
def test_validate_ids_exist_accepts_an_omitted_or_empty_list(
    app: Flask, ids: list[int] | None
) -> None:
    assert validate_ids_exist(Widget, ids, 'widget') is None


def test_validate_ids_exist_counts_a_repeated_known_id_once(app: Flask) -> None:
    widget = persist(Widget(name='a'))
    assert validate_ids_exist(Widget, [widget.id, widget.id], 'widget') is None


def test_validate_ids_exist_rejects_an_unknown_id(app: Flask) -> None:
    widget = persist(Widget(name='a'))
    with pytest.raises(ValidationError, match='Unknown widget id.'):
        validate_ids_exist(Widget, [widget.id, widget.id + 1], 'widget')
