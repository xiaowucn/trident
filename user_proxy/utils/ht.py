# -*-coding:utf-8-*-
import json
import logging
import subprocess
import traceback
from urllib.parse import urljoin

import requests
from sqlalchemy import or_, true

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.models.user import Department, User
from user_proxy.utils.authtoken import encode_url, generate_timestamp


class UpdateUserDataMixin:
    @staticmethod
    def build_post_data(users, ext_type=0, department_ins=None, parent_department_ins=None):
        data = {}
        user_data = {}
        if department_ins:
            user_data['department_type'] = department_ins.department_type
            autodoc_data = (department_ins.data or {}).get('autodoc_data') or {}
            user_data['features'] = autodoc_data.get('features', {})
            autodoc_task_types = config.get_config('autodoc_task_types')
            if autodoc_data and autodoc_data.get('category', {}) and autodoc_task_types:
                categories = [k for k, v in autodoc_data['category'].items() if v]
                user_task_types = ','.join([autodoc_task_types[category] for category in categories if autodoc_task_types.get(category)])
                user_data['task_types'] = {task_type: True for task_type in user_task_types.split(',') if task_type}
            else:
                user_data['task_types'] = {}
            user_data['analysis_mode'] = (autodoc_data or {}).get('analysis_mode')

            if not parent_department_ins and department_ins.department_type == Department.HT_PRIMARY_SECTOR:
                user_data.update({'parent_id': '', 'parent_name': '', 'parent_type': None})
        if parent_department_ins:
            user_data.update(
                {
                    'parent_id': parent_department_ins.external_id,
                    'parent_name': parent_department_ins.name,
                    'parent_type': parent_department_ins.department_type,
                }
            )
        for user in users:
            data[user.ext_uname] = {
                'ext_type': ext_type,  # 对应autodoc, 0: 普通用户， 1: 部门管理员
            }
            if department_ins:
                data[user.ext_uname].update({'department': department_ins.name, 'department_id': department_ins.external_id, 'user_data': user_data})

        return data

    @staticmethod
    def create_update_url(target, origin_host, params=None, action="update"):
        auth_api = target['update_api'].lstrip('/') if action == 'update' else target['auth_api'].lstrip('/')
        subpath = target.get('subpath')
        host = target.get('host') or origin_host
        auth_url = urljoin(host, auth_api)
        url = encode_url(auth_url, target['app_id'], target['secret_key'], exclude_domain=True, params=params, send_subpath=subpath)
        return url

    @classmethod
    def delete_autodoc_user(cls, origin_host, user):
        target = config.get_config('unify_auth.auth_autodoc_user_sync')
        if target['sync_enable'] is False:
            return True
        if not target:
            return None
        params = {"ext_uname": user.ext_uname}
        url = cls.create_update_url(target, origin_host, params, action='delete')
        try:
            res = requests.get(url, timeout=(5, 10), verify=False)
            if not res.ok:
                logging.error("delete autodoc user err, uname: %s, err: %s", user.ext_uname, res.text)
            else:
                return True
        except Exception as e:
            logging.error(traceback.format_exc())

    def update_autodoc_user(self, origin_host, data):
        target = config.get_config('unify_auth.auth_autodoc_user_sync')
        if target['sync_enable'] is False:
            return True
        if not target:
            return None
        url = self.create_update_url(target, origin_host)
        try:
            logging.info('update department data: %s', data)
            res = requests.post(url, json=data, timeout=(5, 10), verify=False)
            if not res.ok:
                logging.error("update autodoc user err, user data: %s, err: %s", data, res.text)
            else:
                return True
        except Exception as e:
            logging.error(traceback.format_exc())


class ValidUserCondMixin:
    @staticmethod
    def build_valid_user_cond():
        current_time = generate_timestamp()
        cond = (
            (User.deleted == User.HT_USER_STATUS_ABNORMAL)
            & (User.user_data.op('->>')('allow_login') != 'false')
            & (User.user_data['expired_time'].as_integer() >= current_time)
        )
        return or_(User.deleted == User.USER_STATUS_DEFAULT, cond)

    def get_user_dept_info(self, username):
        user_cond = self.build_valid_user_cond() if config.get_config('sys') == 'ht' else true()
        user_cond &= User.user_data.op('->>')('username').like("%{}%".format(username.replace('%', '\%')))  # pylint:disable=anomalous-backslash-in-string
        users = db_session.query(User.id, User.department_id).filter(user_cond)
        dept_ids = {user.department_id for user in users}
        user_ids = {user.id for user in users}
        return user_ids, dept_ids


def decrypt_ht_token(token: str):
    key = config.get_config('ht_sso_auth.sso_crypt_key', 'apex.aas.app.webapi')
    if not key:
        logging.error('sso crypt key is null')
        return None
    project_root = config.project_root
    # pylint: disable=subprocess-run-check
    res = subprocess.run(
        ['/usr/bin/java', '-classpath', f'{project_root}/misc/ht/aesutil-client-1.0-SNAPSHOT-jar-with-dependencies.jar', 'com.ht.aesutil.AESUtil', token, key],
        stdout=subprocess.PIPE,
    )
    if res.returncode == 0:
        decrypted_token = res.stdout
        return decrypted_token.decode().strip()
    logging.error('shell command execution failed')
    return None


if __name__ == '__main__':
    user_info_str = decrypt_ht_token('2E3A906CE09F93F32567909322E386528801FAE7C09780DCC2DD17C9E7B15A766DA542B43813962125BD35C5FB2C4816')
    user_info = json.loads(user_info_str)
