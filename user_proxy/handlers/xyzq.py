# pylint: disable=too-many-return-statements
import logging
import random
from string import Template
from urllib.parse import urljoin

import requests
from sqlalchemy.orm.attributes import flag_modified

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.db import db_session
from user_proxy.handlers.base import BaseHandler, route
from user_proxy.models.user import User


@route(r'/sso/login')
class XySsoLoginHandler(BaseHandler):
    ERROR_MSG_INVALID_TOKEN = u'令牌无效，请尝试重新登录'
    ERROR_MSG_NOT_SYNCED = u'该用户信息未同步，请联系管理员'
    ERROR_MSG_INVALID_ORGANIZATION = u'部门权限不足，无法访问该页面'

    # VALID_ORGANIZATION_IDS = config.get_config('xyzq_auth.organization_ids', [])

    def send_html_string(self, html_str, status_code=400):
        self.set_header("Content-Type", 'text/html')
        self.set_status(status_code)
        self.write(html_str)

    def get(self, *args, **kwargs):
        # sys_ = self.get_argument('sys', 'autodoc_overall')
        type_ = self.get_argument('type', '')
        if type_ not in ('ehome', 'ib'):
            return self.error('invalid type', status_code=400)

        if type_ == 'ehome':
            token = self.get_argument('token', '')
            if not token:
                return self.error('token required', status_code=400)
            params = {'token': token}
        else:
            nonce = self.get_argument('nonce', '')
            sign = self.get_argument('sign', '')
            if not all((nonce, sign)):
                return self.error('nonce and sign required', status_code=400)
            params = {'nonce': nonce, 'sign': sign}
        validate_ok, data = self.validate_sso(type_, params)

        if not validate_ok:
            return self.send_html_string(self.build_error_page(self.ERROR_MSG_INVALID_TOKEN))

        login_id = data['login_id']
        username = data['username']
        organization_id = data['organization_id']
        organization_name = data['organization_name']

        # if int(organization_id) not in self.VALID_ORGANIZATION_IDS:
        #     return self.send_html_string(self.build_error_page(self.ERROR_MSG_INVALID_ORGANIZATION))

        user = User.make_user(login_id, login_id, department=organization_name, department_id=organization_id, username=username, _from='xyzq')
        self.session['proxy_user_id'] = str(user.id)
        # redirect_url = urljoin(urljoin(self.origin_host, config.get_config('webif.redirect_subpath', '')), config.get_config('xyzq_auth.after_login', 'api/v1/get-off'))
        # redirect_url = create_url(redirect_url, None, *[('sys', sys_)])
        after_login = config.get_config('xyzq_auth.after_login')
        return self.redirect(after_login or '/')

    @classmethod
    def xy_ehome_sso_verify(cls, params):
        """兴业证券e家sso验证"""
        url = config.get_config('xyzq_auth.ehome_sso_verify.url')
        params = {'oaToken': params.get('token', ''), 'from': 'ehomessomain', 'rand': random.random()}
        return cls.sso_verify(params, url)

    @staticmethod
    def sso_verify(params, url):
        response = requests.get(url, params=params, verify=False)
        json_body = response.json()
        success = json_body['resphead']['success']
        if not success:
            return False, json_body['resphead']['msg']
        data = json_body['respbody']['data']
        return True, {
            'login_id': data['loginId'],
            'username': data['userName'],
            'organization_id': data['organizationId'],
            'organization_name': data['organizationName'],
        }

    @staticmethod
    def xy_ib_sso_verify(params):
        """兴业证券大投行sso验证"""
        url = config.get_config('xyzq_auth.ib_sso_verify.url')
        params = {'nonce': params.get('nonce', ''), 'sign': params.get('sign', '')}
        response = requests.get(url, params=params)
        json_body = response.json()
        success = json_body['succeed']
        if not success:
            return False, json_body['msg']
        return True, {'login_id': json_body['loginid'], 'username': json_body['username'], 'organization_id': None, 'organization_name': None}

    def validate_sso(self, type_, params):
        handler = {'ehome': self.xy_ehome_sso_verify, 'ib': self.xy_ib_sso_verify}
        return handler[type_](params)

    @staticmethod
    def build_error_page(msg):
        html = '''
        <!doctype html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, user-scalable=no, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0">
            <meta http-equiv="X-UA-Compatible" content="ie=edge">
            <title>认证失败</title>
            <style>
                .card {
                    width: 400px;
                    height: 240px;
                    border: 1px solid #cccccc;
                    position: absolute;
                    left: 50%;
                    top: 50%;
                    margin: -120px 0 0 -200px;
                }
                .card-body{
                    margin: 20px;
                }
                h4 {
                    text-align: center;
                }
            </style>
        </head>
        <body>
        <div class="card">
            <div class="card-header"><h4>认证失败</h4></div>
            <hr>
            <div class="card-body" style="text-align: center;padding: 20px;">$msg</div>
        </div>
        </body>
        </html>
        '''
        template = Template(html).substitute(msg=msg)
        return template


