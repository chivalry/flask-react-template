"""normalize_emails_and_nullable_password

Revision ID: e0234c78c7e5
Revises: 683d57722be2
Create Date: 2026-10-25 16:55:30.848712

Stores every email in the form src_back.models.user.normalize_email produces, and
lets users.password_hash be NULL for accounts that sign-in providers create.

Emails are folded in Python by a frozen copy of normalize_email, not by SQL lower()
and trim(): SQLite's lower() folds only ASCII, PostgreSQL's follows the database
locale, and trim() strips only spaces, so either could store a form that sign-in
never computes. The upgrade stops before changing anything when two accounts would
share an email once folded: merge them by hand (ai/auth.md), then run it again. The
downgrade restores NOT NULL and stops while any account has no password; emails
stay folded.
"""
from collections import defaultdict

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e0234c78c7e5'
down_revision = '683d57722be2'
branch_labels = None
depends_on = None

# Enough accounts to act on, and few enough that the deploy's 50-line log tail still
# shows the instruction printed after them.
LISTED_ACCOUNTS_LIMIT = 20


def upgrade():
    connection = op.get_bind()
    accounts = connection.execute(
        sa.text('SELECT id, email FROM users ORDER BY id')
    ).all()
    _abort_listing_accounts(
        _accounts_whose_emails_collide_once_normalized(accounts),
        'Cannot normalize emails: these accounts collide once trimmed and lowercased.',
        'Merge them by hand (see ai/auth.md), then run the upgrade again.',
    )
    for account in accounts:
        normalized = _normalize_email(account.email)
        if normalized != account.email:
            connection.execute(
                sa.text('UPDATE users SET email = :email WHERE id = :id'),
                {'email': normalized, 'id': account.id},
            )
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column(
            'password_hash', existing_type=sa.String(length=255), nullable=True
        )


def downgrade():
    passwordless = op.get_bind().execute(
        sa.text('SELECT id, email FROM users WHERE password_hash IS NULL ORDER BY id')
    ).all()
    _abort_listing_accounts(
        passwordless,
        'Cannot make users.password_hash NOT NULL: these accounts have no password.',
        'Give each one a password or delete it, then run the downgrade again.',
    )
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column(
            'password_hash', existing_type=sa.String(length=255), nullable=False
        )


def _normalize_email(email):
    # A frozen copy of src_back.models.user.normalize_email: a migration must keep
    # doing what it did when it was written, whatever the application code becomes.
    return email.strip().lower()


def _accounts_whose_emails_collide_once_normalized(accounts):
    by_normalized_email = defaultdict(list)
    for account in accounts:
        by_normalized_email[_normalize_email(account.email)].append(account)
    return [
        account
        for group in by_normalized_email.values()
        if len(group) > 1
        for account in group
    ]


def _abort_listing_accounts(accounts, headline, instruction):
    if not accounts:
        return
    listed = [
        f'  id {account.id}: {account.email!r}'
        for account in accounts[:LISTED_ACCOUNTS_LIMIT]
    ]
    if len(accounts) > LISTED_ACCOUNTS_LIMIT:
        listed.append(f'  ... and {len(accounts) - LISTED_ACCOUNTS_LIMIT} more')
    raise RuntimeError('\n'.join([headline, *listed, instruction]))
