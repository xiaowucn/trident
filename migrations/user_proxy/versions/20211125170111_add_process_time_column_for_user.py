"""add process_time column for user

Revision ID: 80ebf19ef4d2
Revises: 4e169d807092
Create Date: 2021-11-25 17:01:11.161408

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '80ebf19ef4d2'
down_revision = '4e169d807092'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('process_time', sa.Integer, server_default=sa.text('extract(epoch from now())::int')))


def downgrade():
    op.drop_column('user', 'process_time')
