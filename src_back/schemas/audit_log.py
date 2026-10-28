"""Audit-log serialization; entries are only ever dumped, never loaded."""

from marshmallow import fields

from src_back.models import AuditAction, AuditLog
from src_back.schemas.base import BaseSchema


class AuditLogSchema(BaseSchema):
    """Serialize audit entries for the history routes.

    Every field is dump-only: no route accepts an entry. ``changed_by_name`` reads
    :attr:`~src_back.models.AuditLog.changed_by_name`, so a route loads the
    ``changed_by`` relationship with its page.
    """

    class Meta(BaseSchema.Meta):
        """Bind to the ``audit_logs`` table, keeping its foreign key."""

        model = AuditLog
        include_fk = True
        dump_only = (
            *BaseSchema.AUDIT,
            'table_name',
            'record_id',
            'record_label',
            'changes',
            'changed_by_id',
            'changed_at',
        )

    action = fields.Enum(AuditAction, by_value=True, dump_only=True)
    changed_by_name = fields.String(dump_only=True)


audit_log_schema = AuditLogSchema()
