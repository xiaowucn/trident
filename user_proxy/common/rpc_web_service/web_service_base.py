# pylint: disable=too-many-locals, too-many-branches
import functools
import logging
import mimetypes
import os
from urllib.parse import quote, urljoin

import psycopg2
import sqlalchemy.exc
from jinja2 import Template
from utensils.auth.token import encode_url_path
from utensils.util import generate_timestamp

from user_proxy import config
from user_proxy.common.rpc_web_service.common import ResultType, WebServiceException, check_needs
from user_proxy.config import project_root
from user_proxy.db import db_session
from user_proxy.models.user import User, SysRequire, RequireStatus, Department, VisitRecord
from user_proxy.utils.sm4_util import SM4Util


def db_commit(method):
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            db_session.commit()
        except Exception as e:
            if isinstance(e, (psycopg2.DatabaseError, sqlalchemy.exc.SQLAlchemyError)):
                db_session.rollback()
        return method(*args, **kwargs)

    return wrapper


class WebServiceBase:
    db = db_session

    @classmethod
    def response_file(cls, file_path, filename=None, headers=None, decrypto=True):
        if not filename:
            filename = os.path.split(file_path)[-1]
        if not headers:
            headers = {}
            mine_type, _ = mimetypes.guess_type(file_path)
            if mine_type:
                headers["Content-Type"] = mine_type
                headers['Content-Disposition'] = 'attachment; filename={}'.format(quote(filename))
        with open(file_path, 'rb') as file_object:
            content = file_object.read()
        return cls.response_file_content(content, headers, filename)

    @classmethod
    @db_commit
    def response_file_content(cls, content, headers, filename=''):
        return ResultType.FILE.value, ({'headers': headers, 'filename': filename}, content)

    @classmethod
    @db_commit
    def redirect(cls, re_url, status_code=302):
        return ResultType.REDIRECT.value, (re_url, status_code)

    @classmethod
    @db_commit
    def redirect_plus(cls, re_url, extras, status_code=302):
        data = {'redirect_url': re_url}
        data.update(extras or {})
        return ResultType.REDIRECT_PLUS.value, (data, status_code)

    @classmethod
    @db_commit
    def data(cls, data=None):
        data = {} if data is None else data
        return ResultType.JSON.value, data

    @classmethod
    @db_commit
    def text(cls, text=None):
        text = text or ''
        return ResultType.TEXT.value, text

    @classmethod
    def template(cls, data, status_code=200):
        return ResultType.HTML.value, (data, status_code)

    @classmethod
    @db_commit
    def error(cls, detail, status_code=400, html=False):
        if html:
            template_path = os.path.join(project_root, 'data', 'template', 'error.html')
            with open(template_path) as fp:
                res = Template(fp.read()).render(message=detail)
            return cls.template(res, status_code)
        raise WebServiceException(status_code=status_code, detail=detail)

    @classmethod
    @db_commit
    def permission_error(cls):
        raise WebServiceException(status_code=403, detail='没有权限')

    @staticmethod
    def valid_system_permission(system, user):
        if config.get_config('sys') != 'htamc':
            return True
        # if system in ['glazer', 'autodoc_overall'] and user.user_data.get('custom_system') == 'reits':
        #     return False
        return True


def compatible_autodoc_system(system):
    if system != 'autodoc':
        return system
    if config.get_config('unify_auth.auth_config.auth_{}'.format(system)):
        return system
    if config.get_config('unify_auth.auth_config.auth_autodoc_overall'):
        logging.debug('transfer autodoc to autodoc_overall')
        return 'autodoc_overall'
    return system


def get_user_sys_permission(user, system):
    if config.get_config('sys') == 'ht':
        return ['normal']
    system = compatible_autodoc_system(system)
    permission = set()
    for role in user.roles:
        if system in role.permission:
            permission = permission.union(set(role.permission[system]))
    return permission


