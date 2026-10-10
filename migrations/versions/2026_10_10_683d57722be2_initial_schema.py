"""initial schema

Revision ID: 683d57722be2
Revises:
Create Date: 2026-10-10 13:00:53.813497

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '683d57722be2'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('admin', 'user', name='role', native_enum=False), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('uuid')
    )


def downgrade():
    op.drop_table('users')
