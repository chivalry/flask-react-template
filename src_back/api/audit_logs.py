"""Audit-log routes.

One record's history, the admin's filtered log, and the audited tables.
"""

from flask import Blueprint, Response, jsonify, request
from flask_login import login_required
from sqlalchemy.orm import joinedload

from src_back.auth import current_user
from src_back.models import AuditLog, Role
from src_back.schemas.audit_log import audit_log_schema
from src_back.services.audit_log import (
    audited_tables,
    select_audit_entries,
    select_record_history,
)
from src_back.utils import (
    admin_required,
    bad_request,
    forbidden,
    not_found,
    paginate_select,
    parse_id_list,
    parse_query_datetime,
)

bp = Blueprint('audit_logs', __name__)

_WITH_ACTOR = joinedload(AuditLog.changed_by)
"""Loads each page's actors in the page query; changed_by_name reads them."""


@bp.get('')
@login_required
def list_record_history() -> tuple[Response, int]:
    """List one record's audit entries, newest first, one page at a time.

    The table check comes first, so an unknown table is a 404 whatever the other
    parameters are. The history of an admin-only table, such as the accounts, is a 403
    for anyone but an admin.

    Returns:
        The pagination envelope of serialized entries; a 404 envelope when no history
        is kept for ``table_name``; a 400 envelope when ``record_id`` is not an
        integer; or a 403 envelope when the table is admin-only and the caller is not
        an admin.
    """
    table_name = request.args.get('table_name', '')
    admin_only = audited_tables().get(table_name)
    if admin_only is None:
        return not_found('No history is kept for that table.')
    record_id = request.args.get('record_id', type=int)
    if record_id is None:
        return bad_request('record_id must be an integer.')
    if admin_only and current_user.role != Role.admin:
        return forbidden('Admin access required.')
    stmt = select_record_history(table_name, record_id)
    return paginate_select(stmt, audit_log_schema, _WITH_ACTOR)


@bp.get('/all')
@admin_required
def list_audit_log() -> tuple[Response, int]:
    """List every audit entry, narrowed by the query string, newest first.

    ``table_name`` may name any table, audited now or not, so entries from a table
    that stopped being audited stay reachable. ``changed_by_id`` is a comma-separated
    list of account ids. ``changed_from`` (inclusive) and ``changed_before``
    (exclusive) are ISO 8601 moments with a UTC offset.

    Returns:
        The pagination envelope of serialized entries, or a 400 envelope when
        ``changed_by_id`` is not a comma-separated list of ids or a moment is not an
        ISO 8601 date and time with a UTC offset.
    """
    try:
        changed_by_ids = parse_id_list('changed_by_id')
        changed_from = parse_query_datetime('changed_from')
        changed_before = parse_query_datetime('changed_before')
    except ValueError as exc:
        return bad_request(str(exc))
    stmt = select_audit_entries(
        table_name=request.args.get('table_name') or None,
        changed_by_ids=changed_by_ids,
        changed_from=changed_from,
        changed_before=changed_before,
    )
    return paginate_select(stmt, audit_log_schema, _WITH_ACTOR)


@bp.get('/tables')
@admin_required
def list_audited_tables() -> tuple[Response, int]:
    """List the tables whose history the routes serve.

    Returns:
        The audited tables' names, sorted, as a JSON array.
    """
    return jsonify(sorted(audited_tables())), 200
