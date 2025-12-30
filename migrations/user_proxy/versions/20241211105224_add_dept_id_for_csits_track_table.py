"""add dept_id for csits_track table

Revision ID: 146a07fb21a6
Revises: 776293d0ef84
Create Date: 2024-12-11 10:52:24.201013

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "146a07fb21a6"
down_revision = "776293d0ef84"
branch_labels = None
depends_on = None

table_name = "csits_track"
column_name = "dept_id"


def upgrade():
    op.add_column(table_name, sa.Column(column_name, sa.String, nullable=True))


def downgrade():
    op.drop_column(table_name, column_name)
