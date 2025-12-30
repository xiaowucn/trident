"""add ldap user record table

Revision ID: 6f52a42b0ecf
Revises: 73230b6df394
Create Date: 2021-09-03 12:54:06.610751

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6f52a42b0ecf'
down_revision = '73230b6df394'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ldap_user_record',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, unique=True),
        sa.Column('department_id', sa.String),
        sa.Column('department', sa.String),
        sa.Column('created_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
        sa.Column('updated_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
    )


def downgrade():
    op.drop_table('ldap_user_record')
