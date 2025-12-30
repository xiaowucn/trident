"""adjust department index

Revision ID: 6e63fc362eba
Revises: 92511c7cfee6
Create Date: 2021-09-10 10:34:23.151740

"""
import os

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '6e63fc362eba'
down_revision = '92511c7cfee6'
branch_labels = None
depends_on = None
_ENV = os.environ.get("ENV")
HT = _ENV == "ht"


def upgrade():
    if HT:
        op.execute("""DROP INDEX IF EXISTS department_type_unique;""")
        op.create_index('ix_parent_id_dep_type', 'departments', ['parent_id', 'department_type'])


def downgrade():
    if HT:
        op.drop_index('ix_parent_id_dep_type', 'departments')
