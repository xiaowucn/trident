# -*- coding: utf-8 -*-
import json
import logging

from kafka import KafkaConsumer

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.models.user import User

from user_proxy.session import RedisDriver


def kafka_user_logout():
    # topic
    topic = config.get_config('kafka_config.topic')
    # 分区
    group_id = config.get_config('kafka_config.group_id')
    # 服务地址
    servers = config.get_config('kafka_config.servers', [])
    if isinstance(servers, str):
        servers = json.loads(servers)

    consumer = KafkaConsumer(topic, group_id=group_id, bootstrap_servers=servers)
    redis_driver = RedisDriver()
    for msg in consumer:
        logging.info("%s:%d:%d: key=%s value=%s", msg.topic, msg.partition, msg.offset, msg.key, msg.value)
        try:
            res = json.loads(msg.value.decode())
            user_id = res['authUserInfo']['userID']
        except Exception as e:
            logging.exception(e)
        else:
            user = db_session.query(User).filter(User.ext_uname == user_id).first()
            if user and user.session_id:
                redis_driver.client.delete(user.session_id)
                logging.info('session cleared, user_id: %s', user_id)
            else:
                logging.info('session clear failed, user_id: %s, session_id： %s', user_id, user.session_id)


if __name__ == '__main__':
    kafka_user_logout()
