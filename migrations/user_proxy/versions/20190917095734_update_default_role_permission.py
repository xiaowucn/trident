"""update default role permission

Revision ID: 414e82ff243f
Revises: 7084d8c011bd
Create Date: 2019-09-17 09:57:34.646238

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '414e82ff243f'
down_revision = '7084d8c011bd'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE roles SET permission = '{"calliper": ["normal"], "autodoc": ["normal"], "autodoc_overall": ["normal"], "scriber": ["remark", "browse"], "pdflux": ["normal"], "scriber_kv":["normal"], "grater": ["normal"]}'::jsonb WHERE name = '默认角色'
    """)
    op.execute("""
        INSERT INTO roles (name, permission) VALUES ('管理员', '{"calliper": ["admin"], "autodoc": ["admin"], "autodoc_overall": ["admin"], "scriber": ["remark", "browse", "manage_mold", "manage_prj", "manage_user", "remark_management", "table_identification"], "pdflux": ["admin"]}'::jsonb)
    """)


def downgrade():
    pass

