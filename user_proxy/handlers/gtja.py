"""
国泰君安单点登录api
"""

# pylint:disable=too-many-positional-arguments,unused-import
import base64

# pylint: disable=too-many-locals,too-many-return-statements
import datetime
import json
import logging
import re
from urllib.parse import urljoin, urlencode

from aiohttp import ClientSession

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.authtoken import generate_timestamp
from user_proxy.utils.cas import create_url
from user_proxy.utils.cms_auth import encrypt, decrypt
from user_proxy.utils.gtja import rsa_encrypt_by_public_key


# @route(r'/gtja/sso-login')
# class GtjaSSOLoginHandler(BaseHandler):
#     def get(self, *args, **kwargs):
#         subpath = config.get_config("webif.redirect_subpath", '')
#         base_url = urljoin(self.origin_host, subpath.lstrip('/'))
#         des_key = config.get_config('gtja_auth.des_key')
#         des_iv = config.get_config('gtja_auth.des_iv')
#         app_id = config.get_config('gtja_auth.app_id')
#         server = config.get_config('gtja_auth.server')
#         auth_uri = config.get_config('gtja_auth.auth_uri')
#         origin = self.get_argument('origin', '')
#         url_host = self.get_argument('host', None)
#         app = self.get_argument('app', 'autodoc_overall')
#
#         url_args = []
#         if origin:
#             url_args.append(('origin', origin))
#         if url_host:
#             url_args.append(('host', url_host))
#         url_args.append(('app', app))
#
#         auth_url = urljoin(server.rstrip('/'), auth_uri)
#         logging.info('auth_url: %s', auth_url)
#
#         create_time = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
#         return_url = '{}/api/v1/gtja/sso-login/callback'.format(base_url.rstrip('/'))
#         return_url = urljoin(return_url, '?{}'.format(urlencode(url_args)))
#         logging.info('encrypt params: app_id: %s, create_time: %s, return_url: %s, des_key: %s, des_iv: %s', app_id, create_time, return_url, des_key, des_iv)
#
#         sso_str = app_id + '$' + encrypt(create_time + '|' + return_url, des_key, des_iv)
#         logging.info('encrypted sso: %s', sso_str)
#
#         url_args = [('SSO', sso_str)]
#         redirect_url = create_url(auth_url, None, *url_args)
#         logging.info('redirect_url: %s', redirect_url)
#         return self.redirect(redirect_url)
#
#
# @route(r'/gtja/sso-login/callback')
# class GtjaSSOLoginCallbackHandler(BaseHandler):
#     def get(self, *args, **kwargs):
#         flag = self.get_argument('flag', None)
#         sso = self.get_argument('SSO', '')
#         des_key = config.get_config('gtja_auth.des_key')
#         des_iv = config.get_config('gtja_auth.des_iv')
#         origin = self.get_argument('origin', '')
#         url_host = self.get_argument('host', None)
#         app = self.get_argument('app', 'autodoc_overall')
#         if flag and flag == '0':
#             logging.info('encrypted sso: %s, des_key: %s, des_iv: %s', sso, des_key, des_iv)
#             try:
#                 decrypt_sso = decrypt(sso, des_key, des_iv)
#             except Exception as e:
#                 logging.exception(e)
#                 return self.error('decrypt sso failed')
#             else:
#                 logging.info('decrypted sso: %s', decrypt_sso)
#                 params = decrypt_sso.split('|')
#                 if not params:
#                     return self.error('params is empty')
#                 user_info = params[0]  # 用户名/账号/用户ID
#                 logging.info('user_info: %s', user_info)
#                 user = User.make_user(uid=user_info, ext_uname=user_info, username=user_info)
#                 if not user:
#                     return self.error('permission denied')
#                 self.session['proxy_user_id'] = str(user.id)
#                 user.session_id = self.session.session_id
#                 after_login_url = config.get_config('gtja_auth.after_login')
#                 url_args = []
#                 if origin:
#                     url_args.append(('origin', origin))
#                 if url_host:
#                     url_args.append(('host', url_host))
#                 url_args.append(('sys', app))
#                 redirect_url = self.gen_redirect_url(after_login_url)
#                 url = create_url(redirect_url, None, *url_args)
#                 logging.info('redirect_url: %s', url)
#                 return self.redirect(url)
#         else:
#             logging.info('flag: %s', flag)
#             self.clear_all_cookies()
#             return self.error('flag is not invalid, permission denied')


