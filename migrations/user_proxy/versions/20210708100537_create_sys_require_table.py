"""create sys require table

Revision ID: bb9cb05ca84c
Revises: 269a9434e3db
Create Date: 2021-07-08 10:05:37.714300

"""
from alembic import op
import sqlalchemy as sa

from user_proxy.utils.extension_manager import ExtensionManager

# revision identifiers, used by Alembic.
revision = 'bb9cb05ca84c'
down_revision = '269a9434e3db'
branch_labels = None
depends_on = None


table_name = 'sys_require'


def upgrade():
    op.create_table(
        table_name,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, nullable=False),
        sa.Column('sys', sa.String, nullable=False),
        sa.Column('status', sa.SmallInteger),
        sa.Column('reason', sa.Text),
        sa.Column('created_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
        sa.Column('updated_utc', sa.Integer, server_default=sa.text('extract(epoch from now())::int')),
        sa.Column('start_utc', sa.Integer),
        sa.Column('end_utc', sa.Integer),
    )

    if ExtensionManager.is_active_extension('btree_gin'):
        op.execute('CREATE EXTENSION IF NOT EXISTS btree_gin;')
        op.execute(
            f"""
            CREATE INDEX {table_name}_gin_idx
                ON {table_name}
                USING gin (user_id, sys, status, end_utc);
            """
        )
    else:
        op.execute(
            f"""
                    CREATE INDEX {table_name}_idx
                        ON {table_name}
                        USING btree (user_id, sys, status, end_utc);
                    """
        )


def downgrade():
    op.drop_table(table_name)
