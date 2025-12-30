"""add deleted column for department

Revision ID: 4e169d807092
Revises: 6e63fc362eba
Create Date: 2021-09-13 15:46:43.598925

"""
import os

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '4e169d807092'
down_revision = '6e63fc362eba'
branch_labels = None
depends_on = None

_ENV = os.environ.get("ENV")
HT = _ENV == "ht"


def upgrade():
    if HT:
        op.add_column('departments', sa.Column('deleted', sa.Integer, server_default=sa.text('0')))


def downgrade():
    if HT:
        op.drop_column('departments', 'deleted')
