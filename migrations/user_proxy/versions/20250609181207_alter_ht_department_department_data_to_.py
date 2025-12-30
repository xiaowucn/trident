"""alter ht department department_data to data

Revision ID: c73817fa30ae
Revises: 455f051c30a9
Create Date: 2025-06-09 18:12:07.032418

"""
import os

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c73817fa30ae'
down_revision = '455f051c30a9'
branch_labels = None
depends_on = None

_ENV = os.environ.get("ENV")
HT = _ENV == "ht"

def upgrade():
    if HT:
        op.execute("""
                    alter table departments rename department_id to external_id;
                    alter table departments rename department to name;
                    alter table departments alter column name set not null;
                    alter table departments drop constraint departments_department_id_key;
                    alter table departments add unique (external_id);
                    alter table departments rename department_data to data;
                """)
        op.add_column('departments', sa.Column('allow_login', sa.Boolean, nullable=False, server_default=sa.text('true')))
    else:
        op.execute("""
                    alter table departments add unique (external_id);
                """)
        op.add_column('departments', sa.Column('department_type', sa.Integer))
        op.create_index('ix_parent_id_dep_type', 'departments', ['parent_id', 'department_type'])


def downgrade():
    if HT:
        op.execute("""
                    alter table departments rename external_id to department_id;
                    alter table departments rename name to department;
                    alter table departments rename data to department_data;
                    alter table departments add unique (department_id); 
                    """)
        op.drop_column('departments', 'allow_login')
    else:
        op.execute("""DROP INDEX IF EXISTS ix_parent_id_dep_type;""")
        op.drop_column('departments', "department_type")

    op.execute("""
                    alter table departments drop constraint departments_external_id_key;
                """)