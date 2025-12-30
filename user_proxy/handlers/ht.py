# -*-coding:utf-8-*-
# pylint:disable=too-many-positional-arguments,too-many-locals,too-many-return-statements,unused-import
import base64
import json
import logging
import os
import secrets
from collections import defaultdict
from urllib.parse import urljoin, urlparse
from xml.dom.minidom import parseString
from xml.etree.ElementTree import Element, SubElement, tostring

import requests
from sqlalchemy import or_, true
from sqlalchemy.orm.attributes import flag_modified
from utensils.crypto import RsaB64Encrypt
from wtforms import Form, IntegerField, StringField, PasswordField, Field
from wtforms.validators import DataRequired, AnyOf

from user_proxy import config
from user_proxy.common.crypto_util import aes_encrypt
from user_proxy.db import cache_session, db_session
from user_proxy.handlers.base import route, BaseHandler, permission_auth
from user_proxy.handlers.gtja import GtjaSSOLogin2Handler
from user_proxy.handlers.message import (
    SYNC_USER_ERROR,
    DEPARTMENT_NOT_EXISTS,
    PERMISSION_DENIED,
    DEPARTMENT_NAME_DUPLICATE,
    USER_NOT_EXISTS,
    INVALID_USERNAME_OR_PASSWD,
)
from user_proxy.handlers.proxy import LDAPUserLoginHandler, BaseUserLoginForm
from user_proxy.models.criteria import Pagination, ArgsPacker
from user_proxy.models.user import Department
from user_proxy.models.user import User
from user_proxy.utils.authtoken import generate_timestamp
from user_proxy.utils.cas import create_url
from user_proxy.utils.ht import ValidUserCondMixin, UpdateUserDataMixin
from user_proxy.utils.ht import decrypt_ht_token
from user_proxy.utils.ldap import ldap_login
from user_proxy.utils.sms import HtSMS


class VerificationCodeForm(Form):
    phone = IntegerField("phone", [DataRequired()])
    csrf_token = StringField("csrf_token", [DataRequired()])


class ESBLoginForm(Form):
    username = StringField("username", [DataRequired()])
    password = PasswordField("password", [DataRequired()])


@route(r'/user/check-auth')
class UserCheckAuthHandler(LDAPUserLoginHandler):
    """
    api for ht to check username matches password
    """

    def post(self, *args, **kwargs):
        flag, msg = self.check_captcha()
        if not flag:
            return self.error(msg, status_code=400)
        form = BaseUserLoginForm.from_json(self.get_json_body())  # type: BaseUserLoginForm
        if not form.validate():
            return self.error(self.form_errors_to_str(form.errors))

        if form.csrf_token.data != self.get_secure_cookie('csrf_token').decode('utf-8'):
            return self.error(u'Invalid csrf_token')

        status, ret_val = ldap_login(form.uid.data, form.password.data)
        if not status:
            return self.error(ret_val)
        return self.data({})


@route(r'/user/auth-code')
class VerificationHandler(BaseHandler):
    async def post(self, *args, **kwargs):
        form = VerificationCodeForm.from_json(self.get_json_body())  # type: VerificationCodeForm
        if not form.validate():
            return self.error(self.form_errors_to_str(form.errors))

        if form.csrf_token.data != self.get_secure_cookie('csrf_token').decode('utf-8'):
            return self.error(u'Invalid csrf_token')

        key = f'trident:ht:auth:code:{form.phone.data}'
        if cache_session.get(key) is not None:
            return self.error(u'can request once in one minute')
        token = ''.join(secrets.choice('0123456789') for _ in range(6))
        key = f'trident:ht:auth:code:{form.phone.data}'
        cache_session.set(key, token, ex=config.get_config('soap.expires') or 60)
        message = config.get_config('soap.message', '短信验证码：%s') % token
        messenger = HtSMS(form.phone.data)
        succeed = await messenger.send_msg(message)
        if not succeed:
            return self.error('get verification code failed', status_code=400)
        return self.data({})

    @staticmethod
    def make_node(name, children=None, **attrs) -> Element:
        children = children or {}
        body = Element(name)
        for key, value in attrs.items():
            body.attrib[key] = value
        for key, value in children.items():
            child = SubElement(body, key)
            child.text = str(value)
        return body


