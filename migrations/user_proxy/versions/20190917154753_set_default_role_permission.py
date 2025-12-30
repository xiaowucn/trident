"""set default role permission

Revision ID: 36edc89a04aa
Revises: f2fb44f0113b
Create Date: 2019-09-17 15:47:53.038615

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '36edc89a04aa'
down_revision = 'f2fb44f0113b'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE roles SET permission = '{"calliper": ["admin"], "autodoc": ["admin"], "autodoc_overall": ["admin"], "scriber": ["remark", "browse", "manage_mold", "manage_prj", "remark_management", "table_identification"], "pdflux": ["admin"]}'::jsonb WHERE name = '管理员'
    """)


def downgrade():
    pass
