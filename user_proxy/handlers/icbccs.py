"""
工银瑞信单点登录api
"""
# pylint: disable=too-many-locals, too-many-return-statements
import json
import logging

from urllib.parse import urljoin

from aiohttp import ClientSession
from sqlalchemy.orm.attributes import flag_modified

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User, VisitRecord, VisitSys
from user_proxy.utils.cas import create_url
from user_proxy.utils.sm4_util import SM4Util


@route(r'/icbccs/sso-login')
class ICBCCsSSOLoginHandler(BaseHandler):
    """oauth2密码模式"""

    @staticmethod
    def save_user(user_info, oa_dept_info):
        permission_contrast = config.get_config('icbccs_auth.permission_contrast', {})
        customer_permissions = []
        for permission in user_info['authorities'] or []:
            if permission_contrast.get(permission):
                customer_permissions.append(permission_contrast[permission])
            else:
                customer_permissions.append(permission)

        user = User.make_user(
            uid=user_info['userId'],
            ext_uname=user_info["user_name"],
            username=user_info["realName"],
            _from='icbccs',
            email=user_info['oaEmail'],
            customer_permissions=customer_permissions,
            oa_dept_list=oa_dept_info,
        )
        if not customer_permissions:
            user.user_data['customer_permissions'] = []
            flag_modified(user, 'user_data')
            db_session.commit()
        return user

    @staticmethod
    async def get_access_token(url):
        async with ClientSession() as session:
            try:
                res = await session.get(url)
            except Exception as e:
                logging.exception(e)
                return False, 'permission denied'

            try:
                token_data = await res.text()
                token_data = json.loads(token_data)
            except Exception as e:
                logging.error('headers: %s', res.headers)
                logging.error('body: %s', res.text)
                logging.exception(e)
                return False, 'permission denied'
            if token_data.get('error'):
                return False, token_data.get('error_description', '')
            logging.info('token_data: %s', token_data)
            return True, token_data

    @staticmethod
    async def get_user_info(token_type, access_token):
        user_info_url = config.get_config('icbccs_auth.user_info_url')
        user_info_api = config.get_config('icbccs_auth.user_info_api')
        get_user_info_url = create_url(
            user_info_url,
            user_info_api,
            ('token', access_token),
        )
        auth_string = f'{token_type}{access_token}'
        logging.info('get_user_info_url:%s, auth_string: %s', get_user_info_url, auth_string)
        async with ClientSession() as session:
            try:
                response = await session.get(get_user_info_url, headers={"Authorization": auth_string})
                res_data = await response.json()
                error = res_data.get('error')
                if error:
                    return False, res_data.get('error_description')
            except Exception as e:
                logging.exception(e)
                return False, 'permission denied'
            logging.info('user_info: %s', res_data)
            return True, res_data

    @staticmethod
    async def get_dept_info(token_type, access_token, user_id):
        dept_info_url = config.get_config('icbccs_auth.dept_info_url')
        dept_info_api = config.get_config('icbccs_auth.dept_info_api')
        get_dept_info_url = create_url(
            dept_info_url,
            dept_info_api,
            ('userId', user_id),
        )
        auth_string = f'{token_type}{access_token}'
        logging.info('get_dept_info_url:%s, auth_string: %s', get_dept_info_url, auth_string)
        async with ClientSession() as session:
            try:
                response = await session.post(get_dept_info_url, headers={"Authorization": auth_string})
                if response.status != 200:
                    logging.error('获取部门信息失败: http_code=%s', response.status)
                    return False, '获取部门信息失败'
                res_data = await response.json()
                oa_dept_info = []
                for item in res_data:
                    for dept_data in item['oaDeptList']:
                        if dept_data in oa_dept_info:
                            continue
                        oa_dept_info.append(dept_data)
            except Exception as e:
                logging.exception(e)
                return False, 'permission denied'
            logging.info('oa_dept_info: %s', oa_dept_info)
            return True, oa_dept_info

    async def post(self, *args, **kwargs):  # pylint: disable=invalid-overridden-method
        body = self.get_json_body(binary=False)
        username = body.get('username')
        password = body.get('password')
        if not username or not password:
            return self.error('parameter error', status_code=400)
        after_login = config.get_config('icbccs_auth.after_login', '')
        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        access_token_url = config.get_config('icbccs_auth.access_token_url')
        client_id = config.get_config('icbccs_auth.client_id')
        client_secret = config.get_config('icbccs_auth.client_secret')
        # 获取access_token
        access_token_api = config.get_config('icbccs_auth.access_token_api')
        get_token_url = create_url(
            access_token_url,
            access_token_api,
            ('client_id', client_id),
            ('client_secret', client_secret),
            ('username', username),
            ('password', password),
        )
        logging.info('get_token_url:%s', get_token_url)
        flag, info = await self.get_access_token(get_token_url)
        if not flag:
            return self.error(info, status_code=400)
        access_token = info.get('access_token')
        token_type = info.get('token_type')
        refresh_token = info.get('refresh_token')

        # 获取用户信息
        flag, user_info = await self.get_user_info(token_type, access_token)
        if not flag:
            if user_info == 'permission denied':
                return self.error('permission denied', status_code=400)
            else:
                # 刷新access_token
                refresh_token_url = create_url(
                    access_token_url,
                    access_token_api,
                    ('client_id', client_id),
                    ('client_secret', client_secret),
                    ('refresh_token', refresh_token),
                    ('grant_type', "refresh_token"),
                )
                logging.info('refresh_token_url:%s', refresh_token_url)
                flag, info = await self.get_access_token(get_token_url)
                if not flag:
                    return self.error(info, status_code=400)
                access_token = info.get('access_token')
                token_type = info.get('token_type')

                # 刷新token后再次获取用户信息
                flag, user_info = self.get_user_info(token_type, access_token)
                if not flag:
                    return self.error(user_info, status_code=400)

        # 获取团队信息，scriberKV使用
        flag, oa_dept_info = await self.get_dept_info(token_type, access_token, user_info['userId'])
        if not flag:
            return self.error(oa_dept_info, status_code=400)
        user = self.save_user(user_info, oa_dept_info)
        if not user:
            return self.error('permission denied')
        self.session['proxy_user_id'] = str(user.id)
        remote_ip = self.request.headers.get("X-Real-IP") or self.request.remote_ip
        logging.info('ip_address: %s', remote_ip)
        VisitRecord.create(user.id, VisitSys.TRIDENT.value, ip_address=remote_ip)
        redirect_url = urljoin(trident_base, after_login)
        return self.data({'redirect_url': redirect_url})


