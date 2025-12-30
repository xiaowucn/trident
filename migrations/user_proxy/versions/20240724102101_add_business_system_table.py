"""add business_system table

Revision ID: 82489bef1b73
Revises: 38a3355421b1
Create Date: 2024-07-24 10:21:01.381573

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '82489bef1b73'
down_revision = '38a3355421b1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
    'business_system',
    sa.Column('id', sa.BigInteger, primary_key=True),
    sa.Column('name', sa.String),
)


def downgrade():
    op.drop_table('business_system')
