from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from flask import Flask
from marshmallow import Schema, ValidationError

from src_back.models import Role, User
from src_back.models.user import normalize_email
from src_back.schemas.base import BaseSchema, UTCDateTime, validate_ids_exist
from src_back.schemas.user import (
    login_schema,
    registration_schema,
    user_schema,
    user_update_schema,
)
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
    assert set(data) == {
        'id',
        'uuid',
        'email',
        'role',
        'is_active',
        'has_password',
        'created_at',
        'updated_at',
    }
    assert data['role'] == 'user'
    assert data['email'] == user.email
    assert data['has_password'] is True


def test_user_schema_dump_reports_a_passwordless_account(passwordless_user: User) -> None:
    data = cast(dict[str, Any], user_schema.dump(passwordless_user))
    assert data['has_password'] is False


def test_user_schema_load_defaults_to_an_active_user() -> None:
    data = user_schema.load({'email': 'a@b.test', 'password': 'password123'})
    assert data == {
        'email': 'a@b.test',
        'password': 'password123',
        'role': Role.user,
        'is_active': True,
    }


def test_user_schema_lets_an_admin_set_role_and_is_active() -> None:
    data = user_schema.load(
        {
            'email': 'a@b.test',
            'password': 'password123',
            'role': 'admin',
            'is_active': False,
        }
    )
    assert data['role'] is Role.admin
    assert data['is_active'] is False


def test_user_schema_rejects_client_supplied_audit_fields() -> None:
    with pytest.raises(ValidationError):
        user_schema.load({'email': 'a@b.test', 'password': 'password123', 'id': 7})


def test_registration_schema_loads_email_and_password_only() -> None:
    data = registration_schema.load({'email': 'a@b.test', 'password': 'password123'})
    assert data == {'email': 'a@b.test', 'password': 'password123'}


@pytest.mark.parametrize(('field', 'value'), [('role', 'admin'), ('is_active', False)])
def test_registration_schema_rejects_role_and_is_active(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        registration_schema.load(
            {'email': 'a@b.test', 'password': 'password123', field: value}
        )
    assert excinfo.value.messages == {field: ['Unknown field.']}


@pytest.mark.parametrize(
    'schema', [user_schema, registration_schema], ids=['user', 'registration']
)
def test_account_schemas_reject_short_password_and_bad_email(schema: Schema) -> None:
    with pytest.raises(ValidationError):
        schema.load({'email': 'a@b.test', 'password': 'short'})
    with pytest.raises(ValidationError):
        schema.load({'email': 'not-an-email', 'password': 'password123'})


def test_user_update_schema_accepts_an_empty_payload() -> None:
    assert user_update_schema.load({}) == {}


def test_user_update_schema_rejects_a_short_password() -> None:
    with pytest.raises(ValidationError):
        user_update_schema.load({'password': 'short'})


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


def test_base_schema_serializes_datetime_columns_with_utc_datetime(app: Flask) -> None:
    fields = WidgetNoteSchema().fields
    assert isinstance(fields['created_at'], UTCDateTime)
    assert isinstance(fields['updated_at'], UTCDateTime)


def test_utc_datetime_gives_every_value_an_explicit_utc_offset() -> None:
    field = UTCDateTime()
    # SQLite returns this without its offset; PostgreSQL may return another zone's.
    naive = datetime(2026, 10, 14, 16, 5)
    pacific = datetime(2026, 10, 14, 9, 5, tzinfo=timezone(timedelta(hours=-7)))
    assert field.serialize('at', {'at': naive}) == '2026-10-14T16:05:00+00:00'
    assert field.serialize('at', {'at': pacific}) == '2026-10-14T16:05:00+00:00'
    assert field.serialize('at', {'at': None}) is None


def test_user_repr_names_the_email(app: Flask) -> None:
    assert repr(User(email='a@b.test')) == '<User a@b.test>'


def test_normalize_email_trims_and_lowercases() -> None:
    assert normalize_email('  Mixed@Example.COM\n') == 'mixed@example.com'


def test_user_stores_every_assigned_email_normalized(app: Flask) -> None:
    account = User(email='  Mixed@Example.COM ')
    assert account.email == 'mixed@example.com'
    account.email = 'Other@Example.COM'
    assert account.email == 'other@example.com'


def test_user_without_a_password_never_matches_one(passwordless_user: User) -> None:
    assert passwordless_user.has_password is False
    assert passwordless_user.check_password('password123') is False


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
