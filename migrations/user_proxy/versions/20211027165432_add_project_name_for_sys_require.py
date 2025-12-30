"""add project name for sys require

Revision ID: d10fa7bb9d2b
Revises: 04ab8fb80048
Create Date: 2021-10-27 16:54:32.875095

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd10fa7bb9d2b'
down_revision = '04ab8fb80048'
branch_labels = None
depends_on = None

table_name = "sys_require"
column_name = "project_name"


def upgrade():
    op.add_column(table_name, sa.Column(column_name, sa.String, server_default=''))


def downgrade():
    op.drop_column(table_name, column_name)
