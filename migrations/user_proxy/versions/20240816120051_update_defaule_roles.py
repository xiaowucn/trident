"""update defaule roles

Revision ID: d0048442b1fd
Revises: 82489bef1b73
Create Date: 2024-08-16 12:00:51.017777

"""
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd0048442b1fd'
down_revision = '82489bef1b73'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    for row in conn.execute('select id, permission, name from roles where name in (\'默认角色\', \'管理员\')'):
        row_id = row[0]
        permission = row[1]
        name = row[2]
        new_perm = {"imitator": ["normal"], "glazer_imitator": ["imitator_normal"]}
        if name == '管理员':
            new_perm = {"imitator": ["admin"], "glazer_imitator": ["imitator_admin"]}

        if not permission:
            permission = {}
        permission.update(new_perm)
        conn.execute('update roles set permission=%s::jsonb where id=%s', (json.dumps(permission), row_id))



def downgrade():
    pass
