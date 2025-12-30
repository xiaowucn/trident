"""add customer_sys_config table

Revision ID: 776293d0ef84
Revises: d0048442b1fd
Create Date: 2024-08-21 12:20:23.236498

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '776293d0ef84'
down_revision = 'd0048442b1fd'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'customer_sys_config',
        sa.Column('id', sa.BigInteger, primary_key=True),
        sa.Column('sync_user', sa.Boolean),
        sa.Column('disable_former_employee', sa.Boolean),
        sa.Column('meta', JSONB),
    )
    op.execute(
        """
            insert into customer_sys_config (sync_user, disable_former_employee) values (false, false);
        """
    )


def downgrade():
    op.drop_table('customer_sys_config')

