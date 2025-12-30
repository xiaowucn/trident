"""add resign for user

Revision ID: c8bd7dcd87f0
Revises: e89951f9f794
Create Date: 2020-05-21 10:29:59.526012

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8bd7dcd87f0'
down_revision = 'e89951f9f794'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('resign', sa.Boolean, server_default=sa.text('false')))


def downgrade():
    op.drop_column('user', 'resign')