# @route(r'/ht/sso-login')
# class HtSSOLoginHandler(VerificationHandler):
#     """集团oa单点登录"""
#
#     @staticmethod
#     def make_ht_user(uid):
#         user = db_session.query(User).filter(or_(User.ext_uname == uid, User.user_data.op('->>')('uid') == uid), User.is_oa.is_(True)).first()
#         if not user:
#             user = User.create_ht_user_from_auth_api(uid, uid, uid)
#         return user
#
#     @classmethod
#     def generate_xml(cls, request_head, request_body):
#         xml = cls.make_node(
#             'soapenv:Envelope',
#             **{
#                 'xmlns:soapenv': 'http://schemas.xmlsoap.org/soap/envelope/',
#                 'xmlns:hts': 'http://www.htsec.com/',
#             },
#         )
#         xml.append(cls.make_node('soapenv:Header'))
#         body = cls.make_node('soapenv:Body')
#         xml.append(body)
#         request = cls.make_node('hts:request')
#         body.append(request)
#         request.append(cls.make_node('messageRequestHead', children=request_head))
#         request.append(cls.make_node('messageRequestBody', children=request_body))
#         xml_bytes = tostring(xml)
#         return xml_bytes
#
#     @classmethod
#     def connect_webserver(cls, data, error_message=''):
#         headers = {
#             'Content-Type': 'text/xml;charset=utf-8',
#             'Accept': 'text/xml;charset=utf-8',
#         }
#         base_url = config.get_config('sso_auth.web_server')
#         web_server = config.get_config('sso_auth.web_service_uri')
#         url = urljoin(base_url, web_server)
#         logging.info('connect_webserver url:%s', url)
#         response = requests.post(url=url, data=data, headers=headers, timeout=(5, 10), verify=False)
#         if response.status_code != 200:
#             logging.info('request xml str: %s', data)
#             logging.error('response content: %s', response.content)
#             raise Exception(f'连接webserver获取数据失败, status_code={response.status_code}')
#         xml = parseString(response.content)
#         if xml.getElementsByTagName('resultCode')[0].childNodes[0].data != '0':
#             logging.info('request xml str: %s', data)
#             logging.error('response content: %s', response.content)
#             raise Exception(f'系统调用不成功, body: {response.content.decode()}')
#         return_code = xml.getElementsByTagName('returnCode')[0].childNodes[0].data
#         if return_code != '0':
#             logging.info('request xml str: %s', data)
#             logging.error('response content: %s', response.content)
#             raise Exception(f'{error_message}业务解析不成功, 错误码: {return_code}')
#         return xml
#
#     @classmethod
#     def get_token_key(cls):
#         # 获取token的cookie的key名称
#         request_head = {
#             'consumerCode': config.get_config('sso_auth.consumer_code'),
#             'interfaceCode': config.get_config('sso_auth.get_token_key_interface_code'),
#             'reqSN': '',
#             'empCode': '',
#             'branchCode': '',
#             'mac': '',
#         }
#         request_body = {
#             'appName': config.get_config('sso_auth.app_name'),
#         }
#         logging.info('get token key begin, request head: %s, request body: %s', request_head, request_body)
#         xml = cls.generate_xml(request_head, request_body)
#         response_xml = cls.connect_webserver(xml, '获取token key')
#         token_key = response_xml.getElementsByTagName('keyName')[0].childNodes[0].data
#         return token_key
#
#     def get(self, *args, **kwargs):
#         check_same_domain = config.get_config('sso_auth.check_same_domain', False)
#         if check_same_domain:
#             original_request_uri = self.get_argument('X-Original-Request-URI', None)
#             full_url = original_request_uri or self.request.full_url()
#             logging.info('sso-login origin request uri: %s, full url: %s', original_request_uri, full_url)
#         else:
#             full_url = self.request.full_url()
#
#         base_url = full_url.split('/api/')[0]
#         parse_res = urlparse(full_url)
#         app = self.get_argument('app', '')
#         oa_domain = config.get_config('sso_auth.oa_domain')
#         if check_same_domain and oa_domain == parse_res.netloc:
#             # 同域获取sso_token
#             try:
#                 token_key = self.get_token_key()
#             except Exception as e:
#                 logging.exception(e)
#                 return self.error('get token key name failed', status_code=400)
#             logging.info('sso_token key: %s', token_key)
#             sso_token = self.get_cookie(token_key)
#         else:
#             # 异域获取sso_token
#             sso_token = self.get_argument('SSOToken', None)
#         logging.info('sso_token: %s', sso_token)
#         if sso_token:
#             # 解密token获取username
#             request_head = {
#                 'consumerCode': config.get_config('sso_auth.consumer_code'),
#                 'interfaceCode': config.get_config('sso_auth.get_username_interface_code'),
#                 'reqSN': '',
#                 'empCode': '',
#                 'branchCode': '',
#                 'mac': '',
#             }
#             request_body = {
#                 'tokenstr': sso_token,
#                 'appName': config.get_config('sso_auth.app_name'),
#             }
#             logging.info('get username from sso_token begin, request head: %s, request body: %s', request_head, request_body)
#             xml = self.generate_xml(request_head, request_body)
#             try:
#                 response_xml = self.connect_webserver(xml, '获取username')
#             except Exception as e:
#                 logging.exception(e)
#                 return self.error('get username from token failed', status_code=400)
#             # 模拟登录
#             username = response_xml.getElementsByTagName('oaAuth')[0].childNodes[0].data
#             logging.info('username: %s', username)
#             user = self.make_ht_user(username)
#             if user.deleted == User.USER_STATUS_DELETED:
#                 return self.error('该用户已被删除', status_code=400)
#             if not user.allow_login:
#                 return self.error('该用户已被禁止登录', status_code=400)
#             self.set_secure_cookie("proxy_user_id", str(user.id))
#             redirect_url = base_url
#             if app in config.get_config('sso_auth.redirect_apps', []):
#                 redirect_url = urljoin(base_url, f'api/v1/get-off?sys={app}')
#             elif app == 'faulty_word':
#                 redirect_url = urljoin(base_url, '/#/faultyWord')
#         else:
#             auto_login = config.get_config('sso_auth.auto_login')
#             # 同域
#             if check_same_domain and oa_domain == parse_res.netloc:
#                 login_uri = config.get_config('sso_auth.oa_login_uri') if auto_login else config.get_config('sso_auth.login_uri')
#                 redirect_url = create_url(base_url, login_uri)
#             else:
#                 origin_url = '{}/api/v1/ht/sso-login'.format(base_url)
#                 if not auto_login:
#                     origin_url = '{}{}'.format(base_url, config.get_config('sso_auth.login_uri'))
#                 if app:
#                     origin_url = create_url(origin_url.rstrip('/'), None, ('app', app))
#                 redirect_url = create_url(
#                     config.get_config('sso_auth.oa_server'),
#                     config.get_config('sso_auth.oa_login_uri'),
#                     ('method', 'getToken'),
#                     ('autologin', auto_login),
#                     ('redirect', origin_url),
#                 )
#             logging.info('sso-login redirect_url: %s', redirect_url)
#         return self.redirect(redirect_url)
#
#
# @route(r'/ht/esb-login')
# class HtESBLoginHandler(HtSSOLoginHandler):
#     rsa_key_path = config.get_config("sso_auth.rsa_key_path", os.path.join(config.project_root, 'user_data/rsa_key'))
#     rsa_encryptor = RsaB64Encrypt(rsa_key_path)
#
#     @classmethod
#     def get_token_by_username(cls, username):
#         # 根据username获取sso_token
#         request_head = {
#             'consumerCode': config.get_config('sso_auth.consumer_code'),
#             'interfaceCode': config.get_config('sso_auth.get_token_interface_code'),
#             'reqSN': '',
#             'empCode': '',
#             'branchCode': '',
#             'mac': '',
#         }
#         request_body = {
#             'user': username,
#             'appName': config.get_config('sso_auth.app_name'),
#         }
#         logging.info('get token by username, request_head: %s, request_body: %s', request_head, request_body)
#         xml = cls.generate_xml(request_head, request_body)
#         response_xml = cls.connect_webserver(xml, '获取token')
#         sso_token = response_xml.getElementsByTagName('token')[0].childNodes[0].data
#         return sso_token
#
#     async def post(self, *args, **kwargs):
#         form = ESBLoginForm.from_json(self.get_json_body())
#         if not form.validate():
#             return self.error(self.form_errors_to_str(form.errors))
#         username = form.username.data
#         password = form.password.data
#         logging.info('username: %s, password: %s', username, password)
#         # 用户认证
#         request_head = {
#             'consumerCode': config.get_config('sso_auth.consumer_code'),
#             'interfaceCode': config.get_config('sso_auth.auth_interface_code'),
#             'reqSN': '',
#             'empCode': '',
#             'branchCode': '',
#             'mac': '',
#         }
#         request_body = {
#             'username': self.rsa_encryptor.encrypt(form.username.data),
#             'password': self.rsa_encryptor.encrypt(form.password.data),
#             'appName': config.get_config('sso_auth.app_name'),
#         }
#         logging.info('auth user info by esb webserver, request_head: %s, request_body: %s', request_head, request_body)
#         xml = self.generate_xml(request_head, request_body)
#         try:
#             self.connect_webserver(xml)
#         except Exception as e:
#             logging.exception(e)
#             return self.error('esb auth failed', status_code=400)
#         logging.info('auth user succeed')
#         user = self.make_ht_user(username)
#         if user.deleted == User.USER_STATUS_DELETED:
#             return self.error('该用户已被删除')
#         if not user.allow_login:
#             return self.error('该用户已被禁止登录')
#         self.set_secure_cookie("proxy_user_id", str(user.id))
#
#         # 设置sso_token的cookie
#         original_request_uri = self.request.headers.get('X-Original-Request-URI')
#         full_url = original_request_uri or self.request.full_url()
#         base_url = full_url.split('/api/')[0]
#         parse_res = urlparse(full_url)
#         oa_domain = config.get_config('sso_auth.oa_domain')
#         logging.info('esb-login origin request uri: %s, full url: %s', original_request_uri, full_url)
#         # 获取sso_token
#         try:
#             sso_token = self.get_token_by_username(username)
#         except Exception as e:
#             logging.exception(e)
#             return self.error('get token from username failed', status_code=400)
#
#         if oa_domain == parse_res.netloc:
#             try:
#                 token_key = self.get_token_key()
#             except Exception as e:
#                 logging.exception(e)
#                 return self.error('get token key name failed', status_code=400)
#             logging.info('set sso_token cookie, token_key: %s, sso_login: %s', token_key, sso_token)
#             self.set_cookie(token_key, sso_token)
#             return self.data(user.to_dict())
#         else:
#             origin_url = '{}/api/v1/ht/sso-login'.format(base_url)
#             redirect_url = create_url(
#                 config.get_config('sso_auth.oa_server'),
#                 config.get_config('sso_auth.oa_login_uri'),
#                 ('method', 'setToken'),
#                 ('SSOToken', sso_token),
#                 ('redirect', origin_url),
#             )
#             logging.info('esb-login redirect_url: %s', redirect_url)
#             return self.data({'redirect_url': redirect_url})


