"""add partial unique constraint for roles

Revision ID: b04b2f3e6247
Revises: c8b2419d5620
Create Date: 2019-09-18 12:45:07.647378

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b04b2f3e6247'
down_revision = 'c8b2419d5620'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE UNIQUE INDEX tbl_unique_constraint_oa_default ON roles (oa_default) WHERE oa_default = 'true';")


def downgrade():
    op.execute("DROP INDEX tbl_unique_constraint_oa_default;")
