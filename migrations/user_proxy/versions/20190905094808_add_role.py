"""add role

Revision ID: d3de0ea79ab1
Revises: 37bbd28f39aa
Create Date: 2019-09-05 09:48:08.375367

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
from sqlalchemy.dialects.postgresql import JSONB

revision = 'd3de0ea79ab1'
down_revision = '37bbd28f39aa'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'roles',
        sa.Column('id', sa.BigInteger, primary_key=True),
        sa.Column('name', sa.String),
        sa.Column('permission', JSONB),
        sa.Column('created_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
        sa.Column('updated_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
    )
    op.create_table(
        'user_role_mapping',
        sa.Column('user_id', sa.BigInteger, nullable=False),
        sa.Column('role_id', sa.BigInteger, nullable=False),
    )

    op.execute("""
        INSERT INTO roles (name, permission) VALUES ('默认角色', '{"autodoc": ["normal"], "scriber": ["remark", "browse"], "pdflux": ["normal"]}'::jsonb)
    """)


def downgrade():
    op.drop_table('roles')
    op.drop_table('user_role_mapping')
