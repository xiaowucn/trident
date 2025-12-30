"""update default role permission

Revision ID: e89951f9f794
Revises: b04b2f3e6247
Create Date: 2019-09-19 10:44:23.651966

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e89951f9f794'
down_revision = 'b04b2f3e6247'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE roles SET permission = '{"calliper": ["admin", "normal"], "autodoc": ["admin", "normal"], "autodoc_overall": ["admin", "normal"], "scriber": ["remark", "browse", "manage_mold", "manage_prj", "remark_management", "table_identification", "manage_user"], "pdflux": ["admin", "normal"]}'::jsonb WHERE name = '管理员'
    """)


def downgrade():
    pass