@route(r'/gtja/sso-login-2')
class GtjaSSOLogin2Handler(BaseHandler):
    P_UNKNOWN_REG = re.compile(r'unKnown', re.I)

    @staticmethod
    def save_user(ext_uname, user_name, staff_id, staff_oa, oa_name, ht_ehr_id=None):
        user = User.make_user(uid=ext_uname, ext_uname=ext_uname, username=user_name, staff_id=staff_id, staff_oa=staff_oa, oa_name=oa_name, _from='gtja')
        return user

    def check_remote_ip(self, remote_ip):
        return remote_ip and not self.P_UNKNOWN_REG.search(remote_ip)

    def get_remote_ip(self):
        remote_ip = self.request.headers.get("X-Forwarded-For")
        if self.check_remote_ip(remote_ip):
            idx = remote_ip.find(',')
            if idx != -1:
                return remote_ip[0:idx]
            return remote_ip

        for remote_ip in [self.request.headers.get("X-Real-IP"), self.request.headers.get('Proxy-Client-IP'), self.request.headers.get('WL-Proxy-Client-IP')]:
            if self.check_remote_ip(remote_ip):
                return remote_ip

        return self.request.remote_ip

    @staticmethod
    async def get_public_key():
        server = config.get_config('gtja_auth_2.server')
        get_public_key_uri = config.get_config('gtja_auth_2.get_public_key_uri')
        get_public_key_url = urljoin(server, get_public_key_uri.lstrip('/'))

        async with ClientSession() as session:
            try:
                response = await session.get(get_public_key_url)
                if response.status != 200:
                    logging.error('获取public key失败: http_code=%s', response.status)
                    return False, '获取公钥失败'
                public_key = await response.text()
                public_key = public_key.replace('\r\n', '\n').replace('\r', '\n')
            except Exception as e:
                logging.exception(e)
                return False, 'permission denied'
            logging.info('public_key_info: %s', public_key)
            return True, public_key

    async def create_user_by_session_id(self, session_id):
        if config.get_config('gtja_auth_2.use_test'):
            res_data = json.loads(base64.b64decode(session_id.encode()).decode())
            data = res_data['Data']
            ext_uname = data['userId']
            oa_name = data['oaName']
            user_name = data['userName']
            staff_id = data.get('staffId')
            staff_oa = data.get('staffOa')
            ht_ehr_id = data.get('htEhrId')
            return self.save_user(ext_uname, user_name, staff_id, staff_oa, oa_name, ht_ehr_id)

        app_id = config.get_config('gtja_auth_2.app_id')
        server = config.get_config('gtja_auth_2.server')
        auth_uri = config.get_config('gtja_auth_2.auth_uri')
        remote_ip = self.get_remote_ip()
        timestamp = generate_timestamp()
        auth_str = json.dumps({"appId": app_id, "checkType": "ip", "ip": remote_ip, "sessionId": session_id, "timestamp": timestamp}, separators=(',', ':'))
        logging.info('auth_str: %s', auth_str)
        flag, public_key_info = await self.get_public_key()
        if not flag:
            return self.error(public_key_info)
        encode_auth_str = rsa_encrypt_by_public_key(public_key_info, auth_str)
        logging.info('encode auth_str: %s', encode_auth_str)
        user_info_url = create_url(
            server,
            auth_uri,
        )
        logging.info('user_info_url: %s', user_info_url)
        async with ClientSession() as session:
            try:
                response = await session.post(user_info_url, data={'ssoParam': encode_auth_str}, headers={"Content-Type": "application/x-www-form-urlencoded"})
                res_data = await response.text()
                res_data = json.loads(res_data)
                logging.info('get user info data: %s', res_data)
                code = res_data['State']
                if response.status != 200:
                    return self.error('get user info error, status_code = {}'.format(response.status))
                if code != 0:
                    logging.info('error msg: %s', res_data['ErrMsg'])
                    return self.error(res_data['ErrMsg'])
                data = res_data['Data']
                ext_uname = data['userId']
                oa_name = data['oaName']
                user_name = data['userName']
                staff_id = data.get('staffId')
                staff_oa = data.get('staffOa')
                ht_ehr_id = data.get('htEhrId')
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')
        return self.save_user(ext_uname, user_name, staff_id, staff_oa, oa_name, ht_ehr_id)

    async def get(self, *args, **kwargs):  # pylint:disable=invalid-overridden-method
        subpath = config.get_config("webif.redirect_subpath", '')
        base_url = urljoin(self.origin_host, subpath.lstrip('/'))
        session_id = self.get_argument('sessionid', None)
        ext_uname = self.get_argument('userId', None)
        oa_name = self.get_argument('oaName', None)
        app = self.get_argument('app', None)
        origin = self.get_argument('origin', None)
        if not session_id and not (ext_uname and oa_name and app and origin):
            return self.error('permission denied')
        if session_id:
            user = await self.create_user_by_session_id(session_id)
        else:
            user = db_session.query(User).filter(User.ext_uname == ext_uname).first()
            if not user:
                user = self.save_user(ext_uname, oa_name, staff_id=None, staff_oa=None, oa_name=oa_name)
        if not user:
            return self.error('permission denied')
        self.session['proxy_user_id'] = str(user.id)
        if app:
            url = get_off_redirect_url(app, user, origin_host=self.origin_host, origin=origin)
            if not url:
                return self.error('sys: {} not config'.format(app))
            return self.redirect(url)
        return self.redirect(base_url)


