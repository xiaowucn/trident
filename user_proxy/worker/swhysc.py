# -*-coding:utf-8-*-

import logging

import requests
from utensils.util import generate_timestamp

from user_proxy import config
from user_proxy.db import db_session, render_key
from user_proxy.models.user import User, Department
from user_proxy.session import RedisDriver
from user_proxy.utils.cas import create_url
from user_proxy.utils.swhysc import generate_request_date, generate_signature
from user_proxy.worker.app import app

USER_SYNC_SERVER = config.get_config('swhysc_auth.sync_server')
USER_SYNC_API = config.get_config('swhysc_auth.sync_api')

SYNC_DEPT_SERVER = config.get_config('swhysc_auth.sync_dept_server')
SYNC_DEPT_API = config.get_config('swhysc_auth.sync_dept_api')

SWHYSC_LOCK_KEY = 'swhysc_sync_user_info'


def build_headers(api, page, size):
    demeter_request_date = generate_request_date()
    # 客户文档中要求query参数进行排序、字符转换(RFC3986规则编码),此接口参数较简单且固定,省略这一步处理
    sign_str = '\n'.join(["HmacSHA256", "GET", api, f"pageNum={page}&pageSize={size}", demeter_request_date])
    logging.debug('sign_str: %s', sign_str)
    demeter_signature = generate_signature(sign_str)
    headers = {
        "accept": "*/*",
        'Content-Type': 'text/plain',
        'X-DemeterRequestDate': demeter_request_date,
        'X-DemeterSignature': demeter_signature,
        'X-DemeterAccessKey': config.get_config('swhysc_auth.demeter_access_key'),
        'X-Demeter-SystemId': str(config.get_config('swhysc_auth.demeter_system_id')),
        'X-Demeter-Source': str(config.get_config('swhysc_auth.demeter_source')),
        'X-Demeter-IP': config.get_config('swhysc_auth.demeter_ip'),
    }
    return headers


def get_page_user_data(page, size=100, department_map=None):
    get_users_url = create_url(USER_SYNC_SERVER, USER_SYNC_API, ("pageNum", page), ("pageSize", size))
    logging.info('get users data url: %s', get_users_url)
    headers = build_headers(USER_SYNC_API, page, size)
    response = requests.get(get_users_url, headers=headers, verify=False)
    if response.status_code != 200:
        logging.error('get user_info error, status_code: %s', response.status_code)
        return -1, []
    data = response.json()
    if data.get('code') != '0':
        logging.error('get user_info failed: %s', data['msg'])
        return -1, []
    if page == 1:
        logging.info('total user count: %s', data['data']['totalCount'])

    user_names = set()
    # 姓名 账号 状态 部门ID 所属部门
    # name staffId userStatus userOrgId userOrgName
    for item in data['data']['list']:
        ext_uname = item['staffId']
        if not ext_uname:
            logging.error('page: %s, not ext_uname user data : %s', page, item)
            continue
        logging.debug('page: %s, user data : %s', page, item)
        origin_department_id = department_id = item.get('userOrgId')
        if department_map and department_id and department_map.get(department_id):
            origin_department_id = department_id  # 用户实际部门id
            department_id = department_map[department_id]  # 替换为一级部门id

        User.make_user(
            ext_uname,
            ext_uname,
            username=item['name'],
            department_id=department_id,
            origin_department_id=origin_department_id,
            department=item.get('userOrgName'),
            status=item.get('userStatus'),
            _from='swhysc',
        )
        user_names.add(ext_uname)
        logging.info('add user ext_uname=%s, username=%s', ext_uname, item['name'])

    return data['data']['totalCount'] - page * size, user_names


def get_page_dept_data(page, size=100):
    get_departments_url = create_url(SYNC_DEPT_SERVER, SYNC_DEPT_API, ("pageNum", page), ("pageSize", size))
    logging.info('get departments data url: %s', get_departments_url)
    headers = build_headers(SYNC_DEPT_API, page, size)
    response = requests.get(get_departments_url, headers=headers, verify=False)
    if response.status_code != 200:
        logging.error('get dept_info error, status_code: %s', response.status_code)
        return -1, []
    data = response.json()
    if data.get('code') != '0':
        logging.error('get dept_info failed: %s', data['msg'])
        return -1, []
    if page == 1:
        logging.info('total departments count: %s', data['data']['totalCount'])

    return data['data']['totalCount'] - page * size, data['data']['list']


def sync_department():
    sync_departments = []
    page = 1
    remain_count, page_departments = get_page_dept_data(page)
    sync_departments.extend(page_departments)
    while remain_count > 0:
        page += 1
        remain_count, page_departments = get_page_dept_data(page)
        sync_departments.extend(page_departments)

    db_department_map = dict(db_session.query(Department.external_id, Department).all())
    for sync_dept_data in sync_departments:
        external_id, name, parent_id = sync_dept_data['orgCode'], sync_dept_data['orgName'], sync_dept_data['supOrgCode']
        dept = db_department_map.pop(external_id, Department(external_id=external_id))
        dept.name = name
        dept.parent_id = parent_id
        dept.deleted = 0
        db_session.add(dept)

    for external_id, dept in db_department_map.items():
        logging.info('delete not exist in sync depts: orgCode=%s, orgName=%s', external_id, dept.name)
        dept.deleted = 1
    db_session.commit()


def build_target_department_map():
    dept_map = {}
    target_dept_ids = config.get_config('swhysc_auth.target_dept_ids') or []
    for first_level_dept_id in target_dept_ids:
        children_departments = Department.find_departments_by_external_id(first_level_dept_id, find_parent=False)
        for child_dept in children_departments:
            dept_map[child_dept.external_id] = first_level_dept_id
    return dept_map


@app.task
def sync_user():
    if not USER_SYNC_SERVER or not USER_SYNC_API:
        return
    redis_driver = RedisDriver()
    if not redis_driver.client.set(render_key(SWHYSC_LOCK_KEY), generate_timestamp(), 3600, nx=True):
        return
    department_map = {}
    if config.get_config('swhysc_auth.sync_dept_enable', False):
        sync_department()
        department_map = build_target_department_map()
    # db_users = db_session.query(User).filter(User.deleted == 0).all()
    # sync_user_names = set()
    page = 1
    remain_count, user_names = get_page_user_data(page, department_map=department_map)
    # sync_user_names = sync_user_names.union(user_names)
    while remain_count > 0:
        page += 1
        remain_count, user_names = get_page_user_data(page, department_map=department_map)
        # sync_user_names = sync_user_names.union(user_names)

    # for db_user in db_users:
    #     if db_user.oa_user and db_user.ext_uname not in sync_user_names:
    #         logging.info('delete not exist in sync user: ext_uname=%s', db_user.ext_uname)
    #         db_user.deleted = 1
    # db_session.commit()
    redis_driver.client.delete(render_key(SWHYSC_LOCK_KEY))


if __name__ == '__main__':
    sync_user()
