"""
东北单点登录api
"""
# pylint:disable=too-many-branches,too-many-return-statements,too-many-locals
import logging
import os
import re
import urllib
from urllib.parse import urljoin

import requests
from aiohttp import ClientSession
from sqlalchemy import or_
from sqlalchemy.orm.attributes import flag_modified
from utensils.auth.token import validate_token_url

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url
from user_proxy.utils.jwt_util import get_user_info

P_OTHER_VALID_DEPT_NAME = re.compile(r'(财务部|证券部)$')


@route(r'/nesc/sso-login')
class NESCSSOLoginHandler(BaseHandler):
    @staticmethod
    def save_user(ext_uname, user_name, custom_system):
        user = User.make_user(uid=ext_uname, ext_uname=ext_uname, username=user_name, _from='nesc', custom_system=custom_system)
        return user

    async def get(self, *args, **kwargs):  # pylint:disable=invalid-overridden-method
        token = self.get_argument('token', None)
        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        custom_system = self.get_argument('custom_system', 'investment')
        oauth_base = config.get_config('nesc_auth.{}_server'.format(custom_system))
        user_info_api = config.get_config('nesc_auth.{}_user_info_api'.format(custom_system))

        if not token:
            return self.error('permission denied', status_code=400)

        user_info_url = create_url(oauth_base, user_info_api, ('token', token))
        logging.info('user_info_url: %s', user_info_url)
        async with ClientSession() as session:
            try:
                response = await session.get(user_info_url)
                res_data = await response.json()
                code = res_data['code']
                msg = res_data['msg']
                if code != 200:
                    return self.error(msg)
                ext_uname = msg['UserAccount']
                user_name = msg['UserName']
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')
        user = self.save_user(ext_uname, user_name, custom_system)
        if not user:
            return self.error('permission denied')
        self.session['proxy_user_id'] = str(user.id)

        redirect_url = trident_base
        app = self.get_argument('app', '')
        # autodoc调用api
        if app == 'autodoc_overall':
            system = self.get_argument('sys', 'autodoc_overall')
            origin = self.get_argument('origin', None)
            redirect_url = get_off_redirect_url(system, user, origin_host=self.origin_host, origin=origin)
            if not redirect_url:
                return self.error('sys: {} not config'.format(system))
        after_login = config.get_config('nesc_auth.after_login')
        return self.redirect(after_login or redirect_url)


@route(r'/nesc/jwt-login')
class NESCJWTLoginHandler(BaseHandler):
    KEY_PATH = os.path.join(config.project_root, config.get_config("jwt_auth.key_path", 'data/keys/cjsc_test_rsa_public_key.json'))
    APP_ID = config.get_config('jwt_auth.app_id')

    def get(self, *args, **kwargs):
        token = self.get_argument('id_token', None)
        base_url = self.origin_host
        target_url = self.get_argument('target_url', None)
        origin = self.get_argument('origin', None)  # autodoc子系统发起的请求
        app = self.get_argument('app', '')
        if token:
            user_info = get_user_info(token, key_data=self.KEY_PATH, audience=self.APP_ID, from_json=True)
            logging.info('login user_info: %s', user_info)
            if not user_info:
                return self.error('decrypt id_token error', status_code=400)
            ext_uname = user_info.get('username')
            if not ext_uname:
                return self.error('invalid username from parse user_info', status_code=400)
            department_name = user_info.get('ouName')
            matched = P_OTHER_VALID_DEPT_NAME.search(department_name or '')
            customer_department = 'cw_zq' if matched else 'th'
            # 客户用户状态校验
            if config.get_config('nesc_auth.check_customer_login') and not matched:
                auth_url = config.get_config("nesc_auth.auth_url")
                if ext_uname == config.get_config('nesc.special_login_id'):
                    ext_uname = 'admin'
                check_url = create_url(auth_url, None, ('loginId', ext_uname))
                try:
                    response = requests.get(check_url)
                    if response.status_code != 200:
                        return self.error('用户状态校验失败', status_code=400)
                    res = response.json()
                    logging.info('auth user state: %s', res['state'])
                    if str(res['isthuser']) != '1':  # 0-非投行用户 1-投行用户
                        return self.error('非投行用户，请联系管理员。', status_code=400)
                    if str(res['state']) == '0':  # 0-账号锁定 1-账号正常
                        return self.redirect('/#/notAllowLoginUser')
                except Exception as e:
                    logging.exception(e)
                    return self.error('permission denied')

            user = User.make_user(
                uid=ext_uname,
                ext_uname=ext_uname,
                department=department_name,
                department_id=user_info.get('ouId'),
                username=user_info.get('name'),
                _from='nesc',
                phone=user_info.get('mobile'),
                email=user_info.get('email'),
                customer_department=customer_department,
            )
            if not user:
                return self.error('permission denied')
            if not user.allow_login:
                return self.redirect('/#/notAllowLoginUser')

            self.session['proxy_user_id'] = str(user.id)
            if target_url:
                main_url, query = urllib.parse.splitquery(target_url)
                params = urllib.parse.parse_qs(query) if query else {}
                if params.get('app'):
                    # 子系统不带token调用api, idaas认证通过后回调
                    redirect_url = get_off_redirect_url(params['app'][0], user, origin_host=self.origin_host, origin=main_url)
                    if not redirect_url:
                        return self.error('sys: {} not config'.format(app))
                else:
                    redirect_url = target_url
            elif app and origin:
                # 子系统带token调用api
                redirect_url = get_off_redirect_url(app, user, origin_host=self.origin_host, origin=origin)
                if not redirect_url:
                    return self.error('sys: {} not config'.format(app))
            else:
                redirect_url = base_url
        else:
            idaas_server = config.get_config('jwt_auth.server')
            idaas_api = config.get_config('jwt_auth.idaas_api')
            enterprise_id = config.get_config('jwt_auth.enterprise_id')
            url_args = [('enterpriseId', enterprise_id)]
            if origin and app:
                # 子系统不带token调用api
                target_url = create_url(origin, None, ('app', app))
                url_args.append(('target_url', target_url))
            redirect_url = create_url(idaas_server, idaas_api, *url_args)
        logging.debug('Redirecting to: %s', redirect_url)
        return self.redirect(redirect_url)


