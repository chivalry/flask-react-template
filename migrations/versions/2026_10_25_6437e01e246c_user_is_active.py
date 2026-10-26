"""user is active

Revision ID: 6437e01e246c
Revises: e0234c78c7e5
Create Date: 2026-10-25 20:42:28.130028

Existing accounts become active through the server default.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6437e01e246c'
down_revision = 'e0234c78c7e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column(
            'is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False
        ),
    )


def downgrade():
    op.drop_column('users', 'is_active')