def get_off_redirect_url(system, user, current_user=None, origin_host='', **arguments):
    system = compatible_autodoc_system(system)
    target = config.get_config('unify_auth.auth_config.auth_{}'.format(system))
    if not target:
        logging.error('sys: %s not config', system)
        return None
    user_data = {key: value for key, value in user.user_data.items() if value not in [None, ''] and not isinstance(value, (dict, list, tuple, set))}
    permission = get_user_sys_permission(user, system)
    if not permission:
        if not check_needs(current_user, [User.P_MANAGE]) and target.get("need_require", False) and config.get_config('unify_auth.enable_sys_require', False):
            require = user.required_sys.filter(
                SysRequire.status == RequireStatus.approved.value, SysRequire.end_utc > generate_timestamp(), SysRequire.start_utc <= generate_timestamp()
            ).first()
            if not require:
                return None
        permission = ['normal']
    config_sys = config.get_config('sys')
    if config_sys != 'ht':
        user_data.update({'permission': ','.join(permission)})

    allowed_args = ['origin', 'host', 'redirect']
    allowed_args.extend(target.get('allowed_args', []))
    for arg_name in allowed_args:
        arg = arguments.get(arg_name, None)
        if arg not in [None, '']:
            user_data.update({arg_name: arg})
    if target.get('origin') and not arguments.get('origin', None):
        user_data['origin'] = target['origin']

    if user.is_super_admin:
        user_data["super_admin"] = 1

    if config_sys == 'ht':
        if user.is_admin is False and user.is_oa is False and 'autodoc' in system:
            user_data["origin"] = target.get("encrypt_api", "/api/v1/encrypt-my-id")
        if user.is_admin:
            user_data["role"] = "admin"
        elif user.is_dep_admin:
            user_data['role'] = User.DEP_ADMIN_KEY
        # autodoc_data = user_data.pop('autodoc_data', {})
        # if system in ['autodoc', 'autodoc_overall']:
        # if autodoc_data.get('analysis_mode') is not None:
        #     user_data['analysis_mode'] = autodoc_data['analysis_mode']
        # if autodoc_data.get('features'):
        #     selected_features, unselected_features = [], []
        #     for feature, value in autodoc_data['features'].items():
        #         if value:
        #             selected_features.append(feature)
        #         else:
        #             unselected_features.append(feature)
        #     if selected_features:
        #         user_data['features'] = '{}|{}'.format(','.join(selected_features), ','.join(unselected_features))
        # config_autodoc_task_types = config.get_config('autodoc_task_types')
        # if autodoc_data.get('category') and config_autodoc_task_types:
        #     categories = [k for k, v in autodoc_data['category'].items() if v]
        #     user_task_types = ','.join([config_autodoc_task_types[category] for category in categories if config_autodoc_task_types.get(category)])
        #     if user_task_types:
        #         user_data['user_task_types'] = user_task_types
        #
        # department_id = user_data.get('department_id')
        # department_ins = db_session.query(Department).filter(Department.external_id == department_id, Department.deleted == 0).first()
        # department_ins: Department
        # if department_ins and department_ins.department_type is not None:
        #     user_data['department_type'] = department_ins.department_type
        # if department_ins and department_ins.department_type == Department.HT_SECONDARY_SECTOR:
        #     parent_department_ins = db_session.query(Department).filter(Department.external_id == department_ins.parent_id, Department.deleted == 0).first()
        #     parent_department_ins: Department
        #     user_data.update(
        #         {
        #             'parent_id': parent_department_ins.external_id,
        #             'parent_name': parent_department_ins.name,
        #         }
        #     )
        #     if parent_department_ins.department_type is not None:
        #         user_data['parent_type'] = parent_department_ins.department_type
        # elif department_ins and department_ins.department_type == Department.HT_PRIMARY_SECTOR and department_ins.parent_id == '-1':
        #     user_data['parent_id'] = department_ins.parent_id
    elif config_sys == 'zts':
        departments = Department.find_departments_by_external_id(user_data.get('department_id'))
        departments = [item for item in departments if item.name != '中泰证券股份有限公司']
        if departments:
            user_data['department'] = departments[0].name
            user_data['display_department'] = '/'.join(department.name for department in departments[::-1])
    elif config_sys == 'cjsc':
        if user.business_segment:
            user_data['business_segment'] = user.business_segment
        if user.business_departments:
            user_data['manage_department_ids'] = ','.join(user.business_departments.keys())
        if user.business_project_types:
            user_data['manage_project_type_ids'] = ','.join(user.business_project_types.keys())
        departments = Department.find_departments_by_external_id(user_data.get('department_id'))
        if departments:
            user_data['display_department'] = '-'.join(department.name for department in departments[::-1])
    elif config_sys == 'icbccs':
        user_data.pop('customer_permissions', None)
        oa_dept_list = user_data.pop('oa_dept_list', [])
        if oa_dept_list and system == 'scriber_kv':
            user_data['oa_dept_ids'] = ','.join([str(item['deptId']) for item in oa_dept_list])
    # grater用ext_uname做唯一值
    elif config_sys == 'csc' and system == 'grater':
        user_data['ext_uname'], user_data['uid'] = user_data['uid'], user_data['ext_uname']
    elif config_sys == 'htamc':
        user_data.pop('project_info', None)
    elif config_sys == 'gffunds' and user.oa_user:
        user_data['oa_user'] = '1'
    elif config.get_config('unify_auth.pass_parameter_permissions', False) and system == 'scriber':
        # 参数提取稽核权限
        parameter_permissions = []
        for role in user.roles:
            if (role.role_data or {}).get('parameter_permission'):
                parameter_permissions.extend(role.role_data['parameter_permission'])
        if parameter_permissions:
            user_data['parameter_permission'] = ','.join(parameter_permissions)
    elif config_sys == 'west' and 'dep_admin' in user_data['permission']:
        if department_id := user_data.get('department_id'):
            sub_departments = Department.find_departments_by_external_id(department_id, find_parent=False)
            user_data['manage_department_ids'] = ','.join([item.external_id for item in sub_departments])
    elif config_sys == 'swhysc':
        if user.is_swhysc_sponsor_super_admin:
            user_data['customer_role_name'] = 'sponsor_super_admin'
        elif user.is_swhysc_bond_super_admin:
            user_data['customer_role_name'] = 'bond_super_admin'

    subpath = target.get('subpath')
    host = target.get('host') or origin_host
    if subpath:
        auth_url = urljoin(host, target['auth_api'].lstrip('/'))
        send_url = urljoin(urljoin(host, subpath.lstrip('/')), target['auth_api'].lstrip('/'))
    else:
        send_url = auth_url = urljoin(host, target['auth_api'].lstrip('/'))
    app = arguments.get('app', '')
    if not app or app != 'autodoc_overall' or config_sys == 'ht':
        VisitRecord.create(user.id, system)
    signup_application = user_data.get('signup_application')
    if signup_application and signup_application != system:
        user_data.pop('uid', None)
    url = encode_url_path(auth_url, send_url, target['app_id'], target['secret_key'], params=user_data, exclude_domain=True)
    if hex_secret := target.get("obs_login_hex"):
        url, params = url.split("?", maxsplit=1)
        sm4_ins = SM4Util()
        obs_params = sm4_ins.encrypt_sm4(hex_secret, params, mode='ECB')
        url = f"{url}?obs={obs_params}"
    return url
