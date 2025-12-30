# -*-coding:utf-8-*-
# pylint:disable=redefined-outer-name
import os
import urllib.parse

import pexpect
import psycopg2
from invoke import task, run

from user_proxy import config
from user_proxy.db import db_session


def run_db_script(script):
    host = config.get_config("webif.postgresql.host")
    port = config.get_config("webif.postgresql.port")
    username = config.get_config("webif.postgresql.user")
    # password = config.get_config("webif.postgresql.password")
    database = config.get_config("webif.postgresql.db_name")
    run("{} {} {} {} {}".format(script, username, database, port, host))


@task
def revision(ctx, msg):
    cmd = 'alembic -c migrations/alembic.ini revision -m "{}"'
    run(cmd.format(msg))


def _alembic_db_task(ctx, command):
    host = config.get_config("webif.postgresql.host")
    port = config.get_config("webif.postgresql.port")
    username = config.get_config("webif.postgresql.user")
    password = config.get_config("webif.postgresql.password")
    database = config.get_config("webif.postgresql.db_name")
    if password and config.get_config('webif.postgresql.quote_password', False):
        password = urllib.parse.quote(password)

    if "," in host:
        conn = psycopg2.connect(
            dbname=database,
            user=username,
            password=password,
            host=host,
            port=port,
            target_session_attrs="primary",
            connect_timeout=5,
        )
        host = conn.info.host
        port = conn.info.port
        print(f"primary pg {host=} {port=}")
        conn.close()

    db_url = 'postgresql+psycopg2://{}:{}@{}:{}/{}'.format(username, password, host, port, database)
    cmd = 'PYTHONPATH={}:$PYTHONPATH alembic -c migrations/alembic.ini -x dburl={} {}'
    run(cmd.format(ctx['project_root'], db_url, command))


@task
def upgrade(ctx):
    _alembic_db_task(ctx, "upgrade head")


@task
def downgrade(ctx, revision):
    _alembic_db_task(ctx, "downgrade {}".format(revision))


@task
def reset(ctx):
    _alembic_db_task(ctx, "downgrade base")


@task
def version(ctx):
    _alembic_db_task(ctx, "current")


@task
def heads(ctx):
    _alembic_db_task(ctx, "heads")


@task
def history(ctx):
    _alembic_db_task(ctx, "history")


@task
def merge_heads(ctx):
    _alembic_db_task(ctx, "merge heads")


@task
def cmd(ctx, cmd):
    _alembic_db_task(ctx, cmd)

def tty_size():
    size = os.get_terminal_size()
    return size.lines, size.columns

@task
def shell(ctx, db_type="postgresql"):
    """Connect to postgresql db"""
    db_conf = config.get_config(f"webif.{db_type}")
    if not db_conf:
        run(f"echo 'Not found {db_type=} config'")
        exit(1)
    cmd = f"psql -U {db_conf.get('user')} -h {db_conf.get('host')} -p {db_conf.get('port')} -d {db_conf.get('db_name')}"
    process = pexpect.spawn(cmd)
    if passwd := db_conf.get("password"):
        try:
            process.expect("Password", timeout=1)
            process.sendline(passwd)
        except pexpect.exceptions.TIMEOUT:
            pass
    if schema := config.get_pg_schema():
        process.sendline(f"SET search_path TO {schema};")
    process.setwinsize(*tty_size())
    process.interact()

@task
def sql(ctx):
    import readline  # noqa

    while True:
        try:
            _sql = input("SQL > ").strip()
        except KeyboardInterrupt:
            print("\r")
            continue
        except EOFError:
            print("\n退出")
            break

        if _sql.lower() in ("exit", "quit", "\\q"):
            print("再见")
            break
        try:
            result = db_session.execute(_sql)
            if not result:
                print("Empty result")
                continue
            for row in result:
                print(row)
        except Exception as e:
            print(f"❌ 执行出错: {e}")
