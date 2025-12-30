"""add session_id for user

Revision ID: db8079fd5883
Revises: e89951f9f794
Create Date: 2020-09-08 14:11:34.879542

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'db8079fd5883'
down_revision = 'e89951f9f794'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('session_id', sa.String))


def downgrade():
    op.drop_column('user', 'session_id')
