# -*-coding:utf-8-*-
import datetime
import logging
from hashlib import md5
from urllib.parse import urljoin

import requests
from sqlalchemy.orm.attributes import flag_modified
from utensils.auth.token import encode_url
from utensils.util import generate_timestamp

from user_proxy import config
from user_proxy.db import db_session, render_key
from user_proxy.models.user import User, Department
from user_proxy.session import RedisDriver
from user_proxy.worker.app import app

USER_SYNC_SERVER = config.get_config('chasing_auth.base_server')
USER_SYNC_API = config.get_config('chasing_auth.sync_user_api')
DEPT_SYNC_API = config.get_config('chasing_auth.sync_department_api')

CHASING_LOCK_KEY = 'chasing_sync_user_info'


def get_current_time():
    return datetime.datetime.now().strftime('%Y%m%d%H%M%S')


def generate_sign(signs):
    sign_source_str = ''.join([str(item) for item in signs])
    logging.info('generate mac source str: %s', sign_source_str)
    return md5(sign_source_str.encode()).hexdigest()


def get_api_data(sync_api, sync_type="users"):
    sync_url = urljoin(USER_SYNC_SERVER, sync_api)
    logging.info('sync %s url: %s', sync_type, sync_url)
    try:
        app_code = config.get_config('chasing_auth.app_code')
        auth_code = config.get_config('chasing_auth.auth_code')
        current_time = get_current_time()
        signs = [app_code, current_time, auth_code]
        json_body = {"appCode": app_code, "mac": generate_sign(signs), "timeStamp": current_time}
        response = requests.post(sync_url, json=json_body, verify=False, timeout=5)
        if response.status_code != 200:
            logging.error('sync %s error: status_code: %s, response text: %s', sync_type, response.status_code, response.text)
            return []
        res_data = response.json()
        if str(res_data['code']) != '000000':
            logging.error('sync %s status error: %s, msg: %s', sync_type, res_data['code'], res_data['code'])
            return []
        data_list = res_data['userInfoList'] if sync_type == 'users' else res_data['orgInfoList']
        logging.info('sync %s: %s', sync_type, len(data_list))
    except Exception as e:
        logging.exception(e)
        return []
    return data_list


@app.task
def sync_user():
    if not USER_SYNC_SERVER or not USER_SYNC_API:
        return
    redis_driver = RedisDriver()
    if not redis_driver.client.set(render_key(CHASING_LOCK_KEY), generate_timestamp(), 3600, nx=True):
        return

    departments = get_api_data(DEPT_SYNC_API, sync_type='dept')
    if departments:
        dept_ids = [item['orgId'] for item in departments]
        db_session.query(Department).filter(Department.external_id.notin_(dept_ids)).delete(synchronize_session='fetch')
        db_session.commit()
        for dept in departments:
            Department.init(dept['orgId'], dept['orgName'], parent_id=dept['parentId'])
        db_session.commit()
    users = get_api_data(USER_SYNC_API)
    if users:
        db_users = dict(db_session.query(User.ext_uname, User).filter(User.deleted == 0))
        valid_user = []
        push_users = []
        for user_info in users:
            if str(user_info['status']) != '0':
                continue
            department_id = user_info.get('orgId')
            department_name = None
            if department_id:
                dept_ins = db_session.query(Department).filter(Department.external_id == department_id).first()
                if dept_ins:
                    department_name = dept_ins.name
            user = User.make_user(
                user_info['memberId'],
                user_info['memberId'],
                username=user_info['userName'],
                oa_name=user_info['accountCode'],
                department_id=user_info.get('orgId'),
                department=department_name,
            )
            push_users.append(
                {
                    'ext_uname': user_info['memberId'],
                    'username': user_info['userName'],
                    'oa_name': user_info['accountCode'],
                    'department_id': user_info.get('orgId'),
                    'department': department_name,
                }
            )
            logging.info('sync user: %s, username: %s', user_info['memberId'], user_info['userName'])
            valid_user.append(user_info['memberId'])
            if user_info['memberId'] not in db_users and department_name in config.get_config('chasing_auth.disable_allow_login_dept', []):
                user.user_data['allow_login'] = False
                flag_modified(user, 'user_data')

        for db_user in db_users.values():
            db_user: User
            if db_user.is_sys_admin or not db_user.oa_user:
                continue
            if db_user.ext_uname not in valid_user:
                db_user.deleted = 1
                logging.info('deleted not in sync users, ext_name: %s', db_user.ext_uname)
        db_session.commit()
        push_users_to_sub_system(push_users)
    redis_driver.client.delete(render_key(CHASING_LOCK_KEY))


def push_users_to_sub_system(user_data):
    for sub_sys in config.get_config('unify_auth.push_to_sub_systems'):
        target = config.get_config(f'unify_auth.auth_config.auth_{sub_sys}')
        if not target:
            logging.error("unify_auth sub_sys: %s not config", sub_sys)
            continue
        push_url = urljoin(target['internal_host'], target['push_users_api'])
        url = encode_url(push_url, target['app_id'], target['secret_key'], exclude_domain=True)
        try:
            logging.info('push users url: %s', url)
            res = requests.post(url, json=user_data, timeout=config.get_config('unify_auth.push_to_sub_sys_time', 30), verify=False)
            if res.status_code == 200:
                logging.info('push user to sub system success: %s', res.text)
            else:
                logging.error('push user to sub system failed: %s, status_code: %s', res.text, res.status_code)
                raise Exception(f'调用子系统接口错误: {sub_sys}')
        except Exception as e:
            logging.exception(e)


if __name__ == '__main__':
    sync_user()
