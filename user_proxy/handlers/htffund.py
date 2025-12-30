# -*-coding:utf-8-*-

import logging

import requests

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url


@route(r'/htffund/auth-token')
class HTFFUNDAuthTokenHandler(BaseHandler):
    """仅用于子系统认证，正常登录还用cas"""

    def get(self, *args, **kwargs):
        user_id = self.get_argument('user_id')
        token = self.get_argument('token')
        origin = self.get_argument('origin')
        app = self.get_argument('app')
        try:
            base_server = config.get_config('cas_token_auth.base_server')
            auth_api = config.get_config('cas_token_auth.auth_api')

            auth_token_url = create_url(
                base_server, auth_api,
                ('token', token),
                ('userId', user_id)

            )
            logging.info('start cas token auth, auth_url: %s', auth_token_url)
            res = requests.get(auth_token_url, verify=False, timeout=5)
            if res.status_code != 200:
                return self.error(f'cas token auth failed, status_code = {res.status_code}')
            auth_data = res.json()
            logging.info('auth token res: %s', auth_data)
            if auth_data['code'] != 200:
                return self.error(f'cas token server auth failed, status_code = {auth_data["code"]}, message: {auth_data["message"]}')
        except Exception as e:
            logging.exception(e)
            return self.error('cas token auth exception')

        user = User.make_user(uid=user_id, ext_uname=user_id, username=user_id, _from='htffund')
        if not user:
            return self.error('permission denied')

        self.session['proxy_user_id'] = str(user.id)
        redirect_url = get_off_redirect_url(app, user, origin_host=self.origin_host, origin=origin)
        if not redirect_url:
            return self.error(f'sys: {app} not config')

        logging.debug(f'Redirecting to: {redirect_url}')
        return self.redirect(redirect_url)
