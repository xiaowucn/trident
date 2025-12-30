"""

Revision ID: 39c8e20f51ef
Revises: 8e51714e1f6d
Create Date: 2021-06-18 10:37:00.113340

"""
import os

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '39c8e20f51ef'
down_revision = '8e51714e1f6d'
branch_labels = None
depends_on = None

_ENV = os.environ.get("ENV")
HT = _ENV == "ht"


def upgrade():
    if HT:
        op.execute("""UPDATE "user" SET is_admin = true, is_oa = false WHERE id in (
        select id from "user" where id < 5 and ext_uname = 'admin' order by id asc limit 1);""")


def downgrade():
    pass
