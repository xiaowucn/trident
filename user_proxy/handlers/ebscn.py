"""
光大单点登录api
"""
import hashlib
import json
import logging
import uuid

from urllib.parse import urljoin

import cx_Oracle
import psycopg2
import requests
import sqlalchemy.exc
from sqlalchemy import create_engine
from tornado.web import HTTPError

from user_proxy import config
from user_proxy.db import get_customer_session, db_session
from user_proxy.handlers.base import route, BaseHandler, permission_auth
from user_proxy.handlers.message import INVALID_PARAMETERS, USER_NOT_EXISTS, INVALID_USERNAME_OR_PASSWD, DATABASE_CONNECT_ERROR, INVALID_USER_ERROR
from user_proxy.models.user import User
from user_proxy.utils.authtoken import encode_url_by_config
from user_proxy.utils.cas import create_url


class EBSCNBaseHandler(BaseHandler):
    @staticmethod
    def ebscn_token(user_id="", user_name="", sys_id="", proc_id="", form_id="", public_key="", for_oa=False):
        from datetime import datetime
        import hashlib
        _date = datetime.now().strftime('%Y%m%d')
        if for_oa:
            _data = ("%s%s%s%s" % (user_id, user_name, public_key, _date)).encode()
        else:
            _data = ("%s%s%s%s%s%s%s" % (sys_id, proc_id, form_id, public_key, user_id, user_name, _date)).encode()
        return hashlib.md5(_data).hexdigest()

    @staticmethod
    def ext_sys_login_url(api, platform, user_id="", user_name="", sys_id="", proc_id="", form_id="", user_role=0):
        return "%s?UserID=%s&UserRole=%s&ProcID=%s&FormID=%s&SysID=%s&UserName=%s&Platform=%s&url=%s" % (
            api, user_id, user_role, proc_id, form_id, sys_id, user_name, platform, "")

    @staticmethod
    def save_user(uid, ext_uname, username, _from):
        user = User.make_user(uid=uid, ext_uname=ext_uname, username=username, _from=_from)
        return user


