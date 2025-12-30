"""merge branch

Revision ID: 0c7cd66c0762
Revises: c8bd7dcd87f0, db8079fd5883, b8ae804d209f, 9f685d2f4d63, a846f4a97770
Create Date: 2020-10-12 15:36:34.267073

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0c7cd66c0762'
down_revision = ('c8bd7dcd87f0', 'db8079fd5883', 'b8ae804d209f', '9f685d2f4d63')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
