# -*-coding:utf-8-*-
import logging
import time
import uuid
from urllib.parse import urljoin

import jwt
import requests
from utensils.util import generate_timestamp

from user_proxy import config
from user_proxy.db import db_session, render_key
from user_proxy.models.user import User
from user_proxy.session import RedisDriver
from user_proxy.worker.app import app

USER_SYNC_SERVER = config.get_config('sync_user_info.server')
USER_SYNC_API = config.get_config('sync_user_info.sync_url')
CMFCHINA_LOCK_KEY = 'cmfchina_sync_user_info'


def generate_authorization():
    app_id = config.get_config('sync_user_info.app_id')
    app_secret = config.get_config('sync_user_info.app_secret')
    token = jwt.encode(
        {"iss": app_id, "iat": int(time.time()), "jti": str(uuid.uuid4())}, app_secret, algorithm="HS256"  # issuer  # issued at  # JWT ID  # 密钥  # 使用HMAC256算法
    )
    return "Bearer " + token


def get_page_user_data(page, size=100):
    get_users_url = urljoin(USER_SYNC_SERVER, USER_SYNC_API)
    headers = {'Content-Type': 'application/json', 'Authorization': generate_authorization()}
    json_data = {"size": str(size), "page": str(page)}
    logging.info('get users url: %s', get_users_url)
    logging.info('get users headers: %s', headers)
    logging.info('get users json_data: %s', json_data)
    response = requests.post(get_users_url, json=json_data, headers=headers)
    res_data = response.json()
    if str(res_data['code']) != '0':
        logging.error('get users response code: %s, msg: %s', res_data['code'], res_data['msg'])

    user_names = set()
    for item in res_data['data']['list']:
        logging.info('page: %s, user data : %s', page, item)
        User.make_user(
            item['app_account__account_no'],
            item['app_account__account_no'],
            department_id=item['orgs'][0]['idt_org__id'],
            department=item['orgs'][0]['idt_org__name'],
            username=item['idt_user__user_name'],
            email=item['idt_user__email'],
            _from='cas',
        )
        user_names.add(item['app_account__account_no'])
        logging.info('add user ext_uname=%s, username=%s', item['app_account__account_no'], item['idt_user__user_name'])
    return res_data['data']['total'] - page * size, user_names


@app.task
def sync_user():
    if not USER_SYNC_SERVER or not USER_SYNC_API:
        return
    redis_driver = RedisDriver()
    if not redis_driver.client.set(render_key(CMFCHINA_LOCK_KEY), generate_timestamp(), 3600, nx=True):
        return
    db_users = db_session.query(User).filter(User.deleted == 0).all()
    sync_user_names = set()
    page = 1
    remain_count, user_names = get_page_user_data(page)
    sync_user_names = sync_user_names.union(user_names)
    while remain_count > 0:
        page += 1
        remain_count, user_names = get_page_user_data(page)
        sync_user_names = sync_user_names.union(user_names)

    for db_user in db_users:
        if db_user.oa_user and db_user.ext_uname not in sync_user_names:
            logging.info('delete not exist in sync user: ext_uname=%s', db_user.ext_uname)
            db_user.deleted = 1
    db_session.commit()
    redis_driver.client.delete(render_key(CMFCHINA_LOCK_KEY))


if __name__ == '__main__':
    sync_user()
