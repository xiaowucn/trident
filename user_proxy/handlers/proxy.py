# pylint: disable=too-many-locals, too-many-return-statements, too-many-branches
import base64
import logging
import os
import time
from collections import defaultdict
from hashlib import sha256
from io import BytesIO
from urllib.parse import urljoin
from uuid import uuid4

import requests
from jwcrypto.jwk import JWK
from xmltodict import parse

from user_proxy import config
from user_proxy.common.rpc_web_service.common import create_tmp_ins, ResultType
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.config import ENV
from user_proxy.db import cache_session
from user_proxy.handlers.base import BaseHandler, route, permission_auth, clear_captcha
from user_proxy.handlers.base import HTTPErrorCode, LoginLimitManager
from user_proxy.handlers.base import common_token_auth
from user_proxy.handlers.csits import CsitsTrackHandler
from user_proxy.handlers.forms import LDAPUserLoginForm, BaseUserLoginForm
from user_proxy.handlers.message import (
    INVALID_PARAMETERS,
    INVALID_USERNAME_OR_PASSWD,
    PERMISSION_DENIED,
    CAPTCHA_EXPIRED,
    CAPTCHA_INVALID,
    ACCOUNT_LOCKED,
    ACCOUNT_LOGIN_LIMIT,
    SYS_CONFIG_ERROR,
    PASSWORD_EXPIRED,
    INVALID_PASSWD,
)
from user_proxy.models.user import User
from user_proxy.models.user import VisitRecord, VisitSys
from user_proxy.utils.authtoken import encode_url
from user_proxy.utils.authtoken import generate_timestamp
from user_proxy.utils.captcha import Captcha
from user_proxy.utils.cas import create_cas_login_url, validate, create_cas_logout_url, create_url
from user_proxy.utils.hash import md5sum
from user_proxy.utils.jwt_util import jwe_decode
from user_proxy.utils.ldap import ldap_login
from user_proxy.web_services import ProxyWebService, UserWebService


@route(r'/test')
class HealthCheckHandler(BaseHandler):
    def get(self):
        return self.data('')


@route(r'/config')
class ConfigsHandler(BaseHandler):
    def get(self):
        data = {
            'redirect_subpath': config.get_config('webif.redirect_subpath'),
            'enable_sys_require': config.get_config('unify_auth.enable_sys_require', False),
            'show_role_manage': config.get_config('unify_auth.show_role_manage', True),
            'http_secure_map': config.get_config('webif.http_secure_map'),
            'auto_redirect_sub_sys': config.get_config('front_config.auto_redirect_sub_sys', False),
            'allow_change_password': config.get_config('front_config.allow_change_password', False),
            'user_login_api': config.get_config('front_config.user_login_api', '/user/login'),
            'internal': config.get_config('front_config.internal', False),  # 标记内部环境，用于区分内外环境登录、退出等差异，暂时只有长江配置
            'dump_user_list': config.get_config('webif.feature.dump_user_list', False),  # 导出用户列表
            'user_manage': config.get_config('front_config.user_manage', True),  # 展示用户管理界面
            'username_manage': config.get_config('front_config.username_manage', False),  # 管理用户名称
            'show_user_allow_login': config.get_config('front_config.show_user_allow_login', False),  # 用户管理里展示用户状态列
            'casdoor_enable': config.get_config('casdoor_auth.enable', False),
            'sys': config.get_config('sys', ''),
            'session': self.session.session_id,
        }
        feature_config = config.get_config('webif.feature', {})
        data.update(feature_config)

        front_config = config.get_config('front_config', {})
        sub_sys_config = front_config.get('sub_sys_config', {})
        data.update({key: value for key, value in front_config.items() if key != 'sub_sys_config'})
        for sub_sys, values in sub_sys_config.items():
            for name, value in values.items():
                data[f'{sub_sys}_{name}'] = value
        if config.get_config('webif.binary_json'):
            data.update({'binary_key': config.get_config('webif.binary_key', '')})
        if self.request.headers.get('Auth-Code', '') == 'enable':
            data['generate_auth_code'] = True
        if config.get_config('autodoc_task_types'):
            data.update(
                {
                    'autodoc_task_types': config.get_config('autodoc_task_types'),
                }
            )
        if config.get_config('autodoc_check_types'):
            data.update(
                {
                    'autodoc_check_types': config.get_config('autodoc_check_types'),
                }
            )
        return self.data(data, handshake=True)


