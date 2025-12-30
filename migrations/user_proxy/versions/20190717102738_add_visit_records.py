"""add visit_records

Revision ID: a846f4a97770
Revises: 7941d33c266c
Create Date: 2019-12-05 10:27:38.592138

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a846f4a97770'
down_revision = '7941d33c266c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'visit_records',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('visit_sys', sa.String, nullable=False, index=True),
        sa.Column('user_id', sa.Integer, nullable=False),
        sa.Column('deleted', sa.Integer, server_default=sa.text('0')),
        sa.Column('created_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
        sa.Column('updated_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
    )


def downgrade():
    op.drop_table('visit_records')