@route(r'/make-sms')
class MakeSMSHandler(BaseHandler):
    """sdk接口，由autodoc后端任务调用"""

    @permission_auth(token=True)
    async def post(self, *args, **kwargs):
        body = self.get_json_body(binary=False)
        ext_uname = body.get('ext_uname')
        if not ext_uname:
            return self.error('forbidden', status_code=400)
        if config.get_config('sys') == 'ht':
            user = (
                db_session.query(User)
                .filter(or_(User.ext_uname == ext_uname, User.user_data.op('->>')('ext_uname') == ext_uname, User.user_data.op('->>')('uid') == ext_uname))
                .first()
            )
        else:
            user = db_session.query(User).filter(User.ext_uname == ext_uname).first()
        if not user:
            return self.error('user is not existed', status_code=400)
        user_data = user.user_data or {}
        phone_number = user_data.get('phone_number')
        if phone_number:
            messenger = HtSMS(phone_number)
            succeed = await messenger.send_msg(body['message'])
            if not succeed:
                return self.error('make sms msg failed', status_code=400)
        else:
            logging.error('user: %s does not config phone_number', user.ext_uname)
            return self.error(f'user: {user.ext_uname} does not config phone_number', status_code=400)
        return self.data(None)


# @route(r'/departments')
# class DepartmentsHandler(BaseHandler, ValidUserCondMixin):
#     @permission_auth()
#     def get(self, *args, **kwargs):
#         if not self.is_admin():
#             return self.error(PERMISSION_DENIED)
#         cond = (Department.department_type.notin_([Department.HT_SECONDARY_SECTOR, Department.HT_OTHER_DEPARTMENT])) & (Department.deleted == 0)
#         department_name = self.get_argument('department', '')
#         department_id = self.get_argument('department_id', None)
#         username = self.get_argument('username', '')
#         user_ids = []
#         if username:
#             user_ids, dept_ids = self.get_user_dept_info(username)
#             if not department_id:
#                 # 如是二级部门用户，需查找到一级部门信息
#                 departments = db_session.query(Department.external_id, Department.parent_id, Department.department_type).filter(Department.id.in_(dept_ids))
#                 dept_department_ids = []
#                 for item in departments:
#                     if item.department_type == Department.HT_SECONDARY_SECTOR:
#                         dept_department_ids.append(item.parent_id)
#                     else:
#                         dept_department_ids.append(item.external_id)
#                 cond &= Department.external_id.in_(dept_department_ids)
#
#         if department_id:
#             cond &= Department.id == int(department_id)
#         if department_name:
#             cond &= Department.name.like("%{}%".format(department_name.replace('%', '\%')))  # pylint:disable=anomalous-backslash-in-string
#         query = db_session.query(Department).filter(cond).order_by(Department.department_type, Department.id.desc())
#         packer = ArgsPacker(detail=True)
#         data = Pagination(query, packer=packer).limit_from_request(self).data()
#         department_ids = [item['external_id'] for item in data['items']]
#         dep_admins = defaultdict(list)
#         dept_admin_cond = self.build_valid_user_cond() if config.get_config('sys') == 'ht' else true()
#         dep_admin_users = db_session.query(User).filter(
#             User.user_data['department_id'].as_string().in_(department_ids), User.user_data.op('->>')('dep_admin') == 'true', dept_admin_cond
#         )
#         for user in dep_admin_users:
#             dep_admins[str(user.user_data['department_id'])].append(user)
#
#         dep_users = defaultdict(list)
#         if config.get_config('sys') == 'ht':
#             secondary_departments = (
#                 db_session.query(Department)
#                 .filter(Department.parent_id.in_(department_ids), Department.department_type == Department.HT_SECONDARY_SECTOR, Department.deleted == 0)
#                 .all()
#             )
#             for secondary_department in secondary_departments:
#                 dep_users[secondary_department.parent_id].extend(secondary_department.users)
#
#         for item in data['items']:
#             if item['external_id'] in dep_admins:
#                 item['dep_admin'] = [user.to_dict() for user in dep_admins[str(item['external_id'])]]
#             else:
#                 item['dep_admin'] = []
#             if config.get_config('sys') == 'ht' and dep_users and dep_users.get(item['external_id']):
#                 item_user_data = item['users']
#                 item_user_data.extend(
#                     [user.to_dict() for user in dep_users[item['external_id']] if user.deleted == User.USER_STATUS_DEFAULT or user.allow_login]
#                 )
#                 # 根据department_id区分是部门用户管理、部门用户，部门用户需过滤具体user信息
#                 if department_id and username:
#                     item_user_data = [user_info for user_info in item['users'] if user_info['id'] in user_ids]
#                 item['users'] = sorted(item_user_data, key=lambda x: x['id'])
#         return self.data(data)
#
#
# class DepartmentForm(Form):
#     department = StringField('department')
#     parent_id = StringField('parent_id')
#     department_type = IntegerField('department_type', validators=[AnyOf([Department.HT_SECONDARY_SECTOR])])
#     autodoc_data = Field('autodoc_data')
#     categories = Field('categories')


