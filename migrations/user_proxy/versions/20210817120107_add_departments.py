"""add departments

Revision ID: 73230b6df394
Revises: 39c8e20f51ef
Create Date: 2021-08-17 12:01:07.112883

"""
import os

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '73230b6df394'
down_revision = '39c8e20f51ef'
branch_labels = None
depends_on = None
_ENV = os.environ.get("ENV")
HT = _ENV == "ht"


def upgrade():
    if HT:
        op.create_table(
            'departments',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('department_id', sa.String, unique=True),
            sa.Column('department', sa.String),
            sa.Column('created_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
            sa.Column('updated_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
        )

    op.add_column('user', sa.Column('department_id', sa.Integer, index=True))


def downgrade():
    if HT:
        op.drop_table('departments')
    op.drop_column('user', 'department_id')
