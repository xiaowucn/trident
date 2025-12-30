"""update ht admin permissions

Revision ID: 526fc0f08ed5
Revises: c73817fa30ae
Create Date: 2025-06-11 10:14:16.651156

"""
import os

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '526fc0f08ed5'
down_revision = 'c73817fa30ae'
branch_labels = None
depends_on = None
_ENV = os.environ.get("ENV")
HT = _ENV == "ht"

def upgrade():
    if HT:
        op.execute(
            """
                update "user" set permissions = '{p_manage}' where is_admin is true;
            """
        )


def downgrade():
    pass
