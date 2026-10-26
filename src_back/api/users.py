"""Accounts: admin-only management routes.

There is no delete route. An account is deactivated through the update route
instead, which keeps the rows that reference it intact.
"""

from flask import Blueprint, Response, jsonify

from src_back.auth import current_user
from src_back.schemas.user import user_schema, user_update_schema
from src_back.services.errors import DuplicateRecordError, SelfModificationError
from src_back.services.users import create_user, select_users_in_email_order, update_user
from src_back.utils import (
    admin_required,
    bad_request,
    conflict,
    dump_or_404,
    paginate_select,
    parse_request_json,
)

bp = Blueprint('users', __name__)


@bp.get('')
@admin_required
def list_accounts() -> tuple[Response, int]:
    """List every account, one page at a time.

    Returns:
        The pagination envelope of serialized accounts, in email order.
    """
    return paginate_select(select_users_in_email_order(), user_schema)


@bp.post('')
@admin_required
def create_account() -> tuple[Response, int]:
    """Create an account with the role and status the admin chose.

    A payload that fails validation never reaches this body: ``parse_request_json``
    raises and the application answers with a 422 envelope.

    Returns:
        The serialized account with status 201, or a 409 envelope when the
        email is already in use in any letter case.
    """
    data = parse_request_json(user_schema)
    try:
        user = create_user(data)
    except DuplicateRecordError as exc:
        return conflict(str(exc))
    return jsonify(user_schema.dump(user)), 201


@bp.put('/<int:user_id>')
@admin_required
def update_account(user_id: int) -> tuple[Response, int]:
    """Change an account's email, password, role, or active status.

    Args:
        user_id: The account's primary key.

    Returns:
        The serialized account, a 404 envelope for an unknown id, a 400
        envelope when the admin would deactivate or demote themself, or a 409
        envelope when the email belongs to another account in any letter case.
    """
    data = parse_request_json(user_update_schema)
    try:
        user = update_user(user_id, data, current_user.id)
    except SelfModificationError as exc:
        return bad_request(str(exc))
    except DuplicateRecordError as exc:
        return conflict(str(exc))
    return dump_or_404(user, user_schema)
