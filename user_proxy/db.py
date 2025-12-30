# -*- coding: utf-8 -*-

import redis
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from user_proxy import config


KEY_PREFIX = config.get_config('webif.key_prefix') or ''


def render_key(key):
    if not KEY_PREFIX or key.startswith(KEY_PREFIX):
        return key
    return f'{KEY_PREFIX}{key}'


def get_db_session():
    host = config.get_config("webif.postgresql.host")
    if ',' not in host:
        dsn_url = URL(drivername='postgresql',
                      host=config.get_config("webif.postgresql.host"),
                      port=config.get_config("webif.postgresql.port"),
                      username=config.get_config("webif.postgresql.user"),
                      password=config.get_config("webif.postgresql.password"),
                      database=config.get_config("webif.postgresql.db_name"))
        engine = create_engine(dsn_url, echo=config.get_config("webif.sqlalchemy.echo", False), pool_pre_ping=True,
                               connect_args={"options": f"{config.get_config('webif.postgresql.options', '')}"})
        return sessionmaker(engine) ()

    query = {
        "host": config.get_config("webif.postgresql.host"),
        "port": config.get_config("webif.postgresql.port"),
        "target_session_attrs": "primary",
    }
    dsn_url = URL.create(
        drivername="postgresql",
        username=config.get_config("webif.postgresql.user"),
        password=config.get_config("webif.postgresql.password"),
        database=config.get_config("webif.postgresql.db_name"),
        query=query,
    )
    engine = create_engine(dsn_url, echo=config.get_config("webif.sqlalchemy.echo", False), pool_pre_ping=True,
        connect_args={"options": f"{config.get_config('webif.postgresql.options', '')}"})
    return sessionmaker(engine)()

db_session = get_db_session()

BaseModel = declarative_base()  # pylint: disable=invalid-name


def get_customer_session(prefix='customer_postgresql'):
    customer_dsn_url = URL(drivername='postgresql',
                           host=config.get_config(f"webif.{prefix}.host"),
                           port=config.get_config(f"webif.{prefix}.port"),
                           username=config.get_config(f"webif.{prefix}.user"),
                           password=config.get_config(f"webif.{prefix}.password"),
                           database=config.get_config(f"webif.{prefix}.db_name"))

    customer_engine = create_engine(customer_dsn_url, echo=config.get_config("webif.sqlalchemy.echo", False), pool_pre_ping=True)
    CustomerDBSession = sessionmaker(customer_engine)  # pylint: disable=invalid-name
    return CustomerDBSession()


def get_cache_redis() -> redis.Redis:
    host = config.get_config("webif.cache.host")
    passwd = config.get_config("webif.cache.password")
    port = config.get_config("webif.cache.port")
    db = config.get_config("webif.cache.db")
    rds = redis.Redis(host=host, password=passwd, port=port, db=db)
    return rds


cache_session = get_cache_redis()

if __name__ == '__main__':
    print(cache_session.get('trident:ht:auth:code:1323790000') == '125124214'.encode())
