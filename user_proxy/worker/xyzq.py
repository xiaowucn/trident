# -*-coding:utf-8-*-
import datetime
import hashlib
import json
import logging

import requests
from utensils.util import generate_timestamp

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.models.user import User
from user_proxy.worker.app import app

USER_SYNC_URL = config.get_config('xyzq_sync.sync_url')
DEPT_SYNC_URL = config.get_config('xyzq_sync.dept_url')


def get_page_group_data(org_id, page, size=100, update_time='1970-01-01 00:00:00'):
    headers = get_sync_headers()
    data = {"SysID": config.get_config('xyzq_sync.sys_id'), "DataUpdTm": update_time, "OrgId": org_id, "Page": page, "Size": size}
    response = requests.post(DEPT_SYNC_URL, json=data, headers=headers, verify=False)
    if response.status_code != 200:
        logging.error('get dept info error, status_code: %s', response.status_code)
        return -1, []
    json_body = response.json()
    logging.debug('response body: %s', json_body)
    response_data = json.loads(json_body['ResponseData'])
    if not response_data['resphead']['success']:
        logging.error('get dept info failed: %s', response_data['resphead']['msg'])
        return -1, []

    total = int(response_data['respbody']['data']['total'])
    page_dept_ids = [item['org_id'] for item in response_data['respbody']['data']['list'] if item['rec_stat_cd'] == 'A' and item['data_upd_stat_cd'] != '3']
    return total - page * size, page_dept_ids


def get_dept_data(sync_dept_id):
    dept_ids = []
    page = 1
    remain_count, page_dept_ids = get_page_group_data(sync_dept_id, page)
    dept_ids.extend(page_dept_ids)
    while remain_count > 0:
        page += 1
        remain_count, page_dept_ids = get_page_group_data(sync_dept_id, page)
        dept_ids.extend(page_dept_ids)
    return dept_ids


def get_total_dept_data():
    dept_ids = []
    if not DEPT_SYNC_URL:
        return dept_ids
    need_sync_dept_ids = config.get_config('xyzq_sync.sync_dept_ids') or []
    for sync_dept_id in need_sync_dept_ids:
        sync_dept_ids = get_dept_data(sync_dept_id)
        logging.info('primary department: %s, sync_dept_ids: %s', sync_dept_id, sync_dept_ids)
        dept_ids.extend(sync_dept_ids)
    return dept_ids


def get_sync_headers():
    app_id = config.get_config('xyzq_sync.username')
    app_secret = config.get_config('xyzq_sync.password')
    timestamp = str(generate_timestamp() * 1000)
    sign = hashlib.md5(f"{app_id}:{app_secret}:{timestamp}".encode()).hexdigest()
    headers = {"appId": app_id, "timestamp": timestamp, "sign": sign}
    return headers


def get_page_user_data(page, update_time, dept_ids, size=100):
    headers = get_sync_headers()
    data = {"SysID": config.get_config('xyzq_sync.sys_id'), "DataUpdTm": update_time, "OrgID": '0', "Page": page, "Size": size}
    if page == 1:
        logging.info('get users data url: %s', USER_SYNC_URL)
        logging.info('get users data headers: %s', headers)
        logging.info('get users data data: %s', data)

    response = requests.post(USER_SYNC_URL, json=data, headers=headers, verify=False)
    if response.status_code != 200:
        logging.error('get user_info error, status_code: %s', response.status_code)
        return -1
    json_body = response.json()
    logging.debug('response body: %s', json_body)
    response_data = json.loads(json_body['ResponseData'])
    if not response_data['resphead']['success']:
        logging.error('get user_info failed: %s', response_data['resphead']['msg'])
        return -1

    total = int(response_data['respbody']['data']['total'])
    if page == 1:
        logging.info('total user count: %s', total)

    for item in response_data['respbody']['data']['list']:
        ext_uname = item['emp_id']
        if not ext_uname:
            logging.error('page: %s, not ext_uname user data : %s', page, item)
            continue
        if item['emp_sub_type_cd'] not in ['101', '102']:
            logging.error('user is not valid sync type: emp_id: %s, emp_sub_type_cd: %s', item['emp_id'], item['emp_sub_type_cd'])
            continue

        logging.debug('page: %s, user data : %s', page, item)
        status = item.get('emp_logn_acct_stat_cd') or ''
        user = User.make_user(ext_uname, ext_uname, username=item['emp_name'], status=status, _from='xyzq', department_id=item['org_id'])
        if user:
            if status != User.XYZQ_STATUS_VALIDATION:
                logging.info('delete user ext_uname=%s, status=%s', ext_uname, status)
                user.deleted = 1
            elif item['org_id'] not in dept_ids:
                logging.info('delete invalid dept user ext_uname=%s, org_id=%s', ext_uname, item['org_id'])
                user.deleted = 1
            else:
                logging.info('add user ext_uname=%s, username=%s', ext_uname, item['emp_name'])
    db_session.commit()
    return total - page * size


def increment_sync_user(update_time):
    dept_ids = get_total_dept_data()
    logging.info('dept_ids: %s', dept_ids)
    if not dept_ids:
        return
    page = 1
    remain_count = get_page_user_data(page, update_time, dept_ids)
    while remain_count > 0:
        page += 1
        remain_count = get_page_user_data(page, update_time, dept_ids)


@app.task
def sync_user():
    if not USER_SYNC_URL:
        return

    increment_sync_user((datetime.date.today() - datetime.timedelta(2)).strftime('%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    increment_sync_user('1970-01-01 00:00:00')
