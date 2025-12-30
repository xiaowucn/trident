"""add permissions for user

Revision ID: 37bbd28f39aa
Revises: 7941d33c266c
Create Date: 2019-09-04 12:00:06.016331

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '37bbd28f39aa'
down_revision = 'a846f4a97770'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('permissions', sa.ARRAY(sa.String)))


def downgrade():
    op.drop_column('user', 'permissions')