# @route(r'/secondary/departments')
# class SecondaryDepartmentsHandler(BaseHandler, UpdateUserDataMixin, ValidUserCondMixin):
#     def check_admin_permission(self, parent_id):
#         parent_department = (
#             db_session.query(Department)
#             .filter(Department.external_id == parent_id, Department.deleted == 0, Department.department_type == Department.HT_PRIMARY_SECTOR)
#             .first()
#         )
#         if not parent_department:
#             return False, 'parent department not exist'
#         if not self.is_admin() and not (self.current_user.is_dep_admin and self.current_user.user_data.get('department_id') == parent_id):
#             return False, PERMISSION_DENIED
#         return True, ''
#
#     @permission_auth()
#     def get(self, *args, **kwargs):
#         parent_id = self.get_argument('parent_id', None)
#         username = self.get_argument('username', '')
#         if not parent_id:
#             return self.error('parameter error')
#         flag, msg = self.check_admin_permission(parent_id)
#         if not flag:
#             return self.error(msg)
#         cond = (Department.parent_id == parent_id) & (Department.department_type == Department.HT_SECONDARY_SECTOR) & (Department.deleted == 0)
#         user_ids = []
#         if username:
#             user_ids, dept_ids = self.get_user_dept_info(username)
#             cond &= Department.id.in_(dept_ids)
#
#         query = db_session.query(Department).filter(cond).order_by(Department.id.desc())
#         packer = ArgsPacker(detail=True)
#         data = Pagination(query, packer=packer).limit_from_request(self).data()
#         if username:
#             for item in data['items']:
#                 item['users'] = [user_info for user_info in item['users'] if user_info['id'] in user_ids]
#         return self.data(data)
#
#     @permission_auth()
#     def post(self, *args, **kwargs):
#         body = self.get_json_body()
#         parent_id = body.get('parent_id')
#         flag, msg = self.check_admin_permission(parent_id)
#         if not flag:
#             return self.error(msg)
#         form = DepartmentForm.from_json(body)
#         if not form.validate():
#             return self.error(form.errors, status_code=400)
#         department = form.department.data
#         department_type = form.department_type.data
#         department_data = {
#             'autodoc_data': form.autodoc_data.data,
#             'categories': form.categories.data,
#         }
#         db_departments = (
#             db_session.query(Department)
#             .filter(Department.name == department, Department.deleted == 0, or_(Department.parent_id == parent_id, Department.external_id == parent_id))
#             .all()
#         )
#         if db_departments:
#             return self.error(DEPARTMENT_NAME_DUPLICATE)
#
#         department_ins = Department.make_secondary_department(department, parent_id, department_type, department_data)
#         return self.data(department_ins.to_dict())
#
#     @permission_auth()
#     def put(self, *args, **kwargs):
#         body = self.get_json_body()
#         department_id = body.get('department_id')
#         department_ins = (
#             db_session.query(Department)
#             .filter(Department.external_id == department_id, Department.deleted == 0, Department.department_type == Department.HT_SECONDARY_SECTOR)
#             .first()
#         )
#         if not department_ins:
#             return self.error(DEPARTMENT_NOT_EXISTS)
#         parent_id = department_ins.parent_id
#         flag, msg = self.check_admin_permission(parent_id)
#         if not flag:
#             return self.error(msg)
#         # 修改部门名称
#         if body.get('department') is not None:
#             db_departments = (
#                 db_session.query(Department)
#                 .filter(
#                     Department.name == body['department'], Department.deleted == 0, or_(Department.parent_id == parent_id, Department.external_id == parent_id)
#                 )
#                 .all()
#             )
#             if db_departments:
#                 return self.error(DEPARTMENT_NAME_DUPLICATE)
#             department_ins.name = body['department']
#         department_data = department_ins.data or {}
#         # 修改部门配置
#         autodoc_data = {}
#         if body.get('analysis_mode') is not None:
#             autodoc_data['analysis_mode'] = body['analysis_mode']
#         if body.get('category'):
#             autodoc_task_types = config.get_config('autodoc_task_types')
#             autodoc_data['category'] = {item: v for item, v in body['category'].items() if item in autodoc_task_types}
#             department_data['categories'] = body['category']
#         if body.get('features'):
#             autodoc_data['features'] = body['features']
#         if autodoc_data:
#             department_data['autodoc_data'] = autodoc_data
#             department_ins.data = department_data
#             flag_modified(department_ins, 'data')
#             # 刷新部门用户的信息
#             users = db_session.query(User).filter(User.user_data['department_id'].as_string() == department_id).all()
#             for user in users:
#                 user.user_data['autodoc_data'] = autodoc_data
#                 user.user_data['categories'] = body.get('category')
#                 flag_modified(user, 'user_data')
#             if config.get_config('sys') == 'ht':
#                 data = self.build_post_data(users, department_ins=department_ins)
#                 if not self.update_autodoc_user(self.origin_host, data):
#                     return self.error(SYNC_USER_ERROR)
#         db_session.commit()
#         return self.data(department_ins.to_dict())
#
#
# @route(r'/departments/(?P<department_id>[-\w]+)')
# class DepartmentHandler(SecondaryDepartmentsHandler, UpdateUserDataMixin):
#     @permission_auth()
#     def get(self, department_id, *args, **kwargs):
#         if not self.is_admin() and not self.current_user.is_dep_admin:
#             return self.error(PERMISSION_DENIED)
#         department_ins = db_session.query(Department).filter(Department.external_id == department_id, Department.deleted == 0).first()
#         if not department_ins:
#             return self.error(DEPARTMENT_NOT_EXISTS)
#         return self.data(department_ins.to_dict())
#
#     @permission_auth()
#     def delete(self, department_id, *args, **kwargs):
#         department_ins = db_session.query(Department).filter(Department.external_id == department_id).first()
#         if not department_ins:
#             return self.error(DEPARTMENT_NOT_EXISTS)
#         if department_ins.department_type == Department.HT_SECONDARY_SECTOR:
#             flag, msg = self.check_admin_permission(department_ins.parent_id)
#             if not flag:
#                 return self.error(msg)
#         else:
#             if not self.is_admin() and not self.current_user.is_dep_admin:
#                 return self.error(PERMISSION_DENIED)
#         department_ins.deleted = 1
#         if department_ins.department_type == Department.HT_SECONDARY_SECTOR:
#             parent_department_ins = (
#                 db_session.query(Department)
#                 .filter(Department.external_id == department_ins.parent_id, Department.deleted == 0, Department.department_type == Department.HT_PRIMARY_SECTOR)
#                 .first()
#             )
#             parent_update_data = {
#                 'department': parent_department_ins.name,
#                 'department_id': department_ins.parent_id,
#                 'autodoc_data': {},
#                 'categories': {},
#                 'dep_admin': False,
#             }
#             users = db_session.query(User).filter(User.user_data['department_id'].as_string() == department_id).all()
#             for user in users:
#                 user.department_id = parent_department_ins.id
#                 user.user_data.update(parent_update_data)
#                 flag_modified(user, 'user_data')
#             if config.get_config('sys') == 'ht':
#                 data = self.build_post_data(users, department_ins=parent_department_ins)
#                 if not self.update_autodoc_user(self.origin_host, data):
#                     return self.error(SYNC_USER_ERROR)
#         db_session.commit()
#         return self.data({})
#
#
# @route(r'/departments/(?P<department_id>[-\w]+)/users')
# class DepartmentUsersHandler(SecondaryDepartmentsHandler, UpdateUserDataMixin, ValidUserCondMixin):
#     @permission_auth()
#     def get(self, department_id, *args, **kwargs):
#         if not self.is_admin() and not self.current_user.is_dep_admin:
#             return self.error(PERMISSION_DENIED)
#         paginate = int(self.get_argument('paginate', '1'))
#         parent_id = self.get_argument('parent_id', None)
#         department_ids = [department_id, parent_id] if parent_id else [department_id]
#         cond = self.build_valid_user_cond() if config.get_config('sys') == 'ht' else true()
#         query = db_session.query(User).filter(User.user_data['department_id'].as_string().in_(department_ids), cond).order_by(User.id.desc())
#         if paginate == '1':
#             return self.data(Pagination(query).limit_from_request(self).data())
#         else:
#             return self.data([user.to_dict() for user in query])
#
#     @permission_auth()
#     def put(self, department_id, *args, **kwargs):
#         department_ins = (
#             db_session.query(Department)
#             .filter(Department.external_id == department_id, Department.deleted == 0, Department.department_type == Department.HT_SECONDARY_SECTOR)
#             .first()
#         )
#         if not department_ins:
#             return self.error(DEPARTMENT_NOT_EXISTS)
#
#         parent_id = department_ins.parent_id
#         flag, msg = self.check_admin_permission(parent_id)
#         if not flag:
#             return self.error(msg)
#         parent_department_ins = (
#             db_session.query(Department)
#             .filter(Department.external_id == parent_id, Department.deleted == 0, Department.department_type == Department.HT_PRIMARY_SECTOR)
#             .first()
#         )
#         body = self.get_json_body()
#         user_ids = body.get('user_ids') or []
#         cond = self.build_valid_user_cond() if config.get_config('sys') == 'ht' else true()
#         users = db_session.query(User).filter(or_(User.user_data['department_id'].as_string() == department_id, User.id.in_(user_ids)), cond).all()
#         department_ins: Department
#         update_data = {
#             'department': department_ins.name,
#             'department_id': department_id,
#             'autodoc_data': (department_ins.data or {}).get('autodoc_data'),
#             'categories': (department_ins.data or {}).get('categories'),
#         }
#         parent_update_data = {
#             'department': parent_department_ins.name,
#             'department_id': parent_id,
#             'autodoc_data': {},
#             "categories": {},
#             'dep_admin': False,
#         }
#         add_users, cancel_users = [], []
#         for user in users:
#             if user.id in user_ids:
#                 user.department_id = department_ins.id
#                 user.user_data.update(update_data)
#                 add_users.append(user)
#             else:
#                 cancel_users.append(user)
#                 user.department_id = parent_department_ins.id
#                 user.user_data.update(parent_update_data)
#             flag_modified(user, 'user_data')
#         db_session.commit()
#         if config.get_config('sys') == 'ht':
#             data = self.build_post_data(add_users, department_ins=department_ins, parent_department_ins=parent_department_ins)
#             data.update(self.build_post_data(cancel_users, department_ins=parent_department_ins))
#             if not self.update_autodoc_user(self.origin_host, data):
#                 return self.error(SYNC_USER_ERROR)
#         return self.data([user.to_dict() for user in users])
#
#
# @route(r'/departments/(?P<department_id>[-\w]+)/dep-admins')
# class DepartmentDepAdminHandler(BaseHandler, UpdateUserDataMixin, ValidUserCondMixin):
#     @permission_auth()
#     def get(self, department_id, *args, **kwargs):
#         if not self.is_admin() and not self.current_user.is_dep_admin:
#             return self.error(PERMISSION_DENIED)
#         cond = self.build_valid_user_cond() if config.get_config('sys') == 'ht' else true()
#         username = self.get_argument('username', '')
#         if username:
#             cond &= User.user_data.op('->>')('username').like("%{}%".format(username.replace('%', '\%')))  # pylint:disable=anomalous-backslash-in-string
#         query = (
#             db_session.query(User)
#             .filter(User.user_data['department_id'].as_string() == department_id, User.user_data.op('->>')('dep_admin') == 'true', cond)
#             .order_by(User.id.desc())
#         )
#         return self.data(Pagination(query).limit_from_request(self).data())
#
#     @permission_auth()
#     def post(self, department_id, *args, **kwargs):
#         if not self.is_admin():
#             return self.error(PERMISSION_DENIED)
#         department = db_session.query(Department).filter(Department.external_id == department_id, Department.deleted == 0).first()
#         if not department:
#             return self.error(DEPARTMENT_NOT_EXISTS)
#         body = self.get_json_body()
#         user_ids = body['user_ids']
#         action = body['action']
#         users = db_session.query(User).filter(User.id.in_(user_ids), User.user_data['department_id'].as_string() == department_id)
#         for user in users:
#             logging.info('user: %s, department_id: %s', user.ext_uname, department_id)
#             if str(user.user_data.get('department_id')) != str(department_id):
#                 continue
#             user.user_data['dep_admin'] = action == 'add'
#             flag_modified(user, 'user_data')
#         db_session.commit()
#         if config.get_config('sys') == 'ht':
#             ext_type = 1 if action == 'add' else 0
#             data = self.build_post_data(users, ext_type=ext_type)
#             if not self.update_autodoc_user(self.origin_host, data):
#                 return self.error(SYNC_USER_ERROR)
#         return self.data(None)
#
#
# @route(r'/users/(\d+)/dep-admin')
# class OperateUserDepAdminHandler(BaseHandler, UpdateUserDataMixin):
#     @permission_auth()
#     def put(self, user_id, *args, **kwargs):
#         if not self.is_admin():
#             return self.error(PERMISSION_DENIED)
#         user = db_session.query(User).filter(User.id == user_id).first()
#         if not user:
#             return self.error(USER_NOT_EXISTS)
#         body = self.get_json_body()
#         dep_admin = body.get(User.DEP_ADMIN_KEY)
#         if dep_admin is not None:
#             user.user_data[User.DEP_ADMIN_KEY] = bool(dep_admin)
#             flag_modified(user, 'user_data')
#             db_session.commit()
#             if config.get_config('sys') == 'ht':
#                 ext_type = 1 if bool(dep_admin) else 0
#                 data = self.build_post_data([user], ext_type=ext_type)
#                 if not self.update_autodoc_user(self.origin_host, data):
#                     return self.error(SYNC_USER_ERROR)
#         return self.data(user.to_dict())