@route(r'/icbccs/user-login')
class ICBCCSUserLoginHandler(ICBCCsSSOLoginHandler):
    @staticmethod
    def get_decrypt_data(encrypt_token):
        secret_key = config.get_config('icbccs_auth.secret_key')
        sm4_ins = SM4Util()
        decrypt_data = sm4_ins.decrypt_sm4(secret_key, encrypt_token, mode='ECB')
        logging.info('decrypt_data: %s', decrypt_data)
        return decrypt_data

    def get(self, *args, **kwargs):
        app = self.get_argument('app', '')
        client_ip = self.get_argument('clientIp')
        remote_ip = self.request.headers.get("X-Real-IP") or self.request.remote_ip
        logging.info('ip_address: %s', remote_ip)
        if config.get_config('unify_auth.check_client_ip') and remote_ip != client_ip:
            return self.error('ip auth check failed', status_code=400)

        user_token = self.get_argument('secretUserInfo')
        dept_token = self.get_argument('secretDeptInfo')
        user_info = json.loads(self.get_decrypt_data(user_token))
        dept_info = json.loads(self.get_decrypt_data(dept_token))
        if app and app not in user_info['authorities']:
            return self.error('您不具备该子系统访问权', status_code=400)
        user = self.save_user(user_info, dept_info['oaDeptList'])
        self.session['proxy_user_id'] = str(user.id)
        VisitRecord.create(user.id, VisitSys.TRIDENT.value, ip_address=remote_ip)
        url = '/'
        permission_contrast = config.get_config('icbccs_auth.permission_contrast', {})
        if app and (sys := permission_contrast.get(app)):
            url = get_off_redirect_url(sys, user, origin_host=self.origin_host)
            if not url:
                return self.error('sys: {} not config'.format(sys))
        return self.redirect(url)