@route(r'/gtja/sso-login-2/user-info')
class GtjaSSOLogin2UserHandler(GtjaSSOLogin2Handler):
    async def get(self, *args, **kwargs):  # pylint:disable=invalid-overridden-method
        session_id = self.get_argument('sessionid', None)
        if not session_id:
            return self.error('permission denied')
        user = None
        if session_id:
            user = await self.create_user_by_session_id(session_id)
        if not user:
            return self.error('permission denied')
        return self.data(user.to_dict())


@route(r"/gtja/mock1/ibcenter/app/auto-doc/auth-preview")
class GTJSMock1AuthPreview(BaseHandler):
    def data(self, data, **kwargs):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json.dumps(data, ensure_ascii=False))

    def get(self, *args, **kwargs):
        preview_map = config.get_config('check_autodoc_permission.preview')
        task_id = self.get_argument('proId')
        uid = self.get_argument('uid')
        checked = task_id in preview_map.get(uid, [])
        data = {"code": 0, "msg": "OK", "result": checked}
        return self.data(data)


@route(r"/gtja/mock1/ibcenter/app/auto-doc/auth-edit")
class GTJSMock1AuthEdit(GTJSMock1AuthPreview):
    def get(self, *args, **kwargs):
        edit_map = config.get_config('check_autodoc_permission.edit')
        task_id = self.get_argument('proId')
        uid = self.get_argument('uid')
        checked = task_id in edit_map.get(uid, [])
        data = {"code": 0, "msg": "OK", "result": checked}
        return self.data(data)


@route(r"/gtja/mock/ibcenter/app/auto-doc/auth-preview")
class GTJSMockAuthPreview(BaseHandler):
    def data(self, data, **kwargs):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json.dumps(data, ensure_ascii=False))

    def get(self, *args, **kwargs):
        preview_map = config.get_config('check_autodoc_permission.preview')
        task_id = self.get_argument('taskId')
        uid = self.get_argument('uid')
        checked = task_id in preview_map.get(uid, [])
        data = {"code": 0, "msg": "OK", "result": checked}
        return self.data(data)


@route(r"/gtja/mock/ibcenter/app/auto-doc/auth-edit")
class GTJSMockAuthEdit(GTJSMockAuthPreview):
    def get(self, *args, **kwargs):
        edit_map = config.get_config('check_autodoc_permission.edit')
        task_id = self.get_argument('taskId')
        uid = self.get_argument('uid')
        checked = task_id in edit_map.get(uid, [])
        data = {"code": 0, "msg": "OK", "result": checked}
        return self.data(data)


@route(r"/gtja/mock/ibcenter/auth/authClient/clientToken")
@route(r"/gtja/mock1/ibcenter/auth/authClient/clientToken")
class GTJSMockClientToken(GTJSMockAuthPreview):
    def get(self, *args, **kwargs):
        data = {
            "code": 0,
            "msg": "OK",
            "result": "eyJhbGciOiJSUzI1NiJ9.eyJjbGllbnRDb2RlIjoiY3NnbCIsImlhdCI6MTYzNjYyODI0OSwianRpIjoiNWMwZmE1YzQtNDRiZS00ZTAxLWIxMjMtY2YzOTNjOGIzZDI1In0.oE3PwJArEtY6Gld5y1e8Kmis88dj21lF6yAyupbC3nzw7Jf7WtUGb9ZT9W-M3wlBoaRO8_ov1RemViLW_8T0ftMFGoC6TLPWfOaXAAPmgx_H96LomvR0wI_VPnteBOTvARYDW4w0QFq5lvyrkII8bxr19GA8IR5c0BPyfD2hUIQ",
        }
        return self.data(data)
