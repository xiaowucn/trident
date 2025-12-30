"""set role name as unique

Revision ID: f2fb44f0113b
Revises: 414e82ff243f
Create Date: 2019-09-17 10:27:03.242525

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2fb44f0113b'
down_revision = '414e82ff243f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('roles_idx_name', 'roles', ['name'], unique=True)


def downgrade():
    op.drop_index('roles_idx_name')
