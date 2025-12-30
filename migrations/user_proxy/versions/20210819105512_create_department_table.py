"""

Revision ID: de427f3c2ce9
Revises: bb9cb05ca84c
Create Date: 2021-08-19 10:55:12.575244

"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = 'de427f3c2ce9'
down_revision = 'bb9cb05ca84c'
branch_labels = None
depends_on = None
_ENV = os.environ.get("ENV")
HT = _ENV == "ht"


def upgrade():
    if not HT:
        op.create_table(
            'departments',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('name', sa.String, nullable=False),
            sa.Column('allow_login', sa.Boolean, nullable=False),
            sa.Column('parent_id', sa.String),
            sa.Column('external_id', sa.String),
            sa.Column('data', JSONB, nullable=True),
            sa.Column('created_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
            sa.Column('updated_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
        )


def downgrade():
    if not HT:
        op.drop_table('departments')