@route(r'/xyzq/sso-login')
class XYZQSSOLoginHandler(XySsoLoginHandler):
    ERROR_MSG_USER_INVALIDATION = '该用户已失效，请联系管理员'

    def get(self, *args, **kwargs):
        source = self.get_argument('source', 'OA')
        token = self.get_argument('oa_token', '')

        if source not in ('gipms', 'OA'):
            return self.error('invalid source')
        if not token:
            return self.error('oa_token required')

        if source == 'gipms':
            url = config.get_config('xyzq_auth_1.gipms_sso_verify.url')
        else:
            url = config.get_config('xyzq_auth_1.oa_sso_verify.url')
        params = {'oa_token': token, 'from': config.get_config('xyzq_auth_1.auth_from'), 'rand': random.random()}

        validate_ok, data = self.sso_verify(params, url)
        if not validate_ok:
            return self.send_html_string(self.build_error_page(self.ERROR_MSG_INVALID_TOKEN))

        logging.debug(
            'get user_info: login_id: %s, username: %s, organization_id: %s, organization_name: %s',
            data['login_id'],
            data['username'],
            data['organization_id'],
            data['organization_name'],
        )
        user = db_session.query(User).filter(User.ext_uname == data['login_id']).first()
        if not user:
            return self.send_html_string(self.build_error_page(self.ERROR_MSG_NOT_SYNCED))
        if user.deleted == 1 or user.user_data.get('status') != User.XYZQ_STATUS_VALIDATION:
            return self.send_html_string(self.build_error_page(self.ERROR_MSG_USER_INVALIDATION))

        user.user_data.update(
            {
                "department_id": data['organization_id'],
                "department": data['organization_name'],
            }
        )
        flag_modified(user, 'user_data')
        db_session.commit()

        self.session['proxy_user_id'] = str(user.id)
        redirect_url = '/'
        if self.get_argument('redirect', '') == 'true' and (redirect_path := self.get_argument('redirectPath', '')):
            logging.info('redirect_path: %s', redirect_path)
            subpath = config.get_config("webif.redirect_subpath", '')
            base_url = urljoin(self.origin_host, subpath.strip('/'))
            origin = urljoin(f'{base_url}/', redirect_path.lstrip('/'))
            # 客户已规定参数，跳转sys只能从redirect_path中获取，新增子系统配置的redirect_path和各个子系统的subpath必须跟trident子系统简称保持一致, autodoc走的/sso/login接口，不影响
            system = redirect_path.lstrip('/').split('/', 1)[0]
            logging.info('redirect to sys: %s', system)
            redirect_url = get_off_redirect_url(system, user, origin=origin)
            if not redirect_url:
                return self.error('sys: {} not config'.format(system))
        return self.redirect(redirect_url)
