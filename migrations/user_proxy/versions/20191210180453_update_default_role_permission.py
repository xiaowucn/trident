"""update default role permission

Revision ID: 9f685d2f4d63
Revises: e89951f9f794
Create Date: 2019-12-10 18:04:53.460100

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f685d2f4d63'
down_revision = 'e89951f9f794'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE roles SET permission = '{"grater": ["admin", "normal"], "calliper": ["admin", "normal"], "autodoc": ["admin", "normal"], "autodoc_overall": ["admin", "normal"], "scriber": ["remark", "browse", "manage_mold", "manage_prj", "remark_management", "table_identification", "manage_user"], "pdflux": ["admin", "normal"], "scriber_kv": ["normal"]}'::jsonb WHERE name = '管理员'
    """)


def downgrade():
    pass