@route(r'/ebscn/sso-login')
class EBSCNSSOLoginHandler(EBSCNBaseHandler):
    @staticmethod
    def save_user_without_update_username(uid, ext_uname, username, _from):
        user = db_session.query(User).filter(User.ext_uname == ext_uname).first()
        if user and user.user_data.get('username'):
            username = None
        user = User.make_user(uid=uid, ext_uname=ext_uname, username=username, _from=_from)
        return user

    # 未对接使用
    def get(self, *args, **kwargs):
        code = self.get_argument('code', None)
        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))

        oauth_base = config.get_config('ebscn_uth.base_url')
        client_id = config.get_config('ebscn_uth.client_id')
        code_state_key = config.get_config('ebscn_auth.code_state_session_key')
        access_token_key = config.get_config('ebscn_auth.access_token_session_key')

        if code:
            callback_state = self.get_argument('state', None)
            if not callback_state or callback_state != self.session[code_state_key]:
                return self.error('permission denied, illegal request')
            # 根据code获取access_token
            origin_url = '{}/api/v1/ebscn/sso-login'.format(trident_base)
            access_token_api = config.get_config('ebscn_uth.access_token_api')
            client_secret = config.get_config('ebscn_uth.client_secret')
            access_token_url = create_url(
                oauth_base, access_token_api,
                ('client_id', client_id),
                ('grant_type', 'authorization_code'),
                ('client_secret', client_secret),
                ('redirect_uri', origin_url),
                ('code', code),
            )
            logging.info('access_token_url: %s', access_token_url)
            try:
                response = requests.get(access_token_url)
                res_data = response.json()
                if response.status_code != 200:
                    return self.error('get access_token failed, status_code={}'.format(response.status_code), status_code=400)
                access_token = res_data.get('access_token')
                if not access_token:
                    return self.error('access_token is empty', status_code=400)
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied, get access_token error')
            self.set_secure_cookie(access_token_key, access_token)
            # 根据access_token获取用户信息
            user_info_api = config.get_config('ebscn_uth.user_info_api')
            user_info_url = create_url(
                oauth_base, user_info_api,
                ('access_token', access_token)
            )
            logging.info('user_info_url: %s', user_info_url)
            try:
                response = requests.get(user_info_url)
                res_data = response.json()
                if response.status_code != 200:
                    return self.error('get user_info failed, status_code={}'.format(response.status_code), status_code=400)
                uid = res_data.get('id')
                ext_uname = res_data.get('user_id')
                username = res_data.get('username')
                # TODO 确认与旧单点用户参数对应情况
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied, get user info error')
            user = self.save_user(uid, ext_uname, username, _from='ebscn')
            if not user:
                return self.error('permission denied')
            self.session['proxy_user_id'] = str(user.id)
            redirect_url = trident_base
        else:
            origin_url = '{}/api/v1/ebscn/sso-login'.format(trident_base)
            authorize_api = config.get_config('ebscn_uth.authorize_api')
            state = uuid.uuid4().hex
            redirect_url = create_url(
                oauth_base, authorize_api,
                ('client_id', client_id),
                ('redirect_uri', origin_url),
                ('response_type', 'code'),
                ('state', state)
            )
            self.session[code_state_key] = str(state)
            logging.info('redirect to %s', redirect_url)
        return self.redirect(redirect_url)

    def post(self, *args, **kwargs):
        """trident登录界面用客户账号密码登录"""
        body = self.get_json_body()
        username = body.get('username')
        password = body.get('password')
        if not username or not password:
            return self.error(INVALID_PARAMETERS, status_code=400)

        if not config.get_config('ebscn_db.enable'):
            return self.error('permission denied')

        dsn = config.get_config('ebscn_db.oracle_dsn')
        user_sql = config.get_config('ebscn_db.user_info_sql')
        if not dsn or not user_sql:
            raise HTTPError(status_code=404)

        user_info = None
        # ebscn: 光大投行用户 ebscn_oa: 光大其他用户
        platform = 'ebscn'
        try:
            engine = create_engine(dsn, pool_pre_ping=True)
            with engine.connect() as connection:
                user_info = connection.execute(user_sql, {"USERID": username}).fetchone()
        except (cx_Oracle.DatabaseError, sqlalchemy.exc.DatabaseError) as e:
            if config.get_config('ebscn_db.raise_db_error', True):
                logging.exception(e)
                return self.error(DATABASE_CONNECT_ERROR, status_code=400)
        if not user_info:
            try:
                customer_db_session = get_customer_session()
                pg_user_sql = config.get_config('ebscn_db.pg_user_info_sql')
                user_info = customer_db_session.execute(pg_user_sql, {"loginid": username}).fetchone()
            except (psycopg2.DatabaseError, sqlalchemy.exc.SQLAlchemyError) as e:
                logging.exception(e)
                return self.error(DATABASE_CONNECT_ERROR, status_code=400)
            if not user_info:
                return self.error(USER_NOT_EXISTS, status_code=400)
            if str(user_info.status) not in User.EBSCN_USER_VALID_STATUS_MAP:
                return self.error(INVALID_USER_ERROR, status_code=400)
            platform = 'ebscn_oa'
        input_password = hashlib.md5(password.encode()).hexdigest()
        if user_info.password.lower() != input_password:
            return self.error(INVALID_USERNAME_OR_PASSWD, status_code=400)
        user = self.save_user_without_update_username(uid=username, ext_uname=username, username=username, _from=platform)
        if not user:
            return self.error('permission denied')
        self.session['proxy_user_id'] = str(user.id)
        return self.data(user.to_dict())


@route(r'/ebscn/sso-logout')
class EBSCNSSOLogoutHandler(BaseHandler):
    def get(self, *args, **kwargs):
        access_token_key = config.get_config('ebscn_auth.access_token_session_key')
        access_token = self.get_secure_cookie(access_token_key)
        oa_server = config.get_config('ebscn_auth.base_url')
        oa_logout_api = config.get_config('ebscn_auth.oa_logout_api')
        redirect_url = create_url(oa_server, oa_logout_api, ('access_token', access_token))
        logging.debug('Logout, Redirecting to: {0}'.format(redirect_url))
        self.clear_all_cookies()
        return self.redirect(redirect_url)


