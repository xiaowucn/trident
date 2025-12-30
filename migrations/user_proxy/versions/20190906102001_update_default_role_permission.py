"""update default role permission

Revision ID: 7084d8c011bd
Revises: cea95de932ec
Create Date: 2019-09-06 10:20:01.971867

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7084d8c011bd'
down_revision = 'd3de0ea79ab1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE roles SET permission = '{"autodoc": ["normal"], "autodoc_overall": ["normal"], "scriber": ["remark", "browse"], "pdflux": ["normal"]}'::jsonb WHERE name = '默认角色'
    """)


def downgrade():
    pass
