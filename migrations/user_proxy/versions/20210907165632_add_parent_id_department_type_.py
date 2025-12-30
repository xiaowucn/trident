"""add parent_id, department_type, department_data columns for department 

Revision ID: 92511c7cfee6
Revises: 6f52a42b0ecf
Create Date: 2021-09-07 16:56:32.474672

"""
import os

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '92511c7cfee6'
down_revision = '6f52a42b0ecf'
branch_labels = None
depends_on = None
_ENV = os.environ.get("ENV")
HT = _ENV == "ht"

def upgrade():
    if HT:
        op.add_column('departments', sa.Column('parent_id', sa.String))
        op.add_column('departments', sa.Column('department_data', sa.JSON))
        op.add_column('departments', sa.Column('department_type', sa.Integer))
        op.create_index('department_type_unique', 'departments', ['department_type'], unique=True)


def downgrade():
    if HT:
        op.drop_column('departments', "department_data")
        op.drop_column('departments', "parent_id")
        op.execute("""DROP INDEX IF EXISTS department_type_unique;""")
        op.drop_column('departments', "department_type")