@route(r'/user/sso_login/ebscn')
class EbscnLoginHandler(EBSCNBaseHandler):
    """光大登录入口 大投行, calliper和grater只走这个接口和协同账号密码登录接口, _from不进行区分,都为ebscn"""

    def get(self, *args, **kwargs):
        user_id = self.get_argument("UserID", "0")
        user_name = self.get_argument("UserName", "")
        sys_id = self.get_argument("SysID", "")
        proc_id = self.get_argument("ProcID", "")
        form_id = self.get_argument("FormID", "")
        token = self.get_argument("Token")
        sub_system = self.get_argument("subSystem", '')  # 子系统
        third_id = self.get_argument("thPjId", '')  # 投行系统项目ID
        third_type = self.get_argument("xmfl", '')  # 投行系统分类
        redirect_url = self.get_argument("url", "/")
        if token != self.ebscn_token(user_id, user_name, sys_id, proc_id, form_id, public_key=config.get_config("sso.ebscn.key", "")):
            raise HTTPError(403)
        user = self.save_user(user_id, user_id, user_name, _from='ebscn')
        self.session_clear()
        self.session["proxy_user_id"] = str(user.id)
        self.session["user_meta"] = json.dumps({
            "ebscn_sys_id": sys_id,
            "ebscn_proc_id": proc_id,
            "ebscn_form_id": form_id,
        })
        if sub_system and third_id and third_type:
            redirect_url = create_url(redirect_url, None,
                                      ('sub_system', sub_system),
                                      ('third_id', third_id),
                                      ('third_type', third_type))
        self.redirect(redirect_url)


@route(r'/user/sso_login/ebscn_oa')
class EbscnOALoginHandler(EBSCNBaseHandler):
    """光大登录入口 oa, calliper和grater已废弃oa单点接口"""

    def get(self, *args, **kwargs):
        if not self.check_referer():
            raise HTTPError(403)
        user_id = self.get_argument("UserID", "0")
        user_name = self.get_argument("UserName", "")
        token = self.get_argument("Token")
        redirect_url = self.get_argument("url", "/")
        if token != self.ebscn_token(user_id, user_name, public_key=config.get_config("sso.ebscn_oa.key", ""), for_oa=True):
            raise HTTPError(403)
        user = self.save_user(user_id, user_id, user_name, _from='ebscn_oa')
        self.session_clear()
        self.session["proxy_user_id"] = str(user.id)
        self.redirect(redirect_url)

    def check_referer(self):
        allowed_referers = config.get_config("sso.ebscn_oa.allowed_referer", [])
        if not allowed_referers:
            return True

        referer = self.request.headers.get("Referer")
        for allowed_referer in allowed_referers:
            if allowed_referer == "*":
                return True
            elif referer and referer.startswith(allowed_referer):
                return True
        return False


@route(r'/ebscn/entries')
class EbscnEntryHandler(EBSCNBaseHandler):
    """光大环境，各系统入口地址（token 登录对接）"""

    @permission_auth()
    def get(self, *args, **kwargs):
        user = self.current_user
        user_id = user.ext_uname
        user_name = user.user_data.get('username')
        user_meta = json.loads(self.session["user_meta"] or "{}")
        platform = user.user_data.get('_from')
        user_role = 1 if User.P_MANAGE in (user.permissions or []) else 0  # 光大没有用户管理，只有系统管理员
        data = {}
        systems_config = config.get_config('unify_auth.auth_config', {})
        # ebscn_systems = config.get_config('unify_auth.ebscn_systems', [])
        # if isinstance(ebscn_systems, str):
        #     ebscn_systems = json.loads(ebscn_systems)
        for auth_system, config_data in systems_config.items():
            system = auth_system.replace('auth_', '')
            base_url = config_data.get('host', '') or '/'
            subpath = config_data.get('subpath', '')
            auth_api = config_data.get('auth_api')
            # if system in ebscn_systems and platform == 'ebscn_oa':
            #     platform = 'ebscn'
            sub_sys_api = self.gen_redirect_url(auth_api, base_url, subpath)
            sub_sys_url = self.ext_sys_login_url(sub_sys_api, platform, user_id, user_name, user_meta.get("ebscn_sys_id", ""),
                                                 user_meta.get("ebscn_proc_id", ""), user_meta.get("ebscn_form_id", ""), user_role)
            data[system] = encode_url_by_config(system, sub_sys_url, exclude_domain=True)

        return self.data(data)
