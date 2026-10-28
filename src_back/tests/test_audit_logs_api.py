from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from src_back.models import AuditAction, AuditLog, User
from src_back.services import audit_log
from src_back.tests.helpers import persist

HISTORY_URL = '/api/v1/audit-logs'
ALL_URL = f'{HISTORY_URL}/all'
TABLES_URL = f'{HISTORY_URL}/tables'
USERS_URL = '/api/v1/users'

DAY = datetime(2026, 10, 14, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pin_audited_tables(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    # Taking ``app`` builds the application, and registers ``users``, before the
    # patch. The tables go in out of order, so ``/tables`` has a sort to show.
    monkeypatch.setattr(audit_log, '_AUDITED_TABLES', {'widgets': False, 'users': True})


def _entry(
    table_name: str = 'widgets',
    record_id: int = 1,
    *,
    changed_at: datetime = DAY,
    changed_by: User | None = None,
    changes: dict[str, Any] | None = None,
) -> AuditLog:
    return persist(
        AuditLog(
            table_name=table_name,
            record_id=record_id,
            record_label=f'{table_name} {record_id}',
            action=AuditAction.updated,
            changes={'name': {'old': 'a', 'new': 'b'}} if changes is None else changes,
            changed_by_id=None if changed_by is None else changed_by.id,
            changed_at=changed_at,
        )
    )


# -- access control -----------------------------------------------------------


@pytest.mark.parametrize('path', [HISTORY_URL, ALL_URL, TABLES_URL])
def test_routes_reject_anonymous_callers(client: FlaskClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 401
    assert r.get_json() == {'error': 'Unauthorized'}


@pytest.mark.parametrize('path', [ALL_URL, TABLES_URL])
def test_admin_routes_forbid_non_admins(auth_client: FlaskClient, path: str) -> None:
    r = auth_client.get(path)
    assert r.status_code == 403
    assert r.get_json() == {'error': 'Admin access required.'}


# -- one record's history -----------------------------------------------------


def test_record_history_is_newest_first_and_only_that_record(
    auth_client: FlaskClient, admin_user: User
) -> None:
    older = _entry(changed_at=DAY + timedelta(hours=10))
    newer = _entry(changed_at=DAY + timedelta(hours=12), changed_by=admin_user)
    _entry(record_id=2, changed_at=DAY + timedelta(hours=11))
    _entry('users', 1, changed_at=DAY + timedelta(hours=13))
    r = auth_client.get(
        HISTORY_URL, query_string={'table_name': 'widgets', 'record_id': 1}
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data['total'] == 2
    assert data['page'] == 1
    assert data['pages'] == 1
    assert data['per_page'] == 20
    assert [item['id'] for item in data['items']] == [newer.id, older.id]
    assert [item['changed_by_name'] for item in data['items']] == [
        'admin@test.com',
        None,
    ]
    # In UTC with an explicit offset, on SQLite too, which stores datetimes without one;
    # a browser would read an offset-less string as local time.
    assert [item['changed_at'] for item in data['items']] == [
        '2026-10-14T12:00:00+00:00',
        '2026-10-14T10:00:00+00:00',
    ]


def test_history_breaks_ties_by_id(auth_client: FlaskClient) -> None:
    first = _entry()
    second = _entry()
    r = auth_client.get(
        HISTORY_URL, query_string={'table_name': 'widgets', 'record_id': 1}
    )
    assert r.status_code == 200
    assert [item['id'] for item in r.get_json()['items']] == [second.id, first.id]


def test_record_history_pages(auth_client: FlaskClient) -> None:
    entries = [_entry(changed_at=DAY + timedelta(hours=hour)) for hour in (1, 2, 3)]
    r = auth_client.get(
        HISTORY_URL,
        query_string={'table_name': 'widgets', 'record_id': 1, 'per_page': 2, 'page': 2},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data['total'] == 3
    assert data['page'] == 2
    assert data['pages'] == 2
    assert data['per_page'] == 2
    assert [item['id'] for item in data['items']] == [entries[0].id]


@pytest.mark.parametrize('table_name', ['', 'widget_notes'])
def test_unaudited_table_has_no_history(
    auth_client: FlaskClient, table_name: str
) -> None:
    # No record_id: the table check comes before the record id is read.
    r = auth_client.get(HISTORY_URL, query_string={'table_name': table_name})
    assert r.status_code == 404
    assert r.get_json() == {'error': 'No history is kept for that table.'}


@pytest.mark.parametrize(
    'query',
    [{}, {'record_id': ''}, {'record_id': 'abc'}],
    ids=['missing', 'blank', 'text'],
)
def test_record_history_needs_an_integer_record_id(
    auth_client: FlaskClient, query: dict[str, str]
) -> None:
    r = auth_client.get(HISTORY_URL, query_string={'table_name': 'widgets', **query})
    assert r.status_code == 400
    assert r.get_json() == {'error': 'record_id must be an integer.'}


def test_account_history_is_admin_only(auth_client: FlaskClient, user: User) -> None:
    _entry('users', user.id)
    r = auth_client.get(
        HISTORY_URL, query_string={'table_name': 'users', 'record_id': user.id}
    )
    assert r.status_code == 403
    assert r.get_json() == {'error': 'Admin access required.'}


def test_admin_reads_an_accounts_history(admin_client: FlaskClient, user: User) -> None:
    entry = _entry('users', user.id)
    r = admin_client.get(
        HISTORY_URL, query_string={'table_name': 'users', 'record_id': user.id}
    )
    assert r.status_code == 200
    assert [item['id'] for item in r.get_json()['items']] == [entry.id]


# -- the admin's log ----------------------------------------------------------


def test_log_lists_every_table_newest_first(admin_client: FlaskClient) -> None:
    oldest = _entry('widgets', 1, changed_at=DAY + timedelta(hours=1))
    # Not in the registry: the log still reaches a table that is no longer audited.
    middle = _entry('widget_notes', 3, changed_at=DAY + timedelta(hours=2))
    newest = _entry('users', 2, changed_at=DAY + timedelta(hours=3))
    r = admin_client.get(ALL_URL)
    assert r.status_code == 200
    data = r.get_json()
    assert data['total'] == 3
    assert [item['id'] for item in data['items']] == [newest.id, middle.id, oldest.id]


def test_log_reads_a_blank_table_as_every_table(admin_client: FlaskClient) -> None:
    widget_entry = _entry('widgets', 1)
    account_entry = _entry('users', 2)
    r = admin_client.get(ALL_URL, query_string={'table_name': ''})
    assert r.status_code == 200
    listed = {item['id'] for item in r.get_json()['items']}
    assert listed == {widget_entry.id, account_entry.id}


def test_log_filters_by_table_and_account(
    admin_client: FlaskClient, admin_user: User, user: User
) -> None:
    by_admin = _entry('widgets', 1, changed_by=admin_user)
    by_user = _entry('users', 2, changed_by=user)
    by_nobody = _entry('widgets', 3)

    def listed(query: dict[str, Any]) -> set[int]:
        r = admin_client.get(ALL_URL, query_string=query)
        assert r.status_code == 200
        return {item['id'] for item in r.get_json()['items']}

    both_ids = f'{admin_user.id},{user.id}'
    assert listed({'table_name': 'widgets'}) == {by_admin.id, by_nobody.id}
    assert listed({'changed_by_id': admin_user.id}) == {by_admin.id}
    assert listed({'changed_by_id': both_ids}) == {by_admin.id, by_user.id}
    assert listed({'table_name': 'widgets', 'changed_by_id': both_ids}) == {by_admin.id}


def test_log_rejects_a_malformed_account_filter(admin_client: FlaskClient) -> None:
    r = admin_client.get(ALL_URL, query_string={'changed_by_id': '1,x'})
    assert r.status_code == 400
    assert r.get_json() == {
        'error': 'changed_by_id must be a comma-separated list of ids.'
    }


def test_log_range_includes_its_start_and_excludes_its_end(
    admin_client: FlaskClient,
) -> None:
    _entry(changed_at=DAY + timedelta(hours=6))
    inside = _entry(changed_at=DAY + timedelta(hours=7))
    _entry(changed_at=DAY + timedelta(hours=8))
    r = admin_client.get(
        ALL_URL,
        query_string={
            'changed_from': '2026-10-14T07:00:00Z',
            'changed_before': '2026-10-14T08:00:00Z',
        },
    )
    assert r.status_code == 200
    assert [item['id'] for item in r.get_json()['items']] == [inside.id]


def test_log_range_reads_offsets(admin_client: FlaskClient) -> None:
    _entry(changed_at=DAY + timedelta(hours=6))
    at_start = _entry(changed_at=DAY + timedelta(hours=7))
    r = admin_client.get(
        ALL_URL, query_string={'changed_from': '2026-10-14T00:00:00-07:00'}
    )
    assert r.status_code == 200
    assert [item['id'] for item in r.get_json()['items']] == [at_start.id]


@pytest.mark.parametrize('value', ['2026-10-14', 'yesterday', '2026-10-14T07:00:00'])
def test_log_rejects_a_malformed_moment(admin_client: FlaskClient, value: str) -> None:
    r = admin_client.get(ALL_URL, query_string={'changed_from': value})
    assert r.status_code == 400
    assert r.get_json() == {
        'error': 'changed_from must be an ISO 8601 date and time with a UTC offset.'
    }


# -- the audited tables -------------------------------------------------------


def test_tables_lists_the_audited_tables_in_order(admin_client: FlaskClient) -> None:
    r = admin_client.get(TABLES_URL)
    assert r.status_code == 200
    assert r.get_json() == ['users', 'widgets']


# -- an admin's edit, end to end ----------------------------------------------


def test_an_admin_edit_shows_in_the_accounts_history(
    admin_client: FlaskClient, user: User
) -> None:
    r = admin_client.put(f'{USERS_URL}/{user.id}', json={'role': 'admin'})
    assert r.status_code == 200
    r = admin_client.get(
        HISTORY_URL, query_string={'table_name': 'users', 'record_id': user.id}
    )
    assert r.status_code == 200
    (item,) = r.get_json()['items']
    assert item['action'] == 'updated'
    assert item['changes'] == {'role': {'old': 'user', 'new': 'admin'}}
    assert item['changed_by_name'] == 'admin@test.com'
