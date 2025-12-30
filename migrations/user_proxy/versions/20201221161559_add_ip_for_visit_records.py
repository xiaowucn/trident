"""add visit_records

Revision ID: b55a762cde91
Revises: e89951f9f794
Create Date: 2020-12-21 16:15:59.091055

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b55a762cde91'
down_revision = '0c7cd66c0762'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('visit_records', sa.Column('api', sa.String))
    op.add_column('visit_records', sa.Column('ip_address', sa.String))


def downgrade():
    op.drop_column('visit_records', 'api')
    op.drop_column('visit_records', 'ip_address')