@route(r'/csrf_token')
class CsrfTokenHandler(BaseHandler):
    def get(self):
        csrf_token = sha256(str(uuid4()).encode('utf-8')).hexdigest()
        self.set_secure_cookie("csrf_token", csrf_token, httponly=True)
        return self.data({"csrf_token": csrf_token})


@route(r'/captcha')
class CaptchaHandler(BaseHandler):
    def get(self, *args, **kwargs):
        captcha = Captcha()
        img, code = captcha.generate()

        img_buffer = BytesIO()
        img_buffer.name = 'captcha.gif'
        img.save(img_buffer)
        captcha_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
        self.session['captcha'] = code.lower()
        self.session['captcha_time'] = int(time.time())
        return self.data({'captcha': captcha_base64})


@route(r'/available-sys')
class AvailableSysHandler(BaseHandler):
    def get(self, *args, **kwargs):
        systems = config.get_config('unify_auth.auth_config')
        ret = defaultdict(dict)
        for sys, sys_value in systems.items():
            actual_sys = '_'.join(sys.split('_')[1:])
            host = sys_value.get('host')
            subpath = sys_value.get('subpath') or ''
            logout_api = self.gen_redirect_url(sys_value.get('logout_api', ''), host, subpath)
            ret[actual_sys]['logout_api'] = logout_api
            ret[actual_sys]['system'] = actual_sys
            ret[actual_sys]['need_require'] = sys_value.get('need_require', False)
        return self.data(ret)


@route(r'/get-off')
class GetOffHandler(BaseHandler):
    @permission_auth()
    def get(self, *args, **kwargs):
        arguments = {key: self.get_argument(key, None) for key in self.request.arguments.keys()}
        res = ProxyWebService.get_off(current_user_id=self.current_user.id, origin_host=self.origin_host, arguments=arguments, user_id=None)
        clear_session = config.get_config('unify_auth.clear_session_when_get_off')
        if clear_session or config.get_config('sso_auth_use') == 'casdoor_auth':
            self.session_clear()
        return self.hand_out_data(res)


@route(r'/visit-stat')
class VisitStatHandler(BaseHandler):
    @permission_auth()
    def get(self, *args, **kwargs):
        start_utc = self.get_argument('start_utc', None)
        end_utc = self.get_argument('end_utc', None)
        res = ProxyWebService.get_visit_stat(start_utc=start_utc, end_utc=end_utc)
        return self.hand_out_data(res)


class LoginHandler(BaseHandler):
    def check_captcha(self):
        if config.get_config("webif.feature.check_captcha"):
            expired_time = config.get_config('webif.feature.captcha_expired_time', 60 * 2)
            if self.session['captcha_time'] and int(time.time()) - int(self.session['captcha_time']) > expired_time:
                return False, CAPTCHA_EXPIRED
            captcha = self.get_json_body().get("captcha")
            if not captcha:
                return False, CAPTCHA_INVALID
            if captcha.lower() != self.session['captcha']:
                clear_captcha(self)
                return False, CAPTCHA_INVALID
        return True, ''


