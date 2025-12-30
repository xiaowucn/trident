# -*-coding:utf-8-*-
import hashlib
import json
import logging
import time

import requests
from kafka import KafkaProducer
from sqlalchemy import or_

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url
from user_proxy.worker.app import app


@app.task
def send_dashboard_data():
    servers = config.get_config('kafka.servers')
    kafka_topic = config.get_config('kafka.topic')
    producer = KafkaProducer(
        bootstrap_servers=servers,
        key_serializer=lambda k: json.dumps(k, ensure_ascii=False).encode(),
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode(),
    )
    sub_system_map = config.get_config('kafka.sub_system')
    dashboard_target_map = config.get_config('kafka.dashboard_target')
    for sub_system, sub_system_cn_name in sub_system_map.items():
        auth_config = config.get_config('unify_auth.auth_config.auth_{}'.format(sub_system))
        if not auth_config:
            logging.error('sys: %s not config', sub_system)
            continue
        dashboard_url = auth_config['dashboard_url']
        logging.info('get cicc %s system dashboard data url: %s', sub_system, dashboard_url)
        response = requests.get(dashboard_url)
        if response.status_code != 200:
            logging.error('get cicc %s system dashboard data failed, status_code: %s', sub_system, response.status_code)
            continue
        dashboard_data = response.json()
        logging.info('get cicc %s system dashboard data: %s', sub_system, dashboard_data)
        for target, value in dashboard_data['data'].items():
            if target not in dashboard_target_map:
                logging.error('cicc %s system dashboard %s data not in config dashboard_target map: %s', sub_system, target, dashboard_target_map)
                continue
            item_data = {
                "ciCode": config.get_config('kafka.ciCode'),
                "metric": f"{sub_system_cn_name}_{dashboard_target_map[target]}",
                "instance": "_",
                "value": value,
                "timestamp": str(int(round(time.time() * 1000))),
                "sourceID": "投行智能审核系统",
                "type": "business_operation",
            }
            logging.info('send dashboard data to customer: %s', item_data)
            producer.send(kafka_topic, item_data)
    producer.close()


def generate_user_info_sign(product_name, data=None):
    sign_list = ['prod', product_name]
    if data:
        data = json.dumps(data, sort_keys=True).replace('\n', '\r\n')
        sign_list.append(data)
    sign_list.append(config.get_config('sync_user.token'))
    auth_str = ''.join(sign_list)
    logging.info('auth str: %s', auth_str)
    sign = hashlib.md5(auth_str.encode()).hexdigest()
    logging.info('auth sign: %s', sign)
    return sign


def get_page_user_data(page, size=3000):
    """中金只做更新，不做新增和删除操作"""
    user_info_server = config.get_config('sync_user.user_info_server')
    user_info_uri = config.get_config('sync_user.user_info_uri')
    product_name = config.get_config('sync_user.product_name')
    body = {"pageIndex": page, "pageSize": size}
    sign = generate_user_info_sign(product_name, body)
    get_users_url = create_url(user_info_server, user_info_uri, ("prod", product_name), ("sign", sign))
    logging.info('get users data url: %s', get_users_url)
    response = requests.post(get_users_url, json=body)
    assert response.status_code == 200, response.status_code
    res = response.json()
    user_names = set()
    # {"empNumber":"10184","empName":"王曙光","department":"IB","buName":"CCM","email":"wangsg@cicc.com.cn"}
    logging.info('get user info: total: %s, current_page: %s', res['total'], res['currentPage'])
    for item in res['items']:
        # user_data emp_number from manual import
        user = db_session.query(User).filter(or_(User.ext_uname == item['empNumber'], User.user_data.op('->>')('emp_number') == item['empNumber'])).first()
        # IB user emp_number length 5 bits
        if user:
            User.make_user(user.ext_uname, user.ext_uname, username=item['empName'], department=item['department'], bu_name=item['buName'], email=item['email'])
            user_names.add(item['empNumber'])
            logging.info('update user ext_uname=%s, username=%s, bu_name=%s', item['empNumber'], item['empName'], item['buName'])
        # IBS user emp_number length 7 bits
        ibs_ext_uname = f"10{item['empNumber']}"
        orig_user = db_session.query(User).filter(User.ext_uname == ibs_ext_uname).first()
        if orig_user:
            User.make_user(ibs_ext_uname, ibs_ext_uname, username=item['empName'], bu_name=item['buName'])
            user_names.add(ibs_ext_uname)
            logging.info('update user orig_ext_uname=%s, bu_name=%s', ibs_ext_uname, item['buName'])

    return res['total'] - page * size, user_names


@app.task
def sync_user_info():
    # db_users = db_session.query(User).filter(User.deleted == 0).all()
    # sync_user_names = set()
    page = 1
    remain_count, user_names = get_page_user_data(page)
    # sync_user_names = sync_user_names.union(user_names)
    while remain_count > 0:
        page += 1
        remain_count, user_names = get_page_user_data(page)
        # sync_user_names = sync_user_names.union(user_names)

    # for db_user in db_users:
    #     if db_user.oa_user and db_user.ext_uname not in sync_user_names:
    #         logging.info('delete not exist in sync user: ext_uname=%s', db_user.ext_uname)
    #         db_user.deleted = 1
    db_session.commit()


if __name__ == '__main__':
    # send_dashboard_data()
    sync_user_info()
