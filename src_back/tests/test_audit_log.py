import enum
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from flask import Flask, g
from flask_login import login_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, select

from src_back.models import AuditAction, AuditLog, Role, User
from src_back.services import audit_log
from src_back.services.audit_log import (
    AuditTrail,
    audited_tables,
    create_audit_entry,
    diff,
    snapshot,
)
from src_back.tests.conftest import Widget, WidgetNote
from src_back.tests.helpers import persist

# -- snapshot and diff --------------------------------------------------------


class Priority(enum.Enum):
    # A plain enum: unlike Role, a StrEnum, its member is no string, so json.dumps
    # refuses it unless the snapshot converts it.
    high = 2


def test_snapshot_makes_every_value_json_safe() -> None:
    moment = datetime(2026, 10, 14, 16, 5, tzinfo=UTC)
    record = SimpleNamespace(
        price=Decimal('12.50'),
        day=date(2026, 10, 14),
        moment=moment,
        clock=time(9, 5),
        role=Role.admin,
        priority=Priority.high,
        token=UUID(int=1),
        nothing=None,
        count=3,
        flag=True,
        text='alpha',
    )
    result = snapshot(record, list(vars(record)))
    assert result == {
        'price': '12.50',
        'day': '2026-10-14',
        'moment': moment.isoformat(),
        'clock': '09:05:00',
        'role': 'admin',
        'priority': 2,
        'token': '00000000-0000-0000-0000-000000000001',
        'nothing': None,
        'count': 3,
        'flag': True,
        'text': 'alpha',
    }
    assert json.loads(json.dumps(result)) == result


def test_diff_lists_only_changed_fields() -> None:
    before = {'name': 'alpha', 'code': 'a1', 'note': None}
    after = {'name': 'beta', 'code': 'a1', 'note': 'hello'}
    assert diff(before, after) == {
        'name': {'old': 'alpha', 'new': 'beta'},
        'note': {'old': None, 'new': 'hello'},
    }
    assert diff(before, before) == {}


# -- create_audit_entry -------------------------------------------------------


def test_entry_is_added_without_a_commit(db: SQLAlchemy) -> None:
    entry = create_audit_entry(
        'widgets', 1, 'alpha', AuditAction.created, {'name': 'alpha'}
    )
    assert entry is not None
    assert entry in db.session.new
    db.session.rollback()
    assert db.session.scalar(select(func.count(AuditLog.id))) == 0


def test_update_that_changed_nothing_is_skipped(db: SQLAlchemy) -> None:
    assert create_audit_entry('widgets', 1, None, AuditAction.updated, {}) is None
    assert not db.session.new
    entry = create_audit_entry('widgets', 1, None, AuditAction.deleted, {})
    assert entry is not None
    assert entry in db.session.new


def test_entry_outside_a_request_has_no_actor(db: SQLAlchemy) -> None:
    entry = create_audit_entry('widgets', 1, None, AuditAction.created, {})
    assert entry is not None
    assert entry.changed_by_id is None


def test_entry_in_an_anonymous_request_has_no_actor(app: Flask) -> None:
    with app.test_request_context():
        entry = create_audit_entry('widgets', 1, None, AuditAction.created, {})
    assert entry is not None
    assert entry.changed_by_id is None


def test_entry_in_a_signed_in_request_names_the_actor(app: Flask, user: User) -> None:
    with app.test_request_context():
        login_user(user)
        entry = create_audit_entry('widgets', 1, None, AuditAction.created, {})
    assert entry is not None
    assert entry.changed_by_id == user.id
    # The fixture's application context outlives the request, and Flask-Login caches
    # the signed-in user on it.
    g.pop('_login_user', None)


# -- AuditTrail and the registry ----------------------------------------------


@pytest.mark.usefixtures('app')
def test_trail_registers_its_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_log, '_AUDITED_TABLES', {})
    AuditTrail(Widget, ('name',))
    AuditTrail(WidgetNote, ('body',), None, admin_only=True)
    assert dict(audited_tables()) == {'widgets': False, 'widget_notes': True}
    AuditTrail(WidgetNote, ('body',), None)
    assert audited_tables()['widget_notes'] is True
    with pytest.raises(TypeError):
        audited_tables()['x'] = True  # pyright: ignore[reportIndexIssue]


@pytest.mark.usefixtures('app')
def test_trail_rejects_attributes_the_model_lacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_log, '_AUDITED_TABLES', {})
    with pytest.raises(ValueError) as unknown_field:
        AuditTrail(Widget, ('nope',))
    assert str(unknown_field.value) == 'Widget has no attribute nope.'
    with pytest.raises(ValueError) as unknown_label:
        AuditTrail(WidgetNote, ('body',))
    assert str(unknown_label.value) == 'WidgetNote has no attribute name.'
    assert dict(audited_tables()) == {}


def test_trail_labels_entries(db: SQLAlchemy) -> None:
    named = AuditTrail(Widget, ('name',))
    long_label = named.log(SimpleNamespace(id=1, name='n' * 300), AuditAction.deleted, {})
    assert long_label is not None
    assert long_label.record_label == 'n' * 255

    body_labelled = AuditTrail(WidgetNote, ('body',), 'body')
    no_value = body_labelled.log(
        SimpleNamespace(id=2, body=None), AuditAction.deleted, {}
    )
    assert no_value is not None
    assert no_value.record_label is None

    unlabelled = AuditTrail(WidgetNote, ('body',), None)
    no_field = unlabelled.log(SimpleNamespace(id=3, body='kept'), AuditAction.deleted, {})
    assert no_field is not None
    assert no_field.record_label is None


# -- AuditLog -----------------------------------------------------------------


def test_deleting_an_account_keeps_its_entries_without_an_actor(
    db: SQLAlchemy, user: User
) -> None:
    entry = persist(
        AuditLog(
            table_name='widgets',
            record_id=1,
            record_label='alpha',
            action=AuditAction.created,
            changes={'name': 'alpha'},
            changed_by_id=user.id,
        )
    )
    db.session.delete(user)
    db.session.commit()
    db.session.refresh(entry)
    assert entry.changed_by_id is None
    assert entry.changed_by_name is None


def test_entry_names_its_actor_and_describes_itself(admin_user: User) -> None:
    entry = persist(
        AuditLog(
            table_name='widgets',
            record_id=1,
            record_label='alpha',
            action=AuditAction.created,
            changes={'name': 'alpha'},
            changed_by_id=admin_user.id,
        )
    )
    assert entry.changed_by_name == 'admin@test.com'
    assert repr(entry) == '<AuditLog widgets:1 created>'
