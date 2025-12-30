"""add super_admin column for role

Revision ID: 04ab8fb80048
Revises: de427f3c2ce9
Create Date: 2021-09-24 15:39:48.902524

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '04ab8fb80048'
down_revision = 'de427f3c2ce9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('roles', sa.Column('super_admin', sa.Boolean, server_default=sa.text('false')))


def downgrade():
    op.drop_column('roles', 'super_admin')
