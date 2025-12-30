"""add visit_records record_data column

Revision ID: c729a0e60e0f
Revises: 99abfb547e7c
Create Date: 2023-02-14 11:55:08.264505

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
from sqlalchemy.dialects.postgresql import JSONB

revision = 'c729a0e60e0f'
down_revision = '99abfb547e7c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('visit_records', sa.Column('record_data', JSONB))



def downgrade():
    op.drop_column('visit_records', 'record_data')
