# -*-coding:utf-8-*-
import logging
from urllib.parse import urljoin

import requests

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler, common_token_auth
from user_proxy.models.user import User, Department
from user_proxy.utils.authtoken import encode_url


@route(r'/west/users/sync')
class WESTUsersSyncHandler(BaseHandler):
    @common_token_auth
    def post(self, *args, **kwargs):
        data = self.get_json_body(binary=False)
        logging.info('west users sync, total: %s, sync_type: %s', data['total'], data['sync_type'])
        if str(data['sync_type']) not in ['1', '2']:
            return self.error(f'sync_type error: {data["sync_type"]}')
        if not data['items']:
            return self.error('empty sync users')
        if any(item for item in data['items'] if not item['ext_uname'].strip() or not item['username'].strip()):
            return self.error('exist empty ext_uname or username data')
        data['items'] = [item for item in data['items'] if item['ext_uname'] != 'admin']
        sync_users = []
        for item in data['items']:
            sync_users.append(item['ext_uname'])
            user = User.make_user(
                item['ext_uname'],
                item['ext_uname'],
                username=item['username'],
                department=item['department'],
                department_id=item['department_id'],
                work_status=item['work_status'],
            )
            if user.is_sys_admin:
                continue
            # 无效用户
            if str(item['work_status']) == '2':
                logging.info('delete invalid user: %s, work_status: %s', item['ext_uname'], item['work_status'])
                user.deleted = 1
        db_session.commit()

        # 全量同步
        if str(data['sync_type']) == '1':
            without_sync_users = db_session.query(User).filter(User.deleted == 0, User.ext_uname.notin_(sync_users))
            for user in without_sync_users:
                if user.is_sys_admin or not user.oa_user:
                    continue
                user.deleted = 1
                logging.info('deleted not in full sync users, ext_name: %s', user.ext_uname)
            db_session.commit()

        try:
            push_users_to_sub_system(data)
        except Exception:
            return self.error('push users to sub_sys error')

        return self.data({})


@route(r'/west/departments/sync')
class WESTDepartmentSyncHandler(BaseHandler):
    @common_token_auth
    def post(self, *args, **kwargs):
        data = self.get_json_body(binary=False)
        logging.info('west departments sync, total: %s, sync_type: %s', data['total'], data['sync_type'])
        if str(data['sync_type']) not in ['1', '2']:
            return self.error(f'sync_type error: {data["sync_type"]}')
        if not data['items']:
            return self.error('empty sync departments')
        if any(item for item in data['items'] if not item['department_id'].strip() or not item['parent_id'].strip()):
            return self.error('exist empty department_id or parent_id data')
        db_departments = dict(db_session.query(Department.external_id, Department))
        for item in data['items']:
            dept = db_departments.pop(str(item['department_id']), Department(external_id=str(item['department_id'])))
            dept.parent_id = str(item['parent_id'])
            dept.name = str(item['department'])

            if str(item['work_status']) == '2':
                logging.info(
                    'delete invalid department_id: %s, department: %s, work_status: %s', item['department_id'], item['department'], item['work_status']
                )
                dept.deleted = 1
            elif str(item['work_status']) == '1':
                dept.deleted = 0
            db_session.add(dept)
        db_session.commit()

        # 全量同步
        if str(data['sync_type']) == '1':
            for dept in db_departments.values():
                dept.deleted = 1
                logging.info('deleted not in full sync departments, department_id: %s, department: %s', dept.external_id, dept.name)
            db_session.commit()

        return self.data({})


@route(r'/west/sub-departments')
class WESTSubDepartmentsHandler(BaseHandler):
    @common_token_auth
    def get(self, *args, **kwargs):
        department_id = self.get_argument('department_id', '')
        if not department_id:
            return self.data([])
        sub_departments = Department.find_departments_by_external_id(department_id, find_parent=False)
        sub_department_ids = [item.external_id for item in sub_departments]
        return self.data(sub_department_ids)


@route(r'/west/projects/sync')
class WESTProjectsSyncHandler(BaseHandler):
    @common_token_auth
    def post(self, *args, **kwargs):
        data = self.get_json_body(binary=False)
        logging.info('west projects sync, total: %s, sync_type: %s', data['total'], data['sync_type'])
        if str(data['sync_type']) not in ['1', '2']:
            return self.error(f'sync_type error: {data["sync_type"]}')
        if not data['items']:
            return self.error('empty sync projects')
        if any(item for item in data['items'] if not item['project_id'].strip() or not item['project_name'].strip()):
            return self.error('exist empty project_id or project_name data')
        try:
            push_projects_to_autodoc(data)
        except Exception:
            return self.error('push projects to sub_sys error')
        return self.data({})


def push_users_to_sub_system(user_data):
    for sub_sys in config.get_config('unify_auth.push_to_sub_systems'):
        target = config.get_config(f'unify_auth.auth_config.auth_{sub_sys}')
        if not target:
            logging.error("unify_auth sub_sys: %s not config", sub_sys)
            raise Exception(f'子系统配置错误: {sub_sys}')
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
            raise Exception('push users to sub_sys error') from e


def push_projects_to_autodoc(projects_data):
    target = config.get_config('unify_auth.auth_config.auth_autodoc_overall')
    if not target:
        logging.error("unify_auth sub_sys: %s not config", 'autodoc_overall')
        return
    push_url = urljoin(urljoin(target['internal_host'], target['subpath']), target['push_projects_api'])
    url = encode_url(push_url, target['app_id'], target['secret_key'], exclude_domain=True)
    try:
        logging.info('push projects url: %s', url)
        res = requests.post(url, json=projects_data, timeout=config.get_config('unify_auth.push_to_sub_sys_time', 30), verify=False)
        if res.status_code == 200:
            logging.info('push projects to autodoc success: %s', res.text)
        else:
            logging.error('push projects to autodoc failed: %s, status_code: %s', res.text, res.status_code)
            raise Exception('调用autodoc系统接口错误')
    except Exception as e:
        logging.exception(e)
        raise Exception('push projects to autodoc error') from e
