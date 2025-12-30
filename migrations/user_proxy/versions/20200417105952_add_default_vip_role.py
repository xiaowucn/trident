"""add default vip role

Revision ID: b8ae804d209f
Revises: e89951f9f794
Create Date: 2020-04-17 10:59:52.617762

"""
import os

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8ae804d209f'
down_revision = 'e89951f9f794'
branch_labels = None
depends_on = None
XYZQ = 'ENV' in os.environ and os.environ['ENV'] == 'xyzq'


def upgrade():
    if XYZQ:
        op.execute("""
            INSERT INTO roles (name, permission) VALUES ('vip', '{"autodoc": ["vip"], "autodoc_overall": ["vip"]}'::json)
        """)


def downgrade():
    op.execute("""
        DELETE FROM roles WHERE name = 'vip';
    """)
