"""add nafmii role

Revision ID: 96c37c1ebfad
Revises: 526fc0f08ed5
Create Date: 2025-08-26 09:53:56.491173

"""
import os

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '96c37c1ebfad'
down_revision = '526fc0f08ed5'
branch_labels = None
depends_on = None
_ENV = os.environ.get("ENV")
NAFMII = _ENV == "nafmii"

def upgrade():
    if NAFMII:
        op.execute("""
            INSERT INTO roles (name, permission) VALUES 
            ('biz_role', '{"scriber": ["manage_task","remark","browse","manage_prj","manage_mold","manage_model","inspect"]}'::json), 
            ('ops_role', '{"scriber": ["remark","browse","manage_prj","manage_mold","manage_model","inspect","manage_all"]}'::json)
        """)


def downgrade():
    if NAFMII:
        op.execute("""
            DELETE FROM roles WHERE name in ('biz_role', 'ops_role');
        """)