#
# @route(r'/ht/external-system')
# class HTExternalSystemHandler(BaseHandler):
#     STATUS_MAP = {200: "成功", 600: "信息校验失败", 601: "缺少参数信息", 602: "用户不存在", 603: "用户信息错误", 604: "网络异常"}
#
#     @permission_auth()
#     def get(self, *args, **kwargs):
#         external_sys = self.get_argument('sys')
#         if not config.get_config(f'external_system.{external_sys}'):
#             return self.error(f'{external_sys} config error', status_code=400)
#         user_data = self.current_user.user_data
#         user_info = {
#             "EMP_NO": user_data.get('uid', ''),
#             'EMP_NAME': user_data.get('username', '') if not self.current_user.is_admin else user_data.get('uid', ''),
#             'EMAIL': user_data.get('email', '') if not self.current_user.is_admin else config.get_config(f'external_system.{external_sys}.admin_pwd'),
#             'is_admin': self.current_user.is_admin,
#         }
#         external_sys_server = config.get_config(f'external_system.{external_sys}.base_server')
#         get_token_api = config.get_config(f'external_system.{external_sys}.get_token_api')
#         key = config.get_config(f'external_system.{external_sys}.binary_key')
#         token = base64.b64encode(aes_encrypt(json.dumps(user_info).encode("utf-8"), key=key, fill=True)).decode("utf-8")
#         logging.info('token: %s', token)
#         get_token_url = urljoin(external_sys_server, get_token_api)
#         logging.info('get_token_url: %s', get_token_url)
#         try:
#             response = requests.post(get_token_url, data={'user_info': token}, timeout=5)
#             res_data = response.json()
#             if res_data['status'] != 200:
#                 return self.error(f"message: {res_data['message']}，status: {res_data['status']}", status_code=400)
#             access_token = res_data['data']['accessToken']
#             # refresh_token = res_data['data']['refreshToken']
#         except Exception as e:
#             logging.exception(e)
#             return self.error('获取accessToken失败', status_code=400)
#
#         external_sys_main_url = urljoin(self.origin_host, config.get_config(f'external_system.{external_sys}.subpath')).rstrip('/')
#         redirect_url = f'{external_sys_main_url}/#/?access_token={access_token}'
#         logging.info('redirect to: %s', redirect_url)
#         return self.redirect(redirect_url)
#
#
# @route(r'/ht/sso-token-login')
# class HtSSOTokenLoginHandler(HtSSOLoginHandler):
#     """投行oa单点登录"""
#
#     def get(self, *args, **kwargs):
#         token = self.get_argument('token', None)
#         callback_url = self.get_argument('callBackUrl', None)
#         if not token:
#             return self.error('miss token', status_code=400)
#         user_info_str = decrypt_ht_token(token)
#         # {"userName":"admin","timestamp":1666588425130}
#         logging.info('decrypt token user_info: %s', user_info_str)
#         if not user_info_str:
#             logging.error('decrypt token failed: token: %s', token)
#             return self.error('decrypt token failed', status_code=400)
#         user_info = json.loads(user_info_str)
#         user_id = user_info['userName']
#         timestamp = user_info['timestamp']
#         current_time = generate_timestamp()
#         if current_time * 1000 - timestamp >= config.get_config('ht_sso_auth.token_expired_time', 18000000):
#             return self.error('token expired', status_code=400)
#         user = self.make_ht_user(user_id)
#         if user.deleted == User.USER_STATUS_DELETED:
#             return self.error('该用户已被删除', status_code=400)
#         if not user.allow_login:
#             return self.error('该用户已被禁止登录', status_code=400)
#         self.set_secure_cookie("proxy_user_id", str(user.id))
#         redirect_url = self.request.full_url().split('/api/')[0] if not callback_url else callback_url
#         logging.info('redirect to : %s', redirect_url)
#         return self.redirect(redirect_url)


