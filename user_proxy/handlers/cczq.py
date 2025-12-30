"""
长城单点登录api
"""
# pylint: disable=too-many-locals,too-many-return-statements
import logging
from urllib.parse import urljoin

import requests

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url


@route(r'/cczq/sso-login')
class CCZQSSOLoginHandler(BaseHandler):
    """oauth2授权码模式"""

    @staticmethod
    def build_user_info(res_data):
        return {
            'uid': res_data['empno'],  # 工号
            'ext_uname': res_data['oaname'],  # oa⽤户名
            'username': res_data['name'],  # 姓名
        }

    def get(self, *args, **kwargs):
        access_token = self.get_argument('access_token', None)
        code = self.get_argument('code', None)
        sys = self.get_argument('sys', None)

        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        origin_url = f'{trident_base}/api/v1/cczq/sso-login'
        if sys:
            origin_url = f'{origin_url}?sys={sys}'

        oauth_base = config.get_config('oauth2_auth.base_url')
        client_id = config.get_config('oauth2_auth.client_id')
        client_secret = config.get_config('oauth2_auth.client_secret')
        scope = config.get_config('oauth2_auth.scope')

        headers = {"User-Agent": self.request.headers.get("User-Agent"), 'Content-Type': 'application/x-www-form-urlencoded'}
        if access_token:
            check_access_token_api = config.get_config('oauth2_auth.check_access_token_api')
            check_access_token_url = create_url(oauth_base, check_access_token_api)
            data = {
                'client_id': client_id,
                'client_secret': client_secret,
                'token': access_token,
            }
            logging.info('check_access_token_url: %s, data: %s', check_access_token_url, data)
            try:
                response = requests.post(check_access_token_url, headers=headers, data=data, verify=False)
                res_data = response.json()
                logging.debug('check_access_token_res_data: %s', res_data)
                if response.status_code != 200:
                    return self.error(f'check access_token error, status_code={response.status_code}')
                if res_data.get('error'):
                    return self.error(f'check access_token error, error={res_data["error"]}, error_description={res_data["error_description"]}')
                if not res_data.get('active'):
                    return self.error('access_token is not active')
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')

            user_info_api = config.get_config('oauth2_auth.user_info_api')
            user_info_url = create_url(oauth_base, user_info_api)
            data = {
                "access_token": access_token,
            }
            logging.info('user_info_url: %s, data: %s', user_info_url, data)
            try:
                response = requests.post(user_info_url, headers=headers, data=data, verify=False)
                res_data = response.json()
                if response.status_code != 200:
                    return self.error(f'get user_info error, status_code={response.status_code}')
                if res_data.get('error'):
                    return self.error(f'get user_info error, error={res_data["error"]}, error_description={res_data["error_description"]}')
                user_info = self.build_user_info(res_data)
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')
            user = User.make_user(**user_info)
            if not user:
                return self.error('permission denied')
            self.session['proxy_user_id'] = str(user.id)
            redirect_url = trident_base if not sys else get_off_redirect_url(sys, user, origin_host=self.origin_host)
        elif code:
            access_token_api = config.get_config('oauth2_auth.access_token_api')
            access_token_url = create_url(oauth_base, access_token_api)
            data = {'client_id': client_id, 'client_secret': client_secret, 'redirect_uri': origin_url, 'code': code, 'grant_type': 'authorization_code'}
            logging.info('get_access_token_url: %s, data: %s', access_token_url, data)
            try:
                response = requests.post(access_token_url, headers=headers, data=data, verify=False)
                if response.status_code != 200:
                    return self.error(f'get access_token error, status_code={response.status_code}')
                access_token_info = response.json()
                logging.debug('access_token_info: %s', access_token_info)
                if access_token_info.get('error'):
                    return self.error(f'get access_token error, error={access_token_info["error"]}, error_description={access_token_info["error_description"]}')
                url_args = [('access_token', access_token_info['access_token'])]
                if sys:
                    url_args.append(('sys', sys))
                redirect_url = create_url(trident_base, 'api/v1/cczq/sso-login', *url_args)
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')
        else:
            authorize_api = config.get_config('oauth2_auth.authorize_api')
            url_args = [('client_id', client_id), ('redirect_uri', origin_url), ('response_type', 'code'), ('scope', scope)]
            redirect_url = create_url(oauth_base, authorize_api, *url_args)
        logging.info('redirect to %s', redirect_url)
        return self.redirect(redirect_url)
