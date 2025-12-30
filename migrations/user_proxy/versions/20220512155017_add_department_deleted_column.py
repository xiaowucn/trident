"""add department deleted column

Revision ID: 99abfb547e7c
Revises: 2225c263c117
Create Date: 2022-05-12 15:50:17.042072

"""
import os

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '99abfb547e7c'
down_revision = '2225c263c117'
branch_labels = None
depends_on = None

_ENV = os.environ.get("ENV")
HT = _ENV == "ht"


def upgrade():
    if not HT:
        op.add_column('departments', sa.Column('deleted', sa.Integer, server_default=sa.text('0')))


def downgrade():
    if not HT:
        op.drop_column('departments', 'deleted')
