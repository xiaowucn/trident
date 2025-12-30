"""add role_data column for role

Revision ID: 2225c263c117
Revises: d10fa7bb9d2b
Create Date: 2022-04-12 16:55:40.174870

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
from sqlalchemy.dialects.postgresql import JSONB

revision = '2225c263c117'
down_revision = 'd10fa7bb9d2b'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("roles", sa.Column("role_data", JSONB))


def downgrade():
    op.drop_column("roles", "role_data")