@route(r'/user/login')
class UserLoginHandler(LoginHandler):
    @staticmethod
    def check_password_wrong_times(user):
        if not user or not config.get_config('webif.session.check_wrong_password_times.enable', False):
            return False
        if not user.is_sys_admin and config.get_config('sys') == 'xyzq':
            return False
        return True

    def post(self, *args, **kwargs):
        body = self.get_json_body()
        username = body.get('username')
        password = body.get('password')
        if not username or not password:
            return self.error(INVALID_PARAMETERS)

        flag, msg = self.check_captcha()
        if not flag:
            return self.error(msg, status_code=400)

        user = create_tmp_ins(User, UserWebService.get_user_from_ext_uname(ext_uname=username))

        if not self.session.driver.client:
            return self.error(SYS_CONFIG_ERROR)

        remote_ip = self.request.headers.get("X-Real-IP") or self.request.remote_ip
        login_limit_manager = LoginLimitManager(self.session.driver.client, remote_ip, username)
        if self.check_password_wrong_times(user):
            times = login_limit_manager.get_times()
            if times and int(times) >= login_limit_manager.TIMES:
                return self.error(ACCOUNT_LOCKED.format(login_limit_manager.EXPIRED_PERIOD // 60), status_code=400)

            if not user.check_password(password):
                login_limit_manager.incr()
                clear_captcha(self)
                current_times = login_limit_manager.get_times() or 1
                if int(current_times) == login_limit_manager.TIMES:
                    return self.error(ACCOUNT_LOCKED.format(login_limit_manager.EXPIRED_PERIOD // 60), status_code=400)
                return self.error(INVALID_PASSWD.format(login_limit_manager.TIMES - int(current_times)), status_code=400)

            # repeat function with LoginLimitManager
            # if not user.check_password(password):
            #     self.session.check_wrong_password_times(user.id)
            #
            # if self.session.account_locked(user.id):
            #     return self.error(ACCOUNT_LOCKED)

        if not user or not user.check_password(password):
            clear_captcha(self)
            return self.error(INVALID_USERNAME_OR_PASSWD, status_code=400)

        if config.get_config('webif.feature.check_admin_password_expired.enable', False) and user.is_sys_admin:
            if not user.user_data.get('password_expired_time') or generate_timestamp() >= user.user_data['password_expired_time']:
                return self.error(PASSWORD_EXPIRED, status_code=HTTPErrorCode.PASSWORD_EXPIRED.value)

        if self.check_password_wrong_times(user):
            clear_captcha(self)
            login_limit_manager.clear()

        if config.get_config('sys') in ['nesc', 'stocke', 'chasing'] and not user.allow_login:
            return self.error(PERMISSION_DENIED, status_code=400)

        self.session['proxy_user_id'] = str(user.id)
        online_login_limit_toggle = config.get_config('webif.online_login_limit.toggle', False)
        if online_login_limit_toggle and self.session.online_count >= config.get_config("webif.session.online_limit", 10):
            self.session_clear()
            return self.error(ACCOUNT_LOGIN_LIMIT, status_code=400)
        ret_data = UserWebService.get_user(user_id=user.id)
        if config.get_config('webif.xsrf_cookies', False):
            ret_data[1]['_xsrf'] = self.xsrf_token.decode()
        user.session_id = self.session.session_id
        if config.get_config('sys') == 'icbccs':
            remote_ip = self.request.headers.get("X-Real-IP") or self.request.remote_ip
            VisitRecord.create(user.id, VisitSys.TRIDENT.value, ip_address=remote_ip)
        if config.get_config('casdoor_auth.enable', False):
            endpoint = config.get_config('casdoor_auth.endpoint')
            user_sync_url = config.get_config('casdoor_auth.user_sync_url')
            url = create_url(
                endpoint,
                user_sync_url,
                ('userId', user.id),
                ('username', user.ext_uname),
                ('password', password),
                ('owner', config.get_config('casdoor_auth.org_name')),
                ('clientId', config.get_config('casdoor_auth.client_id')),
                ('redirectUrl', self.origin_host),
            )
            url = encode_url(
                url, config.get_config('casdoor_auth.token_auth.app_id'), config.get_config('casdoor_auth.token_auth.secret_key'), exclude_domain=False
            )
            return self.data({'redirect_url': url})
        return self.hand_out_data(ret_data)


@route(r'/user/me')
class CurrentUserHandler(BaseHandler):
    @permission_auth()
    def get(self, *args, **kwargs):
        res = ProxyWebService.me(current_user_id=self.current_user.id)
        if res[0] == ResultType.JSON.value:
            if config.get_config('webif.xsrf_cookies', False):
                res[1]['_xsrf'] = self.get_cookie('_xsrf') or self.xsrf_token.decode()
        return self.hand_out_data(res)


@route(r'/user/logout')
class UserLogoutHandler(BaseHandler):
    def get(self, *args, **kwargs):
        token = None
        ext_uname = self.get_argument('ext_uname', None)
        if self.current_user:
            token = self.current_user.user_data.get('token')
        elif self.check_token():
            if ext_uname:
                user = create_tmp_ins(User, UserWebService.get_user_from_ext_uname(ext_uname=ext_uname))
                token = user and user.user_data.get('token')

        if token:
            res = self.single_sign_out(token)
            if not res and ext_uname is None:
                return self.error('single sign out failed')
        self.session_clear()
        config_sys = config.get_config('sys')
        if config_sys == 'ctsec':
            return self.data({'redirect_url': '/api/v1/ctsec/cas-logout'})
        elif config_sys == 'cjsc' and not config.get_config('front_config.internal'):
            return self.data({'redirect_url': '/api/v1/user/cas-logout'})
        elif config_sys == 'htffund' and not config.get_config('front_config.internal'):
            return self.data({'redirect_url': self.gen_redirect_url('/api/v1/user/cas-logout')})
        elif config_sys == 'mszq':
            custom_system = self.get_argument('custom_system', '')
            redirect_url = '/api/v1/mszq/sso-logout?custom_system=cas' if custom_system == 'cas' else '/api/v1/mszq/sso-logout'
            return self.data({'redirect_url': redirect_url})
        elif config_sys == 'ebscn':
            access_token_key = config.get_config('ebscn_auth.access_token_session_key')
            access_token = self.get_secure_cookie(access_token_key)
            if access_token:
                return self.data({'redirect_url': '/api/v1/ebscn/sso-logout'})
        elif config_sys == 'htsc':
            # glazer的trident只有admin有退出逻辑，需要跳回trident登陆界面
            if 'glazer' in ENV:
                return self.data({'redirect_url': self.gen_redirect_url(config.get_config('htsc_auth.oa_logout_url'))})
            return self.data({'redirect_url': config.get_config('htsc_auth.oa_logout_url')})
        elif config.get_config('sse.login_page_url'):
            redirect_url = f"{config.get_config('sse.login_page_url')}?guid={config.get_config('sse.guid')}&redirect={self.origin_host}"
            if ext_uname is not None:
                return self.redirect(redirect_url)
            else:
                return self.data({'redirect_url': redirect_url})
        elif config.get_config('use_customer_logout', False) and not config.get_config('front_config.internal'):
            return self.data({'redirect_url': '/api/v1/user/customer-logout'})
        return self.data({})

    @staticmethod
    def single_sign_out(token):
        if not token:
            return True
        sign_out_url = config.get_config('sse.logout_url')
        if not sign_out_url:
            return True
        json_payload = {"params": {"token": token}}
        headers = {"access-key": config.get_config("sse.access_key")}
        res = requests.post(sign_out_url, json=json_payload, headers=headers, timeout=(5, 10), verify=False)
        if res.status_code != 200:
            logging.error('登出失败: http_code=%s, content=%s', res.status_code, res.content)
            return False
        return True


@route(r'/user/ldap-login')
class LDAPUserLoginHandler(LoginHandler):
    def post(self, *args, **kwargs):
        need_check_code = self.request.headers.get('Auth-Code', '') == 'enable'
        need_check_code = need_check_code or config.get_config('webif.feature.generate_auth_code', False)
        flag, msg = self.check_captcha()
        if not flag:
            return self.error(msg, status_code=400)

        custom_sys = config.get_config('sys')
        if custom_sys == 'ht':
            form = LDAPUserLoginForm.from_json(self.get_json_body())  # type: LDAPUserLoginForm
        else:
            form = BaseUserLoginForm.from_json(self.get_json_body())

        if not form.validate():
            return self.error(self.form_errors_to_str(form.errors))

        if form.csrf_token.data != self.get_secure_cookie('csrf_token').decode('utf-8'):
            return self.error(u'Invalid csrf_token')

        if need_check_code:
            if not (form.phone.data and form.auth_code.data):
                return self.error('参数错误', status_code=400)
            if form.auth_code.data.encode() != cache_session.get(f'trident:ht:auth:code:{form.phone.data}'):
                return self.error('auth code does not match')
        if custom_sys == 'kysec':
            ProxyWebService.login_precheck(uid=form.uid.data)

        password = form.password.data
        if config.get_config('ldap.passwd_encrypt'):
            password = md5sum(password).upper()
        status, ret_val = ldap_login(form.uid.data, password)
        if not status:
            return self.error(ret_val)
        # ret_val = '1', [2, '2', '3']
        # 创建本地用户
        user_dn, attrlist = ret_val
        department_id, department, username = [item.decode('utf-8') if item is not None else item for item in attrlist]
        res = ProxyWebService.ldap_login(form.uid.data, form.uid.data, department, department_id, username, user_dn)
        self.session['proxy_user_id'] = str(res[1]['id'])
        return self.hand_out_data(res)


@route(r'/user/cas-login')
class UserCasLoginHandler(BaseHandler):
    def get(self, *args, **kwargs):
        cas_token_session_key = config.get_config('cas_auth.cas_token_session_key')
        ticket = self.get_argument(cas_token_session_key, None)
        origin_url = self.gen_redirect_url('api/v1/user/cas-login')
        origin = self.get_argument('origin', '')
        app = self.get_argument('app', '') or self.get_argument('sys', '')
        task_types = self.get_argument('task_types', '')
        url_args = []
        if app:
            url_args.append(('app', app))
        if origin:
            url_args.append(('origin', origin))
        if task_types:
            url_args.append(('task_types', task_types))
        if url_args:
            origin_url = create_url(origin_url, None, *url_args)
        if ticket:
            status, data = validate(ticket, origin_url, self)
            if status:
                result = ProxyWebService.cas_login(cas_res=data)
                res_type, res = result
                if res_type == ResultType.REDIRECT.value:
                    return self.hand_out_data(result)
                self.session['proxy_user_id'] = str(res['id'])
                ticket_session_expired = config.get_config('cas_auth.ticket_session_expire', 2592000)
                self.session.driver.client.setex(ticket, ticket_session_expired, self.session.driver.db_key(self.session.session_id))

                # 子系统调用api
                if app:
                    args = {key: self.get_argument(key, None) for key in self.request.arguments.keys()}
                    args.update({'sys': app})
                    res = ProxyWebService.get_off(current_user_id=self.current_user.id, origin_host=self.origin_host, arguments=args, user_id=res['id'])

                    if config.get_config('sys') == 'csits':
                        CsitsTrackHandler.add_login_track(user=self.current_user, url=self.request.full_url(), system=app)

                    return self.hand_out_data(res)
                elif config.get_config('sys') == 'mszq':
                    url_args.append(('custom_system', 'cas'))
                    redirect_url = create_url('/', None, *url_args)
                else:
                    redirect_url = self.gen_redirect_url(config.get_config('cas_auth.cas_after_login'))
            else:
                return self.error('permission denied')
                # self.clear_cookie(cas_token_session_key)
        else:
            redirect_url = create_cas_login_url(
                config.get_config('cas_auth.server'), config.get_config('cas_auth.login_uri'), origin_url, appid=config.get_config('cas_auth.appid')
            )

        logging.debug('Redirecting to: %s', redirect_url)
        return self.redirect(redirect_url)

    def post(self, *args, **kwargs):
        logging.info('headers: %s', self.request.headers)
        logging.info('json_body: %s', self.request.body)
        if config.get_config('sys') in ['csits', 'mszq']:
            xml_str = self.get_argument('logoutRequest', '')
            if xml_str:
                try:
                    xml_dict = parse(xml_str)
                    ticket = xml_dict['samlp:LogoutRequest']['samlp:SessionIndex']
                except Exception as e:
                    logging.error('parse xml_str error: %s', xml_str)
                    logging.exception(e)
                else:
                    logging.info('delete ticket session: %s', ticket)
                    session_id = self.session.driver.client.get(ticket)
                    if session_id:
                        self.session.driver.client.delete(session_id)
                    self.session.driver.client.delete(ticket)


@route(r'/user/cas-logout')
class UserCasLogoutHandler(BaseHandler):
    # @permission_auth()
    def get(self, *args, **kwargs):
        # cas_username_session_key = config.get_config('cas_auth.cas_username_session_key')
        # cas_attributes_session_key = config.get_config('cas_auth.cas_attributes_session_key')
        #
        # self.clear_cookie(cas_attributes_session_key)
        # self.clear_cookie(cas_username_session_key)
        if self.get_argument('idle', ''):
            pass
        else:
            self.clear_all_cookies()
        cas_after_logout = config.get_config('cas_auth.cas_after_logout')
        if cas_after_logout:
            if app := self.get_argument('app', ''):
                cas_after_logout = f'{cas_after_logout}?app={app}'
        origin_url = self.gen_redirect_url(cas_after_logout)
        if cas_after_logout:
            redirect_url = create_cas_logout_url(config.get_config('cas_auth.server', '/'), config.get_config('cas_auth.logout_uri'), origin_url)
        else:
            redirect_url = create_cas_logout_url(config.get_config('cas_auth.server', '/'), config.get_config('cas_auth.logout_uri'))

        logging.debug('Redirecting to: %s', redirect_url)
        return self.redirect(redirect_url)


@route(r'/user/oauth-login')
class UserOauthLoginHandler(BaseHandler):
    """oauth2授权码模式"""

    @staticmethod
    def build_user_info(res_data):
        return {
            'uid': res_data.get('uid'),
            'ext_uname': res_data.get('accountId'),
            'username': res_data.get('userName'),
            'phone': res_data.get('mobile'),
            'email': res_data.get('email'),
        }

    def get(self, *args, **kwargs):
        access_token = self.get_argument('access_token', None)
        code = self.get_argument('code', None)
        target_uri = self.get_argument('target_uri', None)

        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        trident_sso_api = config.get_config('oauth2_auth.trident_sso_api') or 'user/oauth-login'
        origin_url = f'{trident_base}/api/v1/{trident_sso_api}'

        oauth_base = config.get_config('oauth2_auth.base_url')
        client_id = config.get_config('oauth2_auth.client_id')
        user_agent = self.request.headers.get("User-Agent")
        headers = {"User-Agent": user_agent}
        logging.info('user_agent: %s', user_agent)

        if access_token:
            user_info_api = config.get_config('oauth2_auth.user_info_api')
            user_info_url = create_url(oauth_base, user_info_api, ('access_token', access_token))
            logging.info('user_info_url: %s', user_info_url)
            try:
                response = requests.get(user_info_url, headers=headers, verify=False, timeout=(5, 10))
                res_data = response.json()
                if response.status_code != 200:
                    return self.error(f'get user_info error, status_code={response.status_code}', status_code=400)
                error = res_data.get('error')
                if error:
                    raise Exception(error)
                user_info = self.build_user_info(res_data)
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')
            user = User.make_user(**user_info)
            if not user:
                return self.error('permission denied')
            self.session['proxy_user_id'] = str(user.id)
            redirect_url = urljoin(trident_base, target_uri) if target_uri else trident_base
        elif code:
            if target_uri:
                origin_url = f'{origin_url}?target_uri={target_uri}'
            access_token_api = config.get_config('oauth2_auth.access_token_api')
            client_secret = config.get_config('oauth2_auth.client_secret')
            redirect_url = create_url(
                oauth_base, access_token_api, ('client_id', client_id), ('client_secret', client_secret), ('redirect_uri', origin_url), ('code', code)
            )
            logging.info('redirect to %s', redirect_url)
            if config.get_config('oauth2_auth.request_access_token', False):
                try:
                    response = requests.get(redirect_url, headers=headers, verify=False, timeout=(5, 10))
                    if response.status_code != 200:
                        return self.error(f'get access_token error, status_code={response.status_code}', status_code=400)
                    access_token_info = response.text
                    logging.info('access_token_info: %s', access_token_info)
                    redirect_url = f'{origin_url}?{access_token_info}'
                    logging.info('redirect to %s', redirect_url)
                except Exception as e:
                    logging.exception(e)
                    return self.error('permission denied')
        else:
            authorize_api = config.get_config('oauth2_auth.authorize_api')
            url_args = [('client_id', client_id), ('redirect_uri', origin_url), ('response_type', 'code')]
            if target_uri:
                url_args.append(('target_uri', target_uri))
            redirect_url = create_url(oauth_base, authorize_api, *url_args)
            logging.info('redirect to %s', redirect_url)
        return self.redirect(redirect_url)


@route(r'/user/sso-login')
class UserSSOLoginHandler(BaseHandler):
    @common_token_auth
    def get(self, *args, **kwargs):
        ext_uname = self.get_argument('ext_uname')
        username = self.get_argument('username')
        department = self.get_argument('department', None)
        department_id = self.get_argument('department_id', None)
        if config.get_config('sys') == 'rsm':
            uid = self.get_argument("userid", ext_uname)
            extra = {"tele_phone": self.get_argument("phone", None), "qq": self.get_argument("qq", None)}
        else:
            uid = ext_uname
            extra = {}
        if config.get_config('sys') == 'west':
            user = User.get_by_ext_uname(ext_uname)
        else:
            user = User.make_user(uid, ext_uname, username=username, department_id=department_id, department=department, **extra)
        if not user:
            return self.error('permission denied')
        if not config.get_config('unify_auth.allow_sys_admin_sso', True) and user.is_sys_admin:
            return self.error('管理员用户禁止单点登录')
        self.session['proxy_user_id'] = str(user.id)
        url = '/'
        if sys := self.get_argument('sys', None):
            origin = self.get_argument('origin', None)
            url = get_off_redirect_url(sys, user, origin_host=self.origin_host, origin=origin, redirect=self.get_argument('redirect', None))
            if not url:
                return self.error('sys: {} not config'.format(sys))
        return self.redirect(url)


# @route(r"/user/jwe-login")
class UserSecLoginHandler(BaseHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        jwk = None
        if key_path := config.get_config("jwe_auth.key_path"):
            key_path = os.path.join(config.project_root, key_path)
            if os.path.exists(key_path):
                with open(key_path, 'rb') as f:
                    jwk = JWK.from_json(f.read())
        self.jwk = jwk

    def get(self):
        if self.jwk is None:
            return self.error("Not Found", status_code=404)

        jwe = self.get_argument('jwe', '')
        if not jwe:
            return self.error('invalid params')

        try:
            user_info = jwe_decode(jwe, self.jwk)

            uid = user_info["sub"]
            name = user_info.get("name", uid)
            user = User.make_user(uid=uid, ext_uname=uid, username=name)
            self.session['proxy_user_id'] = str(user.id)
            if app := user_info.get("app"):
                args = {key: self.get_argument(key, None) for key in self.request.arguments.keys()}
                args.update({'sys': app})
                res = ProxyWebService.get_off(current_user_id=self.current_user.id, origin_host=self.origin_host, arguments=args, user_id=user.id)
                return self.hand_out_data(res)

            redirect_url = self.gen_redirect_url(config.get_config('cas_auth.cas_after_login'))
            logging.debug('Redirecting to: %s', redirect_url)
            return self.redirect(redirect_url)

        except Exception as e:
            logging.exception(e)
            return self.error('invalid params')


@route(r'/user/customer-logout')
class UserCustomerLogoutHandler(BaseHandler):
    def get(self, *args, **kwargs):
        self.clear_all_cookies()
        redirect_url = self.gen_redirect_url(config.get_config('oa_auth_url'))
        logging.debug('Redirecting to: %s', redirect_url)
        return self.redirect(redirect_url)


@route(r'/user/auth')
class UserAuthHandler(BaseHandler):
    def get(self, *args, **kwargs):
        sys = self.get_argument('sys', '')
        if not self.current_user:
            redirect_url = self.gen_redirect_url(config.get_config('oa_auth_url'))
        elif sys:
            args = {key: self.get_argument(key, None) for key in self.request.arguments.keys()}
            res = ProxyWebService.get_off(current_user_id=self.current_user.id, origin_host=self.origin_host, arguments=args, user_id=None)
            return self.hand_out_data(res)
        else:
            redirect_url = '/'
        logging.debug('Redirecting to: %s', redirect_url)
        return self.redirect(redirect_url)


def get_autodoc_auth_info():
    app_id = config.get_config('webif.auth_autodoc.app_id')
    secret_key = config.get_config('webif.auth_autodoc.secret_key')
    exclude_domain = config.get_config('webif.auth_autodoc.exclude_domain', True)
    return app_id, secret_key, exclude_domain


def get_autodoc_call_url(self, api):
    host = config.get_config('webif.autodoc_api.host') or self.origin_host
    subpath = config.get_config('webif.autodoc_api.subpath')
    if subpath:
        url = urljoin(urljoin(host, subpath.lstrip('/')), api.lstrip('/'))
    else:
        url = urljoin(host, api.lstrip('/'))
    return url


@route(r'/instructions')
class InstructionUploadHandler(BaseHandler):
    @permission_auth()
    def post(self, *args, **kwargs):
        file_obj = self.request.files['file'][0]
        instructions_upload_api = "/api/v1/instructions?from_token=1"
        instructions_upload_url = get_autodoc_call_url(self, instructions_upload_api)
        app_id, secret_key, exclude_domain = get_autodoc_auth_info()
        instructions_upload_url = encode_url(instructions_upload_url, instructions_upload_url, app_id, secret_key, exclude_domain=exclude_domain)
        mem_file = BytesIO()
        mem_file.write(file_obj['body'])
        mem_file.seek(0)
        try:
            response = requests.post(
                instructions_upload_url,
                files=[
                    ('file', (file_obj['filename'], mem_file)),
                ],
                timeout=(5, 10),
                verify=False,
            )
            ret_data = response.json()
        except Exception as e:
            logging.exception(e)
            return self.data('connect error')
        return self.data(ret_data)

    def get(self, *args, **kwargs):
        file_type = self.get_argument('file_type', None)
        limit = self.get_argument('limit', None)
        instructions_get_api = "/api/v1/instructions?from_token=1"
        instructions_get_url = get_autodoc_call_url(self, instructions_get_api)
        if file_type:
            instructions_get_url += f'&file_type={file_type}'
        if limit:
            instructions_get_url += f'&limit={limit}'
        try:
            response = requests.get(instructions_get_url, timeout=(5, 10), verify=False)
            ret_data = response.json()
        except Exception as e:
            logging.exception(e)
            return self.data('connect error')
        return self.data(ret_data)


@route(r'/instructions/(\d+)/download')
class InstructionDownloadHandler(BaseHandler):
    def get(self, instruction_id, *args, **kwargs):
        instructions_download_api = "/api/v1/instructions/{instruction_id}/download?from_token=1"
        instructions_download_api = instructions_download_api.format(instruction_id=instruction_id)
        instructions_download_url = get_autodoc_call_url(self, instructions_download_api)
        try:
            response = requests.get(instructions_download_url, stream=True, timeout=(5, 60), verify=False)
            logging.info(response.headers['Content-Type'])
            if not response or response.status_code != 200 or 'application/json' in response.headers['Content-Type']:
                return self.error(response.json()['message'])
            logging.info(list(response.headers.keys()))
        except Exception as e:
            logging.exception(e)
            return self.data('connect error')
        else:
            filename = response.headers['Content-Disposition'].split('=')[-1].strip('"')
            self.set_header('Content-Type', 'application/octet-stream')
            self.set_header('Content-Disposition', 'attachment; filename="%s"' % filename)
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    self.write(chunk)
                    self.flush()
            self.finish()


@route(r'/instructions/(\d+)')
class InstructionHandler(BaseHandler):
    @permission_auth()
    def delete(self, instruction_id, *args, **kwargs):
        instructions_delete_api = "/api/v1/instructions/{instruction_id}?from_token=1"
        instructions_delete_api = instructions_delete_api.format(instruction_id=instruction_id)
        instructions_delete_url = get_autodoc_call_url(self, instructions_delete_api)
        app_id, secret_key, exclude_domain = get_autodoc_auth_info()
        instructions_delete_url = encode_url(instructions_delete_url, instructions_delete_url, app_id, secret_key, exclude_domain=exclude_domain)
        try:
            response = requests.delete(instructions_delete_url, timeout=(5, 10), verify=False)
            ret_data = response.json()
        except Exception as e:
            logging.exception(e)
            return self.data('connect error')
        return self.data(ret_data)


if __name__ == '__main__':
    # 使用专门的JWE密钥进行加密解密测试
    with open("/home/gshmu/aoe/trident/data/keys/cgs_test_jwe_public_key.json", 'rb') as _f:
        pub = JWK.from_json(_f.read())
    with open("/home/gshmu/aoe/trident/data/keys/cgs_test_jwe_private_key.json", 'rb') as _f:
        pk = JWK.from_json(_f.read())

    _token = jwe_encode({"sub": "lugang"}, pub)
    print(_token)
    payload = jwe_decode(_token, pk)
    print(payload)

    _token = jwe_encode({"sub": "lugang"}, pk)
    print(_token)
    payload = jwe_decode(_token, pk)
    print(payload)