@route(r'/gtht/sso-login')
class GTHTSSOLoginHandler(GtjaSSOLogin2Handler):

    @staticmethod
    def save_user(ext_uname, user_name, staff_id, staff_oa, oa_name, ht_ehr_id=None):
        user = db_session.query(User).filter(User.ext_uname == ht_ehr_id, User.is_oa.is_(True)).first()
        if not user:
            user = db_session.query(User).filter(User.user_data.op('->>')('uid') == ht_ehr_id, User.is_oa.is_(True)).first()
        if user:
            user.user_data.update(
                {
                    'staff_id': staff_id,
                    'staff_oa': staff_oa,
                }
            )
            flag_modified(user, 'user_data')
            return user
        else:
            user = User.make_user(
                uid=staff_id, ext_uname=staff_id, username=staff_oa, staff_id=staff_id, staff_oa=staff_oa, oa_name=oa_name, ht_ehr_id=ht_ehr_id, _from='gtja'
            )
        return user


@route(r'/gtht/user-info')
class GTHTUserInfoHandler(GTHTSSOLoginHandler):
    async def post(self, *args, **kwargs):
        body = self.get_json_body(binary=False)
        session_id = body.get('sessionid')
        if session_id:
            user = await self.create_user_by_session_id(session_id)
            if user:
                return self.data(user.to_dict())
            return self.error('获取用户信息失败')
        username = body.get('username')
        password = body.get('password')
        if not username or not password:
            return self.error(INVALID_USERNAME_OR_PASSWD)
        user = db_session.query(User).filter(User.ext_uname == username, User.deleted == 0).first()
        if not user:
            return self.error(INVALID_USERNAME_OR_PASSWD)
        if not user.check_password(base64.b64decode(password.encode()).decode()):
            return self.data(INVALID_USERNAME_OR_PASSWD)
        return self.data(user.to_dict())