@route(r'/nesc/jwt-logout')
class NESCJWTLogoutHandler(NESCJWTLoginHandler):
    def get(self, *args, **kwargs):
        idaas_server = config.get_config('jwt_auth.server')
        idaas_api = config.get_config('jwt_auth.idaas_api')
        idaas_logout_api = config.get_config('jwt_auth.idaas_logout_api')
        enterprise_id = config.get_config('jwt_auth.enterprise_id')

        # idaas平台主动退出，各个子系统退出, 目前东北采用的链接嵌入式单点，只在idaas做认证，不从idaas首页进入复核系统
        # state = self.get_argument('state', None)
        # if not state:
        #     return self.error('wrong state parameter', status_code=400)
        # user_info = get_user_info(state, key_data=self.KEY_PATH, audience=self.APP_ID, from_json=True)
        # if not user_info:
        #     return self.error('parse state error', status_code=400)

        self.clear_all_cookies()
        self.session_clear()

        redirect_login_url = create_url(idaas_server, idaas_api, ('enterpriseId', enterprise_id))
        redirect_url = create_url(idaas_server, idaas_logout_api, ('redirect_url', redirect_login_url))
        logging.info('Redirecting to: %s', redirect_url)
        return self.redirect(redirect_url)


@route(r'/nesc/user/synchronize')
class NESCUserUpdateHandler(BaseHandler):
    def post(self, *args, **kwargs):
        app_id = config.get_config("nesc_auth.app_id")
        secret_key = config.get_config("nesc_auth.secret_key")
        token_expire = config.get_config("nesc_auth.token_expire", 3600)
        origin_url = self.request.full_url()
        token = self.request.headers.get('token')
        timestamp = self.request.headers.get('timestamp')
        check_url = create_url(origin_url, None, ('_token', token), ('_timestamp', timestamp))
        if not validate_token_url(check_url, app_id=app_id, secret_key=secret_key, token_expire=token_expire):
            return self.error('auth token failed', status_code=400)
        body = self.get_json_body(binary=False)
        is_all_user = body['isAll'] == '1'

        for item in body['data']:
            user = User.make_user(
                item['UserAccount'], item['UserAccount'], username=item['UserName'], _from='nesc', department_id=item['DeptID'], department=item['DeptName']
            )
            if not user.is_sys_admin:
                user.user_data.update({'allow_login': item['State'] == '1'})
                flag_modified(user, 'user_data')

        if is_all_user:
            db_users = db_session.query(User).filter(User.deleted == 0).all()
            sync_user_names = [item['UserAccount'] for item in body['data']]
            # 全量推送时,不在本次推送的数据范围内，需将用户置为锁定状态。
            for db_user in db_users:
                if db_user.oa_user and db_user.ext_uname not in sync_user_names and db_user.user_data.get('customer_department') != 'cw_zq':
                    db_user.user_data['allow_login'] = False
                    flag_modified(db_user, 'user_data')
                    logging.info('set allow_login False for not exist in sync users: ext_uname=%s', db_user.ext_uname)
        db_session.commit()
        return self.data({})


@route(r'/nesc/user-nums')
class NESCUserNumbersHandler(BaseHandler):
    def get(self, *args, **kwargs):
        ext_uname = self.get_argument('ext_uname', '')
        user = db_session.query(User).filter(User.ext_uname == ext_uname).first()
        if not user:
            user_count = 0
        else:
            cond = User.deleted == 0
            if user.user_data.get('customer_department') == 'cw_zq':
                cond &= User.user_data.op('->>')('customer_department') == user.user_data['customer_department']
            else:
                cond &= or_(User.user_data.op('->>')('customer_department') != 'cw_zq', User.user_data.op('->>')('customer_department').is_(None))
            user_count = db_session.query(User.id).filter(cond).count()
        return self.data({"user_count": user_count})
