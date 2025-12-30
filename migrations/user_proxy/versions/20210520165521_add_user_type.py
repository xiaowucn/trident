"""

Revision ID: 8e51714e1f6d
Revises: a846f4a97770
Create Date: 2021-05-20 16:55:21.456179

"""
import os

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8e51714e1f6d'
down_revision = 'a846f4a97770'
branch_labels = None
depends_on = None

_ENV = os.environ.get("ENV")
HT = _ENV == "ht"


def oa_user(user_data):
    if user_data.get('_from') == 'cas':
        return True
    if '_from' not in user_data and user_data.get('ext_sys') != 'self':
        return True
    if user_data.get('_from') and user_data['_from'] != 'self':
        return True
    return False


def non_oa_user_ids(users):
    user_ids = set()
    for user in users:
        if not oa_user(user.user_data):
            user_ids.add(user.id)

    return user_ids


def upgrade():
    op.add_column('user', sa.Column('is_oa', sa.Boolean, server_default=sa.text('true')))
    op.add_column('user', sa.Column('is_admin', sa.Boolean, server_default=sa.text('false')))
    users = op.get_bind().execute('select * from "user";')
    non_oa_ids = non_oa_user_ids(users)
    if non_oa_ids:
        if len(non_oa_ids) == 1:
            op.get_bind().execute(f'update "user" set is_oa = False where id  = {tuple(non_oa_ids)[0]}')
        else:
            op.get_bind().execute(f'update "user" set is_oa = False where id in {tuple(non_oa_ids)}')

    if HT:
        op.drop_index('ext_uname_unique')
        op.create_index('ux_ext_uname_is_oa', 'user', ['ext_uname', 'is_oa'], unique=True, postgresql_where=sa.text("deleted = 0"))
        op.create_index('ix_user_is_oa_admin', 'user', ['is_oa', 'is_admin'])


def downgrade():
    op.drop_column('user', "is_oa")
    op.drop_column('user', "is_admin")
    if HT:
        op.drop_index('ux_ext_uname_is_oa')
        op.drop_index('ix_user_is_oa_admin')
        op.create_index('ext_uname_unique', 'user', ['ext_uname'], unique=True)
