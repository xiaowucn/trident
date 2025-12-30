"""create user

Revision ID: 7941d33c266c
Revises: 
Create Date: 2019-07-16 14:41:10.860033

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
from sqlalchemy.dialects.postgresql import JSONB

revision = '7941d33c266c'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_data', JSONB),
        sa.Column('ext_uname', sa.String, nullable=False),
        sa.Column('password', sa.String),
        sa.Column('password_salt', sa.String),
        sa.Column('deleted', sa.Integer, server_default=sa.text('0')),
        sa.Column('created_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
        sa.Column('updated_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
    )
    op.create_index('ext_uname_unique', 'user', ['ext_uname'], unique=True)


def downgrade():
    op.drop_table('user')
