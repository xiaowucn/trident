"""set visit_records user_id nullable

Revision ID: 269a9434e3db
Revises: b55a762cde91
Create Date: 2021-04-29 10:11:26.709491

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '269a9434e3db'
down_revision = 'b55a762cde91'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE visit_records ALTER COLUMN user_id DROP NOT NULL;
    """)


def downgrade():
    pass
