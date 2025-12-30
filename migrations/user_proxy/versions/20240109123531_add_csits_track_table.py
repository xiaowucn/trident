"""add csits_track table

Revision ID: 38a3355421b1
Revises: c729a0e60e0f
Create Date: 2024-01-09 12:35:31.563890

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '38a3355421b1'
down_revision = 'c729a0e60e0f'
branch_labels = None
depends_on = None


# 中证埋点表
TABLE_NAME = "csits_track"


def upgrade():
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(), nullable=True),
        sa.Column("system_code", sa.String(), nullable=True),
        sa.Column("system_name", sa.String(), nullable=True),
        sa.Column("account", sa.String(), nullable=True),
        sa.Column("dept_name", sa.String(), nullable=True),
        sa.Column("event", sa.String(), nullable=True),
        sa.Column("event_time", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("path", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_table(TABLE_NAME)
