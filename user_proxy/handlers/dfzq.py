# pylint: disable=too-many-locals,too-many-return-statements
import logging
from urllib.parse import urljoin

import requests

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url


@route(r'/dfzq/sso-login')
class DFZQSSOLoginHandler(BaseHandler):

    @staticmethod
    def build_user_info(res_data):
        return {
            'uid': res_data['useridcode'],
            'ext_uname': res_data['uid'],
            'username': res_data['cn'],
        }

    def get(self, *args, **kwargs):
        code = self.get_argument('code', None)
        sys = self.get_argument('sys', None)

        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        origin_url = f'{trident_base}/api/v1/dfzq/sso-login'
        if sys:
            origin_url = f'{origin_url}?sys={sys}'

        oauth_base = config.get_config('oauth2_auth.base_url')
        init_service = config.get_config('oauth2_auth.init_service')
        client_id = config.get_config('oauth2_auth.client_id')
        client_secret = config.get_config('oauth2_auth.client_secret')
        scope = config.get_config('oauth2_auth.scope')
        login_page = config.get_config('oauth2_auth.login_page')

        headers = {"User-Agent": self.request.headers.get("User-Agent")}
        if code:
            access_token_api = config.get_config('oauth2_auth.access_token_api')
            url_args = [
                ('client_id', client_id),
                ('redirect_uri', origin_url),
                ('client_secret', client_secret),
                ('grant_type', 'authorization_code'),
                ('code', code),
            ]
            access_token_url = create_url(oauth_base, access_token_api, *url_args)
            access_token_url += f'&scope={scope}'
            logging.info('get_access_token_url: %s', access_token_url)
            try:
                response = requests.post(access_token_url, headers=headers, verify=False, timeout=3)
                if response.status_code != 200:
                    return self.error(f'get access_token error, status_code={response.status_code}')
                access_token_info = response.json()
                logging.info('access_token_info: %s', access_token_info)

                user_info_api = config.get_config('oauth2_auth.user_info_api')
                user_info_url = create_url(oauth_base, user_info_api, ('access_token', access_token_info['access_token']))
                logging.info('user_info_url: %s', user_info_url)
                response = requests.get(user_info_url, headers=headers, verify=False, timeout=3)
                res_data = response.json()
                if response.status_code != 200:
                    return self.error(f'get user_info error, status_code={response.status_code}')
                logging.info('user_info: %s', res_data)
                user_info = self.build_user_info(res_data)
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')
            user = User.make_user(**user_info)
            if not user:
                return self.error('permission denied')
            self.session['proxy_user_id'] = str(user.id)
            redirect_url = trident_base if not sys else get_off_redirect_url(sys, user, origin_host=self.origin_host)
        else:
            authorize_api = config.get_config('oauth2_auth.authorize_api')
            url_args = [
                ('service', init_service),
                ('response_type', 'code'),
                ('client_id', client_id),
                ('redirect_uri', origin_url),
                ('login_page', login_page),
                ('decision', 'Allow'),
            ]
            redirect_url = create_url(oauth_base, authorize_api, *url_args)
            redirect_url += f'&scope={scope}'
        logging.info('redirect to %s', redirect_url)
        return self.redirect(redirect_url)
