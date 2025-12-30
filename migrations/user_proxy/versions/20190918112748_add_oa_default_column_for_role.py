"""add oa_default column for role

Revision ID: c8b2419d5620
Revises: 36edc89a04aa
Create Date: 2019-09-18 11:27:48.259137

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8b2419d5620'
down_revision = '36edc89a04aa'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('roles', sa.Column('oa_default', sa.Boolean, server_default=sa.text('false')))
    op.execute("""
        UPDATE roles SET oa_default = 'true' WHERE name = '默认角色'
    """)


def downgrade():
    op.drop_column('roles', 'oa_default')
