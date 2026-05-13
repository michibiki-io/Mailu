"""Add invisible column to fetch table

Revision ID: fdff7f84d363
Revises: 31f40da48c01
Create Date: 2026-05-11 08:55:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'fdff7f84d363'
down_revision = '31f40da48c01'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('fetch', sa.Column('invisible', sa.Boolean(), nullable=False, server_default=sa.sql.expression.false()))


def downgrade():
    op.drop_column('fetch', 'invisible')
